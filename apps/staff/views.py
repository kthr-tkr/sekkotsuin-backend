# apps/staff/views.py
import json
from calendar import monthrange
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Q, Case, When, Value, IntegerField
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_POST

from apps.ai_jobs.usecases import run_ai_draft
from apps.appointments.models import Appointment
from apps.charts.models import ChartNote
from apps.clinical_notes.models import ClinicalNote, ClinicalNoteHistory
from apps.clinics.models import Clinic
from apps.intakes.forms import AREA_CHOICES, VISIT_TYPE_CHOICES, SYMPTOM_TYPE_CHOICES
from apps.intakes.models import Intake, InterviewRecording
from apps.patients.models import Patient
from apps.staff.decorators import staff_required
from apps.staff.forms import ClinicalNoteEditForm
from apps.treatment_plans.models import TreatmentPlan
from apps.visits.models import Visit

from .forms import StaffCreateForm


INTAKE_FIELD_LABELS = {
    "visit_type": "来院種別",
    "symptom_type": "症状タイプ",
    "chief_complaint": "主訴",
    "onset": "いつから",
    "since": "いつから",
    "trigger": "きっかけ",
    "areas": "痛みの部位",
    "pain_level": "痛みの強さ",
    "severity": "痛みの強さ",
    "pain_qualities": "症状の感じ",
    "qualities": "症状の感じ",
    "other_quality_text": "その他の症状詳細",
    "other_area_text": "その他の部位",
    "free_text": "自由記入",
    "followup_type": "再診区分",
    "followup_change": "前回との変化",
    "followup_change_detail": "変化の詳細",
    "followup_comment": "気になる変化・コメント",
    "agreement": "同意",
    "agreed": "同意",
    "consent_agreed": "同意",
    "confirm_profile": "登録情報確認",
    "source": "来院経路",
    "job": "職業",
    "note": "備考",
    "other_clinic": "他院通院",
    "other_clinic_note": "他院通院メモ",
    "taking_meds": "服薬中",
    "meds_note": "服薬メモ",
    "past_history": "既往歴",
    "history_note": "既往歴メモ",
    "final_note": "最後に伝えたいこと",
    "meta": "進行情報",
    "step1": "ステップ1",
    "step2": "ステップ2",
    "step3": "ステップ3",
    "step4": "ステップ4",
    "symptoms": "症状情報",
    "history": "既往歴など",
    "consent": "同意",
    "branch_selected": "分岐選択済み",
    "intake_mode": "問診モード",
    "current_step": "現在ステップ",
    "completed_steps": "完了ステップ",
}

INTAKE_VALUE_LABELS = {
    "new_issue": "新しい症状",
    "followup": "再診",
    "unknown": "わからない",
    "normal": "通常問診",
    "acute": "急性",
    "chronic": "慢性",
    "2_3days": "2〜3日前",
    "today": "今日",
    "yesterday": "昨日",
    "within_week": "1週間以内",
    "over_week": "1週間以上前",
    "over_month": "1か月以上前",
    "shoulder_r": "右肩",
    "shoulder_l": "左肩",
    "waist": "腰",
    "neck": "首",
    "back": "背中",
    "knee_r": "右ひざ",
    "knee_l": "左ひざ",
    "hip_r": "右股関節",
    "hip_l": "左股関節",
    "elbow_r": "右ひじ",
    "elbow_l": "左ひじ",
    "wrist_r": "右手首",
    "wrist_l": "左手首",
    "ankle_r": "右足首",
    "ankle_l": "左足首",
    "sharp": "鋭い痛み",
    "dull": "鈍い痛み",
    "numb": "しびれ",
    "tight": "張る感じ",
    "heavy": "重だるい",
    "swollen": "腫れぼったい",
    "hot": "熱っぽい",
    "web": "Web予約",
    "walkin": "直接来院",
    "yes": "あり",
    "no": "なし",
    "true": "はい",
    "false": "いいえ",
}

User = get_user_model()


def get_current_clinic(request):
    if hasattr(request.user, "clinic") and request.user.clinic_id:
        return request.user.clinic
    return Clinic.objects.order_by("id").first()


def _is_staff_user(user, clinic=None):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    valid_roles = {
        getattr(User.Role, "ADMIN", "admin"),
        getattr(User.Role, "RECEPTION", "reception"),
        getattr(User.Role, "PRACTITIONER", "practitioner"),
    }

    if getattr(user, "role", None) not in valid_roles:
        return False

    if clinic is not None and hasattr(user, "clinic_id"):
        if user.clinic_id != clinic.id:
            return False

    return True


def _format_answer_value(value):
    if value in [None, "", []]:
        return "-"
    if isinstance(value, list):
        return "、".join(str(v) for v in value if str(v).strip()) or "-"
    if isinstance(value, bool):
        return "はい" if value else "いいえ"
    return str(value)


def _jp_label(key):
    return INTAKE_FIELD_LABELS.get(str(key), str(key))


def _jp_value(value):
    if value in [None, "", []]:
        return "-"

    if isinstance(value, bool):
        return "はい" if value else "いいえ"

    if isinstance(value, list):
        return "、".join(_jp_value(v) for v in value) or "-"

    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            lines.append(f"{_jp_label(k)}：{_jp_value(v)}")
        return "\n".join(lines) if lines else "-"

    s = str(value)
    return INTAKE_VALUE_LABELS.get(s, s)


def staff_login_view(request):
    if request.user.is_authenticated:
        return redirect("staff:dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is None:
            messages.error(request, "IDまたはパスワードが正しくありません。")
            return render(request, "staff/login.html")

        clinic = getattr(user, "clinic", None)
        if not _is_staff_user(user, clinic):
            messages.error(request, "スタッフ用アカウントではありません。")
            return render(request, "staff/login.html")

        login(request, user)
        return redirect("staff:dashboard")

    return render(request, "staff/login.html")


@require_POST
def staff_logout_view(request):
    logout(request)
    return redirect("/")


@staff_required
def staff_dashboard_view(request):
    clinic = get_current_clinic(request)
    today = timezone.localdate()

    todays_appts = (
        Appointment.objects
        .select_related("patient", "assigned_staff")
        .filter(clinic=clinic, start_at__date=today)
        .order_by("start_at")
    )

    waiting_qs = todays_appts.filter(status__in=[Appointment.Status.BOOKED, Appointment.Status.ARRIVED])
    waiting_count = waiting_qs.count()
    done_count = todays_appts.filter(status=Appointment.Status.COMPLETED).count()
    intake_count = Intake.objects.filter(clinic=clinic, submitted_at__date=today).count()
    not_intake_count = todays_appts.filter(intake__isnull=True).count()

    ai_count = intake_count
    note_count = intake_count
    next_appt = waiting_qs.first()
    appt_cards = todays_appts[:5]

    return render(request, "staff/dashboard.html", {
        "active": "home",
        "page_title": "Dashboard",
        "today": today,
        "waiting_count": waiting_count,
        "done_count": done_count,
        "ai_count": ai_count,
        "intake_count": intake_count,
        "note_count": note_count,
        "not_intake_count": not_intake_count,
        "next_appt": next_appt,
        "appointments": appt_cards,
    })


@staff_required
def staff_intake_view(request):
    return render(request, "staff/intake.html", {
        "active": "intake",
        "page_title": "問診",
    })


@staff_required
def staff_appointments_view(request):
    clinic = get_current_clinic(request)
    today = timezone.localdate()

    day_str = request.GET.get("day") or today.isoformat()
    period = (request.GET.get("period") or "day").strip()
    if period not in ["day", "week", "month", "year"]:
        period = "day"

    staff_id = request.GET.get("staff", "")
    status = request.GET.get("status", "")
    q = (request.GET.get("q", "") or "").strip()

    base_day = parse_date(day_str) or today
    range_start, range_end, range_label = _get_period_range(base_day, period)

    qs = (
        Appointment.objects
        .select_related("patient", "assigned_staff", "intake")
        .filter(
            clinic=clinic,
            start_at__date__gte=range_start,
            start_at__date__lte=range_end,
        )
        .order_by("start_at")
    )

    if staff_id:
        qs = qs.filter(assigned_staff_id=staff_id)

    if status:
        qs = qs.filter(status=status)

    if q:
        qs = qs.filter(
            Q(patient__last_name__icontains=q) |
            Q(patient__first_name__icontains=q) |
            Q(patient__phone__icontains=q) |
            Q(menu__icontains=q) |
            Q(notes__icontains=q)
        )

    appointments = list(qs)

    for a in appointments:
        intake = getattr(a, "intake", None)
        summary = _build_staff_intake_summary(intake)

        a.has_intake = summary["has_intake"]
        a.intake_completed = summary["intake_completed"]
        a.visit_type_label = summary["visit_type_label"]
        a.chief_label = summary["chief_label"]
        a.areas_display = summary["areas_display"]
        a.pain_level_display = summary["pain_level_display"]
        a.intake_kind_label = summary["intake_kind_label"]

        parts = []
        if a.chief_label:
            parts.append(a.chief_label)
        if a.areas_display:
            parts.append("、".join(a.areas_display))
        if a.pain_level_display:
            parts.append(a.pain_level_display)
        if a.visit_type_label:
            parts.append(a.visit_type_label)
        a.intake_one_line = " / ".join(parts) if parts else "-"

    base = (
        Appointment.objects
        .select_related("intake")
        .filter(
            clinic=clinic,
            start_at__date__gte=range_start,
            start_at__date__lte=range_end,
        )
    )
    base_list = list(base)

    stats = {
        "total": len(base_list),
        "not_done": sum(1 for x in base_list if not getattr(getattr(x, "intake", None), "submitted_at", None)),
        "done": sum(1 for x in base_list if getattr(getattr(x, "intake", None), "submitted_at", None)),
        "arrived": sum(1 for x in base_list if x.status == Appointment.Status.ARRIVED),
    }

    staff_users = User.objects.filter(
        clinic=clinic,
        is_active=True,
        role__in=[
            User.Role.ADMIN,
            User.Role.RECEPTION,
            User.Role.PRACTITIONER,
        ],
    ).order_by("username")

    context = {
        "active": "appointments",
        "page_title": "予約管理",
        "day": base_day,
        "period": period,
        "range_start": range_start,
        "range_end": range_end,
        "range_label": range_label,
        "appointments": appointments,
        "stats": stats,
        "staff_users": staff_users,
        "filter_staff": staff_id,
        "filter_status": status,
        "filter_q": q,
        "status_choices": Appointment.Status.choices,
    }

    if period == "day":
        return render(request, "staff/appointments.html", context)

    context["calendar_events"] = _build_calendar_events(appointments)
    context["calendar_day_summary"] = _build_calendar_day_summary(appointments)
    return render(request, "staff/appointments_calendar.html", context)


@staff_required
def staff_list(request):
    clinic = get_current_clinic(request)

    users = User.objects.filter(
        clinic=clinic,
        is_active=True,
        role__in=[
            User.Role.ADMIN,
            User.Role.RECEPTION,
            User.Role.PRACTITIONER,
        ],
    ).order_by("last_name", "first_name", "username")

    staff_cards = []
    for user in users:
        full_name = user.get_full_name().strip() or user.username
        staff_cards.append({
            "id": user.id,
            "full_name": full_name,
            "username": user.username,
            "email": user.email,
            "is_superuser": user.is_superuser,
            "is_staff": user.is_staff,
            "role": user.get_role_display() if hasattr(user, "get_role_display") else user.role,
            "today_appointments": 0,
            "active_plans": 0,
            "status_label": "稼働中" if user.is_active else "停止中",
            "status_class": "running" if user.is_active else "stopped",
        })

    return render(request, "staff/staff_list.html", {
        "active": "staffs",
        "page_title": "担当者一覧",
        "staff_cards": staff_cards,
    })


def superuser_required(user):
    return user.is_authenticated and user.is_superuser


@login_required
@user_passes_test(superuser_required)
def staff_create(request):
    clinic = get_current_clinic(request)

    if request.method == "POST":
        form = StaffCreateForm(request.POST, clinic=clinic)
        if form.is_valid():
            form.save()
            messages.success(request, "スタッフを登録しました。")
            return redirect("staff:staff_list")
    else:
        form = StaffCreateForm(clinic=clinic)

    return render(request, "staff/staff_create.html", {
        "active": "staffs",
        "page_title": "スタッフ追加",
        "form": form,
    })


@staff_required
def staff_patient_search_view(request):
    clinic = get_current_clinic(request)
    q = (request.GET.get("q") or "").strip()

    qs = Patient.objects.filter(clinic=clinic).order_by("last_name", "first_name")
    if q:
        qs = qs.filter(
            Q(last_name__icontains=q) |
            Q(first_name__icontains=q) |
            Q(phone__icontains=q)
        )

    patients = qs[:50]

    return render(request, "staff/patients/search.html", {
        "active": "patient_search",
        "page_title": "患者検索",
        "q": q,
        "patients": patients,
    })


@staff_required
def staff_manual_view(request):
    return render(request, "staff/manual.html", {
        "active": "manual",
        "page_title": "操作マニュアル",
    })


@staff_required
def staff_settings_view(request):
    return render(request, "staff/placeholder.html", {
        "active": "settings",
        "page_title": "設定",
    })


def _choice_dict(choices):
    return dict(choices)


def _labels_from_codes(values, choices):
    if not values:
        return []

    cmap = dict(choices)

    if isinstance(values, list):
        return [cmap.get(v, v) for v in values if v]

    if isinstance(values, str):
        values = [v.strip() for v in values.split(",") if v.strip()]
        return [cmap.get(v, v) for v in values]

    return []


def _build_staff_intake_summary(intake):
    data = {
        "has_intake": False,
        "intake_completed": False,
        "visit_type_label": "",
        "chief_label": "",
        "areas_display": [],
        "pain_level_display": "",
        "intake_kind_label": "",
    }

    if not intake:
        return data

    data["has_intake"] = True
    data["intake_completed"] = bool(getattr(intake, "submitted_at", None))

    followup_type = getattr(intake, "followup_type", "") or ""
    visit_type = getattr(intake, "visit_type", "") or ""

    if followup_type:
        data["intake_kind_label"] = "再診簡易問診"
        followup_map = {
            "followup": "再診",
            "new_issue": "新しい症状",
            "unknown": "不明",
        }
        data["visit_type_label"] = followup_map.get(followup_type, followup_type)

        chief = getattr(intake, "chief_complaint", "") or ""
        data["chief_label"] = chief or "再診問診"
    else:
        data["intake_kind_label"] = "通常問診"

        if visit_type:
            data["visit_type_label"] = _choice_dict(VISIT_TYPE_CHOICES).get(visit_type, visit_type)

        chief_complaint = getattr(intake, "chief_complaint", "") or ""
        symptom_type = getattr(intake, "symptom_type", "") or ""

        if chief_complaint:
            data["chief_label"] = chief_complaint
        elif symptom_type:
            data["chief_label"] = _choice_dict(SYMPTOM_TYPE_CHOICES).get(symptom_type, symptom_type)

        areas = getattr(intake, "areas", None)
        data["areas_display"] = _labels_from_codes(areas, AREA_CHOICES)

    pain_level = getattr(intake, "pain_level", None)
    if pain_level not in [None, ""]:
        data["pain_level_display"] = f"{pain_level}/10"

    return data


def _get_period_range(base_day, period):
    if period == "week":
        start = base_day - timedelta(days=base_day.weekday())
        end = start + timedelta(days=6)
        label = f"{start.strftime('%Y/%m/%d')} 〜 {end.strftime('%Y/%m/%d')}"
        return start, end, label

    if period == "month":
        start = base_day.replace(day=1)
        last_day = monthrange(base_day.year, base_day.month)[1]
        end = base_day.replace(day=last_day)
        label = f"{base_day.year}年{base_day.month}月"
        return start, end, label

    if period == "year":
        start = date(base_day.year, 1, 1)
        end = date(base_day.year, 12, 31)
        label = f"{base_day.year}年"
        return start, end, label

    label = base_day.strftime("%Y/%m/%d")
    return base_day, base_day, label


def _build_calendar_events(appointments):
    events = []

    for a in appointments:
        intake = getattr(a, "intake", None)
        summary = _build_staff_intake_summary(intake)

        patient_name = "（患者未確定）"
        if a.patient:
            patient_name = f"{a.patient.last_name} {a.patient.first_name}"

        chief = summary["chief_label"] or "主訴未入力"
        intake_state = "問診未着手"
        if summary["has_intake"]:
            intake_state = "問診完了" if summary["intake_completed"] else "問診入力中"

        visit_type = summary["visit_type_label"] or "-"
        pain = summary["pain_level_display"] or "-"
        areas = "、".join(summary["areas_display"]) if summary["areas_display"] else "-"

        if a.status == Appointment.Status.CANCELLED:
            bg = "#fee2e2"
            border = "#ef4444"
            text = "#991b1b"
        elif a.status == Appointment.Status.ARRIVED:
            bg = "#cffafe"
            border = "#06b6d4"
            text = "#164e63"
        elif summary["has_intake"] and summary["intake_completed"]:
            bg = "#dbeafe"
            border = "#3b82f6"
            text = "#1e3a8a"
        elif summary["has_intake"] and not summary["intake_completed"]:
            bg = "#ffedd5"
            border = "#f97316"
            text = "#9a3412"
        else:
            bg = "#f8fafc"
            border = "#cbd5e1"
            text = "#0f172a"

        events.append({
            "id": str(a.id),
            "title": patient_name,
            "start": a.start_at.isoformat(),
            "end": a.end_at.isoformat() if getattr(a, "end_at", None) else None,
            "backgroundColor": bg,
            "borderColor": border,
            "textColor": text,
            "extendedProps": {
                "appointmentId": a.id,
                "patientName": patient_name,
                "menu": a.menu or "-",
                "staffName": a.assigned_staff.username if a.assigned_staff else "未割当",
                "statusLabel": a.get_status_display(),
                "intakeState": intake_state,
                "intakeCompleted": summary["intake_completed"],
                "intakeKindLabel": summary["intake_kind_label"] or "-",
                "visitTypeLabel": visit_type,
                "chiefLabel": chief,
                "painLevelDisplay": pain,
                "areasDisplay": areas,
                "status": a.status,
                "intakeDetailUrl": reverse("staff:intake_detail", args=[a.intake.id]) if intake else "",
                "recordingUrl": reverse("intakes:recording_new", args=[a.id]),
                "dayUrl": f"{reverse('staff:appointments')}?period=day&day={a.start_at.date().isoformat()}",
            }
        })

    return events


def _is_filled(value):
    return value not in [None, "", [], {}]


def _deep_find_value(data, target_key):
    if isinstance(data, dict):
        if target_key in data and _is_filled(data.get(target_key)):
            return data.get(target_key)

        for _, v in data.items():
            found = _deep_find_value(v, target_key)
            if _is_filled(found):
                return found

    elif isinstance(data, list):
        for item in data:
            found = _deep_find_value(item, target_key)
            if _is_filled(found):
                return found

    return None


def _payload_get(payload, *keys):
    for key in keys:
        found = _deep_find_value(payload, key)
        if _is_filled(found):
            return found
    return None


def _build_calendar_day_summary(appointments):
    summary = {}

    for a in appointments:
        day_key = a.start_at.date().isoformat()
        intake = getattr(a, "intake", None)
        intake_summary = _build_staff_intake_summary(intake)

        if day_key not in summary:
            summary[day_key] = {
                "total": 0,
                "not_done": 0,
                "first_visit": 0,
            }

        summary[day_key]["total"] += 1

        if not intake_summary["intake_completed"]:
            summary[day_key]["not_done"] += 1

        visit_type_label = intake_summary.get("visit_type_label", "") or ""
        menu_text = (a.menu or "").strip()

        if visit_type_label == "初診" or "初診" in menu_text:
            summary[day_key]["first_visit"] += 1

    return summary


@staff_required
@require_POST
def staff_appointment_status_update_view(request, pk):
    clinic = get_current_clinic(request)
    appt = get_object_or_404(Appointment, pk=pk, clinic=clinic)

    new_status = (request.POST.get("status") or "").strip()
    valid = {c[0] for c in Appointment.Status.choices}

    if new_status not in valid:
        messages.error(request, "不正なステータスです。")
        return redirect(request.POST.get("next") or "staff:appointments")

    appt.status = new_status
    appt.save(update_fields=["status", "updated_at"])

    messages.success(request, f"ステータスを「{appt.get_status_display()}」に更新しました。")
    return redirect(request.POST.get("next") or "staff:appointments")


@staff_required
@require_POST
def move_appointment_view(request, pk):
    clinic = get_current_clinic(request)

    if not _is_staff_user(request.user, clinic):
        return JsonResponse({"ok": False, "error": "権限がありません。"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "不正なリクエストです。"}, status=400)

    start_raw = data.get("start")
    end_raw = data.get("end")

    start_dt = parse_datetime(start_raw) if start_raw else None
    end_dt = parse_datetime(end_raw) if end_raw else None

    if not start_dt:
        return JsonResponse({"ok": False, "error": "開始日時が不正です。"}, status=400)

    appt = get_object_or_404(Appointment, pk=pk, clinic=clinic)

    if not end_dt:
        if getattr(appt, "end_at", None):
            duration = appt.end_at - appt.start_at
            end_dt = start_dt + duration
        else:
            end_dt = start_dt

    overlap_qs = Appointment.objects.filter(
        clinic=clinic,
        assigned_staff=appt.assigned_staff,
        start_at__lt=end_dt,
        end_at__gt=start_dt,
    ).exclude(pk=appt.pk).exclude(status=Appointment.Status.CANCELLED)

    if overlap_qs.exists():
        return JsonResponse({
            "ok": False,
            "error": "同じ施術者の予約と時間が重複しています。"
        }, status=400)

    appt.start_at = start_dt
    appt.end_at = end_dt
    appt.save(update_fields=["start_at", "end_at", "updated_at"])

    return JsonResponse({
        "ok": True,
        "start": appt.start_at.isoformat(),
        "end": appt.end_at.isoformat() if appt.end_at else None,
    })


@staff_required
def staff_intake_list_view(request):
    clinic = get_current_clinic(request)
    today = timezone.localdate()
    q = (request.GET.get("q", "") or "").strip()

    appts = (
        Appointment.objects
        .select_related("patient", "assigned_staff")
        .filter(clinic=clinic, start_at__date=today)
        .order_by("start_at")
    )

    if q:
        appts = appts.filter(
            Q(patient__last_name__icontains=q) |
            Q(patient__first_name__icontains=q) |
            Q(patient__phone__icontains=q) |
            Q(menu__icontains=q)
        )

    done = appts.filter(intake__isnull=False).count()
    not_done = appts.filter(intake__isnull=True).count()

    return render(request, "staff/intake_list.html", {
        "active": "intake",
        "page_title": "問診",
        "today": today,
        "appointments": appts,
        "stats": {"done": done, "not_done": not_done, "total": appts.count()},
        "filter_q": q,
    })


@staff_required
def staff_intake_detail_view(request, pk):
    clinic = get_current_clinic(request)
    intake = get_object_or_404(
        Intake.objects.select_related("patient", "appointment"),
        pk=pk,
        clinic=clinic
    )

    payload = intake.payload or {}

    summary_rows = [
        {
            "label": "来院種別",
            "value": _jp_value(
                _payload_get(payload, "visit_type", "followup_type")
                or getattr(intake, "visit_type", None)
            ),
        },
        {
            "label": "主訴",
            "value": _jp_value(
                _payload_get(payload, "chief_complaint")
                or getattr(intake, "chief_complaint", None)
            ),
        },
        {
            "label": "症状タイプ",
            "value": _jp_value(
                _payload_get(payload, "symptom_type")
                or getattr(intake, "symptom_type", None)
            ),
        },
        {
            "label": "いつから",
            "value": _jp_value(
                _payload_get(payload, "since", "onset")
                or getattr(intake, "onset", None)
            ),
        },
        {
            "label": "きっかけ",
            "value": _jp_value(_payload_get(payload, "trigger")),
        },
        {
            "label": "痛みの部位",
            "value": _jp_value(
                _payload_get(payload, "areas")
                or getattr(intake, "areas", None)
            ),
        },
        {
            "label": "痛みの強さ",
            "value": _jp_value(
                _payload_get(payload, "severity", "pain_level")
                or getattr(intake, "pain_level", None)
            ),
        },
        {
            "label": "症状の感じ",
            "value": _jp_value(_payload_get(payload, "qualities", "pain_qualities")),
        },
    ]

    note_rows = [
        {"label": "自由記入", "value": _jp_value(_payload_get(payload, "free_text"))},
        {"label": "その他の部位", "value": _jp_value(_payload_get(payload, "other_area_text"))},
        {"label": "その他の症状詳細", "value": _jp_value(_payload_get(payload, "other_quality_text"))},
    ]

    medical_rows = [
        {"label": "他院通院", "value": _jp_value(_payload_get(payload, "other_clinic"))},
        {"label": "他院通院メモ", "value": _jp_value(_payload_get(payload, "other_clinic_note"))},
        {"label": "服薬中", "value": _jp_value(_payload_get(payload, "taking_meds"))},
        {"label": "服薬メモ", "value": _jp_value(_payload_get(payload, "meds_note"))},
        {"label": "既往歴", "value": _jp_value(_payload_get(payload, "past_history"))},
        {"label": "既往歴メモ", "value": _jp_value(_payload_get(payload, "history_note"))},
        {"label": "最後に伝えたいこと", "value": _jp_value(_payload_get(payload, "final_note"))},
    ]

    summary_rows = [row for row in summary_rows if row["value"] != "-"]
    note_rows = [row for row in note_rows if row["value"] != "-"]
    medical_rows = [row for row in medical_rows if row["value"] != "-"]

    return render(request, "staff/intake_detail.html", {
        "active": "intake",
        "page_title": "問診詳細",
        "intake": intake,
        "summary_rows": summary_rows,
        "note_rows": note_rows,
        "medical_rows": medical_rows,
    })


@staff_required
def staff_interview_view(request, appointment_id: int):
    clinic = get_current_clinic(request)

    appt = get_object_or_404(
        Appointment.objects.select_related("patient", "assigned_staff"),
        pk=appointment_id,
        clinic=clinic
    )

    if appt.patient_id is None:
        messages.error(request, "この予約は患者が未確定です。先に患者を紐づけてください。")
        return redirect("staff:appointments")

    intake = getattr(appt, "intake", None)
    if intake is None:
        messages.warning(request, "この予約は問診が未提出です。先に問診の確認/入力をお願いします。")
        return redirect("staff:intake")

    visit = (
        Visit.objects
        .filter(clinic=clinic, appointment=appt)
        .order_by("-visited_at")
        .first()
    )

    if visit is None:
        visit = Visit.objects.create(
            clinic=clinic,
            patient=appt.patient,
            appointment=appt,
            intake=intake,
            visited_at=timezone.now(),
            practitioner=appt.assigned_staff,
            status=Visit.Status.IN_PROGRESS,
        )
    else:
        changed = False
        if visit.patient_id != appt.patient_id:
            visit.patient = appt.patient
            changed = True
        if visit.intake_id is None:
            visit.intake = intake
            changed = True
        if visit.practitioner_id is None and appt.assigned_staff_id:
            visit.practitioner = appt.assigned_staff
            changed = True
        if changed:
            visit.save()

    note = ChartNote.objects.filter(visit=visit).order_by("-version").first()

    if request.method == "POST":
        exam_text = (request.POST.get("exam_text") or "").strip()
        if not exam_text:
            messages.error(request, "診察メモを入力してください。")
            return redirect("staff:interview", appointment_id=appt.id)

        job = run_ai_draft(visit=visit, input_text=exam_text)

        if job.status == job.Status.SUCCESS:
            messages.success(request, "SOAP（AI下書き）を作成しました。")
        else:
            messages.error(request, f"AI処理に失敗しました：{job.error_message}")

        return redirect("staff:interview", appointment_id=appt.id)

    note = ChartNote.objects.filter(visit=visit).order_by("-version").first()

    return render(request, "staff/interview.html", {
        "active": "appointments",
        "page_title": "診察（AI Interview）",
        "appointment": appt,
        "visit": visit,
        "intake": intake,
        "note": note,
    })


@staff_required
@require_POST
@transaction.atomic
def register_clinical_note(request, recording_id):
    clinic = get_current_clinic(request)

    if not _is_staff_user(request.user, clinic):
        return HttpResponseForbidden("staff only")

    recording = get_object_or_404(
        InterviewRecording.objects.select_related("appointment", "patient", "intake"),
        pk=recording_id,
        clinic=clinic,
    )

    appointment = recording.appointment
    patient = recording.patient
    intake = recording.intake

    summary = recording.get_active_summary() or {}

    def parse_json_field(name, default):
        raw = request.POST.get(name, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    # 元データ
    base_soap = summary.get("soap", {}) or {}
    base_extract = summary.get("extract", {}) or {}
    base_followups = summary.get("followups", []) or {}

    # POST優先
    posted_summary = parse_json_field("summary_json", None)
    posted_soap = parse_json_field("soap_json", None)
    posted_extract = parse_json_field("extract_json", None)
    posted_followups = parse_json_field("followups_json", None)
    posted_locations = parse_json_field("selected_locations_json", None)

    if posted_summary and isinstance(posted_summary, dict):
        soap = posted_summary.get("soap", {}) or {}
        extract = posted_summary.get("extract", {}) or {}
        followups = posted_summary.get("followups", []) or []
    else:
        soap = posted_soap if isinstance(posted_soap, dict) else base_soap
        extract = posted_extract if isinstance(posted_extract, dict) else base_extract
        followups = posted_followups if isinstance(posted_followups, list) else base_followups

    # 部位は selected_locations_json を最優先にして上書き
    if isinstance(posted_locations, list):
        extract["locations"] = posted_locations

    web_snapshot = {}
    if intake:
        web_snapshot = {
            "payload": intake.payload or {},
            "chief_complaint": intake.chief_complaint,
            "symptom_type": intake.symptom_type,
            "onset": intake.onset,
            "submitted_at": intake.submitted_at.isoformat() if intake.submitted_at else None,
        }

    note, created = ClinicalNote.objects.update_or_create(
        appointment=appointment,
        defaults={
            "patient": patient,
            "intake": intake,
            "recording": recording,
            "soap_json": soap,
            "extract_json": extract,
            "followups_json": followups,
            "web_intake_snapshot": web_snapshot,
            "registered_by": request.user,
            "updated_by": request.user,
        },
    )

    messages.success(request, "内容登録（確定保存）が完了しました。")
    return redirect("staff:patient_detail", patient_id=patient.id)


@staff_required
def staff_patient_detail_view(request, patient_id):
    clinic = get_current_clinic(request)
    patient = get_object_or_404(Patient, pk=patient_id, clinic=clinic)

    notes = (
        ClinicalNote.objects
        .filter(patient=patient)
        .select_related("appointment", "recording", "intake")
        .order_by("-created_at")
    )

    treatment_plans = (
        TreatmentPlan.objects
        .filter(patient=patient)
        .select_related("appointment", "intake", "clinical_note", "created_by")
        .prefetch_related("progress_logs")
        .annotate(
            status_order=Case(
                When(status="active", then=Value(0)),
                When(status="paused", then=Value(1)),
                When(status="completed", then=Value(2)),
                default=Value(9),
                output_field=IntegerField(),
            )
        )
        .order_by("status_order", "-created_at")
    )

    latest_note = notes.first()
    latest_extract = latest_note.extract_json if latest_note else {}
    latest_soap = latest_note.soap_json if latest_note else {}

    latest_assessment = ""
    if latest_soap and isinstance(latest_soap.get("A"), list) and latest_soap.get("A"):
        latest_assessment = latest_soap.get("A")[0]

    return render(request, "staff/patients/detail.html", {
        "active": "patient_search",
        "page_title": "患者詳細",
        "patient": patient,
        "notes": notes,
        "treatment_plans": treatment_plans,
        "latest_note": latest_note,
        "latest_extract": latest_extract,
        "latest_assessment": latest_assessment,
    })


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str):
        return [s.strip() for s in v.split("\n") if s.strip()]
    return [str(v)]


@staff_required
def staff_clinical_note_detail_view(request, pk):
    clinic = get_current_clinic(request)
    note = get_object_or_404(
        ClinicalNote.objects.select_related(
            "patient", "appointment", "intake", "recording", "registered_by", "updated_by"
        ),
        pk=pk,
        patient__clinic=clinic,
    )

    soap = note.soap_json or {}
    soap_view = {
        "S": _as_list(soap.get("S")),
        "O": _as_list(soap.get("O")),
        "A": _as_list(soap.get("A")),
        "P": _as_list(soap.get("P")),
    }

    extract = note.extract_json or {}
    followups = note.followups_json or []
    histories = note.histories.select_related("edited_by").all()

    return render(request, "staff/clinical_notes/detail.html", {
        "active": "patient_search",
        "page_title": "カルテ詳細",
        "note": note,
        "soap_view": soap_view,
        "extract": extract,
        "followups": followups,
        "histories": histories,
    })


@staff_required
def staff_clinical_note_edit(request, note_id):
    clinic = get_current_clinic(request)
    note = get_object_or_404(ClinicalNote, id=note_id, patient__clinic=clinic)

    if request.method == "POST":
        form = ClinicalNoteEditForm(request.POST)
        if form.is_valid():
            payload = form.build_payload()

            ClinicalNoteHistory.objects.create(
                note=note,
                soap_json=note.soap_json or {},
                extract_json=note.extract_json or {},
                followups_json=note.followups_json or [],
                web_intake_snapshot=note.web_intake_snapshot or {},
                edited_by=request.user,
            )

            note.soap_json = payload["soap"]
            note.extract_json = payload["extract"]
            note.followups_json = payload["followups"]
            note.updated_by = request.user

            note.save(update_fields=[
                "soap_json",
                "extract_json",
                "followups_json",
                "updated_by",
                "updated_at",
            ])

            messages.success(request, "カルテを更新しました。")
            return redirect("staff:clinical_note_detail", pk=note.id)
    else:
        form = ClinicalNoteEditForm.from_note(note)

    return render(request, "staff/clinical_notes/edit.html", {
        "note": note,
        "form": form,
    })