from decimal import Decimal
from typing import Any, cast

from django.db.models import Count, OuterRef, QuerySet, Subquery
from django.utils import timezone
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.capabilities import Capability
from accounts.models import User
from accounts.permissions import read_or

from . import services
from .models import Brand, Category, Collection, Color, Price, Product, ProductVariant, SizeGrid
from .serializers import (
    AddColorsSerializer,
    BrandSerializer,
    CategorySerializer,
    CollectionSerializer,
    ColorSerializer,
    LookupSerializer,
    PriceSerializer,
    ProductCreateSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    ProductUpdateSerializer,
    SizeGridSerializer,
    SupplierBarcodeSerializer,
    VariantSerializer,
)

CatalogWrite = read_or(Capability.CATALOG_MANAGE)
WRITE_METHODS = ("get", "post", "patch", "head", "options")


class CategoryViewSet(viewsets.ModelViewSet[Category]):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = (CatalogWrite,)
    http_method_names = WRITE_METHODS


class BrandViewSet(viewsets.ModelViewSet[Brand]):
    queryset = Brand.objects.all()
    serializer_class = BrandSerializer
    permission_classes = (CatalogWrite,)
    http_method_names = WRITE_METHODS


class CollectionViewSet(viewsets.ModelViewSet[Collection]):
    queryset = Collection.objects.all()
    serializer_class = CollectionSerializer
    permission_classes = (CatalogWrite,)
    http_method_names = WRITE_METHODS


class ColorViewSet(viewsets.ModelViewSet[Color]):
    queryset = Color.objects.all()
    serializer_class = ColorSerializer
    permission_classes = (CatalogWrite,)
    http_method_names = WRITE_METHODS


class SizeGridViewSet(
    mixins.ListModelMixin, mixins.RetrieveModelMixin, mixins.CreateModelMixin, viewsets.GenericViewSet[SizeGrid]
):
    """Grids are created with their sizes. Sizes are only appended later: products depend on them."""

    queryset = SizeGrid.objects.prefetch_related("sizes")
    serializer_class = SizeGridSerializer
    permission_classes = (CatalogWrite,)

    @action(detail=True, methods=["post"])
    def sizes(self, request: Request, pk: str) -> Response:
        grid = self.get_object()
        label = str(cast(dict[str, Any], request.data).get("label", "")).strip().upper()
        if not label or len(label) > 8:
            return Response({"label": ["Informe o tamanho (até 8 caracteres)."]}, status=status.HTTP_400_BAD_REQUEST)
        if grid.sizes.filter(label=label).exists():
            return Response({"label": ["Este tamanho já está na grade."]}, status=status.HTTP_400_BAD_REQUEST)
        last = grid.sizes.order_by("-position").values_list("position", flat=True).first() or 0
        grid.sizes.create(label=label, position=last + 1)
        return Response(SizeGridSerializer(grid).data, status=status.HTTP_201_CREATED)


class ProductViewSet(viewsets.ModelViewSet[Product]):
    permission_classes = (CatalogWrite,)
    http_method_names = WRITE_METHODS
    filterset_fields = ("category", "brand", "collection", "is_active")

    def get_queryset(self) -> QuerySet[Product]:
        products = Product.objects.select_related("category", "brand", "collection", "size_grid")
        if self.action == "list":
            product_wide = Price.objects.filter(
                product=OuterRef("pk"), variant__isnull=True, valid_from__lte=timezone.now()
            ).order_by("-valid_from")
            products = products.annotate(
                current_price=Subquery(product_wide.values("amount")[:1]), variant_count=Count("variants")
            )
            products = services.search_products(products, self.request.query_params.get("q", ""))
        return products

    def get_serializer_class(self) -> Any:
        return {
            "list": ProductListSerializer,
            "create": ProductCreateSerializer,
            "partial_update": ProductUpdateSerializer,
        }.get(self.action, ProductDetailSerializer)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        data = ProductCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        fields = dict(data.validated_data)
        product = services.create_product(
            user=cast(User, request.user), colors=fields.pop("colors"), price=fields.pop("price"), **fields
        )
        return Response(ProductDetailSerializer(product).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def colors(self, request: Request, pk: str) -> Response:
        product = self.get_object()
        data = AddColorsSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.complete_grid(product, data.validated_data["colors"])
        return Response(ProductDetailSerializer(product).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"], permission_classes=(read_or(Capability.PRICES_CHANGE),))
    def prices(self, request: Request, pk: str) -> Response:
        product = self.get_object()
        if request.method == "GET":
            history = product.prices.select_related("variant", "created_by")
            return Response(PriceSerializer(history, many=True).data)
        data = PriceSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        price = services.set_price(
            user=cast(User, request.user),
            product=product,
            amount=cast(Decimal, data.validated_data["amount"]),
            valid_from=data.validated_data.get("valid_from"),
            variant=data.validated_data.get("variant"),
        )
        return Response(PriceSerializer(price).data, status=status.HTTP_201_CREATED)


class PriceViewSet(mixins.DestroyModelMixin, viewsets.GenericViewSet[Price]):
    """Withdraws a scheduled price that hasn't started yet."""

    queryset = Price.objects.select_related("product")
    permission_classes = (read_or(Capability.PRICES_CHANGE),)

    def perform_destroy(self, instance: Price) -> None:
        services.cancel_scheduled_price(user=cast(User, self.request.user), price=instance)


class VariantViewSet(mixins.RetrieveModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet[ProductVariant]):
    serializer_class = VariantSerializer
    permission_classes = (CatalogWrite,)
    http_method_names = ("get", "patch", "post", "head", "options")

    def get_queryset(self) -> QuerySet[ProductVariant]:
        return services.with_current_price(
            ProductVariant.objects.select_related("size", "color").prefetch_related("barcodes")
        )

    @action(detail=True, methods=["post"])
    def barcodes(self, request: Request, pk: str) -> Response:
        variant = self.get_object()
        data = SupplierBarcodeSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.add_supplier_barcode(variant, data.validated_data["code"])
        return Response(VariantSerializer(self.get_queryset().get(pk=variant.pk)).data, status=status.HTTP_201_CREATED)


class LookupView(APIView):
    """GET /api/catalog/lookup?code=…: a scan (barcode) or a typed SKU, resolved to one variant."""

    def get(self, request: Request) -> Response:
        code = request.query_params.get("code", "").strip()
        if not code:
            raise NotFound("Informe o código.")
        variants = services.with_current_price(ProductVariant.objects.select_related("product", "size", "color"))
        variant = services.variant_for_code(code, variants)
        if variant is None:
            raise NotFound("Código não encontrado.")
        return Response(LookupSerializer(variant).data)
