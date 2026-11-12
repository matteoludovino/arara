from django.conf import settings
from django.db import models

from catalog.models import ProductVariant
from locations.models import Location
from stock.models import StockEntry


class Transfer(models.Model):
    """
    Goods moving between two of the company's locations. Dispatching moves them into the
    transit location; receiving moves them out of it into the destination, and whatever
    didn't arrive out of it into losses. Stock in transit is still the company's inventory.
    """

    class Status(models.TextChoices):
        DRAFT = "draft", "Rascunho"
        IN_TRANSIT = "in_transit", "Em trânsito"
        RECEIVED = "received", "Recebida"
        CANCELLED = "cancelled", "Cancelada"

    number = models.CharField(max_length=12, unique=True)
    origin = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="transfers_out")
    destination = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="transfers_in")
    status = models.CharField(max_length=12, choices=Status.choices, default=Status.DRAFT)
    notes = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    dispatched_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    dispatched_at = models.DateTimeField(null=True, blank=True)
    dispatch_entry = models.OneToOneField(StockEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    received_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    received_at = models.DateTimeField(null=True, blank=True)
    receipt_entry = models.OneToOneField(StockEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.CharField(max_length=200, blank=True)
    cancel_entry = models.OneToOneField(StockEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(origin=models.F("destination")), name="transfer_between_two_places"
            ),
            # Each status carries exactly the stock entries it implies.
            models.CheckConstraint(
                condition=models.Q(status="draft", dispatch_entry__isnull=True, receipt_entry__isnull=True)
                | models.Q(status="in_transit", dispatch_entry__isnull=False, receipt_entry__isnull=True)
                | models.Q(status="received", dispatch_entry__isnull=False, receipt_entry__isnull=False)
                | models.Q(status="cancelled", receipt_entry__isnull=True),
                name="transfer_entries_match_status",
            ),
        )
        indexes = (models.Index(fields=("status", "destination")),)

    def __str__(self) -> str:
        return self.number


class TransferLine(models.Model):
    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="+")
    quantity_sent = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(null=True, blank=True)

    class Meta:
        ordering = ("id",)
        constraints = (
            models.UniqueConstraint(fields=("transfer", "variant"), name="one_line_per_sku_in_transfer"),
            models.CheckConstraint(condition=models.Q(quantity_sent__gt=0), name="transfer_line_quantity_positive"),
            models.CheckConstraint(
                condition=models.Q(quantity_received__isnull=True)
                | models.Q(quantity_received__lte=models.F("quantity_sent")),
                name="transfer_line_not_over_received",
            ),
        )

    def __str__(self) -> str:
        return f"{self.transfer_id}: {self.variant_id} × {self.quantity_sent}"
