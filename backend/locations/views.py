from typing import Any

from django.db.models import QuerySet
from rest_framework import viewsets
from rest_framework.permissions import IsAuthenticated
from rest_framework.request import Request

from accounts.capabilities import Capability, can
from accounts.models import Role, User

from .models import Location
from .serializers import LocationSerializer


class CanManageLocationsOrReadOnly(IsAuthenticated):
    message = "Você não tem permissão para esta ação."

    def has_permission(self, request: Request, view: Any) -> bool:
        if not super().has_permission(request, view):
            return False
        return request.method in ("GET", "HEAD", "OPTIONS") or can(request.user, Capability.LOCATIONS_MANAGE)


class LocationViewSet(viewsets.ModelViewSet[Location]):
    """Physical locations the user works at (all of them for an owner)."""

    serializer_class = LocationSerializer
    permission_classes = (CanManageLocationsOrReadOnly,)
    http_method_names = ("get", "post", "patch", "head", "options")

    def get_queryset(self) -> QuerySet[Location]:
        user: User = self.request.user  # type: ignore[assignment]
        physical = Location.objects.filter(kind__in=Location.PHYSICAL_KINDS)
        return physical if user.role == Role.OWNER else physical.filter(staff=user)
