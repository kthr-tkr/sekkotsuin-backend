from datetime import date, datetime, time, timedelta
import inspect
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai_usage.models import AiUsageLog, ClinicAiPlan
from apps.appointments.models import Appointment
from apps.clinical_notes.models import ClinicalNote
from apps.clinics.models import Clinic, ClinicSettings, SalesRecord, TreatmentMenu
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

    def test_major_render_views_do_not_use_filefield_path(self):
        views = (
            staff_views.staff_dashboard_view,
            staff_views.staff_patient_detail_view,
            staff_views.staff_pre_treatment_check_view,
            staff_views.staff_clinical_note_detail_view,
            staff_views.staff_post_treatment_summary_view,
            staff_views.staff_patient_aftercare_report_view,
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
        self.assertContains(response, "カルテ案作成待ち")

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
        self.assertContains(response, "確認待ちのカルテ案はありません")
        self.assertContains(response, "処理中・要確認の録音はありません")
        self.assertContains(response, "本日の予約はありません")

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

    def test_user_without_clinic_cannot_open_kpi(self):
        self.client.force_login(self.no_clinic_user)

        response = self.client.get(self._url())

        self.assertEqual(response.status_code, 403)

    def test_kpi_builder_does_not_use_file_path(self):
        source = (
            inspect.getsource(staff_views.build_staff_kpi_context)
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

        self.assertContains(response, "--clinic-primary-color:#123456")
        self.assertContains(response, "--clinic-secondary-color:#234567")
        self.assertContains(response, "--clinic-accent-color:#345678")

    def test_clinic_settings_view_does_not_use_file_path(self):
        source = inspect.getsource(
            staff_views.staff_clinic_settings_view
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

    def test_aftercare_report_displays_print_pdf_and_line_guidance(self):
        response = self.client.get(self._report_url())

        self.assertContains(response, "印刷する")
        self.assertContains(response, "PDFに保存")
        self.assertContains(response, "LINE共有 準備中")
        self.assertContains(response, "LINE共有は今後対応予定です")
        self.assertContains(response, "disabled")

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

        response = self.client.get(self._report_url())

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
