from typing import Any

from rest_framework import serializers

from catalog.models import ProductVariant
from locations.models import Location

from .models import Transfer, TransferLine

PHYSICAL = Location.objects.filter(kind__in=Location.PHYSICAL_KINDS)


class TransferLineSerializer(serializers.ModelSerializer[TransferLine]):
    sku = serializers.CharField(source="variant.sku")
    product = serializers.CharField(source="variant.product.name")
    size = serializers.CharField(source="variant.size.label")
    color = serializers.CharField(source="variant.color.name")

    class Meta:
        model = TransferLine
        fields = ("id", "variant", "sku", "product", "size", "color", "quantity_sent", "quantity_received")


class TransferSerializer(serializers.ModelSerializer[Transfer]):
    origin_code = serializers.CharField(source="origin.code")
    destination_code = serializers.CharField(source="destination.code")
    status_label = serializers.CharField(source="get_status_display")
    created_by = serializers.CharField(source="created_by.name")
    dispatched_by = serializers.CharField(source="dispatched_by.name", allow_null=True)
    received_by = serializers.CharField(source="received_by.name", allow_null=True)
    lines = serializers.SerializerMethodField()

    class Meta:
        model = Transfer
        fields = (
            "id",
            "number",
            "origin",
            "origin_code",
            "destination",
            "destination_code",
            "status",
            "status_label",
            "notes",
            "created_by",
            "created_at",
            "dispatched_by",
            "dispatched_at",
            "received_by",
            "received_at",
            "cancelled_at",
            "cancel_reason",
            "lines",
        )

    def get_lines(self, transfer: Transfer) -> list[dict[str, Any]]:
        # Prefetched in lists (see the view); one query for a single transfer.
        return TransferLineSerializer(transfer.lines.all(), many=True).data  # type: ignore[return-value]


class LineInputSerializer(serializers.Serializer[None]):
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.all())
    quantity = serializers.IntegerField(min_value=1)


class TransferWriteSerializer(serializers.Serializer[None]):
    origin = serializers.PrimaryKeyRelatedField(queryset=PHYSICAL)
    destination = serializers.PrimaryKeyRelatedField(queryset=PHYSICAL)
    notes = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")
    lines = LineInputSerializer(many=True, allow_empty=False)


class LinesSerializer(serializers.Serializer[None]):
    lines = LineInputSerializer(many=True, allow_empty=False)


class ReceivedLineSerializer(serializers.Serializer[None]):
    line = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=0)


class ReceiveSerializer(serializers.Serializer[None]):
    lines = ReceivedLineSerializer(many=True, allow_empty=False)
    missing_reason = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class CancelSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(max_length=200)
