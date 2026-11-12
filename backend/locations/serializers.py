from rest_framework import serializers

from .models import Location


class LocationSerializer(serializers.ModelSerializer[Location]):
    # Only physical locations are created through the API; transit and loss come from a migration.
    kind = serializers.ChoiceField(choices=[(k.value, k.label) for k in Location.PHYSICAL_KINDS])

    class Meta:
        model = Location
        fields = ("id", "code", "name", "kind", "is_active", "cnpj", "state_registration")

    def validate_code(self, value: str) -> str:
        code = value.strip().upper()
        taken = Location.objects.filter(code__iexact=code)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("Já existe um local com este código.")
        return code
