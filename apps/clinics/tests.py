from datetime import date, timedelta

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.clinical_notes.models import ClinicalNote
from apps.patients.models import Patient

from .models import Clinic, PatientShareToken


class PatientShareTokenModelTests(TestCase):
    def setUp(self):
        self.clinic = Clinic.objects.create(name="共有元院")
        self.other_clinic = Clinic.objects.create(name="共有対象外院")
        self.patient = Patient.objects.create(
            clinic=self.clinic,
            card_no="TOKEN-001",
            last_name="共有",
            first_name="患者",
            birth_date=date(1990, 1, 1),
            phone="09000007001",
        )
        self.other_patient = Patient.objects.create(
            clinic=self.other_clinic,
            card_no="TOKEN-002",
            last_name="他院",
            first_name="患者",
            birth_date=date(1991, 1, 1),
            phone="09000007002",
        )
        now = timezone.now()
        self.appointment = Appointment.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            start_at=now,
            end_at=now + timedelta(minutes=30),
        )
        self.note = ClinicalNote.objects.create(
            appointment=self.appointment,
            patient=self.patient,
        )

    def test_token_is_random_and_available_by_default(self):
        first = PatientShareToken.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            clinical_note=self.note,
        )
        second = PatientShareToken.objects.create(
            clinic=self.clinic,
            patient=self.patient,
            appointment=self.appointment,
            clinical_note=self.note,
        )

        self.assertNotEqual(first.token, second.token)
        self.assertGreaterEqual(len(first.token), 40)
        self.assertTrue(first.is_available)

    def test_other_clinic_patient_cannot_be_linked(self):
        with self.assertRaises(ValidationError):
            PatientShareToken.objects.create(
                clinic=self.clinic,
                patient=self.other_patient,
                appointment=self.appointment,
                clinical_note=self.note,
            )
