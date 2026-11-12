import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from accounts.models import User
from common.integrity import all_problems
from counts.models import InventoryCount
from demo.seed import PASSWORD, Seed
from pos.models import CashSession, Sale
from purchasing.models import PurchaseOrder, PurchaseOrderLine
from stock.models import StockEntry
from transfers.models import Transfer

pytestmark = pytest.mark.django_db


def test_a_short_story_is_consistent() -> None:
    Seed(days=10).run()
    assert all_problems() == []
    assert Sale.objects.count() > 50
    # Every till was closed; the demo leaves work in progress for today.
    assert not CashSession.objects.filter(closed_at__isnull=True).exists()
    assert PurchaseOrder.objects.filter(status=PurchaseOrder.Status.SENT).exists()
    assert Transfer.objects.filter(status=Transfer.Status.IN_TRANSIT).count() == 1
    assert InventoryCount.objects.filter(status=InventoryCount.Status.APPLIED).count() == 1
    assert User.objects.get(email="marta@arara.test").check_password(PASSWORD)


@override_settings(DEMO_MODE=False, DEBUG=False)
def test_reset_needs_demo_mode() -> None:
    with pytest.raises(CommandError, match="DEMO_MODE"):
        call_command("seed_demo", "--reset")


def test_sale_numbers_follow_the_clock() -> None:
    Seed(days=3).run()
    for store in {s.location_id for s in Sale.objects.all()}:
        by_number = list(Sale.objects.filter(location_id=store).order_by("number").values_list("created_at", flat=True))
        assert by_number == sorted(by_number)


def test_the_ledger_is_in_the_order_things_happened() -> None:
    # Every entry is dated no earlier than the one before it: nothing was sold before it arrived.
    Seed(days=5).run()
    dates = list(StockEntry.objects.order_by("pk").values_list("created_at", flat=True))
    assert dates == sorted(dates)
    first_sale = Sale.objects.order_by("created_at").values_list("created_at", flat=True).first()
    winter = PurchaseOrderLine.objects.filter(
        variant__product__collection__name="Inverno 2026", order__location__kind="store"
    )
    assert winter.exists(), "the stores open with the winter collection"
    assert first_sale is not None
    assert all(d <= first_sale for d in winter.values_list("order__receipts__received_at", flat=True))
