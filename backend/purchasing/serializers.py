from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_serializer
from rest_framework import serializers

from accounts.visibility import HidesCosts
from catalog.models import ProductVariant
from common.serializers import clean_cnpj, cnpj_field
from locations.models import Location

from .models import GoodsReceipt, GoodsReceiptLine, PurchaseOrder, PurchaseOrderLine, PurchaseReturn, Supplier


class SupplierSerializer(serializers.ModelSerializer[Supplier]):
    cnpj = cnpj_field()

    class Meta:
        model = Supplier
        fields = ("id", "name", "cnpj", "contact", "email", "phone", "notes", "is_active")

    def validate_cnpj(self, value: str) -> str:
        cnpj = clean_cnpj(value)
        taken = Supplier.objects.filter(cnpj=cnpj).exclude(cnpj="")
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if cnpj and taken.exists():
            raise serializers.ValidationError("Já existe um fornecedor com este CNPJ.")
        return cnpj


class OrderLineSerializer(HidesCosts, serializers.ModelSerializer[PurchaseOrderLine]):
    sku = serializers.CharField(source="variant.sku")
    product = serializers.CharField(source="variant.product.name")
    size = serializers.CharField(source="variant.size.label")
    color = serializers.CharField(source="variant.color.name")
    pending = serializers.IntegerField()

    class Meta:
        model = PurchaseOrderLine
        fields = (
            "id",
            "variant",
            "sku",
            "product",
            "size",
            "color",
            "quantity_ordered",
            "quantity_received",
            "pending",
            "unit_cost",
        )


class OrderSerializer(HidesCosts, serializers.ModelSerializer[PurchaseOrder]):
    supplier_name = serializers.CharField(source="supplier.name")
    location_code = serializers.CharField(source="location.code")
    status_label = serializers.CharField(source="get_status_display")
    created_by = serializers.CharField(source="created_by.name")
    lines = serializers.SerializerMethodField()
    total_cost = serializers.SerializerMethodField()

    class Meta:
        model = PurchaseOrder
        fields = (
            "id",
            "number",
            "supplier",
            "supplier_name",
            "location",
            "location_code",
            "status",
            "status_label",
            "expected_on",
            "notes",
            "created_by",
            "created_at",
            "sent_at",
            "finished_at",
            "finish_reason",
            "lines",
            "total_cost",
        )

    def get_lines(self, order: PurchaseOrder) -> list[dict[str, Any]]:
        # Prefetched in lists (see the views); one query for a single order.
        return OrderLineSerializer(order.lines.all(), many=True, context=self.context).data  # type: ignore[return-value]

    def get_total_cost(self, order: PurchaseOrder) -> str:
        total = sum((line.unit_cost * line.quantity_ordered for line in order.lines.all()), Decimal(0))
        return str(total.quantize(Decimal("0.01")))


class OrderLineInputSerializer(serializers.Serializer[None]):
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.filter(is_active=True))
    quantity = serializers.IntegerField(min_value=1)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal(0))


class OrderWriteSerializer(serializers.Serializer[None]):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.filter(kind__in=Location.PHYSICAL_KINDS))
    expected_on = serializers.DateField(required=False, allow_null=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = OrderLineInputSerializer(many=True, allow_empty=False)


class OrderLinesSerializer(serializers.Serializer[None]):
    lines = OrderLineInputSerializer(many=True, allow_empty=False)


class ReasonSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(max_length=200)


class ReceiveLineSerializer(serializers.Serializer[None]):
    order_line = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1)
    unit_cost = serializers.DecimalField(max_digits=14, decimal_places=4, min_value=Decimal(0), required=False)


class ReceiveSerializer(serializers.Serializer[None]):
    invoice_number = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    lines = ReceiveLineSerializer(many=True, allow_empty=False)


class ReceiptLineSerializer(HidesCosts, serializers.ModelSerializer[GoodsReceiptLine]):
    sku = serializers.CharField(source="order_line.variant.sku")

    class Meta:
        model = GoodsReceiptLine
        fields = ("id", "order_line", "sku", "quantity", "unit_cost")


class ReceiptSerializer(serializers.ModelSerializer[GoodsReceipt]):
    order_number = serializers.CharField(source="order.number")
    received_by = serializers.CharField(source="received_by.name")
    lines = serializers.SerializerMethodField()

    class Meta:
        model = GoodsReceipt
        fields = (
            "id",
            "order",
            "order_number",
            "invoice_number",
            "received_by",
            "received_at",
            "cancelled_at",
            "lines",
        )

    def get_lines(self, receipt: GoodsReceipt) -> list[dict[str, Any]]:
        return ReceiptLineSerializer(receipt.lines.all(), many=True, context=self.context).data  # type: ignore[return-value]


class ReturnLineInputSerializer(serializers.Serializer[None]):
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.all())
    quantity = serializers.IntegerField(min_value=1)


class ReturnWriteSerializer(serializers.Serializer[None]):
    supplier = serializers.PrimaryKeyRelatedField(queryset=Supplier.objects.all())
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.filter(kind__in=Location.PHYSICAL_KINDS))
    reason = serializers.CharField(max_length=200)
    lines = ReturnLineInputSerializer(many=True, allow_empty=False)


@extend_schema_serializer(component_name="PurchaseReturn")
class ReturnSerializer(serializers.ModelSerializer[PurchaseReturn]):
    supplier_name = serializers.CharField(source="supplier.name")
    created_by = serializers.CharField(source="created_by.name")

    class Meta:
        model = PurchaseReturn
        fields = ("id", "supplier", "supplier_name", "location", "reason", "stock_entry", "created_by", "created_at")
