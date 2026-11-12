"""
Stock is a ledger. Every change is an immutable StockEntry (one business event) with its
StockMovement lines; StockLevel and SkuCost are projections of that ledger, updated in the
same transaction by stock.services.post_entry(), the only code that writes any of them.

Valuation is a moving weighted average per SKU, company-wide: SkuCost holds the total
quantity and value of the SKU in inventory locations (stores, warehouses, transit), and the
average is value / quantity. Moving goods between inventory locations is cost-neutral;
anything entering or leaving inventory changes the total. Values carry four decimals so
repeated averaging doesn't drift, and the value of the stock at any moment is the sum of
the value deltas up to it.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models

from catalog.models import ProductVariant
from locations.models import Location

QTY_ZERO = 0
VALUE_ZERO = Decimal("0.0000")


class StockLevel(models.Model):
    """Pieces of one SKU at one location: the ledger's running balance, plus restock targets."""

    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="stock_levels")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="stock_levels")
    quantity = models.IntegerField(default=0)
    # Restock targets for this store: below `min_quantity` is a stock-out risk, refill to `max_quantity`.
    min_quantity = models.PositiveIntegerField(default=0)
    max_quantity = models.PositiveIntegerField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("variant_id", "location_id")
        constraints = (
            models.UniqueConstraint(fields=("variant", "location"), name="one_level_per_sku_and_location"),
            # The services check this first and explain it; the database is the last line of defence.
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name="stock_never_negative"),
            models.CheckConstraint(
                condition=models.Q(max_quantity__isnull=True) | models.Q(max_quantity__gte=models.F("min_quantity")),
                name="stock_targets_in_order",
            ),
        )

    def __str__(self) -> str:
        return f"{self.variant_id}@{self.location_id}: {self.quantity}"


class SkuCost(models.Model):
    """The SKU's inventory across the company: one lockable row for the moving average."""

    variant = models.OneToOneField(ProductVariant, primary_key=True, on_delete=models.PROTECT, related_name="cost")
    quantity = models.IntegerField(default=0)
    value = models.DecimalField(max_digits=16, decimal_places=4, default=VALUE_ZERO)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = (
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name="sku_cost_quantity_not_negative"),
            models.CheckConstraint(condition=models.Q(value__gte=0), name="sku_cost_value_not_negative"),
            # No stock, no value: the last piece out takes whatever value was left.
            models.CheckConstraint(
                condition=models.Q(quantity__gt=0) | models.Q(value=0), name="sku_cost_empty_has_no_value"
            ),
        )

    def __str__(self) -> str:
        return f"{self.variant_id}: {self.quantity} / {self.value}"


class StockEntry(models.Model):
    """One business event that moves stock or value. Immutable (a database trigger enforces it)."""

    class Kind(models.TextChoices):
        PURCHASE_RECEIPT = "purchase_receipt", "Recebimento de compra"
        RECEIPT_CANCELLATION = "receipt_cancellation", "Estorno de recebimento"
        PURCHASE_RETURN = "purchase_return", "Devolução ao fornecedor"
        SALE = "sale", "Venda"
        SALE_CANCELLATION = "sale_cancellation", "Cancelamento de venda"
        SALE_RETURN = "sale_return", "Devolução de cliente"
        TRANSFER_DISPATCH = "transfer_dispatch", "Envio de transferência"
        TRANSFER_RECEIPT = "transfer_receipt", "Recebimento de transferência"
        ADJUSTMENT = "adjustment", "Ajuste manual"
        COUNT_ADJUSTMENT = "count_adjustment", "Acerto de inventário"
        COST_ADJUSTMENT = "cost_adjustment", "Ajuste de custo"

    class Reason(models.TextChoices):
        DAMAGED = "damaged", "Avaria"
        THEFT = "theft", "Furto"
        FOUND = "found", "Encontrado"
        ERROR = "error", "Erro de lançamento"
        OTHER = "other", "Outro"

    kind = models.CharField(max_length=24, choices=Kind.choices)
    reason = models.CharField(max_length=12, choices=Reason.choices, blank=True)
    note = models.CharField(max_length=200, blank=True)
    # The document that caused it, e.g. "sale:120" or "receipt:7".
    source_ref = models.CharField(max_length=60, blank=True, db_index=True)
    approval = models.ForeignKey("accounts.Approval", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("-created_at", "-id")
        verbose_name_plural = "stock entries"

    def __str__(self) -> str:
        return f"#{self.pk} {self.kind}"


class StockMovement(models.Model):
    """One line of an entry: a SKU's quantity and value changing at one location. Immutable."""

    entry = models.ForeignKey(StockEntry, on_delete=models.PROTECT, related_name="movements")
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="movements")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="movements")
    quantity_delta = models.IntegerField()
    value_delta = models.DecimalField(max_digits=16, decimal_places=4)
    unit_cost = models.DecimalField(max_digits=14, decimal_places=4)
    # The location's balance right after this line: the ledger reads like a bank statement.
    balance_after = models.IntegerField()

    class Meta:
        ordering = ("id",)
        indexes = (models.Index(fields=("variant", "location", "id")),)
        constraints = (
            models.CheckConstraint(condition=models.Q(balance_after__gte=0), name="movement_balance_not_negative"),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="movement_unit_cost_not_negative"),
            # Quantity and value move in the same direction (or value alone, for a cost adjustment).
            models.CheckConstraint(
                condition=models.Q(quantity_delta__gt=0, value_delta__gte=0)
                | models.Q(quantity_delta__lt=0, value_delta__lte=0)
                | models.Q(quantity_delta=0),
                name="movement_value_follows_quantity",
            ),
        )

    def __str__(self) -> str:
        return f"{self.variant_id}@{self.location_id} {self.quantity_delta:+d}"
