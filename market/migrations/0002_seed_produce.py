from django.db import migrations

PRODUCE = [
    ("potatoes", "Potatoes", 44, 52),
    ("maize", "Maize", 58, 68),
    ("tomatoes", "Tomatoes", 78, 92),
    ("kale", "Kale (sukuma wiki)", 36, 44),
    ("onions", "Onions", 88, 102),
    ("beans", "Beans", 140, 160),
    ("bananas", "Bananas", 50, 60),
    ("avocados", "Avocados", 100, 120),
]


def add_produce(apps, schema_editor):
    Produce = apps.get_model("market", "Produce")
    for slug, name, lo, hi in PRODUCE:
        Produce.objects.get_or_create(slug=slug, defaults={"name": name, "ref_min": lo, "ref_max": hi})


class Migration(migrations.Migration):
    dependencies = [("market", "0001_initial")]
    operations = [migrations.RunPython(add_produce, migrations.RunPython.noop)]
