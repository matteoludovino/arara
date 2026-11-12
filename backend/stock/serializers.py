from decimal import Decimal
from typing import Any

from rest_framework import serializers

from accounts.visibility import HidesCosts
from catalog.models import ProductVariant
from locations.models import Location

from .models import StockEntry, StockLevel, StockMovement


class StockLevelSerializer(HidesCosts, serializers.ModelSerializer[StockLevel]):
    sku = serializers.CharField(source="variant.sku", read_only=True)
    product = serializers.CharField(source="variant.product.name", read_only=True)
    reference = serializers.CharField(source="variant.product.reference", read_only=True)
    size = serializers.CharField(source="variant.size.label", read_only=True)
    color = serializers.CharField(source="variant.color.name", read_only=True)
    location_code = serializers.CharField(source="location.code", read_only=True)
    below_min = serializers.SerializerMethodField()
    average_cost = serializers.SerializerMethodField()
    stock_value = serializers.SerializerMethodField()

    class Meta:
        model = StockLevel
        fields = (
            "id",
            "variant",
            "sku",
            "reference",
            "product",
            "size",
            "color",
            "location",
            "location_code",
            "quantity",
            "min_quantity",
            "max_quantity",
            "below_min",
            "average_cost",
            "stock_value",
        )
        read_only_fields = ("variant", "location", "quantity")

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        level = self.instance
        low = attrs.get("min_quantity", level.min_quantity if level else 0)
        high = attrs.get("max_quantity", level.max_quantity if level else None)
        if high is not None and high < low:
            raise serializers.ValidationError("O máximo precisa ser maior ou igual ao mínimo.")
        return attrs

    def get_below_min(self, level: StockLevel) -> bool:
        return level.quantity < level.min_quantity

    def get_average_cost(self, level: StockLevel) -> str | None:
        cost = getattr(level.variant, "cost", None)
        if cost is None or cost.quantity == 0:
            return None
        return str((cost.value / cost.quantity).quantize(Decimal("0.0001")))

    def get_stock_value(self, level: StockLevel) -> str | None:
        average = self.get_average_cost(level)
        return None if average is None else str((Decimal(average) * level.quantity).quantize(Decimal("0.01")))


class MovementSerializer(HidesCosts, serializers.ModelSerializer[StockMovement]):
    kind = serializers.CharField(source="entry.kind")
    kind_label = serializers.CharField(source="entry.get_kind_display")
    reason = serializers.CharField(source="entry.reason")
    note = serializers.CharField(source="entry.note")
    source_ref = serializers.CharField(source="entry.source_ref")
    created_by = serializers.CharField(source="entry.created_by.name")
    created_at = serializers.DateTimeField(source="entry.created_at")
    sku = serializers.CharField(source="variant.sku")
    location_code = serializers.CharField(source="location.code")

    class Meta:
        model = StockMovement
        fields = (
            "id",
            "entry",
            "kind",
            "kind_label",
            "reason",
            "note",
            "source_ref",
            "created_by",
            "created_at",
            "variant",
            "sku",
            "location",
            "location_code",
            "quantity_delta",
            "balance_after",
            "value_delta",
            "unit_cost",
        )


class AdjustmentLineSerializer(serializers.Serializer[None]):
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.all())
    quantity_delta = serializers.IntegerField()


class AdjustmentSerializer(serializers.Serializer[None]):
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.filter(kind__in=Location.PHYSICAL_KINDS))
    reason = serializers.ChoiceField(choices=StockEntry.Reason.choices)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    lines = AdjustmentLineSerializer(many=True, allow_empty=False)
    approval = serializers.IntegerField(required=False)

    def validate_lines(self, lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
        variants = [line["variant"].pk for line in lines]
        if len(set(variants)) != len(variants):
            raise serializers.ValidationError("SKU repetido no ajuste.")
        return lines
