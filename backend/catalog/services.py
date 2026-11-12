"""
Catalog writes. Rules that span tables live here, the single write path, and are tested:
a variant's size belongs to its product's grid, and a variant price belongs to that product.
"""

from datetime import datetime, timedelta
from decimal import Decimal

from django.db import connection, transaction
from django.db.models import OuterRef, Q, QuerySet, Subquery
from django.db.models.functions import Coalesce
from django.utils import timezone

from accounts.models import User
from audit.services import record
from common.errors import DomainError

from .gtin import INTERNAL_PREFIX, internal_ean13, is_valid_gtin
from .models import Barcode, Color, Price, Product, ProductVariant, Size

# A price may start "now" give or take a request's latency, never in the past: rewriting
# what a past sale should have cost would make history lie.
BACKDATE_TOLERANCE = timedelta(minutes=1)


def next_internal_barcode() -> str:
    with connection.cursor() as cursor:
        cursor.execute("select nextval('catalog_internal_barcode_seq')")
        (serial,) = cursor.fetchone()
    return internal_ean13(serial)


def sku_code(product: Product, color: Color, size: Size) -> str:
    return f"{product.reference}-{color.code}-{size.label}".upper()


@transaction.atomic
def complete_grid(product: Product, colors: list[Color]) -> list[ProductVariant]:
    """
    Creates the missing size × color combinations for these colors, each with an internal
    barcode. Idempotent: existing variants are left alone, so adding a color or a size to the
    grid later only fills the gaps.
    """
    existing = set(product.variants.values_list("size_id", "color_id"))
    created: list[ProductVariant] = []
    for color in colors:
        for size in product.size_grid.sizes.all():
            if (size.pk, color.pk) in existing:
                continue
            variant = ProductVariant.objects.create(
                product=product, size=size, color=color, sku=sku_code(product, color, size)
            )
            Barcode.objects.create(code=next_internal_barcode(), variant=variant, kind=Barcode.Kind.INTERNAL)
            created.append(variant)
    return created


@transaction.atomic
def create_product(*, user: User, colors: list[Color], price: Decimal, **fields: object) -> Product:
    if not colors:
        raise DomainError("Escolha pelo menos uma cor.", "product_needs_a_color")
    product = Product.objects.create(**fields)
    if not product.size_grid.sizes.exists():
        raise DomainError("A grade escolhida não tem tamanhos.", "size_grid_empty")
    complete_grid(product, colors)
    set_price(user=user, product=product, amount=price)
    return product


def add_supplier_barcode(variant: ProductVariant, code: str) -> Barcode:
    code = code.strip()
    if not is_valid_gtin(code):
        raise DomainError("Código de barras inválido (dígito verificador ou tamanho).", "barcode_invalid")
    if code.startswith(INTERNAL_PREFIX) and len(code) == 13:
        raise DomainError("Este código está na faixa reservada aos códigos internos da loja.", "barcode_reserved")
    owner = Barcode.objects.filter(code=code).select_related("variant").first()
    if owner is not None:
        raise DomainError(f"Este código já pertence ao SKU {owner.variant.sku}.", "barcode_taken")
    return Barcode.objects.create(code=code, variant=variant, kind=Barcode.Kind.SUPPLIER)


@transaction.atomic
def set_price(
    *,
    user: User,
    product: Product,
    amount: Decimal,
    valid_from: datetime | None = None,
    variant: ProductVariant | None = None,
) -> Price:
    now = timezone.now()
    starts = valid_from or now
    if starts < now - BACKDATE_TOLERANCE:
        raise DomainError("O preço não pode começar no passado.", "price_backdated")
    if variant is not None and variant.product_id != product.pk:
        raise DomainError("Este SKU é de outro produto.", "price_variant_mismatch")
    if amount <= 0:
        raise DomainError("O preço precisa ser maior que zero.", "price_not_positive")
    previous = current_price(variant, at=starts) if variant is not None else current_product_price(product, at=starts)
    price = Price.objects.create(product=product, variant=variant, amount=amount, valid_from=starts, created_by=user)
    record(
        actor=user,
        action="price.scheduled" if starts > now + BACKDATE_TOLERANCE else "price.changed",
        target=price,
        data={
            "product": product.reference,
            "sku": variant.sku if variant else None,
            "from": str(previous) if previous is not None else None,
            "to": str(amount),
            "valid_from": starts.isoformat(),
        },
    )
    return price


@transaction.atomic
def cancel_scheduled_price(*, user: User, price: Price) -> None:
    """Only a price that hasn't started yet can be withdrawn; a past one is history."""
    if price.valid_from <= timezone.now():
        raise DomainError("Este preço já entrou em vigor e não pode ser cancelado.", "price_already_effective")
    record(
        actor=user,
        action="price.cancelled",
        target=price,
        data={
            "product": price.product.reference,
            "amount": str(price.amount),
            "valid_from": price.valid_from.isoformat(),
        },
    )
    price.delete()


def _prices_at(at: datetime | None) -> QuerySet[Price]:
    return Price.objects.filter(valid_from__lte=at or timezone.now()).order_by("-valid_from")


def current_product_price(product: Product, *, at: datetime | None = None) -> Decimal | None:
    row = _prices_at(at).filter(product=product, variant__isnull=True).first()
    return row.amount if row else None


def current_price(variant: ProductVariant, *, at: datetime | None = None) -> Decimal | None:
    """The SKU's own price if it has one in force, otherwise the product's."""
    prices = _prices_at(at).filter(product_id=variant.product_id)
    row = prices.filter(variant=variant).first() or prices.filter(variant__isnull=True).first()
    return row.amount if row else None


def with_current_price(variants: QuerySet[ProductVariant], *, at: datetime | None = None) -> QuerySet[ProductVariant]:
    """Annotates `current_price` in one query, with the same precedence as current_price()."""
    prices = _prices_at(at)
    own = prices.filter(variant=OuterRef("pk")).values("amount")[:1]
    product_wide = prices.filter(product=OuterRef("product_id"), variant__isnull=True).values("amount")[:1]
    return variants.annotate(current_price=Coalesce(Subquery(own), Subquery(product_wide)))


def search_products(products: QuerySet[Product], q: str) -> QuerySet[Product]:
    q = q.strip()
    if not q:
        return products
    # A subquery, not a join on variants: a join would multiply the rows (and any count annotated on them).
    by_sku = ProductVariant.objects.filter(sku__icontains=q).values("product_id")
    return products.filter(Q(name__icontains=q) | Q(reference__icontains=q) | Q(pk__in=by_sku))
