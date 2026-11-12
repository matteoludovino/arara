from collections.abc import Callable

import pytest

from accounts.capabilities import Capability as C
from accounts.capabilities import can, capabilities_of
from accounts.models import Role, User
from locations.models import Location

pytestmark = pytest.mark.django_db

# The policy, restated here on purpose (not read from ROLE_CAPABILITIES): changing what a
# role may do must be a deliberate change in two places.
OW, MG, CA, ST = Role.OWNER, Role.MANAGER, Role.CASHIER, Role.STOCKIST
EXPECTED: dict[C, set[Role]] = {
    C.USERS_MANAGE: {OW},
    C.LOCATIONS_MANAGE: {OW},
    C.PRICES_CHANGE: {OW},
    C.CATALOG_MANAGE: {OW, MG},
    C.COSTS_VIEW: {OW, MG},
    C.STOCK_VIEW: {OW, MG, CA, ST},
    C.STOCK_ADJUST: {OW, MG},
    C.PURCHASING_MANAGE: {OW, MG},
    C.STOCK_RECEIVE: {OW, MG, ST},
    C.STOCK_TRANSFER: {OW, MG, ST},
    C.STOCK_COUNT: {OW, MG, ST},
    C.STOCK_COUNT_APPLY: {OW, MG},
    C.POS_SELL: {OW, MG, CA},
    C.POS_CASH: {OW, MG, CA},
    C.APPROVALS_GRANT: {OW, MG},
    C.REPORTS_SALES: {OW, MG},
    C.REPORTS_MARGIN: {OW, MG},
    C.AUDIT_VIEW: {OW, MG},
}


def test_every_capability_is_in_the_expected_table() -> None:
    assert set(EXPECTED) == set(C)


@pytest.mark.parametrize("role", list(Role))
@pytest.mark.parametrize("capability", list(C))
def test_policy_matrix(make_user: Callable[..., User], role: Role, capability: C) -> None:
    assert (capability in capabilities_of(make_user(role))) == (role in EXPECTED[capability])


def test_a_cashier_never_sees_cost_or_margin(make_user: Callable[..., User]) -> None:
    cashier = make_user(Role.CASHIER)
    assert not can(cashier, C.COSTS_VIEW)
    assert not can(cashier, C.REPORTS_MARGIN)


def test_location_scope(make_user: Callable[..., User], store: Location, other_store: Location) -> None:
    manager = make_user(Role.MANAGER, locations=[store])
    owner = make_user(Role.OWNER, locations=[])
    assert can(manager, C.STOCK_ADJUST, store)
    assert not can(manager, C.STOCK_ADJUST, other_store)
    assert can(owner, C.STOCK_ADJUST, other_store)


def test_an_inactive_user_can_do_nothing(make_user: Callable[..., User]) -> None:
    owner = make_user(Role.OWNER, is_active=False)
    assert capabilities_of(owner) == frozenset()
