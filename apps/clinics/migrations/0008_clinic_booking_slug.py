import re

import apps.clinics.models
from django.db import migrations, models
from django.utils.text import slugify


def _slug_base(value, fallback):
    base = slugify(value or "", allow_unicode=False).lower()
    base = re.sub(r"[^a-z0-9_-]+", "-", base).strip("-_")
    return (base or fallback)[:70].strip("-_") or fallback


def populate_booking_slugs(apps, schema_editor):
    Clinic = apps.get_model("clinics", "Clinic")
    used = set()
    for clinic in Clinic.objects.order_by("id"):
        base = _slug_base(clinic.name, f"clinic-{clinic.id}")
        candidate = base[:80]
        counter = 2
        while candidate in used or Clinic.objects.filter(booking_slug=candidate).exclude(pk=clinic.pk).exists():
            suffix = f"-{counter}"
            candidate = f"{base[:80 - len(suffix)]}{suffix}"
            counter += 1
        clinic.booking_slug = candidate
        clinic.save(update_fields=["booking_slug"])
        used.add(candidate)


class Migration(migrations.Migration):

    dependencies = [
        ("clinics", "0007_patientsharetoken"),
    ]

    operations = [
        migrations.AddField(
            model_name="clinic",
            name="booking_slug",
            field=models.SlugField(
                blank=True,
                help_text="患者向け院別予約URL /b/<slug>/ に使用します。",
                max_length=80,
                null=True,
                unique=True,
                validators=[apps.clinics.models.booking_slug_validator],
                verbose_name="予約URL用slug",
            ),
        ),
        migrations.RunPython(populate_booking_slugs, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="clinic",
            name="booking_slug",
            field=models.SlugField(
                blank=True,
                help_text="患者向け院別予約URL /b/<slug>/ に使用します。",
                max_length=80,
                unique=True,
                validators=[apps.clinics.models.booking_slug_validator],
                verbose_name="予約URL用slug",
            ),
        ),
    ]
