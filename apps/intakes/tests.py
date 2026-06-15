from datetime import timedelta
import inspect
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai_usage.models import AiUsageLog
from apps.appointments.models import Appointment
from apps.clinical_notes.models import ClinicalNote, ClinicalNoteHistory
from apps.clinics.models import Clinic
from apps.patients.models import Patient
from apps.treatment_sessions.models import TreatmentSession

from .models import Intake, InterviewRecording
from .views import build_interview_recording_flow_state
from . import views as intake_views


class InterviewRecordingStateTests(SimpleTestCase):
    @staticmethod
    def _recording(**overrides):
        values = {
            "audio_file": None,
            "transcript_text": "",
            "summary_json": {},
            "confirmed_summary_json": None,
            "status": InterviewRecording.Status.PENDING,
            "error_message": "",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_major_flow_states(self):
        cases = [
            (self._recording(), "recording_ready"),
            (
                self._recording(
                    audio_file="interviews/recording.webm",
                    status=InterviewRecording.Status.UPLOADED,
                ),
                "transcription_waiting",
            ),
            (
                self._recording(
                    audio_file="interviews/recording.webm",
                    transcript_text="文字起こし",
                    status=InterviewRecording.Status.UPLOADED,
                ),
                "summary_waiting",
            ),
            (
                self._recording(
                    transcript_text="文字起こし",
                    summary_json={"soap": {}},
                    status=InterviewRecording.Status.DONE,
                ),
                "confirmation_waiting",
            ),
            (
                self._recording(
                    summary_json={"soap": {}},
                    confirmed_summary_json={"soap": {}},
                    status=InterviewRecording.Status.DONE,
                ),
                "confirmed",
            ),
            (
                self._recording(
                    summary_json={"soap": {}},
                    confirmed_summary_json={"soap": {}},
                    status=InterviewRecording.Status.DONE,
                ),
                "registered",
            ),
            (
                self._recording(
                    status=InterviewRecording.Status.FAILED,
                    error_message="処理失敗",
                ),
                "error",
            ),
        ]

        for recording, expected_key in cases:
            with self.subTest(expected_key=expected_key):
                state = build_interview_recording_flow_state(
                    recording,
                    clinical_note_exists=expected_key == "registered",
                    clinical_note_is_current=expected_key == "registered",
                )
                self.assertEqual(state["key"], expected_key)

    def test_intake_recording_views_do_not_use_file_path(self):
        source = "\n".join(
            [
                inspect.getsource(intake_views.upload_recording),
                inspect.getsource(intake_views.process_recording),
            ]
        )
        self.assertNotIn("audio_file.path", source)


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
        self.no_clinic_user = user_model.objects.create_user(
            username="staff-no-clinic",
            password="test-password",
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

    def test_recording_detail_empty_state_explains_next_step_and_return_links(self):
        empty_recording = InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            intake=self.intake,
            created_by=self.user,
            status=InterviewRecording.Status.PENDING,
            summary_json={},
        )

        response = self.client.get(
            reverse("intakes:recording_detail", args=[empty_recording.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "カルテ案はまだありません")
        self.assertContains(response, "患者詳細へ戻る")
        self.assertContains(response, "予約管理へ戻る")

    def test_no_clinic_user_recording_detail_returns_403(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(
            reverse("intakes:recording_detail", args=[self.recording.id])
        )

        self.assertEqual(response.status_code, 403)

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
        self.recording.confirmed_summary_json = self.summary
        self.recording.summary_status = (
            InterviewRecording.SummaryStatus.CONFIRMED
        )
        self.recording.save(
            update_fields=["confirmed_summary_json", "summary_status"]
        )
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

        self.client.post(
            reverse("staff:register_clinical_note", args=[self.recording.id])
        )
        self.assertEqual(
            ClinicalNoteHistory.objects.filter(note=note).count(),
            1,
        )

    def test_summary_only_cannot_be_registered(self):
        response = self.client.post(
            reverse("staff:register_clinical_note", args=[self.recording.id])
        )

        self.assertRedirects(
            response,
            reverse(
                "intakes:recording_detail",
                args=[self.recording.id],
            ),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            ClinicalNote.objects.filter(appointment=self.appointment).exists()
        )

    def test_confirmed_summary_can_be_registered_and_is_displayed(self):
        self.recording.confirmed_summary_json = self.summary
        self.recording.summary_status = (
            InterviewRecording.SummaryStatus.CONFIRMED
        )
        self.recording.status = InterviewRecording.Status.DONE
        self.recording.save(
            update_fields=[
                "confirmed_summary_json",
                "summary_status",
                "status",
            ]
        )

        register_response = self.client.post(
            reverse("staff:register_clinical_note", args=[self.recording.id])
        )
        self.assertEqual(register_response.status_code, 302)

        detail_response = self.client.get(
            reverse("intakes:recording_detail", args=[self.recording.id])
        )
        self.assertContains(detail_response, "カルテ登録済み")
        self.assertContains(detail_response, "カルテ詳細を見る")

    @patch("apps.intakes.views.build_ai_usage_summary")
    @patch("apps.intakes.views.run_stt")
    @patch("apps.intakes.views.summarize_transcript")
    def test_resummarize_resets_confirmed_summary(
        self,
        summarize_mock,
        run_stt_mock,
        usage_summary_mock,
    ):
        usage_summary_mock.return_value = SimpleNamespace(
            can_use_ai=True,
            warning_message="",
        )
        recreated_summary = {
            **self.summary,
            "extract": {
                **self.summary["extract"],
                "chief_complaint": "再作成後の主訴",
            },
        }
        summarize_mock.return_value = recreated_summary
        self.recording.transcript_text = "既存の文字起こし"
        self.recording.confirmed_summary_json = self.summary
        self.recording.summary_status = (
            InterviewRecording.SummaryStatus.CONFIRMED
        )
        self.recording.status = InterviewRecording.Status.DONE
        self.recording.save(
            update_fields=[
                "transcript_text",
                "confirmed_summary_json",
                "summary_status",
                "status",
            ]
        )

        response = self.client.post(
            reverse("intakes:process_recording", args=[self.recording.id]),
            {"force": "1"},
        )

        self.assertEqual(response.status_code, 302)
        self.recording.refresh_from_db()
        self.assertEqual(self.recording.summary_json, recreated_summary)
        self.assertIsNone(self.recording.confirmed_summary_json)
        self.assertEqual(
            self.recording.summary_status,
            InterviewRecording.SummaryStatus.DRAFT,
        )
        run_stt_mock.assert_not_called()

    @patch("apps.intakes.views.summarize_transcript")
    @patch("apps.intakes.views.run_stt")
    def test_stt_usage_log_uses_model_returned_by_stt(
        self,
        run_stt_mock,
        summarize_mock,
    ):
        self.recording.audio_file = "interviews/test.webm"
        self.recording.duration_sec = 60
        self.recording.summary_json = {}
        self.recording.save(
            update_fields=["audio_file", "duration_sec", "summary_json"]
        )
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
