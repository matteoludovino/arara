import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import override_settings

from accounts.models import User
from common.integrity import all_problems
from counts.models import InventoryCount
from demo.seed import PASSWORD, Seed
from pos.models import CashSession, Sale
from purchasing.models import PurchaseOrder
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
