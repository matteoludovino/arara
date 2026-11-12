from typing import Any, ClassVar

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone

from locations.models import Location


def normalize_email(email: str) -> str:
    """The whole address in lowercase: `Ana@Loja.com` and `ana@loja.com` are one person."""
    return email.strip().lower()


class Role(models.TextChoices):
    OWNER = "owner", "Proprietário(a)"
    MANAGER = "manager", "Gerente"
    CASHIER = "cashier", "Caixa"
    STOCKIST = "stockist", "Estoquista"


class UserManager(BaseUserManager["User"]):
    def get_by_natural_key(self, username: str | None) -> User:
        # Authentication looks people up through this: normalize as on save.
        return self.get(email=normalize_email(username or ""))

    def create_user(self, email: str, password: str | None = None, **fields: Any) -> User:
        user = self.model(email=normalize_email(email), **fields)
        user.set_password(password)
        user.full_clean(exclude=["password"])
        user.save(using=self._db)
        return user

    def create_superuser(self, email: str, password: str | None = None, **fields: Any) -> User:
        fields.setdefault("role", Role.OWNER)
        return self.create_user(email, password, is_staff=True, is_superuser=True, **fields)


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)  # always stored lowercase; the constraint below covers case
    name = models.CharField(max_length=120)
    role = models.CharField(max_length=12, choices=Role.choices)
    # Stores and warehouses this person works at. Owners see every location regardless.
    locations = models.ManyToManyField(Location, blank=True, related_name="staff")
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)  # Django admin access only
    date_joined = models.DateTimeField(default=timezone.now)

    objects: ClassVar[UserManager] = UserManager()

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: ClassVar[list[str]] = ["name"]

    class Meta:
        ordering = ("name",)
        constraints = (models.UniqueConstraint(Lower("email"), name="user_email_unique_ci"),)

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>"

    def clean(self) -> None:
        super().clean()
        self.email = normalize_email(self.email)


class Approval(models.Model):
    """
    A manager's go-ahead for one action a capability alone doesn't allow (a discount above
    the cashier's limit, a return without a receipt, a quick stock adjustment).

    The manager types their password on the requester's screen; it is checked and never
    stored. What remains is who approved what, for whom, where and why. An approval is
    single-use and expires quickly, so it can't be replayed for a different sale.
    """

    class Action(models.TextChoices):
        DISCOUNT = "discount", "Desconto acima do limite"
        RETURN_WITHOUT_RECEIPT = "return_without_receipt", "Devolução sem cupom"
        STOCK_ADJUSTMENT = "stock_adjustment", "Ajuste de estoque"

    action = models.CharField(max_length=30, choices=Action.choices)
    approver = models.ForeignKey(User, on_delete=models.PROTECT, related_name="approvals_granted")
    requested_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="approvals_requested")
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=200)
    # For a discount: the highest percentage approved.
    limit = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    # What used it, e.g. "sale:1234".
    consumed_by_ref = models.CharField(max_length=60, blank=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.CheckConstraint(
                condition=~models.Q(approver=models.F("requested_by")),
                name="approval_needs_a_second_person",
            ),
            models.CheckConstraint(
                condition=models.Q(consumed_at__isnull=True, consumed_by_ref="")
                | models.Q(consumed_at__isnull=False) & ~models.Q(consumed_by_ref=""),
                name="approval_consumption_is_complete",
            ),
        )

    def __str__(self) -> str:
        return f"{self.get_action_display()} by {self.approver_id} for {self.requested_by_id}"
