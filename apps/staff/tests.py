from datetime import date, datetime, time, timedelta
import inspect
import json
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.base import Message
from django.template.loader import render_to_string
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai_usage.models import AiUsageLog, ClinicAiPlan
from apps.appointments.models import Appointment
from apps.clinical_notes.models import ClinicalNote
from apps.clinics.models import (
    Clinic,
    ClinicSettings,
    PatientShareToken,
    SalesRecord,
    StaffLeave,
    StaffShift,
    TreatmentMenu,
)
from apps.intakes import views as intake_views
from apps.intakes.models import Intake, InterviewRecording
from apps.patients.models import Patient
from apps.posture_assessments import views as posture_views
from apps.posture_assessments.models import PostureAssessment
from apps.staff import views as staff_views
from apps.treatment_plans import views as treatment_plan_views
from apps.treatment_plans.models import TreatmentPlan
from apps.treatment_sessions import views as treatment_session_views
from apps.treatment_sessions.models import TreatmentSession


class MajorWorkflowCopyTests(SimpleTestCase):
    template_paths = (
        "templates/staff/dashboard.html",
        "templates/staff/ai_usage_dashboard.html",
        "templates/staff/clinic_settings.html",
        "templates/staff/kpi_dashboard.html",
        "templates/staff/sales_record_form.html",
        "templates/staff/sales_record_list.html",
        "templates/staff/staff_create.html",
        "templates/staff/staff_list.html",
        "templates/staff/staff_leave_form.html",
        "templates/staff/staff_leave_list.html",
        "templates/staff/staff_member_form.html",
        "templates/staff/staff_shift_form.html",
        "templates/staff/staff_shift_month.html",
        "templates/staff/treatment_menu_form.html",
        "templates/staff/treatment_menu_list.html",
        "templates/staff/partials/recording_start_cards.html",
        "templates/staff/patients/search.html",
        "templates/staff/patients/detail.html",
        "templates/staff/patients/pre_treatment_check.html",
        "templates/intakes/staff/recording_new.html",
        "templates/intakes/staff/recording_detail.html",
        "templates/treatment_sessions/session_detail.html",
        "templates/treatment_sessions/session_confirm.html",
        "templates/staff/clinical_notes/detail.html",
        "templates/staff/patients/post_treatment_summary.html",
        "templates/staff/patients/patient_aftercare_report.html",
        "templates/patients/shared_aftercare_report.html",
        "templates/patients/shared_page_unavailable.html",
    )

    def _template_text(self):
        return "\n".join(
            (Path(settings.BASE_DIR) / relative_path).read_text(
                encoding="utf-8"
            )
            for relative_path in self.template_paths
        )

    def test_major_templates_do_not_use_forbidden_copy(self):
        source = self._template_text()

        for forbidden in (
            "AI下書き",
            "AI診断",
            "自動診断",
            "確定診断",
            "治ります",
            "完治します",
            "必ず改善します",
        ):
            self.assertNotIn(forbidden, source)

    def test_major_templates_use_standard_action_copy(self):
        source = self._template_text()

        for expected in (
            "施術前チェックを開く",
            "初診録音を開始",
            "通院施術録音を開始",
            "カルテ案を確認・修正",
            "確認内容を保存",
            "カルテへ登録",
            "施術後サマリーを見る",
            "患者向け説明レポートを開く",
            "印刷する",
            "PDF保存案内",
        ):
            self.assertIn(expected, source)

    def test_staff_sidebar_contains_main_menu_and_scroll_layout(self):
        source = (
            Path(settings.BASE_DIR) / "templates/staff/_layout.html"
        ).read_text(encoding="utf-8")

        for expected in (
            "ホーム",
            "予約管理",
            "患者様一覧",
            "担当者一覧",
            "シフト管理",
            "休暇管理",
            "KPI",
            "売上管理",
            "AI利用量",
            "院設定",
            "料金設定",
            "選択画面に戻る",
            "ログアウト",
        ):
            self.assertIn(expected, source)

        self.assertNotIn('<span class="label-text">操作マニュアル</span>', source)
        self.assertNotIn("{% url 'staff:manual' %}", source)
        self.assertIn("flex-direction:column", source)
        self.assertIn("overflow-y:auto", source)
        self.assertIn("min-height:0", source)
        self.assertIn("flex-shrink:0", source)
        self.assertNotIn("{% url 'staff:intake' %}", source)
        self.assertNotIn('<span class="label-text">問診</span>', source)

        legacy_source = (
            Path(settings.BASE_DIR) / "templates/staff/base.html"
        ).read_text(encoding="utf-8")
        self.assertNotIn('<span class="dot"></span> 問診', legacy_source)
        self.assertNotIn('<span class="dot"></span> 操作マニュアル', legacy_source)


class ProductionReadinessSmokeTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="Production Smoke Clinic")
        self.other_clinic = Clinic.objects.create(name="Other Smoke Clinic")
        self.user = user_model.objects.create_user(
            username="production-smoke-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.other_user = user_model.objects.create_user(
            username="production-smoke-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="production-smoke-no-clinic",
            password="test-password",
            role=user_model.Role.PRACTITIONER,
        )
        self.patient = self._patient(
            clinic=self.clinic,
            card_no="SMOKE-A-001",
            last_name="本番前",
            first_name="確認",
            phone="09000000071",
        )
        self.other_patient = self._patient(
            clinic=self.other_clinic,
            card_no="SMOKE-B-001",
            last_name="他院",
            first_name="確認",
            phone="09000000072",
        )
        now = timezone.now()
        self.appointment = self._appointment(
            clinic=self.clinic,
            patient=self.patient,
            user=self.user,
            start_at=now,
        )
        self.other_appointment = self._appointment(
            clinic=self.other_clinic,
            patient=self.other_patient,
            user=self.other_user,
            start_at=now,
        )
        self.intake = Intake.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            submitted_at=now,
            chief_complaint="右膝の違和感",
        )
        self.other_intake = Intake.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            submitted_at=now,
            chief_complaint="他院データ",
        )
        self.summary = {
            "session_summary": {
                "overall_summary": "右膝の荷重動作を中心に確認しました",
            },
            "soap": {
                "S": ["階段で右膝に違和感"],
                "O": ["屈伸動作を確認"],
                "A": ["荷重バランスは継続確認が必要"],
                "P": ["次回も階段動作を確認"],
            },
            "treatment": {
                "performed_treatments": ["右膝周囲の状態を確認"],
            },
            "explanation": {
                "explained_to_patient": ["無理のない動作範囲を説明"],
                "home_care": ["痛みのない範囲で曲げ伸ばし"],
                "cautions_until_next_visit": ["強い痛みがある場合は中止"],
            },
            "next_plan": {
                "items_to_check_next_time": ["階段動作の変化"],
            },
        }
        self.recording = InterviewRecording.objects.create(
            clinic=self.clinic,
            appointment=self.appointment,
            patient=self.patient,
            intake=self.intake,
            created_by=self.user,
            status=InterviewRecording.Status.DONE,
            transcript_text="階段動作について確認しました。",
            summary_json=self.summary,
            confirmed_summary_json=self.summary,
            summary_status=InterviewRecording.SummaryStatus.CONFIRMED,
        )
        self.other_recording = InterviewRecording.objects.create(
            clinic=self.other_clinic,
            appointment=self.other_appointment,
            patient=self.other_patient,
            intake=self.other_intake,
            created_by=self.other_user,
            status=InterviewRecording.Status.DONE,
            transcript_text="他院の録音です。",
            summary_json=self.summary,
            confirmed_summary_json=self.summary,
            summary_status=InterviewRecording.SummaryStatus.CONFIRMED,
        )
        self.session = TreatmentSession.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            intake=self.intake,
            status=TreatmentSession.Status.DONE,
            transcript_text="本日の施術内容を確認しました。",
            summary_json=self.summary,
            confirmed_summary_json=self.summary,
            summary_status="confirmed",
            created_by=self.user,
            updated_by=self.user,
        )
        self.other_session = TreatmentSession.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            intake=self.other_intake,
            status=TreatmentSession.Status.DONE,
            transcript_text="他院の施術録音です。",
            summary_json=self.summary,
            confirmed_summary_json=self.summary,
            summary_status="confirmed",
            created_by=self.other_user,
            updated_by=self.other_user,
        )
        self.note = self._note(
            appointment=self.appointment,
            patient=self.patient,
            user=self.user,
            session=self.session,
        )
        self.other_note = self._note(
            appointment=self.other_appointment,
            patient=self.other_patient,
            user=self.other_user,
            session=self.other_session,
        )
        self.session.clinical_note = self.note
        self.session.save(update_fields=["clinical_note"])
        self.other_session.clinical_note = self.other_note
        self.other_session.save(update_fields=["clinical_note"])
        posture_summary = {
            "important_points": ["膝と骨盤の荷重バランスを確認"],
            "overall_summary": "全体バランスは継続して確認します。",
            "patient_explanation": "無理のない範囲で変化を確認します。",
            "report_summary_for_patient": "膝と骨盤の位置関係を確認しました。",
            "posture_findings": {"knee": "膝の向きは継続確認が必要です。"},
        }
        self.posture = PostureAssessment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            clinical_note=self.note,
            status=PostureAssessment.Status.CONFIRMED,
            confirmed_summary_json=posture_summary,
            created_by=self.user,
        )
        self.other_posture = PostureAssessment.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            clinical_note=self.other_note,
            status=PostureAssessment.Status.CONFIRMED,
            confirmed_summary_json=posture_summary,
            created_by=self.other_user,
        )
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
        self.other_plan = TreatmentPlan.objects.create(
            patient=self.other_patient,
            appointment=self.other_appointment,
            clinical_note=self.other_note,
            title="他院の施術計画",
            chief_complaint="他院データ",
            created_by=self.other_user,
        )
        self.client.force_login(self.user)

    @staticmethod
    def _patient(*, clinic, card_no, last_name, first_name, phone):
        return Patient.objects.create(
            clinic=clinic,
            card_no=card_no,
            last_name=last_name,
            first_name=first_name,
            last_name_kana="スモーク",
            first_name_kana="テスト",
            birth_date=date(1990, 1, 1),
            phone=phone,
        )

    @staticmethod
    def _appointment(*, clinic, patient, user, start_at):
        return Appointment.objects.create(
            clinic=clinic,
            patient=patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            menu="通院施術",
            status=Appointment.Status.COMPLETED,
            assigned_staff=user,
            created_by=user,
        )

    @staticmethod
    def _note(*, appointment, patient, user, session):
        return ClinicalNote.objects.create(
            appointment=appointment,
            patient=patient,
            treatment_session=session,
            soap_json={
                "S": ["階段で右膝が気になる"],
                "O": ["右膝の屈伸を確認"],
                "A": ["荷重バランスの傾向を確認"],
                "P": ["次回も動作を確認"],
            },
            extract_json={
                "chief_complaint": "右膝の違和感",
                "overall_summary": "本日は右膝を中心に確認しました",
                "performed_treatments": ["膝周囲への施術"],
                "home_care": ["無理のない範囲で曲げ伸ばし"],
                "items_to_check_next_time": ["階段動作の変化"],
            },
            followups_json=[],
            registered_by=user,
            updated_by=user,
        )

    def _major_urls(self):
        return {
            "dashboard": reverse("staff:dashboard"),
            "appointments": reverse("staff:appointments"),
            "ai_usage_dashboard": reverse("staff:ai_usage_dashboard"),
            "clinic_settings": reverse("staff:clinic_settings"),
            "kpi_dashboard": reverse("staff:kpi_dashboard"),
            "treatment_menu_list": reverse("staff:treatment_menu_list"),
            "patient_list": reverse("staff:patient_search"),
            "patient_detail": reverse(
                "staff:patient_detail",
                args=[self.patient.id],
            ),
            "sales_record_list": reverse("staff:sales_record_list"),
            "staff_list": reverse("staff:staff_list"),
            "staff_leave_list": reverse("staff:staff_leave_list"),
            "staff_shift_month": reverse("staff:staff_shift_month"),
            "patient_timeline": (
                reverse("staff:patient_detail", args=[self.patient.id])
                + "?tab=timeline"
            ),
            "pre_treatment_check": reverse(
                "staff:pre_treatment_check",
                args=[self.patient.id],
            ),
            "clinical_note_detail": reverse(
                "staff:clinical_note_detail",
                args=[self.note.id],
            ),
            "post_treatment_summary": reverse(
                "staff:post_treatment_summary",
                args=[self.note.id],
            ),
            "patient_aftercare_report": reverse(
                "staff:patient_aftercare_report",
                args=[self.note.id],
            ),
            "intake_detail": reverse(
                "staff:intake_detail",
                args=[self.intake.id],
            ),
            "interview_recording_detail": reverse(
                "intakes:recording_detail",
                args=[self.recording.id],
            ),
            "treatment_session_detail": reverse(
                "treatment_sessions:detail",
                args=[self.session.id],
            ),
            "treatment_session_confirm": reverse(
                "treatment_sessions:session_confirm",
                args=[self.session.id],
            ),
            "posture_detail": reverse(
                "posture_assessments:detail",
                args=[self.posture.id],
            ),
            "posture_report": reverse(
                "posture_assessments:assessment_report",
                args=[self.posture.id],
            ),
            "treatment_plan_detail": reverse(
                "treatment_plans:plan_detail",
                args=[self.plan.id],
            ),
        }

    def test_major_staff_workflow_pages_render_without_reverse_errors(self):
        for label, url in self._major_urls().items():
            with self.subTest(page=label, url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)

    def test_major_staff_management_pages_use_shared_page_header(self):
        urls = self._major_urls()
        shared_header_pages = (
            "dashboard",
            "appointments",
            "ai_usage_dashboard",
            "clinic_settings",
            "kpi_dashboard",
            "treatment_menu_list",
            "patient_list",
            "patient_detail",
            "sales_record_list",
            "staff_list",
            "staff_leave_list",
            "staff_shift_month",
            "pre_treatment_check",
            "post_treatment_summary",
            "patient_aftercare_report",
        )

        for label in shared_header_pages:
            with self.subTest(page=label):
                response = self.client.get(urls[label])
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "data-staff-page-header")
                self.assertContains(response, "staff-page-header__title")

    def test_shared_page_header_template_and_layout_define_common_structure(self):
        include_source = Path(
            "templates/staff/includes/page_header.html"
        ).read_text(encoding="utf-8")
        layout_source = Path("templates/staff/_layout.html").read_text(
            encoding="utf-8"
        )

        for expected in (
            "staff-page-header__main",
            "staff-page-header__eyebrow",
            "staff-page-header__title",
            "staff-page-header__description",
            "staff-page-header__actions",
        ):
            self.assertIn(expected, include_source)
            self.assertIn(expected, layout_source)

        self.assertIn("staff-toast-container", layout_source)
        self.assertIn("position:fixed", layout_source)

    def test_major_navigation_copy_is_rendered(self):
        patient_response = self.client.get(
            reverse("staff:patient_detail", args=[self.patient.id])
        )
        self.assertContains(patient_response, "施術前チェックを開く")
        self.assertContains(patient_response, "治療履歴")

        recording_response = self.client.get(
            reverse("intakes:recording_detail", args=[self.recording.id])
        )
        self.assertContains(recording_response, "カルテ案を確認・修正")
        self.assertContains(recording_response, "患者詳細へ戻る")

        session_response = self.client.get(
            reverse("treatment_sessions:detail", args=[self.session.id])
        )
        self.assertContains(session_response, "カルテ案を確認・修正")
        self.assertContains(session_response, "患者詳細へ戻る")

        note_response = self.client.get(
            reverse("staff:clinical_note_detail", args=[self.note.id])
        )
        self.assertContains(note_response, "施術後サマリーを見る")
        self.assertContains(note_response, "患者向け説明レポートを開く")

        summary_response = self.client.get(
            reverse("staff:post_treatment_summary", args=[self.note.id])
        )
        self.assertContains(summary_response, "患者向け説明レポートを開く")
        self.assertContains(summary_response, "カルテ詳細へ戻る")
        self.assertContains(summary_response, "印刷する")

        report_response = self.client.get(
            reverse("staff:patient_aftercare_report", args=[self.note.id])
        )
        self.assertContains(report_response, "カルテ詳細へ戻る")
        self.assertContains(report_response, "患者詳細へ戻る")
        self.assertContains(report_response, "印刷する")
        self.assertContains(report_response, "PDF保存案内")

    def test_legacy_intake_list_redirects_to_appointments_with_guidance(self):
        response = self.client.get(reverse("staff:intake"))

        self.assertRedirects(response, reverse("staff:appointments"))

        followed_response = self.client.get(reverse("staff:intake"), follow=True)
        self.assertEqual(followed_response.status_code, 200)
        self.assertContains(
            followed_response,
            "問診は予約または患者詳細から作成してください。",
        )

    def test_unimplemented_manual_menu_is_hidden_and_redirects_to_dashboard(self):
        dashboard_response = self.client.get(reverse("staff:dashboard"))
        self.assertEqual(dashboard_response.status_code, 200)
        self.assertNotContains(dashboard_response, "操作マニュアル")
        self.assertNotContains(dashboard_response, reverse("staff:manual"))

        response = self.client.get(reverse("staff:manual"))
        self.assertRedirects(response, reverse("staff:dashboard"))

    def test_intake_detail_keeps_initial_recording_route(self):
        response = self.client.get(
            reverse("staff:intake_detail", args=[self.intake.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "初診録音を開始")
        self.assertContains(
            response,
            reverse("intakes:recording_new", args=[self.appointment.id]),
        )

    def test_other_clinic_major_object_pages_return_404(self):
        urls = {
            "patient_detail": reverse(
                "staff:patient_detail",
                args=[self.other_patient.id],
            ),
            "pre_treatment_check": reverse(
                "staff:pre_treatment_check",
                args=[self.other_patient.id],
            ),
            "clinical_note_detail": reverse(
                "staff:clinical_note_detail",
                args=[self.other_note.id],
            ),
            "post_treatment_summary": reverse(
                "staff:post_treatment_summary",
                args=[self.other_note.id],
            ),
            "patient_aftercare_report": reverse(
                "staff:patient_aftercare_report",
                args=[self.other_note.id],
            ),
            "intake_detail": reverse(
                "staff:intake_detail",
                args=[self.other_intake.id],
            ),
            "interview_recording_detail": reverse(
                "intakes:recording_detail",
                args=[self.other_recording.id],
            ),
            "treatment_session_detail": reverse(
                "treatment_sessions:detail",
                args=[self.other_session.id],
            ),
            "posture_detail": reverse(
                "posture_assessments:detail",
                args=[self.other_posture.id],
            ),
            "treatment_plan_detail": reverse(
                "treatment_plans:plan_detail",
                args=[self.other_plan.id],
            ),
        }
        for label, url in urls.items():
            with self.subTest(page=label, url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 404)

    def test_user_without_clinic_gets_403_on_major_pages(self):
        self.client.force_login(self.no_clinic_user)

        for label, url in self._major_urls().items():
            with self.subTest(page=label, url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 403)

        intake_list_response = self.client.get(reverse("staff:intake"))
        self.assertEqual(intake_list_response.status_code, 403)

    def test_major_render_views_do_not_use_filefield_path(self):
        views = (
            staff_views.staff_dashboard_view,
            staff_views.staff_patient_detail_view,
            staff_views.staff_pre_treatment_check_view,
            staff_views.staff_clinical_note_detail_view,
            staff_views.staff_post_treatment_summary_view,
            staff_views.staff_patient_aftercare_report_view,
            staff_views.staff_intake_list_view,
            staff_views.staff_intake_detail_view,
            intake_views.recording_detail,
            treatment_session_views.treatment_session_detail_view,
            treatment_session_views.treatment_session_confirm_view,
            posture_views.posture_detail_view,
            posture_views.posture_assessment_report_view,
            treatment_plan_views.plan_detail_view,
        )

        for view in views:
            with self.subTest(view=view.__name__):
                self.assertNotIn(".path", inspect.getsource(view))


class StaffTodayDashboardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="Dashboard Clinic")
        self.other_clinic = Clinic.objects.create(name="Other Dashboard Clinic")
        self.user = user_model.objects.create_user(
            username="dashboard-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.other_user = user_model.objects.create_user(
            username="dashboard-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="dashboard-no-clinic",
            password="test-password",
            role=user_model.Role.PRACTITIONER,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="DASH-A-001",
            last_name="田中",
            first_name="一郎",
            last_name_kana="タナカ",
            first_name_kana="イチロウ",
            birth_date=date(1989, 3, 2),
            phone="09000000041",
        )
        self.other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="DASH-B-001",
            last_name="他院",
            first_name="患者",
            last_name_kana="タイイン",
            first_name_kana="カンジャ",
            birth_date=date(1990, 5, 4),
            phone="09000000042",
        )
        self.client.force_login(self.user)

    @staticmethod
    def _at_today(hour):
        return timezone.make_aware(
            datetime.combine(
                timezone.localdate(),
                time(hour=hour),
            )
        )

    def _appointment(
        self,
        *,
        patient=None,
        clinic=None,
        user=None,
        hour=10,
        menu="本日施術",
        days=0,
    ):
        start_at = self._at_today(hour) + timedelta(days=days)
        return Appointment.objects.create(
            clinic=clinic or self.clinic,
            patient=patient or self.patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            menu=menu,
            status=Appointment.Status.BOOKED,
            created_by=user or self.user,
        )

    def _dashboard_url(self):
        return reverse("staff:dashboard")

    def test_dashboard_displays_only_own_clinic_today_data(self):
        own_appointment = self._appointment(menu="OWN_TODAY_APPOINTMENT")
        self._appointment(
            patient=self.other_patient,
            clinic=self.other_clinic,
            user=self.other_user,
            hour=11,
            menu="OTHER_CLINIC_APPOINTMENT",
        )
        other_recording_appointment = self._appointment(
            patient=self.other_patient,
            clinic=self.other_clinic,
            user=self.other_user,
            hour=12,
            menu="OTHER_RECORDING_APPOINTMENT",
        )
        InterviewRecording.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=other_recording_appointment,
            summary_json={"overall_summary": "OTHER_CLINIC_RECORDING"},
            created_by=self.other_user,
        )

        response = self.client.get(self._dashboard_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "OWN_TODAY_APPOINTMENT")
        self.assertNotContains(response, "OTHER_CLINIC_APPOINTMENT")
        self.assertNotContains(response, "OTHER_RECORDING_APPOINTMENT")
        self.assertNotContains(response, "OTHER_CLINIC_RECORDING")
        self.assertEqual(
            response.context["today_appointment_items"][0]["appointment"],
            own_appointment,
        )

    def test_dashboard_shows_today_appointment_but_not_past_appointment(self):
        self._appointment(menu="TODAY_ONLY_APPOINTMENT")
        self._appointment(
            hour=9,
            menu="PAST_APPOINTMENT_SHOULD_NOT_SHOW",
            days=-2,
        )

        response = self.client.get(self._dashboard_url())

        self.assertEqual(response.context["total_appointment_count"], 1)
        self.assertContains(response, "TODAY_ONLY_APPOINTMENT")
        self.assertNotContains(response, "PAST_APPOINTMENT_SHOULD_NOT_SHOW")

    def test_unconfirmed_summary_is_in_confirmation_waiting(self):
        pending_appointment = self._appointment(
            hour=12,
            menu="確認待ち予約",
        )
        pending = InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=pending_appointment,
            summary_json={"overall_summary": "確認が必要なカルテ案"},
            confirmed_summary_json=None,
            created_by=self.user,
        )
        confirmed_appointment = self._appointment(
            hour=13,
            menu="確認済み予約",
        )
        confirmed = InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=confirmed_appointment,
            summary_json={"overall_summary": "確認済み元データ"},
            confirmed_summary_json={"overall_summary": "確認済みカルテ案"},
            summary_status=InterviewRecording.SummaryStatus.CONFIRMED,
            created_by=self.user,
        )

        response = self.client.get(self._dashboard_url())
        waiting_ids = {
            item["url"]
            for item in response.context["confirmation_waiting_items"]
        }

        self.assertIn(
            reverse("intakes:recording_confirm", args=[pending.id]),
            waiting_ids,
        )
        self.assertNotIn(
            reverse("intakes:recording_confirm", args=[confirmed.id]),
            waiting_ids,
        )
        self.assertEqual(response.context["confirmation_waiting_count"], 1)

    def test_recording_needing_summary_is_in_attention_list(self):
        appointment = self._appointment(
            hour=14,
            menu="録音要確認予約",
        )
        recording = InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=appointment,
            status=InterviewRecording.Status.DONE,
            transcript_text="文字起こし完了済み",
            summary_json={},
            created_by=self.user,
        )

        response = self.client.get(self._dashboard_url())
        attention_urls = {
            item["url"]
            for item in response.context["recording_attention_items"]
        }

        self.assertIn(
            reverse("intakes:recording_detail", args=[recording.id]),
            attention_urls,
        )
        self.assertContains(response, "要確認")
        self.assertContains(response, "要約結果を確認")

    def test_today_clinical_note_displays_aftercare_report_link(self):
        appointment = self._appointment(
            hour=15,
            menu="レポート対象施術",
        )
        note = ClinicalNote.objects.create(
            appointment=appointment,
            patient=self.patient,
            soap_json={"S": ["本日の状態"]},
            registered_by=self.user,
        )

        response = self.client.get(self._dashboard_url())

        self.assertEqual(response.context["today_note_count"], 1)
        self.assertContains(
            response,
            reverse("staff:patient_aftercare_report", args=[note.id]),
        )
        self.assertContains(response, "患者向け説明レポートを開く")

    def test_user_without_clinic_cannot_open_dashboard(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._dashboard_url())

        self.assertEqual(response.status_code, 403)

    def test_dashboard_empty_states_explain_current_state(self):
        response = self.client.get(self._dashboard_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "確認が必要なカルテ案はありません")
        self.assertContains(response, "確認が必要な録音データはありません")
        self.assertContains(response, "本日の予約はありません")

    def test_dashboard_uses_action_oriented_today_task_copy(self):
        response = self.client.get(self._dashboard_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "AIカルテ案の確認が必要")
        self.assertContains(response, "録音データの確認が必要")
        self.assertContains(response, "AIカルテ案")
        self.assertContains(response, "録音確認")
        self.assertNotContains(response, "録音処理中・要確認")

    def test_dashboard_today_tasks_do_not_use_file_path(self):
        source = inspect.getsource(staff_views.build_dashboard_today_tasks)

        self.assertNotIn(".path", source)


class StaffKpiDashboardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="KPI Clinic")
        self.other_clinic = Clinic.objects.create(name="Other KPI Clinic")
        self.user = user_model.objects.create_user(
            username="kpi-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.other_user = user_model.objects.create_user(
            username="kpi-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="kpi-no-clinic",
            password="test-password",
            role=user_model.Role.PRACTITIONER,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="KPI-A-001",
            last_name="自院",
            first_name="患者",
            last_name_kana="ジイン",
            first_name_kana="カンジャ",
            birth_date=date(1990, 1, 1),
            phone="09000000081",
        )
        self.other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="KPI-B-001",
            last_name="他院",
            first_name="患者",
            last_name_kana="タイイン",
            first_name_kana="カンジャ",
            birth_date=date(1991, 1, 1),
            phone="09000000082",
        )
        self.appointment = self._appointment(
            clinic=self.clinic,
            patient=self.patient,
            user=self.user,
            hour=10,
            menu="自院本日予約",
        )
        self.other_appointment = self._appointment(
            clinic=self.other_clinic,
            patient=self.other_patient,
            user=self.other_user,
            hour=11,
            menu="他院本日予約",
        )
        self.pending_recording = InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            status=InterviewRecording.Status.DONE,
            transcript_text="文字起こし済み",
            summary_json={"overall_summary": "確認待ちカルテ案"},
            confirmed_summary_json=None,
            created_by=self.user,
        )
        self.error_recording = InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            status=InterviewRecording.Status.FAILED,
            error_message="録音処理を確認してください",
            created_by=self.user,
        )
        InterviewRecording.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            status=InterviewRecording.Status.DONE,
            summary_json={"overall_summary": "OTHER_KPI_WAITING"},
            confirmed_summary_json=None,
            created_by=self.other_user,
        )
        self.note = ClinicalNote.objects.create(
            appointment=self.appointment,
            patient=self.patient,
            soap_json={"S": ["本日の状態"]},
            extract_json={"overall_summary": "自院カルテ"},
            registered_by=self.user,
        )
        self.menu = TreatmentMenu.objects.create(
            clinic=self.clinic,
            name="KPI全身調整",
            price=5000,
            duration_minutes=30,
        )
        self.other_menu = TreatmentMenu.objects.create(
            clinic=self.other_clinic,
            name="OTHER_KPI_MENU",
            price=99999,
            duration_minutes=60,
        )
        self.client.force_login(self.user)

    @staticmethod
    def _today_at(hour):
        return timezone.make_aware(
            datetime.combine(timezone.localdate(), time(hour=hour))
        )

    def _appointment(self, *, clinic, patient, user, hour, menu):
        start_at = self._today_at(hour)
        return Appointment.objects.create(
            clinic=clinic,
            patient=patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            menu=menu,
            status=Appointment.Status.COMPLETED,
            assigned_staff=user,
            created_by=user,
        )

    def _url(self):
        return reverse("staff:kpi_dashboard")

    def _sales_record(
        self,
        *,
        clinic=None,
        patient=None,
        appointment=None,
        menu="__default__",
        staff=None,
        amount=5000,
        status=SalesRecord.Status.PAID,
        payment_method=SalesRecord.PaymentMethod.CASH,
        treatment_date=None,
    ):
        clinic = clinic or self.clinic
        patient = patient or self.patient
        appointment = appointment or self.appointment
        menu = self.menu if menu == "__default__" else menu
        staff = staff if staff is not None else self.user
        return SalesRecord.objects.create(
            clinic=clinic,
            patient=patient,
            appointment=appointment,
            treatment_menu=menu,
            staff=staff,
            treatment_date=treatment_date or timezone.localdate(),
            amount=amount,
            status=status,
            payment_method=payment_method,
        )

    def test_kpi_counts_only_own_clinic_data(self):
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        today_values = {
            card["label"]: card["value"]
            for card in response.context["today_cards"]
        }
        self.assertEqual(today_values["本日の予約"], 1)
        self.assertEqual(today_values["カルテ登録"], 1)
        self.assertEqual(today_values["カルテ案確認待ち"], 1)
        self.assertContains(response, "自院 患者")
        self.assertNotContains(response, "他院 患者")
        self.assertNotContains(response, "OTHER_KPI_WAITING")

    def test_kpi_displays_recording_error_and_confirmation_waiting(self):
        response = self.client.get(self._url())

        self.assertEqual(
            response.context["attention_counts"]["confirmation_waiting"],
            1,
        )
        self.assertEqual(
            response.context["attention_counts"]["recording_errors"],
            1,
        )
        self.assertContains(response, "カルテ案確認待ち")
        self.assertContains(response, "エラーあり")
        self.assertContains(
            response,
            reverse(
                "intakes:recording_detail",
                args=[self.pending_recording.id],
            ),
        )

    def test_kpi_sales_summary_counts_paid_only_and_excludes_other_clinic(self):
        self._sales_record(amount=5000, status=SalesRecord.Status.PAID)
        self._sales_record(amount=3000, status=SalesRecord.Status.UNPAID)
        self._sales_record(amount=2000, status=SalesRecord.Status.CANCELED)
        self._sales_record(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            menu=self.other_menu,
            staff=self.other_user,
            amount=99999,
            status=SalesRecord.Status.PAID,
        )

        response = self.client.get(self._url())
        summary = response.context["sales_summary"]

        self.assertEqual(summary["today_sales"], 5000)
        self.assertEqual(summary["month_sales"], 5000)
        self.assertEqual(summary["seven_day_sales"], 5000)
        self.assertEqual(summary["today_paid_count"], 1)
        self.assertEqual(summary["unpaid_count"], 1)
        self.assertEqual(summary["canceled_count"], 1)
        self.assertContains(response, "¥5,000")
        self.assertNotContains(response, "99999")
        self.assertNotContains(response, "OTHER_KPI_MENU")

    def test_kpi_sales_breakdowns_are_displayed(self):
        self._sales_record(
            amount=5000,
            payment_method=SalesRecord.PaymentMethod.CASH,
        )
        self._sales_record(
            amount=3000,
            menu=None,
            payment_method=SalesRecord.PaymentMethod.CARD,
        )

        response = self.client.get(self._url())

        self.assertContains(response, "KPI全身調整")
        self.assertContains(response, "メニュー未設定")
        self.assertContains(response, "現金")
        self.assertContains(response, "カード")
        self.assertContains(response, "kpi-staff")
        self.assertContains(response, "¥8,000")

    def test_kpi_unpaid_sales_are_in_attention_list(self):
        unpaid = self._sales_record(
            amount=3000,
            status=SalesRecord.Status.UNPAID,
        )

        response = self.client.get(self._url())

        self.assertEqual(
            response.context["attention_counts"]["unpaid_sales"],
            1,
        )
        self.assertContains(response, "未会計")
        self.assertContains(response, "¥3,000")
        self.assertContains(
            response,
            reverse("staff:sales_record_update", args=[unpaid.id]),
        )

    def test_kpi_sales_links_are_rendered(self):
        response = self.client.get(self._url())

        self.assertContains(response, reverse("staff:sales_record_list"))
        self.assertContains(response, reverse("staff:sales_record_create"))

    def test_kpi_displays_booking_source_trends_for_own_clinic_only(self):
        Appointment.objects.filter(pk=self.appointment.pk).update(
            booking_source=Appointment.BookingSource.LINE,
        )
        Appointment.objects.filter(pk=self.other_appointment.pk).update(
            booking_source=Appointment.BookingSource.GOOGLE,
        )

        response = self.client.get(self._url())
        month_rows = {
            row["source"]: row["count"]
            for row in response.context["booking_source_trends"]["month_rows"]
        }

        self.assertContains(response, "予約流入元")
        self.assertContains(response, "LINE")
        self.assertEqual(month_rows[Appointment.BookingSource.LINE], 1)
        self.assertEqual(month_rows[Appointment.BookingSource.GOOGLE], 0)

    def test_kpi_patient_trends_are_clinic_scoped_and_grouped(self):
        Intake.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            chief_complaint="デスクワーク後の腰痛",
            payload={"job": "デスクワーク", "visit_type": "followup"},
        )
        young_patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="KPI-A-002",
            last_name="傾向",
            first_name="集計",
            last_name_kana="ケイコウ",
            first_name_kana="シュウケイ",
            birth_date=date(timezone.localdate().year - 25, 1, 1),
            phone="09000000083",
        )
        Intake.objects.create(
            clinic=self.clinic,
            patient=young_patient,
            chief_complaint="サッカー時の膝の違和感",
            payload={"sport": "サッカー"},
        )
        Intake.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            chief_complaint="OTHER肩相談",
            payload={"sport": "野球"},
        )

        response = self.client.get(self._url())
        trends = response.context["patient_trends"]
        complaints = {
            row["label"]: row["count"]
            for row in trends["complaint_ranking"]
        }
        ages = {row["label"]: row["count"] for row in trends["age_groups"]}

        self.assertContains(response, "患者傾向分析")
        self.assertContains(response, "痛み・相談内容ランキング")
        self.assertEqual(complaints["腰"], 1)
        self.assertEqual(complaints["膝"], 1)
        self.assertNotIn("肩", complaints)
        self.assertEqual(ages["20代"], 1)
        self.assertEqual(ages["30代"], 1)
        self.assertContains(response, "スポーツ由来")
        self.assertNotContains(response, "OTHER肩相談")

    def test_kpi_patient_trends_handle_unknown_age_and_empty_data(self):
        self.assertEqual(
            staff_views._patient_age_group(None, timezone.localdate()),
            "不明",
        )
        empty_clinic = Clinic.objects.create(name="傾向データなし院")
        trends = staff_views.build_patient_trend_context(empty_clinic)

        self.assertEqual(trends["patient_count"], 0)
        self.assertFalse(trends["has_complaint_data"])

    def test_kpi_template_avoids_diagnostic_ranking_wording(self):
        template = Path("templates/staff/kpi_dashboard.html").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("診断ランキング", template)
        self.assertNotIn("疾患ランキング", template)

    def test_user_without_clinic_cannot_open_kpi(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)

    def test_kpi_builder_does_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views.build_staff_kpi_context)
            + inspect.getsource(staff_views.build_patient_trend_context)
            + inspect.getsource(staff_views.staff_kpi_dashboard_view)
        )

        self.assertNotIn(".path", source)


class StaffAiUsageDashboardTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="AI Usage Clinic")
        self.other_clinic = Clinic.objects.create(name="Other AI Usage Clinic")
        self.user = user_model.objects.create_user(
            username="ai-usage-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
        )
        self.other_user = user_model.objects.create_user(
            username="ai-usage-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.ADMIN,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="ai-usage-no-clinic",
            password="test-password",
            role=user_model.Role.ADMIN,
        )
        self.patient = self._patient(
            clinic=self.clinic,
            card_no="AIUSE-A-001",
            last_name="利用",
            first_name="患者",
            phone="09000000091",
        )
        self.other_patient = self._patient(
            clinic=self.other_clinic,
            card_no="AIUSE-B-001",
            last_name="他院利用",
            first_name="患者",
            phone="09000000092",
        )
        now = timezone.now()
        self.appointment = self._appointment(
            clinic=self.clinic,
            patient=self.patient,
            user=self.user,
            start_at=now,
        )
        self.other_appointment = self._appointment(
            clinic=self.other_clinic,
            patient=self.other_patient,
            user=self.other_user,
            start_at=now,
        )
        self.recording = InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            created_by=self.user,
        )
        self.session = TreatmentSession.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            status=TreatmentSession.Status.DONE,
            created_by=self.user,
            updated_by=self.user,
        )
        self.posture = PostureAssessment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            status=PostureAssessment.Status.ANALYZED,
            created_by=self.user,
        )
        self.plan = ClinicAiPlan.objects.create(
            clinic=self.clinic,
            plan_name="CareFrow 100",
            monthly_base_fee=12000,
            included_minutes=100,
            overage_unit_minutes=20,
            overage_unit_price=1000,
            hard_limit_minutes=160,
            is_ai_enabled=True,
        )
        self.initial_stt = self._usage_log(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            recording=self.recording,
            user=self.user,
            usage_type=AiUsageLog.UsageType.STT,
            billing_minutes=30,
            cost=120,
            input_tokens=100,
            output_tokens=20,
            model_name="gpt-4o-mini-transcribe",
            metadata={"source": "interview_recording"},
        )
        self.session_stt = self._usage_log(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            user=self.user,
            usage_type=AiUsageLog.UsageType.STT,
            billing_minutes=15,
            cost=80,
            input_tokens=80,
            output_tokens=10,
            model_name="gpt-4o-mini-transcribe",
            metadata={
                "source": "treatment_session_chunk",
                "treatment_session_id": self.session.id,
            },
        )
        self._usage_log(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            user=self.user,
            usage_type=AiUsageLog.UsageType.SUMMARY,
            billing_minutes=0,
            cost=40,
            input_tokens=200,
            output_tokens=70,
            model_name="gpt-4.1-mini",
            metadata={
                "source": "treatment_session",
                "treatment_session_id": self.session.id,
            },
        )
        self._usage_log(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            user=self.user,
            usage_type=AiUsageLog.UsageType.POSTURE,
            billing_minutes=0,
            cost=60,
            input_tokens=300,
            output_tokens=100,
            model_name="gpt-4.1-mini",
            metadata={
                "source": "posture_assessment",
                "assessment_id": self.posture.id,
            },
        )
        self._usage_log(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            user=self.other_user,
            usage_type=AiUsageLog.UsageType.STT,
            billing_minutes=900,
            cost=9999,
            input_tokens=9999,
            output_tokens=9999,
            model_name="OTHER_CLINIC_MODEL",
            metadata={"source": "interview_recording"},
        )
        self.client.force_login(self.user)

    @staticmethod
    def _patient(*, clinic, card_no, last_name, first_name, phone):
        return Patient.objects.create(
            clinic=clinic,
            card_no=card_no,
            last_name=last_name,
            first_name=first_name,
            last_name_kana="テスト",
            first_name_kana="カンジャ",
            birth_date=date(1990, 1, 1),
            phone=phone,
        )

    @staticmethod
    def _appointment(*, clinic, patient, user, start_at):
        return Appointment.objects.create(
            clinic=clinic,
            patient=patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            menu="AI利用確認",
            status=Appointment.Status.COMPLETED,
            assigned_staff=user,
            created_by=user,
        )

    @staticmethod
    def _usage_log(
        *,
        clinic,
        patient,
        appointment,
        user,
        usage_type,
        billing_minutes,
        cost,
        input_tokens,
        output_tokens,
        model_name,
        metadata,
        recording=None,
    ):
        return AiUsageLog.objects.create(
            clinic=clinic,
            patient=patient,
            appointment=appointment,
            recording=recording,
            usage_type=usage_type,
            status=AiUsageLog.Status.SUCCESS,
            model_name=model_name,
            billing_minutes=billing_minutes,
            audio_duration_sec=billing_minutes * 60,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost_yen=cost,
            metadata=metadata,
            created_by=user,
        )

    def _url(self):
        return reverse("staff:ai_usage_dashboard")

    def test_ai_usage_aggregates_only_own_clinic_logs(self):
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        monthly = response.context["monthly_usage"]
        self.assertEqual(monthly["recording_minutes"], 45)
        self.assertEqual(monthly["transcription_count"], 2)
        self.assertEqual(monthly["summary_count"], 1)
        self.assertEqual(monthly["posture_count"], 1)
        self.assertEqual(monthly["estimated_cost_yen"], 300)
        self.assertEqual(monthly["usage_percent"], 45)
        self.assertContains(response, "利用 患者")
        self.assertNotContains(response, "他院利用 患者")
        self.assertNotContains(response, "OTHER_CLINIC_MODEL")

    def test_ai_usage_displays_plan_and_usage_rate(self):
        response = self.client.get(self._url())

        self.assertContains(response, "CareFrow 100")
        self.assertContains(response, "月間使用率")
        self.assertContains(response, "45%")
        self.assertContains(response, "55分")
        self.assertContains(response, "実際の請求額とは異なる場合があります")

    def test_ai_usage_displays_standard_plan_policy(self):
        self.plan.plan_name = "standard"
        self.plan.save(update_fields=["plan_name", "updated_at"])

        response = self.client.get(self._url())

        self.assertContains(response, "スタンダード")
        self.assertContains(response, "月3000分まで利用できます")
        self.assertContains(response, "1日5名程度のAI録音に対応")
        self.assertContains(response, "3000分")
        self.assertContains(response, "1000分 / 5000円")
        self.assertContains(response, "30000円")
        self.assertEqual(response.context["monthly_usage"]["included_minutes"], 3000)

    def test_ai_usage_displays_pro_plan_policy(self):
        self.plan.plan_name = "pro"
        self.plan.save(update_fields=["plan_name", "updated_at"])

        response = self.client.get(self._url())

        self.assertContains(response, "プロ")
        self.assertContains(response, "月7000分まで利用できます")
        self.assertContains(response, "複数スタッフ・高頻度運用")
        self.assertContains(response, "優先サポート")
        self.assertContains(response, "7000分")
        self.assertContains(response, "50000円")
        self.assertEqual(response.context["monthly_usage"]["included_minutes"], 7000)

    def test_ai_usage_displays_campaign_plan_policy(self):
        self.plan.plan_name = "campaign_standard"
        self.plan.save(update_fields=["plan_name", "updated_at"])

        response = self.client.get(self._url())

        self.assertContains(response, "先行導入キャンペーン")
        self.assertContains(response, "3か月間19,800円")
        self.assertContains(response, "4か月目以降29,800円")
        self.assertContains(response, "常設ライトプランではありません")
        self.assertTrue(response.context["plan"]["campaign_applied"])

    def test_ai_usage_without_plan_does_not_fail(self):
        self.plan.delete()

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertIsNone(response.context["plan"])
        self.assertContains(response, "AI料金プランはまだ設定されていません")
        self.assertContains(response, "プラン未設定")

    def test_recent_usage_logs_and_related_links_are_displayed(self):
        response = self.client.get(self._url())

        self.assertContains(response, "gpt-4o-mini-transcribe")
        self.assertContains(
            response,
            reverse(
                "intakes:recording_detail",
                args=[self.recording.id],
            ),
        )
        self.assertContains(
            response,
            reverse(
                "treatment_sessions:detail",
                args=[self.session.id],
            ),
        )
        self.assertContains(
            response,
            reverse(
                "posture_assessments:detail",
                args=[self.posture.id],
            ),
        )

    def test_dashboard_links_to_ai_usage_screen(self):
        response = self.client.get(reverse("staff:dashboard"))

        self.assertContains(response, "AI利用量を見る")
        self.assertContains(response, self._url())

    def test_user_without_clinic_cannot_open_ai_usage(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)

    def test_ai_usage_view_does_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views.build_ai_usage_dashboard_context)
            + inspect.getsource(staff_views.staff_ai_usage_dashboard_view)
        )

        self.assertNotIn(".path", source)


class StaffClinicSettingsTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="設定前院名")
        self.other_clinic = Clinic.objects.create(name="他院設定")
        self.user = user_model.objects.create_user(
            username="clinic-settings-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
        )
        self.other_user = user_model.objects.create_user(
            username="clinic-settings-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.ADMIN,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="clinic-settings-no-clinic",
            password="test-password",
            role=user_model.Role.ADMIN,
        )
        self.other_settings = ClinicSettings.objects.create(
            clinic=self.other_clinic,
            display_name="他院表示名",
            phone="099-999-9999",
            primary_color="#999999",
        )
        self.client.force_login(self.user)

    def _url(self):
        return reverse("staff:clinic_settings")

    def _valid_data(self, **overrides):
        data = {
            "clinic_name": "CareFrow中央院",
            "display_name": "CareFrow 中央",
            "phone": "03-1234-5678",
            "address": "東京都中央区1-2-3",
            "booking_description": "ご予約時間の5分前にお越しください。",
            "business_start_time": "09:00",
            "business_end_time": "20:00",
            "break_start_time": "13:00",
            "break_end_time": "15:00",
            "appointment_interval_minutes": "30",
            "closed_weekdays": ["sun", "wed"],
            "primary_color": "#1D4ED8",
            "secondary_color": "#0F172A",
            "accent_color": "#16A34A",
        }
        data.update(overrides)
        return data

    def test_own_clinic_settings_page_returns_200(self):
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/clinic_settings.html")
        self.assertEqual(response.context["clinic"], self.clinic)
        self.assertTrue(
            ClinicSettings.objects.filter(clinic=self.clinic).exists()
        )
        self.assertContains(response, "院設定を保存")

    def test_clinic_settings_can_be_saved(self):
        response = self.client.post(self._url(), self._valid_data())

        self.assertRedirects(response, self._url())
        self.clinic.refresh_from_db()
        settings = ClinicSettings.objects.get(clinic=self.clinic)
        self.assertEqual(self.clinic.name, "CareFrow中央院")
        self.assertEqual(settings.display_name, "CareFrow 中央")
        self.assertEqual(settings.appointment_interval_minutes, 30)
        self.assertEqual(settings.closed_weekdays, ["sun", "wed"])
        self.assertEqual(settings.primary_color, "#1D4ED8")

    def test_business_start_must_be_before_end(self):
        response = self.client.post(
            self._url(),
            self._valid_data(
                business_start_time="20:00",
                business_end_time="09:00",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "business_end_time",
            response.context["form"].errors,
        )

    def test_break_time_must_be_inside_business_hours(self):
        response = self.client.post(
            self._url(),
            self._valid_data(
                break_start_time="08:00",
                break_end_time="10:00",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "break_end_time",
            response.context["form"].errors,
        )

    def test_invalid_color_code_is_rejected(self):
        response = self.client.post(
            self._url(),
            self._valid_data(primary_color="blue"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("primary_color", response.context["form"].errors)

    def test_invalid_appointment_interval_is_rejected(self):
        response = self.client.post(
            self._url(),
            self._valid_data(appointment_interval_minutes="25"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(
            "appointment_interval_minutes",
            response.context["form"].errors,
        )

    def test_post_cannot_modify_other_clinic_settings(self):
        data = self._valid_data()
        data["clinic"] = str(self.other_clinic.id)

        response = self.client.post(self._url(), data)

        self.assertRedirects(response, self._url())
        self.other_settings.refresh_from_db()
        self.assertEqual(self.other_settings.display_name, "他院表示名")
        self.assertEqual(self.other_settings.phone, "099-999-9999")
        self.assertEqual(self.other_settings.primary_color, "#999999")

    def test_user_without_clinic_cannot_open_settings(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)

    def test_saved_schedule_is_exposed_to_appointment_calendar(self):
        settings = ClinicSettings.objects.create(
            clinic=self.clinic,
            business_start_time=time(10, 0),
            business_end_time=time(18, 0),
            appointment_interval_minutes=15,
        )

        response = self.client.get(reverse("staff:appointments"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["clinic_settings"], settings)
        self.assertEqual(response.context["calendar_slot_min"], "10:00:00")
        self.assertEqual(response.context["calendar_slot_max"], "18:00:00")
        self.assertEqual(
            response.context["calendar_slot_duration"],
            "00:15:00",
        )

    def test_staff_layout_exposes_clinic_theme_variables(self):
        ClinicSettings.objects.create(
            clinic=self.clinic,
            primary_color="#123456",
            secondary_color="#234567",
            accent_color="#345678",
        )

        response = self.client.get(self._url())

        self.assertContains(response, "--clinic-theme-color:#123456")
        self.assertContains(
            response,
            "--clinic-primary-color:var(--clinic-theme-color)",
        )
        self.assertContains(response, "--clinic-secondary-color:#234567")
        self.assertContains(response, "--clinic-accent-color:#345678")
        self.assertContains(response, "--clinic-sidebar-start:")
        self.assertContains(response, "--clinic-hero-start:")

    def test_staff_layout_uses_default_theme_for_missing_settings(self):
        response = self.client.get(reverse("staff:dashboard"))

        self.assertContains(response, "--clinic-theme-color:#2563EB")

    def test_staff_layout_uses_default_theme_for_invalid_stored_color(self):
        clinic_settings = ClinicSettings.objects.create(clinic=self.clinic)
        ClinicSettings.objects.filter(pk=clinic_settings.pk).update(
            primary_color="invalid"
        )

        response = self.client.get(reverse("staff:dashboard"))

        self.assertContains(response, "--clinic-theme-color:#2563EB")
        self.assertNotContains(response, "--clinic-theme-color:invalid")

    def test_settings_explains_where_theme_color_is_applied(self):
        response = self.client.get(self._url())

        self.assertContains(response, "管理画面のテーマカラー")
        self.assertContains(
            response,
            "管理画面のヒーロー、サイドバー、主要ボタンの色味に反映されます。",
        )
        self.assertContains(response, "CareFrow Blue")
        self.assertContains(response, 'type="color"')

    def test_clinic_settings_displays_public_booking_urls(self):
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "院別予約URL")
        self.assertContains(response, "HP用予約URL")
        self.assertContains(response, "LINE用予約URL")
        self.assertContains(response, "Google用予約URL")
        self.assertContains(response, "QR用予約URL")
        self.assertContains(response, f"/b/{self.clinic.booking_slug}/?source=hp")

    def test_shared_header_and_sidebar_use_theme_variables(self):
        layout_source = Path("templates/staff/_layout.html").read_text(
            encoding="utf-8"
        )
        header_source = Path(
            "templates/staff/includes/page_header.html"
        ).read_text(encoding="utf-8")

        self.assertIn("staff-page-header--themed", header_source)
        self.assertIn("var(--clinic-hero-start)", layout_source)
        self.assertIn("var(--clinic-sidebar-start)", layout_source)
        self.assertIn("var(--clinic-sidebar-active-bg)", layout_source)

    def test_clinic_settings_view_does_not_use_file_path(self):
        source = inspect.getsource(
            staff_views.staff_clinic_settings_view
        )

        self.assertNotIn(".path", source)


class StaffMemberManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.User = user_model
        self.clinic = Clinic.objects.create(name="担当者管理院")
        self.other_clinic = Clinic.objects.create(name="他院担当者")
        self.user = user_model.objects.create_user(
            username="member-admin",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
            last_name="管理",
            first_name="太郎",
        )
        self.staff_user = user_model.objects.create_user(
            username="member-practitioner",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="担当",
            first_name="花子",
            email="practitioner@example.com",
        )
        self.inactive_staff = user_model.objects.create_user(
            username="member-inactive",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="退職",
            first_name="一郎",
            is_active=False,
        )
        self.other_staff = user_model.objects.create_user(
            username="member-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="他院",
            first_name="スタッフ",
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="member-no-clinic",
            password="test-password",
            role=user_model.Role.ADMIN,
        )
        self.patient = self._patient(
            clinic=self.clinic,
            card_no="MEM-A-001",
            last_name="担当",
            first_name="患者",
            phone="09000002001",
        )
        self.other_patient = self._patient(
            clinic=self.other_clinic,
            card_no="MEM-B-001",
            last_name="他院",
            first_name="患者",
            phone="09000002002",
        )
        now = timezone.now()
        self.appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=now,
            end_at=now + timedelta(hours=1),
            menu="担当確認",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.staff_user,
            created_by=self.user,
        )
        self.other_appointment = Appointment.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            start_at=now,
            end_at=now + timedelta(hours=1),
            menu="他院担当確認",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.other_staff,
            created_by=self.other_staff,
        )
        self.menu = TreatmentMenu.objects.create(
            clinic=self.clinic,
            name="担当者売上メニュー",
            price=5000,
            duration_minutes=30,
        )
        self.other_menu = TreatmentMenu.objects.create(
            clinic=self.other_clinic,
            name="他院担当メニュー",
            price=99999,
            duration_minutes=30,
        )
        self.client.force_login(self.user)

    @staticmethod
    def _patient(*, clinic, card_no, last_name, first_name, phone):
        return Patient.objects.create(
            clinic=clinic,
            card_no=card_no,
            last_name=last_name,
            first_name=first_name,
            last_name_kana="スタッフ",
            first_name_kana="テスト",
            birth_date=date(1990, 1, 1),
            phone=phone,
        )

    def _list_url(self):
        return reverse("staff:staff_list")

    def _create_url(self):
        return reverse("staff:staff_create")

    def _update_url(self, user):
        return reverse("staff:staff_member_update", args=[user.id])

    def _toggle_url(self, user):
        return reverse("staff:staff_member_toggle", args=[user.id])

    def _delete_url(self, user):
        return reverse("staff:staff_member_delete", args=[user.id])

    def _valid_create_data(self, **overrides):
        data = {
            "last_name": "新規",
            "first_name": "担当",
            "email": "new-member@example.com",
            "password1": "StrongPass123!",
            "password2": "StrongPass123!",
            "role": self.User.Role.PRACTITIONER,
        }
        data.update(overrides)
        return data

    def _valid_edit_data(self, **overrides):
        data = {
            "last_name": "更新",
            "first_name": "担当",
            "email": "updated-practitioner@example.com",
            "role": self.User.Role.RECEPTION,
            "is_active": "on",
        }
        data.update(overrides)
        return data

    def _sales_record(self, *, staff, clinic=None, patient=None, menu=None, amount=5000):
        return SalesRecord.objects.create(
            clinic=clinic or self.clinic,
            patient=patient or self.patient,
            treatment_menu=menu or self.menu,
            staff=staff,
            treatment_date=timezone.localdate(),
            amount=amount,
            payment_method=SalesRecord.PaymentMethod.CASH,
            status=SalesRecord.Status.PAID,
        )

    def test_own_staff_can_open_staff_member_list(self):
        response = self.client.get(self._list_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/staff_list.html")
        self.assertContains(response, "スタッフ一覧・担当者管理")
        self.assertContains(response, "担当 花子")
        self.assertContains(response, "退職 一郎")
        self.assertNotContains(response, "member-practitioner")
        self.assertNotContains(response, "member-other")

    def test_user_without_clinic_cannot_open_staff_member_list(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._list_url())

        self.assertEqual(response.status_code, 403)

    def test_staff_member_can_be_created_with_role(self):
        response = self.client.post(
            self._create_url(),
            self._valid_create_data(),
        )

        self.assertRedirects(response, self._list_url())
        created = self.User.objects.get(email="new-member@example.com")
        self.assertEqual(created.username, "new-member@example.com")
        self.assertEqual(created.clinic, self.clinic)
        self.assertEqual(created.role, self.User.Role.PRACTITIONER)
        self.assertFalse(created.is_staff)

    def test_new_staff_internal_username_is_safely_uniquified(self):
        first = self.client.post(self._create_url(), self._valid_create_data())
        second = self.client.post(
            self._create_url(),
            self._valid_create_data(last_name="別", first_name="担当"),
        )

        self.assertEqual(first.status_code, 302)
        self.assertEqual(second.status_code, 302)
        usernames = list(
            self.User.objects.filter(email="new-member@example.com")
            .order_by("id")
            .values_list("username", flat=True)
        )
        self.assertEqual(len(usernames), 2)
        self.assertEqual(len(set(usernames)), 2)

    def test_staff_create_template_uses_role_field(self):
        response = self.client.get(self._create_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "権限/ロール")
        self.assertNotContains(response, "スタッフ権限を付与する")

    def test_own_staff_edit_page_can_be_opened(self):
        response = self.client.get(self._update_url(self.staff_user))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/staff_member_form.html")
        self.assertContains(response, "スタッフ編集")
        self.assertContains(response, "担当")
        self.assertNotContains(response, "member-practitioner")

    def test_staff_member_can_be_updated(self):
        original_username = self.staff_user.username
        response = self.client.post(
            self._update_url(self.staff_user),
            self._valid_edit_data(),
        )

        self.assertRedirects(response, self._list_url())
        self.staff_user.refresh_from_db()
        self.assertEqual(self.staff_user.last_name, "更新")
        self.assertEqual(self.staff_user.first_name, "担当")
        self.assertEqual(self.staff_user.email, "updated-practitioner@example.com")
        self.assertEqual(self.staff_user.role, self.User.Role.RECEPTION)
        self.assertFalse(self.staff_user.is_staff)
        self.assertEqual(self.staff_user.username, original_username)

    def test_staff_names_are_used_in_appointment_and_sales_views(self):
        appointment_response = self.client.get(reverse("staff:appointments"))
        sales_response = self.client.get(reverse("staff:sales_record_create"))

        self.assertContains(appointment_response, "担当 花子")
        self.assertContains(sales_response, "担当 花子")
        self.assertNotContains(sales_response, ">member-practitioner<")

    def test_other_clinic_staff_edit_returns_404(self):
        response = self.client.get(self._update_url(self.other_staff))

        self.assertEqual(response.status_code, 404)

    def test_staff_member_can_be_disabled_and_reenabled(self):
        response = self.client.post(self._toggle_url(self.staff_user))

        self.assertRedirects(response, self._list_url())
        self.staff_user.refresh_from_db()
        self.assertFalse(self.staff_user.is_active)

        response = self.client.post(self._toggle_url(self.staff_user))

        self.assertRedirects(response, self._list_url())
        self.staff_user.refresh_from_db()
        self.assertTrue(self.staff_user.is_active)

    def test_staff_member_can_be_marked_deleted_without_physical_delete(self):
        response = self.client.post(self._delete_url(self.staff_user))

        self.assertRedirects(response, self._list_url())
        self.staff_user.refresh_from_db()
        self.assertFalse(self.staff_user.is_active)
        self.assertTrue(self.User.objects.filter(pk=self.staff_user.pk).exists())

        list_response = self.client.get(self._list_url())
        self.assertContains(list_response, "担当 花子")
        self.assertContains(list_response, "削除済み")

    def test_deleted_staff_is_excluded_from_new_assignment_candidates(self):
        target_day = timezone.localdate() + timedelta(days=3)
        ClinicSettings.objects.create(
            clinic=self.clinic,
            business_start_time=time(9, 0),
            business_end_time=time(18, 0),
        )
        StaffShift.objects.create(
            clinic=self.clinic,
            staff=self.staff_user,
            date=target_day,
            status=StaffShift.Status.WORKING,
            start_time=time(9, 0),
            end_time=time(18, 0),
        )
        self.client.post(self._delete_url(self.staff_user))

        slot_result = staff_views.build_appointment_available_slots(
            clinic=self.clinic,
            target_date=target_day,
            duration_minutes=30,
            limit=None,
        )
        slot_staff_ids = {slot["staff_id"] for slot in slot_result["slots"]}
        self.assertNotIn(self.staff_user.id, slot_staff_ids)

        sales_response = self.client.get(reverse("staff:sales_record_create"))
        sales_staff_ids = set(
            sales_response.context["form"].fields["staff"].queryset
            .values_list("id", flat=True)
        )
        self.assertNotIn(self.staff_user.id, sales_staff_ids)

        shift_response = self.client.get(reverse("staff:staff_shift_create"))
        shift_staff_ids = set(
            shift_response.context["form"].fields["staff"].queryset
            .values_list("id", flat=True)
        )
        self.assertNotIn(self.staff_user.id, shift_staff_ids)

    def test_deleted_staff_name_remains_on_existing_sales_history(self):
        self._sales_record(staff=self.staff_user, amount=8800)
        self.client.post(self._delete_url(self.staff_user))

        response = self.client.get(reverse("staff:sales_record_list"))

        self.assertContains(response, "担当 花子")
        self.assertContains(response, "¥8,800")

    def test_self_staff_member_delete_is_rejected(self):
        response = self.client.post(self._delete_url(self.user))

        self.assertRedirects(response, self._list_url())
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)

    def test_other_clinic_staff_member_delete_returns_404(self):
        response = self.client.post(self._delete_url(self.other_staff))

        self.assertEqual(response.status_code, 404)
        self.other_staff.refresh_from_db()
        self.assertTrue(self.other_staff.is_active)

    def test_month_sales_total_uses_only_own_clinic_sales(self):
        self._sales_record(staff=self.staff_user, amount=50000)
        self._sales_record(
            staff=self.other_staff,
            clinic=self.other_clinic,
            patient=self.other_patient,
            menu=self.other_menu,
            amount=999999,
        )

        response = self.client.get(self._list_url())

        self.assertContains(response, "¥50,000")
        self.assertNotContains(response, "999999")
        self.assertNotContains(response, "他院担当メニュー")

    def test_inactive_staff_remains_visible_with_past_sales(self):
        self._sales_record(staff=self.inactive_staff, amount=12000)

        response = self.client.get(self._list_url())

        self.assertContains(response, "退職 一郎")
        self.assertContains(response, "無効")
        self.assertContains(response, "¥12,000")

    def test_staff_member_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views.staff_list)
            + inspect.getsource(staff_views.staff_create)
            + inspect.getsource(staff_views.staff_member_update_view)
            + inspect.getsource(staff_views.staff_member_toggle_view)
            + inspect.getsource(staff_views.staff_member_delete_view)
        )

        self.assertNotIn(".path", source)


class StaffMessageUxTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="通知テスト院")
        self.user = user_model.objects.create_user(
            username="message-admin",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
        )
        self.member = user_model.objects.create_user(
            username="message-member",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="通知",
            first_name="担当",
        )

    def _remove_auth_without_flushing_messages(self):
        session = self.client.session
        for key in ("_auth_user_id", "_auth_user_backend", "_auth_user_hash"):
            session.pop(key, None)
        session.save()

    def test_staff_layout_renders_success_and_warning_as_toasts(self):
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("staff:staff_member_toggle", args=[self.member.id]),
            follow=True,
        )
        self.assertContains(response, "staff-toast-container")
        self.assertContains(response, "スタッフを無効化しました。")

        request = RequestFactory().get("/staff/staff/")
        request.user = self.user
        html = render_to_string(
            "staff/_layout.html",
            {"messages": [Message(messages.WARNING, "入力内容を確認してください。")]},
            request=request,
        )
        self.assertIn("staff-toast warning", html)
        self.assertIn("data-toast-close", html)

    def test_login_get_discards_management_messages(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("staff:staff_member_toggle", args=[self.member.id])
        )
        self._remove_auth_without_flushing_messages()

        response = self.client.get(reverse("staff:login"))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "スタッフを無効化しました。")
        self.assertNotContains(response, "data-login-messages")

    def test_failed_login_shows_only_login_error(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("staff:staff_member_toggle", args=[self.member.id])
        )
        self._remove_auth_without_flushing_messages()

        response = self.client.post(
            reverse("staff:login"),
            {"username": "missing", "password": "wrong"},
        )

        self.assertContains(response, "IDまたはパスワードが正しくありません。")
        self.assertNotContains(response, "スタッフを無効化しました。")
        self.assertContains(response, "data-login-messages")

    def test_logout_clears_management_messages(self):
        self.client.force_login(self.user)
        self.client.post(
            reverse("staff:staff_member_toggle", args=[self.member.id])
        )

        response = self.client.post(reverse("staff:logout"), follow=True)

        self.assertContains(response, "ログアウトしました。")
        self.assertNotContains(response, "スタッフを無効化しました。")

    def test_layout_has_fixed_toast_container_not_content_alert_stack(self):
        source = Path("templates/staff/_layout.html").read_text(encoding="utf-8")
        self.assertIn("staff-toast-container", source)
        self.assertIn("position:fixed", source)
        self.assertNotIn('<div class="messages">', source)


class StaffShiftManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.User = user_model
        self.clinic = Clinic.objects.create(name="シフト管理院")
        self.other_clinic = Clinic.objects.create(name="他院シフト")
        self.user = user_model.objects.create_user(
            username="shift-admin",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
            last_name="管理",
            first_name="太郎",
        )
        self.staff_user = user_model.objects.create_user(
            username="shift-practitioner",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="勤務",
            first_name="花子",
        )
        self.inactive_staff = user_model.objects.create_user(
            username="shift-inactive",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="休止",
            first_name="一郎",
            is_active=False,
        )
        self.other_staff = user_model.objects.create_user(
            username="shift-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="他院",
            first_name="勤務",
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="shift-no-clinic",
            password="test-password",
            role=user_model.Role.ADMIN,
        )
        ClinicSettings.objects.create(
            clinic=self.clinic,
            business_start_time=time(10, 0),
            business_end_time=time(19, 0),
            break_start_time=time(14, 0),
            break_end_time=time(15, 0),
        )
        self.shift_date = date(2026, 6, 16)
        self.other_shift = StaffShift.objects.create(
            clinic=self.other_clinic,
            staff=self.other_staff,
            date=self.shift_date,
            status=StaffShift.Status.WORKING,
            start_time=time(9, 0),
            end_time=time(18, 0),
        )
        self.client.force_login(self.user)

    def _month_url(self, **params):
        url = reverse("staff:staff_shift_month")
        query = {
            "year": "2026",
            "month": "6",
        }
        query.update({key: str(value) for key, value in params.items()})
        return url + "?" + "&".join(f"{key}={value}" for key, value in query.items())

    def _create_url(self):
        return reverse("staff:staff_shift_create")

    def _update_url(self, shift):
        return reverse("staff:staff_shift_update", args=[shift.id])

    def _generate_url(self):
        return reverse("staff:staff_shift_generate_month")

    def _valid_data(self, **overrides):
        data = {
            "staff": str(self.staff_user.id),
            "date": self.shift_date.isoformat(),
            "status": StaffShift.Status.WORKING,
            "start_time": "10:00",
            "end_time": "19:00",
            "break_start": "14:00",
            "break_end": "15:00",
            "memo": "通常勤務",
        }
        data.update(overrides)
        return data

    def test_own_staff_can_open_shift_month(self):
        StaffShift.objects.create(
            clinic=self.clinic,
            staff=self.staff_user,
            date=self.shift_date,
            status=StaffShift.Status.WORKING,
            start_time=time(10, 0),
            end_time=time(19, 0),
            break_start=time(14, 0),
            break_end=time(15, 0),
        )

        response = self.client.get(self._month_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/staff_shift_month.html")
        self.assertContains(response, "スタッフシフト管理")
        self.assertContains(response, "勤務 花子")
        self.assertContains(response, "10:00〜19:00")
        self.assertNotContains(response, "shift-other")

    def test_user_without_clinic_cannot_open_shift_month(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._month_url())

        self.assertEqual(response.status_code, 403)

    def test_other_clinic_shift_is_not_displayed(self):
        response = self.client.get(self._month_url())

        self.assertNotContains(response, "他院 勤務")
        self.assertNotContains(response, "09:00〜18:00")

    def test_shift_can_be_created(self):
        response = self.client.post(self._create_url(), self._valid_data())

        self.assertEqual(response.status_code, 302)
        shift = StaffShift.objects.get(clinic=self.clinic, staff=self.staff_user)
        self.assertEqual(shift.date, self.shift_date)
        self.assertEqual(shift.start_time, time(10, 0))
        self.assertEqual(shift.end_time, time(19, 0))
        self.assertEqual(shift.status, StaffShift.Status.WORKING)

    def test_shift_can_be_updated(self):
        shift = StaffShift.objects.create(
            clinic=self.clinic,
            staff=self.staff_user,
            date=self.shift_date,
            status=StaffShift.Status.WORKING,
            start_time=time(10, 0),
            end_time=time(19, 0),
        )

        response = self.client.post(
            self._update_url(shift),
            self._valid_data(
                status=StaffShift.Status.HALF_DAY,
                start_time="10:00",
                end_time="14:00",
                break_start="",
                break_end="",
                memo="午前中心",
            ),
        )

        self.assertEqual(response.status_code, 302)
        shift.refresh_from_db()
        self.assertEqual(shift.status, StaffShift.Status.HALF_DAY)
        self.assertEqual(shift.end_time, time(14, 0))
        self.assertEqual(shift.memo, "午前中心")

    def test_other_clinic_shift_update_returns_404(self):
        response = self.client.get(self._update_url(self.other_shift))

        self.assertEqual(response.status_code, 404)

    def test_other_clinic_staff_cannot_be_selected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(staff=str(self.other_staff.id)),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("staff", response.context["form"].errors)
        self.assertFalse(StaffShift.objects.filter(clinic=self.clinic).exists())

    def test_invalid_time_order_is_rejected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(start_time="18:00", end_time="10:00"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("end_time", response.context["form"].errors)

    def test_break_outside_working_hours_is_rejected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(break_start="09:00", break_end="09:30"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("break_end", response.context["form"].errors)

    def test_duplicate_staff_date_is_rejected(self):
        StaffShift.objects.create(
            clinic=self.clinic,
            staff=self.staff_user,
            date=self.shift_date,
            status=StaffShift.Status.WORKING,
            start_time=time(10, 0),
            end_time=time(19, 0),
        )

        response = self.client.post(self._create_url(), self._valid_data())

        self.assertEqual(response.status_code, 200)
        self.assertIn("date", response.context["form"].errors)

    def test_clinic_settings_are_used_for_create_initial_values(self):
        response = self.client.get(
            self._create_url()
            + f"?staff={self.staff_user.id}&date={self.shift_date.isoformat()}"
        )

        self.assertEqual(response.status_code, 200)
        form = response.context["form"]
        self.assertEqual(form.initial["start_time"], time(10, 0))
        self.assertEqual(form.initial["end_time"], time(19, 0))
        self.assertEqual(form.initial["break_start"], time(14, 0))
        self.assertEqual(form.initial["break_end"], time(15, 0))
        self.assertEqual(form.initial["staff"], self.staff_user)

    def test_closed_weekday_uses_off_initial_values(self):
        clinic_settings = ClinicSettings.objects.get(clinic=self.clinic)
        clinic_settings.closed_weekdays = ["tue"]
        clinic_settings.save(update_fields=["closed_weekdays"])

        response = self.client.get(
            self._create_url() + "?date=2026-06-16"
        )
        form = response.context["form"]

        self.assertEqual(form.initial["status"], StaffShift.Status.OFF)
        self.assertIsNone(form.initial["start_time"])
        self.assertIsNone(form.initial["end_time"])

    def test_generate_month_uses_clinic_settings_and_preserves_existing(self):
        clinic_settings = ClinicSettings.objects.get(clinic=self.clinic)
        clinic_settings.closed_weekdays = ["sun"]
        clinic_settings.save(update_fields=["closed_weekdays"])
        existing = StaffShift.objects.create(
            clinic=self.clinic,
            staff=self.staff_user,
            date=date(2026, 6, 1),
            status=StaffShift.Status.HALF_DAY,
            start_time=time(10, 0),
            end_time=time(14, 0),
        )

        response = self.client.post(
            self._generate_url(),
            {"year": "2026", "month": "6"},
        )

        self.assertEqual(response.status_code, 302)
        existing.refresh_from_db()
        self.assertEqual(existing.status, StaffShift.Status.HALF_DAY)
        business_day = StaffShift.objects.get(
            clinic=self.clinic,
            staff=self.staff_user,
            date=date(2026, 6, 2),
        )
        closed_day = StaffShift.objects.get(
            clinic=self.clinic,
            staff=self.staff_user,
            date=date(2026, 6, 7),
        )
        self.assertEqual(business_day.status, StaffShift.Status.WORKING)
        self.assertEqual(business_day.start_time, time(10, 0))
        self.assertEqual(business_day.end_time, time(19, 0))
        self.assertEqual(closed_day.status, StaffShift.Status.OFF)
        self.assertIsNone(closed_day.start_time)
        self.assertFalse(
            StaffShift.objects.filter(
                clinic=self.other_clinic,
                staff=self.other_staff,
            ).exclude(pk=self.other_shift.pk).exists()
        )

    def test_generate_month_requires_post_and_clinic(self):
        self.assertEqual(self.client.get(self._generate_url()).status_code, 405)

        self.client.force_login(self.no_clinic_user)
        response = self.client.post(
            self._generate_url(),
            {"year": "2026", "month": "6"},
        )
        self.assertEqual(response.status_code, 403)

    def test_inactive_staff_with_existing_shift_is_displayed_and_editable(self):
        shift = StaffShift.objects.create(
            clinic=self.clinic,
            staff=self.inactive_staff,
            date=self.shift_date,
            status=StaffShift.Status.OFF,
        )

        month_response = self.client.get(self._month_url())
        self.assertContains(month_response, "休止 一郎")
        self.assertContains(month_response, "無効")

        edit_response = self.client.get(self._update_url(shift))
        self.assertEqual(edit_response.status_code, 200)
        staff_ids = list(edit_response.context["form"].fields["staff"].queryset.values_list("id", flat=True))
        self.assertIn(self.inactive_staff.id, staff_ids)

    def test_staff_shift_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views.staff_shift_month_view)
            + inspect.getsource(staff_views.staff_shift_create_view)
            + inspect.getsource(staff_views.staff_shift_update_view)
            + inspect.getsource(staff_views.staff_shift_generate_month_view)
        )

        self.assertNotIn(".path", source)


class StaffLeaveManagementTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.User = user_model
        self.clinic = Clinic.objects.create(name="休暇管理院")
        self.other_clinic = Clinic.objects.create(name="他院休暇")
        self.user = user_model.objects.create_user(
            username="leave-admin",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
            last_name="管理",
            first_name="太郎",
        )
        self.staff_user = user_model.objects.create_user(
            username="leave-practitioner",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="休暇",
            first_name="花子",
        )
        self.inactive_staff = user_model.objects.create_user(
            username="leave-inactive",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="休止",
            first_name="一郎",
            is_active=False,
        )
        self.other_staff = user_model.objects.create_user(
            username="leave-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="他院",
            first_name="休暇",
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="leave-no-clinic",
            password="test-password",
            role=user_model.Role.ADMIN,
        )
        self.leave_date = date(2026, 6, 17)
        self.other_leave = StaffLeave.objects.create(
            clinic=self.other_clinic,
            staff=self.other_staff,
            leave_type=StaffLeave.LeaveType.PAID_LEAVE,
            start_date=self.leave_date,
            end_date=self.leave_date,
            status=StaffLeave.Status.APPROVED,
            reason="他院休暇",
        )
        self.client.force_login(self.user)

    def _list_url(self, **params):
        url = reverse("staff:staff_leave_list")
        query = {
            "year": "2026",
            "month": "6",
        }
        query.update({key: str(value) for key, value in params.items()})
        return url + "?" + "&".join(f"{key}={value}" for key, value in query.items())

    def _create_url(self):
        return reverse("staff:staff_leave_create")

    def _update_url(self, leave):
        return reverse("staff:staff_leave_update", args=[leave.id])

    def _shift_month_url(self):
        return reverse("staff:staff_shift_month") + "?year=2026&month=6"

    def _valid_data(self, **overrides):
        data = {
            "staff": str(self.staff_user.id),
            "leave_type": StaffLeave.LeaveType.PAID_LEAVE,
            "start_date": self.leave_date.isoformat(),
            "end_date": self.leave_date.isoformat(),
            "start_time": "",
            "end_time": "",
            "status": StaffLeave.Status.APPROVED,
            "reason": "私用",
            "memo": "予約枠調整",
        }
        data.update(overrides)
        return data

    def test_own_staff_can_open_leave_list(self):
        StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.staff_user,
            leave_type=StaffLeave.LeaveType.PAID_LEAVE,
            start_date=self.leave_date,
            end_date=self.leave_date,
            status=StaffLeave.Status.APPROVED,
            reason="私用",
        )

        response = self.client.get(self._list_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/staff_leave_list.html")
        self.assertContains(response, "休暇・有給管理")
        self.assertContains(response, "休暇 花子")
        self.assertContains(response, "有給")
        self.assertNotContains(response, "他院休暇")

    def test_user_without_clinic_cannot_open_leave_list(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._list_url())

        self.assertEqual(response.status_code, 403)

    def test_other_clinic_leave_is_not_displayed(self):
        response = self.client.get(self._list_url())

        self.assertNotContains(response, "他院 休暇")
        self.assertNotContains(response, "他院休暇")

    def test_leave_can_be_created(self):
        response = self.client.post(self._create_url(), self._valid_data())

        self.assertEqual(response.status_code, 302)
        leave = StaffLeave.objects.get(clinic=self.clinic, staff=self.staff_user)
        self.assertEqual(leave.leave_type, StaffLeave.LeaveType.PAID_LEAVE)
        self.assertEqual(leave.status, StaffLeave.Status.APPROVED)
        self.assertEqual(leave.start_date, self.leave_date)

    def test_leave_can_be_updated(self):
        leave = StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.staff_user,
            leave_type=StaffLeave.LeaveType.PAID_LEAVE,
            start_date=self.leave_date,
            end_date=self.leave_date,
            status=StaffLeave.Status.REQUESTED,
        )

        response = self.client.post(
            self._update_url(leave),
            self._valid_data(
                leave_type=StaffLeave.LeaveType.MORNING_OFF,
                start_time="10:00",
                end_time="13:00",
                status=StaffLeave.Status.APPROVED,
                reason="午前休",
            ),
        )

        self.assertEqual(response.status_code, 302)
        leave.refresh_from_db()
        self.assertEqual(leave.leave_type, StaffLeave.LeaveType.MORNING_OFF)
        self.assertEqual(leave.start_time, time(10, 0))
        self.assertEqual(leave.end_time, time(13, 0))
        self.assertEqual(leave.reason, "午前休")

    def test_other_clinic_leave_update_returns_404(self):
        response = self.client.get(self._update_url(self.other_leave))

        self.assertEqual(response.status_code, 404)

    def test_other_clinic_staff_cannot_be_selected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(staff=str(self.other_staff.id)),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("staff", response.context["form"].errors)
        self.assertFalse(StaffLeave.objects.filter(clinic=self.clinic).exists())

    def test_start_date_after_end_date_is_rejected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(
                start_date="2026-06-20",
                end_date="2026-06-17",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("end_date", response.context["form"].errors)

    def test_invalid_time_order_is_rejected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(start_time="15:00", end_time="12:00"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("end_time", response.context["form"].errors)

    def test_inactive_staff_with_existing_leave_is_editable(self):
        leave = StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.inactive_staff,
            leave_type=StaffLeave.LeaveType.ABSENCE,
            start_date=self.leave_date,
            end_date=self.leave_date,
            status=StaffLeave.Status.APPROVED,
            reason="体調不良",
        )

        list_response = self.client.get(self._list_url())
        self.assertContains(list_response, "休止 一郎")
        self.assertContains(list_response, "無効スタッフ")

        edit_response = self.client.get(self._update_url(leave))
        self.assertEqual(edit_response.status_code, 200)
        staff_ids = list(edit_response.context["form"].fields["staff"].queryset.values_list("id", flat=True))
        self.assertIn(self.inactive_staff.id, staff_ids)

    def test_leave_is_displayed_on_shift_month(self):
        StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.staff_user,
            leave_type=StaffLeave.LeaveType.PAID_LEAVE,
            start_date=self.leave_date,
            end_date=self.leave_date,
            status=StaffLeave.Status.APPROVED,
            reason="私用",
        )

        response = self.client.get(self._shift_month_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "休暇 花子")
        self.assertContains(response, "有給")

    def test_staff_leave_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views.staff_leave_list_view)
            + inspect.getsource(staff_views.staff_leave_create_view)
            + inspect.getsource(staff_views.staff_leave_update_view)
        )

        self.assertNotIn(".path", source)


class AppointmentStaffAvailabilityTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.User = user_model
        self.clinic = Clinic.objects.create(name="予約担当候補院")
        self.other_clinic = Clinic.objects.create(name="他院予約担当")
        self.user = user_model.objects.create_user(
            username="availability-admin",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
            last_name="管理",
            first_name="太郎",
        )
        self.working_staff = user_model.objects.create_user(
            username="availability-working",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="勤務",
            first_name="可能",
        )
        self.no_shift_staff = user_model.objects.create_user(
            username="availability-no-shift",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="未設定",
            first_name="太郎",
        )
        self.off_staff = user_model.objects.create_user(
            username="availability-off",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="休み",
            first_name="太郎",
        )
        self.approved_leave_staff = user_model.objects.create_user(
            username="availability-approved-leave",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="有給",
            first_name="太郎",
        )
        self.requested_leave_staff = user_model.objects.create_user(
            username="availability-requested-leave",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="申請中",
            first_name="太郎",
        )
        self.morning_leave_staff = user_model.objects.create_user(
            username="availability-morning-leave",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="午前休",
            first_name="太郎",
        )
        self.afternoon_leave_staff = user_model.objects.create_user(
            username="availability-afternoon-leave",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="午後休",
            first_name="太郎",
        )
        self.timed_leave_staff = user_model.objects.create_user(
            username="availability-timed-leave",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="時間休",
            first_name="太郎",
        )
        self.other_staff = user_model.objects.create_user(
            username="availability-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="他院",
            first_name="太郎",
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="availability-no-clinic",
            password="test-password",
            role=user_model.Role.ADMIN,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="AVAIL-A-001",
            last_name="予約",
            first_name="患者",
            birth_date=date(1990, 1, 1),
            phone="09000004001",
        )
        self.treatment_menu = TreatmentMenu.objects.create(
            clinic=self.clinic,
            name="再診30分",
            price=5000,
            duration_minutes=30,
            is_active=True,
        )
        self.other_treatment_menu = TreatmentMenu.objects.create(
            clinic=self.other_clinic,
            name="他院メニュー",
            price=7000,
            duration_minutes=30,
            is_active=True,
        )
        self.target_date = date(2026, 6, 17)
        ClinicSettings.objects.create(
            clinic=self.clinic,
            business_start_time=time(9, 0),
            business_end_time=time(20, 0),
            break_start_time=time(13, 0),
            break_end_time=time(15, 0),
        )
        for staff_user, status in (
            (self.working_staff, StaffShift.Status.WORKING),
            (self.off_staff, StaffShift.Status.OFF),
            (self.approved_leave_staff, StaffShift.Status.WORKING),
            (self.requested_leave_staff, StaffShift.Status.WORKING),
            (self.morning_leave_staff, StaffShift.Status.WORKING),
            (self.afternoon_leave_staff, StaffShift.Status.WORKING),
            (self.timed_leave_staff, StaffShift.Status.WORKING),
        ):
            StaffShift.objects.create(
                clinic=self.clinic,
                staff=staff_user,
                date=self.target_date,
                status=status,
                start_time=time(9, 0) if status != StaffShift.Status.OFF else None,
                end_time=time(18, 0) if status != StaffShift.Status.OFF else None,
            )
        StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.approved_leave_staff,
            leave_type=StaffLeave.LeaveType.PAID_LEAVE,
            start_date=self.target_date,
            end_date=self.target_date,
            status=StaffLeave.Status.APPROVED,
        )
        StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.requested_leave_staff,
            leave_type=StaffLeave.LeaveType.PAID_LEAVE,
            start_date=self.target_date,
            end_date=self.target_date,
            status=StaffLeave.Status.REQUESTED,
        )
        StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.morning_leave_staff,
            leave_type=StaffLeave.LeaveType.MORNING_OFF,
            start_date=self.target_date,
            end_date=self.target_date,
            status=StaffLeave.Status.APPROVED,
        )
        StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.afternoon_leave_staff,
            leave_type=StaffLeave.LeaveType.AFTERNOON_OFF,
            start_date=self.target_date,
            end_date=self.target_date,
            status=StaffLeave.Status.APPROVED,
        )
        StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.timed_leave_staff,
            leave_type=StaffLeave.LeaveType.OTHER,
            start_date=self.target_date,
            end_date=self.target_date,
            start_time=time(10, 30),
            end_time=time(11, 30),
            status=StaffLeave.Status.APPROVED,
        )
        StaffShift.objects.create(
            clinic=self.other_clinic,
            staff=self.other_staff,
            date=self.target_date,
            status=StaffShift.Status.WORKING,
            start_time=time(9, 0),
            end_time=time(18, 0),
        )
        StaffLeave.objects.create(
            clinic=self.other_clinic,
            staff=self.other_staff,
            leave_type=StaffLeave.LeaveType.PAID_LEAVE,
            start_date=self.target_date,
            end_date=self.target_date,
            status=StaffLeave.Status.APPROVED,
        )
        self.client.force_login(self.user)

    def _appointments_url(self, **params):
        query = {
            "period": "day",
            "day": self.target_date.isoformat(),
        }
        query.update({key: str(value) for key, value in params.items()})
        return reverse("staff:appointments") + "?" + "&".join(
            f"{key}={value}" for key, value in query.items()
        )

    def _available_slots_response(self, **params):
        query = {
            "date": self.target_date.isoformat(),
            "duration_minutes": 30,
        }
        query.update({key: value for key, value in params.items()})
        return self.client.get(reverse("staff:appointment_available_slots_api"), query)

    def _timeline_response(self, target_date=None):
        return self.client.get(
            reverse("staff:appointments"),
            {
                "view": "timeline",
                "date": (target_date or self.target_date).isoformat(),
            },
        )

    def _timeline_row(self, response, staff_user):
        return next(
            row
            for row in response.context["staff_slot_timeline"]["rows"]
            if row["staff_id"] == staff_user.id
        )

    def _timeline_cell(self, response, staff_user, start_time):
        row = self._timeline_row(response, staff_user)
        return next(
            cell for cell in row["cells"] if cell["start_time"] == start_time
        )

    def _slot_starts(self, response):
        return {slot["start_time"] for slot in response.json().get("slots", [])}

    def _slot_staff_ids(self, response):
        return {slot["staff_id"] for slot in response.json().get("slots", [])}

    def _candidate_ids(self, response):
        return {user.id for user in response.context["staff_users"]}

    def _candidate_ids_for_time(self, hour, minute=0, duration_minutes=30):
        start = timezone.make_aware(datetime(2026, 6, 17, hour, minute))
        result = staff_views._build_appointment_staff_candidates(
            self.clinic,
            target_start=start,
            target_end=start + timedelta(minutes=duration_minutes),
        )
        return {
            user.id
            for user in result["users"]
            if user.is_appointment_staff_candidate
        }

    def _availability_for_time(self, staff_user, hour, minute=0, duration_minutes=30, exclude_id=None):
        start = timezone.make_aware(datetime(2026, 6, 17, hour, minute))
        return staff_views.check_appointment_availability(
            clinic=self.clinic,
            start_at=start,
            end_at=start + timedelta(minutes=duration_minutes),
            assigned_staff=staff_user,
            exclude_appointment_id=exclude_id,
        )

    def _appointment_api_payload(self, staff_user=None, patient=None, hour=10, minute=0, **overrides):
        start = time(hour, minute)
        end_dt = datetime.combine(self.target_date, start) + timedelta(minutes=30)
        data = {
            "patient_id": str((patient or self.patient).id),
            "appointment_date": self.target_date.isoformat(),
            "start_time": start.strftime("%H:%M"),
            "end_time": end_dt.time().strftime("%H:%M"),
            "assigned_staff_id": str((staff_user or self.working_staff).id),
            "status": Appointment.Status.BOOKED,
            "menu": "再診",
            "notes": "予約APIテスト",
        }
        data.update({key: str(value) for key, value in overrides.items()})
        return data

    def _post_create_appointment_api(self, **payload):
        return self.client.post(
            reverse("staff:appointment_create_api"),
            data=json.dumps(payload or self._appointment_api_payload()),
            content_type="application/json",
        )

    def _post_update_appointment_api(self, appointment, **payload):
        return self.client.post(
            reverse("staff:appointment_update_api", args=[appointment.id]),
            data=json.dumps(payload or self._appointment_api_payload()),
            content_type="application/json",
        )

    def test_working_shift_staff_is_candidate(self):
        response = self.client.get(self._appointments_url())

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.working_staff.id, self._candidate_ids(response))
        self.assertContains(response, "シフト反映済み")
        self.assertContains(response, "勤務可能な担当者のみ表示")

    def test_staff_without_shift_is_not_candidate(self):
        response = self.client.get(self._appointments_url())

        self.assertNotIn(self.no_shift_staff.id, self._candidate_ids(response))

    def test_off_shift_staff_is_not_candidate(self):
        response = self.client.get(self._appointments_url())

        self.assertNotIn(self.off_staff.id, self._candidate_ids(response))

    def test_approved_leave_staff_is_not_candidate(self):
        response = self.client.get(self._appointments_url())

        self.assertNotIn(self.approved_leave_staff.id, self._candidate_ids(response))

    def test_requested_leave_staff_remains_candidate(self):
        response = self.client.get(self._appointments_url())

        self.assertIn(self.requested_leave_staff.id, self._candidate_ids(response))

    def test_other_clinic_staff_is_not_candidate(self):
        response = self.client.get(self._appointments_url())

        self.assertNotIn(self.other_staff.id, self._candidate_ids(response))

    def test_staff_availability_rows_are_rendered_for_own_clinic_staff(self):
        response = self.client.get(self._appointments_url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "スタッフ別表示")
        rows = {
            row["staff_id"]: row
            for row in response.context["staff_availability_rows"]
        }
        self.assertIn(self.working_staff.id, rows)
        self.assertIn(self.off_staff.id, rows)
        self.assertNotIn(self.other_staff.id, rows)
        self.assertEqual(rows[self.working_staff.id]["work_time_label"], "09:00〜18:00")
        self.assertEqual(rows[self.working_staff.id]["availability_label"], "空きあり")

    def test_staff_availability_marks_off_and_approved_leave_unavailable(self):
        response = self.client.get(self._appointments_url())

        rows = {
            row["staff_id"]: row
            for row in response.context["staff_availability_rows"]
        }
        self.assertEqual(rows[self.off_staff.id]["availability_label"], "予約不可")
        self.assertEqual(
            rows[self.approved_leave_staff.id]["availability_label"],
            "予約不可",
        )

    def test_staff_availability_displays_morning_and_afternoon_leave_badges(self):
        response = self.client.get(self._appointments_url())

        rows = {
            row["staff_id"]: row
            for row in response.context["staff_availability_rows"]
        }
        morning_badges = rows[self.morning_leave_staff.id]["leave_badges"]
        afternoon_badges = rows[self.afternoon_leave_staff.id]["leave_badges"]
        self.assertTrue(any(badge["label"] == "午前休" for badge in morning_badges))
        self.assertTrue(any(badge["label"] == "午後休" for badge in afternoon_badges))
        self.assertEqual(rows[self.morning_leave_staff.id]["availability_label"], "要確認")
        self.assertEqual(rows[self.afternoon_leave_staff.id]["availability_label"], "要確認")

    def test_staff_availability_counts_own_staff_appointments_only(self):
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="再診",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )
        other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="AVAIL-B-001",
            last_name="他院",
            first_name="患者",
            birth_date=date(1991, 1, 1),
            phone="09000004002",
        )
        Appointment.objects.create(
            clinic=self.other_clinic,
            patient=other_patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 11, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 11, 30)),
            menu="他院予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.other_staff,
            created_by=self.other_staff,
        )

        response = self.client.get(self._appointments_url())

        rows = {
            row["staff_id"]: row
            for row in response.context["staff_availability_rows"]
        }
        self.assertEqual(rows[self.working_staff.id]["appointment_count"], 1)
        self.assertEqual(
            rows[self.working_staff.id]["appointments"][0]["patient_name"],
            "予約 患者",
        )
        self.assertNotIn(self.other_staff.id, rows)
        self.assertNotContains(response, "他院予約")

    def test_morning_off_staff_is_excluded_from_morning_appointment(self):
        ids = self._candidate_ids_for_time(10, 0)

        self.assertNotIn(self.morning_leave_staff.id, ids)
        self.assertIn(self.afternoon_leave_staff.id, ids)

    def test_morning_off_staff_remains_candidate_for_afternoon_appointment(self):
        ids = self._candidate_ids_for_time(16, 0)

        self.assertIn(self.morning_leave_staff.id, ids)

    def test_afternoon_off_staff_is_excluded_from_afternoon_appointment(self):
        ids = self._candidate_ids_for_time(16, 0)

        self.assertNotIn(self.afternoon_leave_staff.id, ids)
        self.assertIn(self.morning_leave_staff.id, ids)

    def test_afternoon_off_staff_remains_candidate_for_morning_appointment(self):
        ids = self._candidate_ids_for_time(10, 0)

        self.assertIn(self.afternoon_leave_staff.id, ids)

    def test_timed_leave_excludes_only_overlapping_appointment(self):
        overlapping_ids = self._candidate_ids_for_time(10, 45)
        non_overlapping_ids = self._candidate_ids_for_time(12, 0)

        self.assertNotIn(self.timed_leave_staff.id, overlapping_ids)
        self.assertIn(self.timed_leave_staff.id, non_overlapping_ids)

    def test_other_clinic_leave_does_not_affect_candidates(self):
        ids = self._candidate_ids_for_time(10, 0)

        self.assertIn(self.working_staff.id, ids)
        self.assertNotIn(self.other_staff.id, ids)

    def test_availability_rejects_same_staff_overlapping_appointment(self):
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="再診",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )

        result = self._availability_for_time(self.working_staff, 10, 15)

        self.assertFalse(result["is_valid"])
        self.assertIn("この担当者は同じ時間帯に別の予約があります。", result["errors"])
        self.assertEqual(len(result["conflict_appointments"]), 1)

    def test_availability_allows_same_time_for_different_staff(self):
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="再診",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )

        result = self._availability_for_time(self.requested_leave_staff, 10, 0)

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["conflict_appointments"], [])

    def test_availability_ignores_self_when_editing_existing_appointment(self):
        appt = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="再診",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )

        result = self._availability_for_time(
            self.working_staff,
            10,
            0,
            exclude_id=appt.id,
        )

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["conflict_appointments"], [])

    def test_availability_rejects_outside_business_hours(self):
        result = self._availability_for_time(self.working_staff, 8, 30)

        self.assertFalse(result["is_valid"])
        self.assertIn("営業時間外です。予約日時を確認してください。", result["errors"])

    def test_availability_warns_break_time_overlap(self):
        result = self._availability_for_time(self.working_staff, 13, 30)

        self.assertTrue(result["is_valid"])
        self.assertIn("休憩時間と重なっています。予約日時を確認してください。", result["warnings"])

    def test_availability_rejects_closed_weekday(self):
        settings = ClinicSettings.objects.get(clinic=self.clinic)
        settings.closed_weekdays = ["wed"]
        settings.save(update_fields=["closed_weekdays"])

        result = self._availability_for_time(self.working_staff, 10, 0)

        self.assertFalse(result["is_valid"])
        self.assertIn("休診曜日です。予約日時を確認してください。", result["errors"])

    def test_availability_rejects_off_shift_staff(self):
        result = self._availability_for_time(self.off_staff, 10, 0)

        self.assertFalse(result["is_valid"])
        self.assertIn("この担当者は対象日に休みです。", result["errors"])

    def test_availability_rejects_approved_leave_staff(self):
        result = self._availability_for_time(self.approved_leave_staff, 10, 0)

        self.assertFalse(result["is_valid"])
        self.assertTrue(any("休暇" in error or "勤務候補外" in error for error in result["errors"]))

    def test_availability_rejects_half_day_and_timed_leave_overlap(self):
        morning_result = self._availability_for_time(self.morning_leave_staff, 10, 0)
        afternoon_result = self._availability_for_time(self.afternoon_leave_staff, 16, 0)
        timed_result = self._availability_for_time(self.timed_leave_staff, 10, 45)

        self.assertFalse(morning_result["is_valid"])
        self.assertFalse(afternoon_result["is_valid"])
        self.assertFalse(timed_result["is_valid"])

    def test_availability_allows_requested_leave_staff(self):
        result = self._availability_for_time(self.requested_leave_staff, 10, 0)

        self.assertTrue(result["is_valid"])

    def test_availability_ignores_other_clinic_appointments(self):
        other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="AVAIL-C-001",
            last_name="他院",
            first_name="予約",
            birth_date=date(1992, 1, 1),
            phone="09000004003",
        )
        Appointment.objects.create(
            clinic=self.other_clinic,
            patient=other_patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="他院予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.other_staff,
            created_by=self.other_staff,
        )

        result = self._availability_for_time(self.working_staff, 10, 0)

        self.assertTrue(result["is_valid"])
        self.assertEqual(result["conflict_appointments"], [])

    def test_user_without_clinic_gets_403(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._appointments_url())

        self.assertEqual(response.status_code, 403)

    def test_existing_assigned_staff_outside_candidates_does_not_break_view(self):
        appt = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="再診",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.no_shift_staff,
            created_by=self.user,
        )

        response = self.client.get(self._appointments_url(staff=self.no_shift_staff.id))

        self.assertEqual(response.status_code, 200)
        self.assertIn(self.no_shift_staff.id, self._candidate_ids(response))
        self.assertContains(response, "現在の担当者は、この日時では勤務候補外です")
        self.assertContains(response, appt.menu)

    def test_unknown_date_returns_active_staff_without_crashing(self):
        result = staff_views._build_appointment_staff_candidates(
            self.clinic,
            target_date=None,
        )

        ids = {user.id for user in result["users"]}
        self.assertFalse(result["is_filtered"])
        self.assertTrue(result["date_unknown"])
        self.assertIn(self.working_staff.id, ids)
        self.assertIn(self.no_shift_staff.id, ids)

    def test_move_appointment_rejects_candidate_outside_target_day(self):
        appt = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="再診",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )
        target = timezone.make_aware(datetime(2026, 6, 18, 10, 0))

        response = self.client.post(
            reverse("staff:appointment_move", args=[appt.id]),
            data=json.dumps({
                "start": target.isoformat(),
                "end": (target + timedelta(minutes=30)).isoformat(),
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("勤務シフト", response.json()["error"])

    def test_move_appointment_rejects_afternoon_off_overlap(self):
        appt = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="再診",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.afternoon_leave_staff,
            created_by=self.user,
        )
        target = timezone.make_aware(datetime(2026, 6, 17, 16, 0))

        response = self.client.post(
            reverse("staff:appointment_move", args=[appt.id]),
            data=json.dumps({
                "start": target.isoformat(),
                "end": (target + timedelta(minutes=30)).isoformat(),
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("午後休", response.json()["error"])

    def test_move_appointment_rejects_overlapping_staff_appointment(self):
        existing = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="既存予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )
        appt = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 11, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 11, 30)),
            menu="移動予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )
        target = timezone.make_aware(datetime(2026, 6, 17, 10, 15))

        response = self.client.post(
            reverse("staff:appointment_move", args=[appt.id]),
            data=json.dumps({
                "start": target.isoformat(),
                "end": (target + timedelta(minutes=30)).isoformat(),
            }),
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("同じ時間帯", response.json()["error"])
        existing.refresh_from_db()
        self.assertEqual(existing.start_at, timezone.make_aware(datetime(2026, 6, 17, 10, 0)))

    def test_staff_timeline_view_renders_own_clinic_staff_and_business_slots(self):
        response = self._timeline_response()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "担当者別タイムライン")
        timeline = response.context["staff_slot_timeline"]
        staff_ids = {row["staff_id"] for row in timeline["rows"]}
        slot_starts = {slot["start_time"] for slot in timeline["slots"]}
        self.assertIn(self.working_staff.id, staff_ids)
        self.assertNotIn(self.other_staff.id, staff_ids)
        self.assertIn("09:00", slot_starts)
        self.assertIn("19:30", slot_starts)

    def test_staff_timeline_marks_available_break_and_outside_shift(self):
        response = self._timeline_response()

        self.assertEqual(
            self._timeline_cell(response, self.working_staff, "09:00")["state"],
            "available",
        )
        self.assertEqual(
            self._timeline_cell(response, self.working_staff, "13:00")["state"],
            "break",
        )
        self.assertEqual(
            self._timeline_cell(response, self.working_staff, "18:00")["state"],
            "outside_shift",
        )

    def test_staff_timeline_marks_off_shift_and_approved_leave(self):
        response = self._timeline_response()

        self.assertEqual(
            self._timeline_cell(response, self.off_staff, "09:00")["state"],
            "off",
        )
        self.assertEqual(
            self._timeline_cell(
                response,
                self.approved_leave_staff,
                "09:00",
            )["state"],
            "leave",
        )

    def test_staff_timeline_applies_half_day_and_timed_leave_windows(self):
        response = self._timeline_response()

        self.assertEqual(
            self._timeline_cell(response, self.morning_leave_staff, "09:00")["state"],
            "leave",
        )
        self.assertEqual(
            self._timeline_cell(response, self.morning_leave_staff, "15:00")["state"],
            "available",
        )
        self.assertEqual(
            self._timeline_cell(response, self.afternoon_leave_staff, "15:00")["state"],
            "leave",
        )
        self.assertEqual(
            self._timeline_cell(response, self.timed_leave_staff, "10:30")["state"],
            "leave",
        )

    def test_staff_timeline_marks_appointment_as_booked_and_excludes_other_clinic(self):
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="再診",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )
        other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="TIMELINE-OTHER",
            last_name="他院",
            first_name="非表示",
            birth_date=date(1990, 1, 1),
            phone="09000004999",
        )
        Appointment.objects.create(
            clinic=self.other_clinic,
            patient=other_patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="他院予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.other_staff,
            created_by=self.other_staff,
        )

        response = self._timeline_response()
        cell = self._timeline_cell(response, self.working_staff, "10:00")

        self.assertEqual(cell["state"], "booked")
        self.assertEqual(cell["appointment"]["patient_name"], "予約 患者")
        self.assertNotContains(response, "他院予約")
        self.assertNotContains(response, "他院 非表示")

    def test_staff_timeline_outputs_available_and_edit_modal_data_attributes(self):
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="再診",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )

        response = self._timeline_response()

        self.assertContains(response, "data-timeline-available")
        self.assertContains(response, "data-timeline-booked")
        self.assertContains(
            response,
            f'data-assigned-staff-id="{self.working_staff.id}"',
        )

    def test_staff_timeline_closed_weekday_has_no_available_cells(self):
        settings = ClinicSettings.objects.get(clinic=self.clinic)
        settings.closed_weekdays = ["wed"]
        settings.save(update_fields=["closed_weekdays"])

        response = self._timeline_response()
        row = self._timeline_row(response, self.working_staff)

        self.assertTrue(response.context["staff_slot_timeline"]["is_closed"])
        self.assertNotIn("available", {cell["state"] for cell in row["cells"]})

    def test_staff_timeline_user_without_clinic_gets_403(self):
        self.client.force_login(self.no_clinic_user)

        response = self._timeline_response()

        self.assertEqual(response.status_code, 403)

    def test_available_slots_api_returns_business_hour_slots(self):
        response = self._available_slots_response(staff_id=self.working_staff.id)

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn("09:00", self._slot_starts(response))
        self.assertIn(self.working_staff.id, self._slot_staff_ids(response))
        self.assertTrue(any(slot["staff_id"] == self.working_staff.id for slot in data["slots"]))

    def test_available_slots_api_uses_clinic_interval(self):
        settings = ClinicSettings.objects.get(clinic=self.clinic)
        settings.appointment_interval_minutes = 15
        settings.save(update_fields=["appointment_interval_minutes"])

        response = self._available_slots_response(staff_id=self.working_staff.id)

        self.assertEqual(response.status_code, 200)
        self.assertIn("09:15", self._slot_starts(response))

    def test_available_slots_api_excludes_break_time_overlap(self):
        response = self._available_slots_response(staff_id=self.working_staff.id)

        self.assertEqual(response.status_code, 200)
        starts = self._slot_starts(response)
        self.assertNotIn("13:00", starts)
        self.assertNotIn("14:30", starts)
        self.assertIn("15:00", starts)

    def test_available_slots_api_rejects_closed_weekday(self):
        settings = ClinicSettings.objects.get(clinic=self.clinic)
        settings.closed_weekdays = ["wed"]
        settings.save(update_fields=["closed_weekdays"])

        response = self._available_slots_response(staff_id=self.working_staff.id)

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("休診曜日", response.json()["errors"][0])

    def test_available_slots_api_excludes_existing_appointment_overlap(self):
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="既存予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )

        response = self._available_slots_response(staff_id=self.working_staff.id)

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("10:00", self._slot_starts(response))

    def test_available_slots_api_exclude_appointment_id_ignores_self(self):
        appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="編集予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )

        blocked = self._available_slots_response(staff_id=self.working_staff.id)
        allowed = self._available_slots_response(
            staff_id=self.working_staff.id,
            exclude_appointment_id=appointment.id,
        )

        self.assertNotIn("10:00", self._slot_starts(blocked))
        self.assertIn("10:00", self._slot_starts(allowed))

    def test_available_slots_api_excludes_off_and_approved_leave_staff(self):
        off_response = self._available_slots_response(staff_id=self.off_staff.id)
        leave_response = self._available_slots_response(staff_id=self.approved_leave_staff.id)

        self.assertEqual(off_response.status_code, 200)
        self.assertEqual(leave_response.status_code, 200)
        self.assertEqual(off_response.json()["slots"], [])
        self.assertEqual(leave_response.json()["slots"], [])

    def test_available_slots_api_handles_half_day_and_timed_leave(self):
        morning_response = self._available_slots_response(staff_id=self.morning_leave_staff.id)
        afternoon_response = self._available_slots_response(staff_id=self.afternoon_leave_staff.id)
        timed_response = self._available_slots_response(staff_id=self.timed_leave_staff.id)

        self.assertNotIn("10:00", self._slot_starts(morning_response))
        self.assertIn("15:00", self._slot_starts(morning_response))
        self.assertIn("09:00", self._slot_starts(afternoon_response))
        self.assertNotIn("15:00", self._slot_starts(afternoon_response))
        self.assertNotIn("10:30", self._slot_starts(timed_response))
        self.assertIn("12:00", self._slot_starts(timed_response))

    def test_available_slots_api_keeps_requested_leave_staff(self):
        response = self._available_slots_response(staff_id=self.requested_leave_staff.id)

        self.assertEqual(response.status_code, 200)
        self.assertIn("10:00", self._slot_starts(response))

    def test_available_slots_api_ignores_other_clinic_appointments(self):
        other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="AVAIL-F-001",
            last_name="他院",
            first_name="予約",
            birth_date=date(1992, 1, 1),
            phone="09000004006",
        )
        Appointment.objects.create(
            clinic=self.other_clinic,
            patient=other_patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="他院予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.other_staff,
            created_by=self.other_staff,
        )

        response = self._available_slots_response(staff_id=self.working_staff.id)

        self.assertEqual(response.status_code, 200)
        self.assertIn("10:00", self._slot_starts(response))

    def test_available_slots_api_rejects_other_clinic_staff_and_menu(self):
        staff_response = self._available_slots_response(staff_id=self.other_staff.id)
        menu_response = self._available_slots_response(
            staff_id=self.working_staff.id,
            treatment_menu_id=self.other_treatment_menu.id,
        )

        self.assertEqual(staff_response.status_code, 404)
        self.assertEqual(menu_response.status_code, 404)

    def test_available_slots_api_uses_treatment_menu_duration(self):
        long_menu = TreatmentMenu.objects.create(
            clinic=self.clinic,
            name="長め施術",
            price=9000,
            duration_minutes=60,
            is_active=True,
        )

        response = self._available_slots_response(
            staff_id=self.working_staff.id,
            treatment_menu_id=long_menu.id,
            duration_minutes="",
        )

        self.assertEqual(response.status_code, 200)
        first = response.json()["slots"][0]
        self.assertEqual(first["start_time"], "09:00")
        self.assertEqual(first["end_time"], "10:00")

    def test_available_slots_api_without_staff_returns_own_available_staff_only(self):
        response = self._available_slots_response()

        self.assertEqual(response.status_code, 200)
        staff_ids = self._slot_staff_ids(response)
        self.assertIn(self.working_staff.id, staff_ids)
        self.assertIn(self.requested_leave_staff.id, staff_ids)
        self.assertNotIn(self.off_staff.id, staff_ids)
        self.assertNotIn(self.other_staff.id, staff_ids)

    def test_available_slots_api_user_without_clinic_gets_403(self):
        self.client.force_login(self.no_clinic_user)

        response = self._available_slots_response(staff_id=self.working_staff.id)

        self.assertEqual(response.status_code, 403)

    def test_appointment_create_api_creates_own_clinic_appointment(self):
        response = self._post_create_appointment_api(
            **self._appointment_api_payload(self.working_staff)
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        appt = Appointment.objects.get(pk=data["appointment_id"])
        self.assertEqual(appt.clinic, self.clinic)
        self.assertEqual(appt.patient, self.patient)
        self.assertEqual(appt.assigned_staff, self.working_staff)
        self.assertEqual(appt.menu, "再診")
        self.assertEqual(appt.booking_source, Appointment.BookingSource.STAFF)

    def test_appointment_create_api_rejects_other_clinic_patient(self):
        other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="AVAIL-D-001",
            last_name="他院",
            first_name="患者",
            birth_date=date(1992, 1, 1),
            phone="09000004004",
        )

        response = self._post_create_appointment_api(
            **self._appointment_api_payload(
                self.working_staff,
                patient=other_patient,
            )
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("患者情報", response.json()["error"])

    def test_appointment_create_api_rejects_other_clinic_staff(self):
        response = self._post_create_appointment_api(
            **self._appointment_api_payload(
                self.working_staff,
                assigned_staff_id=self.other_staff.id,
            )
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("担当者情報", response.json()["error"])

    def test_appointment_create_api_rejects_overlapping_same_staff(self):
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="既存予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )

        response = self._post_create_appointment_api(
            **self._appointment_api_payload(self.working_staff, hour=10, minute=15)
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("同じ時間帯", response.json()["error"])

    def test_appointment_create_api_allows_same_time_for_different_staff(self):
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="既存予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )

        response = self._post_create_appointment_api(
            **self._appointment_api_payload(self.requested_leave_staff, hour=10)
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_appointment_create_api_rejects_outside_business_hours(self):
        response = self._post_create_appointment_api(
            **self._appointment_api_payload(self.working_staff, hour=8, minute=30)
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("営業時間外", response.json()["error"])

    def test_appointment_create_api_rejects_closed_weekday(self):
        settings = ClinicSettings.objects.get(clinic=self.clinic)
        settings.closed_weekdays = ["wed"]
        settings.save(update_fields=["closed_weekdays"])

        response = self._post_create_appointment_api(
            **self._appointment_api_payload(self.working_staff)
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("休診曜日", response.json()["error"])

    def test_appointment_create_api_rejects_off_shift_staff(self):
        response = self._post_create_appointment_api(
            **self._appointment_api_payload(self.off_staff)
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("休み", response.json()["error"])

    def test_appointment_create_api_rejects_approved_leave_staff(self):
        response = self._post_create_appointment_api(
            **self._appointment_api_payload(self.approved_leave_staff)
        )

        self.assertEqual(response.status_code, 400)
        self.assertTrue(
            "休暇" in response.json()["error"]
            or "勤務候補外" in response.json()["error"]
        )

    def test_appointment_create_api_allows_requested_leave_staff(self):
        response = self._post_create_appointment_api(
            **self._appointment_api_payload(self.requested_leave_staff)
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

    def test_appointment_update_api_ignores_self_overlap(self):
        appt = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="更新前",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.working_staff,
            created_by=self.user,
        )

        response = self._post_update_appointment_api(
            appt,
            **self._appointment_api_payload(self.working_staff, menu="更新後"),
        )

        self.assertEqual(response.status_code, 200)
        appt.refresh_from_db()
        self.assertEqual(appt.menu, "更新後")

    def test_appointment_update_api_other_clinic_appointment_returns_404(self):
        other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="AVAIL-E-001",
            last_name="他院",
            first_name="予約",
            birth_date=date(1992, 1, 1),
            phone="09000004005",
        )
        other_appt = Appointment.objects.create(
            clinic=self.other_clinic,
            patient=other_patient,
            start_at=timezone.make_aware(datetime(2026, 6, 17, 10, 0)),
            end_at=timezone.make_aware(datetime(2026, 6, 17, 10, 30)),
            menu="他院予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.other_staff,
            created_by=self.other_staff,
        )

        response = self._post_update_appointment_api(
            other_appt,
            **self._appointment_api_payload(self.working_staff),
        )

        self.assertEqual(response.status_code, 404)

    def test_appointment_create_api_user_without_clinic_gets_403(self):
        self.client.force_login(self.no_clinic_user)

        response = self._post_create_appointment_api(
            **self._appointment_api_payload(self.working_staff)
        )

        self.assertEqual(response.status_code, 403)

    def test_appointment_staff_candidate_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views._build_appointment_staff_candidates)
            + inspect.getsource(staff_views._is_staff_available_for_appointment)
            + inspect.getsource(staff_views.check_appointment_availability)
            + inspect.getsource(staff_views._build_staff_availability_rows)
            + inspect.getsource(staff_views._build_staff_appointment_item)
            + inspect.getsource(staff_views.build_staff_appointment_timeline)
            + inspect.getsource(staff_views.staff_appointments_view)
            + inspect.getsource(staff_views.build_appointment_available_slots)
            + inspect.getsource(staff_views.staff_appointment_available_slots_api)
            + inspect.getsource(staff_views.staff_appointment_create_api)
            + inspect.getsource(staff_views.staff_appointment_update_api)
            + inspect.getsource(staff_views.move_appointment_view)
        )

        self.assertNotIn(".path", source)


class StaffTreatmentMenuTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="料金設定院")
        self.other_clinic = Clinic.objects.create(name="他院料金")
        self.user = user_model.objects.create_user(
            username="treatment-menu-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
        )
        self.other_user = user_model.objects.create_user(
            username="treatment-menu-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.ADMIN,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="treatment-menu-no-clinic",
            password="test-password",
            role=user_model.Role.ADMIN,
        )
        self.other_menu = TreatmentMenu.objects.create(
            clinic=self.other_clinic,
            name="他院限定メニュー",
            description="他院の料金です。",
            price=99999,
            duration_minutes=60,
        )
        self.client.force_login(self.user)

    def _list_url(self):
        return reverse("staff:treatment_menu_list")

    def _create_url(self):
        return reverse("staff:treatment_menu_create")

    def _update_url(self, menu):
        return reverse("staff:treatment_menu_update", args=[menu.id])

    def _toggle_url(self, menu):
        return reverse("staff:treatment_menu_toggle", args=[menu.id])

    def _valid_data(self, **overrides):
        data = {
            "name": "全身調整 30分",
            "description": "姿勢や動作の状態に合わせて調整します。",
            "price": "5000",
            "duration_minutes": "30",
            "is_active": "on",
            "display_order": "10",
        }
        data.update(overrides)
        return data

    def test_own_staff_can_open_treatment_menu_list(self):
        response = self.client.get(self._list_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/treatment_menu_list.html")
        self.assertContains(response, "施術メニュー・料金設定")
        self.assertContains(response, "施術メニューはまだ登録されていません")
        self.assertNotContains(response, "他院限定メニュー")

    def test_user_without_clinic_cannot_open_treatment_menu_list(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._list_url())

        self.assertEqual(response.status_code, 403)

    def test_treatment_menu_can_be_created(self):
        response = self.client.post(self._create_url(), self._valid_data())

        self.assertRedirects(response, self._list_url())
        menu = TreatmentMenu.objects.get(clinic=self.clinic)
        self.assertEqual(menu.name, "全身調整 30分")
        self.assertEqual(menu.price, 5000)
        self.assertEqual(menu.duration_minutes, 30)
        self.assertTrue(menu.is_active)

    def test_treatment_menu_can_be_updated(self):
        menu = TreatmentMenu.objects.create(
            clinic=self.clinic,
            name="旧メニュー",
            price=3000,
            duration_minutes=20,
        )

        response = self.client.post(
            self._update_url(menu),
            self._valid_data(
                name="骨盤バランス調整",
                price="6500",
                duration_minutes="45",
                display_order="2",
            ),
        )

        self.assertRedirects(response, self._list_url())
        menu.refresh_from_db()
        self.assertEqual(menu.name, "骨盤バランス調整")
        self.assertEqual(menu.price, 6500)
        self.assertEqual(menu.duration_minutes, 45)
        self.assertEqual(menu.display_order, 2)

    def test_other_clinic_menu_update_returns_404(self):
        response = self.client.get(self._update_url(self.other_menu))

        self.assertEqual(response.status_code, 404)

    def test_negative_price_is_rejected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(price="-1"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("price", response.context["form"].errors)

    def test_invalid_duration_is_rejected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(duration_minutes="7"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("duration_minutes", response.context["form"].errors)

    def test_treatment_menu_can_be_disabled_and_reenabled(self):
        menu = TreatmentMenu.objects.create(
            clinic=self.clinic,
            name="アクティブメニュー",
            price=4000,
            duration_minutes=30,
        )

        response = self.client.post(self._toggle_url(menu))

        self.assertRedirects(response, self._list_url())
        menu.refresh_from_db()
        self.assertFalse(menu.is_active)

        response = self.client.post(self._toggle_url(menu))

        self.assertRedirects(response, self._list_url())
        menu.refresh_from_db()
        self.assertTrue(menu.is_active)

    def test_other_clinic_menu_is_not_displayed_on_list(self):
        TreatmentMenu.objects.create(
            clinic=self.clinic,
            name="自院メニュー",
            price=5000,
            duration_minutes=30,
        )

        response = self.client.get(self._list_url())

        self.assertContains(response, "自院メニュー")
        self.assertContains(response, "¥5,000")
        self.assertNotContains(response, "他院限定メニュー")
        self.assertNotContains(response, "99999")

    def test_treatment_menu_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views.staff_treatment_menu_list_view)
            + inspect.getsource(staff_views.staff_treatment_menu_create_view)
            + inspect.getsource(staff_views.staff_treatment_menu_update_view)
            + inspect.getsource(staff_views.staff_treatment_menu_toggle_view)
        )

        self.assertNotIn(".path", source)


class StaffSalesRecordTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="売上管理院")
        self.other_clinic = Clinic.objects.create(name="他院売上")
        self.user = user_model.objects.create_user(
            username="sales-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
            last_name="売上",
            first_name="太郎",
        )
        self.other_user = user_model.objects.create_user(
            username="sales-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.ADMIN,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="sales-no-clinic",
            password="test-password",
            role=user_model.Role.ADMIN,
        )
        self.patient = self._patient(
            clinic=self.clinic,
            card_no="SALE-A-001",
            last_name="売上",
            first_name="患者",
            phone="09000001001",
        )
        self.other_patient = self._patient(
            clinic=self.other_clinic,
            card_no="SALE-B-001",
            last_name="他院",
            first_name="患者",
            phone="09000001002",
        )
        now = timezone.now()
        self.appointment = self._appointment(
            clinic=self.clinic,
            patient=self.patient,
            user=self.user,
            start_at=now,
        )
        self.other_appointment = self._appointment(
            clinic=self.other_clinic,
            patient=self.other_patient,
            user=self.other_user,
            start_at=now,
        )
        self.note = ClinicalNote.objects.create(
            appointment=self.appointment,
            patient=self.patient,
            soap_json={},
            extract_json={},
            followups_json=[],
            registered_by=self.user,
        )
        self.other_note = ClinicalNote.objects.create(
            appointment=self.other_appointment,
            patient=self.other_patient,
            soap_json={},
            extract_json={},
            followups_json=[],
            registered_by=self.other_user,
        )
        self.menu = TreatmentMenu.objects.create(
            clinic=self.clinic,
            name="全身調整",
            price=5000,
            duration_minutes=30,
        )
        self.other_menu = TreatmentMenu.objects.create(
            clinic=self.other_clinic,
            name="他院メニュー",
            price=99999,
            duration_minutes=60,
        )
        self.other_record = SalesRecord.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            clinical_note=self.other_note,
            treatment_menu=self.other_menu,
            staff=self.other_user,
            treatment_date=timezone.localdate(),
            amount=99999,
            payment_method=SalesRecord.PaymentMethod.CASH,
            status=SalesRecord.Status.PAID,
        )
        self.client.force_login(self.user)

    @staticmethod
    def _patient(*, clinic, card_no, last_name, first_name, phone):
        return Patient.objects.create(
            clinic=clinic,
            card_no=card_no,
            last_name=last_name,
            first_name=first_name,
            last_name_kana="テスト",
            first_name_kana="カンジャ",
            birth_date=date(1990, 1, 1),
            phone=phone,
        )

    @staticmethod
    def _appointment(*, clinic, patient, user, start_at):
        return Appointment.objects.create(
            clinic=clinic,
            patient=patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            menu="会計確認",
            status=Appointment.Status.COMPLETED,
            assigned_staff=user,
            created_by=user,
        )

    def _list_url(self):
        return reverse("staff:sales_record_list")

    def _create_url(self):
        return reverse("staff:sales_record_create")

    def _update_url(self, record):
        return reverse("staff:sales_record_update", args=[record.id])

    def _valid_data(self, **overrides):
        data = {
            "patient": str(self.patient.id),
            "appointment": str(self.appointment.id),
            "clinical_note": str(self.note.id),
            "treatment_menu": str(self.menu.id),
            "staff": str(self.user.id),
            "treatment_date": timezone.localdate().isoformat(),
            "amount": "5000",
            "payment_method": SalesRecord.PaymentMethod.CASH,
            "status": SalesRecord.Status.PAID,
            "memo": "通常会計",
        }
        data.update(overrides)
        return data

    def test_own_staff_can_open_sales_record_list(self):
        response = self.client.get(self._list_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "staff/sales_record_list.html")
        self.assertContains(response, "売上管理")
        self.assertNotContains(response, "他院メニュー")
        self.assertNotContains(response, "99999")

    def test_user_without_clinic_cannot_open_sales_record_list(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._list_url())

        self.assertEqual(response.status_code, 403)

    def test_sales_record_can_be_created(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(amount=""),
        )

        self.assertRedirects(response, self._list_url())
        record = SalesRecord.objects.get(clinic=self.clinic)
        self.assertEqual(record.patient, self.patient)
        self.assertEqual(record.treatment_menu, self.menu)
        self.assertEqual(record.amount, self.menu.price)
        self.assertEqual(record.status, SalesRecord.Status.PAID)

    def test_sales_record_can_be_updated(self):
        record = SalesRecord.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            clinical_note=self.note,
            treatment_menu=self.menu,
            staff=self.user,
            treatment_date=timezone.localdate(),
            amount=5000,
            payment_method=SalesRecord.PaymentMethod.CASH,
            status=SalesRecord.Status.PAID,
        )

        response = self.client.post(
            self._update_url(record),
            self._valid_data(
                amount="6500",
                payment_method=SalesRecord.PaymentMethod.CARD,
                status=SalesRecord.Status.UNPAID,
                memo="カード確認中",
            ),
        )

        self.assertRedirects(response, self._list_url())
        record.refresh_from_db()
        self.assertEqual(record.amount, 6500)
        self.assertEqual(record.payment_method, SalesRecord.PaymentMethod.CARD)
        self.assertEqual(record.status, SalesRecord.Status.UNPAID)
        self.assertEqual(record.memo, "カード確認中")

    def test_other_clinic_sales_record_update_returns_404(self):
        response = self.client.get(self._update_url(self.other_record))

        self.assertEqual(response.status_code, 404)

    def test_other_clinic_patient_cannot_be_linked(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(
                patient=str(self.other_patient.id),
                appointment="",
                clinical_note="",
            ),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("patient", response.context["form"].errors)
        self.assertFalse(SalesRecord.objects.filter(clinic=self.clinic).exists())

    def test_other_clinic_treatment_menu_cannot_be_linked(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(treatment_menu=str(self.other_menu.id)),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("treatment_menu", response.context["form"].errors)
        self.assertFalse(SalesRecord.objects.filter(clinic=self.clinic).exists())

    def test_negative_amount_is_rejected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(amount="-1"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("amount", response.context["form"].errors)

    def test_canceled_sales_record_can_be_saved(self):
        response = self.client.post(
            self._create_url(),
            self._valid_data(status=SalesRecord.Status.CANCELED),
        )

        self.assertRedirects(response, self._list_url())
        record = SalesRecord.objects.get(clinic=self.clinic)
        self.assertEqual(record.status, SalesRecord.Status.CANCELED)
        self.assertEqual(record.amount, 5000)

    def test_only_own_clinic_sales_are_displayed(self):
        SalesRecord.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            clinical_note=self.note,
            treatment_menu=self.menu,
            staff=self.user,
            treatment_date=timezone.localdate(),
            amount=5000,
            payment_method=SalesRecord.PaymentMethod.CASH,
            status=SalesRecord.Status.PAID,
        )

        response = self.client.get(self._list_url())

        self.assertContains(response, "全身調整")
        self.assertContains(response, "¥5,000")
        self.assertNotContains(response, "他院メニュー")
        self.assertNotContains(response, "99999")

    def test_sales_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views.staff_sales_record_list_view)
            + inspect.getsource(staff_views.staff_sales_record_create_view)
            + inspect.getsource(staff_views.staff_sales_record_update_view)
        )

        self.assertNotIn(".path", source)


class StaffPatientListTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="Patient List Clinic")
        self.other_clinic = Clinic.objects.create(name="Other Patient List")
        self.user = user_model.objects.create_user(
            username="patient-list-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.other_user = user_model.objects.create_user(
            username="patient-list-other",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.no_clinic_user = user_model.objects.create_user(
            username="patient-list-no-clinic",
            password="test-password",
            role=user_model.Role.PRACTITIONER,
        )
        self.patient = self._patient(
            clinic=self.clinic,
            card_no="LIST-A-001",
            last_name="山田",
            first_name="太郎",
            phone="09011112222",
        )
        self.second_patient = self._patient(
            clinic=self.clinic,
            card_no="LIST-A-002",
            last_name="佐藤",
            first_name="花子",
            phone="08033334444",
        )
        self.other_patient = self._patient(
            clinic=self.other_clinic,
            card_no="LIST-B-001",
            last_name="他院",
            first_name="患者",
            phone="07055556666",
        )
        today_start = timezone.make_aware(
            datetime.combine(timezone.localdate(), time(hour=10))
        )
        self.appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=today_start,
            end_at=today_start + timedelta(hours=1),
            menu="本日施術",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.user,
            created_by=self.user,
        )
        other_appointment = Appointment.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            start_at=today_start,
            end_at=today_start + timedelta(hours=1),
            menu="他院予約",
            status=Appointment.Status.BOOKED,
            assigned_staff=self.other_user,
            created_by=self.other_user,
        )
        Intake.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            submitted_at=timezone.now(),
            chief_complaint="腰部の違和感",
        )
        InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            summary_json={"overall_summary": "確認待ち"},
            confirmed_summary_json=None,
            created_by=self.user,
        )
        InterviewRecording.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=other_appointment,
            summary_json={"overall_summary": "他院確認待ち"},
            confirmed_summary_json=None,
            created_by=self.other_user,
        )
        self.client.force_login(self.user)

    @staticmethod
    def _patient(*, clinic, card_no, last_name, first_name, phone):
        return Patient.objects.create(
            clinic=clinic,
            card_no=card_no,
            last_name=last_name,
            first_name=first_name,
            last_name_kana="テスト",
            first_name_kana="カンジャ",
            birth_date=date(1990, 1, 1),
            phone=phone,
        )

    def _url(self):
        return reverse("staff:patient_search")

    def test_patient_list_displays_only_own_clinic_patients(self):
        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "山田 太郎")
        self.assertContains(response, "佐藤 花子")
        self.assertNotContains(response, "他院 患者")

    def test_patient_name_and_phone_search(self):
        name_response = self.client.get(self._url(), {"q": "山田"})
        phone_response = self.client.get(self._url(), {"q": "0803333"})
        complaint_response = self.client.get(self._url(), {"q": "腰部"})

        self.assertContains(name_response, "山田 太郎")
        self.assertNotContains(name_response, "佐藤 花子")
        self.assertContains(phone_response, "佐藤 花子")
        self.assertNotContains(phone_response, "山田 太郎")
        self.assertContains(complaint_response, "山田 太郎")
        self.assertNotContains(complaint_response, "佐藤 花子")

    def test_today_appointment_filter(self):
        response = self.client.get(self._url(), {"filter": "today"})

        self.assertContains(response, "山田 太郎")
        self.assertNotContains(response, "佐藤 花子")

    def test_confirmation_waiting_filter(self):
        response = self.client.get(
            self._url(),
            {"filter": "confirmation_waiting"},
        )

        self.assertContains(response, "山田 太郎")
        self.assertNotContains(response, "佐藤 花子")
        self.assertContains(response, "要確認")

    def test_patient_list_major_action_links_render(self):
        response = self.client.get(self._url())

        self.assertContains(
            response,
            reverse("staff:patient_detail", args=[self.patient.id]),
        )
        self.assertContains(
            response,
            reverse("staff:pre_treatment_check", args=[self.patient.id]),
        )
        self.assertContains(
            response,
            reverse(
                "intakes:recording_new",
                args=[self.appointment.id],
            ),
        )
        self.assertContains(
            response,
            reverse(
                "treatment_sessions:start_for_patient",
                args=[self.patient.id],
            ),
        )

    def test_user_without_clinic_cannot_open_patient_list(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)

    def test_empty_patient_list_displays_guidance(self):
        empty_clinic = Clinic.objects.create(name="Empty Patient Clinic")
        empty_user = get_user_model().objects.create_user(
            username="empty-patient-list",
            password="test-password",
            clinic=empty_clinic,
            role=get_user_model().Role.PRACTITIONER,
        )
        self.client.force_login(empty_user)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "まだ患者様は登録されていません")

    def test_patient_list_view_does_not_use_file_path(self):
        source = inspect.getsource(staff_views.staff_patient_search_view)

        self.assertNotIn(".path", source)


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

    def _timeline_url(self, patient=None):
        return (
            reverse(
                "staff:patient_detail",
                args=[(patient or self.patient).id],
            )
            + "?tab=timeline"
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

    def test_patient_clinical_notes_empty_state_explains_next_step(self):
        response = self.client.get(
            f"{self._detail_url()}?tab=clinical_notes"
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "まだカルテは登録されていません。録音または手入力からカルテを作成できます。",
        )

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
            "まだカルテは登録されていません。録音または手入力からカルテを作成できます。",
        )
        self.assertContains(response, "姿勢分析はまだ登録されていません")
        self.assertContains(response, "施術計画はまだ作成されていません")
        self.assertContains(response, "ダッシュボードへ戻る")
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

    def test_patient_timeline_includes_major_treatment_events(self):
        start_at = timezone.now() - timedelta(days=1)
        appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=start_at,
            end_at=start_at + timedelta(hours=1),
            menu="タイムライン施術",
            status=Appointment.Status.COMPLETED,
            created_by=self.user,
        )
        recording = InterviewRecording.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=appointment,
            status=InterviewRecording.Status.DONE,
            transcript_text="初診時の主訴を確認しました",
            confirmed_summary_json={"overall_summary": "確認済み"},
            summary_status=InterviewRecording.SummaryStatus.CONFIRMED,
            created_by=self.user,
        )
        session = TreatmentSession.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=appointment,
            title="通院施術の記録",
            status=TreatmentSession.Status.DONE,
            transcript_text="施術中の変化を確認しました",
            confirmed_summary_json={"overall_summary": "確認済み"},
            summary_status="confirmed",
            created_by=self.user,
        )
        note = ClinicalNote.objects.create(
            appointment=appointment,
            patient=self.patient,
            recording=recording,
            treatment_session=session,
            soap_json={"S": ["右膝の違和感"]},
            extract_json={"overall_summary": "右膝の状態を確認しました"},
            registered_by=self.user,
        )
        session.clinical_note = note
        session.save(update_fields=["clinical_note"])
        posture = PostureAssessment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=appointment,
            treatment_session=session,
            clinical_note=note,
            title="姿勢バランス確認",
            status=PostureAssessment.Status.CONFIRMED,
            confirmed_summary_json={
                "report_summary_for_patient": "骨盤と膝のバランスを確認しました"
            },
            created_by=self.user,
        )
        plan = TreatmentPlan.objects.create(
            patient=self.patient,
            appointment=appointment,
            clinical_note=note,
            title="右膝の施術計画",
            chief_complaint="右膝の違和感",
            status="active",
            created_by=self.user,
        )

        response = self.client.get(self._timeline_url())

        self.assertEqual(response.status_code, 200)
        event_types = {
            event["type"]
            for event in response.context["timeline_events"]
        }
        self.assertTrue({
            "予約",
            "カルテ",
            "初診録音",
            "通院施術録音",
            "姿勢分析",
            "施術計画",
            "患者向けレポート",
        }.issubset(event_types))
        self.assertContains(response, "治療履歴タイムライン")
        self.assertContains(
            response,
            reverse("staff:clinical_note_detail", args=[note.id]),
        )
        self.assertContains(
            response,
            reverse("posture_assessments:detail", args=[posture.id]),
        )
        self.assertContains(
            response,
            reverse("treatment_plans:plan_detail", args=[plan.id]),
        )
        self.assertContains(
            response,
            reverse("staff:patient_aftercare_report", args=[note.id]),
        )

    def test_other_clinic_notes_and_recordings_do_not_mix_into_timeline(self):
        other_start = timezone.now() - timedelta(days=2)
        other_appointment = Appointment.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            start_at=other_start,
            end_at=other_start + timedelta(hours=1),
            menu="OTHER_CLINIC_APPOINTMENT",
            status=Appointment.Status.COMPLETED,
        )
        InterviewRecording.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=other_appointment,
            status=InterviewRecording.Status.DONE,
            transcript_text="OTHER_CLINIC_RECORDING",
        )
        ClinicalNote.objects.create(
            appointment=other_appointment,
            patient=self.other_patient,
            extract_json={"overall_summary": "OTHER_CLINIC_NOTE"},
        )

        response = self.client.get(self._timeline_url())

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "OTHER_CLINIC_APPOINTMENT")
        self.assertNotContains(response, "OTHER_CLINIC_RECORDING")
        self.assertNotContains(response, "OTHER_CLINIC_NOTE")

    def test_patient_timeline_without_events_does_not_fail(self):
        response = self.client.get(self._timeline_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["timeline_events"], [])
        self.assertContains(response, "まだ治療履歴はありません")

    def test_other_clinic_patient_timeline_returns_404(self):
        response = self.client.get(self._timeline_url(self.other_patient))

        self.assertEqual(response.status_code, 404)

    def test_user_without_clinic_cannot_open_patient_timeline(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._timeline_url())

        self.assertEqual(response.status_code, 403)

    def test_patient_timeline_builder_does_not_use_file_path(self):
        source = inspect.getsource(staff_views.build_patient_timeline)

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

    def _share_create_url(self, note=None):
        return reverse(
            "staff:patient_share_token_create",
            args=[(note or self.note).id],
        )

    def _share_qr_url(self, share_token):
        return reverse(
            "staff:patient_share_token_qr",
            args=[share_token.id],
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

    def test_aftercare_report_is_not_public_without_staff_login(self):
        self.client.logout()

        response = self.client.get(self._report_url())

        self.assertEqual(response.status_code, 302)
        self.assertIn("/staff/login/", response.url)

    def test_aftercare_report_displays_print_pdf_and_line_guidance(self):
        response = self.client.get(self._report_url())

        self.assertContains(response, "印刷する")
        self.assertContains(response, "PDFに保存")
        self.assertContains(
            response,
            "共有URLを発行するとLINE送信用文面を作成できます",
        )
        self.assertNotContains(response, "LINEで送る文面")

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
        self.note.extract_json["internal_debug"] = "RAW_JSON_SECRET"
        self.note.extract_json["error_message"] = "PRIVATE_ERROR_MESSAGE"
        self.note.save(update_fields=["extract_json"])
        summary = dict(self.session.confirmed_summary_json)
        summary["meta"] = {
            "model": "gpt-private-model",
            "internal_trace": "MODEL_TRACE_SECRET",
            "traceback": "PRIVATE_TRACEBACK",
            "provider": "OpenAI",
        }
        self.session.confirmed_summary_json = summary
        self.session.save(update_fields=["confirmed_summary_json"])
        self.client.post(self._share_create_url())

        response = self.client.get(self._report_url())
        line_message = response.context["line_share_message"]

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "内部限定メモXYZ")
        self.assertNotContains(response, "内部評価メモXYZ")
        self.assertNotContains(response, "施術者向けメモ")
        self.assertNotContains(response, "RAW_JSON_SECRET")
        self.assertNotContains(response, "gpt-private-model")
        self.assertNotContains(response, "MODEL_TRACE_SECRET")
        self.assertNotContains(response, "PRIVATE_ERROR_MESSAGE")
        self.assertNotContains(response, "PRIVATE_TRACEBACK")
        self.assertNotContains(response, "OpenAI")
        self.assertNotContains(response, "生JSON")
        self.assertNotContains(response, "summary_json")
        self.assertNotIn("RAW_JSON_SECRET", line_message)
        self.assertNotIn("gpt-private-model", line_message)
        self.assertNotIn("MODEL_TRACE_SECRET", line_message)
        self.assertNotIn("PRIVATE_ERROR_MESSAGE", line_message)
        self.assertNotIn("PRIVATE_TRACEBACK", line_message)
        self.assertNotIn("OpenAI", line_message)

    def test_patient_detail_shows_latest_aftercare_report_link(self):
        response = self.client.get(
            reverse("staff:patient_detail", args=[self.patient.id])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(
            response,
            "最新の患者向け説明レポートを開く",
        )
        self.assertContains(response, self._report_url())

    def test_patient_detail_without_clinical_note_does_not_fail(self):
        patient_without_note = Patient.objects.create(
            clinic=self.clinic,
            card_no="POST-A-EMPTY",
            last_name="井上",
            first_name="健",
            last_name_kana="イノウエ",
            first_name_kana="ケン",
            birth_date=date(1985, 2, 1),
            phone="09000000039",
        )

        response = self.client.get(
            reverse(
                "staff:patient_detail",
                args=[patient_without_note.id],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(
            response,
            "最新の患者向け説明レポートを開く",
        )

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

    def test_staff_can_issue_share_url_for_own_clinic_note(self):
        response = self.client.post(self._share_create_url())

        self.assertRedirects(response, self._report_url())
        share_token = PatientShareToken.objects.get(clinical_note=self.note)
        self.assertEqual(share_token.clinic, self.clinic)
        self.assertEqual(share_token.patient, self.patient)
        self.assertEqual(share_token.appointment, self.appointment)
        self.assertEqual(
            share_token.purpose,
            PatientShareToken.Purpose.AFTERCARE_REPORT,
        )
        self.assertTrue(share_token.is_active)
        self.assertGreaterEqual(len(share_token.token), 40)
        self.assertGreater(share_token.expires_at, timezone.now())

        report_response = self.client.get(self._report_url())
        public_url = reverse(
            "patients:shared_patient_page",
            args=[share_token.token],
        )
        self.assertContains(report_response, "患者向け共有URL")
        self.assertContains(report_response, "有効")
        self.assertContains(report_response, "残り7日")
        self.assertContains(report_response, "アクセス回数：0回")
        self.assertContains(report_response, "最終アクセス：なし")
        self.assertContains(report_response, public_url)

    def test_active_share_token_displays_safe_line_message(self):
        self.client.post(self._share_create_url())
        share_token = PatientShareToken.objects.get(clinical_note=self.note)
        response = self.client.get(self._report_url())
        line_message = response.context["line_share_message"]
        share_url = "http://testserver" + reverse(
            "patients:shared_patient_page",
            args=[share_token.token],
        )
        expires_text = timezone.localtime(share_token.expires_at).strftime(
            "%Y年%m月%d日 %H:%M"
        )

        self.assertContains(response, "LINEで送る文面")
        self.assertContains(response, "メッセージをコピー")
        self.assertContains(response, "共有URLをコピー")
        self.assertContains(response, 'id="line-share-message"')
        self.assertContains(response, 'data-copy-target="line-share-message"')
        self.assertContains(response, "navigator.clipboard.writeText")
        self.assertContains(response, "document.execCommand('copy')")
        self.assertContains(response, "LINE送信 準備中")
        self.assertContains(response, "LINE公式アカウント連携は次フェーズで対応予定")
        self.assertContains(response, "Messaging APIによる自動送信")
        self.assertContains(response, "患者のLINE userId管理は未実装")
        self.assertIn(self.clinic.name, line_message)
        self.assertIn(
            f"{self.patient.last_name} {self.patient.first_name} 様",
            line_message,
        )
        self.assertIn(share_url, line_message)
        self.assertIn(expires_text, line_message)
        self.assertIn("URLの共有先にはご注意ください", line_message)
        self.assertIn("自己判断せず当院までご相談ください", line_message)

        for hidden_text in (
            "patient_id=",
            "clinic_id=",
            "clinical_note_id=",
            "staff_id=",
            "OpenAI",
            "AI usage",
            "生JSON",
            "traceback",
            "AI診断",
            "診断しました",
        ):
            self.assertNotIn(hidden_text, line_message)

    def test_line_message_is_hidden_before_share_url_is_issued(self):
        response = self.client.get(self._report_url())

        self.assertEqual(response.context["line_share_message"], "")
        self.assertNotContains(response, "LINEで送る文面")
        self.assertContains(
            response,
            "共有URLを発行するとLINE送信用文面を作成できます",
        )

    def test_reissuing_share_url_revokes_previous_token(self):
        self.client.post(self._share_create_url())
        first_token = PatientShareToken.objects.get(clinical_note=self.note)

        self.client.post(self._share_create_url())

        first_token.refresh_from_db()
        latest_token = PatientShareToken.objects.filter(
            clinical_note=self.note
        ).order_by("-created_at", "-id").first()
        self.assertFalse(first_token.is_active)
        self.assertTrue(latest_token.is_active)
        self.assertNotEqual(first_token.token, latest_token.token)

    def test_other_clinic_note_share_url_cannot_be_issued(self):
        response = self.client.post(self._share_create_url(self.other_note))

        self.assertEqual(response.status_code, 404)
        self.assertFalse(
            PatientShareToken.objects.filter(clinical_note=self.other_note).exists()
        )

        report_response = self.client.get(self._report_url(self.other_note))
        self.assertEqual(report_response.status_code, 404)
        self.assertNotContains(
            report_response,
            "LINEで送る文面",
            status_code=404,
        )

    def test_user_without_clinic_cannot_issue_share_url(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.post(self._share_create_url())

        self.assertEqual(response.status_code, 403)

    def test_staff_can_revoke_own_clinic_share_url(self):
        self.client.post(self._share_create_url())
        share_token = PatientShareToken.objects.get(clinical_note=self.note)
        revoke_url = reverse(
            "staff:patient_share_token_revoke",
            args=[self.note.id, share_token.id],
        )

        response = self.client.post(revoke_url)

        self.assertRedirects(response, self._report_url())
        share_token.refresh_from_db()
        self.assertFalse(share_token.is_active)

    def test_other_clinic_share_url_cannot_be_revoked(self):
        other_token = PatientShareToken.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            clinical_note=self.other_note,
            created_by=self.other_user,
        )
        revoke_url = reverse(
            "staff:patient_share_token_revoke",
            args=[self.other_note.id, other_token.id],
        )

        response = self.client.post(revoke_url)

        self.assertEqual(response.status_code, 404)
        other_token.refresh_from_db()
        self.assertTrue(other_token.is_active)

    def test_share_token_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views.staff_patient_share_token_create_view)
            + inspect.getsource(staff_views.staff_patient_share_token_revoke_view)
            + inspect.getsource(staff_views._build_line_share_message)
        )

        self.assertNotIn(".path", source)

    def test_valid_own_clinic_share_token_returns_qr_png(self):
        self.client.post(self._share_create_url())
        share_token = PatientShareToken.objects.get(clinical_note=self.note)

        response = self.client.get(self._share_qr_url(share_token))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertTrue(response.content.startswith(b"\x89PNG\r\n\x1a\n"))
        self.assertIn("no-store", response["Cache-Control"])
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("noindex", response["X-Robots-Tag"])
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")

    def test_qr_contains_only_public_share_url_as_payload(self):
        self.client.post(self._share_create_url())
        share_token = PatientShareToken.objects.get(clinical_note=self.note)
        expected_url = "http://testserver" + reverse(
            "patients:shared_patient_page",
            args=[share_token.token],
        )

        with patch(
            "apps.staff.views._render_qr_png",
            return_value=b"test-png",
        ) as renderer:
            response = self.client.get(self._share_qr_url(share_token))

        self.assertEqual(response.status_code, 200)
        renderer.assert_called_once_with(expected_url)
        self.assertNotIn(f"patient_id={self.patient.id}", expected_url)
        self.assertNotIn(f"clinical_note_id={self.note.id}", expected_url)
        self.assertNotIn(f"clinic_id={self.clinic.id}", expected_url)

    def test_other_clinic_share_token_qr_returns_404(self):
        other_token = PatientShareToken.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            appointment=self.other_appointment,
            clinical_note=self.other_note,
            created_by=self.other_user,
        )

        response = self.client.get(self._share_qr_url(other_token))

        self.assertEqual(response.status_code, 404)

    def test_revoked_share_token_qr_returns_404(self):
        self.client.post(self._share_create_url())
        share_token = PatientShareToken.objects.get(clinical_note=self.note)
        share_token.is_active = False
        share_token.save(update_fields=["is_active", "updated_at"])

        response = self.client.get(self._share_qr_url(share_token))
        report_response = self.client.get(self._report_url())

        self.assertEqual(response.status_code, 404)
        self.assertContains(report_response, "無効化済み")
        self.assertEqual(report_response.context["line_share_message"], "")
        self.assertNotContains(report_response, "LINEで送る文面")
        self.assertNotContains(report_response, share_token.token)
        self.assertContains(report_response, "共有URLを再発行するとLINE送信用文面を作成できます")
        self.assertNotContains(
            report_response,
            "今日の説明をスマホで見返せます",
        )

    def test_expired_share_token_qr_returns_404(self):
        self.client.post(self._share_create_url())
        share_token = PatientShareToken.objects.get(clinical_note=self.note)
        share_token.expires_at = timezone.now() - timedelta(seconds=1)
        share_token.save(update_fields=["expires_at", "updated_at"])

        response = self.client.get(self._share_qr_url(share_token))
        report_response = self.client.get(self._report_url())

        self.assertEqual(response.status_code, 404)
        self.assertContains(report_response, "期限切れ")
        self.assertEqual(report_response.context["line_share_message"], "")
        self.assertNotContains(report_response, "LINEで送る文面")
        self.assertNotContains(report_response, share_token.token)
        self.assertContains(report_response, "共有URLを再発行するとLINE送信用文面を作成できます")
        self.assertNotContains(
            report_response,
            "今日の説明をスマホで見返せます",
        )

    def test_user_without_clinic_cannot_open_share_token_qr(self):
        self.client.post(self._share_create_url())
        share_token = PatientShareToken.objects.get(clinical_note=self.note)
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._share_qr_url(share_token))

        self.assertEqual(response.status_code, 403)

    def test_qr_is_displayed_only_after_share_url_is_issued(self):
        unissued_response = self.client.get(self._report_url())

        self.assertNotContains(unissued_response, "今日の説明をスマホで見返せます")

        self.client.post(self._share_create_url())
        share_token = PatientShareToken.objects.get(clinical_note=self.note)
        issued_response = self.client.get(self._report_url())

        self.assertContains(issued_response, "今日の説明をスマホで見返せます")
        self.assertContains(issued_response, "カメラでQRコードを読み取ってください")
        self.assertContains(issued_response, "ご本人またはご家族への共有にご利用ください")
        self.assertContains(issued_response, "個人情報を含むため、共有先にはご注意ください")
        self.assertContains(issued_response, self.clinic.name)
        self.assertContains(
            issued_response,
            f"{self.patient.last_name} {self.patient.first_name} 様",
        )
        self.assertContains(
            issued_response,
            timezone.localtime(self.appointment.start_at).strftime("%Y年%m月%d日"),
        )
        self.assertContains(issued_response, "QRコードを印刷")
        self.assertContains(issued_response, self._share_qr_url(share_token))

    def test_qr_view_does_not_use_file_path(self):
        source = inspect.getsource(staff_views.staff_patient_share_token_qr_view)

        self.assertNotIn(".path", source)
