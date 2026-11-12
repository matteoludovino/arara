from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("transfers", "0001_initial")]
    operations = [
        migrations.RunSQL(
            "create sequence transfers_number_seq minvalue 1 no cycle", "drop sequence transfers_number_seq"
        )
    ]
