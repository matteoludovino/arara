"""
What each role may do, in one place. Views and services ask for a capability, never for a
role, so the whole policy is this table (and it is tested cell by cell).
"""

from enum import StrEnum
from typing import TYPE_CHECKING

from .models import Role

if TYPE_CHECKING:
    from django.contrib.auth.models import AnonymousUser

    from locations.models import Location

    from .models import User


class Capability(StrEnum):
    USERS_MANAGE = "users.manage"
    LOCATIONS_MANAGE = "locations.manage"
    CATALOG_MANAGE = "catalog.manage"
    PRICES_CHANGE = "prices.change"
    COSTS_VIEW = "costs.view"
    STOCK_VIEW = "stock.view"
    STOCK_ADJUST = "stock.adjust"
    PURCHASING_MANAGE = "purchasing.manage"
    STOCK_RECEIVE = "stock.receive"
    STOCK_TRANSFER = "stock.transfer"
    STOCK_COUNT = "stock.count"
    STOCK_COUNT_APPLY = "stock.count_apply"
    POS_SELL = "pos.sell"
    POS_CASH = "pos.cash"
    APPROVALS_GRANT = "approvals.grant"
    REPORTS_SALES = "reports.sales"
    REPORTS_MARGIN = "reports.margin"
    AUDIT_VIEW = "audit.view"


C = Capability

ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    # Everything, in every location: prices and costs are company-wide decisions.
    Role.OWNER: frozenset(Capability),
    # Runs their store(s): stock, purchasing, the till, approvals and margin reports.
    Role.MANAGER: frozenset(
        {
            C.CATALOG_MANAGE,
            C.COSTS_VIEW,
            C.STOCK_VIEW,
            C.STOCK_ADJUST,
            C.PURCHASING_MANAGE,
            C.STOCK_RECEIVE,
            C.STOCK_TRANSFER,
            C.STOCK_COUNT,
            C.STOCK_COUNT_APPLY,
            C.POS_SELL,
            C.POS_CASH,
            C.APPROVALS_GRANT,
            C.REPORTS_SALES,
            C.REPORTS_MARGIN,
            C.AUDIT_VIEW,
        }
    ),
    # Sells and runs their own till; never sees cost or margin.
    Role.CASHIER: frozenset({C.STOCK_VIEW, C.POS_SELL, C.POS_CASH}),
    # Moves and counts goods; doesn't sell, doesn't see cost, doesn't apply a count.
    Role.STOCKIST: frozenset({C.STOCK_VIEW, C.STOCK_RECEIVE, C.STOCK_TRANSFER, C.STOCK_COUNT}),
}


def capabilities_of(user: User | AnonymousUser) -> frozenset[Capability]:
    if not user.is_authenticated or not user.is_active:
        return frozenset()
    return ROLE_CAPABILITIES.get(user.role, frozenset())


def works_at(user: User, location: Location) -> bool:
    """Owners work everywhere; everyone else, at the locations they are assigned to."""
    if user.role == Role.OWNER:
        return True
    return user.locations.filter(pk=location.pk).exists()


def can(user: User | AnonymousUser, capability: Capability, location: Location | None = None) -> bool:
    if capability not in capabilities_of(user):
        return False
    return location is None or works_at(user, location)  # type: ignore[arg-type]
