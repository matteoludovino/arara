import uuid
from collections.abc import Callable, Iterator
from decimal import Decimal
from typing import Any

import pytest
from rest_framework.test import APIClient

from accounts.models import Role, User
from catalog.models import Product, ProductVariant
from common.integrity import all_problems
from locations.models import Location
from pos import services
from pos.models import CashRegister, CashSession
from stock.models import StockEntry
from stock.services import Inflow, post_entry


@pytest.fixture(autouse=True)
def _everything_agrees(request: pytest.FixtureRequest) -> Iterator[None]:
    yield
    if request.node.get_closest_marker("django_db") is not None:
        assert all_problems() == []


@pytest.fixture
def register(store: Location) -> CashRegister:
    return CashRegister.objects.create(location=store, name="Caixa 1")


@pytest.fixture
def cashier(make_user: Callable[..., User]) -> User:
    return make_user(Role.CASHIER)


@pytest.fixture
def session(cashier: User, register: CashRegister) -> CashSession:
    return services.open_session(user=cashier, register=register, opening_float=Decimal("100.00"))


@pytest.fixture
def shirt(owner: User, make_product: Callable[..., Product], store: Location) -> Product:
    """CAM-001 in black, R$ 79,90, 10 pieces of each size in the store at R$ 30,00."""
    product = make_product(price="79.90")
    post_entry(
        kind=StockEntry.Kind.PURCHASE_RECEIPT,
        operations=[Inflow(v.pk, store.pk, 10, Decimal("30.00")) for v in product.variants.all()],
        user=owner,
    )
    return product


def sku(product: Product, size: str = "M") -> ProductVariant:
    return product.variants.get(size__label=size)


def sale_payload(
    *items: tuple[ProductVariant, int], payments: list[dict[str, Any]] | None = None, **extra: Any
) -> dict[str, Any]:
    return {
        "client_request_id": str(extra.pop("request_id", uuid.uuid4())),
        "items": [{"variant": v.pk, "quantity": q} for v, q in items],
        "payments": payments if payments is not None else [],
        **extra,
    }


def pay_cash(amount: str, tendered: str | None = None) -> dict[str, Any]:
    return {"method": "cash", "amount": amount, "tendered": tendered or amount}


def post_sale(client: APIClient, payload: dict[str, Any]) -> Any:
    return client.post("/api/pos/sales", payload, format="json")
