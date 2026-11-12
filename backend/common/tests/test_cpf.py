import pytest

from common.cpf import is_valid_cpf, normalize_cpf


@pytest.mark.parametrize("raw", ["529.982.247-25", "52998224725", "111.444.777-35"])
def test_valid(raw: str) -> None:
    assert is_valid_cpf(normalize_cpf(raw))


@pytest.mark.parametrize("raw", ["529.982.247-26", "111.111.111-11", "123", ""])
def test_invalid(raw: str) -> None:
    assert not is_valid_cpf(normalize_cpf(raw))
