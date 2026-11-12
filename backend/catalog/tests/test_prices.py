from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any, cast

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from accounts.models import Role, User
from audit.models import AuditEvent
from catalog import services
from catalog.models import Price, Product

pytestmark = pytest.mark.django_db


def test_a_sku_price_overrides_the_product_price(owner: User, make_product: Callable[..., Product]) -> None:
    product = make_product(price="79.90")
    gg = product.variants.get(size__label="GG")
    m = product.variants.get(size__label="M")
    services.set_price(user=owner, product=product, variant=gg, amount=Decimal("89.90"))
    assert services.current_price(gg) == Decimal("89.90")
    assert services.current_price(m) == Decimal("79.90")
    annotated = {
        v.size.label: cast(Any, v).current_price  # annotated by the query
        for v in services.with_current_price(product.variants.select_related("size"))
    }
    assert annotated["GG"] == Decimal("89.90")
    assert annotated["M"] == Decimal("79.90")


def test_a_scheduled_price_applies_from_its_start(owner: User, make_product: Callable[..., Product]) -> None:
    product = make_product(price="79.90")
    variant = product.variants.first()
    assert variant is not None
    starts = timezone.now() + timedelta(days=7)
    services.set_price(user=owner, product=product, amount=Decimal("49.90"), valid_from=starts)
    assert services.current_price(variant) == Decimal("79.90")
    assert services.current_price(variant, at=starts) == Decimal("49.90")
    assert AuditEvent.objects.filter(action="price.scheduled").count() == 1


def test_history_is_kept(owner: User, make_product: Callable[..., Product]) -> None:
    product = make_product(price="79.90")
    services.set_price(user=owner, product=product, amount=Decimal("69.90"))
    assert list(product.prices.values_list("amount", flat=True)) == [Decimal("69.90"), Decimal("79.90")]
    changed = AuditEvent.objects.filter(action="price.changed").first()
    assert changed is not None
    assert (changed.data["from"], changed.data["to"]) == ("79.90", "69.90")


def test_a_price_cannot_start_in_the_past(owner: User, make_product: Callable[..., Product]) -> None:
    product = make_product()
    with pytest.raises(Exception, match="passado"):
        services.set_price(
            user=owner, product=product, amount=Decimal("10"), valid_from=timezone.now() - timedelta(hours=1)
        )


def test_a_sku_price_must_be_for_the_same_product(owner: User, make_product: Callable[..., Product]) -> None:
    shirt, pants = make_product(reference="CAM-001"), make_product(reference="CAL-001")
    with pytest.raises(Exception, match="outro produto"):
        services.set_price(user=owner, product=shirt, variant=pants.variants.first(), amount=Decimal("10"))


def test_the_database_refuses_zero_or_negative_prices(owner: User, make_product: Callable[..., Product]) -> None:
    product = make_product()
    with pytest.raises(Exception, match="price_positive"):
        Price.objects.create(
            product=product, amount=Decimal("0"), valid_from=timezone.now() + timedelta(days=1), created_by=owner
        )


@pytest.mark.parametrize("role", [Role.MANAGER, Role.CASHIER])
def test_only_the_owner_changes_prices(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product], role: Role
) -> None:
    product = make_product()
    client = api_as(role)
    assert client.get(f"/api/catalog/products/{product.pk}/prices").status_code == 200
    assert (
        client.post(f"/api/catalog/products/{product.pk}/prices", {"amount": "59.90"}, format="json").status_code == 403
    )


def test_owner_changes_and_withdraws_a_scheduled_price(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product]
) -> None:
    product = make_product(price="79.90")
    client = api_as(Role.OWNER)
    later = (timezone.now() + timedelta(days=3)).isoformat()
    scheduled = client.post(
        f"/api/catalog/products/{product.pk}/prices", {"amount": "59.90", "valid_from": later}, format="json"
    )
    assert scheduled.status_code == 201
    assert client.delete(f"/api/catalog/prices/{scheduled.json()['id']}").status_code == 204
    effective = product.prices.get(amount=Decimal("79.90"))
    response = client.delete(f"/api/catalog/prices/{effective.pk}")
    assert response.status_code == 422
    assert response.json()["code"] == "price_already_effective"
    assert AuditEvent.objects.filter(action="price.cancelled").count() == 1


def test_the_list_shows_the_current_product_price(
    api_as: Callable[..., APIClient], owner: User, make_product: Callable[..., Product]
) -> None:
    product = make_product(price="79.90")
    services.set_price(
        user=owner, product=product, amount=Decimal("59.90"), valid_from=timezone.now() + timedelta(days=2)
    )
    listed = api_as(Role.CASHIER).get("/api/catalog/products").json()["results"]
    assert listed[0]["current_price"] == "79.90"
    assert listed[0]["variant_count"] == 5
