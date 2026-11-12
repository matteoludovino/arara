import threading
import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Approval, Role, User
from catalog.models import Product
from common.errors import ConflictError
from locations.models import Location
from pos import services
from pos.models import CashRegister, CashSession, Payment, SaleReturn, StoreCredit
from pos.tests.conftest import pay_cash, post_sale, sale_payload, sku
from stock.models import SkuCost, StockLevel

pytestmark = pytest.mark.django_db
D = Decimal


def stock_of(product: Product, location: Location, size: str = "M") -> int:
    level = StockLevel.objects.filter(variant=sku(product, size), location=location).first()
    return level.quantity if level else 0


def sold(
    client: APIClient, *items: tuple[Any, int], total: str, discount: str = "0", method: str = "pix"
) -> dict[str, Any]:
    payments = [pay_cash(total)] if method == "cash" else [{"method": method, "amount": total}]
    response = post_sale(client, sale_payload(*items, payments=payments, discount=discount))
    assert response.status_code == 201, response.json()
    return response.json()  # type: ignore[no-any-return]


def give_back(
    client: APIClient, store: Location, sale: dict[str, Any] | None, lines: list[dict[str, Any]], **extra: Any
) -> Any:
    payload = {
        "location": store.pk,
        "sale": sale["id"] if sale else None,
        "lines": lines,
        "refund_method": "store_credit",
        "reason": "Não serviu",
        **extra,
    }
    return client.post("/api/pos/returns", payload, format="json")


class TestCancelling:
    def test_a_cancelled_sale_gives_everything_back(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product, store: Location
    ) -> None:
        client = api_as(user=cashier)
        sale = sold(client, (sku(shirt, "M"), 2), (sku(shirt, "G"), 1), total="239.70", method="cash")
        assert client.get(f"/api/pos/sessions/{session.pk}/summary").json()["expected_cash"] == "339.70"
        cancelled = client.post(f"/api/pos/sales/{sale['id']}/cancel", {"reason": "Cliente desistiu"}, format="json")
        assert cancelled.json()["status"] == "cancelled"
        assert (stock_of(shirt, store, "M"), stock_of(shirt, store, "G")) == (10, 10)
        assert SkuCost.objects.get(variant=sku(shirt, "M")).value == D("300.0000")
        assert client.get(f"/api/pos/sessions/{session.pk}/summary").json()["expected_cash"] == "100.00"
        again = client.post(f"/api/pos/sales/{sale['id']}/cancel", {"reason": "de novo"}, format="json")
        assert again.json()["code"] == "sale_already_cancelled"

    def test_store_credit_spent_comes_back(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product, store: Location
    ) -> None:
        credit = services.issue_credit(user=cashier, location=store, amount=D("79.90"), source_ref="t", customer=None)
        client = api_as(user=cashier)
        payments = [{"method": "store_credit", "amount": "79.90", "store_credit_code": credit.code}]
        sale = post_sale(client, sale_payload((sku(shirt), 1), payments=payments)).json()
        client.post(f"/api/pos/sales/{sale['id']}/cancel", {"reason": "erro"}, format="json")
        credit.refresh_from_db()
        assert credit.balance == D("79.90")

    def test_after_the_shift_it_is_a_return(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product
    ) -> None:
        client = api_as(user=cashier)
        sale = sold(client, (sku(shirt), 1), total="79.90")
        services.close_session(user=cashier, session=session, counted_cash=D("100.00"))
        response = client.post(f"/api/pos/sales/{sale['id']}/cancel", {"reason": "x"}, format="json")
        assert response.json()["code"] == "sale_session_closed"


class TestReturning:
    def test_a_line_returned_in_parts_adds_up(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product, store: Location
    ) -> None:
        client = api_as(user=cashier)
        # 3 × 79.90 = 239.70, minus 10.00: the line was paid 229.70, and 90.00 of cost left inventory.
        sale = sold(client, (sku(shirt), 3), total="229.70", discount="10.00")
        item = sale["items"][0]["id"]
        refunds = [give_back(client, store, sale, [{"sale_item": item, "quantity": 1}]).json() for _ in range(3)]
        # 229.70 / 3 = 76.5666…: 76.57, 76.57, and the last takes what is left, 76.56.
        assert [r["total"] for r in refunds] == ["76.57", "76.57", "76.56"]
        assert stock_of(shirt, store) == 10
        assert SkuCost.objects.get(variant=sku(shirt)).value == D("300.0000")
        assert sum(StoreCredit.objects.values_list("balance", flat=True), D(0)) == D("229.70")
        over = give_back(client, store, sale, [{"sale_item": item, "quantity": 1}])
        assert over.json()["code"] == "return_over_sold"

    def test_at_another_store(
        self,
        api_as: Callable[..., APIClient],
        make_user: Callable[..., User],
        session: CashSession,
        cashier: User,
        shirt: Product,
        store: Location,
        other_store: Location,
    ) -> None:
        sale = sold(api_as(user=cashier), (sku(shirt), 1), total="79.90")
        elsewhere = api_as(user=make_user(Role.CASHIER, locations=[other_store]))
        response = give_back(elsewhere, other_store, sale, [{"sale_item": sale["items"][0]["id"], "quantity": 1}])
        assert response.status_code == 201, response.json()
        assert (stock_of(shirt, store), stock_of(shirt, other_store)) == (9, 1)
        assert SkuCost.objects.get(variant=sku(shirt)).value == D("300.0000")

    def test_without_the_receipt_a_manager_approves(
        self,
        api_as: Callable[..., APIClient],
        make_user: Callable[..., User],
        cashier: User,
        session: CashSession,
        shirt: Product,
        store: Location,
    ) -> None:
        client = api_as(user=cashier)
        lines = [{"variant": sku(shirt).pk, "quantity": 1}]
        assert give_back(client, store, None, lines).json()["code"] == "return_needs_approval"
        approval = Approval.objects.create(
            action=Approval.Action.RETURN_WITHOUT_RECEIPT,
            approver=make_user(Role.MANAGER),
            requested_by=cashier,
            location=store,
            reason="Presente, sem nota",
            expires_at=timezone.now() + timedelta(minutes=5),
        )
        response = give_back(client, store, None, lines, approval=approval.pk)
        assert response.json()["total"] == "79.90"  # the current price
        assert stock_of(shirt, store) == 11
        assert SkuCost.objects.get(variant=sku(shirt)).value == D("330.0000")  # back at the average, 30.00

    def test_a_cash_refund_comes_out_of_the_drawer(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product, store: Location
    ) -> None:
        client = api_as(user=cashier)
        sale = sold(client, (sku(shirt), 2), total="159.80")  # paid by pix: the drawer still holds just the float
        line = [{"sale_item": sale["items"][0]["id"], "quantity": 2}]
        refused = give_back(client, store, sale, line, refund_method="cash")
        assert refused.json()["code"] == "refund_exceeds_drawer"
        client.post(
            f"/api/pos/sessions/{session.pk}/movements",
            {"kind": "supply", "amount": "100.00", "reason": "x"},
            format="json",
        )
        assert give_back(client, store, sale, line, refund_method="cash").status_code == 201
        assert client.get(f"/api/pos/sessions/{session.pk}/summary").json()["expected_cash"] == "40.20"


class TestExchanging:
    def test_the_credit_pays_first(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product, store: Location
    ) -> None:
        client = api_as(user=cashier)
        sale = sold(client, (sku(shirt, "M"), 1), total="79.90")
        payload = {
            "client_request_id": str(uuid.uuid4()),
            "sale": sale["id"],
            "returned": [{"sale_item": sale["items"][0]["id"], "quantity": 1}],
            "reason": "Trocou por G e GG",
            "items": [{"variant": sku(shirt, "G").pk, "quantity": 1}, {"variant": sku(shirt, "GG").pk, "quantity": 1}],
            "payments": [{"method": "pix", "amount": "79.90"}],
        }
        body = client.post("/api/pos/exchanges", payload, format="json").json()
        assert [(p["method"], p["amount"]) for p in body["sale"]["payments"]] == [
            ("store_credit", "79.90"),
            ("pix", "79.90"),
        ]
        assert body["store_credit"]["balance"] == "0.00"
        assert (stock_of(shirt, store, "M"), stock_of(shirt, store, "G"), stock_of(shirt, store, "GG")) == (10, 9, 9)

    def test_a_cheaper_choice_leaves_credit_for_later(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product
    ) -> None:
        client = api_as(user=cashier)
        sale = sold(client, (sku(shirt, "M"), 2), total="159.80")
        payload = {
            "client_request_id": str(uuid.uuid4()),
            "sale": sale["id"],
            "returned": [{"sale_item": sale["items"][0]["id"], "quantity": 2}],
            "reason": "Levou só uma",
            "items": [{"variant": sku(shirt, "G").pk, "quantity": 1}],
        }
        body = client.post("/api/pos/exchanges", payload, format="json").json()
        assert body["store_credit"]["balance"] == "79.90"


@pytest.mark.django_db(transaction=True)
def test_two_counters_returning_the_last_piece(
    make_user: Callable[..., User], shirt: Product, store: Location, register: CashRegister
) -> None:
    seller = make_user(Role.CASHIER)
    services.open_session(user=seller, register=register, opening_float=D("0"))
    sale, _ = services.create_sale(
        user=seller,
        client_request_id=uuid.uuid4(),
        items=[services.ItemInput(sku(shirt), 1)],
        payments=[services.PaymentInput(Payment.Method.PIX, D("79.90"))],
    )
    item = sale.items.get()
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def take_back(user: User) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            barrier.wait()
            services.return_items(
                user=user,
                location=store,
                lines=[services.ReturnInput(quantity=1, sale_item_id=item.pk)],
                refund_method=SaleReturn.Refund.STORE_CREDIT,
                reason="Não serviu",
                original_sale=sale,
            )
            outcomes.append("returned")
        except ConflictError as error:
            outcomes.append(error.code)
        finally:
            connection.close()

    threads = [threading.Thread(target=take_back, args=(make_user(Role.CASHIER),)) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["return_over_sold", "returned"]
    assert StockLevel.objects.get(variant=sku(shirt), location=store).quantity == 10
