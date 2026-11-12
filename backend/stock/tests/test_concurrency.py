"""
Races against a real PostgreSQL: threads released together by a barrier, each on its own
connection. A short lock_timeout turns a deadlock into a failure instead of a hung CI run.
"""

import threading
from collections.abc import Callable
from decimal import Decimal

import pytest
from django.db import connection

from accounts.models import User
from catalog.models import Product, ProductVariant
from locations.models import Location
from stock.invariants import stock_problems
from stock.models import SkuCost, StockEntry, StockLevel
from stock.services import Inflow, InsufficientStock, Outflow, post_entry

pytestmark = pytest.mark.django_db(transaction=True)
K = StockEntry.Kind


def race(*tasks: Callable[[], str]) -> list[str]:
    """Runs the tasks at the same instant; each returns an outcome label (or the error's class name)."""
    barrier = threading.Barrier(len(tasks))
    outcomes: list[str] = []

    def run(task: Callable[[], str]) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            barrier.wait()
            outcomes.append(task())
        except InsufficientStock:
            outcomes.append("insufficient")
        except Exception as error:  # a deadlock or a timeout must show up in the assertion
            outcomes.append(type(error).__name__)
        finally:
            connection.close()

    threads = [threading.Thread(target=run, args=(task,)) for task in tasks]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return outcomes


def receive(user: User, variant: ProductVariant, location: Location, quantity: int, unit_cost: str) -> None:
    post_entry(
        kind=K.PURCHASE_RECEIPT, operations=[Inflow(variant.pk, location.pk, quantity, Decimal(unit_cost))], user=user
    )


def test_two_tills_selling_the_last_piece(owner: User, make_product: Callable[..., Product], store: Location) -> None:
    sku = make_product().variants.first()
    assert sku is not None
    receive(owner, sku, store, 1, "10.00")

    def sell() -> str:
        post_entry(kind=K.SALE, operations=[Outflow(sku.pk, store.pk, 1)], user=owner)
        return "sold"

    assert sorted(race(sell, sell)) == ["insufficient", "sold"]
    assert StockLevel.objects.get(variant=sku, location=store).quantity == 0
    assert stock_problems() == []


def test_simultaneous_receipts_average_correctly(
    owner: User, make_product: Callable[..., Product], store: Location
) -> None:
    sku = make_product().variants.first()
    assert sku is not None

    def receiving(unit_cost: str) -> Callable[[], str]:
        def task() -> str:
            receive(owner, sku, store, 2, unit_cost)
            return "received"

        return task

    outcomes = race(*(receiving(c) for c in ("10.00", "20.00", "30.00", "40.00", "50.00")))
    assert outcomes == ["received"] * 5
    row = SkuCost.objects.get(variant=sku)
    assert (row.quantity, row.value) == (10, Decimal("300.0000"))  # average 30.00
    assert stock_problems() == []


def test_opposite_orders_do_not_deadlock(owner: User, make_product: Callable[..., Product], store: Location) -> None:
    first, second = make_product().variants.order_by("size__position")[:2]
    for sku in (first, second):
        receive(owner, sku, store, 20, "10.00")

    def selling(order: tuple[ProductVariant, ProductVariant]) -> Callable[[], str]:
        def task() -> str:
            for _ in range(10):
                post_entry(kind=K.SALE, operations=[Outflow(v.pk, store.pk, 1) for v in order], user=owner)
            return "done"

        return task

    # One till scans A then B, the other B then A: locks are taken in id order regardless.
    assert race(selling((first, second)), selling((second, first))) == ["done", "done"]
    assert StockLevel.objects.get(variant=first, location=store).quantity == 0
    assert StockLevel.objects.get(variant=second, location=store).quantity == 0
    assert stock_problems() == []
