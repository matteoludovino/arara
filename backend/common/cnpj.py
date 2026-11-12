"""
CNPJ, including the alphanumeric format issued since July 2026: twelve characters in [0-9A-Z]
and two numeric check digits. Each character is worth ord(c) - 48, which for digits is the
digit itself, so old all-numeric CNPJs keep validating as before.
"""

import re

_SHAPE = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
_FIRST_WEIGHTS = (5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
_SECOND_WEIGHTS = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)


def normalize_cnpj(raw: str) -> str:
    """Strips the mask ("12.ABC.345/01DE-35" → "12ABC34501DE35") and uppercases."""
    return re.sub(r"[.\-/\s]", "", raw).upper()


def _digit(values: list[int], weights: tuple[int, ...]) -> int:
    remainder = sum(v * w for v, w in zip(values, weights, strict=True)) % 11
    return 0 if remainder < 2 else 11 - remainder


def is_valid_cnpj(cnpj: str) -> bool:
    if not _SHAPE.match(cnpj) or len(set(cnpj)) == 1:
        return False
    values = [ord(c) - 48 for c in cnpj[:12]]
    first = _digit(values, _FIRST_WEIGHTS)
    second = _digit([*values, first], _SECOND_WEIGHTS)
    return cnpj[12:] == f"{first}{second}"
