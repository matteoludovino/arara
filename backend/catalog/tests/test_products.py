from collections.abc import Callable

import pytest
from rest_framework.test import APIClient

from accounts.models import Role
from audit.models import AuditEvent
from catalog.gtin import is_internal, is_valid_gtin
from catalog.models import Barcode, Category, Color, Product, ProductVariant, SizeGrid

pytestmark = pytest.mark.django_db


def create(client: APIClient, letters: SizeGrid, tops: Category, colors: list[Color], **extra: object):  # type: ignore[no-untyped-def]
    payload = {
        "reference": "cam-001",
        "name": "Camiseta básica",
        "category": tops.pk,
        "size_grid": letters.pk,
        "colors": [c.pk for c in colors],
        "price": "79.90",
        **extra,
    }
    return client.post("/api/catalog/products", payload, format="json")


def test_a_product_becomes_its_grid_of_skus(
    api_as: Callable[..., APIClient], letters: SizeGrid, tops: Category, colors: dict[str, Color]
) -> None:
    response = create(api_as(Role.MANAGER), letters, tops, [colors["preto"], colors["branco"]])
    assert response.status_code == 201, response.json()
    body = response.json()
    assert body["reference"] == "CAM-001"
    assert body["current_price"] == "79.90"
    skus = [v["sku"] for v in body["variants"]]
    assert len(skus) == 10
    assert {"CAM-001-PRE-PP", "CAM-001-BRA-GG"} <= set(skus)
    codes = [v["barcodes"][0]["code"] for v in body["variants"]]
    assert len(set(codes)) == 10
    assert all(is_valid_gtin(code) and is_internal(code) for code in codes)
    assert all(v["current_price"] == "79.90" for v in body["variants"])


def test_variants_follow_the_grid_order(make_product: Callable[..., Product]) -> None:
    product = make_product()
    assert [v.size.label for v in product.variants.order_by("size__position")] == ["PP", "P", "M", "G", "GG"]


def test_reference_is_unique_regardless_of_case(
    api_as: Callable[..., APIClient],
    letters: SizeGrid,
    tops: Category,
    colors: dict[str, Color],
    make_product: Callable[..., Product],
) -> None:
    make_product(reference="CAM-001")
    response = create(api_as(Role.MANAGER), letters, tops, [colors["preto"]], reference="Cam-001")
    assert response.status_code == 400
    assert "reference" in response.json()


def test_a_product_needs_a_color(api_as: Callable[..., APIClient], letters: SizeGrid, tops: Category) -> None:
    assert create(api_as(Role.MANAGER), letters, tops, []).status_code == 422


def test_adding_colors_fills_only_the_gaps(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product], colors: dict[str, Color]
) -> None:
    product = make_product(color_names=("preto",))
    response = api_as(Role.MANAGER).post(
        f"/api/catalog/products/{product.pk}/colors", {"colors": [colors["preto"].pk, colors["azul"].pk]}, format="json"
    )
    assert response.status_code == 201
    assert product.variants.count() == 10
    assert Barcode.objects.filter(variant__product=product).count() == 10


def test_a_size_appended_to_the_grid_is_filled_on_request(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product], letters: SizeGrid, colors: dict[str, Color]
) -> None:
    product = make_product(color_names=("preto", "branco"))
    client = api_as(Role.MANAGER)
    assert client.post(f"/api/catalog/size-grids/{letters.pk}/sizes", {"label": "xg"}, format="json").status_code == 201
    client.post(
        f"/api/catalog/products/{product.pk}/colors",
        {"colors": [colors["preto"].pk, colors["branco"].pk]},
        format="json",
    )
    assert sorted(product.variants.filter(size__label="XG").values_list("sku", flat=True)) == [
        "CAM-001-BRA-XG",
        "CAM-001-PRE-XG",
    ]


@pytest.mark.parametrize("role", [Role.CASHIER, Role.STOCKIST])
def test_the_floor_team_reads_but_does_not_edit_the_catalog(
    api_as: Callable[..., APIClient],
    make_product: Callable[..., Product],
    letters: SizeGrid,
    tops: Category,
    colors: dict[str, Color],
    role: Role,
) -> None:
    product = make_product()
    client = api_as(role)
    assert client.get("/api/catalog/products").status_code == 200
    assert client.get(f"/api/catalog/products/{product.pk}").status_code == 200
    assert create(client, letters, tops, [colors["preto"]], reference="X-1").status_code == 403
    assert client.patch(f"/api/catalog/products/{product.pk}", {"name": "Outro"}, format="json").status_code == 403


def test_the_grid_of_a_product_cannot_change(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product]
) -> None:
    product = make_product()
    other = SizeGrid.objects.create(name="Numeração")
    client = api_as(Role.MANAGER)
    client.patch(
        f"/api/catalog/products/{product.pk}", {"size_grid": other.pk, "name": "Camiseta gola V"}, format="json"
    )
    product.refresh_from_db()
    assert (product.size_grid.name, product.name) == ("Letras PP–GG", "Camiseta gola V")


def test_a_variant_can_be_retired(api_as: Callable[..., APIClient], make_product: Callable[..., Product]) -> None:
    variant = make_product().variants.first()
    assert variant is not None
    response = api_as(Role.MANAGER).patch(f"/api/catalog/variants/{variant.pk}", {"is_active": False}, format="json")
    assert response.status_code == 200
    assert ProductVariant.objects.get(pk=variant.pk).is_active is False


def test_search_by_name_reference_or_sku(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product]
) -> None:
    make_product(reference="CAM-001", name="Camiseta básica")
    make_product(reference="CAL-020", name="Calça jeans reta")
    client = api_as(Role.CASHIER)

    def found(q: str) -> list[str]:
        return [p["reference"] for p in client.get("/api/catalog/products", {"q": q}).json()["results"]]

    assert found("jeans") == ["CAL-020"]
    assert found("cam-001") == ["CAM-001"]
    assert found("CAL-020-PRE-M") == ["CAL-020"]


def test_creation_records_the_initial_price(make_product: Callable[..., Product]) -> None:
    make_product()
    event = AuditEvent.objects.get(action="price.changed")
    assert event.data["to"] == "79.90"
    assert event.data["from"] is None


def test_search_does_not_inflate_the_sku_count(
    api_as: Callable[..., APIClient], make_product: Callable[..., Product]
) -> None:
    make_product(reference="CAM-001", color_names=("preto", "branco"))
    client = api_as(Role.CASHIER)
    for q in ("", "camiseta", "CAM-001-PRE"):
        rows = client.get("/api/catalog/products", {"q": q}).json()["results"]
        assert [(r["reference"], r["variant_count"]) for r in rows] == [("CAM-001", 10)], q


def test_the_list_is_in_name_order(api_as: Callable[..., APIClient], make_product: Callable[..., Product]) -> None:
    # Created out of order, and with ids that would sort them differently.
    for reference, name in (
        ("VES-001", "Vestido"),
        ("BER-001", "Bermuda"),
        ("CAM-001", "Camiseta"),
        ("ALF-001", "Zíper"),
    ):
        make_product(reference=reference, name=name)
    rows = api_as(Role.CASHIER).get("/api/catalog/products").json()["results"]
    assert [r["name"] for r in rows] == ["Bermuda", "Camiseta", "Vestido", "Zíper"]
