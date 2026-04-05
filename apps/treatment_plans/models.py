from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError

class TreatmentPlan(models.Model):
    VISIT_GUIDE_TYPE_CHOICES = [
        ("daily", "毎日"),
        ("weekly", "週"),
        ("monthly", "月"),
        ("custom", "個別設定"),
    ]

    STATUS_CHOICES = [
        ("active", "進行中"),
        ("completed", "完了"),
        ("paused", "中断"),
    ]

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="treatment_plans",
        verbose_name="患者",
    )
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="treatment_plans",
        verbose_name="関連予約",
    )
    intake = models.ForeignKey(
        "intakes.Intake",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="treatment_plans",
        verbose_name="関連問診",
    )
    clinical_note = models.ForeignKey(
        "clinical_notes.ClinicalNote",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="treatment_plans",
        verbose_name="関連カルテ",
    )

    title = models.CharField("計画タイトル", max_length=200, blank=True)
    chief_complaint = models.CharField("主訴", max_length=255, blank=True)

    status = models.CharField(
        "計画ステータス",
        max_length=20,
        choices=STATUS_CHOICES,
        default="active",
    )

    next_visit_date = models.DateField("次回来院日", null=True, blank=True)

    visit_guide_type = models.CharField(
        "来院目安区分",
        max_length=20,
        choices=VISIT_GUIDE_TYPE_CHOICES,
        blank=True,
    )
    visit_guide_count = models.PositiveIntegerField("来院回数目安", null=True, blank=True)
    visit_guide_unit_note = models.CharField("来院目安補足", max_length=100, blank=True)

    bath_instruction = models.TextField("入浴について", blank=True)
    walking_instruction = models.TextField("歩行について", blank=True)
    exercise_instruction = models.TextField("運動について", blank=True)
    work_instruction = models.TextField("就労について", blank=True)
    lifestyle_other_instruction = models.TextField("日常生活その他", blank=True)

    caution_notes = models.TextField("その他注意事項", blank=True)

    expected_recovery_weeks_min = models.PositiveIntegerField("改善目安（最短週）", null=True, blank=True)
    expected_recovery_weeks_max = models.PositiveIntegerField("改善目安（最長週）", null=True, blank=True)

    rebound_reaction_note = models.TextField("好転反応の説明", blank=True)

    explained_to_patient = models.BooleanField("患者へ説明済み", default=False)
    is_active = models.BooleanField("有効な計画", default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_treatment_plans",
        verbose_name="作成者",
    )
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "施術計画"
        verbose_name_plural = "施術計画"
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.patient} / {self.title or self.chief_complaint or '施術計画'}"

    def clean(self):
        errors = {}

        if self.appointment and self.appointment.patient_id and self.appointment.patient_id != self.patient_id:
            errors["appointment"] = "関連予約の患者と施術計画の患者が一致していません。"

        if self.intake and self.intake.patient_id != self.patient_id:
            errors["intake"] = "関連問診の患者と施術計画の患者が一致していません。"

        if self.clinical_note and self.clinical_note.patient_id != self.patient_id:
            errors["clinical_note"] = "関連カルテの患者と施術計画の患者が一致していません。"

        if (
            self.expected_recovery_weeks_min is not None
            and self.expected_recovery_weeks_max is not None
            and self.expected_recovery_weeks_min > self.expected_recovery_weeks_max
        ):
            errors["expected_recovery_weeks_max"] = "最長週は最短週以上にしてください。"

        if errors:
            raise ValidationError(errors)


class TreatmentProgress(models.Model):
    plan = models.ForeignKey(
        TreatmentPlan,
        on_delete=models.CASCADE,
        related_name="progress_logs",
        verbose_name="施術計画",
    )

    visit_date = models.DateField("施術日")
    pain_level = models.PositiveSmallIntegerField("痛みレベル", null=True, blank=True)

    symptom_change = models.TextField("症状変化", blank=True)
    adl_status = models.TextField("ADL・生活状況", blank=True)
    treatment_detail = models.TextField("施術内容", blank=True)
    post_treatment_response = models.TextField("施術後の反応", blank=True)
    next_instruction = models.TextField("次回までの指示", blank=True)
    memo = models.TextField("備考", blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_treatment_progresses",
        verbose_name="記録者",
    )
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "施術経過記録"
        verbose_name_plural = "施術経過記録"
        ordering = ["-visit_date", "-created_at"]

    def __str__(self):
        return f"{self.plan_id} / {self.visit_date}"

def clean(self):
    errors = {}

    if self.pain_level is not None and not (0 <= self.pain_level <= 10):
        errors["pain_level"] = "痛みレベルは 0〜10 の範囲で入力してください。"

    if errors:
        raise ValidationError(errors)