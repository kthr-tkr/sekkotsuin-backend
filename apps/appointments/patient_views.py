# apps/appointments/patient_views.py
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.clinics.models import Clinic
from apps.intakes.models import Intake
from apps.patients.models import Patient
from .models import Appointment
from .patient_forms import PatientLookupForm, IntakeForm


def _get_default_clinic():
    # 院を特定できない公開URLで、複数院から先頭を暗黙選択しない。
    clinics = list(Clinic.objects.order_by("id")[:2])
    return clinics[0] if len(clinics) == 1 else None


def _normalize_phone(phone: str) -> str:
    return "".join(ch for ch in (phone or "") if ch.isdigit())


def _authenticated_patient(request):
    if not request.user.is_authenticated:
        return None
    return Patient.objects.select_related("clinic").filter(user=request.user).first()


def _clear_booking_session(request):
    keys = [
        "booking_patient_id",
        "booking_clinic_id",
        "pending_booking_last_name",
        "pending_booking_first_name",
        "pending_booking_phone",
        "pending_booking_clinic_id",
    ]
    for key in keys:
        request.session.pop(key, None)


@require_http_methods(["GET", "POST"])
def book_start(request):
    if _authenticated_patient(request):
        return redirect("patients:booking_calendar")

    clinic = _get_default_clinic()
    if not clinic:
        return render(
            request,
            "appointments/book_error.html",
            {"message": "院情報を確認できません。院から案内された予約ページをご利用ください。"},
        )

    form = PatientLookupForm(request.POST or None)

    if request.method == "POST" and form.is_valid():
        cleaned = form.cleaned_data
        phone = _normalize_phone(cleaned["phone"])
        last_name = cleaned["last_name"].strip()
        first_name = cleaned["first_name"].strip()

        patient = Patient.objects.filter(
            clinic=clinic,
            phone=phone,
            last_name=last_name,
            first_name=first_name,
        ).first()

        if not patient:
            # ここで雑に Patient を作らない
            # Patient に必須項目があるため、新規登録画面に誘導する
            request.session["pending_booking_last_name"] = last_name
            request.session["pending_booking_first_name"] = first_name
            request.session["pending_booking_phone"] = phone
            request.session["pending_booking_clinic_id"] = clinic.id

            # 患者新規登録画面のURL名に合わせて変更してください
            return redirect("patients:register")

        request.session["booking_patient_id"] = patient.id
        request.session["booking_clinic_id"] = clinic.id
        return redirect(
            f"{reverse('patients:login')}?next={reverse('patients:booking_calendar')}"
        )

    return render(
        request,
        "appointments/book_start.html",
        {
            "form": form,
            "clinic": clinic,
        },
    )


@login_required(login_url="/patients/login/")
@require_http_methods(["GET", "POST"])
def book_new(request):
    clinic_id = request.session.get("booking_clinic_id")
    patient_id = request.session.get("booking_patient_id")

    if not clinic_id or not patient_id:
        return redirect("appointments:book_start")

    get_object_or_404(
        Patient.objects.select_related("clinic"),
        pk=patient_id,
        clinic_id=clinic_id,
        user=request.user,
    )
    _clear_booking_session(request)
    # 旧フォームはシフト・休暇判定を持たないため、共通判定済みの患者予約へ統合する。
    return redirect("patients:booking_calendar")


@login_required(login_url="/patients/login/")
def book_complete(request, appointment_id):
    patient = get_object_or_404(Patient, user=request.user)
    appt = get_object_or_404(
        Appointment,
        pk=appointment_id,
        clinic=patient.clinic,
        patient=patient,
    )

    # 予約完了後に最低限の予約セッションを整理
    request.session.pop("booking_patient_id", None)
    request.session.pop("booking_clinic_id", None)

    return render(
        request,
        "appointments/book_complete.html",
        {
            "appointment": appt,
        },
    )


@login_required(login_url="/patients/login/")
@require_http_methods(["GET", "POST"])
def book_intake(request, appointment_id):
    patient = get_object_or_404(Patient, user=request.user)
    appt = get_object_or_404(
        Appointment,
        pk=appointment_id,
        clinic=patient.clinic,
        patient=patient,
    )

    intake, created = Intake.objects.get_or_create(
        appointment=appt,
        defaults={
            "clinic": appt.clinic,
            "patient": appt.patient,
            "submitted_at": timezone.now(),
        },
    )

    # 念のため既存 intake の整合性を補正
    changed = False
    if intake.clinic_id != appt.clinic_id:
        intake.clinic = appt.clinic
        changed = True
    if intake.patient_id != appt.patient_id:
        intake.patient = appt.patient
        changed = True
    if not intake.submitted_at:
        intake.submitted_at = timezone.now()
        changed = True
    if changed and request.method == "GET":
        intake.save()

    form = IntakeForm(request.POST or None, instance=intake)

    if request.method == "POST" and form.is_valid():
        obj = form.save(commit=False)
        obj.clinic = appt.clinic
        obj.patient = appt.patient
        if not obj.submitted_at:
            obj.submitted_at = timezone.now()
        obj.save()

        return redirect("appointments:book_complete", appointment_id=appt.id)

    return render(
        request,
        "appointments/book_intake.html",
        {
            "appointment": appt,
            "intake": intake,
            "form": form,
        },
    )
