"""
Point of sale services.

Lock order, the same as everywhere: CashSession → Approval → DocumentSequence → SkuCost →
StockLevel (inside post_entry) → StoreCredit. Every write that touches the till starts by
locking its session, which also serializes a cashier's retried requests.
"""

import secrets
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Sum
from django.utils import timezone

from accounts.capabilities import Capability, can
from accounts.models import Approval, User
from accounts.services import consume_approval
from audit.services import record
from catalog.models import ProductVariant
from catalog.services import current_price
from common.errors import ConflictError, DomainError
from locations.models import Location
from stock.models import StockEntry
from stock.services import Outflow, post_entry

from .models import (
    ZERO,
    CashMovement,
    CashRegister,
    CashSession,
    Customer,
    DocumentSequence,
    Payment,
    Sale,
    SaleItem,
    StoreCredit,
    StoreCreditEntry,
)

CENT = Decimal("0.01")
CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # no 0/O, 1/I: read aloud at the counter


def cents(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


# ─── Cash sessions ─────────────────────────────────────────────────────────────


def open_session(*, user: User, register: CashRegister, opening_float: Decimal) -> CashSession:
    if not can(user, Capability.POS_CASH, register.location):
        raise DomainError("Você não opera caixa nesta loja.", "pos_not_allowed")
    if not register.is_active:
        raise DomainError("Este caixa está desativado.", "register_inactive")
    if opening_float < 0:
        raise DomainError("O troco inicial não pode ser negativo.", "float_negative")
    try:
        with transaction.atomic():
            return CashSession.objects.create(register=register, opened_by=user, opening_float=cents(opening_float))
    except IntegrityError as error:
        mine = CashSession.objects.filter(opened_by=user, closed_at__isnull=True).exists()
        message = "Você já tem um caixa aberto." if mine else "Este caixa já está aberto por outra pessoa."
        raise ConflictError(message, "session_already_open") from error


def open_session_of(user: User, *, lock: bool = False) -> CashSession:
    sessions = CashSession.objects.select_related("register__location").filter(opened_by=user, closed_at__isnull=True)
    if lock:
        sessions = sessions.select_for_update(of=("self",))
    session = sessions.first()
    if session is None:
        raise ConflictError("Abra o caixa antes de vender.", "session_not_open")
    return session


def _locked_open(session: CashSession) -> CashSession:
    locked = CashSession.objects.select_for_update(of=("self",)).select_related("register__location").get(pk=session.pk)
    if not locked.is_open:
        raise ConflictError("Este caixa já foi fechado.", "session_closed")
    return locked


def _may_operate(user: User, session: CashSession) -> bool:
    """The session's own cashier, or a manager of the store."""
    location = session.register.location
    return session.opened_by_id == user.pk or can(user, Capability.APPROVALS_GRANT, location)


def expected_cash(session: CashSession) -> Decimal:
    """Float + cash sales - change already given (amount is net of it) + top-ups - withdrawals - refunds."""
    cash_sales = (
        Payment.objects.filter(
            sale__session=session, sale__status=Sale.Status.COMPLETED, method=Payment.Method.CASH
        ).aggregate(total=Sum("amount"))["total"]
        or ZERO
    )
    moves = {
        row["kind"]: row["total"]
        for row in CashMovement.objects.filter(session=session).values("kind").annotate(total=Sum("amount"))
    }
    K = CashMovement.Kind
    return cents(
        session.opening_float
        + cash_sales
        + moves.get(K.SUPPLY, ZERO)
        - moves.get(K.WITHDRAWAL, ZERO)
        - moves.get(K.REFUND, ZERO)
    )


@transaction.atomic
def move_cash(
    *, user: User, session: CashSession, kind: CashMovement.Kind, amount: Decimal, reason: str
) -> CashMovement:
    session = _locked_open(session)
    if not _may_operate(user, session):
        raise DomainError("Só o operador deste caixa (ou o gerente) movimenta o dinheiro.", "session_not_yours")
    if kind == CashMovement.Kind.REFUND:
        raise DomainError("Devoluções em dinheiro são lançadas pela devolução.", "cash_refund_direct")
    if amount <= 0:
        raise DomainError("Informe um valor maior que zero.", "amount_not_positive")
    if kind == CashMovement.Kind.WITHDRAWAL and amount > expected_cash(session):
        raise ConflictError("A sangria é maior que o dinheiro na gaveta.", "withdrawal_exceeds_drawer")
    movement = CashMovement.objects.create(
        session=session, kind=kind, amount=cents(amount), reason=reason, created_by=user
    )
    record(
        actor=user,
        action=f"cash.{kind}",
        location=session.register.location,
        target=movement,
        data={"amount": str(movement.amount), "reason": reason},
    )
    return movement


def session_summary(session: CashSession) -> dict[str, object]:
    by_method = {
        row["method"]: str(row["total"])
        for row in Payment.objects.filter(sale__session=session, sale__status=Sale.Status.COMPLETED)
        .values("method")
        .annotate(total=Sum("amount"))
    }
    sales = Sale.objects.filter(session=session)
    moves = {
        row["kind"]: str(row["total"])
        for row in CashMovement.objects.filter(session=session).values("kind").annotate(total=Sum("amount"))
    }
    expected = session.expected_cash if session.closed_at else expected_cash(session)
    return {
        "opening_float": str(session.opening_float),
        "sales": sales.filter(status=Sale.Status.COMPLETED).count(),
        "cancelled_sales": sales.filter(status=Sale.Status.CANCELLED).count(),
        "by_method": by_method,
        "movements": moves,
        "expected_cash": str(expected),
        "counted_cash": str(session.counted_cash) if session.counted_cash is not None else None,
        "difference": str(session.counted_cash - expected)
        if session.counted_cash is not None and expected is not None
        else None,
    }


@transaction.atomic
def close_session(*, user: User, session: CashSession, counted_cash: Decimal, note: str = "") -> CashSession:
    session = _locked_open(session)
    if not _may_operate(user, session):
        raise DomainError("Só o operador deste caixa (ou o gerente) o fecha.", "session_not_yours")
    if counted_cash < 0:
        raise DomainError("O valor contado não pode ser negativo.", "counted_negative")
    session.expected_cash = expected_cash(session)
    session.counted_cash = cents(counted_cash)
    session.closed_by, session.closed_at, session.closing_note = user, timezone.now(), note
    session.save(update_fields=["expected_cash", "counted_cash", "closed_by", "closed_at", "closing_note"])
    difference = session.counted_cash - session.expected_cash
    if difference:
        record(
            actor=user,
            action="cash.difference",
            location=session.register.location,
            target=session,
            data={
                "expected": str(session.expected_cash),
                "counted": str(session.counted_cash),
                "difference": str(difference),
                "note": note,
            },
        )
    return session


# ─── Sales ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ItemInput:
    variant: ProductVariant
    quantity: int
    discount: Decimal = ZERO  # line discount, in money


@dataclass(frozen=True)
class PaymentInput:
    method: Payment.Method
    amount: Decimal
    tendered: Decimal | None = None
    installments: int | None = None
    card_brand: str = ""
    nsu: str = ""
    store_credit_code: str = ""


@dataclass
class _Line:
    item: ItemInput
    unit_price: Decimal
    gross: Decimal
    discount: Decimal = field(default=ZERO)


def _next_number(location: Location, doc_type: str) -> int:
    DocumentSequence.objects.bulk_create(
        [DocumentSequence(location=location, doc_type=doc_type)], ignore_conflicts=True
    )
    sequence = DocumentSequence.objects.select_for_update().get(location=location, doc_type=doc_type)
    number = sequence.next_value
    sequence.next_value += 1
    sequence.save(update_fields=["next_value"])
    return number


def _distribute(lines: list[_Line], sale_discount: Decimal) -> None:
    """
    Spreads the sale-level discount over the lines in proportion to what is left of each, so
    every line knows what the customer actually paid for it (partial returns depend on it).
    The cents lost to rounding go to the largest line.
    """
    base = sum((line.gross - line.discount for line in lines), ZERO)
    if sale_discount <= 0 or base <= 0:
        return
    shares = [cents(sale_discount * (line.gross - line.discount) / base) for line in lines]
    shares[max(range(len(lines)), key=lambda i: lines[i].gross - lines[i].discount)] += sale_discount - sum(
        shares, ZERO
    )
    for line, share in zip(lines, shares, strict=True):
        line.discount += share


def _price(items: list[ItemInput]) -> list[_Line]:
    if not items:
        raise DomainError("A venda precisa de pelo menos um item.", "sale_empty")
    if len({item.variant.pk for item in items}) != len(items):
        raise DomainError("SKU repetido: some as quantidades na mesma linha.", "sale_duplicate_sku")
    lines: list[_Line] = []
    for item in items:
        if item.quantity <= 0:
            raise DomainError("Quantidade precisa ser maior que zero.", "quantity_not_positive")
        if not item.variant.is_active:
            raise DomainError(f"{item.variant.sku} está desativado.", "variant_inactive")
        price = current_price(item.variant)
        if price is None:
            raise DomainError(f"{item.variant.sku} está sem preço.", "variant_without_price")
        gross = cents(price * item.quantity)
        discount = cents(item.discount)
        if not ZERO <= discount <= gross:
            raise DomainError(f"Desconto inválido em {item.variant.sku}.", "line_discount_invalid")
        lines.append(_Line(item=item, unit_price=price, gross=gross, discount=discount))
    return lines


def _check_payments(payments: list[PaymentInput], total: Decimal) -> None:
    paid = sum((cents(p.amount) for p in payments), ZERO)
    if paid != total:
        raise DomainError(f"Pagamentos somam {paid}, a venda é {total}.", "payments_do_not_match")
    for payment in payments:
        if payment.amount <= 0:
            raise DomainError("Cada pagamento precisa ser maior que zero.", "payment_not_positive")
        if payment.method == Payment.Method.CASH and (payment.tendered is None or payment.tendered < payment.amount):
            raise DomainError("Informe o valor entregue em dinheiro.", "cash_tendered_missing")
        if payment.method == Payment.Method.CREDIT and not (payment.installments and 1 <= payment.installments <= 12):
            raise DomainError("Crédito: de 1 a 12 parcelas.", "installments_invalid")
        if payment.method == Payment.Method.STORE_CREDIT and not payment.store_credit_code:
            raise DomainError("Informe o código do vale-troca.", "store_credit_code_missing")


def redeem_credit(*, user: User, code: str, amount: Decimal, source_ref: str) -> StoreCredit:
    """Spends a credit under its row lock: two tills can't spend the same balance twice."""
    credit = StoreCredit.objects.select_for_update().filter(code=code.strip().upper()).first()
    if credit is None:
        raise DomainError("Vale-troca não encontrado.", "store_credit_not_found")
    if credit.expires_on and credit.expires_on < timezone.localdate():
        raise ConflictError("Este vale-troca venceu.", "store_credit_expired")
    if credit.balance < amount:
        raise ConflictError(f"Saldo do vale-troca: {credit.balance}.", "store_credit_insufficient")
    credit.balance -= amount
    credit.save(update_fields=["balance"])
    StoreCreditEntry.objects.create(
        credit=credit, kind=StoreCreditEntry.Kind.REDEEM, amount=-amount, source_ref=source_ref, created_by=user
    )
    return credit


def issue_credit(
    *, user: User, location: Location, amount: Decimal, source_ref: str, customer: Customer | None
) -> StoreCredit:
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(10))  # 32^10: collisions are not a concern
    credit = StoreCredit.objects.create(code=code, customer=customer, issued_at_location=location, balance=amount)
    StoreCreditEntry.objects.create(
        credit=credit, kind=StoreCreditEntry.Kind.ISSUE, amount=amount, source_ref=source_ref, created_by=user
    )
    return credit


@transaction.atomic
def create_sale(
    *,
    user: User,
    client_request_id: UUID,
    items: list[ItemInput],
    payments: list[PaymentInput],
    discount: Decimal = ZERO,
    customer: Customer | None = None,
    salesperson: User | None = None,
    approval_id: int | None = None,
) -> tuple[Sale, bool]:
    """Returns the sale and whether it was created now (False: a retry of one already made)."""
    session = open_session_of(user, lock=True)
    location = session.register.location
    if not can(user, Capability.POS_SELL, location):
        raise DomainError("Você não vende nesta loja.", "pos_not_allowed")
    existing = Sale.objects.filter(client_request_id=client_request_id).first()
    if existing is not None:
        if existing.session_id != session.pk:
            raise ConflictError("Este identificador de venda já foi usado em outro caixa.", "sale_request_reused")
        return existing, False
    if salesperson is not None and not salesperson.locations.filter(pk=location.pk).exists():
        raise DomainError("O vendedor não é desta loja.", "salesperson_not_here")

    lines = _price(items)
    subtotal = sum((line.gross for line in lines), ZERO)
    _distribute(lines, cents(discount))
    discount_total = sum((line.discount for line in lines), ZERO)
    if discount_total > subtotal or cents(discount) < 0:
        raise DomainError("Desconto maior que a venda.", "discount_invalid")
    total = subtotal - discount_total

    approval: Approval | None = None
    percent = (discount_total * 100 / subtotal) if subtotal else ZERO
    if percent > settings.POS_CASHIER_MAX_DISCOUNT_PERCENT and not can(user, Capability.APPROVALS_GRANT, location):
        if approval_id is None:
            raise DomainError(
                f"Desconto de {percent:.1f}% precisa de aprovação do gerente.",
                "discount_needs_approval",
                percent=f"{percent:.2f}",
            )
        approval = consume_approval(
            approval_id=approval_id, requester=user, action=Approval.Action.DISCOUNT, location=location, used_by="sale"
        )
        if approval.limit is not None and percent > approval.limit:
            raise DomainError(f"A aprovação cobre até {approval.limit}%.", "discount_above_approval")

    _check_payments(payments, total)
    number = _next_number(location, "sale")
    entry = post_entry(
        kind=StockEntry.Kind.SALE,
        operations=[Outflow(line.item.variant.pk, location.pk, line.item.quantity) for line in lines],
        user=user,
        source_ref=f"sale:{location.code}-{number}",
    )
    cost_by_variant = {m.variant_id: -m.value_delta for m in entry.movements.all()}
    sale = Sale.objects.create(
        location=location,
        number=number,
        session=session,
        client_request_id=client_request_id,
        cashier=user,
        salesperson=salesperson,
        customer=customer,
        subtotal=subtotal,
        discount_total=discount_total,
        total=total,
        approval=approval,
        stock_entry=entry,
    )
    SaleItem.objects.bulk_create(
        SaleItem(
            sale=sale,
            variant=line.item.variant,
            quantity=line.item.quantity,
            unit_price=line.unit_price,
            discount=line.discount,
            net_amount=line.gross - line.discount,
            cost_value=cost_by_variant[line.item.variant.pk],
        )
        for line in lines
    )
    for payment in payments:
        credit = None
        if payment.method == Payment.Method.STORE_CREDIT:
            credit = redeem_credit(
                user=user, code=payment.store_credit_code, amount=cents(payment.amount), source_ref=f"sale:{sale.pk}"
            )
        Payment.objects.create(
            sale=sale,
            method=payment.method,
            amount=cents(payment.amount),
            tendered=cents(payment.tendered) if payment.tendered is not None else None,
            change=cents(payment.tendered - payment.amount) if payment.tendered is not None else None,
            installments=payment.installments,
            card_brand=payment.card_brand,
            nsu=payment.nsu,
            store_credit=credit,
        )
    if approval is not None:
        Approval.objects.filter(pk=approval.pk).update(consumed_by_ref=f"sale:{sale.pk}")
        record(
            actor=user,
            action="sale.discount_approved",
            location=location,
            target=sale,
            data={"percent": f"{percent:.2f}", "approved_by": approval.approver_id, "total": str(total)},
        )
    return sale, True
