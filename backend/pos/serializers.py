from decimal import Decimal
from typing import Any

from rest_framework import serializers

from accounts.models import User
from accounts.visibility import HidesCosts
from catalog.models import ProductVariant
from common.cpf import is_valid_cpf, normalize_cpf
from locations.models import Location

from .models import (
    CashMovement,
    CashRegister,
    CashSession,
    Customer,
    Payment,
    ReturnLine,
    Sale,
    SaleItem,
    SaleReturn,
    StoreCredit,
)


class CustomerSerializer(serializers.ModelSerializer[Customer]):
    cpf = serializers.CharField(max_length=14, required=False, allow_blank=True)

    class Meta:
        model = Customer
        fields = ("id", "name", "cpf", "email", "phone")

    def validate_cpf(self, value: str) -> str:
        if not value:
            return ""
        cpf = normalize_cpf(value)
        if not is_valid_cpf(cpf):
            raise serializers.ValidationError("CPF inválido.")
        taken = Customer.objects.filter(cpf=cpf)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("Já existe um cliente com este CPF.")
        return cpf


class RegisterSerializer(serializers.ModelSerializer[CashRegister]):
    location_code = serializers.CharField(source="location.code", read_only=True)
    open_session = serializers.SerializerMethodField()

    class Meta:
        model = CashRegister
        fields = ("id", "location", "location_code", "name", "is_active", "open_session")

    def get_open_session(self, register: CashRegister) -> dict[str, Any] | None:
        session = register.sessions.filter(closed_at__isnull=True).select_related("opened_by").first()
        return {"id": session.pk, "opened_by": session.opened_by.name} if session else None


class SessionSerializer(serializers.ModelSerializer[CashSession]):
    register_name = serializers.CharField(source="register.name")
    location = serializers.IntegerField(source="register.location_id")
    opened_by = serializers.CharField(source="opened_by.name")
    closed_by = serializers.CharField(source="closed_by.name", allow_null=True)

    class Meta:
        model = CashSession
        fields = (
            "id",
            "register",
            "register_name",
            "location",
            "opened_by",
            "opened_at",
            "opening_float",
            "closed_by",
            "closed_at",
            "expected_cash",
            "counted_cash",
            "closing_note",
        )


class OpenSessionSerializer(serializers.Serializer[None]):
    register = serializers.PrimaryKeyRelatedField(queryset=CashRegister.objects.select_related("location"))
    opening_float = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal(0))


class CashMovementSerializer(serializers.ModelSerializer[CashMovement]):
    kind = serializers.ChoiceField(choices=[CashMovement.Kind.WITHDRAWAL, CashMovement.Kind.SUPPLY])

    class Meta:
        model = CashMovement
        fields = ("id", "kind", "amount", "reason", "created_at")


class CloseSessionSerializer(serializers.Serializer[None]):
    counted_cash = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal(0))
    note = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class ItemInputSerializer(serializers.Serializer[None]):
    variant = serializers.PrimaryKeyRelatedField(queryset=ProductVariant.objects.all())
    quantity = serializers.IntegerField(min_value=1)
    discount = serializers.DecimalField(
        max_digits=10, decimal_places=2, min_value=Decimal(0), required=False, default=Decimal(0)
    )


class PaymentInputSerializer(serializers.Serializer[None]):
    method = serializers.ChoiceField(choices=Payment.Method.choices)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    tendered = serializers.DecimalField(
        max_digits=12,
        decimal_places=2,
        required=False,
        allow_null=True,
        default=None,
    )
    installments = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )
    card_brand = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    nsu = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    store_credit_code = serializers.CharField(max_length=12, required=False, allow_blank=True, default="")


class SaleInputSerializer(serializers.Serializer[None]):
    client_request_id = serializers.UUIDField()
    items = ItemInputSerializer(many=True, allow_empty=False)
    payments = PaymentInputSerializer(many=True)
    discount = serializers.DecimalField(
        max_digits=12, decimal_places=2, min_value=Decimal(0), required=False, default=Decimal(0)
    )
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(), required=False, allow_null=True, default=None
    )
    salesperson = serializers.PrimaryKeyRelatedField(
        queryset=User.objects.filter(is_active=True), required=False, allow_null=True, default=None
    )
    approval = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )


class SaleItemSerializer(HidesCosts, serializers.ModelSerializer[SaleItem]):
    sku = serializers.CharField(source="variant.sku")
    product = serializers.CharField(source="variant.product.name")
    size = serializers.CharField(source="variant.size.label")
    color = serializers.CharField(source="variant.color.name")
    margin = serializers.SerializerMethodField()

    class Meta:
        model = SaleItem
        fields = (
            "id",
            "variant",
            "sku",
            "product",
            "size",
            "color",
            "quantity",
            "quantity_returned",
            "unit_price",
            "discount",
            "net_amount",
            "cost_value",
            "margin",
        )

    def get_margin(self, item: SaleItem) -> str:
        return str((item.net_amount - item.cost_value).quantize(Decimal("0.01")))


class PaymentSerializer(serializers.ModelSerializer[Payment]):
    method_label = serializers.CharField(source="get_method_display")

    class Meta:
        model = Payment
        fields = ("method", "method_label", "amount", "tendered", "change", "installments", "card_brand", "nsu")


class SaleSerializer(serializers.ModelSerializer[Sale]):
    location_code = serializers.CharField(source="location.code")
    cashier = serializers.CharField(source="cashier.name")
    salesperson = serializers.CharField(source="salesperson.name", allow_null=True)
    customer = serializers.CharField(source="customer.name", allow_null=True)
    status_label = serializers.CharField(source="get_status_display")
    items = serializers.SerializerMethodField()
    payments = PaymentSerializer(many=True)

    class Meta:
        model = Sale
        fields = (
            "id",
            "location",
            "location_code",
            "number",
            "status",
            "status_label",
            "cashier",
            "salesperson",
            "customer",
            "subtotal",
            "discount_total",
            "total",
            "created_at",
            "cancelled_at",
            "cancel_reason",
            "items",
            "payments",
        )

    def get_items(self, sale: Sale) -> list[dict[str, Any]]:
        # Prefetched in lists (pos.services.SALE_ITEMS); one query for a single sale.
        return SaleItemSerializer(sale.items.all(), many=True, context=self.context).data  # type: ignore[return-value]


class StoreCreditSerializer(serializers.ModelSerializer[StoreCredit]):
    customer = serializers.CharField(source="customer.name", allow_null=True)

    class Meta:
        model = StoreCredit
        fields = ("code", "customer", "balance", "expires_on", "created_at")


class CancelSaleSerializer(serializers.Serializer[None]):
    reason = serializers.CharField(max_length=200)


class ReturnLineInputSerializer(serializers.Serializer[None]):
    sale_item = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )
    variant = serializers.PrimaryKeyRelatedField(
        queryset=ProductVariant.objects.all(), required=False, allow_null=True, default=None
    )
    quantity = serializers.IntegerField(min_value=1)


class ReturnInputSerializer(serializers.Serializer[None]):
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.filter(kind=Location.Kind.STORE))
    sale = serializers.PrimaryKeyRelatedField(
        queryset=Sale.objects.all(), required=False, allow_null=True, default=None
    )
    lines = ReturnLineInputSerializer(many=True, allow_empty=False)
    refund_method = serializers.ChoiceField(choices=SaleReturn.Refund.choices)
    reason = serializers.CharField(max_length=200)
    customer = serializers.PrimaryKeyRelatedField(
        queryset=Customer.objects.all(), required=False, allow_null=True, default=None
    )
    approval = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )


class ExchangeInputSerializer(serializers.Serializer[None]):
    client_request_id = serializers.UUIDField()
    sale = serializers.PrimaryKeyRelatedField(
        queryset=Sale.objects.all(), required=False, allow_null=True, default=None
    )
    returned = ReturnLineInputSerializer(many=True, allow_empty=False)
    reason = serializers.CharField(max_length=200)
    items = ItemInputSerializer(many=True, allow_empty=False)
    payments = PaymentInputSerializer(many=True, required=False, default=list)
    approval = serializers.IntegerField(
        required=False,
        allow_null=True,
        default=None,
    )


class ReturnLineSerializer(HidesCosts, serializers.ModelSerializer[ReturnLine]):
    sku = serializers.CharField(source="variant.sku")

    class Meta:
        model = ReturnLine
        fields = ("id", "sale_item", "variant", "sku", "quantity", "refund_amount", "cost_value")


class ReturnSerializer(serializers.ModelSerializer[SaleReturn]):
    location_code = serializers.CharField(source="location.code")
    sale_number = serializers.IntegerField(source="original_sale.number", allow_null=True)
    store_credit = serializers.CharField(source="store_credit.code", allow_null=True)
    created_by = serializers.CharField(source="created_by.name")
    lines = serializers.SerializerMethodField()

    class Meta:
        model = SaleReturn
        fields = (
            "id",
            "location",
            "location_code",
            "original_sale",
            "sale_number",
            "refund_method",
            "total",
            "reason",
            "store_credit",
            "created_by",
            "created_at",
            "lines",
        )

    def get_lines(self, sale_return: SaleReturn) -> list[dict[str, Any]]:
        return ReturnLineSerializer(sale_return.lines.all(), many=True, context=self.context).data  # type: ignore[return-value]
