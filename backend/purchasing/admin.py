from django.contrib import admin

from .models import GoodsReceipt, PurchaseOrder, PurchaseReturn, Supplier


@admin.register(Supplier)
class SupplierAdmin(admin.ModelAdmin[Supplier]):
    list_display = ("name", "cnpj", "contact", "is_active")
    search_fields = ("name", "cnpj")


@admin.register(PurchaseOrder)
class PurchaseOrderAdmin(admin.ModelAdmin[PurchaseOrder]):
    list_display = ("number", "supplier", "location", "status", "created_at")
    list_filter = ("status",)

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False  # orders change through their actions, which keep stock in step


@admin.register(GoodsReceipt, PurchaseReturn)
class StockDocumentAdmin(admin.ModelAdmin):  # type: ignore[type-arg]
    """Receipts and returns moved stock: they are read here, changed only through their actions."""

    def has_add_permission(self, request: object) -> bool:
        return False

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: object, obj: object = None) -> bool:
        return False
