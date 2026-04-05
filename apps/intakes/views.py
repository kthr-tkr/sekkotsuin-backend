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
from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.http import HttpResponse, HttpResponseForbidden, HttpResponseBadRequest
from .services.ai_summarizer import SUMMARY_JSON_SCHEMA

from .services.stt import run_stt   # ↑で分離した場合

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
            if step == 3:
                payload["symptoms"] = {
                    "areas": cd.get("areas", []),
                    "other_area_text": cd.get("other_area_text", ""),
                    "severity": cd.get("severity"),
                    "qualities": cd.get("qualities", []),
                    "other_quality_text": cd.get("other_quality_text", ""),
                    "free_text": cd.get("free_text", ""),
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

@login_required
def recording_new(request, appointment_id):
    appt = get_object_or_404(Appointment, pk=appointment_id)

    intake, _ = Intake.objects.get_or_create(
        appointment=appt,
        defaults={"clinic": appt.clinic, "patient": appt.patient, "payload": {}},
    )

    rec = InterviewRecording.objects.create(
        clinic=appt.clinic,
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
@login_required
def upload_recording(request, recording_id):
    rec = get_object_or_404(InterviewRecording, pk=recording_id)
    _must_own_recording(request.user, rec)

    f = request.FILES.get("audio")
    if not f:
        return JsonResponse({"ok": False, "error": "audio file is required"}, status=400)

    rec.audio_file = f
    rec.mime_type = f.content_type or ""
    rec.duration_sec = int(request.POST.get("duration_sec") or 0)
    rec.status = InterviewRecording.Status.UPLOADED
    rec.error_message = ""
    rec.save(update_fields=["audio_file", "mime_type", "duration_sec", "status", "error_message"])

    return JsonResponse({"ok": True, "recording_id": rec.id})


@require_POST
@login_required
def process_recording(request, recording_id):
    # ✅ select_for_update で連打/多重実行耐性
    with transaction.atomic():
        rec = InterviewRecording.objects.select_for_update().get(pk=recording_id)
        _must_own_recording(request.user, rec)

        if rec.status in [
            InterviewRecording.Status.TRANSCRIBING,
            InterviewRecording.Status.SUMMARIZING,
            InterviewRecording.Status.DONE,
        ]:
            return redirect("intakes:recording_detail", recording_id=rec.id)

        if not rec.audio_file:
            rec.status = InterviewRecording.Status.FAILED
            rec.error_message = "音声ファイルがアップロードされていません"
            rec.save(update_fields=["status", "error_message"])
            return redirect("intakes:recording_detail", recording_id=rec.id)

        rec.status = InterviewRecording.Status.TRANSCRIBING
        rec.error_message = ""
        rec.save(update_fields=["status", "error_message"])

    try:
        transcript_text, transcript_json = run_stt(rec.audio_file.path, rec.mime_type)

        rec.transcript_text = transcript_text
        rec.transcript_json = transcript_json or {}
        rec.status = InterviewRecording.Status.SUMMARIZING
        rec.save(update_fields=["transcript_text", "transcript_json", "status"])

        summary = summarize_transcript(transcript_text)  # ここは次フェーズで改善
        rec.summary_json = summary
        rec.status = InterviewRecording.Status.DONE
        rec.save(update_fields=["summary_json", "status"])

        if rec.intake_id:
            intake = rec.intake
            sync_intake_columns_from_summary(intake, summary)
            intake.payload = intake.payload or {}
            intake.payload["ai_summary"] = summary
            intake.save(update_fields=["payload"])

        return redirect("intakes:recording_detail", recording_id=rec.id)

    except Exception as e:
        rec.status = InterviewRecording.Status.FAILED
        rec.error_message = str(e)
        rec.save(update_fields=["status", "error_message"])
        return redirect("intakes:recording_detail", recording_id=rec.id)


@login_required
def record_page(request, appointment_id):
    appt = get_object_or_404(Appointment, pk=appointment_id)
    rec = InterviewRecording.objects.create(
        clinic=appt.clinic,
        appointment=appt,
        created_by=request.user,
        status=InterviewRecording.Status.UPLOADED,
    )
    return render(request, "intakes/staff/record_page.html", {"appointment": appt, "recording": rec})


@login_required
def recording_detail(request, recording_id):
    rec = get_object_or_404(InterviewRecording, pk=recording_id)

    # ★確定版があればそっちを表示する（重要）
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
        "soap_view": soap_view,
        "summary": summary,
        "summary_json_pretty": json.dumps(summary, ensure_ascii=False, indent=2),  # ★編集モーダル用
        "transcript_text": rec.transcript_text or "",
        "process_url": reverse("intakes:process_recording", args=[rec.id]),
        "retry_url": reverse("intakes:recording_new", args=[rec.appointment_id]),

        # ★編集確定のPOST先（intakes側で1本化）
        "confirm_url": reverse("intakes:recording_confirm", args=[rec.id]),

        # ★内容登録（ClinicalNoteへ）POST先（staff側を利用）
        "register_url": reverse("staff:register_clinical_note", args=[rec.id]),
    }

    return render(request, "intakes/staff/recording_detail.html", context)

@staff_member_required
@require_POST
def recording_confirm(request, recording_id: int):
    rec = get_object_or_404(InterviewRecording, pk=recording_id)

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

    rec.mark_confirmed(user=request.user, data=data)
    rec.save(update_fields=["confirmed_summary_json", "summary_status", "confirmed_at", "confirmed_by"])

    messages.success(request, "編集内容を確定しました。")
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