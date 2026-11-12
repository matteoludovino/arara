from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, User
from locations.models import Location

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("role", [Role.MANAGER, Role.CASHIER, Role.STOCKIST])
def test_only_the_owner_manages_the_team(api_as: Callable[..., APIClient], role: Role) -> None:
    client = api_as(role)
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/users", {}, format="json").status_code == 403


def test_owner_creates_a_person_with_locations(api_as: Callable[..., APIClient], store: Location) -> None:
    client = api_as(Role.OWNER)
    response = client.post(
        "/api/users",
        {
            "email": " Bia@Arara.test ",
            "name": "Bia Souza",
            "role": "stockist",
            "locations": [store.pk],
            "password": "estoque-forte-2026",
        },
        format="json",
    )
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["email"] == "bia@arara.test"
    assert body["locations"] == [store.pk]
    assert "password" not in body


def test_emails_are_unique_regardless_of_case(api_as: Callable[..., APIClient], make_user: Callable[..., User]) -> None:
    make_user(email="caio@arara.test")
    response = api_as(Role.OWNER).post(
        "/api/users",
        {"email": "CAIO@arara.test", "name": "Outro Caio", "role": "cashier", "password": "senha-boa-2026"},
        format="json",
    )
    assert response.status_code == 400
    assert "email" in response.json()


def test_weak_passwords_are_refused(api_as: Callable[..., APIClient]) -> None:
    response = api_as(Role.OWNER).post(
        "/api/users",
        {"email": "d@arara.test", "name": "Davi", "role": "cashier", "password": "12345678"},
        format="json",
    )
    assert response.status_code == 400
    assert "password" in response.json()


def test_the_last_owner_cannot_be_demoted_or_deactivated(
    make_user: Callable[..., User], api_as: Callable[..., APIClient]
) -> None:
    owner = make_user(Role.OWNER)
    client = api_as(user=owner)
    assert client.patch(f"/api/users/{owner.pk}", {"role": "manager"}, format="json").status_code == 400
    assert client.patch(f"/api/users/{owner.pk}", {"is_active": False}, format="json").status_code == 400
    second = make_user(Role.OWNER)
    assert client.patch(f"/api/users/{second.pk}", {"is_active": False}, format="json").status_code == 200


def test_virtual_locations_cannot_be_assigned(api_as: Callable[..., APIClient], make_user: Callable[..., User]) -> None:
    transit = Location.objects.get(kind=Location.Kind.TRANSIT)
    person = make_user(Role.STOCKIST)
    response = api_as(Role.OWNER).patch(f"/api/users/{person.pk}", {"locations": [transit.pk]}, format="json")
    assert response.status_code == 400
