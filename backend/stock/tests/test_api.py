from collections.abc import Callable, Iterator
from datetime import timedelta
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Approval, Role, User
from audit.models import AuditEvent
from catalog.models import Product, ProductVariant
from locations.models import Location
from stock.invariants import stock_problems
from stock.models import StockEntry, StockLevel
from stock.services import Inflow, post_entry

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _ledger_stays_consistent() -> Iterator[None]:
    yield
    assert stock_problems() == []


@pytest.fixture
def shirt(make_product: Callable[..., Product]) -> Product:
    return make_product(color_names=("preto", "branco"))


def sku(product: Product, color: str = "Preto", size: str = "M") -> ProductVariant:
    return product.variants.get(color__name=color, size__label=size)


def stock(owner: User, variant: ProductVariant, location: Location, quantity: int, unit_cost: str = "20.00") -> None:
    post_entry(
        kind=StockEntry.Kind.PURCHASE_RECEIPT,
        operations=[Inflow(variant.pk, location.pk, quantity, Decimal(unit_cost))],
        user=owner,
    )


def levels(client: APIClient, **params: str | int) -> list[dict[str, object]]:
    response = client.get("/api/stock/levels", params)
    assert response.status_code == 200
    return response.json()["results"]  # type: ignore[no-any-return]


class TestReading:
    def test_costs_are_for_those_who_may_see_them(
        self, api_as: Callable[..., APIClient], owner: User, shirt: Product, store: Location
    ) -> None:
        stock(owner, sku(shirt), store, 4, "20.00")
        cashier_view = levels(api_as(Role.CASHIER))[0]
        manager_view = levels(api_as(Role.MANAGER))[0]
        assert cashier_view["quantity"] == manager_view["quantity"] == 4
        assert "average_cost" not in cashier_view
        assert "stock_value" not in cashier_view
        assert (manager_view["average_cost"], manager_view["stock_value"]) == ("20.0000", "80.00")

    def test_each_person_sees_their_locations(
        self, api_as: Callable[..., APIClient], owner: User, shirt: Product, store: Location, other_store: Location
    ) -> None:
        stock(owner, sku(shirt), store, 1)
        stock(owner, sku(shirt), other_store, 2)
        assert [lvl["location_code"] for lvl in levels(api_as(Role.MANAGER, locations=[other_store]))] == ["SHOP"]
        assert sorted(str(lvl["location_code"]) for lvl in levels(api_as(Role.OWNER))) == ["CENTRO", "SHOP"]

    def test_the_ledger_hides_costs_too(
        self, api_as: Callable[..., APIClient], owner: User, shirt: Product, store: Location
    ) -> None:
        stock(owner, sku(shirt), store, 3)
        line = api_as(Role.STOCKIST).get("/api/stock/movements").json()["results"][0]
        assert (line["kind"], line["quantity_delta"], line["balance_after"]) == ("purchase_receipt", 3, 3)
        assert "unit_cost" not in line
        assert "value_delta" not in line

    def test_the_size_by_color_grid(
        self, api_as: Callable[..., APIClient], owner: User, shirt: Product, store: Location, other_store: Location
    ) -> None:
        stock(owner, sku(shirt, "Preto", "M"), store, 3)
        stock(owner, sku(shirt, "Preto", "M"), other_store, 2)
        stock(owner, sku(shirt, "Branco", "GG"), store, 1)
        grid = api_as(Role.OWNER).get("/api/stock/grid", {"product": shirt.pk}).json()
        assert grid["sizes"] == ["PP", "P", "M", "G", "GG"]
        assert grid["rows"] == [
            {"color": "Branco", "quantities": [0, 0, 0, 0, 1]},
            {"color": "Preto", "quantities": [0, 0, 5, 0, 0]},
        ]
        one_store = api_as(Role.OWNER).get("/api/stock/grid", {"product": shirt.pk, "location": store.pk}).json()
        assert one_store["rows"][1]["quantities"] == [0, 0, 3, 0, 0]

    def test_restock_targets(
        self, api_as: Callable[..., APIClient], owner: User, shirt: Product, store: Location
    ) -> None:
        stock(owner, sku(shirt), store, 2)
        level = StockLevel.objects.get(variant=sku(shirt), location=store)
        url = f"/api/stock/levels/{level.pk}"
        assert api_as(Role.CASHIER).patch(url, {"min_quantity": 5}, format="json").status_code == 403
        manager = api_as(Role.MANAGER)
        assert manager.patch(url, {"min_quantity": 5, "max_quantity": 3}, format="json").status_code == 400
        assert manager.patch(url, {"min_quantity": 5, "max_quantity": 12}, format="json").status_code == 200
        assert [lvl["sku"] for lvl in levels(manager, below_min=1)] == [sku(shirt).sku]

    def test_searching_by_sku_reference_or_name(
        self,
        api_as: Callable[..., APIClient],
        owner: User,
        shirt: Product,
        make_product: Callable[..., Product],
        store: Location,
    ) -> None:
        trousers = make_product(reference="CAL-020", name="Calça sarja")
        stock(owner, sku(shirt), store, 1)
        stock(owner, sku(trousers), store, 1)
        manager = api_as(Role.MANAGER)
        assert [lvl["reference"] for lvl in levels(manager, q="sarja")] == ["CAL-020"]
        assert [lvl["reference"] for lvl in levels(manager, q="cam-001")] == ["CAM-001"]
        assert [lvl["sku"] for lvl in levels(manager, q=sku(trousers).sku.lower())] == [sku(trousers).sku]


class TestAdjusting:
    def payload(self, location: Location, *lines: tuple[ProductVariant, int], **extra: object) -> dict[str, object]:
        return {
            "location": location.pk,
            "reason": "damaged",
            "lines": [{"variant": v.pk, "quantity_delta": d} for v, d in lines],
            **extra,
        }

    def test_a_manager_adjusts_their_store(
        self, api_as: Callable[..., APIClient], owner: User, shirt: Product, store: Location
    ) -> None:
        stock(owner, sku(shirt), store, 5, "20.00")
        stock(owner, sku(shirt, size="G"), store, 1, "30.00")
        response = api_as(Role.MANAGER).post(
            "/api/stock/adjustments",
            self.payload(store, (sku(shirt), -2), (sku(shirt, size="G"), 1), note="Manchas na vitrine"),
            format="json",
        )
        assert response.status_code == 201, response.json()
        assert [(m["sku"], m["quantity_delta"], m["balance_after"]) for m in response.json()["movements"]] == [
            ("CAM-001-PRE-M", -2, 3),
            ("CAM-001-PRE-G", 1, 2),
        ]
        losses = Location.objects.get(kind=Location.Kind.LOSS)
        assert StockLevel.objects.get(variant=sku(shirt), location=losses).quantity == 2
        event = AuditEvent.objects.get(action="stock.adjusted")
        assert event.data["lines"] == [{"sku": "CAM-001-PRE-M", "delta": -2}, {"sku": "CAM-001-PRE-G", "delta": 1}]

    def test_others_need_a_managers_approval(
        self,
        api_as: Callable[..., APIClient],
        make_user: Callable[..., User],
        owner: User,
        shirt: Product,
        store: Location,
    ) -> None:
        stock(owner, sku(shirt), store, 1)
        cashier = make_user(Role.CASHIER)
        client = api_as(user=cashier)
        refused = client.post(
            "/api/stock/adjustments", self.payload(store, (sku(shirt), 1), reason="found"), format="json"
        )
        assert refused.json()["code"] == "adjustment_needs_approval"
        approval = Approval.objects.create(
            action=Approval.Action.STOCK_ADJUSTMENT,
            approver=make_user(Role.MANAGER),
            requested_by=cashier,
            location=store,
            reason="Peça na arara sem entrada lançada",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        body = self.payload(store, (sku(shirt), 1), reason="found", approval=approval.pk)
        assert client.post("/api/stock/adjustments", body, format="json").status_code == 201
        assert StockEntry.objects.get(kind="adjustment").approval == approval
        assert client.post("/api/stock/adjustments", body, format="json").json()["code"] == "approval_used"

    def test_not_outside_ones_locations(
        self, api_as: Callable[..., APIClient], owner: User, shirt: Product, other_store: Location
    ) -> None:
        stock(owner, sku(shirt), other_store, 3)
        response = api_as(Role.MANAGER).post(
            "/api/stock/adjustments", self.payload(other_store, (sku(shirt), -1)), format="json"
        )
        assert response.status_code == 400

    def test_more_than_there_is(
        self, api_as: Callable[..., APIClient], owner: User, shirt: Product, store: Location
    ) -> None:
        stock(owner, sku(shirt), store, 1)
        response = api_as(Role.MANAGER).post(
            "/api/stock/adjustments", self.payload(store, (sku(shirt), -3)), format="json"
        )
        assert response.status_code == 409
        assert response.json()["shortages"] == [
            {"sku": "CAM-001-PRE-M", "location": "Loja Centro", "available": 1, "requested": 3}
        ]
