from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db.models import Sum
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from catalog.models import Product
from locations.models import Location
from pos.models import CashSession, Sale
from pos.tests.conftest import sku
from reports import services
from reports.tests.test_sales_reports import sell, stock
from stock.models import SkuCost, StockEntry
from stock.services import Inflow, post_entry
from transfers import services as transfers

pytestmark = pytest.mark.django_db
D = Decimal


def by_location(report: dict[str, Any]) -> dict[str, str]:
    return {row["location"]: row["value"] for row in report["by_location"]}


class TestValuation:
    @pytest.fixture
    def before_the_second_receipt(
        self, owner: User, shirt: Product, store: Location, other_store: Location
    ) -> tuple[Any, list[int]]:
        """
        Shirts: 10 of each of the 5 sizes at the Centro store at 30.00 (1500.00). Then 10 M at
        the Shopping store at 36.00: the M average becomes 660.00 / 20 = 33.00. Then 2 M leave
        Centro for the Shopping store and are in transit.
        """
        moment = timezone.now()
        post_entry(
            kind=StockEntry.Kind.PURCHASE_RECEIPT,
            operations=[Inflow(sku(shirt).pk, other_store.pk, 10, D("36.00"))],
            user=owner,
        )
        trip = transfers.create(user=owner, origin=store, destination=other_store, lines=[(sku(shirt), 2)])
        transfers.dispatch(user=owner, transfer=trip)
        transit = Location.objects.get(kind=Location.Kind.TRANSIT)
        return moment, [store.pk, other_store.pk, transit.pk]

    def test_now_it_adds_up_to_the_ledger(
        self, api_as: Callable[..., APIClient], before_the_second_receipt: Any
    ) -> None:
        report = api_as(Role.OWNER).get("/api/reports/valuation").json()
        # Centro: 4 sizes × 10 × 30.00 + 8 M × 33.00. Shopping: 10 M × 33.00. In transit: 2 × 33.00.
        assert by_location(report) == {"CENTRO": "1464.00", "SHOP": "330.00", "TRANSITO": "66.00"}
        ledger = SkuCost.objects.aggregate(total=Sum("value"))["total"]
        assert D(report["total"]) == ledger == D("1860.0000")
        assert [(p["reference"], p["quantity"], p["value"]) for p in report["products"]] == [("CAM-001", 60, "1860.00")]

    def test_at_an_earlier_moment(self, before_the_second_receipt: Any) -> None:
        moment, locations = before_the_second_receipt
        report = services.valuation(locations, moment)
        assert (report["total"], by_location(report)) == ("1500.00", {"CENTRO": "1500.00"})

    def test_a_day_before_anything(self, api_as: Callable[..., APIClient], before_the_second_receipt: Any) -> None:
        yesterday = timezone.localdate() - timedelta(days=1)
        assert api_as(Role.OWNER).get(f"/api/reports/valuation?at={yesterday}").json()["total"] == "0.00"

    def test_a_manager_sees_their_store(self, api_as: Callable[..., APIClient], before_the_second_receipt: Any) -> None:
        report = api_as(Role.MANAGER).get("/api/reports/valuation").json()
        assert (report["total"], by_location(report)) == ("1464.00", {"CENTRO": "1464.00"})


def test_turnover_and_coverage(
    api_as: Callable[..., APIClient],
    make_product: Callable[..., Product],
    owner: User,
    cashier: User,
    session: CashSession,
    shirt: Product,
    store: Location,
) -> None:
    trousers = make_product(reference="CAL-001", name="Calça sarja", price="150.00")
    stock(owner, trousers, store, "60.00")
    sell(cashier, (sku(shirt), 5), total="399.50")
    rows = api_as(Role.MANAGER).get(f"/api/reports/turnover?from={timezone.localdate()}").json()
    # Today only. Shirts: nothing in stock when the day began, 1500.00 - 150.00 now: average
    # 675.00; 150.00 sold at cost: turnover 0.22. 45 left at 5 a day: 9 days.
    # Trousers didn't sell: no coverage, last.
    assert [
        (r["reference"], r["units_sold"], r["in_stock"], r["coverage_days"], r["cogs"], r["turnover"]) for r in rows
    ] == [
        ("CAM-001", 5, 45, 9, "150.00", "0.22"),
        ("CAL-001", 0, 10, None, "0.00", "0.00"),
    ]


def test_stale_products(
    api_as: Callable[..., APIClient],
    make_product: Callable[..., Product],
    owner: User,
    cashier: User,
    session: CashSession,
    shirt: Product,
    store: Location,
) -> None:
    trousers = make_product(reference="CAL-001", name="Calça sarja", price="150.00")
    stock(owner, trousers, store, "60.00")
    jacket = make_product(reference="JAQ-001", name="Jaqueta", price="300.00")
    stock(owner, jacket, store, "120.00")
    sell(cashier, (sku(shirt), 1), total="79.90")
    old = sell(cashier, (sku(jacket), 1), total="300.00")
    long_ago = timezone.now() - timedelta(days=90)
    Sale.objects.filter(pk=old.pk).update(created_at=long_ago)
    rows = api_as(Role.MANAGER).get("/api/reports/stale?days=60").json()
    # The shirt sold today. The jacket last sold 90 days ago; the trousers never did.
    assert [(r["reference"], r["in_stock"], r["stock_value"], r["last_sale"]) for r in rows] == [
        ("JAQ-001", 9, "1080.00", long_ago.isoformat()),
        ("CAL-001", 10, "600.00", None),
    ]
    assert api_as(Role.MANAGER).get("/api/reports/stale?days=0").status_code == 400
