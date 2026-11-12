"""
Point of sale. A sale reaches the server complete (the cart lives on the till's screen),
priced by the server, numbered without gaps per store, and idempotent on the till's request
id. Cancelling reverses a whole sale in the same open session; a return is a separate,
possibly partial document, at any store, refunded in cash or in store credit.
"""

from decimal import Decimal

from django.conf import settings
from django.db import models

from catalog.models import ProductVariant
from locations.models import Location
from stock.models import StockEntry

ZERO = Decimal("0.00")


class Customer(models.Model):
    name = models.CharField(max_length=120)
    cpf = models.CharField(max_length=11, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("name",)
        constraints = (
            models.UniqueConstraint(fields=("cpf",), condition=~models.Q(cpf=""), name="customer_cpf_unique"),
            models.CheckConstraint(
                condition=models.Q(cpf="") | models.Q(cpf__regex=r"^\d{11}$"), name="customer_cpf_format"
            ),
        )

    def __str__(self) -> str:
        return self.name


class CashRegister(models.Model):
    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="registers")
    name = models.CharField(max_length=40)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ("location", "name")
        constraints = (models.UniqueConstraint(fields=("location", "name"), name="register_name_unique_in_store"),)

    def __str__(self) -> str:
        return f"{self.location_id}/{self.name}"


class CashSession(models.Model):
    """A cashier's shift at one register: opened with a float, closed by counting the drawer."""

    register = models.ForeignKey(CashRegister, on_delete=models.PROTECT, related_name="sessions")
    opened_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    opened_at = models.DateTimeField(auto_now_add=True)
    opening_float = models.DecimalField(max_digits=10, decimal_places=2)
    closed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    closed_at = models.DateTimeField(null=True, blank=True)
    expected_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    counted_cash = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    closing_note = models.CharField(max_length=200, blank=True)

    class Meta:
        ordering = ("-opened_at",)
        constraints = (
            models.UniqueConstraint(
                fields=("register",), condition=models.Q(closed_at__isnull=True), name="one_open_session_per_register"
            ),
            models.UniqueConstraint(
                fields=("opened_by",), condition=models.Q(closed_at__isnull=True), name="one_open_session_per_cashier"
            ),
            models.CheckConstraint(condition=models.Q(opening_float__gte=0), name="session_float_not_negative"),
            models.CheckConstraint(
                condition=models.Q(closed_at__isnull=True, expected_cash__isnull=True, counted_cash__isnull=True)
                | models.Q(closed_at__isnull=False, expected_cash__isnull=False, counted_cash__isnull=False),
                name="session_closing_is_complete",
            ),
        )

    def __str__(self) -> str:
        return f"session {self.pk} at {self.register_id}"

    @property
    def is_open(self) -> bool:
        return self.closed_at is None


class CashMovement(models.Model):
    """Cash in or out of the drawer that isn't a sale: withdrawals, top-ups, cash refunds."""

    class Kind(models.TextChoices):
        WITHDRAWAL = "withdrawal", "Sangria"
        SUPPLY = "supply", "Suprimento"
        REFUND = "refund", "Devolução em dinheiro"

    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=12, choices=Kind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)
        constraints = (models.CheckConstraint(condition=models.Q(amount__gt=0), name="cash_movement_positive"),)

    def __str__(self) -> str:
        return f"{self.kind} {self.amount}"


class DocumentSequence(models.Model):
    """Gapless numbering per store and document type: the row is locked and bumped in the sale's transaction."""

    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    doc_type = models.CharField(max_length=20)
    next_value = models.PositiveIntegerField(default=1)

    class Meta:
        constraints = (
            models.UniqueConstraint(fields=("location", "doc_type"), name="one_sequence_per_store_and_type"),
        )

    def __str__(self) -> str:
        return f"{self.location_id}/{self.doc_type}: {self.next_value}"


class Sale(models.Model):
    class Status(models.TextChoices):
        COMPLETED = "completed", "Concluída"
        CANCELLED = "cancelled", "Cancelada"

    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="sales")
    number = models.PositiveIntegerField()
    session = models.ForeignKey(CashSession, on_delete=models.PROTECT, related_name="sales")
    # The till's id for this sale: a retried request (flaky Wi-Fi) returns the same sale.
    client_request_id = models.UUIDField(unique=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.COMPLETED)
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # Who sold it on the floor (commission), not necessarily who rang it up.
    salesperson = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="sales")
    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount_total = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    approval = models.ForeignKey("accounts.Approval", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    stock_entry = models.OneToOneField(StockEntry, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cancel_reason = models.CharField(max_length=200, blank=True)
    cancel_entry = models.OneToOneField(StockEntry, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.UniqueConstraint(fields=("location", "number"), name="sale_number_unique_in_store"),
            models.CheckConstraint(condition=models.Q(discount_total__gte=0), name="sale_discount_not_negative"),
            models.CheckConstraint(
                condition=models.Q(total=models.F("subtotal") - models.F("discount_total")), name="sale_total_adds_up"
            ),
            models.CheckConstraint(condition=models.Q(total__gte=0), name="sale_total_not_negative"),
            models.CheckConstraint(
                condition=models.Q(status="completed", cancelled_at__isnull=True, cancel_entry__isnull=True)
                | models.Q(status="cancelled", cancelled_at__isnull=False, cancel_entry__isnull=False),
                name="sale_cancellation_is_complete",
            ),
        )

    def __str__(self) -> str:
        return f"{self.location_id}#{self.number}"


class SaleItem(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="items")
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="+")
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)  # list price at the time of sale
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)  # line + its share of the sale's
    net_amount = models.DecimalField(max_digits=12, decimal_places=2)  # what the customer paid for this line
    # The exact value that left inventory (CMV), frozen: margins don't move when costs do.
    cost_value = models.DecimalField(max_digits=16, decimal_places=4)
    quantity_returned = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ("id",)
        constraints = (
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="sale_item_quantity_positive"),
            models.CheckConstraint(condition=models.Q(discount__gte=0), name="sale_item_discount_not_negative"),
            models.CheckConstraint(
                condition=models.Q(net_amount=models.F("unit_price") * models.F("quantity") - models.F("discount")),
                name="sale_item_net_adds_up",
            ),
            models.CheckConstraint(condition=models.Q(net_amount__gte=0), name="sale_item_net_not_negative"),
            models.CheckConstraint(
                condition=models.Q(quantity_returned__lte=models.F("quantity")), name="sale_item_not_over_returned"
            ),
        )

    def __str__(self) -> str:
        return f"{self.sale_id}: {self.variant_id} × {self.quantity}"


class StoreCredit(models.Model):
    """A vale-troca: money the store owes the customer, spendable at any store."""

    code = models.CharField(max_length=12, unique=True)
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="credits")
    issued_at_location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    expires_on = models.DateField(null=True, blank=True)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=ZERO)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = (models.CheckConstraint(condition=models.Q(balance__gte=0), name="store_credit_not_negative"),)

    def __str__(self) -> str:
        return self.code


class StoreCreditEntry(models.Model):
    """The credit's ledger: its balance is the sum of these."""

    class Kind(models.TextChoices):
        ISSUE = "issue", "Emissão"
        REDEEM = "redeem", "Uso"
        REVERSE = "reverse", "Estorno"

    credit = models.ForeignKey(StoreCredit, on_delete=models.PROTECT, related_name="entries")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    amount = models.DecimalField(max_digits=10, decimal_places=2)  # signed: + issues and reversals, - redemptions
    source_ref = models.CharField(max_length=40)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("id",)
        constraints = (
            models.CheckConstraint(
                condition=models.Q(kind="redeem", amount__lt=0) | models.Q(kind__in=("issue", "reverse"), amount__gt=0),
                name="store_credit_entry_sign",
            ),
        )

    def __str__(self) -> str:
        return f"{self.credit_id} {self.kind} {self.amount}"


class Payment(models.Model):
    class Method(models.TextChoices):
        CASH = "cash", "Dinheiro"
        DEBIT = "debit", "Débito"
        CREDIT = "credit", "Crédito"
        PIX = "pix", "Pix"
        STORE_CREDIT = "store_credit", "Vale-troca"

    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="payments")
    method = models.CharField(max_length=12, choices=Method.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2)  # applied to the sale
    tendered = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # cash handed over
    change = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    installments = models.PositiveSmallIntegerField(null=True, blank=True)
    card_brand = models.CharField(max_length=20, blank=True)
    nsu = models.CharField(max_length=20, blank=True)  # the acquirer's transaction id, for reconciliation later
    store_credit = models.ForeignKey(StoreCredit, null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ("id",)
        constraints = (
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="payment_amount_positive"),
            models.CheckConstraint(
                condition=~models.Q(method="cash")
                | models.Q(tendered__gte=models.F("amount"), change=models.F("tendered") - models.F("amount")),
                name="payment_cash_change_adds_up",
            ),
            models.CheckConstraint(
                condition=models.Q(method="credit", installments__gte=1, installments__lte=12)
                | ~models.Q(method="credit") & models.Q(installments__isnull=True),
                name="payment_installments_only_on_credit",
            ),
            models.CheckConstraint(
                condition=models.Q(method="store_credit", store_credit__isnull=False)
                | ~models.Q(method="store_credit") & models.Q(store_credit__isnull=True),
                name="payment_store_credit_reference",
            ),
        )

    def __str__(self) -> str:
        return f"{self.method} {self.amount}"


class SaleReturn(models.Model):
    """
    Pieces brought back, at any store. With the receipt, each line points at the sale item it
    returns (never more than was sold); without it, a manager's approval is required.
    """

    class Refund(models.TextChoices):
        CASH = "cash", "Dinheiro"
        STORE_CREDIT = "store_credit", "Vale-troca"

    location = models.ForeignKey(Location, on_delete=models.PROTECT, related_name="+")
    original_sale = models.ForeignKey(Sale, null=True, blank=True, on_delete=models.PROTECT, related_name="returns")
    customer = models.ForeignKey(Customer, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    refund_method = models.CharField(max_length=12, choices=Refund.choices)
    total = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=200)
    session = models.ForeignKey(CashSession, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    store_credit = models.ForeignKey(StoreCredit, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    approval = models.ForeignKey("accounts.Approval", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    stock_entry = models.OneToOneField(StockEntry, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
        constraints = (
            models.CheckConstraint(condition=models.Q(total__gte=0), name="return_total_not_negative"),
            models.CheckConstraint(
                condition=models.Q(refund_method="cash", session__isnull=False)
                | models.Q(refund_method="store_credit", store_credit__isnull=False),
                name="return_refund_has_its_source",
            ),
            models.CheckConstraint(
                condition=models.Q(original_sale__isnull=False) | models.Q(approval__isnull=False),
                name="return_without_receipt_needs_approval",
            ),
        )

    def __str__(self) -> str:
        return f"return {self.pk}"


class ReturnLine(models.Model):
    sale_return = models.ForeignKey(SaleReturn, on_delete=models.PROTECT, related_name="lines")
    sale_item = models.ForeignKey(
        SaleItem, null=True, blank=True, on_delete=models.PROTECT, related_name="return_lines"
    )
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name="+")
    quantity = models.PositiveIntegerField()
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    cost_value = models.DecimalField(max_digits=16, decimal_places=4)  # back into inventory at the sale's cost

    class Meta:
        constraints = (
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="return_line_quantity_positive"),
        )

    def __str__(self) -> str:
        return f"{self.sale_return_id}: {self.variant_id} × {self.quantity}"
