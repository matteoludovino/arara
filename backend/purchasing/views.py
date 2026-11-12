from typing import Any, cast

from django.db.models import QuerySet
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.capabilities import Capability, location_ids_for
from accounts.models import User
from accounts.permissions import requires, requires_any
from accounts.visibility import cost_context

from . import services
from .models import GoodsReceipt, PurchaseOrder, PurchaseReturn, Supplier
from .serializers import (
    OrderLinesSerializer,
    OrderSerializer,
    OrderWriteSerializer,
    ReasonSerializer,
    ReceiptSerializer,
    ReceiveSerializer,
    ReturnSerializer,
    ReturnWriteSerializer,
    SupplierSerializer,
)

Buyers = requires(Capability.PURCHASING_MANAGE)
BuyersOrReceivers = requires_any(Capability.PURCHASING_MANAGE, Capability.STOCK_RECEIVE)


def _user(request: Request) -> User:
    return cast(User, request.user)


class SupplierViewSet(viewsets.ModelViewSet[Supplier]):
    queryset = Supplier.objects.all()
    serializer_class = SupplierSerializer
    permission_classes = (Buyers,)
    http_method_names = ("get", "post", "patch", "head", "options")


class OrderViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[PurchaseOrder]):
    """Orders of the user's locations. Stockists see them too: they receive the goods."""

    queryset = PurchaseOrder.objects.none()  # the model, for the schema: get_queryset scopes it to the user
    serializer_class = OrderSerializer
    permission_classes = (BuyersOrReceivers,)
    filterset_fields = ("status", "supplier", "location")

    def get_permissions(self) -> list[Any]:
        if self.action in ("create", "lines", "send", "cancel", "close"):
            return [Buyers()]
        if self.action == "receive":
            return [requires(Capability.STOCK_RECEIVE)()]
        return [BuyersOrReceivers()]

    def get_queryset(self) -> QuerySet[PurchaseOrder]:
        return PurchaseOrder.objects.filter(location_id__in=location_ids_for(_user(self.request))).select_related(
            "supplier", "location", "created_by"
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return cost_context(super().get_serializer_context(), self.request)

    def _render(self, order: PurchaseOrder, code: int = status.HTTP_200_OK) -> Response:
        order = self.get_queryset().get(pk=order.pk)
        return Response(OrderSerializer(order, context=self.get_serializer_context()).data, status=code)

    def create(self, request: Request) -> Response:
        data = OrderWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        order = services.create_order(
            user=_user(request),
            supplier=values["supplier"],
            location=values["location"],
            lines=[services.OrderLineInput(**line) for line in values["lines"]],
            expected_on=values.get("expected_on"),
            notes=values["notes"],
        )
        return self._render(order, status.HTTP_201_CREATED)

    @action(detail=True, methods=["put"])
    def lines(self, request: Request, pk: str) -> Response:
        data = OrderLinesSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        lines = [services.OrderLineInput(**line) for line in data.validated_data["lines"]]
        return self._render(services.replace_lines(user=_user(request), order=self.get_object(), lines=lines))

    @action(detail=True, methods=["post"])
    def send(self, request: Request, pk: str) -> Response:
        return self._render(services.send_order(user=_user(request), order=self.get_object()))

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str) -> Response:
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        order = services.cancel_order(
            user=_user(request), order=self.get_object(), reason=data.validated_data["reason"]
        )
        return self._render(order)

    @action(detail=True, methods=["post"])
    def close(self, request: Request, pk: str) -> Response:
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        order = services.close_order(user=_user(request), order=self.get_object(), reason=data.validated_data["reason"])
        return self._render(order)

    @action(detail=True, methods=["post"])
    def receive(self, request: Request, pk: str) -> Response:
        data = ReceiveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        receipt = services.receive(
            user=_user(request),
            order=self.get_object(),
            invoice_number=data.validated_data["invoice_number"],
            lines=[
                services.ReceiptLineInput(line["order_line"], line["quantity"], line.get("unit_cost"))
                for line in data.validated_data["lines"]
            ],
        )
        context = cost_context({}, request)
        return Response(ReceiptSerializer(receipt, context=context).data, status=status.HTTP_201_CREATED)


class ReceiptViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[GoodsReceipt]):
    queryset = GoodsReceipt.objects.none()  # the model, for the schema: get_queryset scopes it to the user
    serializer_class = ReceiptSerializer
    permission_classes = (BuyersOrReceivers,)
    filterset_fields = ("order",)

    def get_permissions(self) -> list[Any]:
        return [Buyers()] if self.action == "cancel" else [BuyersOrReceivers()]

    def get_queryset(self) -> QuerySet[GoodsReceipt]:
        return GoodsReceipt.objects.filter(order__location_id__in=location_ids_for(_user(self.request))).select_related(
            "order", "received_by"
        )

    def get_serializer_context(self) -> dict[str, Any]:
        return cost_context(super().get_serializer_context(), self.request)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str) -> Response:
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        receipt = services.cancel_receipt(
            user=_user(request), receipt=self.get_object(), reason=data.validated_data["reason"]
        )
        return Response(ReceiptSerializer(receipt, context=self.get_serializer_context()).data)


class PurchaseReturnViewSet(mixins.ListModelMixin, viewsets.GenericViewSet[PurchaseReturn]):
    queryset = PurchaseReturn.objects.none()  # the model, for the schema: get_queryset scopes it to the user
    serializer_class = ReturnSerializer
    permission_classes = (Buyers,)

    def get_queryset(self) -> QuerySet[PurchaseReturn]:
        return PurchaseReturn.objects.filter(location_id__in=location_ids_for(_user(self.request))).select_related(
            "supplier", "created_by"
        )

    def create(self, request: Request) -> Response:
        data = ReturnWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        purchase_return = services.return_to_supplier(
            user=_user(request),
            supplier=values["supplier"],
            location=values["location"],
            reason=values["reason"],
            lines=[(line["variant"], line["quantity"]) for line in values["lines"]],
        )
        return Response(ReturnSerializer(purchase_return).data, status=status.HTTP_201_CREATED)


class SuggestionsView(APIView):
    """What to reorder, per store: below the minimum even counting what is already on order."""

    permission_classes = (Buyers,)

    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        rows = services.suggestions(location_ids_for(_user(request)))
        if not cost_context({}, request)["see_costs"]:
            for row in rows:
                row.pop("last_unit_cost", None)
        return Response(rows)
