from typing import Any

from rest_framework import serializers

from common.serializers import clean_cnpj, cnpj_field
from demo.shared import is_shared_location

from .models import Location


class LocationSerializer(serializers.ModelSerializer[Location]):
    # Only physical locations are created through the API; transit and loss come from a migration.
    kind = serializers.ChoiceField(choices=[(k.value, k.label) for k in Location.PHYSICAL_KINDS])
    cnpj = cnpj_field()

    class Meta:
        model = Location
        fields = ("id", "code", "name", "kind", "is_active", "cnpj", "state_registration")

    def validate_cnpj(self, value: str) -> str:
        return clean_cnpj(value)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        location = self.instance
        closes = location is not None and (
            attrs.get("is_active") is False or attrs.get("code", location.code) != location.code
        )
        if closes and location is not None and is_shared_location(location.code):
            raise serializers.ValidationError(
                "Os locais da demonstração são compartilhados: não podem ser desativados."
            )
        return attrs

    def validate_code(self, value: str) -> str:
        code = value.strip().upper()
        taken = Location.objects.filter(code__iexact=code)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("Já existe um local com este código.")
        return code
