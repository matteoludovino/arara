from django.contrib import admin

from .models import SkuCost, StockEntry, StockLevel, StockMovement


class ReadOnlyAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """The ledger is written by the services only; the admin just reads it."""

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False


@admin.register(StockEntry)
class StockEntryAdmin(ReadOnlyAdmin):
    list_display = ("id", "kind", "reason", "source_ref", "created_by", "created_at")
    list_filter = ("kind",)


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ("id", "entry", "variant", "location", "quantity_delta", "value_delta", "balance_after")


@admin.register(StockLevel)
class StockLevelAdmin(ReadOnlyAdmin):
    list_display = ("variant", "location", "quantity", "min_quantity", "max_quantity")


@admin.register(SkuCost)
class SkuCostAdmin(ReadOnlyAdmin):
    list_display = ("variant", "quantity", "value")
