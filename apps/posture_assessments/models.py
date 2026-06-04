from django.conf import settings
from django.db import models
from django.core.exceptions import ValidationError


class PostureAssessment(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "下書き"
        ANALYZING = "analyzing", "AI分析中"
        ANALYZED = "analyzed", "AI分析済み"
        CONFIRMED = "confirmed", "確定済み"
        FAILED = "failed", "失敗"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="posture_assessments",
        db_index=True,
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="posture_assessments",
        db_index=True,
    )

    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posture_assessments",
    )

    treatment_session = models.ForeignKey(
        "treatment_sessions.TreatmentSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posture_assessments",
    )

    clinical_note = models.ForeignKey(
        "clinical_notes.ClinicalNote",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posture_assessments",
    )

    title = models.CharField(
        max_length=120,
        default="AI姿勢分析",
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        db_index=True,
    )

    memo = models.TextField(
        blank=True,
        default="",
        help_text="撮影時の補足メモ。例：右膝痛、バスケ後に痛みなど",
    )

    ai_summary_json = models.JSONField(
        default=dict,
        blank=True,
    )

    confirmed_summary_json = models.JSONField(
        default=dict,
        blank=True,
    )

    ai_model_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    ai_error_message = models.TextField(
        blank=True,
        default="",
    )

    analyzed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    confirmed_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_posture_assessments",
    )

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_posture_assessments",
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_posture_assessments",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "patient", "status"]),
            models.Index(fields=["clinic", "created_at"]),
        ]

    def __str__(self):
        return f"PostureAssessment(id={self.id}, patient={self.patient_id})"

    def get_active_summary(self):
        if self.confirmed_summary_json:
            return self.confirmed_summary_json
        return self.ai_summary_json or {}

    @property
    def is_confirmed(self):
        return self.status == self.Status.CONFIRMED

    def clean(self):
        errors = {}

        if self.patient_id and self.clinic_id:
            patient_clinic_id = getattr(self.patient, "clinic_id", None)
            if patient_clinic_id and patient_clinic_id != self.clinic_id:
                errors["patient"] = "患者は同じ院に所属している必要があります。"

        if self.appointment_id:
            if self.appointment.clinic_id != self.clinic_id:
                errors["appointment"] = "予約は同じ院に所属している必要があります。"

            if self.appointment.patient_id != self.patient_id:
                errors["appointment"] = "予約の患者と姿勢分析の患者が一致していません。"

        if self.treatment_session_id:
            if self.treatment_session.clinic_id != self.clinic_id:
                errors["treatment_session"] = "施術セッションは同じ院に所属している必要があります。"

            if self.treatment_session.patient_id != self.patient_id:
                errors["treatment_session"] = "施術セッションの患者と姿勢分析の患者が一致していません。"

        if self.clinical_note_id:
            if self.clinical_note.patient_id != self.patient_id:
                errors["clinical_note"] = "カルテの患者と姿勢分析の患者が一致していません。"

        if errors:
            raise ValidationError(errors)


class PostureAssessmentImage(models.Model):
    class ImageType(models.TextChoices):
        FRONT = "front", "正面"
        SIDE_RIGHT = "side_right", "右側面"
        SIDE_LEFT = "side_left", "左側面"
        BACK = "back", "背面"
        OTHER = "other", "その他"

    assessment = models.ForeignKey(
        PostureAssessment,
        on_delete=models.CASCADE,
        related_name="images",
    )

    image_type = models.CharField(
        max_length=30,
        choices=ImageType.choices,
        db_index=True,
    )

    image = models.ImageField(
        upload_to="posture/%Y/%m/",
    )

    thumbnail = models.ImageField(
        upload_to="posture/thumbs/%Y/%m/",
        null=True,
        blank=True,
    )

    ai_image = models.ImageField(
        upload_to="posture/ai/%Y/%m/",
        null=True,
        blank=True,
    )

    order = models.PositiveIntegerField(default=0)

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="uploaded_posture_images",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["order", "id"]
        indexes = [
            models.Index(fields=["assessment", "image_type"]),
        ]

    def __str__(self):
        return f"PostureAssessmentImage(assessment={self.assessment_id}, type={self.image_type})"


class PostureAssessmentHistory(models.Model):
    assessment = models.ForeignKey(
        PostureAssessment,
        on_delete=models.CASCADE,
        related_name="histories",
    )

    ai_summary_json = models.JSONField(default=dict, blank=True)
    confirmed_summary_json = models.JSONField(default=dict, blank=True)

    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="posture_assessment_histories",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"PostureAssessmentHistory(assessment={self.assessment_id})"