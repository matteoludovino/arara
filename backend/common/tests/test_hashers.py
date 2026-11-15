from typing import Any

from django.contrib.auth.hashers import check_password, make_password

DEMO = ["common.hashers.DemoPBKDF2PasswordHasher", "django.contrib.auth.hashers.PBKDF2PasswordHasher"]
DEFAULT = ["django.contrib.auth.hashers.PBKDF2PasswordHasher"]


def test_the_demo_hashes_cheaper_and_still_reads_full_hashes(settings: Any) -> None:
    settings.PASSWORD_HASHERS = DEFAULT
    full = make_password("arara-demo-2026")
    settings.PASSWORD_HASHERS = DEMO
    cheap = make_password("arara-demo-2026")
    assert int(cheap.split("$")[1]) == 100_000 < int(full.split("$")[1])
    assert check_password("arara-demo-2026", full)
    assert check_password("arara-demo-2026", cheap)
    assert not check_password("wrong-password", cheap)
