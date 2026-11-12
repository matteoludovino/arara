from django.db import models
from django.db.models.functions import Lower


class Location(models.Model):
    """
    Anywhere stock can be. Stores and warehouses are physical; `transit` and `loss` are
    virtual locations, so a transfer or a write-off is just another pair of stock movements.
    """

    class Kind(models.TextChoices):
        STORE = "store", "Loja"
        WAREHOUSE = "warehouse", "Depósito"
        TRANSIT = "transit", "Em trânsito"
        LOSS = "loss", "Perdas"

    PHYSICAL_KINDS = (Kind.STORE, Kind.WAREHOUSE)
    # Where the company's inventory is (and is valued). Losses have left it.
    INVENTORY_KINDS = (Kind.STORE, Kind.WAREHOUSE, Kind.TRANSIT)

    code = models.CharField(max_length=12)
    name = models.CharField(max_length=80)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    is_active = models.BooleanField(default=True)
    # Fiscal identity of a store; empty until fiscal documents exist (not in scope yet).
    cnpj = models.CharField(max_length=14, blank=True)
    state_registration = models.CharField(max_length=20, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("kind", "name")
        constraints = (
            models.UniqueConstraint(Lower("code"), name="location_code_unique_ci"),
            # A single virtual location of each kind: stock in transit lives in one place.
            models.UniqueConstraint(
                fields=("kind",),
                condition=models.Q(kind__in=("transit", "loss")),
                name="one_location_per_virtual_kind",
            ),
        )

    def __str__(self) -> str:
        return f"{self.code} · {self.name}"

    @property
    def is_physical(self) -> bool:
        return self.kind in self.PHYSICAL_KINDS

    @property
    def holds_inventory(self) -> bool:
        return self.kind in self.INVENTORY_KINDS
