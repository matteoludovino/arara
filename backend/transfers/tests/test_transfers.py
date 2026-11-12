from collections.abc import Callable, Iterator
from decimal import Decimal

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, User
from audit.models import AuditEvent
from catalog.models import Product, ProductVariant
from common.errors import ConflictError, DomainError
from common.integrity import all_problems
from locations.models import Location
from stock.models import SkuCost, StockEntry, StockLevel
from stock.services import Inflow, InsufficientStock, post_entry
from transfers import services
from transfers.models import Transfer

pytestmark = pytest.mark.django_db
S = Transfer.Status


@pytest.fixture(autouse=True)
def _everything_agrees() -> Iterator[None]:
    yield
    assert all_problems() == []


@pytest.fixture
def m(make_product: Callable[..., Product]) -> ProductVariant:
    return make_product().variants.get(size__label="M")


def qty(variant: ProductVariant, kind_or_location: Location | str) -> int:
    location = (
        kind_or_location if isinstance(kind_or_location, Location) else Location.objects.get(kind=kind_or_location)
    )
    level = StockLevel.objects.filter(variant=variant, location=location).first()
    return level.quantity if level else 0


def stocked(owner: User, variant: ProductVariant, location: Location, quantity: int) -> None:
    post_entry(
        kind=StockEntry.Kind.PURCHASE_RECEIPT,
        operations=[Inflow(variant.pk, location.pk, quantity, Decimal("20.00"))],
        user=owner,
    )


def sent(owner: User, variant: ProductVariant, origin: Location, destination: Location, quantity: int) -> Transfer:
    transfer = services.create(user=owner, origin=origin, destination=destination, lines=[(variant, quantity)])
    return services.dispatch(user=owner, transfer=transfer)


def test_goods_travel_through_transit(owner: User, m: ProductVariant, store: Location, other_store: Location) -> None:
    stocked(owner, m, store, 10)
    transfer = sent(owner, m, store, other_store, 4)
    assert transfer.number.startswith("TR-")
    assert (qty(m, store), qty(m, "transit"), qty(m, other_store)) == (6, 4, 0)
    line = transfer.lines.get()
    services.receive(user=owner, transfer=transfer, received={line.pk: 4})
    assert (qty(m, store), qty(m, "transit"), qty(m, other_store)) == (6, 0, 4)
    assert SkuCost.objects.get(variant=m).value == Decimal("200.0000")  # moving goods doesn't change their cost


def test_what_did_not_arrive_is_a_recorded_loss(
    owner: User, m: ProductVariant, store: Location, other_store: Location
) -> None:
    stocked(owner, m, store, 5)
    transfer = sent(owner, m, store, other_store, 5)
    line = transfer.lines.get()
    with pytest.raises(DomainError, match="informe o motivo"):
        services.receive(user=owner, transfer=transfer, received={line.pk: 4})
    services.receive(user=owner, transfer=transfer, received={line.pk: 4}, missing_reason="Caixa chegou aberta")
    assert (qty(m, other_store), qty(m, "transit"), qty(m, "loss")) == (4, 0, 1)
    assert SkuCost.objects.get(variant=m).quantity == 4  # the lost piece left the inventory
    event = AuditEvent.objects.get(action="transfer.shortage")
    assert event.data["lines"] == [{"sku": m.sku, "sent": 5, "received": 4}]


def test_more_than_was_sent_is_refused(owner: User, m: ProductVariant, store: Location, other_store: Location) -> None:
    stocked(owner, m, store, 2)
    transfer = sent(owner, m, store, other_store, 2)
    with pytest.raises(DomainError, match="enviado 2"):
        services.receive(user=owner, transfer=transfer, received={transfer.lines.get().pk: 3})


def test_cancelling_on_the_road_brings_goods_back(
    owner: User, m: ProductVariant, store: Location, other_store: Location
) -> None:
    stocked(owner, m, store, 3)
    transfer = sent(owner, m, store, other_store, 3)
    services.cancel(user=owner, transfer=transfer, reason="Loja de destino fechada para reforma")
    assert (qty(m, store), qty(m, "transit")) == (3, 0)
    with pytest.raises(ConflictError, match="encerrada"):
        services.cancel(user=owner, transfer=transfer, reason="de novo")


def test_cannot_send_what_is_not_there(owner: User, m: ProductVariant, store: Location, other_store: Location) -> None:
    stocked(owner, m, store, 1)
    transfer = services.create(user=owner, origin=store, destination=other_store, lines=[(m, 2)])
    with pytest.raises(InsufficientStock):
        services.dispatch(user=owner, transfer=transfer)
    transfer.refresh_from_db()
    assert transfer.status == S.DRAFT


class TestApi:
    def test_each_side_does_its_part(
        self,
        owner: User,
        make_user: Callable[..., User],
        api_as: Callable[..., APIClient],
        m: ProductVariant,
        store: Location,
        other_store: Location,
    ) -> None:
        stocked(owner, m, store, 4)
        here = api_as(user=make_user(Role.STOCKIST, locations=[store]))
        there = api_as(user=make_user(Role.STOCKIST, locations=[other_store]))
        created = here.post(
            "/api/transfers",
            {"origin": store.pk, "destination": other_store.pk, "lines": [{"variant": m.pk, "quantity": 4}]},
            format="json",
        ).json()
        url = f"/api/transfers/{created['id']}"
        assert there.post(f"{url}/dispatch").json()["code"] == "transfer_not_allowed"
        assert here.post(f"{url}/dispatch").json()["status"] == "in_transit"
        body = {"lines": [{"line": created["lines"][0]["id"], "quantity": 4}]}
        assert here.post(f"{url}/receive", body, format="json").json()["code"] == "transfer_not_allowed"
        assert there.post(f"{url}/receive", body, format="json").json()["status"] == "received"
        assert [t["number"] for t in there.get("/api/transfers").json()["results"]] == [created["number"]]

    def test_cashiers_do_not_transfer(self, api_as: Callable[..., APIClient]) -> None:
        assert api_as(Role.CASHIER).get("/api/transfers").status_code == 403


def test_the_checker_notices_goods_in_transit_without_a_transfer(
    owner: User, m: ProductVariant, store: Location, other_store: Location
) -> None:
    stocked(owner, m, store, 2)
    transfer = sent(owner, m, store, other_store, 2)
    Transfer.objects.filter(pk=transfer.pk).update(status=S.CANCELLED)  # behind the services' back
    assert any("transit stock differs" in problem for problem in all_problems())
    Transfer.objects.filter(pk=transfer.pk).update(status=S.IN_TRANSIT)  # leave it consistent
