from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai_usage.models import AiUsageLog
from apps.appointments.models import Appointment
from apps.clinical_notes.models import ClinicalNote, ClinicalNoteHistory
from apps.clinics.models import Clinic
from apps.patients.models import Patient
from apps.treatment_sessions.models import TreatmentSession

from .models import Intake, InterviewRecording


class InterviewRecordingFlowTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="Clinic A")
        self.other_clinic = Clinic.objects.create(name="Clinic B")
        self.user = user_model.objects.create_user(
            username="staff-a",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.other_user = user_model.objects.create_user(
            username="staff-b",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="A-001",
            last_name="山田",
            first_name="太郎",
            last_name_kana="ヤマダ",
            first_name_kana="タロウ",
            birth_date="1990-01-01",
            phone="09000000001",
        )
        self.other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="B-001",
            last_name="佐藤",
            first_name="花子",
            last_name_kana="サトウ",
            first_name_kana="ハナコ",
            birth_date="1992-01-01",
            phone="09000000002",
        )
        now = timezone.now()
        self.appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=now,
            end_at=now + timedelta(hours=1),
            created_by=self.user,
        )
        self.other_appointment = Appointment.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            start_at=now,
            end_at=now + timedelta(hours=1),
            created_by=self.other_user,
        )
        self.intake = Intake.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            payload={},
        )
        self.other_intake = Intake.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            payload={},
        )
        self.summary = {
            "version": "1.0",
            "soap": {
                "S": ["腰部の違和感"],
                "O": ["動作時の状態を確認"],
                "A": ["負担が続いている可能性"],
                "P": ["次回も変化を確認"],
            },
            "extract": {
                "chief_complaint": "腰部の違和感",
                "onset": "1週間前",
                "trigger": "",
                "severity_0_10": None,
                "locations": ["腰部"],
                "qualities": [],
                "symptom_type": "unknown",
                "red_flags": {"present": False, "notes": []},
            },
            "followups": ["痛みの変化を確認"],
            "meta": {"language": "ja", "model": "gpt-4.1-mini"},
        }
        self.recording = InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            intake=self.intake,
            created_by=self.user,
            status=InterviewRecording.Status.UPLOADED,
            summary_json=self.summary,
        )
        self.other_recording = InterviewRecording.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            intake=self.other_intake,
            created_by=self.other_user,
            status=InterviewRecording.Status.UPLOADED,
            summary_json=self.summary,
        )
        self.client.force_login(self.user)

    def test_other_clinic_recording_detail_returns_404(self):
        response = self.client.get(
            reverse(
                "intakes:recording_detail",
                args=[self.other_recording.id],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_recording_detail_uses_existing_confirm_url(self):
        response = self.client.get(
            reverse("intakes:recording_detail", args=[self.recording.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            f'action="{reverse("intakes:recording_confirm", args=[self.recording.id])}"',
        )

    def test_legacy_record_page_redirects_without_creating_recording(self):
        before_count = InterviewRecording.objects.count()

        response = self.client.get(
            reverse("intakes:record_page", args=[self.appointment.id])
        )

        self.assertRedirects(
            response,
            reverse("intakes:recording_new", args=[self.appointment.id]),
            fetch_redirect_response=False,
        )
        self.assertEqual(InterviewRecording.objects.count(), before_count)

    def test_registering_recording_preserves_history_and_switches_source(self):
        session = TreatmentSession.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            intake=self.intake,
            created_by=self.user,
            updated_by=self.user,
        )
        note = ClinicalNote.objects.create(
            appointment=self.appointment,
            patient=self.patient,
            intake=self.intake,
            treatment_session=session,
            soap_json={"S": ["更新前"]},
            extract_json={"chief_complaint": "更新前"},
            followups_json=["更新前"],
            registered_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(
            reverse("staff:register_clinical_note", args=[self.recording.id])
        )

        self.assertEqual(response.status_code, 302)
        note.refresh_from_db()
        history = ClinicalNoteHistory.objects.get(note=note)
        self.assertEqual(history.soap_json, {"S": ["更新前"]})
        self.assertEqual(note.recording_id, self.recording.id)
        self.assertIsNone(note.treatment_session_id)

    @patch("apps.intakes.views.summarize_transcript")
    @patch("apps.intakes.views.run_stt")
    def test_stt_usage_log_uses_model_returned_by_stt(
        self,
        run_stt_mock,
        summarize_mock,
    ):
        self.recording.audio_file = "interviews/test.webm"
        self.recording.duration_sec = 60
        self.recording.save(update_fields=["audio_file", "duration_sec"])
        run_stt_mock.return_value = (
            "文字起こし結果",
            {"model": "gpt-4o-mini-transcribe", "language": "ja"},
        )
        summarize_mock.return_value = self.summary

        response = self.client.post(
            reverse("intakes:process_recording", args=[self.recording.id])
        )

        self.assertEqual(response.status_code, 302)
        usage_log = AiUsageLog.objects.get(
            recording=self.recording,
            usage_type=AiUsageLog.UsageType.STT,
            status=AiUsageLog.Status.SUCCESS,
        )
        self.assertEqual(usage_log.model_name, "gpt-4o-mini-transcribe")
