from decimal import Decimal
from typing import Any, ClassVar

from django.db import transaction
from rest_framework import serializers

from .models import Barcode, Brand, Category, Collection, Color, Price, Product, ProductVariant, Size, SizeGrid
from .services import current_product_price, with_current_price


class CategorySerializer(serializers.ModelSerializer[Category]):
    class Meta:
        model = Category
        fields = ("id", "name", "is_active")


class BrandSerializer(serializers.ModelSerializer[Brand]):
    class Meta:
        model = Brand
        fields = ("id", "name", "is_active")


class CollectionSerializer(serializers.ModelSerializer[Collection]):
    class Meta:
        model = Collection
        fields = ("id", "name", "starts_on", "ends_on", "is_active")


class ColorSerializer(serializers.ModelSerializer[Color]):
    class Meta:
        model = Color
        fields = ("id", "name", "code", "hex")

    def validate_code(self, value: str) -> str:
        return value.strip().upper()


class SizeSerializer(serializers.ModelSerializer[Size]):
    class Meta:
        model = Size
        fields = ("id", "label", "position")
        read_only_fields = ("position",)


class SizeGridSerializer(serializers.ModelSerializer[SizeGrid]):
    sizes = SizeSerializer(many=True, read_only=True)
    labels = serializers.ListField(
        child=serializers.CharField(max_length=8), write_only=True, min_length=1, help_text="Na ordem da grade."
    )

    class Meta:
        model = SizeGrid
        fields = ("id", "name", "sizes", "labels")

    def validate_labels(self, labels: list[str]) -> list[str]:
        cleaned = [label.strip().upper() for label in labels]
        if len(set(cleaned)) != len(cleaned):
            raise serializers.ValidationError("Tamanho repetido na grade.")
        return cleaned

    @transaction.atomic
    def create(self, validated: dict[str, Any]) -> SizeGrid:
        labels = validated.pop("labels")
        grid = SizeGrid.objects.create(**validated)
        Size.objects.bulk_create(Size(grid=grid, label=label, position=i) for i, label in enumerate(labels, 1))
        return grid


class BarcodeSerializer(serializers.ModelSerializer[Barcode]):
    class Meta:
        model = Barcode
        fields = ("code", "kind")


class VariantSerializer(serializers.ModelSerializer[ProductVariant]):
    size = serializers.CharField(source="size.label", read_only=True)
    size_position = serializers.IntegerField(source="size.position", read_only=True)
    color = ColorSerializer(read_only=True)
    barcodes = BarcodeSerializer(many=True, read_only=True)
    current_price = serializers.DecimalField(max_digits=10, decimal_places=2, read_only=True, allow_null=True)

    class Meta:
        model = ProductVariant
        fields = ("id", "sku", "size", "size_position", "color", "is_active", "barcodes", "current_price")
        read_only_fields = ("sku",)


class ProductListSerializer(serializers.ModelSerializer[Product]):
    category = serializers.CharField(source="category.name")
    brand = serializers.CharField(source="brand.name", allow_null=True)
    collection = serializers.CharField(source="collection.name", allow_null=True)
    current_price = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)
    variant_count = serializers.IntegerField()

    class Meta:
        model = Product
        fields = (
            "id",
            "reference",
            "name",
            "category",
            "brand",
            "collection",
            "is_active",
            "current_price",
            "variant_count",
        )


class ProductDetailSerializer(serializers.ModelSerializer[Product]):
    size_grid = SizeGridSerializer(read_only=True)
    variants = serializers.SerializerMethodField()
    current_price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = (
            "id",
            "reference",
            "name",
            "description",
            "category",
            "brand",
            "collection",
            "size_grid",
            "ncm",
            "cest",
            "origin",
            "is_active",
            "current_price",
            "variants",
        )
        read_only_fields = ("reference",)

    def get_variants(self, product: Product) -> list[dict[str, Any]]:
        variants = with_current_price(product.variants.select_related("size", "color").prefetch_related("barcodes"))
        return VariantSerializer(variants, many=True).data  # type: ignore[return-value]

    def get_current_price(self, product: Product) -> str | None:
        price = current_product_price(product)
        return str(price) if price is not None else None


class ProductCreateSerializer(serializers.ModelSerializer[Product]):
    colors = serializers.PrimaryKeyRelatedField(queryset=Color.objects.all(), many=True)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal("0.01"))

    class Meta:
        model = Product
        fields = (
            "reference",
            "name",
            "description",
            "category",
            "brand",
            "collection",
            "size_grid",
            "ncm",
            "cest",
            "origin",
            "colors",
            "price",
        )

    def validate_reference(self, value: str) -> str:
        reference = value.strip().upper()
        if Product.objects.filter(reference__iexact=reference).exists():
            raise serializers.ValidationError("Já existe um produto com esta referência.")
        return reference


class ProductUpdateSerializer(serializers.ModelSerializer[Product]):
    """The grid is fixed once SKUs exist: changing it would orphan their sizes."""

    class Meta:
        model = Product
        fields = ("name", "description", "category", "brand", "collection", "ncm", "cest", "origin", "is_active")


class AddColorsSerializer(serializers.Serializer[None]):
    colors = serializers.PrimaryKeyRelatedField(queryset=Color.objects.all(), many=True, allow_empty=False)


class PriceSerializer(serializers.ModelSerializer[Price]):
    sku = serializers.CharField(source="variant.sku", read_only=True, allow_null=True)
    created_by = serializers.CharField(source="created_by.name", read_only=True)

    class Meta:
        model = Price
        fields = ("id", "variant", "sku", "amount", "valid_from", "created_by", "created_at")
        read_only_fields = ("created_at",)
        extra_kwargs: ClassVar[dict[str, dict[str, bool]]] = {
            "valid_from": {"required": False},
            "variant": {"required": False},
        }


class SupplierBarcodeSerializer(serializers.Serializer[None]):
    code = serializers.CharField(max_length=20)


class LookupSerializer(serializers.ModelSerializer[ProductVariant]):
    """What the till needs after a scan."""

    product = serializers.SerializerMethodField()
    size = serializers.CharField(source="size.label")
    color = serializers.CharField(source="color.name")
    current_price = serializers.DecimalField(max_digits=10, decimal_places=2, allow_null=True)

    class Meta:
        model = ProductVariant
        fields = ("id", "sku", "product", "size", "color", "is_active", "current_price")

    def get_product(self, variant: ProductVariant) -> dict[str, Any]:
        return {"id": variant.product_id, "reference": variant.product.reference, "name": variant.product.name}
