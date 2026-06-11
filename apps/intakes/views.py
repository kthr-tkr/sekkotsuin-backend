import json
from django.shortcuts import render, get_object_or_404, redirect
from django.contrib.auth.decorators import login_required
from apps.appointments.models import Appointment
from django.utils import timezone
from .forms import IntakeAdminForm
from .models import Intake
from .forms import (
    IntakeStep1Form, IntakeStep2Form, IntakeStep3Form, IntakeStep4Form, IntakeStartForm, FollowupIntakeForm
)

from django.http import JsonResponse
from django.views.decorators.http import require_POST, require_http_methods
from .models import InterviewRecording
from .services.ai_summarizer import summarize_transcript
from .services.intake_sync import sync_intake_columns_from_summary
from django.urls import reverse

from pathlib import Path
from openai import OpenAI
from django.db import transaction
from django.db.models import Q
from django.contrib import messages
from django.conf import settings
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseBadRequest
from .services.ai_summarizer import SUMMARY_JSON_SCHEMA

from .services.stt import DEFAULT_STT_MODEL, run_stt
from apps.staff.decorators import staff_required

from apps.ai_usage.models import AiUsageLog
from apps.ai_usage.services import (
    build_ai_usage_summary,
    create_ai_usage_log_for_recording,
)
from apps.clinical_notes.models import ClinicalNote

# apps/intakes/views.py

def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str):
        lines = [s.strip("・- \t") for s in v.splitlines()]
        return [s for s in lines if s]
    return [str(v)]


def _get_staff_clinic(request):
    clinic = getattr(request.user, "clinic", None)
    if clinic is None or getattr(request.user, "clinic_id", None) != clinic.id:
        return None
    return clinic


def _recordings_for_clinic(clinic):
    return (
        InterviewRecording.objects
        .select_related("clinic", "patient", "appointment", "intake")
        .filter(
            clinic=clinic,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .filter(Q(intake__isnull=True) | Q(intake__clinic=clinic))
    )


def _get_registered_clinical_note(recording, clinic):
    return (
        ClinicalNote.objects
        .select_related("patient", "appointment")
        .filter(
            recording=recording,
            patient=recording.patient,
            patient__clinic=clinic,
            appointment=recording.appointment,
            appointment__clinic=clinic,
        )
        .order_by("-updated_at")
        .first()
    )


def _clinical_note_matches_recording_summary(note, recording):
    summary = (
        recording.confirmed_summary_json
        if isinstance(recording.confirmed_summary_json, dict)
        else {}
    )
    if note is None or not summary or note.recording_id != recording.id:
        return False

    return (
        (note.soap_json or {}) == (summary.get("soap") or {})
        and (note.extract_json or {}) == (summary.get("extract") or {})
        and (note.followups_json or []) == (summary.get("followups") or [])
    )


def build_interview_recording_flow_state(
    recording,
    *,
    clinical_note_exists=False,
    clinical_note_is_current=False,
):
    has_audio = bool(recording.audio_file)
    has_transcript = bool((recording.transcript_text or "").strip())
    has_summary = bool(recording.summary_json)
    is_confirmed = bool(recording.confirmed_summary_json)
    is_transcribing = (
        recording.status == InterviewRecording.Status.TRANSCRIBING
    )
    is_summarizing = (
        recording.status == InterviewRecording.Status.SUMMARIZING
    )
    has_error = bool(
        recording.status == InterviewRecording.Status.FAILED
        or (recording.error_message or "").strip()
    )

    if has_error:
        key = "error"
        label = "エラーあり"
        tone = "error"
        next_action = (
            "エラー内容を確認し、必要に応じて文字起こしまたはカルテ案作成を再実行してください。"
        )
    elif is_transcribing:
        key = "transcribing"
        label = "文字起こし中"
        tone = "processing"
        next_action = "文字起こし処理中です。完了するまでお待ちください。"
    elif is_summarizing:
        key = "summarizing"
        label = "カルテ案作成中"
        tone = "processing"
        next_action = "録音内容からカルテ案を作成中です。完了するまでお待ちください。"
    elif clinical_note_exists and clinical_note_is_current:
        key = "registered"
        label = "カルテ登録済み"
        tone = "done"
        next_action = "カルテ詳細で登録内容を確認できます。"
    elif is_confirmed:
        key = "confirmed"
        label = "確認済み"
        tone = "confirmed"
        next_action = "確認済みのカルテ案をカルテへ登録してください。"
    elif has_summary:
        key = "confirmation_waiting"
        label = "確認待ち"
        tone = "attention"
        next_action = "カルテ案を確認・修正してください。"
    elif has_transcript:
        key = "summary_waiting"
        label = "カルテ案作成待ち"
        tone = "attention"
        next_action = "録音内容からカルテ案を作成してください。"
    elif has_audio:
        key = "transcription_waiting"
        label = "文字起こし待ち"
        tone = "attention"
        next_action = "保存済みの録音データを文字起こししてください。"
    else:
        key = "recording_ready"
        label = "録音準備中"
        tone = "ready"
        next_action = "初診・問診内容を録音してください。"

    recording_stage = "done" if has_audio else "current"
    transcription_stage = "pending"
    summary_stage = "pending"
    confirmation_stage = "pending"
    registration_stage = "pending"

    if is_transcribing:
        transcription_stage = "current"
    elif has_transcript:
        transcription_stage = "done"
    elif has_audio:
        transcription_stage = "current"

    if is_summarizing:
        summary_stage = "current"
    elif has_summary:
        summary_stage = "done"
    elif has_transcript:
        summary_stage = "current"

    if is_confirmed:
        confirmation_stage = "done"
    elif has_summary:
        confirmation_stage = "current"

    if clinical_note_exists and clinical_note_is_current:
        registration_stage = "done"
    elif is_confirmed:
        registration_stage = "current"

    if has_error:
        if registration_stage == "current":
            registration_stage = "error"
        elif confirmation_stage == "current":
            confirmation_stage = "error"
        elif summary_stage == "current":
            summary_stage = "error"
        elif transcription_stage == "current":
            transcription_stage = "error"
        else:
            recording_stage = "error"

    return {
        "key": key,
        "label": label,
        "tone": tone,
        "next_action": next_action,
        "has_audio": has_audio,
        "has_transcript": has_transcript,
        "has_summary": has_summary,
        "is_confirmed": is_confirmed,
        "is_registered": clinical_note_exists and clinical_note_is_current,
        "clinical_note_exists": clinical_note_exists,
        "has_error": has_error,
        "is_processing": is_transcribing or is_summarizing,
        "can_process": (
            (has_audio or has_transcript)
            and not is_transcribing
            and not is_summarizing
        ),
        "can_confirm": has_summary and not is_summarizing,
        "can_register": (
            is_confirmed
            and not is_transcribing
            and not is_summarizing
            and not (clinical_note_exists and clinical_note_is_current)
        ),
        "stages": [
            {"label": "録音", "status": recording_stage},
            {"label": "文字起こし", "status": transcription_stage},
            {"label": "カルテ案", "status": summary_stage},
            {"label": "確認", "status": confirmation_stage},
            {"label": "カルテ登録", "status": registration_stage},
        ],
        "error_messages": (
            [(recording.error_message or "").strip()]
            if (recording.error_message or "").strip()
            else []
        ),
    }



@login_required
def intake_create_view(request, appointment_id):
    appt = get_object_or_404(Appointment, pk=appointment_id)
    # TODO: form保存
    if request.method == "POST":
        # 保存して…
        return redirect("patients:booking_complete", appointment_id=appt.id)

    return render(request, "intakes/intake_form.html", {"appointment": appt})



@login_required
def intake_staff_edit(request, appointment_id):
    appt = get_object_or_404(Appointment, pk=appointment_id)

    # 🔐スタッフ権限チェック（例）
    # if not request.user.is_staff:
    #     return redirect("patients:home")

    intake, _ = Intake.objects.get_or_create(
        appointment=appt,
        defaults={"clinic": appt.clinic, "patient": appt.patient, "payload": {}},
    )

    if request.method == "POST":
        form = IntakeAdminForm(request.POST, instance=intake)
        if form.is_valid():
            intake = form.save(commit=False)
            form.apply_payload(intake)
            intake.save()
            return redirect("staff:appointment_detail", appointment_id=appt.id)
    else:
        initial = IntakeAdminForm.initial_from_payload(intake)
        form = IntakeAdminForm(instance=intake, initial=initial)

    return render(request, "intakes/staff/intake_edit.html", {"appointment": appt, "form": form})


@login_required
def intake_done(request, appointment_id):
    appt = get_object_or_404(Appointment, pk=appointment_id)
    return render(
        request,
        "intakes/patient/intake_done.html",
        {"appointment": appt}
    )


STEP_FORMS = {
    1: IntakeStep1Form,
    2: IntakeStep2Form,
    3: IntakeStep3Form,
    4: IntakeStep4Form,
}
LAST_STEP = 4

STEP_TITLES = {
    1: "ご登録情報の確認",
    2: "主な症状・経過",
    3: "患部・症状の状態",
    4: "確認・同意",
}

# STEP_FORMS / LAST_STEP / STEP_TITLES は 4ステップ版にしておく
# STEP_FORMS = {1: IntakeStep1Form, 2: IntakeStep2Form, 3: IntakeStep3Form, 4: IntakeStep4Form}
# LAST_STEP = 4
# STEP_TITLES = {1:"...",2:"...",3:"...",4:"..."}

@login_required
def intake_wizard(request, appointment_id):
    appt = get_object_or_404(Appointment, pk=appointment_id)

    try:
        _must_own_appointment(request.user, appt)
    except PermissionError:
        return HttpResponseForbidden("この予約にはアクセスできません。")

    intake, _ = Intake.objects.get_or_create(
        appointment=appt,
        defaults={"clinic": appt.clinic, "patient": appt.patient, "payload": {}},
    )

    payload = intake.payload or {}
    meta = payload.get("meta", {}) or {}

    # ✅ step決定：指定が無ければ「前回の続き」へ
    if "step" in request.GET:
        step = int(request.GET.get("step", 1))
    else:
        step = int(meta.get("current_step", 1) or 1)

    step = max(1, min(step, LAST_STEP))
    FormClass = STEP_FORMS[step]

    if request.method == "POST":
        form = FormClass(request.POST)
        if form.is_valid():
            cd = form.cleaned_data

            if "visit_type" not in payload:
                payload["visit_type"] = "new_issue"

            if payload.get("visit_type") in ["new_issue", "unknown"]:
                payload["meta"] = {
                    **(payload.get("meta", {}) or {}),
                    "intake_mode": "normal",
                }

            # ① stepごとにpayload保存（そのまま保持）
            payload[f"step{step}"] = cd

            # ② meta更新（再開/進捗用）
            completed = set(meta.get("completed_steps", []))
            completed.add(step)
            next_step = step + 1

            payload["meta"] = {
                **meta,
                "current_step": min(next_step, LAST_STEP),
                "completed_steps": sorted(completed),
            }

            # ③ 一覧・検索用カラム同期（コアはStep2）
            if step == 2:
                intake.chief_complaint = cd.get("chief_complaint", "")
                intake.symptom_type = cd.get("symptom_type", "unknown")
                intake.onset = cd.get("since", "")

                if "visit_type" not in payload:
                    payload["visit_type"] = "new_issue"

            # ④ 概要用キーへ集約（任意だけど強い：スタッフ画面が超楽）
            # Step3: 症状（患部/強さ/性質）
            # ④ 概要用キーへ集約
            # Step3: 症状（患部/強さ/性質）
            if step == 3:
                areas = cd.get("areas") or []
                qualities = cd.get("qualities") or []

                payload["symptoms"] = {
                    "areas": areas,
                    "other_area_text": cd.get("other_area_text", ""),
                    "severity": cd.get("severity"),
                    "qualities": qualities,
                    "other_quality_text": cd.get("other_quality_text", ""),
                    "free_text": cd.get("free_text", ""),
                }

                # 病院側問診画面・AI要約・カルテ登録で使いやすい共通形式
                step2 = payload.get("step2", {}) or {}

                payload["extract"] = {
                    "chief_complaint": step2.get("chief_complaint", ""),
                    "onset": step2.get("since", ""),
                    "trigger": step2.get("trigger", ""),
                    "severity_0_10": cd.get("severity"),
                    "symptom_type": step2.get("symptom_type", ""),
                    "locations": areas,
                    "qualities": qualities,
                    "symptom_details": cd.get("symptom_details") or [],
                }

            # Step4: 既往等 + 同意
            if step == 4:
                payload["history"] = {
                    "other_clinic": cd.get("other_clinic"),
                    "other_clinic_note": cd.get("other_clinic_note", ""),
                    "taking_meds": cd.get("taking_meds"),
                    "meds_note": cd.get("meds_note", ""),
                    "past_history": cd.get("past_history"),
                    "history_note": cd.get("history_note", ""),
                    "final_note": cd.get("final_note", ""),
                }
                payload["consent"] = {"agreed": bool(cd.get("consent_agreed"))}

                # ✅ 最終送信時点で病院側と同じ extract 形式を作る
                step2 = payload.get("step2", {}) or {}
                step3 = payload.get("step3", {}) or {}

                payload["extract"] = {
                    "chief_complaint": step2.get("chief_complaint", ""),
                    "onset": step2.get("since", ""),
                    "trigger": step2.get("trigger", ""),
                    "worse_when": step2.get("worse_when", ""),
                    "better_when": step2.get("better_when", ""),
                    "severity_0_10": step3.get("severity"),
                    "symptom_type": step2.get("symptom_type", ""),
                    "locations": step3.get("areas") or [],
                    "qualities": step3.get("qualities") or [],
                }

            intake.payload = payload

            # ✅ 最終stepなら完了へ
            if step >= LAST_STEP:
                intake.submitted_at = timezone.now()
                intake.payload = payload
                intake.save()

                appt.status = Appointment.Status.BOOKED
                appt.save(update_fields=["status"])

                messages.success(request, "Web問診が完了し、予約が確定しました。")
                return redirect("intakes:intake_done", appointment_id=appointment_id)

            intake.save()
            return redirect(f"{request.path}?step={next_step}")
    else:
        # GET：既入力があれば復元
        initial = payload.get(f"step{step}", {})
        form = FormClass(initial=initial)

    progress = int(step / LAST_STEP * 100)
    patient = appt.patient

    context = {
        "appointment": appt,
        "intake": intake,
        "patient": patient,
        "step": step,
        "last_step": LAST_STEP,
        "progress": progress,
        "step_title": STEP_TITLES.get(step, f"Step {step}"),
        "form": form,
        "visit_type": payload.get("visit_type", "new_issue"),
        "front_area_codes": [
            "head", "neck", "shoulder_r", "shoulder_l",
            "arm_r", "arm_l", "hand_r", "hand_l",
            "chest", "waist",
            "thigh_r", "thigh_l",
            "knee_r", "knee_l",
            "ankle_r", "ankle_l",
            "other",
        ],
        "back_area_codes": [
            "back", "hip_r", "hip_l",
        ],
    }
    return render(request, "intakes/patient/intake_wizard.html", context)

def _must_own_recording(user, rec: InterviewRecording):
    # created_by が必ず入る前提。未設定の可能性あるならここで防御。
    if rec.created_by_id and rec.created_by_id != user.id:
        raise PermissionError("Permission denied")

def _must_own_appointment(user, appt: Appointment):
    patient_user_id = getattr(appt.patient, "user_id", None)
    if patient_user_id and patient_user_id != user.id:
        raise PermissionError("Permission denied")

@staff_required
def recording_new(request, appointment_id):
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の録音のみ操作できます。")

    appt = get_object_or_404(
        Appointment.objects.select_related("clinic", "patient"),
        pk=appointment_id,
        clinic=clinic,
        patient__clinic=clinic,
    )

    intake, _ = Intake.objects.get_or_create(
        appointment=appt,
        clinic=clinic,
        patient=appt.patient,
        defaults={"payload": {}},
    )

    rec = InterviewRecording.objects.create(
        clinic=clinic,
        patient=appt.patient,
        appointment=appt,
        intake=intake,
        created_by=request.user,   # ✅ ここ入れる（所有権チェックの前提）
        status=InterviewRecording.Status.PENDING,
    )

    context = {
        "appointment": appt,
        "recording": rec,
        "upload_url": reverse("intakes:upload_recording", args=[rec.id]),
        "process_url": reverse("intakes:process_recording", args=[rec.id]),
        "detail_url": reverse("intakes:recording_detail", args=[rec.id]),
    }
    return render(request, "intakes/staff/recording_new.html", context)


@require_POST
@staff_required
def upload_recording(request, recording_id):
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の録音のみ操作できます。")

    f = request.FILES.get("audio")
    if not f:
        return JsonResponse({"ok": False, "error": "audio file is required"}, status=400)

    try:
        duration_sec = int(request.POST.get("duration_sec") or 0)
    except ValueError:
        duration_sec = 0

    with transaction.atomic():
        rec = get_object_or_404(
            _recordings_for_clinic(clinic)
            .select_for_update(of=("self",)),
            pk=recording_id,
        )
        try:
            _must_own_recording(request.user, rec)
        except PermissionError:
            return HttpResponseForbidden("この録音にはアクセスできません。")

        if rec.status in {
            InterviewRecording.Status.TRANSCRIBING,
            InterviewRecording.Status.SUMMARIZING,
        }:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "文字起こしまたはカルテ案作成中のため、録音を更新できません。",
                },
                status=409,
            )

        rec.audio_file = f
        rec.mime_type = f.content_type or ""
        rec.duration_sec = duration_sec
        rec.status = InterviewRecording.Status.UPLOADED
        rec.error_message = ""
        rec.transcript_text = ""
        rec.transcript_json = {}
        rec.summary_json = {}
        rec.confirmed_summary_json = None
        rec.summary_status = InterviewRecording.SummaryStatus.DRAFT
        rec.confirmed_at = None
        rec.confirmed_by = None
        rec.save(
            update_fields=[
                "audio_file",
                "mime_type",
                "duration_sec",
                "status",
                "error_message",
                "transcript_text",
                "transcript_json",
                "summary_json",
                "confirmed_summary_json",
                "summary_status",
                "confirmed_at",
                "confirmed_by",
            ]
        )

    return JsonResponse({"ok": True, "recording_id": rec.id})


@require_POST
@staff_required
def process_recording(request, recording_id):
    """
    録音データをAI処理する。

    流れ:
    1. 録音データ取得
    2. 所有権チェック
    3. clinic取得
    4. AI利用上限チェック
    5. STT実行
    6. STT利用ログ作成 billing_minutesあり
    7. AI要約実行
    8. 要約利用ログ作成 billing_minutesなし
    9. Intakeへ同期
    """

    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の録音のみ操作できます。")

    rec = get_object_or_404(_recordings_for_clinic(clinic), pk=recording_id)

    try:
        _must_own_recording(request.user, rec)
    except PermissionError:
        return HttpResponseForbidden("この録音にはアクセスできません。")

    ai_usage_summary = build_ai_usage_summary(clinic)

    if not ai_usage_summary.can_use_ai:
        messages.error(
            request,
            ai_usage_summary.warning_message or "AI利用上限に達しているため処理できません。",
        )
        return redirect("intakes:recording_detail", recording_id=rec.id)

    force = request.POST.get("force") == "1"
    try:
        with transaction.atomic():
            rec = get_object_or_404(
                _recordings_for_clinic(clinic)
                .select_for_update(of=("self",)),
                pk=recording_id,
            )
            try:
                _must_own_recording(request.user, rec)
            except PermissionError:
                return HttpResponseForbidden("この録音にはアクセスできません。")

            if rec.status in {
                InterviewRecording.Status.TRANSCRIBING,
                InterviewRecording.Status.SUMMARIZING,
            }:
                messages.info(request, "録音内容はすでに処理中です。")
                return redirect(
                    "intakes:recording_detail",
                    recording_id=rec.id,
                )

            if rec.summary_json and not force:
                messages.info(
                    request,
                    "カルテ案はすでに作成済みです。確認・修正してください。",
                )
                return redirect(
                    "intakes:recording_detail",
                    recording_id=rec.id,
                )

            if not rec.audio_file and not rec.transcript_text:
                rec.status = InterviewRecording.Status.FAILED
                rec.error_message = "音声ファイルがアップロードされていません"
                rec.save(update_fields=["status", "error_message"])
                messages.error(request, rec.error_message)
                return redirect(
                    "intakes:recording_detail",
                    recording_id=rec.id,
                )

            should_transcribe = not bool((rec.transcript_text or "").strip())
            transcript_text = rec.transcript_text or ""
            had_confirmed_summary = bool(rec.confirmed_summary_json)

            rec.status = (
                InterviewRecording.Status.TRANSCRIBING
                if should_transcribe
                else InterviewRecording.Status.SUMMARIZING
            )
            rec.error_message = ""
            if force:
                rec.confirmed_summary_json = None
                rec.summary_status = InterviewRecording.SummaryStatus.DRAFT
                rec.confirmed_at = None
                rec.confirmed_by = None
            update_fields = ["status", "error_message"]
            if force:
                update_fields.extend(
                    [
                        "confirmed_summary_json",
                        "summary_status",
                        "confirmed_at",
                        "confirmed_by",
                    ]
                )
            rec.save(update_fields=update_fields)

        if should_transcribe:
            transcript_text, transcript_json = run_stt(
                rec.audio_file,
                rec.mime_type,
            )

            with transaction.atomic():
                rec = get_object_or_404(
                    _recordings_for_clinic(clinic)
                    .select_for_update(of=("self",)),
                    pk=recording_id,
                )
                rec.transcript_text = transcript_text or ""
                rec.transcript_json = transcript_json or {}
                rec.status = InterviewRecording.Status.SUMMARIZING
                rec.summary_json = {}
                rec.confirmed_summary_json = None
                rec.summary_status = InterviewRecording.SummaryStatus.DRAFT
                rec.confirmed_at = None
                rec.confirmed_by = None
                rec.save(
                    update_fields=[
                        "transcript_text",
                        "transcript_json",
                        "status",
                        "summary_json",
                        "confirmed_summary_json",
                        "summary_status",
                        "confirmed_at",
                        "confirmed_by",
                    ]
                )

            if not AiUsageLog.objects.filter(
                recording=rec,
                usage_type=AiUsageLog.UsageType.STT,
                status=AiUsageLog.Status.SUCCESS,
            ).exists():
                create_ai_usage_log_for_recording(
                    recording=rec,
                    usage_type=AiUsageLog.UsageType.STT,
                    model_name=(rec.transcript_json or {}).get("model")
                    or DEFAULT_STT_MODEL,
                    transcript_text=rec.transcript_text or "",
                    estimated_cost_yen=0,
                    created_by=request.user,
                    count_billing_minutes=True,
                    metadata={
                        "source": "process_recording",
                        "stage": "stt",
                        "duration_sec": rec.duration_sec,
                        "mime_type": rec.mime_type,
                    },
                )

        summary = summarize_transcript(transcript_text)

        with transaction.atomic():
            rec = get_object_or_404(
                _recordings_for_clinic(clinic)
                .select_for_update(of=("self",)),
                pk=recording_id,
            )
            rec.summary_json = summary or {}
            rec.confirmed_summary_json = None
            rec.summary_status = InterviewRecording.SummaryStatus.DRAFT
            rec.confirmed_at = None
            rec.confirmed_by = None
            rec.status = InterviewRecording.Status.DONE
            rec.error_message = ""
            rec.save(
                update_fields=[
                    "summary_json",
                    "confirmed_summary_json",
                    "summary_status",
                    "confirmed_at",
                    "confirmed_by",
                    "status",
                    "error_message",
                ]
            )

        if not AiUsageLog.objects.filter(
            recording=rec,
            usage_type=AiUsageLog.UsageType.SUMMARY,
            status=AiUsageLog.Status.SUCCESS,
        ).exists():
            create_ai_usage_log_for_recording(
                recording=rec,
                usage_type=AiUsageLog.UsageType.SUMMARY,
                model_name=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
                transcript_text=rec.transcript_text or "",
                estimated_cost_yen=0,
                created_by=request.user,
                count_billing_minutes=False,
                metadata={
                    "source": "process_recording",
                    "stage": "summary",
                    "duration_sec": rec.duration_sec,
                    "mime_type": rec.mime_type,
                },
            )

        if rec.intake_id:
            intake = rec.intake
            sync_intake_columns_from_summary(intake, summary)
            intake.payload = intake.payload or {}
            intake.payload["ai_summary"] = summary
            intake.save(update_fields=["payload"])

        if force and had_confirmed_summary:
            messages.success(
                request,
                "録音内容からカルテ案を再作成しました。確認済み内容はリセットされています。カルテ登録前に再度確認してください。",
            )
        elif force:
            messages.success(request, "録音内容からカルテ案を再作成しました。")
        else:
            messages.success(request, "録音内容からカルテ案を作成しました。")
        return redirect("intakes:recording_detail", recording_id=rec.id)

    except Exception as e:
        with transaction.atomic():
            rec = get_object_or_404(
                _recordings_for_clinic(clinic)
                .select_for_update(of=("self",)),
                pk=recording_id,
            )
            rec.status = InterviewRecording.Status.FAILED
            rec.error_message = str(e)
            rec.save(update_fields=["status", "error_message"])

        try:
            create_ai_usage_log_for_recording(
                recording=rec,
                usage_type=AiUsageLog.UsageType.OTHER,
                model_name="",
                transcript_text=getattr(rec, "transcript_text", "") or "",
                estimated_cost_yen=0,
                status=AiUsageLog.Status.FAILED,
                error_message=str(e),
                created_by=request.user,
                count_billing_minutes=False,
                metadata={
                    "source": "process_recording",
                    "stage": "error",
                    "duration_sec": getattr(rec, "duration_sec", 0),
                    "mime_type": getattr(rec, "mime_type", ""),
                },
            )
        except Exception:
            pass

        messages.error(request, f"録音内容の処理に失敗しました: {e}")
        return redirect("intakes:recording_detail", recording_id=rec.id)


@staff_required
def record_page(request, appointment_id):
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の録音のみ操作できます。")

    appt = get_object_or_404(
        Appointment.objects.select_related("clinic", "patient"),
        pk=appointment_id,
        clinic=clinic,
        patient__clinic=clinic,
    )
    messages.info(request, "現行の問診録音画面へ移動しました。")
    return redirect("intakes:recording_new", appointment_id=appt.id)


@staff_required
def recording_detail(request, recording_id):
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の録音のみ閲覧できます。")

    rec = get_object_or_404(_recordings_for_clinic(clinic), pk=recording_id)

    try:
        _must_own_recording(request.user, rec)
    except PermissionError:
        return HttpResponseForbidden("この録音にはアクセスできません。")

    registered_clinical_note = _get_registered_clinical_note(rec, clinic)
    clinical_note_is_current = _clinical_note_matches_recording_summary(
        registered_clinical_note,
        rec,
    )
    flow_state = build_interview_recording_flow_state(
        rec,
        clinical_note_exists=registered_clinical_note is not None,
        clinical_note_is_current=clinical_note_is_current,
    )

    summary = rec.get_active_summary() or {}
    soap = summary.get("soap") or {}

    soap_view = {
        "S": _as_list(soap.get("S")),
        "O": _as_list(soap.get("O")),
        "A": _as_list(soap.get("A")),
        "P": _as_list(soap.get("P")),
    }

    context = {
        "recording": rec,
        "appointment": rec.appointment,
        "patient": rec.patient,
        "soap_view": soap_view,
        "summary": summary,
        "summary_json_pretty": json.dumps(summary, ensure_ascii=False, indent=2),
        "transcript_text": rec.transcript_text or "",
        "flow_state": flow_state,
        "registered_clinical_note": registered_clinical_note,
        "process_url": reverse("intakes:process_recording", args=[rec.id]),
        "retry_url": reverse("intakes:recording_new", args=[rec.appointment_id]),
        "confirm_url": reverse("intakes:recording_confirm", args=[rec.id]),
        "register_url": reverse("staff:register_clinical_note", args=[rec.id]),
    }

    return render(request, "intakes/staff/recording_detail.html", context)

@staff_required
@require_POST
def recording_confirm(request, recording_id: int):
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の録音のみ操作できます。")

    rec = get_object_or_404(
        _recordings_for_clinic(clinic),
        pk=recording_id,
    )

    try:
        _must_own_recording(request.user, rec)
    except PermissionError:
        return HttpResponseForbidden("この録音にはアクセスできません。")

    raw = (request.POST.get("summary_json") or "").strip()
    if not raw:
        return HttpResponseBadRequest("summary_json is required")

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        messages.error(request, "JSONの形式が不正です。")
        return redirect(reverse("intakes:recording_detail", args=[recording_id]))

    # 最低限の防御：soapがdictじゃなければ弾く（データ破壊防止）
    soap = data.get("soap")
    if not isinstance(soap, dict):
        messages.error(request, "soapデータが不正です。")
        return redirect(reverse("intakes:recording_detail", args=[recording_id]))

    # （任意）スキーマ検証は残してOK：InterviewRecordingでも使えるならそのまま
    # try:
    #     from jsonschema import validate
    #     validate(instance=data, schema=SUMMARY_JSON_SCHEMA["schema"])
    # except ImportError:
    #     pass
    # except Exception as e:
    #     messages.error(request, f"スキーマに合いません: {e}")
    #     return redirect(reverse("intakes:recording_detail", args=[recording_id]))

    source_summary = rec.get_active_summary() or {}

    with transaction.atomic():
        rec = get_object_or_404(
            _recordings_for_clinic(clinic)
            .select_for_update(of=("self",)),
            pk=recording_id,
        )

        if rec.status in {
            InterviewRecording.Status.TRANSCRIBING,
            InterviewRecording.Status.SUMMARIZING,
        }:
            messages.info(
                request,
                "文字起こしまたはカルテ案作成中です。完了後に確認内容を保存してください。",
            )
            return redirect(
                "intakes:recording_detail",
                recording_id=recording_id,
            )

        current_source_summary = rec.get_active_summary() or {}
        if current_source_summary != source_summary:
            messages.warning(
                request,
                "保存中にカルテ案が更新されました。最新内容を確認してから、もう一度保存してください。",
            )
            return redirect(
                "intakes:recording_detail",
                recording_id=recording_id,
            )

        if (
            rec.summary_status == InterviewRecording.SummaryStatus.CONFIRMED
            and rec.confirmed_summary_json == data
        ):
            messages.info(request, "確認内容はすでに保存されています。")
            return redirect(
                "intakes:recording_detail",
                recording_id=recording_id,
            )

        rec.mark_confirmed(user=request.user, data=data)
        rec.save(
            update_fields=[
                "confirmed_summary_json",
                "summary_status",
                "confirmed_at",
                "confirmed_by",
            ]
        )

    messages.success(
        request,
        "確認内容を保存しました。カルテへ登録できます。",
    )
    return redirect(reverse("intakes:recording_detail", args=[recording_id]))

@login_required
def intake_start_view(request, appointment_id):
    appt = get_object_or_404(Appointment, pk=appointment_id)

    try:
        _must_own_appointment(request.user, appt)
    except PermissionError:
        return HttpResponseForbidden("この予約にはアクセスできません。")

    intake, _ = Intake.objects.get_or_create(
        appointment=appt,
        defaults={"clinic": appt.clinic, "patient": appt.patient, "payload": {}},
    )

    payload = intake.payload or {}

    previous_intake = (
        Intake.objects
        .filter(patient=appt.patient)
        .exclude(appointment=appt)
        .exclude(chief_complaint__isnull=True)
        .exclude(chief_complaint__exact="")
        .order_by("-submitted_at", "-id")
        .first()
    )
    previous_complaint = previous_intake.chief_complaint if previous_intake else ""

    if request.method == "POST":
        form = IntakeStartForm(request.POST)
        if form.is_valid():
            visit_type = form.cleaned_data["visit_type"]

            payload["visit_type"] = visit_type
            payload["meta"] = {
                **(payload.get("meta", {}) or {}),
                "branch_selected": True,
                "intake_mode": "followup" if visit_type == "followup" else "normal",
                "current_step": 1,
            }

            intake.payload = payload
            intake.save(update_fields=["payload"])

            if visit_type == "followup":
                return redirect("intakes:intake_followup", appointment_id=appt.id)

            # new_issue / unknown は通常問診へ確実に遷移
            wizard_url = reverse("intakes:intake", args=[appt.id])
            return redirect(f"{wizard_url}?step=1")
    else:
        form = IntakeStartForm(initial={
            "visit_type": payload.get("visit_type")
        })

    return render(request, "intakes/patient/intake_start.html", {
        "appointment": appt,
        "form": form,
        "previous_complaint": previous_complaint,
    })

@login_required
def intake_followup_view(request, appointment_id):
    appt = get_object_or_404(Appointment, pk=appointment_id)

    try:
        _must_own_appointment(request.user, appt)
    except PermissionError:
        return HttpResponseForbidden("この予約にはアクセスできません。")

    intake, _ = Intake.objects.get_or_create(
        appointment=appt,
        defaults={"clinic": appt.clinic, "patient": appt.patient, "payload": {}},
    )

    payload = intake.payload or {}

    previous_intake = (
        Intake.objects
        .filter(patient=appt.patient)
        .exclude(appointment=appt)
        .exclude(chief_complaint__isnull=True)
        .exclude(chief_complaint__exact="")
        .order_by("-submitted_at", "-id")
        .first()
    )
    previous_complaint = previous_intake.chief_complaint if previous_intake else ""

    if request.method == "POST":
        form = FollowupIntakeForm(request.POST)
        if form.is_valid():
            cd = form.cleaned_data

            payload["visit_type"] = "followup"
            payload["followup"] = {
                "condition_change": cd.get("condition_change"),
                "pain_level": cd.get("pain_level"),
                "changes": cd.get("changes") or [],
                "comment": cd.get("comment", ""),
            }
            payload["meta"] = {
                **(payload.get("meta", {}) or {}),
                "intake_mode": "followup",
                "completed_steps": [1],
                "current_step": 1,
            }

            if previous_complaint and not intake.chief_complaint:
                intake.chief_complaint = previous_complaint

            intake.symptom_type = "followup"
            intake.onset = "followup"
            intake.payload = payload
            intake.submitted_at = timezone.now()
            intake.save()

            appt.status = Appointment.Status.BOOKED
            appt.save(update_fields=["status"])

            messages.success(request, "Web問診が完了し、予約が確定しました。")
            return redirect("intakes:intake_done", appointment_id=appt.id)
    else:
        form = FollowupIntakeForm(initial=payload.get("followup", {}))

    return render(request, "intakes/patient/intake_followup.html", {
        "appointment": appt,
        "form": form,
        "previous_complaint": previous_complaint,
    })
