from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.clinical_notes.models import ClinicalNote, ClinicalNoteHistory
from apps.clinics.models import Clinic
from apps.patients.models import Patient

from .models import TreatmentSession, TreatmentSessionChunk
from .views import build_treatment_session_flow_state


class TreatmentSessionFlowStateTests(SimpleTestCase):
    @staticmethod
    def _session(**overrides):
        values = {
            "transcript_text": "",
            "summary_json": {},
            "confirmed_summary_json": {},
            "status": TreatmentSession.Status.PENDING,
            "error_message": "",
            "appointment_id": None,
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    @staticmethod
    def _chunk(**overrides):
        values = {
            "audio_file": "recording.webm",
            "transcript_text": "",
            "status": TreatmentSessionChunk.Status.UPLOADED,
            "error_message": "",
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    def test_major_flow_states(self):
        cases = [
            (self._session(), [], "recording_ready"),
            (
                self._session(status=TreatmentSession.Status.UPLOADED),
                [self._chunk()],
                "transcription_waiting",
            ),
            (
                self._session(
                    status=TreatmentSession.Status.UPLOADED,
                    transcript_text="文字起こし",
                ),
                [
                    self._chunk(
                        transcript_text="文字起こし",
                        status=TreatmentSessionChunk.Status.SUMMARIZED,
                    )
                ],
                "summary_waiting",
            ),
            (
                self._session(
                    status=TreatmentSession.Status.DONE,
                    transcript_text="文字起こし",
                    summary_json={"session_summary": {}},
                ),
                [],
                "confirmation_waiting",
            ),
            (
                self._session(
                    status=TreatmentSession.Status.DONE,
                    summary_json={"session_summary": {}},
                    confirmed_summary_json={"session_summary": {}},
                    appointment_id=1,
                ),
                [],
                "confirmed",
            ),
            (
                self._session(
                    status=TreatmentSession.Status.DONE,
                    summary_json={"session_summary": {}},
                    confirmed_summary_json={"session_summary": {}},
                    appointment_id=1,
                ),
                [],
                "registered",
            ),
            (
                self._session(
                    status=TreatmentSession.Status.FAILED,
                    error_message="処理失敗",
                ),
                [],
                "error",
            ),
        ]

        for index, (session, chunks, expected_key) in enumerate(cases):
            with self.subTest(index=index, expected_key=expected_key):
                state = build_treatment_session_flow_state(
                    session,
                    chunks,
                    clinical_note_exists=expected_key == "registered",
                    clinical_note_is_current=expected_key == "registered",
                )
                self.assertEqual(state["key"], expected_key)

    def test_confirmed_without_appointment_cannot_register(self):
        state = build_treatment_session_flow_state(
            self._session(
                status=TreatmentSession.Status.DONE,
                summary_json={"session_summary": {}},
                confirmed_summary_json={"session_summary": {}},
            ),
            [],
        )

        self.assertFalse(state["can_register"])
        self.assertIn("予約", state["next_action"])


class TreatmentSessionStartTests(TestCase):
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
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="TS-A-001",
            last_name="山田",
            first_name="太郎",
            last_name_kana="ヤマダ",
            first_name_kana="タロウ",
            birth_date="1990-01-01",
            phone="09000000011",
        )
        self.other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="TS-B-001",
            last_name="佐藤",
            first_name="花子",
            last_name_kana="サトウ",
            first_name_kana="ハナコ",
            birth_date="1992-01-01",
            phone="09000000012",
        )
        self.client.force_login(self.user)

    def _create_appointment(self, start_at):
        return Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            status=Appointment.Status.BOOKED,
            created_by=self.user,
        )

    def test_patient_start_uses_today_appointment(self):
        today_at_noon = timezone.make_aware(
            datetime.combine(timezone.localdate(), time(hour=12))
        )
        appointment = self._create_appointment(today_at_noon)

        response = self.client.get(
            reverse("treatment_sessions:start_for_patient", args=[self.patient.id])
        )

        self.assertEqual(response.status_code, 302)
        session = TreatmentSession.objects.get(patient=self.patient)
        self.assertEqual(session.appointment_id, appointment.id)

    def test_patient_start_does_not_reuse_past_appointment(self):
        yesterday_at_noon = timezone.make_aware(
            datetime.combine(
                timezone.localdate() - timedelta(days=1),
                time(hour=12),
            )
        )
        past_appointment = self._create_appointment(yesterday_at_noon)

        response = self.client.get(
            reverse("treatment_sessions:start_for_patient", args=[self.patient.id])
        )

        self.assertEqual(response.status_code, 302)
        session = TreatmentSession.objects.get(patient=self.patient)
        self.assertIsNone(session.appointment_id)
        self.assertNotEqual(session.appointment_id, past_appointment.id)

    def test_other_clinic_patient_returns_404(self):
        response = self.client.get(
            reverse(
                "treatment_sessions:start_for_patient",
                args=[self.other_patient.id],
            )
        )

        self.assertEqual(response.status_code, 404)


class TreatmentSessionConfirmTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="Confirm Clinic")
        self.other_clinic = Clinic.objects.create(name="Other Clinic")
        self.user = user_model.objects.create_user(
            username="confirm-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.other_user = user_model.objects.create_user(
            username="other-staff",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="no-clinic-staff",
            password="test-password",
            role=user_model.Role.PRACTITIONER,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="CONFIRM-A-001",
            last_name="山田",
            first_name="太郎",
            last_name_kana="ヤマダ",
            first_name_kana="タロウ",
            birth_date="1990-01-01",
            phone="09000000021",
        )
        self.other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="CONFIRM-B-001",
            last_name="佐藤",
            first_name="花子",
            last_name_kana="サトウ",
            first_name_kana="ハナコ",
            birth_date="1992-01-01",
            phone="09000000022",
        )
        now = timezone.now()
        self.appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=now,
            end_at=now + timedelta(hours=1),
            status=Appointment.Status.BOOKED,
            created_by=self.user,
        )
        self.other_appointment = Appointment.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            start_at=now,
            end_at=now + timedelta(hours=1),
            status=Appointment.Status.BOOKED,
            created_by=self.other_user,
        )
        self.summary = self._summary(
            overall="AI作成時の要約",
            soap_s="AI作成時の主観情報",
        )
        self.session = TreatmentSession.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            summary_json=self.summary,
            status=TreatmentSession.Status.DONE,
            created_by=self.user,
            updated_by=self.user,
        )
        self.other_session = TreatmentSession.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            summary_json=self.summary,
            status=TreatmentSession.Status.DONE,
            created_by=self.other_user,
            updated_by=self.other_user,
        )
        self.client.force_login(self.user)

    @staticmethod
    def _summary(*, overall, soap_s):
        return {
            "important_points": ["右膝の荷重時変化を確認"],
            "session_summary": {
                "chief_complaint": "右膝の違和感",
                "visit_type": "followup",
                "overall_summary": overall,
                "progress_change": {},
            },
            "clinical_assessment": {
                "checked_areas": ["右膝"],
                "pain_areas": ["右膝"],
                "movement_tests": [],
                "findings": [],
                "suspected_causes": [],
                "treatment_intent": "",
            },
            "treatment": {
                "performed_treatments": ["右膝周囲への施術"],
                "target_areas": ["右膝"],
                "patient_response": "",
                "after_treatment_change": "",
            },
            "explanation": {
                "explained_to_patient": ["負担の可能性を説明"],
                "lifestyle_guidance": [],
                "home_care": [],
                "cautions_until_next_visit": ["無理な動作を避ける"],
            },
            "next_plan": {
                "next_treatment_policy": "次回も荷重時の変化を確認",
                "recommended_visit_timing": "",
                "items_to_check_next_time": ["階段動作"],
            },
            "soap": {
                "S": [soap_s],
                "O": ["荷重動作を確認"],
                "A": ["膝周囲への負担が続く可能性"],
                "P": ["次回も動作変化を確認"],
            },
            "progress_note": {
                "short_summary": overall,
                "record_text": overall,
            },
            "relationship_notes": [],
            "missing_information": ["痛みの強さを次回確認"],
            "safety_notes": ["強い痛みがある場合は再確認"],
        }

    @staticmethod
    def _confirm_post_data(*, overall, soap_s):
        return {
            "overall_summary": overall,
            "soap_s": soap_s,
            "soap_o": "確認済みの客観情報",
            "soap_a": "負担が続いている可能性",
            "soap_p": "次回も変化を確認",
            "target_areas": "右膝",
            "performed_treatments": "右膝周囲への施術",
            "patient_response": "動きやすさを確認",
            "after_treatment_change": "違和感が軽減した可能性",
            "explained_to_patient": "状態の傾向を説明",
            "lifestyle_guidance": "無理な負荷を避ける",
            "home_care": "無理のない範囲で運動",
            "next_treatment_policy": "荷重時の変化を再確認",
            "recommended_visit_timing": "状態に合わせて相談",
            "next_check_points": "階段動作\n片脚荷重",
            "caution_notes": "強い痛みがある場合は確認が必要",
            "followup_items": "痛みの強さ",
        }

    def test_other_clinic_session_confirm_returns_404(self):
        response = self.client.get(
            reverse(
                "treatment_sessions:session_confirm",
                args=[self.other_session.id],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_other_clinic_session_detail_returns_404(self):
        response = self.client.get(
            reverse(
                "treatment_sessions:detail",
                args=[self.other_session.id],
            )
        )

        self.assertEqual(response.status_code, 404)

    def test_no_clinic_user_session_confirm_returns_403(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(
            reverse(
                "treatment_sessions:session_confirm",
                args=[self.session.id],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_no_clinic_user_session_detail_returns_403(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(
            reverse(
                "treatment_sessions:detail",
                args=[self.session.id],
            )
        )

        self.assertEqual(response.status_code, 403)

    def test_empty_session_detail_explains_next_step_and_return_links(self):
        empty_session = TreatmentSession.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            status=TreatmentSession.Status.PENDING,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(
            reverse(
                "treatment_sessions:detail",
                args=[empty_session.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "録音はまだありません")
        self.assertContains(response, "カルテ案はまだありません")
        self.assertContains(response, "患者詳細へ戻る")
        self.assertContains(response, "予約管理へ戻る")

    def test_summary_json_can_be_displayed_on_confirm_page(self):
        response = self.client.get(
            reverse(
                "treatment_sessions:session_confirm",
                args=[self.session.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "録音内容から作成したカルテ案")
        self.assertContains(response, "AI作成時の要約")
        self.assertContains(response, "AI作成時の主観情報")

    def test_legacy_or_malformed_summary_does_not_break_confirm_page(self):
        legacy_session = TreatmentSession.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            summary_json={
                "overall_summary": "旧形式の要約",
                "soap": "型が異なる旧データ",
                "clinical_assessment": [],
                "treatment": None,
            },
            status=TreatmentSession.Status.DONE,
            created_by=self.user,
            updated_by=self.user,
        )

        response = self.client.get(
            reverse(
                "treatment_sessions:session_confirm",
                args=[legacy_session.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "旧形式の要約")

    def test_confirmed_summary_is_saved_and_preferred_on_redisplay(self):
        confirm_url = reverse(
            "treatment_sessions:session_confirm",
            args=[self.session.id],
        )
        response = self.client.post(
            confirm_url,
            self._confirm_post_data(
                overall="施術者が確認した要約",
                soap_s="施術者が確認した主観情報",
            ),
        )

        self.assertRedirects(
            response,
            confirm_url,
            fetch_redirect_response=False,
        )
        self.session.refresh_from_db()
        self.assertEqual(self.session.summary_status, "confirmed")
        self.assertEqual(
            self.session.confirmed_summary_json["soap"]["S"],
            ["施術者が確認した主観情報"],
        )
        self.assertEqual(
            self.session.confirmed_summary_json["important_points"],
            ["右膝の荷重時変化を確認"],
        )

        self.session.summary_json = self._summary(
            overall="再表示してはいけない要約",
            soap_s="再表示してはいけない主観情報",
        )
        self.session.save(update_fields=["summary_json"])

        response = self.client.get(confirm_url)
        self.assertContains(response, "施術者が確認した要約")
        self.assertNotContains(response, "再表示してはいけない要約")

    def test_register_uses_confirmed_summary_and_preserves_history(self):
        self.session.confirmed_summary_json = self._summary(
            overall="確認済み要約",
            soap_s="確認済みの主観情報",
        )
        self.session.summary_status = "confirmed"
        self.session.save(
            update_fields=["confirmed_summary_json", "summary_status"]
        )
        note = ClinicalNote.objects.create(
            appointment=self.appointment,
            patient=self.patient,
            treatment_session=self.session,
            soap_json={"S": ["更新前"]},
            extract_json={"overall_summary": "更新前"},
            followups_json=[],
            registered_by=self.user,
            updated_by=self.user,
        )

        response = self.client.post(
            reverse(
                "treatment_sessions:register_clinical_note",
                args=[self.session.id],
            )
        )

        self.assertEqual(response.status_code, 302)
        note.refresh_from_db()
        self.assertEqual(note.soap_json["S"], ["確認済みの主観情報"])
        self.assertEqual(
            note.extract_json["overall_summary"],
            "確認済み要約",
        )
        self.assertEqual(
            ClinicalNoteHistory.objects.filter(note=note).count(),
            1,
        )
        history = ClinicalNoteHistory.objects.get(note=note)
        self.assertEqual(history.soap_json, {"S": ["更新前"]})

        self.client.post(
            reverse(
                "treatment_sessions:register_clinical_note",
                args=[self.session.id],
            )
        )
        self.assertEqual(
            ClinicalNoteHistory.objects.filter(note=note).count(),
            1,
        )

    def test_registered_session_shows_registered_state_and_note_link(self):
        self.session.confirmed_summary_json = self._summary(
            overall="登録済み要約",
            soap_s="登録済みの主観情報",
        )
        self.session.summary_status = "confirmed"
        self.session.save(
            update_fields=["confirmed_summary_json", "summary_status"]
        )
        self.client.post(
            reverse(
                "treatment_sessions:register_clinical_note",
                args=[self.session.id],
            )
        )

        response = self.client.get(
            reverse(
                "treatment_sessions:detail",
                args=[self.session.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "カルテ登録済み")
        self.assertContains(response, "カルテ詳細を見る")

    @patch("apps.treatment_sessions.views.summarize_treatment_session")
    @patch("apps.treatment_sessions.views.build_ai_usage_summary")
    def test_resummarize_resets_confirmed_summary(
        self,
        mock_usage_summary,
        mock_summarize,
    ):
        mock_usage_summary.return_value = SimpleNamespace(
            can_use_ai=True,
            warning_message="",
        )
        recreated_summary = self._summary(
            overall="再作成後の要約",
            soap_s="再作成後の主観情報",
        )
        mock_summarize.return_value = recreated_summary
        self.session.transcript_text = "統合文字起こし"
        self.session.confirmed_summary_json = self.summary
        self.session.summary_status = "confirmed"
        self.session.confirmed_by = self.user
        self.session.confirmed_at = timezone.now()
        self.session.save(
            update_fields=[
                "transcript_text",
                "confirmed_summary_json",
                "summary_status",
                "confirmed_by",
                "confirmed_at",
            ]
        )

        response = self.client.post(
            reverse(
                "treatment_sessions:summarize",
                args=[self.session.id],
            ),
            {"force": "1"},
        )

        self.assertEqual(response.status_code, 302)
        self.session.refresh_from_db()
        self.assertEqual(self.session.summary_json, recreated_summary)
        self.assertEqual(self.session.confirmed_summary_json, {})
        self.assertEqual(self.session.summary_status, "draft")
        self.assertIsNone(self.session.confirmed_by)
        self.assertIsNone(self.session.confirmed_at)

    def test_unconfirmed_register_redirects_to_confirm_page(self):
        response = self.client.post(
            reverse(
                "treatment_sessions:register_clinical_note",
                args=[self.session.id],
            )
        )

        self.assertRedirects(
            response,
            reverse(
                "treatment_sessions:session_confirm",
                args=[self.session.id],
            ),
            fetch_redirect_response=False,
        )
        self.assertFalse(
            ClinicalNote.objects.filter(appointment=self.appointment).exists()
        )

    def test_session_without_appointment_shows_warning_and_cannot_register(self):
        session_without_appointment = TreatmentSession.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            summary_json=self.summary,
            confirmed_summary_json=self.summary,
            summary_status="confirmed",
            status=TreatmentSession.Status.DONE,
            created_by=self.user,
            updated_by=self.user,
        )
        confirm_response = self.client.get(
            reverse(
                "treatment_sessions:session_confirm",
                args=[session_without_appointment.id],
            )
        )

        self.assertContains(
            confirm_response,
            "この施術録音には予約が紐づいていません",
        )

        register_response = self.client.post(
            reverse(
                "treatment_sessions:register_clinical_note",
                args=[session_without_appointment.id],
            )
        )
        self.assertRedirects(
            register_response,
            reverse(
                "treatment_sessions:detail",
                args=[session_without_appointment.id],
            ),
            fetch_redirect_response=False,
        )
