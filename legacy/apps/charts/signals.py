from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.visits.models import Visit
from .models import ChartNote


@receiver(post_save, sender=Visit)
def create_chart_note_on_visit_create(sender, instance: Visit, created: bool, **kwargs):
    if not created:
        return

    # 念のため、すでに存在する場合は作らない
    if ChartNote.objects.filter(visit=instance).exists():
        return

    ChartNote.objects.create(
        clinic=instance.clinic,
        visit=instance,
        version=1,
        state=ChartNote.State.DRAFT_AI,
        created_by=instance.practitioner,  # 空でもOK
        subjective_text="",
        objective_text="",
        assessment_text="",
        plan_text="",
    )
