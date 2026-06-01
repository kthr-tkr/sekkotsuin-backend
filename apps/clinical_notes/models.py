from django.db import models
from django.conf import settings


class ClinicalNote(models.Model):
    appointment = models.OneToOneField(
        "appointments.Appointment",
        on_delete=models.CASCADE,
        related_name="clinical_note",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="clinical_notes",
        db_index=True,
    )
    intake = models.ForeignKey(
        "intakes.Intake",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinical_notes",
    )
    recording = models.ForeignKey(
        "intakes.InterviewRecording",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinical_notes",
    )

    treatment_session = models.ForeignKey(
        "treatment_sessions.TreatmentSession",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinical_notes",
        verbose_name="施術セッション",
    )

    web_intake_snapshot = models.JSONField(default=dict, blank=True)
    soap_json = models.JSONField(default=dict, blank=True)
    extract_json = models.JSONField(default=dict, blank=True)
    followups_json = models.JSONField(default=list, blank=True)

    registered_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="registered_clinical_notes",
    )

    # ★ 追加：最終更新者（nullable にして既存データを壊さない）
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_clinical_notes",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ClinicalNote(appt={self.appointment_id}, patient={self.patient_id})"

    from django.core.exceptions import ValidationError

    def clean(self):
        errors = {}

        if self.appointment and self.patient:
            if self.appointment.patient_id and self.appointment.patient_id != self.patient_id:
                errors["patient"] = "予約の患者とカルテの患者が一致していません。"

        if self.intake and self.patient and self.intake.patient_id != self.patient_id:
            errors["intake"] = "問診の患者とカルテの患者が一致していません。"

        if self.recording and self.patient and self.recording.patient_id != self.patient_id:
            errors["recording"] = "録音データの患者とカルテの患者が一致していません。"

        if self.appointment and self.intake and self.intake.appointment_id and self.intake.appointment_id != self.appointment_id:
            errors["intake"] = "問診の予約とカルテの予約が一致していません。"

        if self.recording and self.appointment and self.recording.appointment_id != self.appointment_id:
            errors["recording"] = "録音データの予約とカルテの予約が一致していません。"

        if self.treatment_session and self.patient and self.treatment_session.patient_id != self.patient_id:
            errors["treatment_session"] = "施術セッションの患者とカルテの患者が一致していません。"

        if (
            self.treatment_session
            and self.appointment
            and self.treatment_session.appointment_id
            and self.treatment_session.appointment_id != self.appointment_id
        ):
            errors["treatment_session"] = "施術セッションの予約とカルテの予約が一致していません。"

        if errors:
            raise ValidationError(errors)


class ClinicalNoteHistory(models.Model):
    note = models.ForeignKey(
        "clinical_notes.ClinicalNote",
        on_delete=models.CASCADE,
        related_name="histories",
    )

    # 編集前スナップショット
    soap_json = models.JSONField(default=dict, blank=True)
    extract_json = models.JSONField(default=dict, blank=True)
    followups_json = models.JSONField(default=list, blank=True)
    web_intake_snapshot = models.JSONField(default=dict, blank=True)

    edited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="clinical_note_histories",
    )

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"ClinicalNoteHistory(note={self.note_id}, created_at={self.created_at:%Y-%m-%d %H:%M})"