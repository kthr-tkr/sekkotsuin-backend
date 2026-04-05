
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.exceptions import ValidationError

class Intake(models.Model):
    class SymptomType(models.TextChoices):
        ACUTE = "acute", "急性"
        CHRONIC = "chronic", "慢性"
        UNKNOWN = "unknown", "不明"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="intakes",
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="intakes",
    )

    # 1予約に対して問診は基本1つ（再送信させるなら FK にして複数もOK）
    appointment = models.OneToOneField(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="intake",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)

    # よく一覧や確認で見る “要点” はカラム化
    chief_complaint = models.CharField(max_length=255, blank=True)  # 主訴
    symptom_type = models.CharField(
        max_length=20,
        choices=SymptomType.choices,
        default=SymptomType.UNKNOWN,
    )
    onset = models.CharField(max_length=100, blank=True)  # いつから（選択＋自由記述）

    payload = models.JSONField(
        default=dict,
        blank=True,
        help_text="Web問診の詳細データ"
    )


    class Meta:
        ordering = ["-submitted_at"]
        indexes = [
            models.Index(fields=["clinic", "submitted_at"]),
            models.Index(fields=["clinic", "patient"]),
        ]

    def __str__(self):
        submitted = self.submitted_at.strftime("%Y-%m-%d") if self.submitted_at else "未提出"
        return f"Intake {self.patient} {submitted}"

    def clean(self):
        errors = {}

        if self.patient and self.clinic_id != self.patient.clinic_id:
            errors["patient"] = "患者は同じ院に所属している必要があります。"

        if self.appointment:
            if self.appointment.clinic_id != self.clinic_id:
                errors["appointment"] = "予約は同じ院に所属している必要があります。"
            if self.appointment.patient_id and self.appointment.patient_id != self.patient_id:
                errors["appointment"] = "予約の患者と問診の患者が一致していません。"

        if errors:
            raise ValidationError(errors)


class InterviewRecording(models.Model):
    class Status(models.TextChoices):
        UPLOADED = "uploaded", "Uploaded"
        PENDING = "pending", "未アップロード"
        TRANSCRIBING = "transcribing", "Transcribing"
        SUMMARIZING = "summarizing", "Summarizing"
        DONE = "done", "Done"
        FAILED = "failed", "Failed"

    clinic = models.ForeignKey("clinics.Clinic", on_delete=models.CASCADE, related_name="recordings")
    appointment = models.ForeignKey("appointments.Appointment", on_delete=models.CASCADE, related_name="recordings")
    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE, related_name="recordings")
    intake = models.ForeignKey("intakes.Intake", on_delete=models.SET_NULL, null=True, blank=True, related_name="recordings")

    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    audio_file = models.FileField(upload_to="interviews/%Y/%m/%d/", null=True, blank=True)
    mime_type = models.CharField(max_length=100, blank=True)
    duration_sec = models.IntegerField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.UPLOADED)
    error_message = models.TextField(blank=True)

    transcript_text = models.TextField(blank=True)
    transcript_json = models.JSONField(default=dict, blank=True)   # タイムスタンプ等
    summary_json = models.JSONField(default=dict, blank=True)      # SOAP/要点/注意点/質問候補

    # 追加（確定運用）
    class SummaryStatus(models.TextChoices):
        DRAFT = "draft", "Draft"
        CONFIRMED = "confirmed", "Confirmed"

    summary_status = models.CharField(
        max_length=16, choices=SummaryStatus.choices, default=SummaryStatus.DRAFT
    )
    confirmed_summary_json = models.JSONField(null=True, blank=True)  # 人が編集した確定版
    confirmed_at = models.DateTimeField(null=True, blank=True)
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="confirmed_recordings"
    )

    def get_active_summary(self):
        """表示で使う：確定版があれば優先"""
        return self.confirmed_summary_json or self.summary_json

    def mark_confirmed(self, *, user, data: dict):
        self.confirmed_summary_json = data
        self.summary_status = self.SummaryStatus.CONFIRMED
        self.confirmed_at = timezone.now()
        self.confirmed_by = user

    class Meta:
        indexes = [
            models.Index(fields=["clinic", "created_at"]),
            models.Index(fields=["appointment", "created_at"]),
            models.Index(fields=["status"]),
        ]
        ordering = ["-created_at"]

    def clean(self):
        errors = {}

        if self.patient and self.patient.clinic_id != self.clinic_id:
            errors["patient"] = "患者は同じ院に所属している必要があります。"

        if self.appointment:
            if self.appointment.clinic_id != self.clinic_id:
                errors["appointment"] = "予約は同じ院に所属している必要があります。"
            if self.appointment.patient_id and self.appointment.patient_id != self.patient_id:
                errors["appointment"] = "予約の患者と録音データの患者が一致していません。"

        if self.intake:
            if self.intake.clinic_id != self.clinic_id:
                errors["intake"] = "問診は同じ院に所属している必要があります。"
            if self.intake.patient_id != self.patient_id:
                errors["intake"] = "問診の患者と録音データの患者が一致していません。"

        if self.created_by and self.created_by.clinic_id != self.clinic_id:
            errors["created_by"] = "作成者は同じ院に所属している必要があります。"

        if self.confirmed_by and self.confirmed_by.clinic_id != self.clinic_id:
            errors["confirmed_by"] = "確定者は同じ院に所属している必要があります。"

        if errors:
            raise ValidationError(errors)