from django.conf import settings
from django.db import models
from django.db.models.functions import Lower


class Category(models.Model):
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        verbose_name_plural = "categories"
        constraints = (models.UniqueConstraint(Lower("name"), name="category_name_unique_ci"),)

    def __str__(self) -> str:
        return self.name


class Brand(models.Model):
    name = models.CharField(max_length=60)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("name",)
        constraints = (models.UniqueConstraint(Lower("name"), name="brand_name_unique_ci"),)

    def __str__(self) -> str:
        return self.name


class Collection(models.Model):
    """A season or drop ("Verão 2027"): what markdowns and stock-ageing reports group by."""

    name = models.CharField(max_length=60)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("-starts_on", "name")
        constraints = (
            models.UniqueConstraint(Lower("name"), name="collection_name_unique_ci"),
            models.CheckConstraint(
                condition=models.Q(starts_on__isnull=True)
                | models.Q(ends_on__isnull=True)
                | models.Q(ends_on__gte=models.F("starts_on")),
                name="collection_dates_in_order",
            ),
        )

    def __str__(self) -> str:
        return self.name


class SizeGrid(models.Model):
    """An ordered set of sizes: "PP–GG", "34–46", "Calçados 33–44", "Único"."""

    name = models.CharField(max_length=40)

    class Meta:
        ordering = ("name",)
        constraints = (models.UniqueConstraint(Lower("name"), name="size_grid_name_unique_ci"),)

    def __str__(self) -> str:
        return self.name


class Size(models.Model):
    grid = models.ForeignKey(SizeGrid, on_delete=models.CASCADE, related_name="sizes")
    label = models.CharField(max_length=8)
    position = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ("grid", "position")
        constraints = (
            models.UniqueConstraint(fields=("grid", "label"), name="size_label_unique_in_grid"),
            models.UniqueConstraint(fields=("grid", "position"), name="size_position_unique_in_grid"),
        )

    def __str__(self) -> str:
        return self.label


class Color(models.Model):
    name = models.CharField(max_length=40)
    # Short code used in SKU codes: "PRE" for preto.
    code = models.CharField(max_length=4)
    hex = models.CharField(max_length=7, blank=True)

    class Meta:
        ordering = ("name",)
        constraints = (
            models.UniqueConstraint(Lower("name"), name="color_name_unique_ci"),
            models.UniqueConstraint(Lower("code"), name="color_code_unique_ci"),
            models.CheckConstraint(condition=models.Q(code__regex=r"^[A-Z0-9]{2,4}$"), name="color_code_format"),
            models.CheckConstraint(
                condition=models.Q(hex="") | models.Q(hex__regex=r"^#[0-9A-Fa-f]{6}$"), name="color_hex_format"
            ),
        )

    def __str__(self) -> str:
        return self.name


class Product(models.Model):
    """
    A model in the store's vocabulary ("Camiseta básica gola V"). What is sold and stocked is
    a variant of it: one size in one color.
    """

    # The supplier's or the store's style reference, printed on the tag: "CAM-0042".
    reference = models.CharField(max_length=20)
    name = models.CharField(max_length=120)
    description = models.TextField(blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    brand = models.ForeignKey(Brand, null=True, blank=True, on_delete=models.PROTECT, related_name="products")
    collection = models.ForeignKey(Collection, null=True, blank=True, on_delete=models.PROTECT, related_name="products")
    size_grid = models.ForeignKey(SizeGrid, on_delete=models.PROTECT, related_name="products")
    # Fiscal classification, empty until invoices exist (out of scope, but cheap to keep now).
    ncm = models.CharField(max_length=8, blank=True)
    cest = models.CharField(max_length=7, blank=True)
    origin = models.CharField(max_length=1, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = (
            models.UniqueConstraint(Lower("reference"), name="product_reference_unique_ci"),
            models.CheckConstraint(
                condition=models.Q(ncm="") | models.Q(ncm__regex=r"^\d{8}$"), name="product_ncm_format"
            ),
        )

    def __str__(self) -> str:
        return f"{self.reference} · {self.name}"


class ProductVariant(models.Model):
    """The SKU: what has stock, a barcode and a line on a sale."""

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="variants")
    size = models.ForeignKey(Size, on_delete=models.PROTECT, related_name="+")
    color = models.ForeignKey(Color, on_delete=models.PROTECT, related_name="+")
    sku = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("product", "color__name", "size__position")
        constraints = (
            models.UniqueConstraint(fields=("product", "size", "color"), name="one_variant_per_size_and_color"),
            models.UniqueConstraint(Lower("sku"), name="variant_sku_unique_ci"),
        )

    def __str__(self) -> str:
        return self.sku


class Barcode(models.Model):
    """
    A scannable code for a SKU. A SKU may have several: the supplier's EAN on the tag and the
    store's own internal code. Codes are globally unique: a scan must resolve to one SKU.
    """

    class Kind(models.TextChoices):
        INTERNAL = "internal", "Interno"
        SUPPLIER = "supplier", "Fornecedor"

    code = models.CharField(max_length=14, unique=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="barcodes")
    kind = models.CharField(max_length=10, choices=Kind.choices)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("created_at",)
        constraints = (
            models.CheckConstraint(condition=models.Q(code__regex=r"^(\d{8}|\d{12,14})$"), name="barcode_gtin_length"),
        )

    def __str__(self) -> str:
        return self.code


class Price(models.Model):
    """
    Selling price, never edited: a change is a new row from `valid_from` on, so a clearance
    can be scheduled and any past price looked up. A row with a variant overrides the
    product-wide price for that SKU (an XXL that costs more).
    """

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="prices")
    variant = models.ForeignKey(ProductVariant, null=True, blank=True, on_delete=models.PROTECT, related_name="prices")
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    valid_from = models.DateTimeField()
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-valid_from",)
        constraints = (
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="price_positive"),
            models.UniqueConstraint(
                fields=("product", "variant", "valid_from"), nulls_distinct=False, name="one_price_per_start"
            ),
        )
        indexes = (models.Index(fields=("product", "variant", "-valid_from")),)

    def __str__(self) -> str:
        return f"{self.amount} from {self.valid_from:%Y-%m-%d}"
