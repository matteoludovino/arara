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
