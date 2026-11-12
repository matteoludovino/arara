from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from accounts.models import Role
from catalog.models import Barcode, Product

pytestmark = pytest.mark.django_db


def add(client: APIClient, variant_id: int, code: str):  # type: ignore[no-untyped-def]
    return client.post(f"/api/catalog/variants/{variant_id}/barcodes", {"code": code}, format="json")


def test_a_supplier_code_is_added_to_a_sku(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product]
) -> None:
    variant = make_product().variants.first()
    assert variant is not None
    response = add(api_as(Role.MANAGER), variant.pk, "7891000315507")
    assert response.status_code == 201
    assert {b["kind"] for b in response.json()["barcodes"]} == {"internal", "supplier"}


@pytest.mark.parametrize(
    ("code", "error"),
    [
        ("7891000315508", "barcode_invalid"),  # wrong check digit
        ("12345", "barcode_invalid"),
        ("2000000000428", "barcode_reserved"),  # the store's own range
    ],
)
def test_bad_supplier_codes(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product], code: str, error: str
) -> None:
    variant = make_product().variants.first()
    assert variant is not None
    response = add(api_as(Role.MANAGER), variant.pk, code)
    assert response.status_code == 422
    assert response.json()["code"] == error


def test_one_code_one_sku(api_as: Callable[..., APIClient], make_product: Callable[..., Product]) -> None:
    first, second = make_product().variants.all()[:2]
    client = api_as(Role.MANAGER)
    assert add(client, first.pk, "7891000315507").status_code == 201
    response = add(client, second.pk, "7891000315507")
    assert response.status_code == 422
    assert first.sku in response.json()["detail"]


def test_the_till_resolves_any_code_to_a_sku(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product]
) -> None:
    variant = make_product(price="79.90").variants.get(size__label="M")
    internal = Barcode.objects.get(variant=variant, kind=Barcode.Kind.INTERNAL).code
    client = api_as(Role.CASHIER)
    add(api_as(Role.MANAGER), variant.pk, "7891000315507")
    for code in (internal, "7891000315507", variant.sku.lower()):
        response = client.get("/api/catalog/lookup", {"code": code})
        assert response.status_code == 200, code
        assert response.json()["sku"] == "CAM-001-PRE-M"
        assert response.json()["current_price"] == "79.90"
    assert client.get("/api/catalog/lookup", {"code": "7890000000000"}).status_code == 404
