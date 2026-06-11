from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.clinics.models import Clinic
from apps.patients.models import Patient

from .models import TreatmentSession


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
