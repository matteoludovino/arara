import pytest

from catalog.gtin import check_digit, internal_ean13, is_internal, is_valid_gtin


@pytest.mark.parametrize(
    "code",
    [
        "4006381333931",  # EAN-13
        "7891000315507",  # EAN-13, Brazilian prefix
        "73513537",  # EAN-8
        "036000291452",  # UPC-A (GTIN-12)
        "10012345678902",  # GTIN-14
    ],
)
def test_known_valid_codes(code: str) -> None:
    assert is_valid_gtin(code)


@pytest.mark.parametrize("code", ["4006381333932", "400638133393", "40063813339A1", "123", ""])
def test_invalid_codes(code: str) -> None:
    assert not is_valid_gtin(code)


def test_internal_codes_are_valid_restricted_ean13() -> None:
    code = internal_ean13(42)
    assert code == "200000000042" + check_digit("200000000042")
    assert is_valid_gtin(code)
    assert is_internal(code)
    assert not is_internal("7891000315507")


def test_internal_serial_range() -> None:
    with pytest.raises(ValueError, match="out of range"):
        internal_ean13(0)
    with pytest.raises(ValueError, match="out of range"):
        internal_ean13(10**9)
