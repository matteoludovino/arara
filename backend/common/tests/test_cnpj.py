import pytest

from common.cnpj import is_valid_cnpj, normalize_cnpj


@pytest.mark.parametrize(
    "raw",
    [
        "11.222.333/0001-81",  # numeric
        "11222333000181",
        "12.ABC.345/01DE-35",  # the Receita Federal's alphanumeric example
        "12abc34501de35",
    ],
)
def test_valid(raw: str) -> None:
    assert is_valid_cnpj(normalize_cnpj(raw))


@pytest.mark.parametrize(
    "raw", ["11.222.333/0001-82", "12.ABC.345/01DE-36", "00000000000000", "1122233300018", "12ABC34501DE3X"]
)
def test_invalid(raw: str) -> None:
    assert not is_valid_cnpj(normalize_cnpj(raw))
