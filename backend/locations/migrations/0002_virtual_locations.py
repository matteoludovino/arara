from django.db import migrations

VIRTUAL = (
    ("TRANSITO", "Em trânsito", "transit"),
    ("PERDAS", "Perdas", "loss"),
)


def create_virtual_locations(apps, schema_editor):  # type: ignore[no-untyped-def]
    Location = apps.get_model("locations", "Location")
    for code, name, kind in VIRTUAL:
        Location.objects.get_or_create(kind=kind, defaults={"code": code, "name": name})


class Migration(migrations.Migration):
    dependencies = [("locations", "0001_initial")]
    operations = [migrations.RunPython(create_virtual_locations, migrations.RunPython.noop)]
