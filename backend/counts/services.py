"""
Inventory counts. The difference for a SKU is what was counted minus the system quantity read
when its first entry was made, and it is applied as a delta to the balance at apply time.
That is exact when pieces are counted before they are sold, the usual case; when a SKU moved
between its first entry and the end of the count, the review flags it for a recount instead
of guessing which area the moved piece was in.
"""

from dataclasses import dataclass
from typing import Literal

from django.db import IntegrityError, transaction
from django.db.models import Max, Q
from django.utils import timezone

from accounts.capabilities import Capability, can
from accounts.models import User
from audit.services import record
from catalog.models import ProductVariant
from catalog.services import variant_for_code
from common.errors import ConflictError, DomainError
from locations.models import Location
from stock.models import StockEntry, StockLevel, StockMovement
from stock.services import Gain, Operation, Transfer, post_entry

from .models import CountEntry, CountScopeItem, InventoryCount

Status = InventoryCount.Status
UncountedPolicy = Literal["zero", "keep"]


@dataclass(frozen=True)
class ReviewRow:
    variant_id: int
    sku: str
    product: str
    counted: int | None  # None: nobody counted it
    expected: int  # the system quantity at its first entry (or now, if uncounted)
    current: int
    difference: int | None
    moved_during_count: bool
    needs_recount: bool
    areas: dict[str, int]


def _require(user: User, capability: Capability, location: Location) -> None:
    if not can(user, capability, location):
        raise DomainError("Você não tem permissão para esta contagem.", "count_not_allowed")


def _locked(count: InventoryCount) -> InventoryCount:
    return InventoryCount.objects.select_for_update(of=("self",)).select_related("location").get(pk=count.pk)


@transaction.atomic
def open_count(
    *,
    user: User,
    location: Location,
    category_ids: list[int] | None = None,
    product_ids: list[int] | None = None,
    tolerance: int = 0,
    note: str = "",
) -> InventoryCount:
    _require(user, Capability.STOCK_COUNT_APPLY, location)
    if not location.is_physical:
        raise DomainError("Contagens são feitas em lojas e depósitos.", "location_not_physical")
    # Active SKUs, plus retired ones that still have stock here: they are on the shelf too.
    variants = ProductVariant.objects.filter(
        Q(is_active=True) | Q(stock_levels__location=location, stock_levels__quantity__gt=0)
    )
    label = "Loja inteira"
    if category_ids:
        variants = variants.filter(product__category_id__in=category_ids)
        label = "Categorias selecionadas"
    if product_ids:
        variants = variants.filter(product_id__in=product_ids)
        label = "Produtos selecionados"
    # order_by() first: the model's default ordering would otherwise leak into DISTINCT.
    variant_ids = list(variants.order_by().values_list("pk", flat=True).distinct())
    if not variant_ids:
        raise DomainError("Nenhum SKU no escopo desta contagem.", "count_scope_empty")
    try:
        with transaction.atomic():
            count = InventoryCount.objects.create(
                location=location, tolerance=tolerance, scope_label=label, note=note, opened_by=user
            )
    except IntegrityError as error:
        raise ConflictError("Já existe uma contagem em andamento neste local.", "count_already_active") from error
    CountScopeItem.objects.bulk_create(CountScopeItem(count=count, variant_id=v) for v in variant_ids)
    return count


@transaction.atomic
def add_entry(*, user: User, count: InventoryCount, code: str, quantity: int, area: str) -> CountEntry:
    count = InventoryCount.objects.select_related("location").get(pk=count.pk)
    _require(user, Capability.STOCK_COUNT, count.location)
    if count.status != Status.COUNTING:
        raise ConflictError("Esta contagem não está aberta para lançamentos.", "count_not_counting")
    if quantity < 0:
        raise DomainError("Quantidade não pode ser negativa.", "quantity_negative")
    variant = variant_for_code(code)
    if variant is None:
        raise DomainError("Código não encontrado.", "code_not_found")
    if not count.scope.filter(variant=variant).exists():
        raise DomainError(f"{variant.sku} está fora do escopo desta contagem.", "count_out_of_scope")
    # Lock the balance row (creating it if needed) so the quantity and the ledger mark are read
    # together, with no sale of this SKU half-posted in between.
    StockLevel.objects.bulk_create([StockLevel(variant=variant, location=count.location)], ignore_conflicts=True)
    level = StockLevel.objects.select_for_update(of=("self",)).get(variant=variant, location=count.location)
    mark = StockMovement.objects.filter(variant=variant, location=count.location).aggregate(last=Max("id"))["last"]
    return CountEntry.objects.create(
        count=count,
        variant=variant,
        area=area.strip() or "Geral",
        quantity=quantity,
        system_quantity=level.quantity,
        ledger_mark=mark or 0,
        counted_by=user,
    )


@transaction.atomic
def delete_entry(*, user: User, entry: CountEntry) -> None:
    count = _locked(entry.count)
    if count.status != Status.COUNTING:
        raise ConflictError("Esta contagem não está aberta para lançamentos.", "count_not_counting")
    if entry.counted_by_id != user.pk and not can(user, Capability.STOCK_COUNT_APPLY, count.location):
        raise DomainError("Só quem lançou (ou o gerente) apaga este lançamento.", "count_entry_not_yours")
    entry.delete()


@transaction.atomic
def finish(*, user: User, count: InventoryCount) -> InventoryCount:
    count = _locked(count)
    _require(user, Capability.STOCK_COUNT_APPLY, count.location)
    if count.status != Status.COUNTING:
        raise ConflictError("Esta contagem não está em andamento.", "count_not_counting")
    count.status, count.finished_at = Status.REVIEW, timezone.now()
    count.save(update_fields=["status", "finished_at"])
    return count


@transaction.atomic
def recount(*, user: User, count: InventoryCount, variant_ids: list[int]) -> InventoryCount:
    """Discards the entries of these SKUs and reopens the count for them."""
    count = _locked(count)
    _require(user, Capability.STOCK_COUNT_APPLY, count.location)
    if count.status not in InventoryCount.ACTIVE:
        raise ConflictError("Esta contagem já foi encerrada.", "count_finished")
    count.entries.filter(variant_id__in=variant_ids).delete()
    count.status, count.finished_at = Status.COUNTING, None
    count.save(update_fields=["status", "finished_at"])
    return count


def review(count: InventoryCount) -> list[ReviewRow]:
    entries: dict[int, list[CountEntry]] = {}
    for entry in count.entries.order_by("id"):
        entries.setdefault(entry.variant_id, []).append(entry)
    current = dict(
        StockLevel.objects.filter(location=count.location, variant__in=count.scope.values("variant")).values_list(
            "variant_id", "quantity"
        )
    )
    moved_after = dict(
        StockMovement.objects.filter(location=count.location, variant_id__in=list(entries))
        .values("variant_id")
        .annotate(last=Max("id"))
        .values_list("variant_id", "last")
    )
    rows: list[ReviewRow] = []
    scope = count.scope.select_related("variant__product").order_by("variant__product__name", "variant__sku")
    for item in scope:
        variant = item.variant
        found = entries.get(variant.pk, [])
        now = current.get(variant.pk, 0)
        if found:
            counted = sum(e.quantity for e in found)
            expected = found[0].system_quantity
            difference: int | None = counted - expected
            moved = moved_after[variant.pk] > found[0].ledger_mark
            needs_recount = abs(counted - expected) > count.tolerance or moved
        else:
            counted, expected, difference, moved = None, now, None, False
            needs_recount = now != 0
        areas: dict[str, int] = {}
        for entry in found:
            areas[entry.area] = areas.get(entry.area, 0) + entry.quantity
        rows.append(
            ReviewRow(
                variant_id=variant.pk,
                sku=variant.sku,
                product=variant.product.name,
                counted=counted,
                expected=expected,
                current=now,
                difference=difference,
                moved_during_count=moved,
                needs_recount=needs_recount,
                areas=areas,
            )
        )
    return rows


@transaction.atomic
def apply(*, user: User, count: InventoryCount, uncounted: UncountedPolicy | None = None) -> InventoryCount:
    """
    Posts the differences. SKUs in scope with stock that nobody counted must be decided
    explicitly: zeroed (they weren't found) or kept (they weren't looked for).
    """
    count = _locked(count)
    _require(user, Capability.STOCK_COUNT_APPLY, count.location)
    if count.status != Status.REVIEW:
        raise ConflictError("Finalize a contagem antes de aplicar.", "count_not_in_review")
    rows = review(count)
    missing = [row for row in rows if row.counted is None and row.current != 0]
    if missing and uncounted is None:
        raise DomainError(
            "Há SKUs com estoque que não foram contados: escolha zerar ou manter.",
            "count_uncounted_undecided",
            uncounted=[{"sku": row.sku, "current": row.current} for row in missing],
        )
    losses = Location.objects.get(kind=Location.Kind.LOSS)
    operations: list[Operation] = []
    for row in rows:
        delta = row.difference if row.counted is not None else (-row.current if uncounted == "zero" else 0)
        if delta and delta > 0:
            operations.append(Gain(row.variant_id, count.location_id, delta))
        elif delta and delta < 0:
            operations.append(Transfer(row.variant_id, count.location_id, losses.pk, -delta))
    if operations:
        count.entry = post_entry(
            kind=StockEntry.Kind.COUNT_ADJUSTMENT,
            operations=operations,
            user=user,
            source_ref=f"count:{count.pk}",
            note=f"Inventário: {count.scope_label}",
        )
    count.status, count.applied_by, count.applied_at = Status.APPLIED, user, timezone.now()
    count.save(update_fields=["status", "entry", "applied_by", "applied_at"])
    record(
        actor=user,
        action="count.applied",
        location=count.location,
        target=count,
        data={
            "scope": count.scope_label,
            "skus": len(rows),
            "gains": sum(1 for op in operations if isinstance(op, Gain)),
            "losses": sum(1 for op in operations if isinstance(op, Transfer)),
            "uncounted_policy": uncounted if missing else None,
        },
    )
    return count


@transaction.atomic
def cancel(*, user: User, count: InventoryCount) -> InventoryCount:
    count = _locked(count)
    _require(user, Capability.STOCK_COUNT_APPLY, count.location)
    if count.status not in InventoryCount.ACTIVE:
        raise ConflictError("Esta contagem já foi encerrada.", "count_finished")
    count.status, count.cancelled_at = Status.CANCELLED, timezone.now()
    count.save(update_fields=["status", "cancelled_at"])
    return count
