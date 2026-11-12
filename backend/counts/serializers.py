from rest_framework import serializers

from catalog.models import Category, Product
from locations.models import Location

from .models import CountEntry, InventoryCount


class CountSerializer(serializers.ModelSerializer[InventoryCount]):
    location_code = serializers.CharField(source="location.code")
    status_label = serializers.CharField(source="get_status_display")
    opened_by = serializers.CharField(source="opened_by.name")
    scope_size = serializers.SerializerMethodField()
    counted_skus = serializers.SerializerMethodField()

    class Meta:
        model = InventoryCount
        fields = (
            "id",
            "location",
            "location_code",
            "status",
            "status_label",
            "scope_label",
            "tolerance",
            "note",
            "opened_by",
            "opened_at",
            "finished_at",
            "applied_at",
            "scope_size",
            "counted_skus",
        )

    def get_scope_size(self, count: InventoryCount) -> int:
        return count.scope.count()

    def get_counted_skus(self, count: InventoryCount) -> int:
        return count.entries.values("variant").distinct().count()


class OpenCountSerializer(serializers.Serializer[None]):
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.filter(kind__in=Location.PHYSICAL_KINDS))
    categories = serializers.PrimaryKeyRelatedField(queryset=Category.objects.all(), many=True, required=False)
    products = serializers.PrimaryKeyRelatedField(queryset=Product.objects.all(), many=True, required=False)
    tolerance = serializers.IntegerField(min_value=0, max_value=100, required=False, default=0)
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class EntrySerializer(serializers.ModelSerializer[CountEntry]):
    """No system quantity here: the count is blind for whoever is counting."""

    sku = serializers.CharField(source="variant.sku", read_only=True)
    counted_by = serializers.CharField(source="counted_by.name", read_only=True)

    class Meta:
        model = CountEntry
        fields = ("id", "variant", "sku", "area", "quantity", "counted_by", "created_at")
        read_only_fields = ("variant",)


class NewEntrySerializer(serializers.Serializer[None]):
    code = serializers.CharField(max_length=40, help_text="Código de barras ou SKU")
    quantity = serializers.IntegerField(min_value=0)
    area = serializers.CharField(max_length=40, required=False, allow_blank=True, default="")


class RecountSerializer(serializers.Serializer[None]):
    variants = serializers.ListField(child=serializers.IntegerField(), allow_empty=False)


class ApplySerializer(serializers.Serializer[None]):
    uncounted = serializers.ChoiceField(choices=["zero", "keep"], required=False, allow_null=True, default=None)
