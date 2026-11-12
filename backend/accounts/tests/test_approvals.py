import threading
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import connection
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Approval, Role, User
from accounts.services import consume_approval
from audit.models import AuditEvent
from common.errors import ConflictError, DomainError
from conftest import PASSWORD
from locations.models import Location

DISCOUNT = Approval.Action.DISCOUNT


def ask(client: APIClient, location: Location, approver: User, password: str = PASSWORD, **extra: object):  # type: ignore[no-untyped-def]
    payload = {
        "action": "discount",
        "location": location.pk,
        "approver_email": approver.email,
        "approver_password": password,
        "reason": "Cliente fiel, peça com defeito leve",
        "limit": "20.00",
        **extra,
    }
    return client.post("/api/approvals", payload, format="json")


@pytest.mark.django_db
class TestGranting:
    def test_a_manager_of_the_store_approves(
        self, api_as: Callable[..., APIClient], make_user: Callable[..., User], store: Location
    ) -> None:
        cashier = make_user(Role.CASHIER)
        manager = make_user(Role.MANAGER)
        response = ask(api_as(user=cashier), store, manager)
        assert response.status_code == 201
        approval = Approval.objects.get(pk=response.json()["id"])
        assert (approval.approver, approval.requested_by, approval.limit) == (manager, cashier, Decimal("20.00"))
        event = AuditEvent.objects.get(action="approval.granted")
        assert event.actor == manager
        assert "password" not in str(event.data)

    def test_wrong_password(
        self, api_as: Callable[..., APIClient], make_user: Callable[..., User], store: Location
    ) -> None:
        response = ask(api_as(Role.CASHIER), store, make_user(Role.MANAGER), password="wrong-one")
        assert response.status_code == 422
        assert response.json()["code"] == "approval_invalid_credentials"

    def test_nobody_approves_their_own_request(
        self, api_as: Callable[..., APIClient], make_user: Callable[..., User], store: Location
    ) -> None:
        manager = make_user(Role.MANAGER)
        assert ask(api_as(user=manager), store, manager).json()["code"] == "approval_same_person"

    def test_a_cashier_cannot_approve(
        self, api_as: Callable[..., APIClient], make_user: Callable[..., User], store: Location
    ) -> None:
        response = ask(api_as(Role.CASHIER), store, make_user(Role.CASHIER))
        assert response.json()["code"] == "approval_not_allowed"

    def test_a_manager_of_another_store_cannot_approve(
        self, api_as: Callable[..., APIClient], make_user: Callable[..., User], store: Location, other_store: Location
    ) -> None:
        response = ask(api_as(Role.CASHIER), store, make_user(Role.MANAGER, locations=[other_store]))
        assert response.json()["code"] == "approval_not_allowed"

    def test_password_checks_are_rate_limited(
        self, api_as: Callable[..., APIClient], make_user: Callable[..., User], store: Location
    ) -> None:
        client, manager = api_as(Role.CASHIER), make_user(Role.MANAGER)
        statuses = [ask(client, store, manager, password="guess").status_code for _ in range(11)]
        assert statuses[-1] == 429


def grant(requester: User, approver: User, location: Location, **fields: object) -> Approval:
    fields.setdefault("expires_at", timezone.now() + timedelta(minutes=5))
    return Approval.objects.create(
        action=DISCOUNT, requested_by=requester, approver=approver, location=location, reason="teste", **fields
    )


@pytest.mark.django_db
class TestConsuming:
    def test_used_once(self, make_user: Callable[..., User], store: Location) -> None:
        cashier, manager = make_user(Role.CASHIER), make_user(Role.MANAGER)
        approval = grant(cashier, manager, store)
        used = consume_approval(
            approval_id=approval.pk, requester=cashier, action=DISCOUNT, location=store, used_by="sale:1"
        )
        assert used.consumed_by_ref == "sale:1"
        with pytest.raises(ConflictError, match="já foi usada"):
            consume_approval(
                approval_id=approval.pk, requester=cashier, action=DISCOUNT, location=store, used_by="sale:2"
            )

    def test_bound_to_requester_action_and_location(
        self, make_user: Callable[..., User], store: Location, other_store: Location
    ) -> None:
        cashier, manager = make_user(Role.CASHIER), make_user(Role.MANAGER)
        approval = grant(cashier, manager, store)
        attempts = [
            {"requester": make_user(Role.CASHIER), "action": DISCOUNT, "location": store},
            {"requester": cashier, "action": Approval.Action.RETURN_WITHOUT_RECEIPT, "location": store},
            {"requester": cashier, "action": DISCOUNT, "location": other_store},
        ]
        for attempt in attempts:
            with pytest.raises(DomainError, match="não encontrada"):
                consume_approval(approval_id=approval.pk, used_by="sale:9", **attempt)  # type: ignore[arg-type]

    def test_expired(self, make_user: Callable[..., User], store: Location) -> None:
        cashier = make_user(Role.CASHIER)
        approval = grant(cashier, make_user(Role.MANAGER), store, expires_at=timezone.now() - timedelta(seconds=1))
        with pytest.raises(ConflictError, match="expirou"):
            consume_approval(
                approval_id=approval.pk, requester=cashier, action=DISCOUNT, location=store, used_by="sale:1"
            )

    def test_the_database_refuses_a_self_approval(self, make_user: Callable[..., User], store: Location) -> None:
        manager = make_user(Role.MANAGER)
        with pytest.raises(Exception, match="approval_needs_a_second_person"):
            grant(manager, manager, store)


@pytest.mark.django_db(transaction=True)
def test_two_tills_racing_for_one_approval(make_user: Callable[..., User], store: Location) -> None:
    cashier, manager = make_user(Role.CASHIER), make_user(Role.MANAGER)
    approval = grant(cashier, manager, store)
    barrier = threading.Barrier(2)
    outcomes: list[str] = []

    def attempt(ref: str) -> None:
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")  # a deadlock fails the test instead of hanging it
            barrier.wait()
            consume_approval(approval_id=approval.pk, requester=cashier, action=DISCOUNT, location=store, used_by=ref)
            outcomes.append("used")
        except ConflictError:
            outcomes.append("refused")
        finally:
            connection.close()

    threads = [threading.Thread(target=attempt, args=(f"sale:{n}",)) for n in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["refused", "used"]
