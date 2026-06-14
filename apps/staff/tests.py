from datetime import date, datetime, time, timedelta
import inspect

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.clinical_notes.models import ClinicalNote
from apps.clinics.models import Clinic
from apps.intakes.models import Intake
from apps.patients.models import Patient
from apps.posture_assessments.models import PostureAssessment
from apps.staff import views as staff_views
from apps.treatment_plans.models import TreatmentPlan
from apps.treatment_sessions.models import TreatmentSession


class StaffPatientBodyProfileTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="Profile Clinic")
        self.other_clinic = Clinic.objects.create(name="Other Clinic")
        self.user = user_model.objects.create_user(
            username="profile-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="profile-no-clinic",
            password="test-password",
            role=user_model.Role.PRACTITIONER,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="PROFILE-A-001",
            last_name="山田",
            first_name="太郎",
            last_name_kana="ヤマダ",
            first_name_kana="タロウ",
            birth_date=date(1990, 1, 1),
            phone="09000000001",
        )
        self.other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="PROFILE-B-001",
            last_name="佐藤",
            first_name="花子",
            last_name_kana="サトウ",
            first_name_kana="ハナコ",
            birth_date=date(1992, 1, 1),
            phone="09000000002",
        )
        self.client.force_login(self.user)

    def _detail_url(self, patient=None):
        return reverse(
            "staff:patient_detail",
            args=[(patient or self.patient).id],
        )

    def _precheck_url(self, patient=None):
        return reverse(
            "staff:pre_treatment_check",
            args=[(patient or self.patient).id],
        )

    @staticmethod
    def _profile_item(response, key):
        return next(
            item
            for item in response.context["body_profile_items"]
            if item["key"] == key
        )

    def test_other_clinic_patient_detail_returns_404(self):
        response = self.client.get(self._detail_url(self.other_patient))

        self.assertEqual(response.status_code, 404)

    def test_user_without_clinic_is_forbidden(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._detail_url())

        self.assertEqual(response.status_code, 403)

    def test_confirmed_posture_summary_has_priority(self):
        PostureAssessment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            status=PostureAssessment.Status.CONFIRMED,
            ai_summary_json={
                "joint_assessments": {
                    "shoulder": {"summary": "AI結果では左肩を確認"}
                }
            },
            confirmed_summary_json={
                "joint_assessments": {
                    "shoulder": {
                        "summary": "確認済み所見では右肩下制傾向",
                        "check_points": ["肩甲帯の左右位置を確認"],
                    }
                }
            },
        )

        response = self.client.get(self._detail_url())
        shoulder = self._profile_item(response, "shoulder")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["posture_summary_source"], "confirmed")
        self.assertIn("確認済み所見", shoulder["text"])
        self.assertNotIn("AI結果", shoulder["text"])
        self.assertIn("肩甲帯", shoulder["check_point"])

    def test_ai_summary_is_used_when_confirmed_summary_is_empty(self):
        PostureAssessment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            status=PostureAssessment.Status.ANALYZED,
            ai_summary_json={
                "joint_assessments": {
                    "knee": {"summary": "右膝にニーイン傾向の可能性"}
                }
            },
            confirmed_summary_json={},
        )

        response = self.client.get(self._detail_url())
        knee = self._profile_item(response, "knee")

        self.assertEqual(response.context["posture_summary_source"], "ai")
        self.assertIn("ニーイン傾向", knee["text"])
        self.assertEqual(knee["level"], "check")

    def test_regions_without_information_are_unassessed(self):
        response = self.client.get(self._detail_url())

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["body_profile_items"])
        self.assertTrue(all(
            item["level"] == "unassessed"
            for item in response.context["body_profile_items"]
        ))

    def test_sports_keyword_adds_related_region_guidance(self):
        Intake.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            submitted_at=timezone.now(),
            payload={
                "sport": "バスケット",
                "pain_trigger": "ジャンプ着地後",
            },
        )

        response = self.client.get(self._detail_url())
        knee = self._profile_item(response, "knee")
        hip = self._profile_item(response, "hip")
        ankle = self._profile_item(response, "ankle_foot")

        self.assertEqual(response.context["patient_context_profile"]["sports"], "バスケット")
        for item in (knee, hip, ankle):
            self.assertEqual(item["level"], "check")
            self.assertIn("荷重バランス", item["context_note"])

    def test_camel_case_json_keys_are_normalized(self):
        PostureAssessment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            status=PostureAssessment.Status.ANALYZED,
            ai_summary_json={
                "jointAssessments": {
                    "shoulders": {
                        "overview": "右肩下制傾向の可能性",
                        "checkPoints": ["肩甲帯の位置を確認"],
                    }
                },
                "reportSummaryForPatient": "肩まわりの左右差を確認します。",
            },
        )

        response = self.client.get(self._detail_url())
        shoulder = self._profile_item(response, "shoulder")

        self.assertEqual(response.status_code, 200)
        self.assertIn("右肩下制", shoulder["text"])
        self.assertIn("肩甲帯", shoulder["check_point"])
        self.assertIn("肩まわり", response.context["posture_profile_summary"])

    def test_own_clinic_patient_precheck_returns_200(self):
        response = self.client.get(self._precheck_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "staff/patients/pre_treatment_check.html",
        )
        self.assertContains(response, "施術前チェック")

    def test_other_clinic_patient_precheck_returns_404(self):
        response = self.client.get(self._precheck_url(self.other_patient))

        self.assertEqual(response.status_code, 404)

    def test_user_without_clinic_cannot_open_precheck(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._precheck_url())

        self.assertEqual(response.status_code, 403)

    def test_today_appointment_is_used_for_precheck_and_recording_links(self):
        start_at = timezone.make_aware(
            datetime.combine(timezone.localdate(), time(hour=12))
        )
        appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            menu="本日の施術",
            status=Appointment.Status.BOOKED,
            created_by=self.user,
        )

        response = self.client.get(self._precheck_url())

        self.assertEqual(response.context["today_appointment"], appointment)
        self.assertContains(response, "本日の施術")
        self.assertContains(
            response,
            reverse("intakes:recording_new", args=[appointment.id]),
        )
        self.assertContains(
            response,
            reverse("treatment_sessions:start", args=[appointment.id]),
        )

    def test_precheck_without_today_appointment_does_not_fail(self):
        response = self.client.get(self._precheck_url())

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["today_appointment"])
        self.assertContains(response, "本日の予約はありません")
        self.assertContains(response, "予約が紐づいていません")
        self.assertContains(
            response,
            reverse(
                "treatment_sessions:start_for_patient",
                args=[self.patient.id],
            ),
        )

    def test_past_appointment_is_not_reused_as_today_appointment(self):
        start_at = timezone.now() - timedelta(days=2)
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            menu="過去の予約",
            status=Appointment.Status.COMPLETED,
            created_by=self.user,
        )

        response = self.client.get(self._precheck_url())

        self.assertIsNone(response.context["today_appointment"])
        self.assertContains(response, "本日の予約はありません")

    def test_precheck_body_profile_uses_confirmed_posture_summary(self):
        PostureAssessment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            status=PostureAssessment.Status.CONFIRMED,
            ai_summary_json={
                "joint_assessments": {
                    "pelvis": {"summary": "AI結果の骨盤所見"}
                }
            },
            confirmed_summary_json={
                "joint_assessments": {
                    "pelvis": {
                        "summary": "確認済みの骨盤前傾傾向",
                        "check_points": ["左右荷重を確認"],
                    }
                }
            },
        )

        response = self.client.get(self._precheck_url())
        pelvis = self._profile_item(response, "pelvis")

        self.assertEqual(response.context["posture_summary_source"], "confirmed")
        self.assertIn("確認済み", pelvis["text"])
        self.assertNotIn("AI結果", pelvis["text"])

    def test_precheck_view_does_not_use_file_path(self):
        source = inspect.getsource(staff_views.staff_pre_treatment_check_view)

        self.assertNotIn(".path", source)


class StaffPostTreatmentSummaryTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="Post Summary Clinic")
        self.other_clinic = Clinic.objects.create(name="Other Post Clinic")
        self.user = user_model.objects.create_user(
            username="post-summary-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.other_user = user_model.objects.create_user(
            username="post-summary-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="post-summary-no-clinic",
            password="test-password",
            role=user_model.Role.PRACTITIONER,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="POST-A-001",
            last_name="高橋",
            first_name="一郎",
            last_name_kana="タカハシ",
            first_name_kana="イチロウ",
            birth_date=date(1988, 4, 10),
            phone="09000000031",
        )
        self.other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="POST-B-001",
            last_name="鈴木",
            first_name="花子",
            last_name_kana="スズキ",
            first_name_kana="ハナコ",
            birth_date=date(1991, 7, 20),
            phone="09000000032",
        )
        start_at = timezone.now()
        self.appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            menu="通院施術",
            status=Appointment.Status.COMPLETED,
            assigned_staff=self.user,
            created_by=self.user,
        )
        self.other_appointment = Appointment.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            status=Appointment.Status.COMPLETED,
            created_by=self.other_user,
        )
        self.session = TreatmentSession.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            status=TreatmentSession.Status.DONE,
            confirmed_summary_json={
                "session_summary": {
                    "overall_summary": "右膝の動作を中心に確認しました",
                },
                "soap": {
                    "S": ["階段で右膝に違和感"],
                    "O": ["屈伸動作を確認"],
                    "A": ["荷重バランスの確認が必要"],
                    "P": ["次回も階段動作を確認"],
                },
                "treatment": {
                    "performed_treatments": ["右膝周囲の筋緊張を確認"],
                },
                "explanation": {
                    "explained_to_patient": ["無理な深い屈伸を避けるよう説明"],
                    "home_care": ["痛みのない範囲で膝の曲げ伸ばし"],
                    "cautions_until_next_visit": ["強い痛みが出た場合は中止"],
                },
                "next_plan": {
                    "items_to_check_next_time": ["階段昇降時の変化"],
                },
            },
            created_by=self.user,
            updated_by=self.user,
        )
        self.note = ClinicalNote.objects.create(
            appointment=self.appointment,
            patient=self.patient,
            treatment_session=self.session,
            soap_json={
                "S": ["階段で右膝が気になる"],
                "O": ["右膝の屈伸を確認"],
                "A": ["右下肢の荷重に左右差の傾向"],
                "P": ["次回も荷重動作を確認"],
            },
            extract_json={
                "chief_complaint": "右膝の違和感",
                "overall_summary": "本日は右膝の荷重動作を中心に確認しました",
                "performed_treatments": ["大腿部と膝周囲への施術"],
                "explained_to_patient": ["日常動作の注意点を説明"],
                "home_care": ["無理のない範囲で大腿部を動かす"],
                "items_to_check_next_time": ["階段動作の変化"],
                "safety_notes": ["強い痛みがある場合は無理をしない"],
            },
            followups_json=[
                {"type": "next_check", "text": "歩行時の変化"},
            ],
            registered_by=self.user,
            updated_by=self.user,
        )
        self.session.clinical_note = self.note
        self.session.save(update_fields=["clinical_note"])
        self.plan = TreatmentPlan.objects.create(
            patient=self.patient,
            appointment=self.appointment,
            clinical_note=self.note,
            title="右膝の負担管理プラン",
            chief_complaint="右膝の違和感",
            visit_guide_type="weekly",
            visit_guide_count=1,
            lifestyle_other_instruction="荷重動作を段階的に確認します。",
            created_by=self.user,
        )
        self.posture = PostureAssessment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            clinical_note=self.note,
            status=PostureAssessment.Status.CONFIRMED,
            confirmed_summary_json={
                "report_summary_for_patient": "膝と骨盤の荷重バランスを確認します。"
            },
            created_by=self.user,
        )
        self.other_note = ClinicalNote.objects.create(
            appointment=self.other_appointment,
            patient=self.other_patient,
            soap_json={},
            extract_json={},
            followups_json=[],
            registered_by=self.other_user,
        )
        self.client.force_login(self.user)

    def _summary_url(self, note=None):
        return reverse(
            "staff:post_treatment_summary",
            args=[(note or self.note).id],
        )

    def _report_url(self, note=None):
        return reverse(
            "staff:patient_aftercare_report",
            args=[(note or self.note).id],
        )

    def test_own_clinic_note_post_summary_returns_200_and_displays_soap(self):
        response = self.client.get(self._summary_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "staff/patients/post_treatment_summary.html",
        )
        self.assertContains(response, "階段で右膝が気になる")
        self.assertContains(response, "右下肢の荷重に左右差の傾向")
        self.assertContains(response, "本日は右膝の荷重動作を中心に確認しました")

    def test_other_clinic_note_post_summary_returns_404(self):
        response = self.client.get(self._summary_url(self.other_note))

        self.assertEqual(response.status_code, 404)

    def test_user_without_clinic_cannot_open_post_summary(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._summary_url())

        self.assertEqual(response.status_code, 403)

    def test_empty_extract_and_followups_do_not_break_post_summary(self):
        self.note.extract_json = {}
        self.note.followups_json = []
        self.note.save(update_fields=["extract_json", "followups_json"])

        response = self.client.get(self._summary_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "施術後サマリー")

    def test_related_plan_posture_and_recording_source_are_displayed(self):
        response = self.client.get(self._summary_url())

        self.assertContains(response, "右膝の負担管理プラン")
        self.assertContains(
            response,
            reverse("treatment_plans:plan_detail", args=[self.plan.id]),
        )
        self.assertContains(response, "膝と骨盤の荷重バランス")
        self.assertContains(
            response,
            reverse("posture_assessments:detail", args=[self.posture.id]),
        )
        self.assertContains(
            response,
            reverse("treatment_sessions:detail", args=[self.session.id]),
        )

    def test_post_summary_view_does_not_use_file_path(self):
        source = inspect.getsource(
            staff_views.staff_post_treatment_summary_view
        )

        self.assertNotIn(".path", source)

    def test_own_clinic_note_aftercare_report_returns_200(self):
        response = self.client.get(self._report_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response,
            "staff/patients/patient_aftercare_report.html",
        )
        self.assertContains(response, "施術後説明レポート")
        self.assertContains(response, "本日は右膝の荷重動作を中心に確認しました")
        self.assertContains(response, "大腿部と膝周囲への施術")

    def test_other_clinic_note_aftercare_report_returns_404(self):
        response = self.client.get(self._report_url(self.other_note))

        self.assertEqual(response.status_code, 404)

    def test_user_without_clinic_cannot_open_aftercare_report(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._report_url())

        self.assertEqual(response.status_code, 403)

    def test_empty_note_json_does_not_break_aftercare_report(self):
        self.note.soap_json = {}
        self.note.extract_json = {}
        self.note.followups_json = []
        self.note.save(
            update_fields=["soap_json", "extract_json", "followups_json"]
        )

        response = self.client.get(self._report_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "施術後説明レポート")

    def test_confirmed_recording_summary_fills_aftercare_report(self):
        self.note.soap_json = {}
        self.note.extract_json = {}
        self.note.followups_json = []
        self.note.save(
            update_fields=["soap_json", "extract_json", "followups_json"]
        )

        response = self.client.get(self._report_url())

        self.assertContains(response, "右膝周囲の筋緊張を確認")
        self.assertContains(response, "痛みのない範囲で膝の曲げ伸ばし")

    def test_aftercare_report_does_not_display_practitioner_only_memo(self):
        self.session.memo = "内部限定メモXYZ"
        self.session.save(update_fields=["memo"])
        self.note.extract_json["findings"] = ["内部評価メモXYZ"]
        self.note.save(update_fields=["extract_json"])

        response = self.client.get(self._report_url())

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "内部限定メモXYZ")
        self.assertNotContains(response, "内部評価メモXYZ")
        self.assertNotContains(response, "施術者向けメモ")

    def test_next_appointment_is_displayed_on_aftercare_report(self):
        future_start = timezone.now() + timedelta(days=3)
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=future_start,
            end_at=future_start + timedelta(hours=1),
            menu="次回施術",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.user,
            created_by=self.user,
        )

        response = self.client.get(self._report_url())

        self.assertContains(response, "次回予約")
        self.assertContains(response, "次回施術")

    def test_aftercare_report_view_does_not_use_file_path(self):
        source = inspect.getsource(
            staff_views.staff_patient_aftercare_report_view
        )

        self.assertNotIn(".path", source)
