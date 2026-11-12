"""
Purchasing. Receipts lock their order row first (then post_entry locks SKU costs and stock
levels), so two people receiving the same order queue up instead of both receiving the
last pending pieces.
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import F, Max, Sum
from django.utils import timezone

from accounts.capabilities import Capability, can
from accounts.models import User
from audit.services import record
from catalog.models import ProductVariant
from common.errors import ConflictError, DomainError
from locations.models import Location
from stock.models import StockEntry, StockLevel, StockMovement
from stock.services import Inflow, Outflow, ReverseInflow, post_entry

from .models import GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine, PurchaseReturn, Supplier

Status = PurchaseOrder.Status


@dataclass(frozen=True)
class OrderLineInput:
    variant: ProductVariant
    quantity: int
    unit_cost: Decimal


@dataclass(frozen=True)
class ReceiptLineInput:
    order_line_id: int
    quantity: int
    unit_cost: Decimal | None = None  # None: the order's cost


def _require(user: User, capability: Capability, location: Location) -> None:
    if not can(user, capability, location):
        raise DomainError("Você não tem permissão para esta loja.", "location_not_allowed")


def _check_lines(lines: list[OrderLineInput]) -> None:
    if not lines:
        raise DomainError("O pedido precisa de pelo menos um item.", "order_empty")
    if len({line.variant.pk for line in lines}) != len(lines):
        raise DomainError("SKU repetido no pedido.", "order_duplicate_sku")
    for line in lines:
        if line.quantity <= 0 or line.unit_cost < 0:
            raise DomainError("Quantidade e custo precisam ser positivos.", "order_line_invalid")


def next_order_number() -> str:
    with connection.cursor() as cursor:
        cursor.execute("select nextval('purchasing_order_number_seq')")
        (serial,) = cursor.fetchone()
    return f"PC-{serial:06d}"


def _locked(order: PurchaseOrder) -> PurchaseOrder:
    return PurchaseOrder.objects.select_for_update(of=("self",)).get(pk=order.pk)


# ─── Orders ────────────────────────────────────────────────────────────────────


@transaction.atomic
def create_order(
    *,
    user: User,
    supplier: Supplier,
    location: Location,
    lines: list[OrderLineInput],
    expected_on: date | None = None,
    notes: str = "",
) -> PurchaseOrder:
    _require(user, Capability.PURCHASING_MANAGE, location)
    if not location.is_physical:
        raise DomainError("O pedido é entregue numa loja ou depósito.", "location_not_physical")
    if not supplier.is_active:
        raise DomainError("Fornecedor inativo.", "supplier_inactive")
    _check_lines(lines)
    order = PurchaseOrder.objects.create(
        number=next_order_number(),
        supplier=supplier,
        location=location,
        expected_on=expected_on,
        notes=notes,
        created_by=user,
    )
    PurchaseOrderLine.objects.bulk_create(
        PurchaseOrderLine(order=order, variant=line.variant, quantity_ordered=line.quantity, unit_cost=line.unit_cost)
        for line in lines
    )
    return order


@transaction.atomic
def replace_lines(*, user: User, order: PurchaseOrder, lines: list[OrderLineInput]) -> PurchaseOrder:
    order = _locked(order)
    _require(user, Capability.PURCHASING_MANAGE, order.location)
    if order.status != Status.DRAFT:
        raise ConflictError("Só um rascunho pode ter os itens alterados.", "order_not_draft")
    _check_lines(lines)
    order.lines.all().delete()
    PurchaseOrderLine.objects.bulk_create(
        PurchaseOrderLine(order=order, variant=line.variant, quantity_ordered=line.quantity, unit_cost=line.unit_cost)
        for line in lines
    )
    return order


@transaction.atomic
def send_order(*, user: User, order: PurchaseOrder) -> PurchaseOrder:
    order = _locked(order)
    _require(user, Capability.PURCHASING_MANAGE, order.location)
    if order.status != Status.DRAFT:
        raise ConflictError("Este pedido já foi enviado.", "order_not_draft")
    if not order.lines.exists():
        raise DomainError("O pedido precisa de pelo menos um item.", "order_empty")
    order.status = Status.SENT
    order.sent_at = timezone.now()
    order.save(update_fields=["status", "sent_at"])
    return order


@transaction.atomic
def cancel_order(*, user: User, order: PurchaseOrder, reason: str) -> PurchaseOrder:
    order = _locked(order)
    _require(user, Capability.PURCHASING_MANAGE, order.location)
    if order.status not in (Status.DRAFT, Status.SENT):
        raise ConflictError(
            "Pedido com mercadoria recebida não é cancelado: encerre com pendência.", "order_not_cancellable"
        )
    order.status = Status.CANCELLED
    order.finished_at = timezone.now()
    order.finish_reason = reason
    order.save(update_fields=["status", "finished_at", "finish_reason"])
    return order


@transaction.atomic
def close_order(*, user: User, order: PurchaseOrder, reason: str) -> PurchaseOrder:
    """The supplier won't deliver the rest: the order ends with pending pieces, on record."""
    order = _locked(order)
    _require(user, Capability.PURCHASING_MANAGE, order.location)
    if order.status != Status.PARTIALLY_RECEIVED:
        raise ConflictError("Só um pedido recebido em parte é encerrado com pendência.", "order_not_closable")
    order.status = Status.CLOSED
    order.finished_at = timezone.now()
    order.finish_reason = reason
    order.save(update_fields=["status", "finished_at", "finish_reason"])
    return order


def _refresh_status(order: PurchaseOrder) -> None:
    if order.status in (Status.CLOSED, Status.CANCELLED):
        return
    totals = order.lines.aggregate(ordered=Sum("quantity_ordered"), received=Sum("quantity_received"))
    received, ordered = totals["received"] or 0, totals["ordered"] or 0
    if received == ordered:
        order.status, order.finished_at = Status.RECEIVED, timezone.now()
    else:
        order.status, order.finished_at = (Status.PARTIALLY_RECEIVED if received else Status.SENT), None
    order.save(update_fields=["status", "finished_at"])


# ─── Receiving ─────────────────────────────────────────────────────────────────


@transaction.atomic
def receive(
    *, user: User, order: PurchaseOrder, lines: list[ReceiptLineInput], invoice_number: str = ""
) -> GoodsReceipt:
    """
    Books a delivery: stock enters at the invoice cost (the order's unless someone who sees
    costs typed another). Never more than what is still pending on each line.
    """
    order = _locked(order)
    _require(user, Capability.STOCK_RECEIVE, order.location)
    if order.status not in PurchaseOrder.OPEN:
        raise ConflictError(f"Pedido {order.get_status_display().lower()}: nada a receber.", "order_not_open")
    if not lines or any(line.quantity <= 0 for line in lines):
        raise DomainError("Informe as quantidades recebidas.", "receipt_empty")
    if len({line.order_line_id for line in lines}) != len(lines):
        raise DomainError("Item repetido no recebimento.", "receipt_duplicate_line")
    order_lines = {ol.pk: ol for ol in order.lines.select_related("variant")}
    sees_costs = can(user, Capability.COSTS_VIEW)
    resolved: list[tuple[PurchaseOrderLine, int, Decimal]] = []
    for line in lines:
        order_line = order_lines.get(line.order_line_id)
        if order_line is None:
            raise DomainError("Item não pertence a este pedido.", "receipt_foreign_line")
        if line.quantity > order_line.pending:
            raise ConflictError(
                f"{order_line.variant.sku}: recebendo {line.quantity}, pendente {order_line.pending}.",
                "receipt_over_pending",
            )
        if line.unit_cost is not None and not sees_costs:
            raise DomainError("Só quem vê custos informa o custo da nota.", "receipt_cost_not_allowed")
        unit_cost = line.unit_cost if line.unit_cost is not None else order_line.unit_cost
        if unit_cost < 0:
            raise DomainError("Custo não pode ser negativo.", "unit_cost_negative")
        resolved.append((order_line, line.quantity, unit_cost))

    entry = post_entry(
        kind=StockEntry.Kind.PURCHASE_RECEIPT,
        operations=[Inflow(ol.variant_id, order.location_id, quantity, cost) for ol, quantity, cost in resolved],
        user=user,
        source_ref=f"order:{order.number}",
        note=f"NF {invoice_number}" if invoice_number else "",
    )
    receipt = GoodsReceipt.objects.create(
        order=order, invoice_number=invoice_number, stock_entry=entry, received_by=user
    )
    GoodsReceiptLine.objects.bulk_create(
        GoodsReceiptLine(receipt=receipt, order_line=ol, quantity=quantity, unit_cost=cost)
        for ol, quantity, cost in resolved
    )
    for ol, quantity, _ in resolved:
        PurchaseOrderLine.objects.filter(pk=ol.pk).update(quantity_received=F("quantity_received") + quantity)
    _refresh_status(order)
    record(
        actor=user,
        action="purchase.received",
        location=order.location,
        target=receipt,
        data={
            "order": order.number,
            "invoice": invoice_number,
            "cost_differences": [
                {"sku": ol.variant.sku, "ordered": str(ol.unit_cost), "invoiced": str(cost)}
                for ol, _, cost in resolved
                if cost != ol.unit_cost
            ],
        },
    )
    return receipt


@transaction.atomic
def cancel_receipt(*, user: User, receipt: GoodsReceipt, reason: str) -> GoodsReceipt:
    """
    Undoes a receipt exactly, at its own costs. Only while none of its SKUs has left
    inventory since: after that, the goods' value is mixed into what was sold, and the way
    back is a return to the supplier.
    """
    order = _locked(receipt.order)
    _require(user, Capability.PURCHASING_MANAGE, order.location)
    receipt = GoodsReceipt.objects.select_for_update(of=("self",)).get(pk=receipt.pk)
    if receipt.cancelled_at is not None:
        raise ConflictError("Este recebimento já foi estornado.", "receipt_already_cancelled")
    lines = list(receipt.lines.select_related("order_line__variant"))
    variant_ids = [line.order_line.variant_id for line in lines]
    last_line = receipt.stock_entry.movements.aggregate(last=Max("id"))["last"]
    moved_since = (
        StockMovement.objects.filter(variant_id__in=variant_ids, id__gt=last_line, quantity_delta__lt=0)
        .values_list("variant__sku", flat=True)
        .distinct()
    )
    if moved_since:
        raise ConflictError(
            f"{', '.join(sorted(moved_since))} já saiu do estoque depois deste recebimento: "
            "faça uma devolução ao fornecedor.",
            "receipt_goods_moved",
        )
    entry = post_entry(
        kind=StockEntry.Kind.RECEIPT_CANCELLATION,
        operations=[
            ReverseInflow(line.order_line.variant_id, order.location_id, line.quantity, line.unit_cost)
            for line in lines
        ],
        user=user,
        source_ref=f"order:{order.number}",
        note=reason,
    )
    receipt.cancelled_at = timezone.now()
    receipt.cancellation_entry = entry
    receipt.save(update_fields=["cancelled_at", "cancellation_entry"])
    for line in lines:
        PurchaseOrderLine.objects.filter(pk=line.order_line_id).update(
            quantity_received=F("quantity_received") - line.quantity
        )
    _refresh_status(order)
    record(
        actor=user,
        action="purchase.receipt_cancelled",
        location=order.location,
        target=receipt,
        data={"reason": reason},
    )
    return receipt


@transaction.atomic
def return_to_supplier(
    *, user: User, supplier: Supplier, location: Location, lines: list[tuple[ProductVariant, int]], reason: str
) -> PurchaseReturn:
    _require(user, Capability.PURCHASING_MANAGE, location)
    if not lines or any(quantity <= 0 for _, quantity in lines):
        raise DomainError("Informe as peças devolvidas.", "return_empty")
    entry = post_entry(
        kind=StockEntry.Kind.PURCHASE_RETURN,
        operations=[Outflow(variant.pk, location.pk, quantity) for variant, quantity in lines],
        user=user,
        source_ref=f"supplier:{supplier.pk}",
        note=reason,
    )
    purchase_return = PurchaseReturn.objects.create(
        supplier=supplier, location=location, reason=reason, stock_entry=entry, created_by=user
    )
    record(
        actor=user,
        action="purchase.returned",
        location=location,
        target=purchase_return,
        data={"supplier": supplier.name, "lines": [{"sku": v.sku, "quantity": q} for v, q in lines]},
    )
    return purchase_return


# ─── Restock suggestions ───────────────────────────────────────────────────────


def suggestions(location_ids: list[int]) -> list[dict[str, object]]:
    """
    SKUs whose stock plus what is already on order is below the store's minimum, and how many
    to order to reach the maximum (or the minimum, when no maximum is set).
    """
    on_order = {
        (row["variant_id"], row["order__location_id"]): row["pending_qty"]
        for row in PurchaseOrderLine.objects.filter(
            order__status__in=PurchaseOrder.OPEN, order__location_id__in=location_ids
        )
        .values("variant_id", "order__location_id")
        .annotate(pending_qty=Sum(F("quantity_ordered") - F("quantity_received")))
    }
    levels = StockLevel.objects.filter(location_id__in=location_ids, min_quantity__gt=0).select_related(
        "variant__product", "variant__size", "variant__color", "location"
    )
    short = [
        lvl for lvl in levels if lvl.quantity + on_order.get((lvl.variant_id, lvl.location_id), 0) < lvl.min_quantity
    ]
    # The latest receipt of each of those SKUs, in one query (DISTINCT ON the variant).
    latest = {
        line.order_line.variant_id: line
        for line in GoodsReceiptLine.objects.filter(
            order_line__variant__in=[lvl.variant_id for lvl in short], receipt__cancelled_at__isnull=True
        )
        .select_related("order_line", "receipt__order")
        .order_by("order_line__variant_id", "-receipt__received_at", "-pk")
        .distinct("order_line__variant_id")
    }
    rows: list[dict[str, object]] = []
    for level in short:
        pending = on_order.get((level.variant_id, level.location_id), 0)
        available = level.quantity + pending
        target = level.max_quantity if level.max_quantity is not None else level.min_quantity
        last = latest.get(level.variant_id)
        rows.append(
            {
                "variant": level.variant_id,
                "sku": level.variant.sku,
                "product": level.variant.product.name,
                "location": level.location_id,
                "location_code": level.location.code,
                "quantity": level.quantity,
                "on_order": pending,
                "min_quantity": level.min_quantity,
                "max_quantity": level.max_quantity,
                "suggested": target - available,
                "last_supplier": last.receipt.order.supplier_id if last else None,
                "last_unit_cost": str(last.unit_cost) if last else None,
            }
        )
    return sorted(rows, key=lambda row: (str(row["location_code"]), str(row["sku"])))
