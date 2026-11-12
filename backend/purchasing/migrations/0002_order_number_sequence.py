from django.db import migrations


class Migration(migrations.Migration):
    """Purchase order numbers (PC-000001). Gaps are harmless for purchase orders."""

    dependencies = [("purchasing", "0001_initial")]
    operations = [
        migrations.RunSQL(
            "create sequence purchasing_order_number_seq minvalue 1 no cycle",
            "drop sequence purchasing_order_number_seq",
        )
    ]
