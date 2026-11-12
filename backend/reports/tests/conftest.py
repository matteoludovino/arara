# The point-of-sale fixtures (a till, a cashier, a stocked shirt) and the integrity check after each test.
from pos.tests.conftest import _everything_agrees, cashier, register, session, shirt  # noqa: F401
