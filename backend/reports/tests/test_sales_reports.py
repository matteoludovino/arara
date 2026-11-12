import uuid
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from accounts.capabilities import ROLE_CAPABILITIES, Capability
from accounts.models import Role, User
from catalog.models import Product, ProductVariant
from locations.models import Location
from pos import services as pos
from pos.models import CashSession, Payment, Sale, SaleReturn
from pos.tests.conftest import sku
from stock.models import StockEntry
from stock.services import Inflow, post_entry

pytestmark = pytest.mark.django_db
D = Decimal
WEEK = "/api/reports/sales?from=2026-11-02&to=2026-11-03"


def utc(text: str) -> datetime:
    return datetime.fromisoformat(f"{text}+00:00")


def stock(owner: User, product: Product, store: Location, cost: str, size: str = "M", quantity: int = 10) -> None:
    post_entry(
        kind=StockEntry.Kind.PURCHASE_RECEIPT,
        operations=[Inflow(sku(product, size).pk, store.pk, quantity, D(cost))],
        user=owner,
    )


def sell(
    cashier: User,
    *items: tuple[ProductVariant, int],
    total: str,
    discount: str = "0",
    salesperson: User | None = None,
    at: str | None = None,
) -> Sale:
    sale, _ = pos.create_sale(
        user=cashier,
        client_request_id=uuid.uuid4(),
        items=[pos.ItemInput(variant, quantity) for variant, quantity in items],
        payments=[pos.PaymentInput(Payment.Method.PIX, D(total))],
        discount=D(discount),
        salesperson=salesperson,
    )
    if at:
        Sale.objects.filter(pk=sale.pk).update(created_at=utc(at))
    return sale


def give_back(cashier: User, store: Location, sale: Sale, quantity: int, at: str | None = None) -> SaleReturn:
    returned = pos.return_items(
        user=cashier,
        location=store,
        lines=[pos.ReturnInput(quantity=quantity, sale_item_id=sale.items.get().pk)],
        refund_method=SaleReturn.Refund.STORE_CREDIT,
        reason="Não serviu",
        original_sale=sale,
    )
    if at:
        SaleReturn.objects.filter(pk=returned.pk).update(created_at=utc(at))
    return returned


@pytest.fixture
def week(
    make_user: Callable[..., User],
    make_product: Callable[..., Product],
    owner: User,
    cashier: User,
    session: CashSession,
    shirt: Product,
    store: Location,
) -> dict[str, User]:
    """
    Two days at the Centro store (São Paulo time). Shirts R$ 79,90 cost R$ 30,00; trousers
    R$ 150,00 cost R$ 60,00.
      Nov 2: Ana sells 2 shirts (159.80). Bia sells trousers with 10.00 off (140.00) at 22:30,
             which is already Nov 3 in UTC.
      Nov 3: Ana sells a shirt (79.90). One shirt of the Nov 2 sale comes back (79.90).
             A sale by Ana is cancelled: it counts for nothing.
      Nov 4, 00:30: a sale outside the period.
    """
    ana = make_user(Role.CASHIER, name="Ana")
    bia = make_user(Role.CASHIER, name="Bia")
    trousers = make_product(reference="CAL-001", name="Calça sarja", price="150.00")
    stock(owner, trousers, store, "60.00")
    first = sell(cashier, (sku(shirt, "M"), 2), total="159.80", salesperson=ana, at="2026-11-02T18:00")
    sell(cashier, (sku(trousers), 1), total="140.00", discount="10.00", salesperson=bia, at="2026-11-03T01:30")
    sell(cashier, (sku(shirt, "G"), 1), total="79.90", salesperson=ana, at="2026-11-03T14:00")
    give_back(cashier, store, first, 1, at="2026-11-03T16:00")
    cancelled = sell(cashier, (sku(shirt, "P"), 1), total="79.90", salesperson=ana, at="2026-11-03T15:00")
    pos.cancel_sale(user=cashier, sale=cancelled, reason="Desistiu")
    sell(cashier, (sku(shirt, "GG"), 1), total="79.90", at="2026-11-04T03:30")
    return {"ana": ana, "bia": bia}


class TestSalesSummary:
    def test_days_and_total(self, api_as: Callable[..., APIClient], week: dict[str, User]) -> None:
        report = api_as(Role.MANAGER).get(WEEK).json()
        assert report["days"] == [
            {
                "day": "2026-11-02",
                "sales": 2,
                "units": 3,
                "gross": "309.80",
                "discounts": "10.00",
                "returns": "0.00",
                "net": "299.80",
                "average_ticket": "149.90",
                "cogs": "120.00",
                "margin": "179.80",
                "margin_percent": "60.0",  # 179.80 / 299.80 = 59.97%
            },
            {
                # The shirt sold and the one returned cancel out, in pieces, money and cost.
                "day": "2026-11-03",
                "sales": 1,
                "units": 0,
                "gross": "79.90",
                "discounts": "0.00",
                "returns": "79.90",
                "net": "0.00",
                "average_ticket": "79.90",
                "cogs": "0.00",
                "margin": "0.00",
                "margin_percent": None,
            },
        ]
        assert report["total"] == {
            "sales": 3,
            "units": 3,
            "gross": "389.70",
            "discounts": "10.00",
            "returns": "79.90",
            "net": "299.80",
            "average_ticket": "126.57",  # 379.70 sold / 3 sales, before returns
            "cogs": "120.00",
            "margin": "179.80",
            "margin_percent": "60.0",
        }

    def test_margin_needs_its_capability(
        self, api_as: Callable[..., APIClient], week: dict[str, User], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        without = ROLE_CAPABILITIES[Role.MANAGER] - {Capability.REPORTS_MARGIN}
        monkeypatch.setitem(ROLE_CAPABILITIES, Role.MANAGER, without)
        report = api_as(Role.MANAGER).get(WEEK).json()
        assert report["total"]["net"] == "299.80"
        assert {"cogs", "margin", "margin_percent"}.isdisjoint(report["total"])
        assert all({"cogs", "margin"}.isdisjoint(day) for day in report["days"])

    def test_only_the_users_stores(
        self,
        api_as: Callable[..., APIClient],
        make_user: Callable[..., User],
        week: dict[str, User],
        store: Location,
        other_store: Location,
    ) -> None:
        elsewhere = api_as(user=make_user(Role.MANAGER, locations=[other_store]))
        assert elsewhere.get(WEEK).json()["total"]["sales"] == 0
        assert elsewhere.get(f"{WEEK}&location={store.pk}").status_code == 403
        owner = api_as(Role.OWNER)
        assert owner.get(f"{WEEK}&location={store.pk}").json()["total"]["net"] == "299.80"
        assert owner.get(f"{WEEK}&location={other_store.pk}").json()["total"]["net"] == "0.00"

    @pytest.mark.parametrize(
        ("query", "status", "code"),
        [
            ("from=2026-11-03&to=2026-11-02", 422, "period_inverted"),
            ("from=2025-01-01&to=2026-11-02", 422, "period_too_long"),
            ("from=02/11/2026", 400, None),
            ("location=abc", 400, None),
        ],
    )
    def test_bad_queries(self, api_as: Callable[..., APIClient], query: str, status: int, code: str | None) -> None:
        response = api_as(Role.OWNER).get(f"/api/reports/sales?{query}")
        assert response.status_code == status
        assert response.json().get("code") == code


def test_by_salesperson(api_as: Callable[..., APIClient], week: dict[str, User]) -> None:
    rows = api_as(Role.MANAGER).get("/api/reports/salespeople?from=2026-11-02&to=2026-11-03").json()
    # Ana: 159.80 + 79.90 sold, 79.90 back. Bia: 140.00. The cancelled sale is nobody's.
    assert [(r["name"], r["sales"], r["net"], r["average_ticket"]) for r in rows] == [
        ("Ana", 2, "159.80", "119.85"),
        ("Bia", 1, "140.00", "140.00"),
    ]


def test_abc_curve(
    api_as: Callable[..., APIClient],
    make_product: Callable[..., Product],
    owner: User,
    cashier: User,
    session: CashSession,
    store: Location,
) -> None:
    for n, price in enumerate(["50.00", "500.00", "150.00", "300.00"], 1):
        product = make_product(reference=f"ABC-{n}", name=f"Peça {price}", price=price)
        stock(owner, product, store, "10.00")
        sell(cashier, (sku(product), 1), total=price)
    rows = api_as(Role.MANAGER).get("/api/reports/abc").json()
    # 500 is 50% (nothing before it: A); 300 brings it to 80% (it started below 80: A);
    # 150 starts at 80%: B, up to 95%; 50 starts at 95%: C.
    assert [(r["revenue"], r["share"], r["cumulative_share"], r["class"]) for r in rows] == [
        ("500.00", "50.0", "50.0", "A"),
        ("300.00", "30.0", "80.0", "A"),
        ("150.00", "15.0", "95.0", "B"),
        ("50.00", "5.0", "100.0", "C"),
    ]


def test_size_color_matrix(
    api_as: Callable[..., APIClient],
    make_product: Callable[..., Product],
    owner: User,
    cashier: User,
    session: CashSession,
    store: Location,
) -> None:
    polo = make_product(reference="POL-001", name="Polo", color_names=("preto", "branco"), price="100.00")
    black_m, white_g = (
        polo.variants.get(color__name="Preto", size__label="M"),
        polo.variants.get(color__name="Branco", size__label="G"),
    )
    for variant in (black_m, white_g):
        post_entry(
            kind=StockEntry.Kind.PURCHASE_RECEIPT,
            operations=[Inflow(variant.pk, store.pk, 5, D("40.00"))],
            user=owner,
        )
    sale = sell(cashier, (black_m, 2), total="200.00")
    sell(cashier, (white_g, 1), total="100.00")
    sell(cashier, (black_m, 1), total="100.00")
    give_back(cashier, store, sale, 1)
    report: dict[str, Any] = api_as(Role.MANAGER).get(f"/api/reports/size-color?product={polo.pk}").json()
    assert report["sizes"] == ["PP", "P", "M", "G", "GG"]
    assert report["rows"] == [
        {"color": "Branco", "units": [0, 0, 0, 1, 0]},
        {"color": "Preto", "units": [0, 0, 2, 0, 0]},  # 3 sold, 1 back
    ]
    assert (report["by_size"], report["total"]) == ([0, 0, 2, 1, 0], 3)


@pytest.mark.parametrize("role", [Role.CASHIER, Role.STOCKIST])
@pytest.mark.parametrize(
    "url", ["sales", "salespeople", "abc", "size-color?product=1", "valuation", "turnover", "stale"]
)
def test_floor_staff_see_no_reports(api_as: Callable[..., APIClient], role: Role, url: str) -> None:
    assert api_as(role).get(f"/api/reports/{url}").status_code == 403
