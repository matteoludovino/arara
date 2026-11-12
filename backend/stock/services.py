"""
The only code that writes stock. Callers describe what happened with a few explicit
operations; post_entry() locks what it touches, values every line and appends the ledger.

Lock order, the same in every service of the system (CashSession → DocumentSequence →
SkuCost → StockLevel → StoreCredit): two transactions touching the same SKUs always queue
up instead of deadlocking.
"""

from collections import defaultdict
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from accounts.capabilities import Capability, can
from accounts.models import Approval, User
from accounts.services import consume_approval
from audit.services import record
from catalog.models import ProductVariant
from common.errors import ConflictError, DomainError
from locations.models import Location

from .models import VALUE_ZERO, SkuCost, StockEntry, StockLevel, StockMovement

FOUR_PLACES = Decimal("0.0001")


def q4(value: Decimal) -> Decimal:
    return value.quantize(FOUR_PLACES, rounding=ROUND_HALF_UP)


# ─── Operations ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Inflow:
    """Goods entering inventory from outside (a purchase, a customer return) at a known unit cost."""

    variant_id: int
    location_id: int
    quantity: int
    unit_cost: Decimal


@dataclass(frozen=True)
class Gain:
    """Goods found (a count, an adjustment): enter at the current average, or the last known cost."""

    variant_id: int
    location_id: int
    quantity: int


@dataclass(frozen=True)
class Outflow:
    """Goods leaving inventory (a sale, a return to the supplier), valued at the average cost."""

    variant_id: int
    location_id: int
    quantity: int


@dataclass(frozen=True)
class Transfer:
    """
    Goods moving between locations. Between inventory locations it is cost-neutral; into a
    location outside inventory (losses) it is a write-off at the average cost.
    """

    variant_id: int
    from_location_id: int
    to_location_id: int
    quantity: int


@dataclass(frozen=True)
class ValueAdjustment:
    """Value only (an invoice priced differently from the order): no pieces move."""

    variant_id: int
    location_id: int
    value_delta: Decimal


Operation = Inflow | Gain | Outflow | Transfer | ValueAdjustment


class InsufficientStock(ConflictError):
    def __init__(self, shortages: list[dict[str, object]]) -> None:
        skus = ", ".join(f"{s['sku']} em {s['location']}" for s in shortages)
        super().__init__(f"Estoque insuficiente: {skus}.", "insufficient_stock", shortages=shortages)


# ─── Posting ───────────────────────────────────────────────────────────────────


def _validate(op: Operation, locations: dict[int, Location]) -> None:
    if isinstance(op, ValueAdjustment):
        if op.value_delta == 0:
            raise DomainError("Ajuste de valor zerado.", "value_adjustment_zero")
    elif op.quantity <= 0:
        raise DomainError("Quantidade precisa ser maior que zero.", "quantity_not_positive")
    if isinstance(op, Inflow) and op.unit_cost < 0:
        raise DomainError("Custo não pode ser negativo.", "unit_cost_negative")
    if isinstance(op, Transfer):
        source, target = locations[op.from_location_id], locations[op.to_location_id]
        if source.pk == target.pk:
            raise DomainError("Origem e destino são o mesmo local.", "transfer_same_location")
        if not source.holds_inventory:
            raise DomainError(f"{source.name} não é estoque da empresa.", "transfer_from_outside")
    else:
        location = locations[op.location_id]
        if not location.is_physical:
            raise DomainError(f"{location.name} não recebe esta operação.", "location_not_physical")


def _keys(op: Operation) -> list[tuple[int, int]]:
    if isinstance(op, Transfer):
        return [(op.variant_id, op.from_location_id), (op.variant_id, op.to_location_id)]
    return [(op.variant_id, op.location_id)]


def _average_out(cost: SkuCost, quantity: int) -> Decimal:
    """Value of `quantity` pieces at the average; the last pieces take exactly what is left."""
    if quantity >= cost.quantity:
        return cost.value
    return q4(cost.value * quantity / cost.quantity)


def _last_known_unit_cost(variant_id: int) -> Decimal | None:
    return (
        StockMovement.objects.filter(variant_id=variant_id, quantity_delta__gt=0, unit_cost__gt=0)
        .order_by("-id")
        .values_list("unit_cost", flat=True)
        .first()
    )


def post_entry(
    *,
    kind: StockEntry.Kind,
    operations: list[Operation],
    user: User,
    reason: str = "",
    note: str = "",
    source_ref: str = "",
    approval: Approval | None = None,
) -> StockEntry:
    if not operations:
        raise DomainError("Nada a lançar.", "entry_empty")
    location_ids = {loc for op in operations for _, loc in _keys(op)}
    locations = Location.objects.in_bulk(location_ids)
    if len(locations) != len(location_ids):
        raise DomainError("Local inexistente.", "location_not_found")
    for op in operations:
        _validate(op, locations)

    with transaction.atomic():
        # Rows that don't exist can't be locked: create them (no-op if present), then lock in order.
        variant_ids = sorted({op.variant_id for op in operations})
        SkuCost.objects.bulk_create([SkuCost(variant_id=v) for v in variant_ids], ignore_conflicts=True)
        costs = {
            c.variant_id: c
            for c in SkuCost.objects.select_for_update(of=("self",))
            .filter(variant_id__in=variant_ids)
            .order_by("variant_id")
        }
        keys = sorted({key for op in operations for key in _keys(op)})
        StockLevel.objects.bulk_create(
            [StockLevel(variant_id=v, location_id=loc) for v, loc in keys], ignore_conflicts=True
        )
        levels = {
            (lvl.variant_id, lvl.location_id): lvl
            for lvl in StockLevel.objects.select_for_update(of=("self",))
            .filter(variant_id__in=variant_ids, location_id__in=location_ids)
            .order_by("variant_id", "location_id")
        }
        available = {key: lvl.quantity for key, lvl in levels.items()}
        requested: dict[tuple[int, int], int] = defaultdict(int)
        went_negative: set[tuple[int, int]] = set()

        entry = StockEntry.objects.create(
            kind=kind, reason=reason, note=note, source_ref=source_ref, approval=approval, created_by=user
        )
        movements: list[StockMovement] = []

        def move(key: tuple[int, int], quantity: int, value: Decimal, unit_cost: Decimal) -> None:
            level = levels[key]
            level.quantity += quantity
            if quantity < 0:
                requested[key] += -quantity
            if level.quantity < 0:
                went_negative.add(key)
            movements.append(
                StockMovement(
                    entry=entry,
                    variant_id=key[0],
                    location_id=key[1],
                    quantity_delta=quantity,
                    value_delta=value,
                    unit_cost=unit_cost,
                    balance_after=max(level.quantity, 0),
                )
            )

        for op in operations:
            cost = costs[op.variant_id]
            if isinstance(op, Inflow | Gain):
                unit_cost = op.unit_cost if isinstance(op, Inflow) else _gain_cost(cost)
                value = q4(unit_cost * op.quantity)
                cost.quantity += op.quantity
                cost.value += value
                move((op.variant_id, op.location_id), op.quantity, value, q4(unit_cost))
            elif isinstance(op, Outflow):
                value = _average_out(cost, op.quantity) if cost.quantity else VALUE_ZERO
                cost.quantity -= op.quantity
                cost.value -= value
                move((op.variant_id, op.location_id), -op.quantity, -value, q4(value / op.quantity))
            elif isinstance(op, Transfer):
                leaves_inventory = not locations[op.to_location_id].holds_inventory
                value = _average_out(cost, op.quantity) if cost.quantity else VALUE_ZERO
                if leaves_inventory:
                    cost.quantity -= op.quantity
                    cost.value -= value
                unit_cost = q4(value / op.quantity)
                move((op.variant_id, op.from_location_id), -op.quantity, -value, unit_cost)
                move((op.variant_id, op.to_location_id), op.quantity, value, unit_cost)
            else:
                if cost.quantity <= 0:
                    raise DomainError("Sem estoque, não há custo a ajustar.", "value_adjustment_without_stock")
                cost.value += q4(op.value_delta)
                if cost.value < 0:
                    raise DomainError("O ajuste deixaria o valor do estoque negativo.", "value_adjustment_negative")
                move((op.variant_id, op.location_id), 0, q4(op.value_delta), q4(cost.value / cost.quantity))

        if went_negative:
            raise InsufficientStock(_shortages(went_negative, available, requested, locations))

        StockMovement.objects.bulk_create(movements)
        StockLevel.objects.bulk_update(levels.values(), ["quantity", "updated_at"])
        SkuCost.objects.bulk_update(costs.values(), ["quantity", "value", "updated_at"])
        return entry


def _gain_cost(cost: SkuCost) -> Decimal:
    if cost.quantity > 0:
        return cost.value / cost.quantity
    last = _last_known_unit_cost(cost.variant_id)
    if last is None:
        sku = ProductVariant.objects.values_list("sku", flat=True).get(pk=cost.variant_id)
        raise DomainError(
            f"{sku} nunca teve custo: lance a entrada como recebimento de compra.", "gain_without_cost", sku=sku
        )
    return last


def _shortages(
    keys: set[tuple[int, int]],
    available: dict[tuple[int, int], int],
    requested: dict[tuple[int, int], int],
    locations: dict[int, Location],
) -> list[dict[str, object]]:
    skus = dict(ProductVariant.objects.filter(pk__in={v for v, _ in keys}).values_list("pk", "sku"))
    return [
        {
            "sku": skus[variant_id],
            "location": locations[location_id].name,
            "available": available[(variant_id, location_id)],
            "requested": requested[(variant_id, location_id)],
        }
        for variant_id, location_id in sorted(keys)
    ]


# ─── Reading ───────────────────────────────────────────────────────────────────


def average_cost(variant: ProductVariant) -> Decimal | None:
    cost = SkuCost.objects.filter(variant=variant).first()
    if cost is None or cost.quantity == 0:
        return None
    return q4(cost.value / cost.quantity)


# ─── Manual adjustments ────────────────────────────────────────────────────────


def adjust_stock(
    *,
    user: User,
    location: Location,
    lines: list[tuple[ProductVariant, int]],
    reason: StockEntry.Reason,
    note: str = "",
    approval_id: int | None = None,
) -> StockEntry:
    """
    Corrects a location's stock: found pieces enter at the average cost, missing ones go to
    the losses location. Managers adjust their own stores; anyone else needs a manager's
    approval for this action and location (e.g. a cashier blocked at the till by a receipt
    that wasn't entered yet).
    """
    if not lines or any(delta == 0 for _, delta in lines):
        raise DomainError("Informe as quantidades a ajustar (positivas ou negativas).", "adjustment_empty")
    if not location.is_physical:
        raise DomainError("Ajustes são feitos em lojas e depósitos.", "location_not_physical")
    losses = Location.objects.get(kind=Location.Kind.LOSS)
    operations: list[Operation] = [
        Gain(variant.pk, location.pk, delta) if delta > 0 else Transfer(variant.pk, location.pk, losses.pk, -delta)
        for variant, delta in lines
    ]
    with transaction.atomic():
        approval = None
        if not can(user, Capability.STOCK_ADJUST, location):
            if approval_id is None:
                raise DomainError("Ajuste de estoque precisa de aprovação do gerente.", "adjustment_needs_approval")
            approval = consume_approval(
                approval_id=approval_id,
                requester=user,
                action=Approval.Action.STOCK_ADJUSTMENT,
                location=location,
                used_by="stock-adjustment",
            )
        entry = post_entry(
            kind=StockEntry.Kind.ADJUSTMENT,
            operations=operations,
            user=user,
            reason=reason,
            note=note,
            approval=approval,
        )
        record(
            actor=user,
            action="stock.adjusted",
            location=location,
            target=entry,
            data={
                "reason": reason,
                "note": note,
                "lines": [{"sku": variant.sku, "delta": delta} for variant, delta in lines],
                "approved_by": approval.approver_id if approval else None,
            },
        )
        return entry
