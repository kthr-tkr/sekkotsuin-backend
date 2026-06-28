from datetime import date, timedelta
import inspect
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.ai_usage.models import AiUsageLog, ClinicAiPlan
from apps.appointments.models import Appointment
from apps.clinics.models import Clinic, ClinicSettings, SalesRecord, TreatmentMenu
from apps.owner_admin.forms import OwnerClinicCreateForm
from apps.owner_admin import views as owner_views
from apps.patients.models import Patient


class OwnerAdminAccessTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.clinic = Clinic.objects.create(name="通常院")
        self.owner = self.User.objects.create_superuser(
            username="owner-root",
            password="test-password",
            email="owner@example.com",
        )
        self.staff = self.User.objects.create_user(
            username="regular-staff",
            password="test-password",
            clinic=self.clinic,
            role=self.User.Role.ADMIN,
        )
        self.patient_user = self.User.objects.create_user(
            username="patient-user",
            password="test-password",
            clinic=self.clinic,
            role=self.User.Role.PATIENT,
        )

    def test_superuser_can_open_owner_dashboard(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse("owner_admin:dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CareFrow")
        self.assertContains(response, "全院管理ダッシュボード")

    def test_regular_staff_gets_403(self):
        self.client.force_login(self.staff)

        response = self.client.get(reverse("owner_admin:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_patient_user_gets_403(self):
        self.client.force_login(self.patient_user)

        response = self.client.get(reverse("owner_admin:dashboard"))

        self.assertEqual(response.status_code, 403)

    def test_anonymous_user_redirects_to_login(self):
        response = self.client.get(reverse("owner_admin:dashboard"))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/staff/login/", response["Location"])


class OwnerClinicManagementTests(TestCase):
    def setUp(self):
        self.User = get_user_model()
        self.owner = self.User.objects.create_superuser(
            username="owner-admin",
            password="test-password",
            email="owner-admin@example.com",
        )
        self.other_clinic = Clinic.objects.create(name="既存他院")
        self.other_staff = self.User.objects.create_user(
            username="other-clinic-staff",
            password="test-password",
            clinic=self.other_clinic,
            role=self.User.Role.PRACTITIONER,
        )
        self.client.force_login(self.owner)

    def _create_url(self):
        return reverse("owner_admin:clinic_create")

    def _valid_create_data(self, **overrides):
        data = {
            "clinic_name": "CareFrow中央院",
            "phone": "03-0000-0000",
            "address": "東京都中央区1-2-3",
            "primary_color": "#2563EB",
            "status": "active",
            "business_start_time": "09:00",
            "business_end_time": "20:00",
            "break_start_time": "13:00",
            "break_end_time": "15:00",
            "appointment_interval_minutes": "30",
            "closed_weekdays": ["sun"],
            "plan_key": "standard",
            "admin_last_name": "院長",
            "admin_first_name": "太郎",
            "admin_email": "clinic-admin@example.com",
            "admin_username": "clinic-admin",
            "admin_password": "InitialPass123!",
            "admin_role": self.User.Role.ADMIN,
        }
        data.update(overrides)
        return data

    def test_owner_clinic_list_is_displayed(self):
        response = self.client.get(reverse("owner_admin:clinic_list"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "院一覧")
        self.assertContains(response, "既存他院")

    def test_owner_clinic_create_creates_initial_records(self):
        response = self.client.post(self._create_url(), self._valid_create_data())

        clinic = Clinic.objects.get(name="CareFrow中央院")
        self.assertRedirects(
            response,
            reverse("owner_admin:clinic_detail", args=[clinic.id]),
        )
        settings = ClinicSettings.objects.get(clinic=clinic)
        plan = ClinicAiPlan.objects.get(clinic=clinic)
        admin_user = self.User.objects.get(username="clinic-admin")
        menus = TreatmentMenu.objects.filter(clinic=clinic)

        self.assertEqual(settings.phone, "03-0000-0000")
        self.assertEqual(settings.closed_weekdays, ["sun"])
        self.assertEqual(plan.plan_name, "standard")
        self.assertEqual(plan.included_minutes, 3000)
        self.assertEqual(plan.overage_unit_minutes, 1000)
        self.assertEqual(plan.overage_unit_price, 5000)
        self.assertEqual(admin_user.clinic, clinic)
        self.assertEqual(admin_user.role, self.User.Role.ADMIN)
        self.assertEqual(menus.count(), 4)
        self.assertTrue(menus.filter(name="初診").exists())

    def test_owner_clinic_create_can_generate_initial_password_once(self):
        response = self.client.post(
            self._create_url(),
            self._valid_create_data(
                admin_username="generated-admin",
                admin_email="generated-admin@example.com",
                admin_password="",
            ),
        )
        clinic = Clinic.objects.get(name="CareFrow中央院")

        detail_response = self.client.get(
            reverse("owner_admin:clinic_detail", args=[clinic.id])
        )

        self.assertEqual(response.status_code, 302)
        self.assertContains(detail_response, "初期パスワード")
        self.assertContains(detail_response, "generated-admin")

    def test_duplicate_username_is_rejected(self):
        self.User.objects.create_user(
            username="clinic-admin",
            password="test-password",
        )

        response = self.client.post(self._create_url(), self._valid_create_data())

        self.assertEqual(response.status_code, 200)
        self.assertIn("admin_username", response.context["form"].errors)
        self.assertFalse(Clinic.objects.filter(name="CareFrow中央院").exists())

    def test_invalid_plan_is_rejected(self):
        response = self.client.post(
            self._create_url(),
            self._valid_create_data(plan_key="light"),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("plan_key", response.context["form"].errors)
        self.assertFalse(Clinic.objects.filter(name="CareFrow中央院").exists())

    def test_transaction_failure_does_not_leave_partial_clinic(self):
        form = OwnerClinicCreateForm(
            self._valid_create_data(
                clinic_name="ロールバック院",
                admin_username="rollback-admin",
                admin_email="rollback-admin@example.com",
            )
        )
        self.assertTrue(form.is_valid(), form.errors)

        with patch(
            "apps.owner_admin.forms.TreatmentMenu.objects.create",
            side_effect=RuntimeError("menu create failed"),
        ):
            with self.assertRaises(RuntimeError):
                form.save()

        self.assertFalse(Clinic.objects.filter(name="ロールバック院").exists())
        self.assertFalse(self.User.objects.filter(username="rollback-admin").exists())

    def test_clinic_detail_displays_aggregate_values(self):
        clinic = Clinic.objects.create(name="集計院")
        user = self.User.objects.create_user(
            username="aggregate-staff",
            password="test-password",
            clinic=clinic,
            role=self.User.Role.PRACTITIONER,
        )
        patient = Patient.objects.create(
            clinic=clinic,
            card_no="OWN-A-001",
            last_name="集計",
            first_name="患者",
            birth_date=date(1990, 1, 1),
            phone="09000009999",
        )
        appointment = Appointment.objects.create(
            clinic=clinic,
            patient=patient,
            start_at=timezone.now(),
            end_at=timezone.now() + timedelta(hours=1),
            assigned_staff=user,
            created_by=user,
            status=Appointment.Status.BOOKED,
        )
        SalesRecord.objects.create(
            clinic=clinic,
            patient=patient,
            appointment=appointment,
            staff=user,
            treatment_date=timezone.localdate(),
            amount=5000,
            status=SalesRecord.Status.PAID,
        )
        AiUsageLog.objects.create(
            clinic=clinic,
            patient=patient,
            appointment=appointment,
            usage_type=AiUsageLog.UsageType.STT,
            status=AiUsageLog.Status.SUCCESS,
            billing_minutes=45,
            estimated_cost_yen=120,
            created_by=user,
        )

        response = self.client.get(reverse("owner_admin:clinic_detail", args=[clinic.id]))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "患者数")
        self.assertContains(response, "45分")
        self.assertContains(response, "¥120")
        self.assertNotContains(response, "traceback")

    def test_plan_setting_updates_existing_ai_plan(self):
        clinic = Clinic.objects.create(name="プラン変更院")

        response = self.client.post(
            reverse("owner_admin:clinic_plan", args=[clinic.id]),
            {
                "plan_key": "pro",
                "is_ai_enabled": "on",
                "allow_overage": "on",
                "hard_limit_minutes": "8000",
            },
        )

        self.assertRedirects(
            response,
            reverse("owner_admin:clinic_detail", args=[clinic.id]),
        )
        plan = ClinicAiPlan.objects.get(clinic=clinic)
        self.assertEqual(plan.plan_name, "pro")
        self.assertEqual(plan.monthly_base_fee, 49800)
        self.assertEqual(plan.included_minutes, 7000)
        self.assertEqual(plan.hard_limit_minutes, 8000)

    def test_owner_staff_create_is_fixed_to_url_clinic(self):
        clinic = Clinic.objects.create(name="スタッフ追加院")

        response = self.client.post(
            reverse("owner_admin:clinic_staff_create", args=[clinic.id]),
            {
                "last_name": "追加",
                "first_name": "担当",
                "email": "add-staff@example.com",
                "username": "add-staff",
                "password": "InitialPass123!",
                "role": self.User.Role.PRACTITIONER,
                "is_active": "on",
                "show_in_reservations": "on",
                "show_in_sales": "on",
            },
        )

        self.assertRedirects(
            response,
            reverse("owner_admin:clinic_detail", args=[clinic.id]),
        )
        staff = self.User.objects.get(username="add-staff")
        self.assertEqual(staff.clinic, clinic)
        self.assertNotEqual(staff.clinic, self.other_clinic)

    def test_owner_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(owner_views.owner_dashboard)
            + inspect.getsource(owner_views.owner_clinic_list)
            + inspect.getsource(owner_views.owner_clinic_create)
            + inspect.getsource(owner_views.owner_clinic_detail)
            + inspect.getsource(owner_views.owner_clinic_staff_create)
        )

        self.assertNotIn(".path", source)
