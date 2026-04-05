from django.db import models
from django.conf import settings


class Visit(models.Model):
    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "進行中"
        DONE = "done", "完了"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="visits",
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="visits",
    )

    # 予約から来院を起こすケースが多いのでFK
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
    )

    # 問診は基本1予約1つ想定なので OneToOne で取れるが、
    # Visit 側は optional で参照できれば十分
    intake = models.ForeignKey(
        "intakes.Intake",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits",
    )

    visited_at = models.DateTimeField()

    practitioner = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="visits_as_practitioner",
        help_text="施術者（担当）",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.IN_PROGRESS,
    )

    pain_scale_before = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="施術前PS（0-10）",
    )
    pain_scale_after = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="施術後PS（0-10）",
    )

    next_visit_suggestion = models.CharField(
        max_length=100,
        blank=True,
        help_text="次回来院の目安（例：2〜3日後）",
    )

    memo = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-visited_at", "-created_at"]
        indexes = [
            models.Index(fields=["clinic", "visited_at"]),
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["clinic", "patient"]),
        ]

    def __str__(self):
        return f"Visit {self.patient} {self.visited_at:%Y-%m-%d %H:%M}"

    def clean(self):
        # PSは0-10の範囲に抑える（UIで守っててもDB側で保険）
        from django.core.exceptions import ValidationError

        for field in ("pain_scale_before", "pain_scale_after"):
            val = getattr(self, field)
            if val is not None and not (0 <= val <= 10):
                raise ValidationError({field: "PSは0〜10で入力してください。"})
