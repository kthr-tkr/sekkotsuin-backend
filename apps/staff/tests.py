from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.clinics.models import Clinic
from apps.intakes.models import Intake
from apps.patients.models import Patient
from apps.posture_assessments.models import PostureAssessment


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
