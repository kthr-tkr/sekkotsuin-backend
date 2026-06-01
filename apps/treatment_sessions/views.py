import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Max, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.ai_usage.models import AiUsageLog
from apps.intakes.services.stt import run_stt

from apps.appointments.models import Appointment
from apps.intakes.models import Intake
from apps.staff.decorators import staff_required

from .models import TreatmentSession, TreatmentSessionChunk
from apps.patients.models import Patient
from apps.ai_usage.services import build_ai_usage_summary
from apps.treatment_sessions.services.session_summarizer import summarize_treatment_session

from django.db import transaction

from apps.clinical_notes.models import ClinicalNote, ClinicalNoteHistory


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

    summary = session.active_summary or {}

    session_summary = summary.get("session_summary") or {}
    clinical_assessment = summary.get("clinical_assessment") or {}
    treatment = summary.get("treatment") or {}
    explanation = summary.get("explanation") or {}
    next_plan = summary.get("next_plan") or {}
    soap = summary.get("soap") or {}
    progress_note = summary.get("progress_note") or {}

    if not isinstance(session_summary, dict):
        session_summary = {}
    if not isinstance(clinical_assessment, dict):
        clinical_assessment = {}
    if not isinstance(treatment, dict):
        treatment = {}
    if not isinstance(explanation, dict):
        explanation = {}
    if not isinstance(next_plan, dict):
        next_plan = {}
    if not isinstance(soap, dict):
        soap = {}
    if not isinstance(progress_note, dict):
        progress_note = {}

    context = {
        "session": session,
        "chunks": session.chunks.all(),
        "summary": summary,
        "important_points": summary.get("important_points") or [],
        "session_summary": session_summary,
        "clinical_assessment": clinical_assessment,
        "treatment": treatment,
        "explanation": explanation,
        "next_plan": next_plan,
        "soap": soap,
        "progress_note": progress_note,
        "relationship_notes": summary.get("relationship_notes") or [],
        "missing_information": summary.get("missing_information") or [],
        "safety_notes": summary.get("safety_notes") or [],
        "summary_json_pretty": json.dumps(summary, ensure_ascii=False, indent=2),
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
      - その予約に紐づく TreatmentSession を get_or_create する

    appointment がない場合:
      - 患者単位の進行中セッションがあれば開く
      - なければ appointment=None で作成する
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

        session, created = TreatmentSession.objects.get_or_create(
            appointment=appointment,
            defaults={
                "clinic": patient.clinic,
                "patient": patient,
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
            messages.info(request, "この予約の施術セッションを開きます。")

        return redirect("treatment_sessions:detail", session_id=session.id)

    existing_session = (
        TreatmentSession.objects
        .filter(
            clinic=patient.clinic,
            patient=patient,
            appointment__isnull=True,
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
        appointment=None,
        intake=None,
        title="施術セッション",
        status=TreatmentSession.Status.PENDING,
        created_by=request.user,
        updated_by=request.user,
    )

    messages.success(request, "施術セッションを作成しました。")
    return redirect("treatment_sessions:detail", session_id=session.id)

@staff_required
@require_POST
def upload_session_chunk_view(request, session_id):
    """
    施術セッションの録音ファイルを1チャンクとして保存する。

    現段階:
    - 1録音 = 1 chunk
    - AI処理はまだ行わない
    - total_duration_sec を更新する
    """
    session = get_object_or_404(
        TreatmentSession.objects.select_related("clinic", "patient", "appointment"),
        pk=session_id,
    )

    if not _same_clinic(request.user, session.clinic):
        return JsonResponse(
            {"ok": False, "error": "この施術セッションにはアクセスできません。"},
            status=403,
        )

    audio_file = request.FILES.get("audio")
    if not audio_file:
        return JsonResponse(
            {"ok": False, "error": "audio file is required"},
            status=400,
        )

    try:
        duration_sec = int(request.POST.get("duration_sec") or 0)
    except ValueError:
        duration_sec = 0

    current_max = (
        TreatmentSessionChunk.objects
        .filter(session=session)
        .aggregate(max_index=Max("chunk_index"))
        .get("max_index")
    )

    next_index = 0 if current_max is None else current_max + 1

    chunk = TreatmentSessionChunk.objects.create(
        session=session,
        chunk_index=next_index,
        audio_file=audio_file,
        mime_type=audio_file.content_type or "",
        duration_sec=duration_sec,
        status=TreatmentSessionChunk.Status.UPLOADED,
        metadata={
            "source": "treatment_session_detail",
            "uploaded_by": request.user.id,
        },
    )

    total_duration = (
        TreatmentSessionChunk.objects
        .filter(session=session)
        .aggregate(total=Sum("duration_sec"))
        .get("total")
        or 0
    )

    session.total_duration_sec = total_duration
    session.status = TreatmentSession.Status.UPLOADED
    session.updated_by = request.user

    # 新しい録音が追加されたので、既存AI要約は無効化
    session.summary_json = {}
    session.confirmed_summary_json = {}
    session.summary_status = "draft"

    if not session.started_at:
        session.started_at = timezone.now()

    session.ended_at = timezone.now()

    session.save(
        update_fields=[
            "total_duration_sec",
            "status",
            "updated_by",
            "summary_json",
            "confirmed_summary_json",
            "summary_status",
            "started_at",
            "ended_at",
            "updated_at",
        ]
    )

    return JsonResponse({
        "ok": True,
        "session_id": session.id,
        "chunk_id": chunk.id,
        "chunk_index": chunk.chunk_index,
        "duration_sec": chunk.duration_sec,
        "total_duration_sec": session.total_duration_sec,
    })

@staff_required
@require_POST
def transcribe_session_chunk_view(request, chunk_id):
    """
    施術セッションチャンクを文字起こしする。

    現段階:
    - chunk単位でSTT
    - AiUsageLogにSTT利用分を記録
    - session.transcript_textへ統合
    - 要約は次フェーズ
    """
    chunk = get_object_or_404(
        TreatmentSessionChunk.objects.select_related(
            "session",
            "session__clinic",
            "session__patient",
            "session__appointment",
            "session__intake",
        ),
        pk=chunk_id,
    )

    session = chunk.session

    if not _same_clinic(request.user, session.clinic):
        return HttpResponseForbidden("この施術セッションにはアクセスできません。")

    if not chunk.audio_file:
        messages.error(request, "音声ファイルがありません。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    if chunk.status == TreatmentSessionChunk.Status.TRANSCRIBING:
        messages.info(request, "このチャンクは文字起こし中です。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    if chunk.transcript_text:
        messages.info(request, "このチャンクはすでに文字起こし済みです。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    try:
        chunk.status = TreatmentSessionChunk.Status.TRANSCRIBING
        chunk.error_message = ""
        chunk.save(update_fields=["status", "error_message", "updated_at"])

        session.status = TreatmentSession.Status.TRANSCRIBING
        session.updated_by = request.user
        session.save(update_fields=["status", "updated_by", "updated_at"])

        transcript_text, transcript_json = run_stt(
            chunk.audio_file.path,
            chunk.mime_type,
        )

        chunk.transcript_text = transcript_text or ""
        chunk.transcript_json = transcript_json or {}
        chunk.status = TreatmentSessionChunk.Status.SUMMARIZED
        chunk.save(
            update_fields=[
                "transcript_text",
                "transcript_json",
                "status",
                "updated_at",
            ]
        )

        # STT利用ログ作成。TreatmentSession用なので recording は使わず metadata に紐づけ情報を残す。
        already_logged = AiUsageLog.objects.filter(
            clinic=session.clinic,
            usage_type=AiUsageLog.UsageType.STT,
            status=AiUsageLog.Status.SUCCESS,
            metadata__treatment_session_chunk_id=chunk.id,
        ).exists()

        if not already_logged:
            AiUsageLog.objects.create(
                clinic=session.clinic,
                patient=session.patient,
                appointment=session.appointment,
                intake=session.intake,
                usage_type=AiUsageLog.UsageType.STT,
                status=AiUsageLog.Status.SUCCESS,
                model_name="whisper-1",
                audio_duration_sec=chunk.duration_sec or 0,
                billing_minutes=AiUsageLog.seconds_to_billing_minutes(chunk.duration_sec or 0),
                transcript_chars=len(chunk.transcript_text or ""),
                input_tokens=0,
                output_tokens=0,
                estimated_cost_yen=0,
                metadata={
                    "source": "treatment_session_chunk",
                    "treatment_session_id": session.id,
                    "treatment_session_chunk_id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                    "duration_sec": chunk.duration_sec,
                    "mime_type": chunk.mime_type,
                },
                created_by=request.user,
            )

        # session側に文字起こしを統合
        chunks = session.chunks.order_by("chunk_index")

        combined_transcript = "\n\n".join(
            [
                f"[chunk {c.chunk_index}]\n{c.transcript_text}"
                for c in chunks
                if c.transcript_text
            ]
        )

        total_duration = (
            chunks.aggregate(total=Sum("duration_sec")).get("total")
            or 0
        )

        session.transcript_text = combined_transcript
        session.total_duration_sec = total_duration
        session.status = TreatmentSession.Status.UPLOADED
        session.updated_by = request.user

        # 文字起こしが更新されたので、既存AI要約は無効化
        session.summary_json = {}
        session.confirmed_summary_json = {}
        session.summary_status = "draft"

        session.save(
            update_fields=[
                "transcript_text",
                "total_duration_sec",
                "status",
                "updated_by",
                "summary_json",
                "confirmed_summary_json",
                "summary_status",
                "updated_at",
            ]
        )

        messages.success(request, "施術録音の文字起こしが完了しました。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    except Exception as e:
        chunk.status = TreatmentSessionChunk.Status.FAILED
        chunk.error_message = str(e)
        chunk.save(update_fields=["status", "error_message", "updated_at"])

        session.status = TreatmentSession.Status.FAILED
        session.error_message = str(e)
        session.updated_by = request.user
        session.save(update_fields=["status", "error_message", "updated_by", "updated_at"])

        try:
            AiUsageLog.objects.create(
                clinic=session.clinic,
                patient=session.patient,
                appointment=session.appointment,
                intake=session.intake,
                usage_type=AiUsageLog.UsageType.STT,
                status=AiUsageLog.Status.FAILED,
                model_name="whisper-1",
                audio_duration_sec=chunk.duration_sec or 0,
                billing_minutes=0,
                transcript_chars=0,
                estimated_cost_yen=0,
                error_message=str(e),
                metadata={
                    "source": "treatment_session_chunk",
                    "stage": "stt_error",
                    "treatment_session_id": session.id,
                    "treatment_session_chunk_id": chunk.id,
                    "chunk_index": chunk.chunk_index,
                },
                created_by=request.user,
            )
        except Exception:
            pass

        messages.error(request, f"文字起こしに失敗しました: {e}")
        return redirect("treatment_sessions:detail", session_id=session.id)
    
@staff_required
@require_POST
def summarize_treatment_session_view(request, session_id):
    """
    施術セッション全体の統合文字起こしをAI要約する。

    現段階:
    - session.transcript_text を summarize_transcript に渡す
    - session.summary_json に保存
    - AiUsageLog に SUMMARY として記録
    - billing_minutes は二重カウント防止のため 0
    """
    session = get_object_or_404(
        TreatmentSession.objects.select_related(
            "clinic",
            "patient",
            "appointment",
            "intake",
        ),
        pk=session_id,
    )

    if not _same_clinic(request.user, session.clinic):
        return HttpResponseForbidden("この施術セッションにはアクセスできません。")

    if not session.transcript_text:
        messages.error(request, "統合文字起こしがないため、AI要約を作成できません。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    ai_usage_summary = build_ai_usage_summary(session.clinic)

    if not ai_usage_summary.can_use_ai:
        messages.error(
            request,
            ai_usage_summary.warning_message or "AI利用上限に達しているため要約できません。",
        )
        return redirect("treatment_sessions:detail", session_id=session.id)

    force = request.POST.get("force") == "1"

    if session.summary_json and not force:
        messages.info(request, "この施術セッションはすでにAI要約済みです。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    try:
        session.status = TreatmentSession.Status.SUMMARIZING
        session.error_message = ""
        session.updated_by = request.user
        session.save(update_fields=["status", "error_message", "updated_by", "updated_at"])

        summary = summarize_treatment_session(session.transcript_text)

        session.summary_json = summary or {}
        session.status = TreatmentSession.Status.DONE
        session.updated_by = request.user
        session.save(update_fields=["summary_json", "status", "updated_by", "updated_at"])

        already_logged = AiUsageLog.objects.filter(
            clinic=session.clinic,
            usage_type=AiUsageLog.UsageType.SUMMARY,
            status=AiUsageLog.Status.SUCCESS,
            metadata__treatment_session_id=session.id,
            metadata__stage="session_summary",
        ).exists()

        if not already_logged:
            AiUsageLog.objects.create(
                clinic=session.clinic,
                patient=session.patient,
                appointment=session.appointment,
                intake=session.intake,
                usage_type=AiUsageLog.UsageType.SUMMARY,
                status=AiUsageLog.Status.SUCCESS,
                model_name=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
                audio_duration_sec=session.total_duration_sec or 0,
                billing_minutes=0,
                transcript_chars=len(session.transcript_text or ""),
                input_tokens=0,
                output_tokens=0,
                estimated_cost_yen=0,
                metadata={
                    "source": "treatment_session",
                    "stage": "session_summary",
                    "treatment_session_id": session.id,
                    "duration_sec": session.total_duration_sec,
                },
                created_by=request.user,
            )

        messages.success(request, "施術セッションのAI要約が完了しました。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    except Exception as e:
        session.status = TreatmentSession.Status.FAILED
        session.error_message = str(e)
        session.updated_by = request.user
        session.save(update_fields=["status", "error_message", "updated_by", "updated_at"])

        try:
            AiUsageLog.objects.create(
                clinic=session.clinic,
                patient=session.patient,
                appointment=session.appointment,
                intake=session.intake,
                usage_type=AiUsageLog.UsageType.SUMMARY,
                status=AiUsageLog.Status.FAILED,
                model_name=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
                audio_duration_sec=session.total_duration_sec or 0,
                billing_minutes=0,
                transcript_chars=len(session.transcript_text or ""),
                estimated_cost_yen=0,
                error_message=str(e),
                metadata={
                    "source": "treatment_session",
                    "stage": "session_summary_error",
                    "treatment_session_id": session.id,
                },
                created_by=request.user,
            )
        except Exception:
            pass

        messages.error(request, f"AI要約に失敗しました: {e}")
        return redirect("treatment_sessions:detail", session_id=session.id)
    
def _build_clinical_note_data_from_session_summary(summary: dict) -> tuple[dict, dict, list]:
    """
    TreatmentSession.summary_json を ClinicalNote 用の
    soap_json / extract_json / followups_json に変換する。
    """
    summary = summary or {}

    important_points = summary.get("important_points") or []
    session_summary = summary.get("session_summary") or {}
    clinical_assessment = summary.get("clinical_assessment") or {}
    treatment = summary.get("treatment") or {}
    explanation = summary.get("explanation") or {}
    next_plan = summary.get("next_plan") or {}
    soap = summary.get("soap") or {}
    progress_note = summary.get("progress_note") or {}

    relationship_notes = summary.get("relationship_notes") or []
    missing_information = summary.get("missing_information") or []
    safety_notes = summary.get("safety_notes") or []

    # SOAPはClinicalNoteでそのまま使える形
    soap_json = {
        "S": soap.get("S") or [],
        "O": soap.get("O") or [],
        "A": soap.get("A") or [],
        "P": soap.get("P") or [],
    }

    # extract_jsonには後から画面表示・検索・施術計画生成に使いやすい情報を集約
    extract_json = {
        "source": "treatment_session",
        "important_points": important_points,

        "chief_complaint": session_summary.get("chief_complaint", ""),
        "visit_type": session_summary.get("visit_type", "unknown"),
        "overall_summary": session_summary.get("overall_summary", ""),
        "progress_change": session_summary.get("progress_change") or {},

        "checked_areas": clinical_assessment.get("checked_areas") or [],
        "pain_areas": clinical_assessment.get("pain_areas") or [],
        "movement_tests": clinical_assessment.get("movement_tests") or [],
        "findings": clinical_assessment.get("findings") or [],
        "suspected_causes": clinical_assessment.get("suspected_causes") or [],
        "treatment_intent": clinical_assessment.get("treatment_intent", ""),

        # 既存の画面が locations を見る可能性があるので互換用に入れる
        "locations": clinical_assessment.get("pain_areas") or clinical_assessment.get("checked_areas") or [],

        "performed_treatments": treatment.get("performed_treatments") or [],
        "target_areas": treatment.get("target_areas") or [],
        "patient_response": treatment.get("patient_response", ""),
        "after_treatment_change": treatment.get("after_treatment_change", ""),

        "explained_to_patient": explanation.get("explained_to_patient") or [],
        "lifestyle_guidance": explanation.get("lifestyle_guidance") or [],
        "home_care": explanation.get("home_care") or [],
        "cautions_until_next_visit": explanation.get("cautions_until_next_visit") or [],

        "next_plan": next_plan,
        "next_treatment_policy": next_plan.get("next_treatment_policy", ""),
        "recommended_visit_timing": next_plan.get("recommended_visit_timing", ""),
        "items_to_check_next_time": next_plan.get("items_to_check_next_time") or [],

        "progress_note": progress_note,
        "relationship_notes": relationship_notes,
        "missing_information": missing_information,
        "safety_notes": safety_notes,
    }

    # followups_json は「次回確認」「不足情報」「注意事項」をまとめておく
    followups_json = []

    for item in next_plan.get("items_to_check_next_time") or []:
        followups_json.append({
            "type": "next_check",
            "text": item,
        })

    for item in missing_information:
        followups_json.append({
            "type": "missing_information",
            "text": item,
        })

    for item in safety_notes:
        followups_json.append({
            "type": "safety",
            "text": item,
        })

    return soap_json, extract_json, followups_json

@staff_required
@require_POST
@transaction.atomic
def register_treatment_session_note_view(request, session_id):
    """
    施術セッションAI要約をClinicalNoteへ登録する。

    役割:
    - TreatmentSession.summary_json を正式なカルテとして保存
    - 既存カルテがある場合は履歴を残して更新
    - 患者詳細カルテタブへ戻す
    """
    session = get_object_or_404(
        TreatmentSession.objects.select_related(
            "clinic",
            "patient",
            "appointment",
            "intake",
        ),
        pk=session_id,
    )

    if not _same_clinic(request.user, session.clinic):
        return HttpResponseForbidden("この施術セッションにはアクセスできません。")

    if not session.appointment:
        messages.error(
            request,
            "この施術セッションには予約が紐づいていないため、カルテ登録できません。先に予約と紐づけてください。",
        )
        return redirect("treatment_sessions:detail", session_id=session.id)

    summary = session.active_summary or {}

    if not summary:
        messages.error(request, "AI要約が未作成のため、カルテに登録できません。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    patient = session.patient
    appointment = session.appointment
    intake = session.intake

    soap_json, extract_json, followups_json = _build_clinical_note_data_from_session_summary(summary)

    web_snapshot = {}
    if intake:
        web_snapshot = {
            "payload": intake.payload or {},
            "chief_complaint": intake.chief_complaint,
            "symptom_type": intake.symptom_type,
            "onset": intake.onset,
            "submitted_at": intake.submitted_at.isoformat() if intake.submitted_at else None,
        }

    existing_note = (
        ClinicalNote.objects
        .filter(appointment=appointment)
        .first()
    )

    # 既存カルテがある場合は更新前履歴を残す
    if existing_note:
        ClinicalNoteHistory.objects.create(
            note=existing_note,
            soap_json=existing_note.soap_json or {},
            extract_json=existing_note.extract_json or {},
            followups_json=existing_note.followups_json or [],
            web_intake_snapshot=existing_note.web_intake_snapshot or {},
            edited_by=request.user,
        )

    note, created = ClinicalNote.objects.update_or_create(
        appointment=appointment,
        defaults={
            "patient": patient,
            "intake": intake,
            "recording": None,
            "treatment_session": session,
            "soap_json": soap_json,
            "extract_json": extract_json,
            "followups_json": followups_json,
            "web_intake_snapshot": web_snapshot,
            "registered_by": request.user,
            "updated_by": request.user,
        },
    )

    # TreatmentSession側にも紐づけを残す
    session.clinical_note = note
    session.updated_by = request.user
    session.save(update_fields=["clinical_note", "updated_by", "updated_at"])

    if created:
        messages.success(request, "施術セッションのAI要約をカルテに登録しました。")
    else:
        messages.success(request, "既存カルテを施術セッションのAI要約で更新しました。")

    return redirect("staff:patient_detail", patient_id=patient.id)