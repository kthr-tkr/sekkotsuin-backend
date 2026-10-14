import json

from django.conf import settings
from django.contrib import messages
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.http import require_POST
from django.db.models import Max, Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.ai_usage.models import AiUsageLog
from apps.intakes.services.stt import DEFAULT_STT_MODEL, run_stt

from apps.appointments.models import Appointment
from apps.intakes.models import Intake
from apps.staff.decorators import staff_required

from .models import TreatmentSession, TreatmentSessionChunk
from apps.patients.models import Patient
from apps.ai_usage.services import build_ai_usage_summary
from apps.treatment_sessions.services.session_summarizer import summarize_treatment_session

from django.db import IntegrityError, transaction

from apps.clinical_notes.models import ClinicalNote, ClinicalNoteHistory

from .forms import TreatmentSessionConfirmForm


def _get_staff_clinic(request):
    clinic = getattr(request.user, "clinic", None)
    if clinic is None or getattr(request.user, "clinic_id", None) != clinic.id:
        return None
    return clinic


def _as_summary_dict(value):
    return value if isinstance(value, dict) else {}


def _as_summary_list(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip(" ・\t") for line in value.splitlines() if line.strip()]
    if isinstance(value, (list, tuple)):
        items = []
        for item in value:
            if isinstance(item, dict):
                item = (
                    item.get("text")
                    or item.get("summary")
                    or item.get("label")
                    or ""
                )
            text = str(item or "").strip()
            if text:
                items.append(text)
        return items
    text = str(value).strip()
    return [text] if text else []


def _session_scope_for_clinic(clinic):
    return (
        TreatmentSession.objects
        .filter(
            clinic=clinic,
            patient__clinic=clinic,
        )
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(intake__isnull=True) | Q(intake__clinic=clinic),
        )
    )


def _get_registered_clinical_note(session, clinic):
    if not session.appointment_id:
        return None

    note_filter = Q(treatment_session=session)
    if session.clinical_note_id:
        note_filter |= Q(pk=session.clinical_note_id)

    return (
        ClinicalNote.objects
        .select_related("patient", "appointment")
        .filter(
            note_filter,
            patient=session.patient,
            patient__clinic=clinic,
            appointment=session.appointment,
            appointment__clinic=clinic,
        )
        .order_by("-updated_at")
        .first()
    )


def _clinical_note_matches_summary(note, summary):
    if note is None or not summary:
        return False

    soap_json, extract_json, followups_json = (
        _build_clinical_note_data_from_session_summary(summary)
    )
    return (
        (note.soap_json or {}) == soap_json
        and (note.extract_json or {}) == extract_json
        and (note.followups_json or []) == followups_json
    )


def build_treatment_session_flow_state(
    session,
    chunks,
    *,
    clinical_note_exists=False,
    clinical_note_is_current=False,
):
    chunks = list(chunks or [])
    has_chunks = bool(chunks)
    has_transcript = bool((session.transcript_text or "").strip())
    has_summary = bool(session.summary_json)
    is_confirmed = bool(session.confirmed_summary_json)
    failed_chunks = [
        chunk
        for chunk in chunks
        if chunk.status == TreatmentSessionChunk.Status.FAILED
        or bool((chunk.error_message or "").strip())
    ]
    pending_transcription_chunks = [
        chunk
        for chunk in chunks
        if chunk.audio_file
        and not (chunk.transcript_text or "").strip()
        and chunk.status != TreatmentSessionChunk.Status.TRANSCRIBING
    ]
    is_transcribing = (
        session.status == TreatmentSession.Status.TRANSCRIBING
        or any(
            chunk.status == TreatmentSessionChunk.Status.TRANSCRIBING
            for chunk in chunks
        )
    )
    is_summarizing = session.status == TreatmentSession.Status.SUMMARIZING
    has_error = bool(
        session.status == TreatmentSession.Status.FAILED
        or (session.error_message or "").strip()
        or failed_chunks
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
        if session.appointment_id:
            next_action = (
                "確認済みのカルテ案をカルテへ登録してください。"
                if not clinical_note_exists
                else "確認済みの変更内容をカルテへ反映してください。"
            )
        else:
            next_action = (
                "カルテへ登録するには、本日の予約を作成または選択してください。"
            )
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
    elif has_chunks:
        key = "transcription_waiting"
        label = "文字起こし待ち"
        tone = "attention"
        next_action = "保存済みの録音データを文字起こししてください。"
    else:
        key = "recording_ready"
        label = "録音準備中"
        tone = "ready"
        next_action = "施術録音を開始してください。"

    recording_stage = "done" if has_chunks else "current"
    transcription_stage = "pending"
    summary_stage = "pending"
    confirmation_stage = "pending"
    registration_stage = "pending"

    if is_transcribing:
        transcription_stage = "current"
    elif has_transcript:
        transcription_stage = "done"
    elif has_chunks:
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
    elif is_confirmed and session.appointment_id:
        registration_stage = "current"

    if has_error:
        for stage in (
            "registration_stage",
            "confirmation_stage",
            "summary_stage",
            "transcription_stage",
            "recording_stage",
        ):
            if locals()[stage] == "current":
                if stage == "registration_stage":
                    registration_stage = "error"
                elif stage == "confirmation_stage":
                    confirmation_stage = "error"
                elif stage == "summary_stage":
                    summary_stage = "error"
                elif stage == "transcription_stage":
                    transcription_stage = "error"
                else:
                    recording_stage = "error"
                break

    return {
        "key": key,
        "label": label,
        "tone": tone,
        "next_action": next_action,
        "has_chunks": has_chunks,
        "has_transcript": has_transcript,
        "has_summary": has_summary,
        "is_confirmed": is_confirmed,
        "is_registered": clinical_note_exists and clinical_note_is_current,
        "clinical_note_exists": clinical_note_exists,
        "clinical_note_is_current": clinical_note_is_current,
        "has_error": has_error,
        "is_processing": is_transcribing or is_summarizing,
        "pending_transcription_count": len(pending_transcription_chunks),
        "can_summarize": (
            has_transcript
            and not pending_transcription_chunks
            and not is_transcribing
            and not is_summarizing
        ),
        "can_confirm": has_summary and not is_summarizing,
        "can_register": (
            is_confirmed
            and bool(session.appointment_id)
            and not (clinical_note_exists and clinical_note_is_current)
        ),
        "stages": [
            {"label": "録音", "status": recording_stage},
            {"label": "文字起こし", "status": transcription_stage},
            {"label": "カルテ案", "status": summary_stage},
            {"label": "確認", "status": confirmation_stage},
            {"label": "カルテ登録", "status": registration_stage},
        ],
        "error_messages": list(
            dict.fromkeys(
                [
                    message
                    for message in [
                        (session.error_message or "").strip(),
                        *[
                            (chunk.error_message or "").strip()
                            for chunk in failed_chunks
                        ],
                    ]
                    if message
                ]
            )
        ),
    }


def _get_or_create_appointment_session(*, appointment, clinic, patient, intake, user):
    session = (
        TreatmentSession.objects
        .filter(
            appointment=appointment,
            clinic=clinic,
            patient=patient,
        )
        .first()
    )
    if session:
        return session, False

    try:
        with transaction.atomic():
            session = TreatmentSession.objects.create(
                appointment=appointment,
                clinic=clinic,
                patient=patient,
                intake=intake,
                title="施術セッション",
                status=TreatmentSession.Status.PENDING,
                created_by=user,
                updated_by=user,
            )
    except IntegrityError:
        session = (
            TreatmentSession.objects
            .filter(
                appointment=appointment,
                clinic=clinic,
                patient=patient,
            )
            .first()
        )
        return session, False

    return session, True


@staff_required
def treatment_session_start_view(request, appointment_id):
    """
    予約から施術セッションを開始する。
    まずは TreatmentSession を作成し、詳細画面へ遷移する。
    """
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の施術録音のみ操作できます。")

    appointment = get_object_or_404(
        Appointment.objects.select_related("clinic", "patient"),
        pk=appointment_id,
        clinic=clinic,
        patient__clinic=clinic,
    )

    intake = (
        Intake.objects
        .filter(
            appointment=appointment,
            clinic=clinic,
            patient=appointment.patient,
        )
        .first()
    )

    session, created = _get_or_create_appointment_session(
        appointment=appointment,
        clinic=clinic,
        patient=appointment.patient,
        intake=intake,
        user=request.user,
    )
    if session is None:
        return HttpResponseForbidden("所属院の施術録音のみ操作できます。")

    if created:
        messages.success(request, "施術セッションを作成しました。")
    else:
        messages.info(request, "既存の施術セッションを開きます。")

    return redirect("treatment_sessions:detail", session_id=session.id)


@staff_required
def treatment_session_detail_view(request, session_id):
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の施術録音のみ閲覧できます。")

    session = get_object_or_404(
        _session_scope_for_clinic(clinic)
        .select_related(
            "clinic",
            "patient",
            "appointment",
            "intake",
            "treatment_plan",
        )
        .prefetch_related("chunks"),
        pk=session_id,
    )
    chunks = list(session.chunks.all())
    registered_clinical_note = _get_registered_clinical_note(session, clinic)
    clinical_note_is_current = _clinical_note_matches_summary(
        registered_clinical_note,
        session.confirmed_summary_json or {},
    )
    flow_state = build_treatment_session_flow_state(
        session,
        chunks,
        clinical_note_exists=registered_clinical_note is not None,
        clinical_note_is_current=clinical_note_is_current,
    )

    summary = _as_summary_dict(session.active_summary)

    session_summary = _as_summary_dict(summary.get("session_summary"))
    clinical_assessment = _as_summary_dict(summary.get("clinical_assessment"))
    treatment = _as_summary_dict(summary.get("treatment"))
    explanation = _as_summary_dict(summary.get("explanation"))
    next_plan = _as_summary_dict(summary.get("next_plan"))
    soap = _as_summary_dict(summary.get("soap"))
    progress_note = _as_summary_dict(summary.get("progress_note"))

    context = {
        "session": session,
        "chunks": chunks,
        "flow_state": flow_state,
        "registered_clinical_note": registered_clinical_note,
        "summary": summary,
        "important_points": _as_summary_list(summary.get("important_points")),
        "session_summary": session_summary,
        "clinical_assessment": clinical_assessment,
        "treatment": treatment,
        "explanation": explanation,
        "next_plan": next_plan,
        "soap": soap,
        "progress_note": progress_note,
        "relationship_notes": _as_summary_list(
            summary.get("relationship_notes")
        ),
        "missing_information": _as_summary_list(
            summary.get("missing_information")
        ),
        "safety_notes": _as_summary_list(summary.get("safety_notes")),
        "summary_json_pretty": json.dumps(summary, ensure_ascii=False, indent=2),
    }

    return render(
        request,
        "treatment_sessions/session_detail.html",
        context,
    )


@staff_required
def treatment_session_confirm_view(request, session_id):
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の施術録音のみ操作できます。")

    session = get_object_or_404(
        _session_scope_for_clinic(clinic)
        .select_related(
            "clinic",
            "patient",
            "appointment",
            "intake",
            "confirmed_by",
        ),
        pk=session_id,
    )

    source_summary = (
        session.confirmed_summary_json
        or session.summary_json
        or {}
    )
    if not source_summary:
        messages.warning(
            request,
            "録音内容からカルテ案を作成してから、確認・修正してください。",
        )
        return redirect("treatment_sessions:detail", session_id=session.id)

    if request.method == "POST":
        form = TreatmentSessionConfirmForm(
            request.POST,
            summary=source_summary,
        )
        if form.is_valid():
            confirmed_summary = form.build_confirmed_summary()
            with transaction.atomic():
                locked_session = get_object_or_404(
                    _session_scope_for_clinic(clinic)
                    .select_for_update(of=("self",)),
                    pk=session.id,
                )
                if locked_session.status in {
                    TreatmentSession.Status.TRANSCRIBING,
                    TreatmentSession.Status.SUMMARIZING,
                }:
                    messages.info(
                        request,
                        "文字起こしまたはカルテ案作成中です。完了後に確認内容を保存してください。",
                    )
                    return redirect(
                        "treatment_sessions:session_confirm",
                        session_id=session.id,
                    )

                current_source_summary = (
                    locked_session.confirmed_summary_json
                    or locked_session.summary_json
                    or {}
                )
                if current_source_summary != source_summary:
                    messages.warning(
                        request,
                        "保存中にカルテ案が更新されました。最新内容を確認してから、もう一度保存してください。",
                    )
                    return redirect(
                        "treatment_sessions:session_confirm",
                        session_id=session.id,
                    )

                if (
                    locked_session.summary_status == "confirmed"
                    and locked_session.confirmed_summary_json
                    == confirmed_summary
                ):
                    messages.info(request, "確認内容はすでに保存されています。")
                else:
                    locked_session.mark_confirmed(
                        user=request.user,
                        data=confirmed_summary,
                    )
                    locked_session.updated_by = request.user
                    locked_session.save(
                        update_fields=[
                            "confirmed_summary_json",
                            "summary_status",
                            "confirmed_at",
                            "confirmed_by",
                            "updated_by",
                            "updated_at",
                        ]
                    )
                    messages.success(
                        request,
                        "確認内容を保存しました。カルテへ登録できます。",
                    )
            return redirect(
                "treatment_sessions:session_confirm",
                session_id=session.id,
            )
    else:
        form = TreatmentSessionConfirmForm(summary=source_summary)

    registered_clinical_note = _get_registered_clinical_note(session, clinic)
    clinical_note_is_current = _clinical_note_matches_summary(
        registered_clinical_note,
        session.confirmed_summary_json or {},
    )
    flow_state = build_treatment_session_flow_state(
        session,
        session.chunks.all(),
        clinical_note_exists=registered_clinical_note is not None,
        clinical_note_is_current=clinical_note_is_current,
    )

    return render(
        request,
        "treatment_sessions/session_confirm.html",
        {
            "session": session,
            "form": form,
            "is_confirmed": bool(session.confirmed_summary_json),
            "flow_state": flow_state,
            "registered_clinical_note": registered_clinical_note,
        },
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
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の施術録音のみ操作できます。")

    patient = get_object_or_404(
        Patient.objects.select_related("clinic"),
        pk=patient_id,
        clinic=clinic,
    )

    now = timezone.now()
    today = timezone.localdate()

    appointment = (
        Appointment.objects
        .filter(
            clinic=clinic,
            patient=patient,
            start_at__date=today,
            start_at__gte=now,
        )
        .exclude(
            status__in=[
                Appointment.Status.CANCELLED,
                Appointment.Status.NO_SHOW,
            ]
        )
        .order_by("start_at")
        .first()
    )

    if appointment is None:
        appointment = (
            Appointment.objects
            .filter(
                clinic=clinic,
                patient=patient,
                start_at__date=today,
            )
            .exclude(
                status__in=[
                    Appointment.Status.CANCELLED,
                    Appointment.Status.NO_SHOW,
                ]
            )
            .order_by("-start_at")
            .first()
        )

    intake = None
    if appointment:
        intake = (
            Intake.objects
            .filter(
                appointment=appointment,
                clinic=clinic,
                patient=patient,
            )
            .first()
        )

        session, created = _get_or_create_appointment_session(
            appointment=appointment,
            clinic=clinic,
            patient=patient,
            intake=intake,
            user=request.user,
        )
        if session is None:
            return HttpResponseForbidden("所属院の施術録音のみ操作できます。")

        if created:
            messages.success(request, "施術セッションを作成しました。")
        else:
            messages.info(request, "この予約の施術セッションを開きます。")

        return redirect("treatment_sessions:detail", session_id=session.id)

    existing_session = (
        TreatmentSession.objects
        .filter(
            clinic=clinic,
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
        clinic=clinic,
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
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return JsonResponse(
            {"ok": False, "error": "所属院の施術録音のみ操作できます。"},
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

    with transaction.atomic():
        session = get_object_or_404(
            _session_scope_for_clinic(clinic)
            .select_for_update(of=("self",)),
            pk=session_id,
        )
        if session.status in {
            TreatmentSession.Status.TRANSCRIBING,
            TreatmentSession.Status.SUMMARIZING,
        }:
            return JsonResponse(
                {
                    "ok": False,
                    "error": "文字起こしまたはカルテ案作成中のため、録音を追加できません。",
                },
                status=409,
            )

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
        session.error_message = ""
        session.updated_by = request.user

        # 新しい録音が追加されたため、以前のカルテ案と確認内容は無効化する。
        session.summary_json = {}
        session.confirmed_summary_json = {}
        session.summary_status = "draft"
        session.confirmed_by = None
        session.confirmed_at = None

        if not session.started_at:
            session.started_at = timezone.now()

        session.ended_at = timezone.now()

        session.save(
            update_fields=[
                "total_duration_sec",
                "status",
                "error_message",
                "updated_by",
                "summary_json",
                "confirmed_summary_json",
                "summary_status",
                "confirmed_by",
                "confirmed_at",
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
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の施術録音のみ操作できます。")

    try:
        with transaction.atomic():
            session = get_object_or_404(
                _session_scope_for_clinic(clinic)
                .select_for_update(of=("self",)),
                chunks__pk=chunk_id,
            )
            chunk = get_object_or_404(
                TreatmentSessionChunk.objects
                .select_for_update(of=("self",)),
                pk=chunk_id,
                session=session,
            )

            if not chunk.audio_file:
                messages.error(request, "音声ファイルがありません。")
                return redirect(
                    "treatment_sessions:detail",
                    session_id=session.id,
                )

            if (
                chunk.status == TreatmentSessionChunk.Status.TRANSCRIBING
                or session.status == TreatmentSession.Status.TRANSCRIBING
            ):
                messages.info(request, "文字起こしはすでに処理中です。")
                return redirect(
                    "treatment_sessions:detail",
                    session_id=session.id,
                )

            if session.status == TreatmentSession.Status.SUMMARIZING:
                messages.info(
                    request,
                    "カルテ案を作成中のため、文字起こしを開始できません。",
                )
                return redirect(
                    "treatment_sessions:detail",
                    session_id=session.id,
                )

            if chunk.transcript_text:
                messages.info(request, "この録音はすでに文字起こし済みです。")
                return redirect(
                    "treatment_sessions:detail",
                    session_id=session.id,
                )

            chunk.status = TreatmentSessionChunk.Status.TRANSCRIBING
            chunk.error_message = ""
            chunk.save(
                update_fields=["status", "error_message", "updated_at"]
            )

            session.status = TreatmentSession.Status.TRANSCRIBING
            session.error_message = ""
            session.updated_by = request.user
            session.save(
                update_fields=[
                    "status",
                    "error_message",
                    "updated_by",
                    "updated_at",
                ]
            )

            audio_file = chunk.audio_file
            mime_type = chunk.mime_type
            session_id = session.id
            had_confirmed_summary = bool(session.confirmed_summary_json)

        transcript_text, transcript_json = run_stt(
            audio_file,
            mime_type,
        )

        with transaction.atomic():
            session = get_object_or_404(
                _session_scope_for_clinic(clinic)
                .select_for_update(of=("self",)),
                pk=session_id,
            )
            chunk = get_object_or_404(
                TreatmentSessionChunk.objects
                .select_for_update(of=("self",)),
                pk=chunk_id,
                session=session,
            )

            chunk.transcript_text = transcript_text or ""
            chunk.transcript_json = transcript_json or {}
            chunk.status = TreatmentSessionChunk.Status.SUMMARIZED
            chunk.error_message = ""
            chunk.save(
                update_fields=[
                    "transcript_text",
                    "transcript_json",
                    "status",
                    "error_message",
                    "updated_at",
                ]
            )

            chunks = list(session.chunks.order_by("chunk_index"))
            combined_transcript = "\n\n".join(
                [
                    f"[chunk {item.chunk_index}]\n{item.transcript_text}"
                    for item in chunks
                    if item.transcript_text
                ]
            )
            total_duration = sum(item.duration_sec or 0 for item in chunks)

            session.transcript_text = combined_transcript
            session.total_duration_sec = total_duration
            session.status = TreatmentSession.Status.UPLOADED
            session.error_message = ""
            session.updated_by = request.user

            # 文字起こしが更新されたため、以前のカルテ案と確認内容は無効化する。
            session.summary_json = {}
            session.confirmed_summary_json = {}
            session.summary_status = "draft"
            session.confirmed_by = None
            session.confirmed_at = None

            session.save(
                update_fields=[
                    "transcript_text",
                    "total_duration_sec",
                    "status",
                    "error_message",
                    "updated_by",
                    "summary_json",
                    "confirmed_summary_json",
                    "summary_status",
                    "confirmed_by",
                    "confirmed_at",
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
                model_name=(chunk.transcript_json or {}).get("model") or DEFAULT_STT_MODEL,
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

        if had_confirmed_summary:
            messages.success(
                request,
                "文字起こしが更新されました。以前の確認済みカルテ案はリセットされたため、カルテ登録前に再度確認してください。",
            )
        else:
            messages.success(request, "施術録音の文字起こしが完了しました。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    except Exception as e:
        with transaction.atomic():
            session = get_object_or_404(
                _session_scope_for_clinic(clinic)
                .select_for_update(of=("self",)),
                chunks__pk=chunk_id,
            )
            chunk = get_object_or_404(
                TreatmentSessionChunk.objects
                .select_for_update(of=("self",)),
                pk=chunk_id,
                session=session,
            )
            chunk.status = TreatmentSessionChunk.Status.FAILED
            chunk.error_message = str(e)
            chunk.save(
                update_fields=["status", "error_message", "updated_at"]
            )

            session.status = TreatmentSession.Status.FAILED
            session.error_message = str(e)
            session.updated_by = request.user
            session.save(
                update_fields=[
                    "status",
                    "error_message",
                    "updated_by",
                    "updated_at",
                ]
            )

        try:
            AiUsageLog.objects.create(
                clinic=session.clinic,
                patient=session.patient,
                appointment=session.appointment,
                intake=session.intake,
                usage_type=AiUsageLog.UsageType.STT,
                status=AiUsageLog.Status.FAILED,
                model_name=DEFAULT_STT_MODEL,
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
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の施術録音のみ操作できます。")

    session = get_object_or_404(
        _session_scope_for_clinic(clinic),
        pk=session_id,
    )
    ai_usage_summary = build_ai_usage_summary(clinic)

    if not ai_usage_summary.can_use_ai:
        messages.error(
            request,
            ai_usage_summary.warning_message or "AI利用上限に達しているため要約できません。",
        )
        return redirect("treatment_sessions:detail", session_id=session.id)

    force = request.POST.get("force") == "1"

    try:
        with transaction.atomic():
            session = get_object_or_404(
                _session_scope_for_clinic(clinic)
                .select_for_update(of=("self",)),
                pk=session_id,
            )

            if session.status == TreatmentSession.Status.SUMMARIZING:
                messages.info(request, "カルテ案はすでに作成処理中です。")
                return redirect(
                    "treatment_sessions:detail",
                    session_id=session.id,
                )

            if session.status == TreatmentSession.Status.TRANSCRIBING:
                messages.info(
                    request,
                    "文字起こし中のため、カルテ案を作成できません。",
                )
                return redirect(
                    "treatment_sessions:detail",
                    session_id=session.id,
                )

            pending_chunks = TreatmentSessionChunk.objects.filter(
                session=session,
                audio_file__isnull=False,
                transcript_text="",
            ).exclude(status=TreatmentSessionChunk.Status.SUMMARIZED)
            if pending_chunks.exists():
                messages.warning(
                    request,
                    "文字起こし待ちの録音があります。すべて文字起こししてからカルテ案を作成してください。",
                )
                return redirect(
                    "treatment_sessions:detail",
                    session_id=session.id,
                )

            if not session.transcript_text:
                messages.error(
                    request,
                    "統合文字起こしがないため、カルテ案を作成できません。",
                )
                return redirect(
                    "treatment_sessions:detail",
                    session_id=session.id,
                )

            if session.summary_json and not force:
                messages.info(
                    request,
                    "カルテ案はすでに作成済みです。確認・修正画面へ進んでください。",
                )
                return redirect(
                    "treatment_sessions:session_confirm",
                    session_id=session.id,
                )

            transcript_text = session.transcript_text
            had_confirmed_summary = bool(session.confirmed_summary_json)
            session.status = TreatmentSession.Status.SUMMARIZING
            session.error_message = ""
            session.updated_by = request.user
            session.save(
                update_fields=[
                    "status",
                    "error_message",
                    "updated_by",
                    "updated_at",
                ]
            )

        summary = summarize_treatment_session(transcript_text)

        with transaction.atomic():
            session = get_object_or_404(
                _session_scope_for_clinic(clinic)
                .select_for_update(of=("self",)),
                pk=session_id,
            )
            session.summary_json = summary or {}
            session.confirmed_summary_json = {}
            session.summary_status = "draft"
            session.confirmed_by = None
            session.confirmed_at = None
            session.status = TreatmentSession.Status.DONE
            session.error_message = ""
            session.updated_by = request.user
            session.save(
                update_fields=[
                    "summary_json",
                    "confirmed_summary_json",
                    "summary_status",
                    "confirmed_by",
                    "confirmed_at",
                    "status",
                    "error_message",
                    "updated_by",
                    "updated_at",
                ]
            )

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

        if force and had_confirmed_summary:
            messages.success(
                request,
                "録音内容からカルテ案を再作成しました。確認済み内容はリセットされています。カルテ登録前に再度確認してください。",
            )
        elif force:
            messages.success(request, "録音内容からカルテ案を再作成しました。")
        else:
            messages.success(request, "録音内容からカルテ案を作成しました。")
        return redirect("treatment_sessions:detail", session_id=session.id)

    except Exception as e:
        with transaction.atomic():
            session = get_object_or_404(
                _session_scope_for_clinic(clinic)
                .select_for_update(of=("self",)),
                pk=session_id,
            )
            session.status = TreatmentSession.Status.FAILED
            session.error_message = str(e)
            session.updated_by = request.user
            session.save(
                update_fields=[
                    "status",
                    "error_message",
                    "updated_by",
                    "updated_at",
                ]
            )

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

        messages.error(request, f"カルテ案の作成に失敗しました: {e}")
        return redirect("treatment_sessions:detail", session_id=session.id)
    
def _build_clinical_note_data_from_session_summary(summary: dict) -> tuple[dict, dict, list]:
    """
    TreatmentSession.summary_json を ClinicalNote 用の
    soap_json / extract_json / followups_json に変換する。
    """
    summary = _as_summary_dict(summary)

    important_points = _as_summary_list(summary.get("important_points"))
    session_summary = _as_summary_dict(summary.get("session_summary"))
    clinical_assessment = _as_summary_dict(summary.get("clinical_assessment"))
    treatment = _as_summary_dict(summary.get("treatment"))
    explanation = _as_summary_dict(summary.get("explanation"))
    next_plan = _as_summary_dict(summary.get("next_plan"))
    soap = _as_summary_dict(summary.get("soap"))
    progress_note = _as_summary_dict(summary.get("progress_note"))

    relationship_notes = _as_summary_list(summary.get("relationship_notes"))
    missing_information = _as_summary_list(summary.get("missing_information"))
    safety_notes = _as_summary_list(summary.get("safety_notes"))

    # SOAPはClinicalNoteでそのまま使える形
    soap_json = {
        "S": _as_summary_list(soap.get("S")),
        "O": _as_summary_list(soap.get("O")),
        "A": _as_summary_list(soap.get("A")),
        "P": _as_summary_list(soap.get("P")),
    }

    # extract_jsonには後から画面表示・検索・施術計画生成に使いやすい情報を集約
    extract_json = {
        "source": "treatment_session",
        "important_points": important_points,

        "chief_complaint": session_summary.get("chief_complaint", ""),
        "visit_type": session_summary.get("visit_type", "unknown"),
        "overall_summary": session_summary.get("overall_summary", ""),
        "progress_change": session_summary.get("progress_change") or {},

        "checked_areas": _as_summary_list(
            clinical_assessment.get("checked_areas")
        ),
        "pain_areas": _as_summary_list(
            clinical_assessment.get("pain_areas")
        ),
        "movement_tests": _as_summary_list(
            clinical_assessment.get("movement_tests")
        ),
        "findings": _as_summary_list(clinical_assessment.get("findings")),
        "suspected_causes": _as_summary_list(
            clinical_assessment.get("suspected_causes")
        ),
        "treatment_intent": clinical_assessment.get("treatment_intent", ""),

        # 既存の画面が locations を見る可能性があるので互換用に入れる
        "locations": (
            _as_summary_list(clinical_assessment.get("pain_areas"))
            or _as_summary_list(clinical_assessment.get("checked_areas"))
        ),

        "performed_treatments": _as_summary_list(
            treatment.get("performed_treatments")
        ),
        "target_areas": _as_summary_list(treatment.get("target_areas")),
        "patient_response": treatment.get("patient_response", ""),
        "after_treatment_change": treatment.get("after_treatment_change", ""),

        "explained_to_patient": _as_summary_list(
            explanation.get("explained_to_patient")
        ),
        "lifestyle_guidance": _as_summary_list(
            explanation.get("lifestyle_guidance")
        ),
        "home_care": _as_summary_list(explanation.get("home_care")),
        "cautions_until_next_visit": _as_summary_list(
            explanation.get("cautions_until_next_visit")
        ),

        "next_plan": next_plan,
        "next_treatment_policy": next_plan.get("next_treatment_policy", ""),
        "recommended_visit_timing": next_plan.get("recommended_visit_timing", ""),
        "items_to_check_next_time": _as_summary_list(
            next_plan.get("items_to_check_next_time")
        ),

        "progress_note": progress_note,
        "relationship_notes": relationship_notes,
        "missing_information": missing_information,
        "safety_notes": safety_notes,
    }

    # followups_json は「次回確認」「不足情報」「注意事項」をまとめておく
    followups_json = []

    for item in _as_summary_list(next_plan.get("items_to_check_next_time")):
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
    clinic = _get_staff_clinic(request)
    if clinic is None:
        return HttpResponseForbidden("所属院の施術録音のみ操作できます。")

    session = get_object_or_404(
        _session_scope_for_clinic(clinic)
        .select_for_update(of=("self",)),
        pk=session_id,
    )

    if session.status in {
        TreatmentSession.Status.TRANSCRIBING,
        TreatmentSession.Status.SUMMARIZING,
    }:
        messages.info(
            request,
            "処理中のため、カルテ登録は完了後に行ってください。",
        )
        return redirect("treatment_sessions:detail", session_id=session.id)

    if not session.appointment:
        messages.error(
            request,
            "この施術セッションには予約が紐づいていないため、カルテ登録できません。先に予約と紐づけてください。",
        )
        return redirect("treatment_sessions:detail", session_id=session.id)

    if not session.confirmed_summary_json:
        messages.warning(
            request,
            "カルテへ登録する前に、録音内容から作成したカルテ案を確認・修正してください。",
        )
        return redirect(
            "treatment_sessions:session_confirm",
            session_id=session.id,
        )

    summary = session.confirmed_summary_json or session.summary_json or {}

    if not summary:
        messages.error(request, "カルテ案が未作成のため、カルテに登録できません。")
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
        .select_for_update(of=("self",))
        .filter(
            appointment=appointment,
            patient__clinic=session.clinic,
            appointment__clinic=session.clinic,
        )
        .first()
    )

    note_content_changed = bool(
        existing_note
        and (
            (existing_note.soap_json or {}) != soap_json
            or (existing_note.extract_json or {}) != extract_json
            or (existing_note.followups_json or []) != followups_json
            or (existing_note.web_intake_snapshot or {}) != web_snapshot
        )
    )

    if (
        existing_note
        and not note_content_changed
        and existing_note.treatment_session_id == session.id
    ):
        if session.clinical_note_id != existing_note.id:
            session.clinical_note = existing_note
            session.updated_by = request.user
            session.save(
                update_fields=["clinical_note", "updated_by", "updated_at"]
            )
        messages.info(request, "この確認内容はすでにカルテへ登録済みです。")
        return redirect(
            "staff:clinical_note_detail",
            pk=existing_note.id,
        )

    # 内容が変わる既存カルテのみ、更新前履歴を1件残す。
    if note_content_changed:
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
        messages.success(request, "確認済みのカルテ案をカルテに登録しました。")
    else:
        messages.success(request, "確認済みのカルテ案で既存カルテを更新しました。")

    return redirect("staff:patient_detail", patient_id=patient.id)
