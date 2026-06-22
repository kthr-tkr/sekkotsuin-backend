import inspect
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.messages.storage.base import Message
from django.contrib.messages.storage.cookie import CookieStorage
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.clinical_notes.models import ClinicalNote
from apps.clinics.models import (
    Clinic,
    ClinicSettings,
    PatientShareToken,
    StaffLeave,
    StaffShift,
    TreatmentMenu,
)
from apps.patients import views as patient_views
from apps.patients.models import Patient


class PatientFacingSafetyTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.User = user_model
        self.clinic = Clinic.objects.create(name="患者予約院")
        self.other_clinic = Clinic.objects.create(name="他院")
        self.patient_user = user_model.objects.create_user(
            username="patient-safe",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PATIENT,
        )
        self.other_patient_user = user_model.objects.create_user(
            username="other-patient-safe",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PATIENT,
        )
        self.patient = Patient.objects.create(
            user=self.patient_user,
            clinic=self.clinic,
            card_no="SAFE-P-001",
            last_name="患者",
            first_name="本人",
            birth_date=date(1990, 1, 1),
            phone="09000005001",
        )
        self.other_patient = Patient.objects.create(
            user=self.other_patient_user,
            clinic=self.other_clinic,
            card_no="SAFE-P-002",
            last_name="他院",
            first_name="患者",
            birth_date=date(1991, 1, 1),
            phone="09000005002",
        )
        self.staff = user_model.objects.create_user(
            username="patient-booking-staff",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="予約",
            first_name="担当",
        )
        self.off_staff = user_model.objects.create_user(
            username="patient-booking-off",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="休み",
            first_name="担当",
        )
        self.leave_staff = user_model.objects.create_user(
            username="patient-booking-leave",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="休暇",
            first_name="担当",
        )
        self.other_staff = user_model.objects.create_user(
            username="other-patient-booking-staff",
            password="test-password",
            clinic=self.other_clinic,
            role=user_model.Role.PRACTITIONER,
            last_name="他院",
            first_name="担当",
        )
        self.admin = user_model.objects.create_user(
            username="patient-booking-admin",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.ADMIN,
            is_staff=True,
        )
        self.target_date = timezone.localdate() + timedelta(days=14)
        ClinicSettings.objects.create(
            clinic=self.clinic,
            business_start_time=time(9, 0),
            business_end_time=time(18, 0),
            break_start_time=time(13, 0),
            break_end_time=time(14, 0),
            appointment_interval_minutes=30,
        )
        self.menu = TreatmentMenu.objects.create(
            clinic=self.clinic,
            name="初診",
            price=5000,
            duration_minutes=60,
            is_active=True,
        )
        self.other_menu = TreatmentMenu.objects.create(
            clinic=self.other_clinic,
            name="他院メニュー",
            price=9000,
            duration_minutes=30,
            is_active=True,
        )
        for staff, status in (
            (self.staff, StaffShift.Status.WORKING),
            (self.off_staff, StaffShift.Status.OFF),
            (self.leave_staff, StaffShift.Status.WORKING),
        ):
            StaffShift.objects.create(
                clinic=self.clinic,
                staff=staff,
                date=self.target_date,
                status=status,
                start_time=time(9, 0) if status != StaffShift.Status.OFF else None,
                end_time=time(18, 0) if status != StaffShift.Status.OFF else None,
            )
        StaffLeave.objects.create(
            clinic=self.clinic,
            staff=self.leave_staff,
            leave_type=StaffLeave.LeaveType.PAID_LEAVE,
            start_date=self.target_date,
            end_date=self.target_date,
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
        self.client.force_login(self.patient_user)

    def _booking_day_response(self, **params):
        return self.client.get(
            reverse("patients:booking_day", args=[self.target_date.isoformat()]),
            params,
        )

    def _slot_starts(self, response, staff):
        item = next(
            row for row in response.context["staff_slots"] if row["staff"].id == staff.id
        )
        return {timezone.localtime(slot["start"]).strftime("%H:%M") for slot in item["slots"]}

    def _draft(self, **overrides):
        start_at = timezone.make_aware(datetime.combine(self.target_date, time(10, 0)))
        values = {
            "staff_id": self.staff.id,
            "staff_name": self.staff.get_full_name(),
            "start_at": start_at.isoformat(),
            "end_at": (start_at + timedelta(minutes=60)).isoformat(),
            "menu": self.menu.name,
            "treatment_plan_id": None,
            "treatment_menu_id": self.menu.id,
            "duration_minutes": 60,
            "clinic_id": self.clinic.id,
            "patient_id": self.patient.id,
        }
        values.update(overrides)
        session = self.client.session
        session["booking_draft"] = values
        session.save()

    def test_patient_booking_page_uses_only_own_clinic_staff(self):
        response = self._booking_day_response(treatment_menu_id=self.menu.id)

        self.assertEqual(response.status_code, 200)
        staff_ids = {row["staff"].id for row in response.context["staff_slots"]}
        self.assertIn(self.staff.id, staff_ids)
        self.assertNotIn(self.other_staff.id, staff_ids)
        self.assertNotContains(response, "他院 担当")

    def test_patient_slots_respect_hours_break_shift_leave_and_overlap(self):
        existing_start = timezone.make_aware(
            datetime.combine(self.target_date, time(10, 0))
        )
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            assigned_staff=self.staff,
            start_at=existing_start,
            end_at=existing_start + timedelta(minutes=60),
            menu="既存予約",
            status=Appointment.Status.BOOKED,
        )

        response = self._booking_day_response(treatment_menu_id=self.menu.id)

        self.assertEqual(response.status_code, 200)
        starts = self._slot_starts(response, self.staff)
        self.assertIn("09:00", starts)
        self.assertNotIn("10:00", starts)
        self.assertNotIn("13:00", starts)
        self.assertNotIn("17:30", starts)
        self.assertEqual(self._slot_starts(response, self.off_staff), set())
        self.assertEqual(self._slot_starts(response, self.leave_staff), set())

    def test_patient_booking_rejects_other_clinic_menu_and_staff(self):
        menu_response = self._booking_day_response(treatment_menu_id=self.other_menu.id)
        staff_response = self.client.post(
            reverse("patients:booking_review"),
            {
                "staff_token": patient_views._booking_staff_token(
                    self.other_clinic,
                    self.other_staff,
                ),
                "start_at": f"{self.target_date.isoformat()}T10:00",
                "menu": "初診",
            },
        )

        self.assertEqual(menu_response.status_code, 404)
        self.assertEqual(staff_response.status_code, 404)

    def test_patient_booking_rejects_invalid_staff_token(self):
        response = self.client.post(
            reverse("patients:booking_review"),
            {
                "staff_token": "invalid-token",
                "start_at": f"{self.target_date.isoformat()}T10:00",
                "menu": "初診",
            },
        )

        self.assertEqual(response.status_code, 404)

    def test_patient_booking_html_does_not_expose_plain_staff_id_field(self):
        response = self._booking_day_response(treatment_menu_id=self.menu.id)

        self.assertContains(response, 'name="staff_token"')
        self.assertNotContains(response, 'name="staff_id"')

    def test_patient_booking_confirm_rechecks_and_creates_own_clinic_appointment(self):
        self._draft()

        response = self.client.post(reverse("patients:booking_confirm"))

        self.assertEqual(response.status_code, 302)
        appointment = Appointment.objects.get(patient=self.patient)
        self.assertEqual(appointment.clinic, self.clinic)
        self.assertEqual(appointment.assigned_staff, self.staff)
        self.assertEqual(
            int((appointment.end_at - appointment.start_at).total_seconds() / 60),
            60,
        )

    def test_patient_booking_confirm_rejects_slot_taken_after_review(self):
        self._draft()
        start_at = timezone.make_aware(datetime.combine(self.target_date, time(10, 0)))
        Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            assigned_staff=self.staff,
            start_at=start_at,
            end_at=start_at + timedelta(minutes=60),
            menu="先約",
            status=Appointment.Status.BOOKED,
        )

        response = self.client.post(reverse("patients:booking_confirm"))

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Appointment.objects.filter(clinic=self.clinic).count(), 1)

    def test_patient_cannot_open_other_patient_appointment_by_id(self):
        start_at = timezone.make_aware(datetime.combine(self.target_date, time(10, 0)))
        appointment = Appointment.objects.create(
            clinic=self.other_clinic,
            patient=self.other_patient,
            assigned_staff=self.other_staff,
            start_at=start_at,
            end_at=start_at + timedelta(minutes=30),
            menu="他院予約",
            status=Appointment.Status.BOOKED,
        )

        response = self.client.get(
            reverse("patients:booking_complete", args=[appointment.id])
        )

        self.assertEqual(response.status_code, 404)
        self.assertNotContains(response, "他院予約", status_code=404)

    def test_staff_booking_other_clinic_patient_returns_404(self):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse("patients:staff_booking_calendar", args=[self.other_patient.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_patient_booking_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(patient_views.booking_calendar_view)
            + inspect.getsource(patient_views.booking_day_view)
            + inspect.getsource(patient_views.booking_review_view)
            + inspect.getsource(patient_views.booking_confirm_view)
            + inspect.getsource(patient_views.booking_complete_view)
            + inspect.getsource(patient_views.staff_booking_calendar_view)
            + inspect.getsource(patient_views.staff_booking_day_view)
            + inspect.getsource(patient_views.staff_booking_confirm_view)
        )
        self.assertNotIn(".path", source)


class PatientMessageSafetyTests(TestCase):
    LOGIN_ERROR = "メールアドレスまたは診察券番号、もしくはパスワードが正しくありません。"

    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="患者通知テスト院")
        self.user = user_model.objects.create_user(
            username="patient-message-user",
            email="patient-message@example.com",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PATIENT,
        )
        patient_group, _ = Group.objects.get_or_create(name="patient")
        self.user.groups.add(patient_group)
        self.patient = Patient.objects.create(
            user=self.user,
            clinic=self.clinic,
            card_no="MSG-P-001",
            last_name="通知",
            first_name="患者",
            birth_date=date(1990, 1, 1),
            phone="09000007001",
        )

    def _set_message_cookie(self, text, level=messages.ERROR):
        request = RequestFactory().get("/")
        request.COOKIES = {}
        storage = CookieStorage(request)
        response = HttpResponse()
        storage._store([Message(level, text)], response)
        for key, morsel in response.cookies.items():
            self.client.cookies[key] = morsel.value

    def test_failed_login_displays_error_only_on_login_page(self):
        response = self.client.post(
            reverse("patients:login"),
            {"login_id": self.user.email, "password": "wrong"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.LOGIN_ERROR)
        self.assertContains(response, "data-patient-login-messages")

    def test_successful_login_discards_previous_login_error(self):
        self._set_message_cookie(self.LOGIN_ERROR)

        response = self.client.post(
            reverse("patients:login"),
            {"login_id": self.user.email, "password": "test-password"},
            follow=True,
        )

        self.assertRedirects(response, reverse("patients:dashboard"))
        self.assertNotContains(response, self.LOGIN_ERROR)

    def test_dashboard_hides_login_and_staff_operation_messages(self):
        self.client.force_login(self.user)
        for hidden_message in (
            self.LOGIN_ERROR,
            "スタッフを登録しました。",
            "施術メニューを登録しました。",
            "院設定を保存しました。",
        ):
            self._set_message_cookie(hidden_message)
            response = self.client.get(reverse("patients:dashboard"))
            self.assertEqual(response.status_code, 200)
            self.assertNotContains(response, hidden_message)

        self.assertNotContains(response, self.user.username)
        self.assertContains(response, "通知 患者 様")

    def test_patient_operation_message_is_compact_and_visible(self):
        self.client.force_login(self.user)
        self._set_message_cookie("登録情報を更新しました。", messages.SUCCESS)

        response = self.client.get(reverse("patients:dashboard"))

        self.assertContains(response, "登録情報を更新しました。")
        self.assertContains(response, "patient-toast-container")

    def test_logout_discards_old_messages_and_shows_only_logout_notice(self):
        self.client.force_login(self.user)
        self._set_message_cookie("スタッフを登録しました。")

        response = self.client.get(reverse("patients:logout"), follow=True)

        self.assertContains(response, "ログアウトしました。")
        self.assertNotContains(response, "スタッフを登録しました。")

    def test_patient_message_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(patient_views.patient_login_view)
            + inspect.getsource(patient_views.patient_dashboard_view)
            + inspect.getsource(patient_views.shared_patient_page_view)
        )
        self.assertNotIn(".path", source)


class SharedAftercareReportTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="共有テスト院")
        self.other_clinic = Clinic.objects.create(name="共有対象外院")
        self.staff = user_model.objects.create_user(
            username="share-report-staff-secret",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PRACTITIONER,
        )
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="SHARE-INTERNAL-001",
            last_name="共有",
            first_name="太郎",
            birth_date=date(1987, 5, 1),
            phone="09000006001",
        )
        start_at = timezone.now() - timedelta(hours=1)
        self.appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            assigned_staff=self.staff,
            created_by=self.staff,
            start_at=start_at,
            end_at=start_at + timedelta(minutes=45),
            menu="身体バランス施術",
            status=Appointment.Status.COMPLETED,
            notes="APPOINTMENT_INTERNAL_MEMO",
        )
        self.note = ClinicalNote.objects.create(
            appointment=self.appointment,
            patient=self.patient,
            soap_json={
                "S": ["肩まわりが気になる"],
                "O": ["肩の動きを確認"],
                "A": ["肩まわりに負担の傾向"],
                "P": ["次回も動きを確認"],
            },
            extract_json={
                "overall_summary": "本日は肩まわりの動きを中心に確認しました",
                "performed_treatments": ["肩まわりの施術"],
                "home_care": ["無理のない範囲で肩を動かしてください"],
                "items_to_check_next_time": ["肩の動きの変化"],
                "safety_notes": ["痛みが強い場合は中止してください"],
                "internal_debug": "RAW_JSON_SECRET",
                "error_message": "PRIVATE_ERROR_MESSAGE",
                "model": "gpt-private-model",
                "provider": "OpenAI",
            },
            followups_json=[],
            registered_by=self.staff,
            updated_by=self.staff,
        )
        self.share_token = PatientShareToken.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            clinical_note=self.note,
            created_by=self.staff,
        )

        other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="OTHER-SHARE-001",
            last_name="他院秘密",
            first_name="患者",
            birth_date=date(1990, 1, 1),
            phone="09000006002",
        )
        other_start = timezone.now() + timedelta(days=1)
        Appointment.objects.create(
            clinic=self.other_clinic,
            patient=other_patient,
            start_at=other_start,
            end_at=other_start + timedelta(minutes=30),
            menu="OTHER_CLINIC_SECRET_MENU",
            status=Appointment.Status.BOOKED,
        )

    def _shared_url(self, token=None):
        return reverse(
            "patients:shared_patient_page",
            args=[token or self.share_token.token],
        )

    def _set_message_cookie(self, text):
        request = RequestFactory().get("/")
        request.COOKIES = {}
        storage = CookieStorage(request)
        response = HttpResponse()
        storage._store([Message(messages.ERROR, text)], response)
        for key, morsel in response.cookies.items():
            self.client.cookies[key] = morsel.value

    def test_valid_token_displays_shared_aftercare_report_without_login(self):
        response = self.client.get(self._shared_url())

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "patients/shared_aftercare_report.html")
        self.assertContains(response, "施術後説明レポート")
        self.assertContains(response, "本日は肩まわりの動きを中心に確認しました")
        self.assertContains(response, "無理のない範囲で肩を動かしてください")
        self.assertEqual(response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("noindex", response["X-Robots-Tag"])

    def test_shared_pages_never_render_django_operation_messages(self):
        internal_message = "スタッフを登録しました。TOKEN_INTERNAL_MESSAGE"
        self._set_message_cookie(internal_message)

        valid_response = self.client.get(self._shared_url())
        self._set_message_cookie(internal_message)
        invalid_response = self.client.get(
            reverse("patients:shared_patient_page", args=["invalid-token"])
        )

        self.assertNotContains(valid_response, internal_message)
        self.assertNotContains(invalid_response, internal_message, status_code=404)
        self.assertIn("no-store", valid_response["Cache-Control"])
        self.assertIn("noindex", valid_response["X-Robots-Tag"])
        self.assertEqual(valid_response["Referrer-Policy"], "no-referrer")
        self.assertIn("no-store", invalid_response["Cache-Control"])
        self.assertIn("noindex", invalid_response["X-Robots-Tag"])
        self.assertEqual(invalid_response["Referrer-Policy"], "no-referrer")

    def test_missing_or_invalid_token_does_not_display_report(self):
        missing_response = self.client.get("/patients/share/")
        invalid_response = self.client.get(
            reverse("patients:shared_patient_page", args=["invalid-token"])
        )

        self.assertEqual(missing_response.status_code, 404)
        self.assertEqual(invalid_response.status_code, 404)
        self.assertTemplateUsed(
            invalid_response,
            "patients/shared_page_unavailable.html",
        )
        self.assertContains(
            invalid_response,
            "ページを表示できません",
            status_code=404,
        )
        self.assertContains(
            invalid_response,
            "URLの有効期限が切れているか、現在利用できません",
            status_code=404,
        )
        self.assertNotContains(
            invalid_response,
            "このtokenは期限切れです",
            status_code=404,
        )
        self.assertNotContains(
            invalid_response,
            "この患者のレポートは存在します",
            status_code=404,
        )
        self.assertIn("no-store", invalid_response["Cache-Control"])
        self.assertEqual(invalid_response["Referrer-Policy"], "no-referrer")
        self.assertIn("noindex", invalid_response["X-Robots-Tag"])

    def test_expired_token_does_not_display_report(self):
        self.share_token.expires_at = timezone.now() - timedelta(seconds=1)
        self.share_token.save(update_fields=["expires_at", "updated_at"])

        response = self.client.get(self._shared_url())

        self.assertEqual(response.status_code, 404)
        self.assertContains(
            response,
            "ページを表示できません",
            status_code=404,
        )

    def test_revoked_token_does_not_display_report(self):
        self.share_token.is_active = False
        self.share_token.save(update_fields=["is_active", "updated_at"])

        response = self.client.get(self._shared_url())

        self.assertEqual(response.status_code, 404)
        self.assertContains(
            response,
            "ページを表示できません",
            status_code=404,
        )

    def test_access_updates_count_and_last_accessed_at(self):
        self.client.get(self._shared_url())

        self.share_token.refresh_from_db()
        self.assertEqual(self.share_token.access_count, 1)
        self.assertIsNotNone(self.share_token.last_accessed_at)

    def test_shared_report_does_not_expose_internal_information_or_ids(self):
        response = self.client.get(self._shared_url())

        for hidden_text in (
            "APPOINTMENT_INTERNAL_MEMO",
            "RAW_JSON_SECRET",
            "PRIVATE_ERROR_MESSAGE",
            "gpt-private-model",
            "OpenAI",
            "share-report-staff-secret",
            "SHARE-INTERNAL-001",
            "OTHER_CLINIC_SECRET_MENU",
            "他院秘密",
            "生JSON",
            "内部メモ",
            "施術者用メモ",
            "staff_id",
            "clinic_id",
            "patient_id",
        ):
            self.assertNotContains(response, hidden_text)

    def test_shared_report_view_does_not_use_file_path(self):
        source = inspect.getsource(patient_views.shared_patient_page_view)

        self.assertNotIn(".path", source)
