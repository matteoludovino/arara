"""
Integrity checks across apps. Each app registers the checks that prove its projections agree
with the stock ledger; `manage.py check_stock` and the tests run all of them.
"""

from collections.abc import Callable

Check = Callable[[], list[str]]
_checks: list[Check] = []


def register(check: Check) -> Check:
    if check not in _checks:
        _checks.append(check)
    return check


def all_problems() -> list[str]:
    return [problem for check in _checks for problem in check()]
