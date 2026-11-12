from rest_framework import serializers

from .cnpj import is_valid_cnpj, normalize_cnpj


def cnpj_field() -> serializers.CharField:
    """Accepts the CNPJ with or without its mask (18 characters masked) and stores it normalized."""
    return serializers.CharField(max_length=18, required=False, allow_blank=True)


def clean_cnpj(value: str) -> str:
    if not value:
        return ""
    cnpj = normalize_cnpj(value)
    if not is_valid_cnpj(cnpj):
        raise serializers.ValidationError("CNPJ inválido.")
    return cnpj
