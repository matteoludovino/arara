import itertools
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from accounts.models import Role, User
from catalog import services as catalog
from catalog.models import Category, Color, Product, Size, SizeGrid
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


# ─── Catalog ─────────────────────────────────────────────────────────────────


@pytest.fixture
def letters() -> SizeGrid:
    grid = SizeGrid.objects.create(name="Letras PP–GG")
    Size.objects.bulk_create(
        Size(grid=grid, label=label, position=i) for i, label in enumerate(["PP", "P", "M", "G", "GG"], 1)
    )
    return grid


@pytest.fixture
def tops() -> Category:
    return Category.objects.create(name="Camisetas")


@pytest.fixture
def colors() -> dict[str, Color]:
    return {
        "preto": Color.objects.create(name="Preto", code="PRE", hex="#000000"),
        "branco": Color.objects.create(name="Branco", code="BRA", hex="#FFFFFF"),
        "azul": Color.objects.create(name="Azul marinho", code="AZM"),
    }


@pytest.fixture
def owner(make_user: Callable[..., User]) -> User:
    return make_user(Role.OWNER)


@pytest.fixture
def make_product(owner: User, letters: SizeGrid, tops: Category, colors: dict[str, Color]) -> Callable[..., Product]:
    def make(
        reference: str = "CAM-001", color_names: tuple[str, ...] = ("preto",), price: str = "79.90", **fields: Any
    ) -> Product:
        return catalog.create_product(
            user=owner,
            colors=[colors[name] for name in color_names],
            price=Decimal(price),
            reference=reference,
            name=fields.pop("name", "Camiseta básica"),
            category=tops,
            size_grid=letters,
            **fields,
        )

    return make
