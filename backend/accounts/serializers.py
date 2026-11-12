from typing import Any

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from rest_framework import serializers

from locations.models import Location

from .capabilities import capabilities_of
from .models import Approval, Role, User, normalize_email


class LocationRefSerializer(serializers.ModelSerializer[Location]):
    class Meta:
        model = Location
        fields = ("id", "code", "name", "kind")


class MeSerializer(serializers.ModelSerializer[User]):
    role_label = serializers.CharField(source="get_role_display")
    capabilities = serializers.SerializerMethodField()
    locations = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ("id", "email", "name", "role", "role_label", "capabilities", "locations")

    def get_capabilities(self, user: User) -> list[str]:
        return sorted(capabilities_of(user))

    def get_locations(self, user: User) -> list[dict[str, Any]]:
        if user.role == Role.OWNER:
            locations = Location.objects.filter(kind__in=Location.PHYSICAL_KINDS, is_active=True)
        else:
            locations = user.locations.filter(is_active=True)
        return LocationRefSerializer(locations, many=True).data  # type: ignore[return-value]


class LoginSerializer(serializers.Serializer[None]):
    email = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)


class UserSerializer(serializers.ModelSerializer[User]):
    password = serializers.CharField(write_only=True, required=False, trim_whitespace=False)
    locations = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Location.objects.filter(kind__in=Location.PHYSICAL_KINDS), required=False
    )
    role_label = serializers.CharField(source="get_role_display", read_only=True)

    class Meta:
        model = User
        fields = ("id", "email", "name", "role", "role_label", "locations", "is_active", "password", "date_joined")
        read_only_fields = ("date_joined",)

    def validate_email(self, value: str) -> str:
        email = normalize_email(value)
        taken = User.objects.filter(email__iexact=email)
        if self.instance is not None:
            taken = taken.exclude(pk=self.instance.pk)
        if taken.exists():
            raise serializers.ValidationError("Já existe uma pessoa com este e-mail.")
        return email

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if self.instance is None and not attrs.get("password"):
            raise serializers.ValidationError({"password": "Defina uma senha inicial."})
        if attrs.get("password"):
            probe = User(email=attrs.get("email", ""), name=attrs.get("name", ""))
            try:
                validate_password(attrs["password"], probe)
            except DjangoValidationError as error:
                # Under the password field, so the form shows it next to the input.
                raise serializers.ValidationError({"password": list(error.messages)}) from error
        if self.instance is not None and self._removes_last_owner(attrs):
            raise serializers.ValidationError("A empresa precisa de pelo menos um proprietário ativo.")
        return attrs

    def _removes_last_owner(self, attrs: dict[str, Any]) -> bool:
        user = self.instance
        assert user is not None
        if user.role != Role.OWNER or not user.is_active:
            return False
        loses_owner = attrs.get("role", Role.OWNER) != Role.OWNER or attrs.get("is_active") is False
        others = User.objects.filter(role=Role.OWNER, is_active=True).exclude(pk=user.pk)
        return loses_owner and not others.exists()

    @transaction.atomic
    def create(self, validated: dict[str, Any]) -> User:
        locations = validated.pop("locations", [])
        user = User.objects.create_user(**validated)
        user.locations.set(locations)
        return user

    @transaction.atomic
    def update(self, user: User, validated: dict[str, Any]) -> User:
        locations = validated.pop("locations", None)
        password = validated.pop("password", None)
        for field, value in validated.items():
            setattr(user, field, value)
        if password:
            user.set_password(password)
        user.save()
        if locations is not None:
            user.locations.set(locations)
        return user


class ApprovalRequestSerializer(serializers.Serializer[None]):
    action = serializers.ChoiceField(choices=Approval.Action.choices)
    location = serializers.PrimaryKeyRelatedField(queryset=Location.objects.filter(kind__in=Location.PHYSICAL_KINDS))
    approver_email = serializers.CharField()
    approver_password = serializers.CharField(trim_whitespace=False)
    reason = serializers.CharField(max_length=200)
    limit = serializers.DecimalField(max_digits=5, decimal_places=2, required=False, min_value=0, max_value=100)


class ApprovalSerializer(serializers.ModelSerializer[Approval]):
    approver_name = serializers.CharField(source="approver.name")

    class Meta:
        model = Approval
        fields = ("id", "action", "location", "approver_name", "reason", "limit", "expires_at")
