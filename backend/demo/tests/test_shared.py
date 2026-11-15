from collections.abc import Callable

import pytest
from django.test import override_settings
from rest_framework.test import APIClient

from accounts.models import Role, User
from demo import shared
from demo.seed import Seed
from locations.models import Location

pytestmark = pytest.mark.django_db


def test_the_protected_lists_are_what_the_seed_creates() -> None:
    Seed(days=1).run()
    assert set(User.objects.values_list("email", flat=True)) == shared.ACCOUNTS
    assert (
        set(Location.objects.filter(kind__in=Location.PHYSICAL_KINDS).values_list("code", flat=True))
        == shared.LOCATIONS
    )


@override_settings(DEMO_MODE=True)
def test_visitors_cannot_lock_each_other_out(
    api_as: Callable[..., APIClient], make_user: Callable[..., User], store: Location
) -> None:
    owner = api_as(Role.OWNER)
    bia = make_user(Role.CASHIER, email="bia@arara.test", name="Bia")
    # The `store` fixture is CENTRO, one of the demo's shared locations.
    changes: list[dict[str, object]] = [
        {"is_active": False},
        {"role": Role.OWNER},
        {"password": "outra-senha-forte-2026"},
        {"locations": []},
    ]
    for change in changes:
        response = owner.patch(f"/api/users/{bia.pk}", change, format="json")
        assert response.status_code == 400, change
    assert owner.patch(f"/api/users/{bia.pk}", {"name": "Bia S."}, format="json").status_code == 200
    assert owner.patch(f"/api/locations/{store.pk}", {"is_active": False}, format="json").status_code == 400
    # Anyone a visitor creates is theirs to change.
    other = make_user(Role.CASHIER, email="nova@arara.test")
    assert owner.patch(f"/api/users/{other.pk}", {"is_active": False}, format="json").status_code == 200


def test_outside_the_demo_nothing_is_protected(
    api_as: Callable[..., APIClient], make_user: Callable[..., User]
) -> None:
    bia = make_user(Role.CASHIER, email="bia@arara.test")
    assert api_as(Role.OWNER).patch(f"/api/users/{bia.pk}", {"is_active": False}, format="json").status_code == 200
