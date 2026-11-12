"""
The valuation rules, with numbers worked out by hand. Every test ends by checking that
levels and costs still agree with the ledger.
"""

from collections.abc import Callable, Iterator
from decimal import Decimal

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.utils import DatabaseError

from accounts.models import User
from catalog.models import Product, ProductVariant
from common.errors import DomainError
from conftest import make_location
from locations.models import Location
from stock.invariants import stock_problems
from stock.models import SkuCost, StockEntry, StockLevel, StockMovement
from stock.services import (
    Gain,
    Inflow,
    InsufficientStock,
    Outflow,
    ReverseInflow,
    Transfer,
    ValueAdjustment,
    post_entry,
)

pytestmark = pytest.mark.django_db
K = StockEntry.Kind


@pytest.fixture(autouse=True)
def _ledger_stays_consistent() -> Iterator[None]:
    yield
    assert stock_problems() == []


@pytest.fixture
def sku(make_product: Callable[..., Product]) -> ProductVariant:
    return make_product().variants.get(size__label="M")


@pytest.fixture
def transit() -> Location:
    return Location.objects.get(kind=Location.Kind.TRANSIT)


@pytest.fixture
def losses() -> Location:
    return Location.objects.get(kind=Location.Kind.LOSS)


def post(user: User, kind: StockEntry.Kind, *ops: object, **fields: object) -> StockEntry:
    return post_entry(kind=kind, operations=list(ops), user=user, **fields)  # type: ignore[arg-type]


def cost(variant: ProductVariant) -> tuple[int, Decimal]:
    row = SkuCost.objects.get(variant=variant)
    return row.quantity, row.value


def qty(variant: ProductVariant, location: Location) -> int:
    level = StockLevel.objects.filter(variant=variant, location=location).first()
    return level.quantity if level else 0


def out_value(entry: StockEntry) -> Decimal:
    return -sum((m.value_delta for m in entry.movements.all()), Decimal(0))


def test_moving_average(owner: User, sku: ProductVariant, store: Location) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 10, Decimal("20.00")))
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 10, Decimal("30.00")))
    assert cost(sku) == (20, Decimal("500.0000"))  # average 25.00
    sale = post(owner, K.SALE, Outflow(sku.pk, store.pk, 4))
    line = sale.movements.get()
    assert (line.quantity_delta, line.value_delta, line.unit_cost, line.balance_after) == (
        -4,
        Decimal("-100.0000"),
        Decimal("25.0000"),
        16,
    )
    assert cost(sku) == (16, Decimal("400.0000"))


def test_transfers_between_stores_do_not_change_cost(
    owner: User, sku: ProductVariant, store: Location, other_store: Location, transit: Location
) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 10, Decimal("20.00")))
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 10, Decimal("30.00")))
    post(owner, K.TRANSFER_DISPATCH, Transfer(sku.pk, store.pk, transit.pk, 6))
    assert (qty(sku, store), qty(sku, transit)) == (14, 6)
    assert cost(sku) == (20, Decimal("500.0000"))  # stock in transit is still inventory
    post(owner, K.TRANSFER_RECEIPT, Transfer(sku.pk, transit.pk, other_store.pk, 6))
    assert (qty(sku, store), qty(sku, transit), qty(sku, other_store)) == (14, 0, 6)
    assert cost(sku) == (20, Decimal("500.0000"))


def test_the_last_piece_takes_the_remaining_value(owner: User, sku: ProductVariant, store: Location) -> None:
    # 10.00 + 10.01 + 10.01 = 30.02 for 3 pieces: an average of 10.00666…
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 1, Decimal("10.00")))
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 2, Decimal("10.01")))
    first = post(owner, K.SALE, Outflow(sku.pk, store.pk, 1))
    second = post(owner, K.SALE, Outflow(sku.pk, store.pk, 1))
    last = post(owner, K.SALE, Outflow(sku.pk, store.pk, 1))
    # 30.0200 / 3 = 10.0067; then 20.0133 / 2 = 10.00665 → 10.0067; the last takes 10.0066.
    assert [out_value(e) for e in (first, second, last)] == [
        Decimal("10.0067"),
        Decimal("10.0067"),
        Decimal("10.0066"),
    ]
    assert cost(sku) == (0, Decimal("0.0000"))  # no stray fraction of a cent left behind


def test_a_write_off_leaves_inventory(owner: User, sku: ProductVariant, store: Location, losses: Location) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 5, Decimal("10.00")))
    post(owner, K.ADJUSTMENT, Transfer(sku.pk, store.pk, losses.pk, 2), reason="damaged")
    assert (qty(sku, store), qty(sku, losses)) == (3, 2)
    assert cost(sku) == (3, Decimal("30.0000"))


def test_found_pieces_enter_at_the_average(owner: User, sku: ProductVariant, store: Location) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 2, Decimal("10.00")))
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 2, Decimal("12.00")))
    post(owner, K.ADJUSTMENT, Gain(sku.pk, store.pk, 1), reason="found")
    assert cost(sku) == (5, Decimal("55.0000"))


def test_found_pieces_of_a_sold_out_sku_enter_at_its_last_cost(
    owner: User, sku: ProductVariant, store: Location
) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 1, Decimal("18.50")))
    post(owner, K.SALE, Outflow(sku.pk, store.pk, 1))
    post(owner, K.COUNT_ADJUSTMENT, Gain(sku.pk, store.pk, 2))
    assert cost(sku) == (2, Decimal("37.0000"))


def test_a_sku_with_no_cost_history_cannot_be_found(owner: User, sku: ProductVariant, store: Location) -> None:
    with pytest.raises(DomainError, match="nunca teve custo"):
        post(owner, K.ADJUSTMENT, Gain(sku.pk, store.pk, 1), reason="found")


def test_value_adjustment(owner: User, sku: ProductVariant, store: Location) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 4, Decimal("10.00")))
    post(owner, K.COST_ADJUSTMENT, ValueAdjustment(sku.pk, store.pk, Decimal("2.00")))
    assert cost(sku) == (4, Decimal("42.0000"))  # average 10.50
    with pytest.raises(DomainError, match="negativo"):
        post(owner, K.COST_ADJUSTMENT, ValueAdjustment(sku.pk, store.pk, Decimal("-50.00")))


def test_shortages_are_reported_together_and_nothing_is_written(
    owner: User, make_product: Callable[..., Product], store: Location
) -> None:
    variants = list(make_product().variants.order_by("size__position")[:3])
    post(owner, K.PURCHASE_RECEIPT, *(Inflow(v.pk, store.pk, 2, Decimal("10.00")) for v in variants))
    before = (StockEntry.objects.count(), StockMovement.objects.count())
    with pytest.raises(InsufficientStock) as raised:
        post(
            owner,
            K.SALE,
            Outflow(variants[0].pk, store.pk, 3),  # short by 1
            Outflow(variants[1].pk, store.pk, 1),  # fine
            Outflow(variants[2].pk, store.pk, 1),
            Outflow(variants[2].pk, store.pk, 2),  # short only in total
        )
    shortages = raised.value.details["shortages"]
    assert [(s["sku"], s["available"], s["requested"]) for s in shortages] == [
        (variants[0].sku, 2, 3),
        (variants[2].sku, 2, 3),
    ]
    assert (StockEntry.objects.count(), StockMovement.objects.count()) == before
    assert [qty(v, store) for v in variants] == [2, 2, 2]


def test_stock_is_per_location(owner: User, sku: ProductVariant, store: Location, other_store: Location) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, other_store.pk, 5, Decimal("10.00")))
    with pytest.raises(InsufficientStock):
        post(owner, K.SALE, Outflow(sku.pk, store.pk, 1))


@pytest.mark.parametrize(
    ("build", "code"),
    [
        (lambda s, store, transit, losses: Transfer(s, losses, store, 1), "transfer_from_outside"),
        (lambda s, store, transit, losses: Transfer(s, store, store, 1), "transfer_same_location"),
        (lambda s, store, transit, losses: Inflow(s, transit, 1, Decimal("1")), "location_not_physical"),
        (lambda s, store, transit, losses: Outflow(s, store, 0), "quantity_not_positive"),
    ],
)
def test_impossible_operations(
    owner: User,
    sku: ProductVariant,
    store: Location,
    transit: Location,
    losses: Location,
    build: Callable[..., object],
    code: str,
) -> None:
    with pytest.raises(DomainError) as raised:
        post(owner, K.ADJUSTMENT, build(sku.pk, store.pk, transit.pk, losses.pk))
    assert raised.value.code == code


def test_the_ledger_cannot_be_edited_or_deleted(owner: User, sku: ProductVariant, store: Location) -> None:
    entry = post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 1, Decimal("10.00")))
    # Each refused statement gets its own savepoint: PostgreSQL aborts the transaction otherwise.
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic():
        StockMovement.objects.filter(entry=entry).update(quantity_delta=100)
    with pytest.raises(DatabaseError, match="append-only"), transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("delete from stock_stockentry where id = %s", [entry.pk])


def test_the_database_refuses_negative_stock(owner: User, sku: ProductVariant, store: Location) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 1, Decimal("10.00")))
    with pytest.raises(IntegrityError, match="stock_never_negative"), transaction.atomic():
        StockLevel.objects.filter(variant=sku, location=store).update(quantity=-1)


def test_the_checker_catches_a_level_edited_behind_the_ledgers_back(
    owner: User, sku: ProductVariant, store: Location
) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 3, Decimal("10.00")))
    StockLevel.objects.filter(variant=sku, location=store).update(quantity=4)
    problems = stock_problems()
    assert any("stock level differs" in p for p in problems)
    StockLevel.objects.filter(variant=sku, location=store).update(quantity=3)  # leave it consistent


def test_a_new_store_starts_empty(owner: User, sku: ProductVariant) -> None:
    fresh = make_location("NOVA", "Loja nova")
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, fresh.pk, 2, Decimal("10.00")))
    assert qty(sku, fresh) == 2


def test_reversing_a_receipt_removes_exactly_what_it_added(owner: User, sku: ProductVariant, store: Location) -> None:
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 2, Decimal("10.00")))
    post(owner, K.PURCHASE_RECEIPT, Inflow(sku.pk, store.pk, 3, Decimal("14.00")))  # average 12.40
    post(owner, K.RECEIPT_CANCELLATION, ReverseInflow(sku.pk, store.pk, 3, Decimal("14.00")))
    # At the average it would have removed 37.20 and left 24.80 for 2 pieces: wrong.
    assert cost(sku) == (2, Decimal("20.0000"))
    assert qty(sku, store) == 2
