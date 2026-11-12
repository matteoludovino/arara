"""Cost and margin are for those holding costs.view: serializers drop those fields for everyone else."""

from collections.abc import Mapping
from typing import Any, ClassVar

from rest_framework.request import Request

from .capabilities import Capability, can

COST_FIELDS = ("average_cost", "stock_value", "value_delta", "unit_cost", "total_cost", "last_unit_cost")


def cost_context(context: Mapping[str, Any], request: Request) -> dict[str, Any]:
    return {**context, "see_costs": can(request.user, Capability.COSTS_VIEW)}


class HidesCosts:
    """Serializer mixin: output without the cost fields unless the context allows them."""

    cost_fields: ClassVar[tuple[str, ...]] = COST_FIELDS

    def to_representation(self, instance: Any) -> Any:
        data = super().to_representation(instance)  # type: ignore[misc]
        if not self.context.get("see_costs"):  # type: ignore[attr-defined]
            for field in self.cost_fields:
                data.pop(field, None)
        return data
