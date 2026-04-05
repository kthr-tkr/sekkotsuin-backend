from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError


class Appointment(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "問診待ち"
        BOOKED = "booked", "予約確定"
        ARRIVED = "arrived", "来院"
        COMPLETED = "completed", "完了"
        CANCELLED = "cancelled", "キャンセル"
        NO_SHOW = "no_show", "無断キャンセル"

    BLOCKING_STATUSES = [Status.PENDING, Status.BOOKED, Status.ARRIVED]

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="appointments",
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
    )

    treatment_plan = models.ForeignKey(
        "treatment_plans.TreatmentPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="appointments",
        verbose_name="関連施術計画",
    )

    start_at = models.DateTimeField()
    end_at = models.DateTimeField()

    menu = models.CharField(max_length=50, default="初診")

    assigned_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_appointments",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_appointments",
    )

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_at"]
        indexes = [
            models.Index(fields=["clinic", "start_at"]),
            models.Index(fields=["clinic", "status"]),
        ]

    def __str__(self):
        return f"{self.start_at:%Y-%m-%d %H:%M} {self.menu} ({self.get_status_display()})"

    def clean(self):
        errors = {}

        if not self.clinic_id:
            errors["clinic"] = "院情報は必須です。"

        if not self.start_at:
            errors["start_at"] = "開始時刻は必須です。"

        if not self.end_at:
            errors["end_at"] = "終了時刻は必須です。"

        if self.start_at and self.end_at and self.end_at <= self.start_at:
            errors["end_at"] = "終了時刻は開始時刻より後にしてください。"

        if self.patient and self.clinic_id:
            if self.patient.clinic_id != self.clinic_id:
                errors["patient"] = "患者は同じ院に所属している必要があります。"

            if self.patient.user:
                if self.patient.user.role != self.patient.user.Role.PATIENT:
                    errors["patient"] = "患者ユーザーのロールが不正です。"

                if self.patient.user.clinic_id != self.patient.clinic_id:
                    errors["patient"] = "患者ユーザーと患者プロフィールの院が一致していません。"

        if self.assigned_staff:
            if self.assigned_staff.role not in [
                self.assigned_staff.Role.ADMIN,
                self.assigned_staff.Role.RECEPTION,
                self.assigned_staff.Role.PRACTITIONER,
            ]:
                errors["assigned_staff"] = "担当者にはスタッフユーザーのみ指定できます。"

            if self.clinic_id and self.assigned_staff.clinic_id != self.clinic_id:
                errors["assigned_staff"] = "担当者は同じ院に所属している必要があります。"

        if self.created_by:
            if self.clinic_id and self.created_by.clinic_id != self.clinic_id:
                errors["created_by"] = "予約作成者は同じ院に所属している必要があります。"

        if self.treatment_plan:
            if self.patient_id and self.treatment_plan.patient_id != self.patient_id:
                errors["treatment_plan"] = "施術計画の患者と予約の患者が一致していません。"

            tp_clinic_id = getattr(self.treatment_plan, "clinic_id", None)
            if self.clinic_id and tp_clinic_id and tp_clinic_id != self.clinic_id:
                errors["treatment_plan"] = "施術計画は同じ院に所属している必要があります。"

        if (
            self.assigned_staff_id
            and self.clinic_id
            and self.start_at
            and self.end_at
            and self.status in self.BLOCKING_STATUSES
        ):
            overlapping_qs = Appointment.objects.filter(
                clinic_id=self.clinic_id,
                assigned_staff_id=self.assigned_staff_id,
                status__in=self.BLOCKING_STATUSES,
                start_at__lt=self.end_at,
                end_at__gt=self.start_at,
            )
            if self.pk:
                overlapping_qs = overlapping_qs.exclude(pk=self.pk)

            if overlapping_qs.exists():
                errors["assigned_staff"] = "担当者の同時間帯予約が既に存在します。"

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)