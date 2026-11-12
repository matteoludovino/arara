from typing import Any

from rest_framework.permissions import BasePermission
from rest_framework.request import Request

from .capabilities import Capability, can


def requires(*capabilities: Capability) -> type[BasePermission]:
    """DRF permission: the user must hold every listed capability (location scope is checked in services)."""

    class RequiresCapability(BasePermission):
        message = "Você não tem permissão para esta ação."

        def has_permission(self, request: Request, view: Any) -> bool:
            return all(can(request.user, capability) for capability in capabilities)

    RequiresCapability.__name__ = f"Requires({', '.join(capabilities)})"
    return RequiresCapability


def read_or(*capabilities: Capability) -> type[BasePermission]:
    """Anyone signed in reads; writing needs every listed capability."""

    class ReadOrCapability(BasePermission):
        message = "Você não tem permissão para esta ação."

        def has_permission(self, request: Request, view: Any) -> bool:
            if not (request.user and request.user.is_authenticated):
                return False
            if request.method in ("GET", "HEAD", "OPTIONS"):
                return True
            return all(can(request.user, capability) for capability in capabilities)

    ReadOrCapability.__name__ = f"ReadOr({', '.join(capabilities)})"
    return ReadOrCapability


def requires_any(*capabilities: Capability) -> type[BasePermission]:
    """DRF permission: the user must hold at least one of the listed capabilities."""

    class RequiresAnyCapability(BasePermission):
        message = "Você não tem permissão para esta ação."

        def has_permission(self, request: Request, view: Any) -> bool:
            return any(can(request.user, capability) for capability in capabilities)

    RequiresAnyCapability.__name__ = f"RequiresAny({', '.join(capabilities)})"
    return RequiresAnyCapability
