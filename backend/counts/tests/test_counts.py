from collections.abc import Callable, Iterator
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, User
from catalog.models import Barcode, Product, ProductVariant
from common.errors import ConflictError, DomainError
from common.integrity import all_problems
from counts import services
from counts.models import InventoryCount
from locations.models import Location
from stock.models import SkuCost, StockEntry, StockLevel
from stock.services import Inflow, Outflow, post_entry

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _everything_agrees() -> Iterator[None]:
    yield
    assert all_problems() == []


@pytest.fixture
def shirt(make_product: Callable[..., Product]) -> Product:
    return make_product()


def sku(product: Product, size: str = "M") -> ProductVariant:
    return product.variants.get(size__label=size)


def stocked(owner: User, variant: ProductVariant, location: Location, quantity: int, unit_cost: str = "20.00") -> None:
    post_entry(
        kind=StockEntry.Kind.PURCHASE_RECEIPT,
        operations=[Inflow(variant.pk, location.pk, quantity, Decimal(unit_cost))],
        user=owner,
    )


def sell(owner: User, variant: ProductVariant, location: Location, quantity: int = 1) -> None:
    post_entry(kind=StockEntry.Kind.SALE, operations=[Outflow(variant.pk, location.pk, quantity)], user=owner)


def qty(variant: ProductVariant, location: Location) -> int:
    level = StockLevel.objects.filter(variant=variant, location=location).first()
    return level.quantity if level else 0


def counted(owner: User, count: InventoryCount, variant: ProductVariant, quantity: int, area: str = "Loja") -> None:
    services.add_entry(user=owner, count=count, code=variant.sku, quantity=quantity, area=area)


def row(count: InventoryCount, variant: ProductVariant) -> services.ReviewRow:
    return next(r for r in services.review(count) if r.variant_id == variant.pk)


def finished(owner: User, count: InventoryCount) -> InventoryCount:
    return services.finish(user=owner, count=count)


def test_areas_add_up_and_the_shortfall_is_written_off(owner: User, shirt: Product, store: Location) -> None:
    stocked(owner, sku(shirt), store, 5)
    count = services.open_count(user=owner, location=store, product_ids=[shirt.pk])
    counted(owner, count, sku(shirt), 1, "Vitrine")
    counted(owner, count, sku(shirt), 3, "Estoque")
    finished(owner, count)
    result = row(count, sku(shirt))
    assert (result.counted, result.expected, result.difference) == (4, 5, -1)
    assert result.areas == {"Vitrine": 1, "Estoque": 3}
    services.apply(user=owner, count=count, uncounted="keep")
    assert qty(sku(shirt), store) == 4
    assert SkuCost.objects.get(variant=sku(shirt)).value == Decimal("80.0000")


def test_found_pieces_enter_at_the_average(owner: User, shirt: Product, store: Location) -> None:
    stocked(owner, sku(shirt), store, 2, "30.00")
    count = services.open_count(user=owner, location=store, product_ids=[shirt.pk])
    counted(owner, count, sku(shirt), 3)
    services.apply(user=owner, count=finished(owner, count), uncounted="keep")
    assert (qty(sku(shirt), store), SkuCost.objects.get(variant=sku(shirt)).value) == (3, Decimal("90.0000"))


def test_a_sale_after_counting_is_not_lost(owner: User, shirt: Product, store: Location) -> None:
    # Applying adds the difference to the balance of the moment, never "sets" it.
    stocked(owner, sku(shirt), store, 5)
    count = services.open_count(user=owner, location=store, product_ids=[shirt.pk])
    counted(owner, count, sku(shirt), 5)
    sell(owner, sku(shirt), store)
    services.apply(user=owner, count=finished(owner, count), uncounted="keep")
    assert qty(sku(shirt), store) == 4


def test_movement_between_areas_is_flagged_for_recount(owner: User, shirt: Product, store: Location) -> None:
    stocked(owner, sku(shirt), store, 5)
    count = services.open_count(user=owner, location=store, product_ids=[shirt.pk])
    counted(owner, count, sku(shirt), 2, "Vitrine")
    sell(owner, sku(shirt), store)  # which area was this piece in? The system can't know.
    counted(owner, count, sku(shirt), 2, "Estoque")
    finished(owner, count)
    assert row(count, sku(shirt)).moved_during_count
    assert row(count, sku(shirt)).needs_recount
    services.recount(user=owner, count=count, variant_ids=[sku(shirt).pk])
    counted(owner, count, sku(shirt), 4)
    finished(owner, count)
    assert (row(count, sku(shirt)).difference, row(count, sku(shirt)).needs_recount) == (0, False)


def test_tolerance(owner: User, shirt: Product, store: Location) -> None:
    stocked(owner, sku(shirt), store, 10)
    count = services.open_count(user=owner, location=store, product_ids=[shirt.pk], tolerance=1)
    counted(owner, count, sku(shirt), 9)
    finished(owner, count)
    assert (row(count, sku(shirt)).difference, row(count, sku(shirt)).needs_recount) == (-1, False)


def test_uncounted_stock_must_be_decided(owner: User, shirt: Product, store: Location) -> None:
    stocked(owner, sku(shirt, "M"), store, 3)
    stocked(owner, sku(shirt, "G"), store, 2)
    count = services.open_count(user=owner, location=store, product_ids=[shirt.pk])
    counted(owner, count, sku(shirt, "M"), 3)
    finished(owner, count)
    with pytest.raises(DomainError) as raised:
        services.apply(user=owner, count=count)
    assert raised.value.details["uncounted"] == [{"sku": sku(shirt, "G").sku, "current": 2}]
    services.apply(user=owner, count=count, uncounted="zero")
    assert (qty(sku(shirt, "M"), store), qty(sku(shirt, "G"), store)) == (3, 0)


def test_scope_and_codes(owner: User, shirt: Product, make_product: Callable[..., Product], store: Location) -> None:
    pants = make_product(reference="CAL-001", name="Calça")
    count = services.open_count(user=owner, location=store, product_ids=[shirt.pk])
    internal = Barcode.objects.get(variant=sku(shirt), kind=Barcode.Kind.INTERNAL).code
    services.add_entry(user=owner, count=count, code=internal, quantity=1, area="Loja")
    with pytest.raises(DomainError, match="fora do escopo"):
        services.add_entry(user=owner, count=count, code=sku(pants).sku, quantity=1, area="Loja")


def test_one_active_count_per_location(owner: User, shirt: Product, store: Location) -> None:
    services.open_count(user=owner, location=store)
    with pytest.raises(ConflictError, match="em andamento"):
        services.open_count(user=owner, location=store)


class TestApi:
    def test_the_count_is_blind_for_the_stockist(
        self, api_as: Callable[..., APIClient], owner: User, shirt: Product, store: Location
    ) -> None:
        stocked(owner, sku(shirt), store, 7)
        manager, stockist = api_as(Role.MANAGER), api_as(Role.STOCKIST)
        count = manager.post("/api/counts", {"location": store.pk, "products": [shirt.pk]}, format="json").json()
        url = f"/api/counts/{count['id']}"
        entry = stockist.post(
            f"{url}/entries", {"code": sku(shirt).sku, "quantity": 6, "area": "Vitrine"}, format="json"
        )
        assert entry.status_code == 201
        assert "system_quantity" not in entry.json()
        assert all("system_quantity" not in e for e in stockist.get(f"{url}/entries").json())
        assert stockist.get(f"{url}/review").status_code == 403
        assert stockist.post(f"{url}/finish").json()["code"] == "count_not_allowed"
        manager.post(f"{url}/finish")
        review = manager.get(f"{url}/review").json()
        assert [(r["sku"], r["counted"], r["expected"]) for r in review if r["counted"] is not None] == [
            (sku(shirt).sku, 6, 7)
        ]
        applied = manager.post(f"{url}/apply", {"uncounted": "keep"}, format="json")
        assert applied.json()["status"] == "applied"
        assert qty(sku(shirt), store) == 6

    def test_cashiers_do_not_count(self, api_as: Callable[..., APIClient]) -> None:
        assert api_as(Role.CASHIER).get("/api/counts").status_code == 403
