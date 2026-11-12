"""
GTIN (EAN/UPC) check digits. Suppliers' codes come as GTIN-8, -12, -13 or -14; the store's
own codes are EAN-13 in the 200–299 prefix range, which GS1 reserves for restricted
(in-store) circulation, so they can never collide with a real product's code.
"""

GTIN_LENGTHS = (8, 12, 13, 14)
INTERNAL_PREFIX = "200"


def check_digit(body: str) -> str:
    """Mod-10 check digit: weights 3 and 1 alternate from the rightmost digit of the body."""
    if not body.isdigit():
        raise ValueError("GTIN body must be digits")
    total = sum(int(digit) * (3 if i % 2 == 0 else 1) for i, digit in enumerate(reversed(body)))
    return str((10 - total % 10) % 10)


def is_valid_gtin(code: str) -> bool:
    return code.isdigit() and len(code) in GTIN_LENGTHS and check_digit(code[:-1]) == code[-1]


def is_internal(code: str) -> bool:
    return len(code) == 13 and code[0] == "2"


def internal_ean13(serial: int) -> str:
    """An in-store EAN-13: prefix 200, a 9-digit serial and the check digit."""
    if not 0 < serial < 10**9:
        raise ValueError("serial out of range")
    body = f"{INTERNAL_PREFIX}{serial:09d}"
    return body + check_digit(body)
