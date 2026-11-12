"""
Physical inventory counts. The store keeps selling while it counts, so a count never "sets"
a balance: each entry records the system quantity read (under lock) when it was counted, and
applying adds the difference to whatever the balance is by then.
"""

from django.conf import settings
from django.db import models

from catalog.models import ProductVariant
from locations.models import Location
from stock.models import StockEntry


class InventoryCount(models.Model):
    class Status(models.TextChoices):
        COUNTING = "counting", "Em contagem"
        REVIEW = "review", "Em revisão"
        APPLIED = "applied", "Aplicada"
        CANCELLED = "cancelled", "Cancelada"

    ACTIVE = (Status.COUNTING, Status.REVIEW)

    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="counts")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COUNTING)
    # Differences up to this many pieces don't call for a recount.
    tolerance = models.PositiveSmallIntegerField(default=0)
    scope_label = models.CharField(max_length=120)
    note = models.CharField(max_length=200, blank=True)
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    opened_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    applied_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    applied_at = models.DateTimeField(null=True, blank=True)
    entry = models.OneToOneField(StockEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-opened_at",)
        constraints = (
            # Two counts of the same shelves at once would apply the same differences twice.
            models.UniqueConstraint(
                fields=("location",),
                condition=models.Q(status__in=("counting", "review")),
                name="one_active_count_per_location",
            ),
        )

    def __str__(self) -> str:
        return f"count {self.pk} at {self.location_id}"


class CountScopeItem(models.Model):
    """The SKUs this count covers, frozen when it opens: products created later aren't in it."""

    count = models.ForeignKey(InventoryCount, on_delete=models.CASCADE, related_name="scope")
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="+")

    class Meta:
        constraints = (models.UniqueConstraint(fields=("count", "variant"), name="one_scope_item_per_sku"),)

    def __str__(self) -> str:
        return f"{self.count_id}: {self.variant_id}"


class CountEntry(models.Model):
    """
    Pieces of one SKU found in one area by one person. Several entries per SKU add up
    (shop window + back room). Working data: deleted on a recount, until the count is applied.
    """

    count = models.ForeignKey(InventoryCount, on_delete=models.CASCADE, related_name="entries")
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="+")
    area = models.CharField(max_length=40)
    quantity = models.PositiveIntegerField()
    # The system's balance and the last ledger line of this SKU here, read under the stock lock.
    system_quantity = models.IntegerField()
    ledger_mark = models.BigIntegerField()
    counted_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)
        indexes = (models.Index(fields=("count", "variant")),)

    def __str__(self) -> str:
        return f"{self.count_id}: {self.variant_id} × {self.quantity} ({self.area})"
