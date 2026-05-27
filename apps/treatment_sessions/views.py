from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.intakes.models import Intake
from apps.staff.decorators import staff_required

from .models import TreatmentSession
from apps.patients.models import Patient

def _same_clinic(user, clinic) -> bool:
    user_clinic = getattr(user, "clinic", None)

    if user.is_superuser and user_clinic is None:
        # 将来的には運営管理者用の院選択が必要。
        # 現段階では、superuser も clinic を持たせる運用が推奨。
        return False

    return user_clinic == clinic


@staff_required
def treatment_session_start_view(request, appointment_id):
    """
    予約から施術セッションを開始する。
    まずは TreatmentSession を作成し、詳細画面へ遷移する。
    """
    appointment = get_object_or_404(
        Appointment.objects.select_related("clinic", "patient"),
        pk=appointment_id,
    )

    if not _same_clinic(request.user, appointment.clinic):
        return HttpResponseForbidden("この院の予約にはアクセスできません。")

    intake = (
        Intake.objects
        .filter(appointment=appointment)
        .first()
    )

    session, created = TreatmentSession.objects.get_or_create(
        appointment=appointment,
        defaults={
            "clinic": appointment.clinic,
            "patient": appointment.patient,
            "intake": intake,
            "title": "施術セッション",
            "status": TreatmentSession.Status.PENDING,
            "created_by": request.user,
            "updated_by": request.user,
        },
    )

    if created:
        messages.success(request, "施術セッションを作成しました。")
    else:
        messages.info(request, "既存の施術セッションを開きます。")

    return redirect("treatment_sessions:detail", session_id=session.id)


@staff_required
def treatment_session_detail_view(request, session_id):
    session = get_object_or_404(
        TreatmentSession.objects.select_related(
            "clinic",
            "patient",
            "appointment",
            "intake",
            "clinical_note",
            "treatment_plan",
        ).prefetch_related("chunks"),
        pk=session_id,
    )

    if not _same_clinic(request.user, session.clinic):
        return HttpResponseForbidden("この施術セッションにはアクセスできません。")

    context = {
        "session": session,
        "chunks": session.chunks.all(),
    }

    return render(
        request,
        "treatment_sessions/session_detail.html",
        context,
    )
    
@staff_required
def treatment_session_start_for_patient_view(request, patient_id):
    """
    患者詳細画面から施術セッションを開始する。

    appointment がある場合:
      - 今日以降の直近予約を紐づける

    appointment がない場合:
      - 患者単位の施術セッションとして作成する
    """
    patient = get_object_or_404(
        Patient.objects.select_related("clinic"),
        pk=patient_id,
    )

    if not _same_clinic(request.user, patient.clinic):
        return HttpResponseForbidden("この院の患者にはアクセスできません。")

    now = timezone.now()

    appointment = (
        Appointment.objects
        .filter(
            clinic=patient.clinic,
            patient=patient,
            start_at__gte=now,
        )
        .order_by("start_at")
        .first()
    )

    if appointment is None:
        appointment = (
            Appointment.objects
            .filter(
                clinic=patient.clinic,
                patient=patient,
            )
            .order_by("-start_at")
            .first()
        )

    intake = None
    if appointment:
        intake = (
            Intake.objects
            .filter(appointment=appointment)
            .first()
        )

    # 既に進行中の施術セッションがあればそれを開く
    existing_session = (
        TreatmentSession.objects
        .filter(
            clinic=patient.clinic,
            patient=patient,
            status__in=[
                TreatmentSession.Status.PENDING,
                TreatmentSession.Status.RECORDING,
                TreatmentSession.Status.UPLOADED,
                TreatmentSession.Status.TRANSCRIBING,
                TreatmentSession.Status.SUMMARIZING,
            ],
        )
        .order_by("-created_at")
        .first()
    )

    if existing_session:
        messages.info(request, "進行中の施術セッションを開きます。")
        return redirect("treatment_sessions:detail", session_id=existing_session.id)

    session = TreatmentSession.objects.create(
        clinic=patient.clinic,
        patient=patient,
        appointment=appointment,
        intake=intake,
        title="施術セッション",
        status=TreatmentSession.Status.PENDING,
        created_by=request.user,
        updated_by=request.user,
    )

    messages.success(request, "施術セッションを作成しました。")
    return redirect("treatment_sessions:detail", session_id=session.id)