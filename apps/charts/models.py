from django.db import models
from django.conf import settings


class ChartNote(models.Model):
    class State(models.TextChoices):
        DRAFT_AI = "draft_ai", "AI下書き"
        EDITED = "edited", "編集済み"
        FINALIZED = "finalized", "確定"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="chart_notes",
    )

    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.CASCADE,
        related_name="chart_notes",
    )

    version = models.PositiveIntegerField(default=1)

    state = models.CharField(
        max_length=20,
        choices=State.choices,
        default=State.DRAFT_AI,
    )

    # SOAP 本文
    subjective_text = models.TextField(blank=True)  # S
    objective_text = models.TextField(blank=True)   # O
    assessment_text = models.TextField(blank=True)  # A
    plan_text = models.TextField(blank=True)        # P

    # 生活指導や注意事項（任意）
    precautions = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_chart_notes",
        help_text="作成者（AIの場合は空でもOK）",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "created_at"]),
            models.Index(fields=["clinic", "visit"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["visit", "version"],
                name="unique_chartnote_version_per_visit",
            )
        ]

    def __str__(self):
        return f"ChartNote v{self.version} ({self.get_state_display()}) - {self.visit}"

    @staticmethod
    def next_version_for_visit(visit_id: int) -> int:
        """次のversion番号を返す（簡易版）"""
        from django.db.models import Max
        m = ChartNote.objects.filter(visit_id=visit_id).aggregate(Max("version"))["version__max"]
        return (m or 0) + 1
