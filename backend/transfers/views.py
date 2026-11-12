from typing import cast

from django.db.models import Prefetch, Q, QuerySet
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.capabilities import Capability, location_ids_for
from accounts.models import User
from accounts.permissions import requires
from accounts.serializers import LocationRefSerializer
from locations.models import Location

from . import services
from .models import Transfer, TransferLine
from .serializers import (
    CancelSerializer,
    LinesSerializer,
    ReceiveSerializer,
    TransferSerializer,
    TransferWriteSerializer,
)


def _user(request: Request) -> User:
    return cast(User, request.user)


class TransferViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[Transfer]):
    """Transfers leaving or arriving at the user's locations."""

    queryset = Transfer.objects.none()  # the model, for the schema: get_queryset scopes it to the user
    serializer_class = TransferSerializer
    permission_classes = (requires(Capability.STOCK_TRANSFER),)
    filterset_fields = ("status", "origin", "destination")

    def get_queryset(self) -> QuerySet[Transfer]:
        mine = location_ids_for(_user(self.request))
        return (
            Transfer.objects.filter(Q(origin_id__in=mine) | Q(destination_id__in=mine))
            .select_related("origin", "destination", "created_by", "dispatched_by", "received_by")
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=TransferLine.objects.select_related("variant__product", "variant__size", "variant__color"),
                )
            )
        )

    @extend_schema(responses=LocationRefSerializer(many=True))
    @action(detail=False, methods=["get"], pagination_class=None)
    def destinations(self, request: Request) -> Response:
        """Where goods can go: every active store and warehouse, not only the user's own."""
        places = Location.objects.filter(kind__in=Location.PHYSICAL_KINDS, is_active=True)
        return Response(LocationRefSerializer(places, many=True).data)

    def _render(self, transfer: Transfer, code: int = status.HTTP_200_OK) -> Response:
        return Response(TransferSerializer(self.get_queryset().get(pk=transfer.pk)).data, status=code)

    def create(self, request: Request) -> Response:
        data = TransferWriteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        transfer = services.create(
            user=_user(request),
            origin=values["origin"],
            destination=values["destination"],
            notes=values["notes"],
            lines=[(line["variant"], line["quantity"]) for line in values["lines"]],
        )
        return self._render(transfer, status.HTTP_201_CREATED)

    @action(detail=True, methods=["put"])
    def lines(self, request: Request, pk: str) -> Response:
        data = LinesSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        lines = [(line["variant"], line["quantity"]) for line in data.validated_data["lines"]]
        return self._render(services.replace_lines(user=_user(request), transfer=self.get_object(), lines=lines))

    # Not named `dispatch`: that is the view's own request router.
    @action(detail=True, methods=["post"], url_path="dispatch")
    def ship(self, request: Request, pk: str) -> Response:
        return self._render(services.dispatch(user=_user(request), transfer=self.get_object()))

    @action(detail=True, methods=["post"])
    def receive(self, request: Request, pk: str) -> Response:
        data = ReceiveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        received = {line["line"]: line["quantity"] for line in data.validated_data["lines"]}
        transfer = services.receive(
            user=_user(request),
            transfer=self.get_object(),
            received=received,
            missing_reason=data.validated_data["missing_reason"],
        )
        return self._render(transfer)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str) -> Response:
        data = CancelSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        transfer = services.cancel(
            user=_user(request), transfer=self.get_object(), reason=data.validated_data["reason"]
        )
        return self._render(transfer)
