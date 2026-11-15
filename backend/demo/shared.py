"""
What visitors of the public demo share. Deactivating Rafael, demoting Bia or closing the Centro
store would lock everyone else out until the nightly reset, so in DEMO_MODE these stay as seeded.
"""

from django.conf import settings

ACCOUNTS = frozenset(
    {
        "marta@arara.test",
        "rafael@arara.test",
        "lia@arara.test",
        "bia@arara.test",
        "davi@arara.test",
        "caio@arara.test",
        "joao@arara.test",
    }
)
LOCATIONS = frozenset({"CENTRO", "SHOP", "DEP"})


def is_shared_account(email: str) -> bool:
    return bool(settings.DEMO_MODE) and email in ACCOUNTS


def is_shared_location(code: str) -> bool:
    return bool(settings.DEMO_MODE) and code in LOCATIONS
