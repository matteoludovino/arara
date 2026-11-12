from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, User
from locations.models import Location

pytestmark = pytest.mark.django_db


def codes(client: APIClient) -> list[str]:
    return sorted(loc["code"] for loc in client.get("/api/locations").json()["results"])


def test_each_person_sees_their_locations(
    api_as: Callable[..., APIClient], make_user: Callable[..., User], store: Location, other_store: Location
) -> None:
    assert codes(api_as(Role.OWNER)) == ["CENTRO", "SHOP"]  # every physical location, no virtual ones
    assert codes(api_as(Role.MANAGER, locations=[other_store])) == ["SHOP"]
    assert codes(api_as(Role.CASHIER)) == ["CENTRO"]


def test_only_the_owner_creates_locations(api_as: Callable[..., APIClient]) -> None:
    payload = {"code": "dep1", "name": "Depósito", "kind": "warehouse"}
    assert api_as(Role.MANAGER).post("/api/locations", payload, format="json").status_code == 403
    response = api_as(Role.OWNER).post("/api/locations", payload, format="json")
    assert response.status_code == 201
    assert response.json()["code"] == "DEP1"


def test_codes_are_unique_regardless_of_case(api_as: Callable[..., APIClient], store: Location) -> None:
    response = api_as(Role.OWNER).post(
        "/api/locations", {"code": "centro", "name": "Outra", "kind": "store"}, format="json"
    )
    assert response.status_code == 400


def test_virtual_kinds_are_not_created_through_the_api(api_as: Callable[..., APIClient]) -> None:
    response = api_as(Role.OWNER).post(
        "/api/locations", {"code": "T2", "name": "Trânsito 2", "kind": "transit"}, format="json"
    )
    assert response.status_code == 400
    assert Location.objects.filter(kind=Location.Kind.TRANSIT).count() == 1
