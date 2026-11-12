from collections.abc import Callable
from decimal import Decimal
from typing import Any

import pytest

from accounts.models import Role, User
from catalog import services
from catalog.models import Category, Color, Product, Size, SizeGrid


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
        return services.create_product(
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
