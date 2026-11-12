from django.contrib import admin

from .models import Barcode, Brand, Category, Collection, Color, Price, Product, ProductVariant, SizeGrid


class SizeInline(admin.TabularInline):  # type: ignore[type-arg]
    model = SizeGrid.sizes.rel.related_model
    extra = 0


@admin.register(SizeGrid)
class SizeGridAdmin(admin.ModelAdmin[SizeGrid]):
    inlines = (SizeInline,)


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin[Product]):
    list_display = ("reference", "name", "category", "brand", "collection", "is_active")
    list_filter = ("category", "brand", "collection", "is_active")
    search_fields = ("reference", "name")


@admin.register(ProductVariant)
class VariantAdmin(admin.ModelAdmin[ProductVariant]):
    list_display = ("sku", "product", "size", "color", "is_active")
    search_fields = ("sku",)


@admin.register(Price)
class PriceAdmin(admin.ModelAdmin[Price]):
    list_display = ("product", "variant", "amount", "valid_from", "created_by")

    def has_change_permission(self, request: object, obj: object = None) -> bool:
        return False


admin.site.register((Category, Brand, Collection, Color, Barcode))
