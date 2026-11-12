from django.db import migrations


class Migration(migrations.Migration):
    """Serial numbers for the store's own EAN-13 codes. Gaps are fine; repeats are not."""

    dependencies = [("catalog", "0001_initial")]
    operations = [
        migrations.RunSQL(
            "create sequence catalog_internal_barcode_seq minvalue 1 maxvalue 999999999 no cycle",
            "drop sequence catalog_internal_barcode_seq",
        )
    ]
