import itertools
from collections.abc import Callable, Iterator
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import Role, User
from locations.models import Location

PASSWORD = "correct-horse-battery"
_sequence = itertools.count(1)


def make_location(code: str | None = None, name: str | None = None, kind: str = Location.Kind.STORE) -> Location:
    n = next(_sequence)
    return Location.objects.create(code=code or f"L{n:03d}", name=name or f"Loja {n}", kind=kind)


def create_user(role: Role = Role.CASHIER, locations: list[Location] | None = None, **fields: Any) -> User:
    n = next(_sequence)
    fields.setdefault("email", f"pessoa{n}@arara.test")
    fields.setdefault("name", f"Pessoa {n}")
    user = User.objects.create_user(password=PASSWORD, role=role, **fields)
    user.locations.set(locations or [])
    return user


@pytest.fixture(autouse=True)
def _fast_password_hashing(settings: Any) -> None:
    # Production keeps Django's PBKDF2; tests don't need to spend a second per password.
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.MD5PasswordHasher"]


@pytest.fixture(autouse=True)
def _clear_cache() -> Iterator[None]:
    # Throttling counts live in the cache: every test starts from zero.
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def store() -> Location:
    return make_location("CENTRO", "Loja Centro")


@pytest.fixture
def other_store() -> Location:
    return make_location("SHOP", "Loja Shopping")


@pytest.fixture
def make_user(store: Location) -> Callable[..., User]:
    def make(role: Role = Role.CASHIER, locations: list[Location] | None = None, **fields: Any) -> User:
        return create_user(role, [store] if locations is None else locations, **fields)

    return make


@pytest.fixture
def api_as(make_user: Callable[..., User]) -> Callable[..., APIClient]:
    """An API client signed in as a new user of the given role (CSRF not enforced: see the auth tests)."""

    def signed_in(role: Role = Role.CASHIER, user: User | None = None, **fields: Any) -> APIClient:
        client = APIClient()
        client.force_login(user or make_user(role, **fields))
        return client

    return signed_in
