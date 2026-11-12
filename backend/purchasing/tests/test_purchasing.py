import threading
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from rest_framework.test import APIClient

from accounts.models import Role, User
from audit.models import AuditEvent
from catalog.models import Product, ProductVariant
from common.errors import ConflictError
from locations.models import Location
from purchasing import services
from purchasing.models import PurchaseOrder, Supplier
from stock.invariants import stock_problems
from stock.models import SkuCost, StockEntry, StockLevel
from stock.services import Outflow, post_entry

S = PurchaseOrder.Status


@pytest.fixture(autouse=True)
def _ledger_stays_consistent() -> Iterator[None]:
    yield
    assert stock_problems() == []


@pytest.fixture
def supplier() -> Supplier:
    return Supplier.objects.create(name="Malharia Serra Azul", cnpj="11222333000181")


@pytest.fixture
def shirt(make_product: Callable[..., Product]) -> Product:
    return make_product(color_names=("preto",))


def sku(product: Product, size: str) -> ProductVariant:
    return product.variants.get(size__label=size)


def order(owner: User, supplier: Supplier, store: Location, *lines: tuple[ProductVariant, int, str]) -> PurchaseOrder:
    created = services.create_order(
        user=owner,
        supplier=supplier,
        location=store,
        lines=[services.OrderLineInput(v, q, Decimal(c)) for v, q, c in lines],
    )
    return services.send_order(user=owner, order=created)


def lines_of(po: PurchaseOrder) -> dict[str, Any]:
    return {line.variant.sku: line for line in po.lines.select_related("variant")}


def qty(variant: ProductVariant, location: Location) -> int:
    level = StockLevel.objects.filter(variant=variant, location=location).first()
    return level.quantity if level else 0


def cost(variant: ProductVariant) -> tuple[int, Decimal]:
    row = SkuCost.objects.get(variant=variant)
    return row.quantity, row.value


@pytest.mark.django_db
class TestOrders:
    def test_a_draft_is_numbered_and_editable_until_sent(
        self, owner: User, supplier: Supplier, store: Location, shirt: Product
    ) -> None:
        draft = services.create_order(
            user=owner,
            supplier=supplier,
            location=store,
            lines=[services.OrderLineInput(sku(shirt, "M"), 5, Decimal("20"))],
        )
        assert draft.number.startswith("PC-")
        assert draft.status == S.DRAFT
        services.replace_lines(
            user=owner, order=draft, lines=[services.OrderLineInput(sku(shirt, "G"), 3, Decimal("21"))]
        )
        services.send_order(user=owner, order=draft)
        with pytest.raises(ConflictError, match="rascunho"):
            services.replace_lines(
                user=owner, order=draft, lines=[services.OrderLineInput(sku(shirt, "M"), 1, Decimal("1"))]
            )

    def test_partial_then_full_receipt(self, owner: User, supplier: Supplier, store: Location, shirt: Product) -> None:
        po = order(owner, supplier, store, (sku(shirt, "M"), 10, "20.00"), (sku(shirt, "G"), 4, "22.00"))
        m, g = lines_of(po)["CAM-001-PRE-M"], lines_of(po)["CAM-001-PRE-G"]
        services.receive(user=owner, order=po, lines=[services.ReceiptLineInput(m.pk, 6)], invoice_number="1234")
        po.refresh_from_db()
        assert po.status == S.PARTIALLY_RECEIVED
        assert (qty(sku(shirt, "M"), store), cost(sku(shirt, "M"))) == (6, (6, Decimal("120.0000")))
        services.receive(
            user=owner, order=po, lines=[services.ReceiptLineInput(m.pk, 4), services.ReceiptLineInput(g.pk, 4)]
        )
        po.refresh_from_db()
        assert po.status == S.RECEIVED
        assert po.finished_at is not None

    def test_never_more_than_pending(self, owner: User, supplier: Supplier, store: Location, shirt: Product) -> None:
        po = order(owner, supplier, store, (sku(shirt, "M"), 3, "20.00"))
        line = lines_of(po)["CAM-001-PRE-M"]
        with pytest.raises(ConflictError, match="pendente 3"):
            services.receive(user=owner, order=po, lines=[services.ReceiptLineInput(line.pk, 4)])
        assert qty(sku(shirt, "M"), store) == 0

    def test_nothing_is_received_on_a_draft(
        self, owner: User, supplier: Supplier, store: Location, shirt: Product
    ) -> None:
        draft = services.create_order(
            user=owner,
            supplier=supplier,
            location=store,
            lines=[services.OrderLineInput(sku(shirt, "M"), 1, Decimal("1"))],
        )
        with pytest.raises(ConflictError, match="nada a receber"):
            services.receive(user=owner, order=draft, lines=[services.ReceiptLineInput(draft.lines.get().pk, 1)])

    def test_invoice_cost_differs_from_the_order(
        self, owner: User, supplier: Supplier, store: Location, shirt: Product
    ) -> None:
        po = order(owner, supplier, store, (sku(shirt, "M"), 2, "20.00"))
        line = lines_of(po)["CAM-001-PRE-M"]
        services.receive(user=owner, order=po, lines=[services.ReceiptLineInput(line.pk, 2, Decimal("21.50"))])
        assert cost(sku(shirt, "M")) == (2, Decimal("43.0000"))
        event = AuditEvent.objects.get(action="purchase.received")
        assert event.data["cost_differences"] == [{"sku": "CAM-001-PRE-M", "ordered": "20.0000", "invoiced": "21.50"}]

    def test_cancelling_and_closing(self, owner: User, supplier: Supplier, store: Location, shirt: Product) -> None:
        po = order(owner, supplier, store, (sku(shirt, "M"), 5, "20.00"))
        services.receive(user=owner, order=po, lines=[services.ReceiptLineInput(lines_of(po)["CAM-001-PRE-M"].pk, 2)])
        with pytest.raises(ConflictError, match="encerre com pendência"):
            services.cancel_order(user=owner, order=po, reason="desisti")
        closed = services.close_order(user=owner, order=po, reason="Fornecedor sem a cor preta")
        assert (closed.status, closed.finish_reason) == (S.CLOSED, "Fornecedor sem a cor preta")
        with pytest.raises(ConflictError, match="nada a receber"):
            services.receive(
                user=owner, order=po, lines=[services.ReceiptLineInput(lines_of(po)["CAM-001-PRE-M"].pk, 1)]
            )


@pytest.mark.django_db
class TestReceiptCancellation:
    def test_undone_exactly_while_untouched(
        self, owner: User, supplier: Supplier, store: Location, shirt: Product
    ) -> None:
        first = order(owner, supplier, store, (sku(shirt, "M"), 2, "10.00"))
        services.receive(
            user=owner, order=first, lines=[services.ReceiptLineInput(lines_of(first)["CAM-001-PRE-M"].pk, 2)]
        )
        second = order(owner, supplier, store, (sku(shirt, "M"), 3, "14.00"))
        receipt = services.receive(
            user=owner, order=second, lines=[services.ReceiptLineInput(lines_of(second)["CAM-001-PRE-M"].pk, 3)]
        )
        services.cancel_receipt(user=owner, receipt=receipt, reason="Nota lançada no pedido errado")
        assert cost(sku(shirt, "M")) == (2, Decimal("20.0000"))
        second.refresh_from_db()
        assert second.status == S.SENT
        assert lines_of(second)["CAM-001-PRE-M"].quantity_received == 0
        with pytest.raises(ConflictError, match="já foi estornado"):
            services.cancel_receipt(user=owner, receipt=receipt, reason="de novo")

    def test_blocked_once_goods_have_left(
        self, owner: User, supplier: Supplier, store: Location, shirt: Product
    ) -> None:
        po = order(owner, supplier, store, (sku(shirt, "M"), 3, "10.00"))
        receipt = services.receive(
            user=owner, order=po, lines=[services.ReceiptLineInput(lines_of(po)["CAM-001-PRE-M"].pk, 3)]
        )
        post_entry(kind=StockEntry.Kind.SALE, operations=[Outflow(sku(shirt, "M").pk, store.pk, 1)], user=owner)
        with pytest.raises(ConflictError, match="devolução ao fornecedor"):
            services.cancel_receipt(user=owner, receipt=receipt, reason="erro")

    def test_a_return_leaves_at_the_average(
        self, owner: User, supplier: Supplier, store: Location, shirt: Product
    ) -> None:
        po = order(owner, supplier, store, (sku(shirt, "M"), 2, "10.00"), (sku(shirt, "G"), 1, "10.00"))
        services.receive(
            user=owner,
            order=po,
            lines=[services.ReceiptLineInput(line.pk, line.quantity_ordered) for line in lines_of(po).values()],
        )
        more = order(owner, supplier, store, (sku(shirt, "M"), 2, "14.00"))
        services.receive(
            user=owner, order=more, lines=[services.ReceiptLineInput(lines_of(more)["CAM-001-PRE-M"].pk, 2)]
        )
        services.return_to_supplier(
            user=owner, supplier=supplier, location=store, lines=[(sku(shirt, "M"), 1)], reason="Defeito de costura"
        )
        assert cost(sku(shirt, "M")) == (3, Decimal("36.0000"))  # average 12.00, one out at 12.00


@pytest.mark.django_db
def test_restock_suggestions_count_what_is_on_order(
    owner: User, supplier: Supplier, store: Location, shirt: Product, api_as: Callable[..., APIClient]
) -> None:
    m, g = sku(shirt, "M"), sku(shirt, "G")
    po = order(owner, supplier, store, (m, 1, "20.00"), (g, 2, "20.00"))
    services.receive(user=owner, order=po, lines=[services.ReceiptLineInput(lines_of(po)["CAM-001-PRE-M"].pk, 1)])
    StockLevel.objects.filter(variant=m, location=store).update(min_quantity=5, max_quantity=10)
    StockLevel.objects.bulk_create([StockLevel(variant=g, location=store, min_quantity=2)], ignore_conflicts=True)
    StockLevel.objects.filter(variant=g, location=store).update(min_quantity=2)
    rows = api_as(Role.MANAGER).get("/api/purchasing/suggestions").json()
    # M: 1 in stock, nothing pending (received) → refill to the maximum, 10 - 1 = 9.
    # G: 0 in stock, but 2 on order → already covered, no suggestion.
    assert [(r["sku"], r["quantity"], r["on_order"], r["suggested"], r["last_unit_cost"]) for r in rows] == [
        ("CAM-001-PRE-M", 1, 0, 9, "20.0000")
    ]


@pytest.mark.django_db
def test_suggestions_quote_the_latest_receipt(
    owner: User, supplier: Supplier, store: Location, shirt: Product, api_as: Callable[..., APIClient]
) -> None:
    m = sku(shirt, "M")
    other = Supplier.objects.create(name="Outra Malharia")
    for who, cost in ((supplier, "20.00"), (other, "25.00")):
        po = order(owner, who, store, (m, 1, cost))
        services.receive(user=owner, order=po, lines=[services.ReceiptLineInput(lines_of(po)["CAM-001-PRE-M"].pk, 1)])
    StockLevel.objects.filter(variant=m, location=store).update(min_quantity=5, max_quantity=10)
    [row] = api_as(Role.MANAGER).get("/api/purchasing/suggestions").json()
    assert (row["last_supplier"], row["last_unit_cost"], row["suggested"]) == (other.pk, "25.0000", 8)


@pytest.mark.django_db
class TestApi:
    def test_the_stockist_receives_without_seeing_or_changing_costs(
        self, owner: User, supplier: Supplier, store: Location, shirt: Product, api_as: Callable[..., APIClient]
    ) -> None:
        po = order(owner, supplier, store, (sku(shirt, "M"), 4, "20.00"))
        line_id = lines_of(po)["CAM-001-PRE-M"].pk
        stockist = api_as(Role.STOCKIST)
        detail = stockist.get(f"/api/purchasing/orders/{po.pk}").json()
        assert "total_cost" not in detail
        assert "unit_cost" not in detail["lines"][0]
        url = f"/api/purchasing/orders/{po.pk}/receive"
        refused = stockist.post(
            url, {"lines": [{"order_line": line_id, "quantity": 1, "unit_cost": "1.00"}]}, format="json"
        )
        assert refused.json()["code"] == "receipt_cost_not_allowed"
        ok = stockist.post(
            url, {"invoice_number": "998", "lines": [{"order_line": line_id, "quantity": 4}]}, format="json"
        )
        assert ok.status_code == 201
        assert "unit_cost" not in ok.json()["lines"][0]
        assert cost(sku(shirt, "M")) == (4, Decimal("80.0000"))

    def test_who_buys(
        self, supplier: Supplier, store: Location, shirt: Product, api_as: Callable[..., APIClient]
    ) -> None:
        payload = {
            "supplier": supplier.pk,
            "location": store.pk,
            "lines": [{"variant": sku(shirt, "M").pk, "quantity": 2, "unit_cost": "20.00"}],
        }
        for role in (Role.CASHIER, Role.STOCKIST):
            assert api_as(role).post("/api/purchasing/orders", payload, format="json").status_code == 403
        created = api_as(Role.MANAGER).post("/api/purchasing/orders", payload, format="json")
        assert created.status_code == 201
        assert created.json()["total_cost"] == "40.00"
        assert api_as(Role.CASHIER).get("/api/purchasing/orders").status_code == 403

    def test_a_manager_buys_only_for_their_stores(
        self, supplier: Supplier, other_store: Location, shirt: Product, api_as: Callable[..., APIClient]
    ) -> None:
        payload = {
            "supplier": supplier.pk,
            "location": other_store.pk,
            "lines": [{"variant": sku(shirt, "M").pk, "quantity": 2, "unit_cost": "20.00"}],
        }
        response = api_as(Role.MANAGER).post("/api/purchasing/orders", payload, format="json")
        assert response.json()["code"] == "location_not_allowed"


@pytest.mark.django_db(transaction=True)
def test_two_people_receiving_the_same_last_pieces(
    owner: User, supplier: Supplier, store: Location, shirt: Product
) -> None:
    po = order(owner, supplier, store, (sku(shirt, "M"), 5, "20.00"))
    line_id = lines_of(po)["CAM-001-PRE-M"].pk
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def receive_all() -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            barrier.wait()
            services.receive(user=owner, order=po, lines=[services.ReceiptLineInput(line_id, 3)])
            outcomes.append("received")
        except ConflictError as error:
            outcomes.append(error.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=receive_all) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    # 3 + 3 > 5: whoever gets the order's lock second sees only 2 pending.
    assert sorted(outcomes) == ["receipt_over_pending", "received"]
    assert qty(sku(shirt, "M"), store) == 3


@pytest.mark.django_db
def test_suppliers_accept_masked_and_alphanumeric_cnpjs(api_as: Callable[..., APIClient]) -> None:
    client = api_as(Role.MANAGER)
    first = client.post(
        "/api/purchasing/suppliers", {"name": "Malharia A", "cnpj": "11.222.333/0001-81"}, format="json"
    )
    second = client.post(
        "/api/purchasing/suppliers", {"name": "Tecelagem B", "cnpj": "12.abc.345/01de-35"}, format="json"
    )
    assert (first.json()["cnpj"], second.json()["cnpj"]) == ("11222333000181", "12ABC34501DE35")
    wrong = client.post("/api/purchasing/suppliers", {"name": "C", "cnpj": "11.222.333/0001-82"}, format="json")
    assert wrong.json() == {"cnpj": ["CNPJ inválido."]}
    again = client.post("/api/purchasing/suppliers", {"name": "D", "cnpj": "11222333000181"}, format="json")
    assert again.json() == {"cnpj": ["Já existe um fornecedor com este CNPJ."]}
