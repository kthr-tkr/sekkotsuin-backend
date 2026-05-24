from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from apps.patients.models import Patient
from apps.appointments.models import Appointment
from apps.intakes.models import Intake
from apps.clinical_notes.models import ClinicalNote

from .forms import TreatmentPlanForm, TreatmentProgressForm
from .models import TreatmentPlan, TreatmentProgress, TreatmentPlanConsent
from django.views.decorators.http import require_POST
import json
from django.utils import timezone
import base64
import uuid

from django.core.files.base import ContentFile
from django.http import HttpResponseBadRequest
from django.db import transaction

@login_required
def plan_create_view(request, patient_id=None, appointment_id=None):
    patient = None
    appointment = None
    intake = None
    clinical_note = None

    if patient_id:
        patient = get_object_or_404(Patient, pk=patient_id)

    if appointment_id:
        appointment = get_object_or_404(
            Appointment.objects.select_related("patient", "intake"),
            pk=appointment_id
        )
        if patient is None:
            patient = appointment.patient
        intake = getattr(appointment, "intake", None)

        clinical_note = (
            ClinicalNote.objects
            .filter(appointment=appointment)
            .order_by("-created_at")
            .first()
        )

    initial = {}
    if intake:
        if getattr(intake, "chief_complaint", None):
            initial["chief_complaint"] = intake.chief_complaint
        elif getattr(intake, "payload", None):
            chief = intake.payload.get("chief_complaint")
            if chief:
                initial["chief_complaint"] = chief

    if request.method == "POST":
        form = TreatmentPlanForm(request.POST)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.patient = patient
            plan.appointment = appointment
            plan.intake = intake
            plan.clinical_note = clinical_note
            plan.created_by = request.user
            plan.save()

            messages.success(request, "施術計画を作成しました。")
            return redirect("treatment_plans:plan_detail", pk=plan.pk)
    else:
        form = TreatmentPlanForm(initial=initial)

    return render(request, "treatment_plans/plan_form.html", {
        "form": form,
        "patient": patient,
        "appointment": appointment,
        "intake": intake,
        "clinical_note": clinical_note,
        "page_title": "施術計画作成",
    })


@login_required
def plan_detail_view(request, pk):
    plan = get_object_or_404(
        TreatmentPlan.objects.select_related(
            "patient", "appointment", "intake", "clinical_note", "created_by"
        ),
        pk=pk
    )

    active_tab = request.GET.get("tab", "overview")
    valid_tabs = ["overview", "progress", "patient_explanation", "appointments"]
    if active_tab not in valid_tabs:
        active_tab = "overview"

    progress_qs = plan.progress_logs.all()

    progress_logs_asc = list(progress_qs.order_by("visit_date", "created_at"))
    for idx, log in enumerate(progress_logs_asc, start=1):
        log.visit_number = idx

    progress_logs = sorted(
        progress_logs_asc,
        key=lambda x: (x.visit_date, x.created_at),
        reverse=True
    )

    progress_count = len(progress_logs_asc)
    latest_progress = progress_logs[0] if progress_logs else None

    pain_logs = [log for log in progress_logs_asc if log.pain_level is not None]
    first_pain_level = pain_logs[0].pain_level if pain_logs else None
    latest_pain_level = pain_logs[-1].pain_level if pain_logs else None

    now = timezone.now()

    plan_appointments = (
        Appointment.objects
        .filter(treatment_plan=plan)
        .select_related("assigned_staff")
        .order_by("-start_at")
    )

    next_plan_appointment = (
        plan_appointments
        .filter(
            start_at__gte=now,
            status__in=[
                Appointment.Status.PENDING,
                Appointment.Status.BOOKED,
                Appointment.Status.ARRIVED,
            ],
        )
        .order_by("start_at")
        .first()
    )

    appointment_count = plan_appointments.count()

    pain_diff = None
    pain_trend_label = "データなし"

    if first_pain_level is not None and latest_pain_level is not None:
        pain_diff = latest_pain_level - first_pain_level

        if pain_diff <= -3:
            pain_trend_label = "大きく改善"
        elif pain_diff <= -1:
            pain_trend_label = "改善傾向"
        elif pain_diff == 0:
            pain_trend_label = "横ばい"
        else:
            pain_trend_label = "再評価候補"

    pain_history = [
        {
            "visit_number": log.visit_number,
            "visit_date": log.visit_date,
            "pain_level": log.pain_level,
        }
        for log in pain_logs
    ]

    pain_chart_labels = [
        f"第{log.visit_number}回"
        for log in pain_logs
    ]

    pain_chart_values = [
        log.pain_level
        for log in pain_logs
    ]

    improvement_rate = None
    if first_pain_level is not None and latest_pain_level is not None and first_pain_level > 0:
        improvement_rate = round(((first_pain_level - latest_pain_level) / first_pain_level) * 100)

    progress_comment = ""
    progress_comment_level = "muted"

    if progress_count == 0:
        progress_comment = "まだ経過記録がありません。初回施術後の状態変化を記録していきましょう。"
        progress_comment_level = "muted"
    elif not pain_logs:
        progress_comment = "痛みレベルの記録が未入力のため、経過判定は保留です。今後の記録入力で推移を確認できます。"
        progress_comment_level = "muted"
    else:
        if pain_diff <= -3:
            progress_comment = "施術開始時と比較して痛みレベルが大きく改善しています。現在の施術方針を継続しながら、日常生活指導の定着を確認するとよさそうです。"
            progress_comment_level = "good"
        elif pain_diff <= -1:
            progress_comment = "改善傾向が見られます。現在の方針を継続しつつ、症状変化と生活動作の安定を引き続き観察してください。"
            progress_comment_level = "good"
        elif pain_diff == 0:
            progress_comment = "痛みレベルは横ばいです。施術内容、生活負荷、セルフケア実施状況を再確認する候補です。"
            progress_comment_level = "warn"
        else:
            progress_comment = "痛みレベルが悪化傾向です。主訴の再確認、誘発動作の見直し、施術方針の再評価を検討してください。"
            progress_comment_level = "bad"

    next_actions = []
    next_action_level = "muted"

    if progress_count == 0:
        next_actions = [
            "初回施術後の症状変化を記録する",
            "痛みレベルを次回以降なるべく継続入力する",
            "次回来院日を設定して継続フォローにつなげる",
        ]
        next_action_level = "muted"
    elif not pain_logs:
        next_actions = [
            "次回から痛みレベルを記録して推移を可視化する",
            "症状変化とADLの変化をセットで確認する",
            "セルフケアや生活指導の実施状況を記録に残す",
        ]
        next_action_level = "muted"
    else:
        if pain_diff <= -3:
            next_actions = [
                "現在の施術方針を継続する",
                "生活指導・セルフケアの定着状況を確認する",
                "改善が安定していれば来院頻度の調整も検討する",
            ]
            next_action_level = "good"
        elif pain_diff <= -1:
            next_actions = [
                "現行の施術方針を継続する",
                "日常生活での負荷動作が減っているか確認する",
                "次回来院時に可動域やADLの改善も確認する",
            ]
            next_action_level = "good"
        elif pain_diff == 0:
            next_actions = [
                "施術内容の見直し候補として記録を再確認する",
                "負荷動作や仕事・生活習慣の変化をヒアリングする",
                "セルフケアの実施状況を再確認する",
            ]
            next_action_level = "warn"
        else:
            next_actions = [
                "主訴と誘発動作を再評価する",
                "施術刺激量やアプローチ方法の見直しを検討する",
                "必要に応じて再問診や他医療機関との連携も検討する",
            ]
            next_action_level = "bad"

    plan_appointments = (
        Appointment.objects
        .filter(treatment_plan=plan)
        .select_related("assigned_staff")
        .order_by("-start_at")
    )

    return render(request, "treatment_plans/plan_detail.html", {
        "plan": plan,
        "active_tab": active_tab,

        "progress_logs": progress_logs,
        "progress_count": progress_count,
        "progress_tab_count": progress_count,
        "latest_progress": latest_progress,

        "first_pain_level": first_pain_level,
        "latest_pain_level": latest_pain_level,
        "pain_diff": pain_diff,
        "pain_trend_label": pain_trend_label,
        "pain_history": pain_history,

        "progress_comment": progress_comment,
        "progress_comment_level": progress_comment_level,
        "next_actions": next_actions,
        "next_action_level": next_action_level,
        "progress_form": TreatmentProgressForm(),

        "plan_appointments": plan_appointments,
        "appointment_count": plan_appointments.count(),

        "page_title": "施術計画詳細",
        
        "pain_chart_labels_json": json.dumps(pain_chart_labels, ensure_ascii=False),
        "pain_chart_values_json": json.dumps(pain_chart_values, ensure_ascii=False),
        "improvement_rate": improvement_rate,
        "plan_appointments": plan_appointments,
        "next_plan_appointment": next_plan_appointment,
        "appointment_count": appointment_count,
        "current_path": request.get_full_path(),
    })

    todo_cards = []

    if not next_appointment:
        todo_cards.append({
            "type": "reservation",
            "title": "次回予約がありません",
            "message": "継続施術が必要な場合は予約を作成してください。",
            "button": "予約を作成",
        })

    if progress_count == 0:
        todo_cards.append({
            "type": "progress",
            "title": "施術経過を記録してください",
            "message": "初回施術後の状態変化を記録しましょう。",
            "button": "経過を追加",
        })

@login_required
@transaction.atomic
def plan_sign_view(request, pk):
    plan = get_object_or_404(
        TreatmentPlan.objects.select_related(
            "patient",
            "appointment",
            "intake",
            "clinical_note",
            "created_by",
        ),
        pk=pk,
    )

    latest_consent = (
        TreatmentPlanConsent.objects
        .filter(plan=plan, patient=plan.patient)
        .order_by("-signed_at")
        .first()
    )

    if request.method == "POST":
        signed_name = (request.POST.get("signed_name") or "").strip()
        signature_data = request.POST.get("signature_data") or ""

        if not signed_name:
            messages.error(request, "署名者名を入力してください。")
            return redirect("treatment_plans:plan_sign", pk=plan.pk)

        if not signature_data:
            messages.error(request, "サインを入力してください。")
            return redirect("treatment_plans:plan_sign", pk=plan.pk)

        if not signature_data.startswith("data:image/png;base64,"):
            return HttpResponseBadRequest("Invalid signature data")

        try:
            header, encoded = signature_data.split(",", 1)
            decoded_file = base64.b64decode(encoded)
        except Exception:
            return HttpResponseBadRequest("Invalid base64 signature")

        file_name = f"signature_{plan.pk}_{uuid.uuid4().hex}.png"

        plan_snapshot = {
            "plan_id": plan.id,
            "patient_id": plan.patient_id,
            "patient_name": f"{plan.patient.last_name} {plan.patient.first_name}",
            "title": plan.title,
            "chief_complaint": plan.chief_complaint,
            "status": plan.status,
            "next_visit_date": plan.next_visit_date.isoformat() if plan.next_visit_date else None,
            "visit_guide_type": plan.visit_guide_type,
            "visit_guide_type_display": plan.get_visit_guide_type_display() if plan.visit_guide_type else "",
            "visit_guide_count": plan.visit_guide_count,
            "visit_guide_unit_note": plan.visit_guide_unit_note,
            "bath_instruction": plan.bath_instruction,
            "walking_instruction": plan.walking_instruction,
            "exercise_instruction": plan.exercise_instruction,
            "work_instruction": plan.work_instruction,
            "lifestyle_other_instruction": plan.lifestyle_other_instruction,
            "caution_notes": plan.caution_notes,
            "expected_recovery_weeks_min": plan.expected_recovery_weeks_min,
            "expected_recovery_weeks_max": plan.expected_recovery_weeks_max,
            "rebound_reaction_note": plan.rebound_reaction_note,
            "explained_to_patient": True,
            "created_at": plan.created_at.isoformat() if plan.created_at else None,
        }

        consent = TreatmentPlanConsent.objects.create(
            plan=plan,
            patient=plan.patient,
            signed_name=signed_name,
            plan_snapshot=plan_snapshot,
            signed_by_user=request.user,
            ip_address=_get_client_ip(request),
            user_agent=request.META.get("HTTP_USER_AGENT", ""),
        )

        consent.signature_image.save(
            file_name,
            ContentFile(decoded_file),
            save=True,
        )

        plan.explained_to_patient = True
        plan.save(update_fields=["explained_to_patient", "updated_at"])

        messages.success(request, "患者様のサインを保存し、施術計画を説明済みにしました。")
        return redirect(f"{reverse('treatment_plans:plan_detail', args=[plan.pk])}?tab=patient_explanation")

    return render(request, "treatment_plans/plan_sign.html", {
        "plan": plan,
        "patient": plan.patient,
        "latest_consent": latest_consent,
        "page_title": "施術計画への同意サイン",
    })


def _get_client_ip(request):
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR")

@login_required
def progress_create_view(request, pk):
    plan = get_object_or_404(TreatmentPlan, pk=pk)

    if request.method != "POST":
        return redirect(f"{reverse('treatment_plans:plan_detail', kwargs={'pk': plan.pk})}?tab=progress#progress-form")

    form = TreatmentProgressForm(request.POST)
    if form.is_valid():
        progress = form.save(commit=False)
        progress.plan = plan
        progress.created_by = request.user
        progress.save()
        messages.success(request, "施術経過を追加しました。")
    else:
        messages.error(request, "施術経過の入力内容を確認してください。")
        return redirect(f"{reverse('treatment_plans:plan_detail', kwargs={'pk': plan.pk})}?tab=progress#progress-form")

    return redirect(f"{reverse('treatment_plans:plan_detail', kwargs={'pk': plan.pk})}?tab=progress#progress-list")

@login_required
def plan_edit_view(request, pk):
    plan = get_object_or_404(TreatmentPlan, pk=pk)

    if request.method == "POST":
        form = TreatmentPlanForm(request.POST, instance=plan)
        if form.is_valid():
            form.save()
            messages.success(request, "施術計画を更新しました。")
            return redirect("treatment_plans:plan_detail", pk=plan.pk)
    else:
        form = TreatmentPlanForm(instance=plan)

    return render(request, "treatment_plans/plan_form.html", {
        "form": form,
        "patient": plan.patient,
        "appointment": plan.appointment,
        "intake": plan.intake,
        "clinical_note": plan.clinical_note,
        "plan": plan,
        "page_title": "施術計画編集",
    })

@login_required
def progress_edit_view(request, pk):
    progress = get_object_or_404(
        TreatmentProgress.objects.select_related("plan", "plan__patient", "created_by"),
        pk=pk
    )
    plan = progress.plan

    if request.method == "POST":
        form = TreatmentProgressForm(request.POST, instance=progress)
        if form.is_valid():
            form.save()
            messages.success(request, "施術経過記録を更新しました。")
            return redirect(f"{reverse('treatment_plans:plan_detail', args=[plan.pk])}?tab=progress")
        messages.error(request, "入力内容を確認してください。")
    else:
        form = TreatmentProgressForm(instance=progress)

    return render(request, "treatment_plans/progress_form.html", {
        "form": form,
        "plan": plan,
        "progress": progress,
        "page_title": "施術経過記録編集",
        "submit_label": "更新する",
    })


@login_required
def progress_delete_view(request, pk):
    progress = get_object_or_404(
        TreatmentProgress.objects.select_related("plan", "plan__patient"),
        pk=pk
    )
    plan = progress.plan

    if request.method == "POST":
        progress.delete()
        messages.success(request, "施術経過記録を削除しました。")
        return redirect(f"{reverse('treatment_plans:plan_detail', kwargs={'pk': plan.pk})}?tab=progress#progress-list")

    return render(request, "treatment_plans/progress_confirm_delete.html", {
        "progress": progress,
        "plan": plan,
        "page_title": "施術経過記録削除確認",
    })

@login_required
@require_POST
def plan_status_update_view(request, pk):
    plan = get_object_or_404(TreatmentPlan, pk=pk)

    new_status = (request.POST.get("status") or "").strip()
    valid_statuses = {choice[0] for choice in TreatmentPlan.STATUS_CHOICES}

    if new_status not in valid_statuses:
        messages.error(request, "不正なステータスです。")
        next_url = request.POST.get("next") or f"{reverse('treatment_plans:plan_detail', kwargs={'pk': plan.pk})}?tab=overview"
        return redirect(next_url)

    plan.status = new_status

    # 既存の is_active とも軽く整合
    if new_status == "active":
        plan.is_active = True
    else:
        plan.is_active = False

    plan.save(update_fields=["status", "is_active", "updated_at"])

    messages.success(request, f"施術計画を「{plan.get_status_display()}」に更新しました。")
    return redirect(f"{reverse('treatment_plans:plan_detail', args=[plan.pk])}?tab=overview")

@login_required
def plan_create_from_clinical_note_view(request, clinical_note_id):
    clinical_note = get_object_or_404(
        ClinicalNote.objects.select_related("patient", "appointment", "intake"),
        pk=clinical_note_id,
    )

    patient = clinical_note.patient
    appointment = clinical_note.appointment
    intake = clinical_note.intake

    initial = build_treatment_plan_initial_from_note(clinical_note)

    if request.method == "POST":
        form = TreatmentPlanForm(request.POST)
        if form.is_valid():
            plan = form.save(commit=False)
            plan.patient = patient
            plan.appointment = appointment
            plan.intake = intake
            plan.clinical_note = clinical_note
            plan.created_by = request.user
            plan.save()

            messages.success(request, "AI下書きから施術計画を作成しました。")
            return redirect("treatment_plans:plan_detail", pk=plan.pk)
    else:
        form = TreatmentPlanForm(initial=initial)

    return render(request, "treatment_plans/plan_form.html", {
        "form": form,
        "patient": patient,
        "appointment": appointment,
        "intake": intake,
        "clinical_note": clinical_note,
        "page_title": "AI施術計画案の確認",
        "is_ai_draft": True,
    })
    
def build_treatment_plan_initial_from_note(clinical_note):
    extract = clinical_note.extract_json or {}
    soap = clinical_note.soap_json or {}

    chief = extract.get("chief_complaint") or ""
    locations = extract.get("locations") or []
    severity = extract.get("severity_0_10")
    symptom_type = extract.get("symptom_type") or ""

    soap_a = soap.get("A") or []
    soap_p = soap.get("P") or []

    if isinstance(locations, list):
        location_text = "・".join([str(x) for x in locations if x])
    else:
        location_text = str(locations)

    title_base = chief or location_text or "症状"
    title = f"{title_base}に対する施術計画"

    caution_notes = [
        "痛みのでる動作はなるべく控えてください。",
        "同じ姿勢を続けないように注意してください。",
        "睡眠は十分にとってください。",
    ]

    if symptom_type == "acute":
        visit_guide_type = "weekly"
        visit_guide_count = 2
        visit_guide_unit_note = "初期は週2回を目安に、症状の変化を確認しながら調整します。"
        expected_min = 2
        expected_max = 4
        exercise_instruction = "本日から一定期間は中止"
        work_instruction = "痛みが出たら中止"
    else:
        visit_guide_type = "weekly"
        visit_guide_count = 1
        visit_guide_unit_note = "週1回を目安に、生活動作と症状の変化を確認しながら調整します。"
        expected_min = 4
        expected_max = 8
        exercise_instruction = "痛みが出ない範囲で許可"
        work_instruction = "痛みが出たら中止"

    lifestyle_other = ""

    if soap_p:
        lifestyle_other += "AI施術方針案：\n"
        lifestyle_other += "\n".join([f"・{x}" for x in soap_p])

    if soap_a:
        lifestyle_other += "\n\n評価メモ：\n"
        lifestyle_other += "\n".join([f"・{x}" for x in soap_a])

    if severity:
        lifestyle_other += f"\n\n初回確認時の痛み目安：{severity}/10"

    return {
        "title": title,
        "chief_complaint": chief,
        "status": "active",
        "visit_guide_type": visit_guide_type,
        "visit_guide_count": visit_guide_count,
        "visit_guide_unit_note": visit_guide_unit_note,
        "bath_instruction": ["長湯はしないでください"],
        "walking_instruction": ["痛みが出たら中止"],
        "exercise_instruction": [exercise_instruction],
        "work_instruction": [work_instruction],
        "lifestyle_other_instruction": lifestyle_other.strip(),
        "caution_notes": caution_notes,
        "expected_recovery_weeks_min": expected_min,
        "expected_recovery_weeks_max": expected_max,
        "rebound_reaction_note": "施術後、一時的にだるさ・眠気・違和感などが出る場合があります。強い痛みや不安な症状がある場合は、無理をせずご相談ください。",
        "explained_to_patient": False,
        "is_active": True,
    }