from dataclasses import asdict
from typing import cast

from django.db.models import QuerySet
from django.shortcuts import get_object_or_404
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.request import Request
from rest_framework.response import Response

from accounts.capabilities import Capability, can, location_ids_for
from accounts.models import User
from accounts.permissions import requires

from . import services
from .models import InventoryCount
from .serializers import (
    ApplySerializer,
    CountSerializer,
    EntrySerializer,
    NewEntrySerializer,
    OpenCountSerializer,
    RecountSerializer,
)


def _user(request: Request) -> User:
    return cast(User, request.user)


class CountViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet[InventoryCount]):
    serializer_class = CountSerializer
    permission_classes = (requires(Capability.STOCK_COUNT),)
    filterset_fields = ("status", "location")

    def get_queryset(self) -> QuerySet[InventoryCount]:
        return InventoryCount.objects.filter(location_id__in=location_ids_for(_user(self.request))).select_related(
            "location", "opened_by"
        )

    def _render(self, count: InventoryCount, code: int = status.HTTP_200_OK) -> Response:
        return Response(CountSerializer(self.get_queryset().get(pk=count.pk)).data, status=code)

    def create(self, request: Request) -> Response:
        data = OpenCountSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        count = services.open_count(
            user=_user(request),
            location=values["location"],
            category_ids=[c.pk for c in values.get("categories", [])],
            product_ids=[p.pk for p in values.get("products", [])],
            tolerance=values["tolerance"],
            note=values["note"],
        )
        return self._render(count, status.HTTP_201_CREATED)

    @action(detail=True, methods=["get", "post"])
    def entries(self, request: Request, pk: str) -> Response:
        count = self.get_object()
        if request.method == "GET":
            entries = count.entries.select_related("variant", "counted_by").order_by("-id")
            return Response(EntrySerializer(entries, many=True).data)
        data = NewEntrySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        entry = services.add_entry(user=_user(request), count=count, **data.validated_data)
        return Response(EntrySerializer(entry).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["delete"], url_path=r"entries/(?P<entry_id>\d+)")
    def delete_entry(self, request: Request, pk: str, entry_id: str) -> Response:
        entry = get_object_or_404(self.get_object().entries, pk=entry_id)
        services.delete_entry(user=_user(request), entry=entry)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"])
    def finish(self, request: Request, pk: str) -> Response:
        return self._render(services.finish(user=_user(request), count=self.get_object()))

    @action(detail=True, methods=["get"])
    def review(self, request: Request, pk: str) -> Response:
        count = self.get_object()
        if not can(request.user, Capability.STOCK_COUNT_APPLY, count.location):
            raise PermissionDenied("A revisão mostra o esperado: é do gerente.")
        return Response([asdict(row) for row in services.review(count)])

    @action(detail=True, methods=["post"])
    def recount(self, request: Request, pk: str) -> Response:
        data = RecountSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        count = services.recount(
            user=_user(request), count=self.get_object(), variant_ids=data.validated_data["variants"]
        )
        return self._render(count)

    @action(detail=True, methods=["post"])
    def apply(self, request: Request, pk: str) -> Response:
        data = ApplySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        count = services.apply(user=_user(request), count=self.get_object(), uncounted=data.validated_data["uncounted"])
        return self._render(count)

    @action(detail=True, methods=["post"])
    def cancel(self, request: Request, pk: str) -> Response:
        return self._render(services.cancel(user=_user(request), count=self.get_object()))
