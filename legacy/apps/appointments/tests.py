import inspect
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import include, path, reverse
from django.utils import timezone

from apps.appointments import patient_views
from apps.appointments.models import Appointment
from apps.clinics.models import Clinic
from apps.patients.models import Patient


urlpatterns = [
    path(
        "appointments/",
        include(("apps.appointments.urls", "appointments"), namespace="appointments"),
    ),
    path(
        "patients/",
        include(("apps.patients.urls", "patients"), namespace="patients"),
    ),
    path(
        "staff/",
        include(("apps.staff.urls", "staff"), namespace="staff"),
    ),
]


@override_settings(ROOT_URLCONF="apps.appointments.tests")
class LegacyPatientBookingSafetyTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.clinic = Clinic.objects.create(name="旧予約安全院")
        self.user = user_model.objects.create_user(
            username="legacy-patient",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PATIENT,
        )
        self.other_user = user_model.objects.create_user(
            username="legacy-other-patient",
            password="test-password",
            clinic=self.clinic,
            role=user_model.Role.PATIENT,
        )
        self.patient = Patient.objects.create(
            user=self.user,
            clinic=self.clinic,
            card_no="LEGACY-001",
            last_name="旧予約",
            first_name="本人",
            birth_date=date(1990, 1, 1),
            phone="09000006001",
        )
        self.other_patient = Patient.objects.create(
            user=self.other_user,
            clinic=self.clinic,
            card_no="LEGACY-002",
            last_name="別患者",
            first_name="本人",
            birth_date=date(1991, 1, 1),
            phone="09000006002",
        )
        start_at = timezone.now() + timedelta(days=7)
        self.appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=start_at,
            end_at=start_at + timedelta(minutes=30),
            menu="本人予約",
            status=Appointment.Status.BOOKED,
        )
        self.other_appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.other_patient,
            start_at=start_at + timedelta(hours=1),
            end_at=start_at + timedelta(hours=1, minutes=30),
            menu="他患者予約",
            status=Appointment.Status.BOOKED,
        )

    def test_legacy_completion_requires_login(self):
        response = self.client.get(
            reverse("appointments:book_complete", args=[self.appointment.id])
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/patients/login/", response.url)

    def test_legacy_completion_only_displays_own_appointment(self):
        self.client.force_login(self.user)

        own_response = self.client.get(
            reverse("appointments:book_complete", args=[self.appointment.id])
        )
        other_response = self.client.get(
            reverse("appointments:book_complete", args=[self.other_appointment.id])
        )

        self.assertEqual(own_response.status_code, 200)
        self.assertContains(own_response, "本人予約")
        self.assertEqual(other_response.status_code, 404)

    def test_legacy_intake_only_allows_own_appointment(self):
        self.client.force_login(self.user)

        response = self.client.get(
            reverse("appointments:book_intake", args=[self.other_appointment.id])
        )

        self.assertEqual(response.status_code, 404)

    def test_legacy_new_booking_redirects_to_safe_patient_booking(self):
        self.client.force_login(self.user)
        session = self.client.session
        session["booking_clinic_id"] = self.clinic.id
        session["booking_patient_id"] = self.patient.id
        session.save()

        response = self.client.get(reverse("appointments:book_new"))

        self.assertRedirects(response, reverse("patients:booking_calendar"))

    def test_legacy_patient_views_do_not_use_file_path(self):
        source = (
            inspect.getsource(patient_views.book_new)
            + inspect.getsource(patient_views.book_complete)
            + inspect.getsource(patient_views.book_intake)
        )
        self.assertNotIn(".path", source)
