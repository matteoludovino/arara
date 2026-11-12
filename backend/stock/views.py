from typing import Any, cast

from django.db.models import F, QuerySet
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.capabilities import Capability, can, location_ids_for
from accounts.models import User
from accounts.permissions import requires
from accounts.visibility import cost_context
from catalog.models import Product

from . import services
from .models import StockLevel, StockMovement
from .serializers import AdjustmentSerializer, MovementSerializer, StockLevelSerializer

StockReaders = requires(Capability.STOCK_VIEW)


def _user(request: Request) -> User:
    return cast(User, request.user)


class StockLevelViewSet(mixins.ListModelMixin, mixins.UpdateModelMixin, viewsets.GenericViewSet[StockLevel]):
    """Balances at the locations the user works at. PATCH sets restock targets."""

    queryset = StockLevel.objects.none()  # the model, for the schema: get_queryset scopes it to the user
    serializer_class = StockLevelSerializer
    permission_classes = (StockReaders,)
    http_method_names = ("get", "patch", "head", "options")
    filterset_fields = ("location", "variant", "variant__product")

    def get_serializer_context(self) -> dict[str, Any]:
        return cost_context(super().get_serializer_context(), self.request)

    def get_queryset(self) -> QuerySet[StockLevel]:
        levels = StockLevel.objects.filter(location_id__in=location_ids_for(_user(self.request))).select_related(
            "variant__product", "variant__size", "variant__color", "variant__cost", "location"
        )
        if self.request.query_params.get("below_min") in ("1", "true"):
            levels = levels.filter(quantity__lt=F("min_quantity"))
        return levels.order_by("variant__product__name", "variant__color__name", "variant__size__position")

    def perform_update(self, serializer: StockLevelSerializer) -> None:  # type: ignore[override]
        level = cast(StockLevel, serializer.instance)
        if not can(self.request.user, Capability.STOCK_ADJUST, level.location):
            raise PermissionDenied("Só o gerente da loja define mínimo e máximo.")
        serializer.save()


class MovementViewSet(mixins.ListModelMixin, viewsets.GenericViewSet[StockMovement]):
    """The ledger, newest first, for the locations the user works at."""

    queryset = StockMovement.objects.none()  # the model, for the schema: get_queryset scopes it to the user
    serializer_class = MovementSerializer
    permission_classes = (StockReaders,)
    filterset_fields = ("variant", "location", "entry__kind", "entry")

    def get_serializer_context(self) -> dict[str, Any]:
        return cost_context(super().get_serializer_context(), self.request)

    def get_queryset(self) -> QuerySet[StockMovement]:
        return (
            StockMovement.objects.filter(location_id__in=location_ids_for(_user(self.request)))
            .select_related("entry__created_by", "variant", "location")
            .order_by("-id")
        )


class GridView(APIView):
    """GET /api/stock/grid?product=…&location=…: quantities as a color × size matrix."""

    permission_classes = (StockReaders,)

    @extend_schema(
        parameters=[OpenApiParameter("product", int, required=True), OpenApiParameter("location", int)],
        responses=OpenApiTypes.OBJECT,
    )
    def get(self, request: Request) -> Response:
        product = get_object_or_404(Product.objects.select_related("size_grid"), pk=request.query_params.get("product"))
        visible = location_ids_for(_user(request))
        location = request.query_params.get("location")
        if location is not None:
            if not location.isdigit() or int(location) not in visible:
                raise PermissionDenied("Local fora do seu acesso.")
            visible = [int(location)]
        sizes = list(product.size_grid.sizes.values_list("label", flat=True))
        quantities: dict[tuple[str, str], int] = {}
        for color, size, quantity in StockLevel.objects.filter(
            variant__product=product, location_id__in=visible
        ).values_list("variant__color__name", "variant__size__label", "quantity"):
            quantities[(color, size)] = quantities.get((color, size), 0) + quantity
        # order_by() clears the model's default ordering, which DISTINCT would otherwise include.
        colors = list(product.variants.order_by("color__name").values_list("color__name", flat=True).distinct())
        rows = [{"color": c, "quantities": [quantities.get((c, s), 0) for s in sizes]} for c in colors]
        return Response({"product": product.reference, "sizes": sizes, "rows": rows})


class AdjustmentView(APIView):
    permission_classes = (StockReaders,)

    @extend_schema(request=AdjustmentSerializer, responses={201: OpenApiTypes.OBJECT})
    def post(self, request: Request) -> Response:
        data = AdjustmentSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        location = values["location"]
        if location.pk not in location_ids_for(_user(request)):
            raise ValidationError({"location": ["Local fora do seu acesso."]})
        entry = services.adjust_stock(
            user=_user(request),
            location=location,
            lines=[(line["variant"], line["quantity_delta"]) for line in values["lines"]],
            reason=values["reason"],
            note=values["note"],
            approval_id=values.get("approval"),
        )
        movements = entry.movements.filter(location=location).select_related("entry__created_by", "variant", "location")
        context = cost_context({}, request)
        return Response(
            {"entry": entry.pk, "movements": MovementSerializer(movements, many=True, context=context).data},
            status=status.HTTP_201_CREATED,
        )
