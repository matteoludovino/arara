import threading
import uuid
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Approval, Role, User
from audit.models import AuditEvent
from catalog.models import Product
from common.errors import ConflictError
from locations.models import Location
from pos import services
from pos.models import CashMovement, CashRegister, CashSession, Sale, SaleItem
from pos.tests.conftest import pay_cash, post_sale, sale_payload, sku
from stock.models import StockLevel

pytestmark = pytest.mark.django_db
D = Decimal


def stock_of(product: Product, store: Location, size: str = "M") -> int:
    return StockLevel.objects.get(variant=sku(product, size), location=store).quantity


class TestSelling:
    def test_a_sale(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product, store: Location
    ) -> None:
        client = api_as(user=cashier)
        response = post_sale(
            client,
            sale_payload((sku(shirt, "M"), 1), (sku(shirt, "G"), 1), payments=[pay_cash("159.80", "200.00")]),
        )
        assert response.status_code == 201, response.json()
        body = response.json()
        assert (body["number"], body["subtotal"], body["total"]) == (1, "159.80", "159.80")
        assert body["payments"][0]["change"] == "40.20"
        assert (stock_of(shirt, store, "M"), stock_of(shirt, store, "G")) == (9, 9)
        assert post_sale(client, sale_payload((sku(shirt), 1), payments=[pay_cash("79.90")])).json()["number"] == 2

    def test_the_cost_is_frozen_and_hidden_from_the_cashier(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product
    ) -> None:
        sale = post_sale(api_as(user=cashier), sale_payload((sku(shirt), 2), payments=[pay_cash("159.80")])).json()
        assert "cost_value" not in sale["items"][0]
        assert "margin" not in sale["items"][0]
        manager_view = api_as(Role.MANAGER).get(f"/api/pos/sales/{sale['id']}").json()
        assert (manager_view["items"][0]["cost_value"], manager_view["items"][0]["margin"]) == ("60.0000", "99.80")

    def test_a_retried_request_returns_the_same_sale(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product, store: Location
    ) -> None:
        client = api_as(user=cashier)
        payload = sale_payload((sku(shirt), 1), payments=[pay_cash("79.90")])
        first, again = post_sale(client, payload), post_sale(client, payload)
        assert (first.status_code, again.status_code) == (201, 200)
        assert first.json()["id"] == again.json()["id"]
        assert Sale.objects.count() == 1
        assert stock_of(shirt, store) == 9

    def test_a_failed_sale_does_not_burn_a_number(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product
    ) -> None:
        client = api_as(user=cashier)
        refused = post_sale(client, sale_payload((sku(shirt), 11), payments=[pay_cash("878.90")]))
        assert refused.json()["code"] == "insufficient_stock"
        assert post_sale(client, sale_payload((sku(shirt), 1), payments=[pay_cash("79.90")])).json()["number"] == 1

    def test_no_open_till_no_sale(self, api_as: Callable[..., APIClient], shirt: Product) -> None:
        response = post_sale(api_as(Role.CASHIER), sale_payload((sku(shirt), 1), payments=[pay_cash("79.90")]))
        assert (response.status_code, response.json()["code"]) == (409, "session_not_open")

    @pytest.mark.parametrize(
        ("payments", "code"),
        [
            ([pay_cash("50.00")], "payments_do_not_match"),
            ([{"method": "cash", "amount": "79.90"}], "cash_tendered_missing"),
            ([{"method": "credit", "amount": "79.90", "installments": 13}], "installments_invalid"),
        ],
    )
    def test_payments_must_cover_the_sale(
        self,
        api_as: Callable[..., APIClient],
        cashier: User,
        session: CashSession,
        shirt: Product,
        payments: list[dict[str, object]],
        code: str,
    ) -> None:
        response = post_sale(api_as(user=cashier), sale_payload((sku(shirt), 1), payments=payments))
        assert response.json()["code"] == code


class TestDiscounts:
    def test_a_sale_discount_is_spread_over_the_lines(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product
    ) -> None:
        # Three lines of 79.90; 0.10 off the sale: 0.0333 each rounds to 0.03, the lost cent goes to one line.
        payload = sale_payload(
            (sku(shirt, "P"), 1),
            (sku(shirt, "M"), 1),
            (sku(shirt, "G"), 1),
            discount="0.10",
            payments=[pay_cash("239.60")],
        )
        sale = post_sale(api_as(user=cashier), payload).json()
        assert sale["discount_total"] == "0.10"
        assert sorted(item["discount"] for item in sale["items"]) == ["0.03", "0.03", "0.04"]
        assert sum(D(item["net_amount"]) for item in sale["items"]) == D("239.60")

    def test_above_the_limit_a_manager_approves(
        self,
        api_as: Callable[..., APIClient],
        cashier: User,
        make_user: Callable[..., User],
        session: CashSession,
        shirt: Product,
        store: Location,
    ) -> None:
        client = api_as(user=cashier)
        payload = sale_payload((sku(shirt), 1), discount="15.98", payments=[pay_cash("63.92")])  # 20%
        refused = post_sale(client, payload)
        assert (refused.json()["code"], refused.json()["percent"]) == ("discount_needs_approval", "20.00")

        def approval(limit: str) -> Approval:
            return Approval.objects.create(
                action=Approval.Action.DISCOUNT,
                approver=make_user(Role.MANAGER),
                requested_by=cashier,
                location=store,
                reason="Peça de vitrine",
                limit=D(limit),
                expires_at=timezone.now() + timedelta(minutes=5),
            )

        assert (
            post_sale(client, {**payload, "approval": approval("15.00").pk}).json()["code"] == "discount_above_approval"
        )
        granted = approval("20.00")
        sale = post_sale(client, {**payload, "client_request_id": str(uuid.uuid4()), "approval": granted.pk})
        assert sale.status_code == 201
        assert Sale.objects.get(pk=sale.json()["id"]).approval == granted
        assert AuditEvent.objects.filter(action="sale.discount_approved").count() == 1

    def test_a_manager_needs_no_approval(
        self, api_as: Callable[..., APIClient], make_user: Callable[..., User], register: CashRegister, shirt: Product
    ) -> None:
        manager = make_user(Role.MANAGER)
        services.open_session(user=manager, register=register, opening_float=D("0"))
        payload = sale_payload((sku(shirt), 1), discount="15.98", payments=[pay_cash("63.92")])
        assert post_sale(api_as(user=manager), payload).status_code == 201


class TestStoreCredit:
    def test_paying_with_a_credit(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product, store: Location
    ) -> None:
        credit = services.issue_credit(
            user=cashier, location=store, amount=D("50.00"), source_ref="test", customer=None
        )
        client = api_as(user=cashier)
        payments = [
            {"method": "store_credit", "amount": "50.00", "store_credit_code": credit.code.lower()},
            pay_cash("29.90"),
        ]
        assert post_sale(client, sale_payload((sku(shirt), 1), payments=payments)).status_code == 201
        credit.refresh_from_db()
        assert credit.balance == D("0.00")
        again = post_sale(client, sale_payload((sku(shirt), 1), payments=payments))
        assert again.json()["code"] == "store_credit_insufficient"


class TestTheDrawer:
    def test_expected_cash(
        self, api_as: Callable[..., APIClient], cashier: User, session: CashSession, shirt: Product
    ) -> None:
        client = api_as(user=cashier)
        post_sale(client, sale_payload((sku(shirt), 1), payments=[pay_cash("79.90", "100.00")]))
        post_sale(client, sale_payload((sku(shirt, "G"), 1), payments=[{"method": "pix", "amount": "79.90"}]))
        url = f"/api/pos/sessions/{session.pk}"
        client.post(f"{url}/movements", {"kind": "supply", "amount": "50.00", "reason": "Troco"}, format="json")
        client.post(f"{url}/movements", {"kind": "withdrawal", "amount": "30.00", "reason": "Cofre"}, format="json")
        summary = client.get(f"{url}/summary").json()
        # 100.00 float + 79.90 cash sale + 50.00 top-up - 30.00 withdrawal (the pix sale isn't in the drawer)
        assert summary["expected_cash"] == "199.90"
        assert summary["by_method"] == {"cash": "79.90", "pix": "79.90"}
        too_much = client.post(
            f"{url}/movements", {"kind": "withdrawal", "amount": "500.00", "reason": "x"}, format="json"
        )
        assert too_much.json()["code"] == "withdrawal_exceeds_drawer"
        closed = client.post(f"{url}/close", {"counted_cash": "195.00", "note": "Faltou troco"}, format="json").json()
        assert (closed["summary"]["expected_cash"], closed["summary"]["difference"]) == ("199.90", "-4.90")
        assert AuditEvent.objects.get(action="cash.difference").data["difference"] == "-4.90"
        refused = post_sale(client, sale_payload((sku(shirt), 1), payments=[pay_cash("79.90")]))
        assert refused.json()["code"] == "session_not_open"

    def test_one_open_till_per_register_and_per_cashier(
        self,
        cashier: User,
        session: CashSession,
        register: CashRegister,
        make_user: Callable[..., User],
        store: Location,
    ) -> None:
        with pytest.raises(ConflictError, match="outra pessoa"):
            services.open_session(user=make_user(Role.CASHIER), register=register, opening_float=D("0"))
        second = CashRegister.objects.create(location=store, name="Caixa 2")
        with pytest.raises(ConflictError, match="Você já tem"):
            services.open_session(user=cashier, register=second, opening_float=D("0"))
        assert CashMovement.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_concurrent_tills_number_without_gaps(make_user: Callable[..., User], shirt: Product, store: Location) -> None:
    tills = []
    for n in range(2):
        cashier = make_user(Role.CASHIER)
        services.open_session(
            user=cashier, register=CashRegister.objects.create(location=store, name=f"Caixa {n}"), opening_float=D("0")
        )
        tills.append(cashier)
    barrier = threading.Barrier(2)
    errors: list[str] = []

    def sell(cashier: User) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
            barrier.wait()
            for _ in range(5):
                services.create_sale(
                    user=cashier,
                    client_request_id=uuid.uuid4(),
                    items=[services.ItemInput(sku(shirt), 1)],
                    payments=[services.PaymentInput("pix", D("79.90"))],  # type: ignore[arg-type]
                )
        except Exception as error:
            errors.append(repr(error))
        finally:
            connection.close()

    threads = [threading.Thread(target=sell, args=(c,)) for c in tills]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert errors == []
    assert sorted(Sale.objects.values_list("number", flat=True)) == list(range(1, 11))
    assert SaleItem.objects.count() == 10
