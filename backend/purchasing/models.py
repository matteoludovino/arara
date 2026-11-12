from django.conf import settings
from django.db import models
from django.db.models.functions import Lower

from catalog.models import ProductVariant
from locations.models import Location
from stock.models import StockEntry


class Supplier(models.Model):
    name = models.CharField(max_length=120)
    cnpj = models.CharField(max_length=14, blank=True)
    contact = models.CharField(max_length=120, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = (
            models.UniqueConstraint(Lower("name"), name="supplier_name_unique_ci"),
            models.UniqueConstraint(fields=("cnpj",), condition=~models.Q(cnpj=""), name="supplier_cnpj_unique"),
            # Alphanumeric since July 2026: 12 characters in [0-9A-Z] plus 2 numeric check digits.
            models.CheckConstraint(
                condition=models.Q(cnpj="") | models.Q(cnpj__regex=r"^[0-9A-Z]{12}[0-9]{2}$"),
                name="supplier_cnpj_format",
            ),
        )

    def __str__(self) -> str:
        return self.name


class PurchaseOrder(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        SENT = "sent", "Enviado"
        PARTIALLY_RECEIVED = "partially_received", "Recebido em parte"
        RECEIVED = "received", "Recebido"
        CLOSED = "closed", "Encerrado com pendência"
        CANCELLED = "cancelled", "Cancelado"

    OPEN = (Status.SENT, Status.PARTIALLY_RECEIVED)  # waiting for goods

    number = models.CharField(max_length=12, unique=True)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="orders")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="purchase_orders")
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.DRAFT)
    expected_on = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)  # received, closed or cancelled
    finish_reason = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("-created_at",)
        indexes = (models.Index(fields=("status", "location")),)

    def __str__(self) -> str:
        return self.number


class PurchaseOrderLine(models.Model):
    order = models.ForeignKey(PurchaseOrder, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="+")
    quantity_ordered = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)
    quantity_received = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("id",)
        constraints = (
            models.UniqueConstraint(fields=("order", "variant"), name="one_line_per_sku_in_order"),
            models.CheckConstraint(condition=models.Q(quantity_ordered__gt=0), name="po_line_quantity_positive"),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="po_line_cost_not_negative"),
            # Receiving more than was ordered is refused: extra pieces need a corrected order first.
            models.CheckConstraint(
                condition=models.Q(quantity_received__lte=models.F("quantity_ordered")),
                name="po_line_not_over_received",
            ),
        )

    def __str__(self) -> str:
        return f"{self.order_id}: {self.variant_id} × {self.quantity_ordered}"

    @property
    def pending(self) -> int:
        return self.quantity_ordered - self.quantity_received


class GoodsReceipt(models.Model):
    """One delivery against an order (there may be several). Cancelling it reverses its stock entry."""

    order = models.ForeignKey(PurchaseOrder, on_delete=models.PROTECT, related_name="receipts")
    invoice_number = models.CharField(max_length=30, blank=True)  # the supplier's NF-e
    stock_entry = models.OneToOneField(StockEntry, on_delete=models.PROTECT, related_name="+")
    received_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    received_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_entry = models.OneToOneField(
        StockEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ("-received_at",)
        constraints = (
            models.CheckConstraint(
                condition=models.Q(cancelled_at__isnull=True, cancellation_entry__isnull=True)
                | models.Q(cancelled_at__isnull=False, cancellation_entry__isnull=False),
                name="receipt_cancellation_is_complete",
            ),
        )

    def __str__(self) -> str:
        return f"receipt {self.pk} of {self.order_id}"


class GoodsReceiptLine(models.Model):
    receipt = models.ForeignKey(GoodsReceipt, on_delete=models.CASCADE, related_name="lines")
    order_line = models.ForeignKey(PurchaseOrderLine, on_delete=models.PROTECT, related_name="receipt_lines")
    quantity = models.PositiveIntegerField()
    # The invoice's cost, which may differ from the order's.
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)

    class Meta:
        constraints = (
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="receipt_line_quantity_positive"),
            models.UniqueConstraint(fields=("receipt", "order_line"), name="one_receipt_line_per_order_line"),
        )

    def __str__(self) -> str:
        return f"{self.receipt_id}: {self.order_line_id} × {self.quantity}"


class PurchaseReturn(models.Model):
    """Goods sent back to a supplier, leaving inventory at the average cost."""

    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="returns")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=200)
    stock_entry = models.OneToOneField(StockEntry, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self) -> str:
        return f"return {self.pk} to {self.supplier_id}"
