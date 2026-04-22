# apps/patients/views.py
import calendar
import logging
import re
import uuid
from calendar import monthrange
from datetime import date, datetime, time, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group
from django.db import IntegrityError, transaction
from django.http import HttpResponseBase
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.appointments.models import Appointment
from apps.clinics.models import Clinic
from apps.clinics.utils import get_current_clinic
from apps.intakes.forms import (
    AREA_CHOICES,
    FOLLOWUP_CHANGE_CHOICES,
    FOLLOWUP_CHANGE_DETAIL_CHOICES,
    PAIN_QUALITIES,
    SINCE_CHOICES,
    SYMPTOM_TYPE_CHOICES,
    VISIT_TYPE_CHOICES,
)
from .forms import PatientProfileForm, PatientRegisterForm
from .models import Patient

from django.http import JsonResponse
from django.views.decorators.http import require_POST

from django.conf import settings
from django.core.mail import send_mail
from .forms import PatientInquiryForm

User = get_user_model()
logger = logging.getLogger(__name__)

# ========= 設定（A案：スタッフ共通営業時間・30分刻み） =========
OPEN_TIME = time(9, 0)#9に戻す
CLOSE_TIME = time(23, 30) #19,00に戻す
SLOT_MIN = 30 #30に戻す
DURATION_MIN = 60 #60に戻す

BLOCKING_STATUSES = [
    Appointment.Status.PENDING,
    Appointment.Status.BOOKED,
    Appointment.Status.ARRIVED,
]

SYMPTOM_TYPE_LABELS = dict(SYMPTOM_TYPE_CHOICES)
SINCE_LABELS = dict(SINCE_CHOICES)
AREA_LABELS = dict(AREA_CHOICES)
PAIN_QUALITY_LABELS = dict(PAIN_QUALITIES)
VISIT_TYPE_LABELS = dict(VISIT_TYPE_CHOICES)
FOLLOWUP_CHANGE_LABELS = dict(FOLLOWUP_CHANGE_CHOICES)
FOLLOWUP_CHANGE_DETAIL_LABELS = dict(FOLLOWUP_CHANGE_DETAIL_CHOICES)


def _labels_from_codes(values, label_map):
    if not values:
        return []
    return [label_map.get(v, v) for v in values]

def _clear_booking_draft_session(request):
    request.session.pop("booking_draft", None)


def _get_booking_draft_session(request):
    return request.session.get("booking_draft") or {}

def _build_intake_display(intake):
    if not intake:
        return None

    payload = intake.payload or {}
    symptoms = payload.get("symptoms", {}) or {}
    step2 = payload.get("step2", {}) or {}
    followup = payload.get("followup", {}) or {}

    visit_type = payload.get("visit_type")
    is_followup = visit_type == "followup"

    if is_followup:
        return {
            "submitted_at": intake.submitted_at,
            "visit_type": VISIT_TYPE_LABELS.get(visit_type, visit_type or "-"),
            "condition_change": FOLLOWUP_CHANGE_LABELS.get(
                followup.get("condition_change"),
                followup.get("condition_change", "-")
            ),
            "pain_level": followup.get("pain_level"),
            "changes": _labels_from_codes(
                followup.get("changes", []),
                FOLLOWUP_CHANGE_DETAIL_LABELS,
            ),
            "comment": followup.get("comment", ""),
            "chief_complaint": intake.chief_complaint or "",
            "is_followup": True,
        }

    return {
        "submitted_at": intake.submitted_at,
        "visit_type": VISIT_TYPE_LABELS.get(visit_type, visit_type or "-"),
        "symptom_type": SYMPTOM_TYPE_LABELS.get(intake.symptom_type, intake.symptom_type or "-"),
        "chief_complaint": intake.chief_complaint or "",
        "onset": SINCE_LABELS.get(intake.onset, intake.onset or "-"),
        "severity": symptoms.get("severity"),
        "trigger": step2.get("trigger", ""),
        "areas": _labels_from_codes(symptoms.get("areas", []), AREA_LABELS),
        "qualities": _labels_from_codes(symptoms.get("qualities", []), PAIN_QUALITY_LABELS),
        "free_text": symptoms.get("free_text", ""),
        "is_followup": False,
    }

def require_patient_or_redirect(request):
    patient = _patient_from_user(request)
    if patient:
        return patient

    # staff/adminでログインしてるなら「患者アカウントでログインしてね」
    if request.user.is_authenticated and (request.user.is_staff or request.user.is_superuser):
        messages.info(request, "患者予約フローを利用するには、患者アカウントでログインしてください。")
        return redirect("patients:login")

    # 一般ユーザーでpatient未作成なら新規登録へ
    messages.error(request, "患者情報が未登録です。新規登録を完了してください。")
    return redirect("patients:register")

# ========= Utility =========
def _normalize_phone(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")

def _patient_from_user(request):
    return Patient.objects.filter(user=request.user).select_related("clinic").first()


def _get_staff_candidates():
    """
    予約担当候補のユーザーのみ返す。
    patient や一般ユーザーは表示しない。
    """
    therapist_qs = (
        User.objects
        .filter(groups__name="therapist")
        .exclude(groups__name="patient")
        .distinct()
        .order_by("id")
    )
    if therapist_qs.exists():
        return therapist_qs

    staff_qs = (
        User.objects
        .filter(is_staff=True)
        .exclude(groups__name="patient")
        .distinct()
        .order_by("id")
    )
    if staff_qs.exists():
        return staff_qs

    return User.objects.none()

def _aware(dt: datetime):
    return timezone.make_aware(dt, timezone.get_current_timezone())

def _make_day_slots(day: date):
    """指定日の候補枠 (start,end) を生成"""
    start = _aware(datetime.combine(day, OPEN_TIME))
    end = _aware(datetime.combine(day, CLOSE_TIME))
    step = timedelta(minutes=SLOT_MIN)
    dur = timedelta(minutes=DURATION_MIN)

    slots = []
    cur = start
    while cur + dur <= end:
        slots.append((cur, cur + dur))
        cur += step
    return slots

def _slot_free_for_staff(clinic, staff, start_at, end_at) -> bool:
    """同院・同スタッフで重複がなければ空き"""
    return not Appointment.objects.filter(
        clinic=clinic,
        assigned_staff=staff,
        status__in=BLOCKING_STATUSES,
        start_at__lt=end_at,
        end_at__gt=start_at,
    ).exists()

def _count_free_slots_for_staff(clinic, staff, day: date) -> int:
    n = 0
    for s, e in _make_day_slots(day):
        if _slot_free_for_staff(clinic, staff, s, e):
            n += 1
    return n

@require_http_methods(["GET", "POST"])
def patient_login_view(request):
    if request.user.is_authenticated:
        if request.user.is_staff or request.user.is_superuser:
            messages.info(
                request,
                "現在スタッフでログイン中です。患者アカウントで利用する場合は一度ログアウトしてください。"
            )
            return redirect("/")
        return redirect("patients:dashboard")

    if request.method == "POST":
        login_id = (request.POST.get("login_id") or "").strip()
        password = request.POST.get("password") or ""

        user = None

        # 1) メールアドレスで探す
        if "@" in login_id:
            user = (
                User.objects
                .filter(
                    email__iexact=login_id,
                    is_active=True,
                    groups__name="patient",
                )
                .distinct()
                .first()
            )
        else:
            # 2) 診察券番号で探す
            patient = (
                Patient.objects
                .filter(card_no=login_id)
                .select_related("user")
                .first()
            )
            if patient and patient.user and patient.user.is_active:
                user = patient.user

        if user is None:
            messages.error(request, "メールアドレスまたは診察券番号、もしくはパスワードが正しくありません。")
            return render(request, "patients/login.html")

        # 実際の認証は内部 username で行う
        auth_user = authenticate(request, username=user.username, password=password)

        if auth_user is None:
            messages.error(request, "メールアドレスまたは診察券番号、もしくはパスワードが正しくありません。")
            return render(request, "patients/login.html")

        # 念のため patient グループ確認
        if not auth_user.groups.filter(name="patient").exists():
            messages.error(request, "患者用アカウントではありません。")
            return render(request, "patients/login.html")

        login(request, auth_user)

        next_url = request.POST.get("next") or request.GET.get("next")
        if next_url:
            return redirect(next_url)

        return redirect("patients:dashboard")

    return render(request, "patients/login.html")

@login_required(login_url="/patients/login/")
def patient_dashboard_view(request):
    patient_or_resp = require_patient_or_redirect(request)
    if isinstance(patient_or_resp, HttpResponseBase):
        return patient_or_resp
    patient = patient_or_resp

    now = timezone.now()

    next_appointment = (
        Appointment.objects
        .filter(
            patient=patient,
            start_at__gte=now,
            status__in=[
                Appointment.Status.PENDING,
                Appointment.Status.BOOKED,
                Appointment.Status.ARRIVED,
            ],
        )
        .select_related("assigned_staff", "clinic", "intake")
        .order_by("start_at")
        .first()
    )

    recent_appointments = (
        Appointment.objects
        .filter(patient=patient, start_at__lt=now)
        .select_related("assigned_staff", "clinic", "intake")
        .order_by("-start_at")[:3]
    )

    if next_appointment:
        _decorate_appointment_flags(next_appointment)

    recent_appointments = [_decorate_appointment_flags(a) for a in recent_appointments]

    context = {
        "patient": patient,
        "next_appointment": next_appointment,
        "recent_appointments": recent_appointments,
    }
    return render(request, "patients/dashboard.html", context)

@login_required(login_url="/patients/login/")
def patient_profile_view(request):
    patient_or_resp = require_patient_or_redirect(request)
    if isinstance(patient_or_resp, HttpResponseBase):
        return patient_or_resp
    patient = patient_or_resp

    if request.method == "POST":
        form = PatientProfileForm(request.POST, instance=patient)
        if form.is_valid():
            form.save()
            messages.success(request, "登録情報を更新しました。")
            return redirect("patients:dashboard")
    else:
        form = PatientProfileForm(instance=patient)

    return render(request, "patients/profile.html", {
        "patient": patient,
        "form": form,
    })

def patient_logout_view(request):
    logout(request)
    return redirect("/")

def patient_register_view(request):
    pending_clinic_id = request.session.get("pending_booking_clinic_id")

    try:
        if pending_clinic_id:
            clinic = get_object_or_404(Clinic, pk=pending_clinic_id)
        else:
            clinic = get_current_clinic()
    except Exception:
        logger.exception("Clinic resolution failed in patient_register_view")
        messages.error(request, "クリニック情報が未設定です。管理者にお問い合わせください。")
        return redirect("/")

    initial = {
        "last_name": request.session.get("pending_booking_last_name", ""),
        "first_name": request.session.get("pending_booking_first_name", ""),
        "phone": request.session.get("pending_booking_phone", ""),
    }

    form = PatientRegisterForm(request.POST or None, initial=initial)

    if request.method == "POST":
        if not form.is_valid():
            messages.error(request, "入力内容を確認してください。")
            return render(request, "patients/register.html", {"form": form})

        password = form.cleaned_data["password"]
        email = form.cleaned_data["email"]
        username = generate_patient_username()

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    role=User.Role.PATIENT,
                    clinic=clinic,
                )
                user.is_staff = False
                user.is_superuser = False
                user.is_active = True
                user.save()

                patient_group, _ = Group.objects.get_or_create(name="patient")
                user.groups.add(patient_group)

                patient = None
                for _ in range(10):
                    try:
                        patient = Patient.objects.create(
                            user=user,
                            clinic=clinic,
                            card_no=generate_card_no(),
                            last_name=form.cleaned_data["last_name"],
                            first_name=form.cleaned_data["first_name"],
                            last_name_kana=form.cleaned_data["last_name_kana"],
                            first_name_kana=form.cleaned_data["first_name_kana"],
                            birth_date=form.cleaned_data["birth_date"],
                            phone=form.cleaned_data["phone"],
                            address=form.cleaned_data["address"],
                        )
                        break
                    except IntegrityError:
                        continue

                if patient is None:
                    raise IntegrityError("Failed to generate unique card_no")

        except IntegrityError:
            logger.warning(
                "Patient registration failed due to IntegrityError. email=%s clinic_id=%s",
                email,
                clinic.id,
            )
            messages.error(request, "登録に失敗しました。時間をおいてもう一度お試しください。")
            return render(request, "patients/register.html", {"form": form})

        except Exception:
            logger.exception(
                "Unexpected error in patient_register_view. email=%s clinic_id=%s",
                email,
                clinic.id,
            )
            messages.error(request, "登録処理でエラーが発生しました。時間をおいてもう一度お試しください。")
            return render(request, "patients/register.html", {"form": form})

        if pending_clinic_id:
            request.session["booking_patient_id"] = patient.id
            request.session["booking_clinic_id"] = clinic.id

            request.session.pop("pending_booking_last_name", None)
            request.session.pop("pending_booking_first_name", None)
            request.session.pop("pending_booking_phone", None)
            request.session.pop("pending_booking_clinic_id", None)

            messages.success(request, "患者登録が完了しました。続けて予約日時を選択してください。")
            return redirect("appointments:book_new")

        request.session["registered_card_no"] = patient.card_no
        messages.success(request, "患者登録が完了しました。")
        return redirect("patients:register_complete")

    return render(request, "patients/register.html", {"form": form})
def generate_card_no():
    """
    P000001 のような形式で採番する
    ・card_no が None の既存患者がいても落ちない
    ・一番大きい番号 + 1 を返す
    """
    # card_no があるものだけから最大を探す
    last = Patient.objects.exclude(card_no__isnull=True).exclude(card_no="").order_by("-card_no").first()

    if not last or not last.card_no:
        return "P000001"

    # 例: P000123 -> 000123 を取り出す（形式崩れにも耐える）
    m = re.search(r"(\d+)$", last.card_no)
    if not m:
        # 形式がおかしいデータが混じっても落とさない
        return "P000001"

    num = int(m.group(1)) + 1
    return f"P{num:06d}"

def generate_patient_username() -> str:
    """
    患者用の内部 username を自動生成する。
    患者には見せない前提。
    """
    for _ in range(20):
        username = f"p_{uuid.uuid4().hex[:12]}"
        if not User.objects.filter(username=username).exists():
            return username
    raise RuntimeError("一意な username を生成できませんでした。")

# ========= Booking =========

# 追加import（すでに monthrange はあるけど、monthcalendarを使う）
@login_required(login_url="/patients/login/")
def booking_calendar_view(request):
    patient_or_resp = require_patient_or_redirect(request)
    if isinstance(patient_or_resp, HttpResponseBase):
        return patient_or_resp
    patient = patient_or_resp

    clinic = patient.clinic

    # --- 施術計画からの導線 ---
    suggest_date = request.GET.get("suggest_date")
    treatment_plan_id = request.GET.get("treatment_plan_id")

    # --- 再予約導線 ---
    rebook_from = request.GET.get("rebook_from")
    if rebook_from:
        base_appt = get_object_or_404(Appointment, pk=rebook_from, patient=patient)

        request.session["rebook_menu"] = base_appt.menu
        request.session["rebook_staff_id"] = base_appt.assigned_staff_id
        request.session["rebook_from_id"] = base_appt.id

        messages.success(request, "前回と同じ内容で予約できます。ご希望の日付を選択してください。")

    today = timezone.localdate()

    ym = request.GET.get("ym")
    if ym:
        try:
            y, m = map(int, ym.split("-"))
            first_day = date(y, m, 1)
        except Exception:
            first_day = date(today.year, today.month, 1)
    else:
        if suggest_date:
            try:
                suggested = datetime.strptime(suggest_date, "%Y-%m-%d").date()
                first_day = date(suggested.year, suggested.month, 1)
            except Exception:
                first_day = date(today.year, today.month, 1)
        else:
            first_day = date(today.year, today.month, 1)

    prev_month = (first_day.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (first_day.replace(day=28) + timedelta(days=10)).replace(day=1)

    staffs = list(_get_staff_candidates())

    # 日曜始まりを明示
    cal = calendar.Calendar(firstweekday=calendar.SUNDAY)
    month_weeks = cal.monthdayscalendar(first_day.year, first_day.month)

    day_stats = {}
    for week in month_weeks:
        for d in week:
            if d == 0:
                continue

            day = date(first_day.year, first_day.month, d)

            if day < today:
                day_stats[day.isoformat()] = {"free": 0, "disabled": True}
                continue

            free_total = 0
            for st in staffs:
                free_total += _count_free_slots_for_staff(clinic, st, day)

            day_stats[day.isoformat()] = {
                "free": free_total,
                "disabled": free_total == 0,
            }

    cal_weeks = []
    for week in month_weeks:
        row = []
        for d in week:
            if d == 0:
                row.append({"day": 0, "ds": "", "stat": None})
            else:
                ds = date(first_day.year, first_day.month, d).isoformat()
                row.append({
                    "day": d,
                    "ds": ds,
                    "stat": day_stats.get(ds),
                })
        cal_weeks.append(row)

    return render(request, "patients/booking_calendar.html", {
        "clinic": clinic,
        "patient": patient,
        "first_day": first_day,
        "prev_ym": prev_month.strftime("%Y-%m"),
        "next_ym": next_month.strftime("%Y-%m"),
        "cal_weeks": cal_weeks,
        "today": today,
        "suggest_date": suggest_date,
        "treatment_plan_id": treatment_plan_id,
    })

@login_required(login_url="/patients/login/")
def booking_day_view(request, ymd: str):
    patient_or_resp = require_patient_or_redirect(request)
    if isinstance(patient_or_resp, HttpResponseBase):
        return patient_or_resp
    patient = patient_or_resp
    clinic = patient.clinic

    treatment_plan_id = request.GET.get("treatment_plan_id")

    try:
        day = datetime.strptime(ymd, "%Y-%m-%d").date()
    except ValueError:
        return redirect("patients:booking_calendar")

    if day < timezone.localdate():
        messages.error(request, "過去の日付は選択できません。")
        return redirect("patients:booking_calendar")

    staffs = list(_get_staff_candidates())

    rebook_staff_id = request.session.get("rebook_staff_id")
    if rebook_staff_id:
        staffs = sorted(
            staffs,
            key=lambda s: 0 if s.id == rebook_staff_id else 1
        )

    staff_slots = []
    for st in staffs:
        slots = []
        for s, e in _make_day_slots(day):
            if _slot_free_for_staff(clinic, st, s, e):
                slots.append({"start": s, "end": e})
        staff_slots.append({"staff": st, "slots": slots})

    return render(request, "patients/booking_day.html", {
        "clinic": clinic,
        "patient": patient,
        "day": day,
        "staff_slots": staff_slots,
        "treatment_plan_id": treatment_plan_id,
    })

@login_required(login_url="/patients/login/")
@require_http_methods(["POST"])
def booking_review_view(request):
    patient_or_resp = require_patient_or_redirect(request)
    if isinstance(patient_or_resp, HttpResponseBase):
        return patient_or_resp
    patient = patient_or_resp
    clinic = patient.clinic

    staff_id = request.POST.get("staff_id")
    start_iso = request.POST.get("start_at")
    menu = request.POST.get("menu") or request.session.get("rebook_menu") or "初診"
    treatment_plan_id = request.POST.get("treatment_plan_id")

    if not staff_id or not start_iso:
        messages.error(request, "予約枠の情報が不足しています。")
        return redirect("patients:booking_calendar")

    staff = get_object_or_404(User, pk=staff_id)

    try:
        start_naive = datetime.strptime(start_iso, "%Y-%m-%dT%H:%M")
        start_at = timezone.make_aware(start_naive, timezone.get_current_timezone())
    except Exception:
        messages.error(request, "日時の形式が不正です。")
        return redirect("patients:booking_calendar")

    end_at = start_at + timedelta(minutes=DURATION_MIN)

    if start_at < timezone.now():
        messages.error(request, "過去の日時は選択できません。")
        return redirect("patients:booking_calendar")

    if not _slot_free_for_staff(clinic, staff, start_at, end_at):
        messages.error(request, "選択した枠は埋まりました。別の枠を選択してください。")
        return redirect(
            f"{reverse('patients:booking_calendar')}?suggest_date={start_at.date().isoformat()}"
        )

    treatment_plan = None
    if treatment_plan_id:
        from apps.treatment_plans.models import TreatmentPlan
        treatment_plan = TreatmentPlan.objects.filter(
            pk=treatment_plan_id,
            patient=patient
        ).first()

    request.session["booking_draft"] = {
        "staff_id": staff.id,
        "staff_name": staff.get_full_name() or staff.username,
        "start_at": start_at.isoformat(),
        "end_at": end_at.isoformat(),
        "menu": menu,
        "clinic_name": clinic.name,
        "treatment_plan_id": treatment_plan.id if treatment_plan else None,
    }

    return render(request, "patients/booking_review.html", {
        "clinic": clinic,
        "patient": patient,
        "staff": staff,
        "start_at": start_at,
        "end_at": end_at,
        "menu": menu,
        "treatment_plan_id": treatment_plan.id if treatment_plan else None,
    })

@login_required(login_url="/patients/login/")
@require_http_methods(["POST"])
def booking_confirm_view(request):
    patient_or_resp = require_patient_or_redirect(request)
    if isinstance(patient_or_resp, HttpResponseBase):
        return patient_or_resp
    patient = patient_or_resp

    clinic = patient.clinic
    draft = _get_booking_draft_session(request)

    if not draft:
        messages.error(request, "予約確認情報が見つかりません。もう一度やり直してください。")
        return redirect("patients:booking_calendar")

    staff_id = draft.get("staff_id")
    start_iso = draft.get("start_at")
    menu = draft.get("menu") or request.session.get("rebook_menu") or "初診"
    treatment_plan_id = draft.get("treatment_plan_id")

    if not staff_id or not start_iso:
        _clear_booking_draft_session(request)
        messages.error(request, "予約情報が不足しています。もう一度やり直してください。")
        return redirect("patients:booking_calendar")

    staff = get_object_or_404(User, pk=staff_id)

    try:
        start_at = datetime.fromisoformat(start_iso)
        if timezone.is_naive(start_at):
            start_at = timezone.make_aware(start_at, timezone.get_current_timezone())
    except Exception:
        _clear_booking_draft_session(request)
        messages.error(request, "日時の形式が不正です。")
        return redirect("patients:booking_calendar")

    end_at = start_at + timedelta(minutes=DURATION_MIN)

    if start_at < timezone.now():
        _clear_booking_draft_session(request)
        messages.error(request, "過去の日時は選択できません。")
        return redirect("patients:booking_calendar")

    if not _slot_free_for_staff(clinic, staff, start_at, end_at):
        _clear_booking_draft_session(request)
        messages.error(request, "選択した枠は埋まりました。別の枠を選択してください。")
        return redirect(
            f"{reverse('patients:booking_calendar')}?suggest_date={start_at.date().isoformat()}"
        )

    treatment_plan = None
    if treatment_plan_id:
        from apps.treatment_plans.models import TreatmentPlan
        treatment_plan = TreatmentPlan.objects.filter(
            pk=treatment_plan_id,
            patient=patient
        ).first()

    appt = Appointment.objects.create(
        clinic=clinic,
        patient=patient,
        assigned_staff=staff,
        start_at=start_at,
        end_at=end_at,
        menu=menu,
        status=Appointment.Status.PENDING,
        created_by=request.user,
        treatment_plan=treatment_plan,
    )

    _clear_booking_draft_session(request)
    request.session.pop("rebook_menu", None)
    request.session.pop("rebook_staff_id", None)
    request.session.pop("rebook_from_id", None)

    messages.success(request, "予約枠を受け付けました。続けてWeb問診をご入力ください。")
    return redirect("intakes:intake_start", appointment_id=appt.id)

@login_required(login_url="/patients/login/")
def booking_complete_view(request, appointment_id: int):
    appt = get_object_or_404(Appointment, pk=appointment_id)
    if appt.created_by_id != request.user.id:
        messages.error(request, "この予約は表示できません。")
        return redirect("patients:booking_calendar")

    return render(request, "patients/booking_complete.html", {"appointment": appt})

@login_required(login_url="/patients/login/")
def patient_my_appointments_view(request):

    patient_or_resp = require_patient_or_redirect(request)
    if isinstance(patient_or_resp, HttpResponseBase):
        return patient_or_resp

    patient = patient_or_resp
    now = timezone.now()

    appointments = list(
        Appointment.objects
        .filter(patient=patient)
        .select_related("clinic", "assigned_staff", "intake")
        .order_by("start_at")
    )

    appointments = [_decorate_appointment_flags(a) for a in appointments]

    future = [a for a in appointments if a.start_at >= now]
    past = [a for a in appointments if a.start_at < now]

    next_appointment = future[0] if future else None
    upcoming = future[1:] if len(future) > 1 else []

    past_preview = past[-3:]
    past_more = past[:-3]

    history_count = len(past_preview) + len(past_more)

    return render(
        request,
        "patients/my_appointments.html",
        {
            "next_appointment": next_appointment,
            "upcoming": upcoming,
            "past_preview": past_preview,
            "past_more": past_more,
            "history_count": history_count,
        }
    )

@require_http_methods(["GET"])
def patient_register_complete_view(request):
    card_no = request.session.get("registered_card_no")
    if not card_no:
        # 直リンク対策：registerへ戻す or loginへ
        messages.info(request, "登録情報が見つかりません。もう一度登録してください。")
        return redirect("patients:register")

    # 使い終わったら消す（リロードで残るの防止）
    request.session.pop("registered_card_no", None)

    return render(request, "patients/register_complete.html", {"card_no": card_no})

def _decorate_appointment_flags(appt):
    intake = getattr(appt, "intake", None)
    appt.intake_completed = bool(intake and intake.submitted_at)
    appt.show_resume_intake = (
        appt.status == Appointment.Status.PENDING and not appt.intake_completed
    )
    appt.intake_display = _build_intake_display(intake) if appt.intake_completed else None
    return appt

@login_required(login_url="/patients/login/")
@require_http_methods(["POST"])
def appointment_cancel_view(request, appointment_id):
    patient_or_resp = require_patient_or_redirect(request)
    if isinstance(patient_or_resp, HttpResponseBase):
        return patient_or_resp
    patient = patient_or_resp

    appt = get_object_or_404(Appointment, pk=appointment_id, patient=patient)

    if appt.start_at <= timezone.now():
        messages.error(request, "過去または当日の予約はキャンセルできません。")
        return redirect("patients:my_appointments")

    if appt.status not in [Appointment.Status.PENDING, Appointment.Status.BOOKED]:
        messages.error(request, "この予約はキャンセルできません。")
        return redirect("patients:my_appointments")

    appt.status = Appointment.Status.CANCELLED
    appt.save(update_fields=["status"])

    messages.success(request, "予約をキャンセルしました。")
    return redirect("patients:my_appointments")

@login_required
def staff_booking_calendar_view(request, patient_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "スタッフのみ利用できます。")
        return redirect("patients:login")

    patient = get_object_or_404(Patient.objects.select_related("clinic"), pk=patient_id)
    clinic = patient.clinic

    suggest_date = request.GET.get("suggest_date")
    treatment_plan_id = request.GET.get("treatment_plan_id")

    today = timezone.localdate()

    ym = request.GET.get("ym")
    if ym:
        try:
            y, m = map(int, ym.split("-"))
            first_day = date(y, m, 1)
        except Exception:
            first_day = date(today.year, today.month, 1)
    else:
        if suggest_date:
            try:
                suggested = datetime.strptime(suggest_date, "%Y-%m-%d").date()
                first_day = date(suggested.year, suggested.month, 1)
            except Exception:
                first_day = date(today.year, today.month, 1)
        else:
            first_day = date(today.year, today.month, 1)

    prev_month = (first_day.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month = (first_day.replace(day=28) + timedelta(days=10)).replace(day=1)

    staffs = list(_get_staff_candidates())
    weeks = calendar.monthcalendar(first_day.year, first_day.month)

    day_stats = {}
    for week in weeks:
        for d in week:
            if d == 0:
                continue
            day = date(first_day.year, first_day.month, d)

            if day < today:
                day_stats[day.isoformat()] = {"free": 0, "disabled": True}
                continue

            free_total = 0
            for st in staffs:
                free_total += _count_free_slots_for_staff(clinic, st, day)

            day_stats[day.isoformat()] = {
                "free": free_total,
                "disabled": free_total == 0
            }

    cal_weeks = []
    for week in weeks:
        row = []
        for d in week:
            if d == 0:
                row.append({"day": 0, "ds": "", "stat": None})
            else:
                ds = date(first_day.year, first_day.month, d).isoformat()
                row.append({"day": d, "ds": ds, "stat": day_stats.get(ds)})
        cal_weeks.append(row)

    return render(request, "patients/staff_booking_calendar.html", {
        "clinic": clinic,
        "patient": patient,
        "first_day": first_day,
        "prev_ym": prev_month.strftime("%Y-%m"),
        "next_ym": next_month.strftime("%Y-%m"),
        "cal_weeks": cal_weeks,
        "today": today,
        "suggest_date": suggest_date,
        "treatment_plan_id": treatment_plan_id,
    })
    
@login_required
def staff_booking_day_view(request, patient_id, ymd):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "スタッフのみ利用できます。")
        return redirect("patients:login")

    patient = get_object_or_404(Patient.objects.select_related("clinic"), pk=patient_id)
    clinic = patient.clinic
    treatment_plan_id = request.GET.get("treatment_plan_id")

    try:
        day = datetime.strptime(ymd, "%Y-%m-%d").date()
    except ValueError:
        return redirect("patients:staff_booking_calendar", patient_id=patient.pk)

    if day < timezone.localdate():
        messages.error(request, "過去の日付は選択できません。")
        return redirect("patients:staff_booking_calendar", patient_id=patient.pk)

    staffs = list(_get_staff_candidates())

    staff_slots = []
    for st in staffs:
        slots = []
        for s, e in _make_day_slots(day):
            if _slot_free_for_staff(clinic, st, s, e):
                slots.append({"start": s, "end": e})
        staff_slots.append({"staff": st, "slots": slots})

    return render(request, "patients/staff_booking_day.html", {
        "clinic": clinic,
        "patient": patient,
        "day": day,
        "staff_slots": staff_slots,
        "treatment_plan_id": treatment_plan_id,
    })
    
@login_required
@require_http_methods(["POST"])
def staff_booking_confirm_view(request, patient_id):
    if not (request.user.is_staff or request.user.is_superuser):
        messages.error(request, "スタッフのみ利用できます。")
        return redirect("patients:login")

    patient = get_object_or_404(Patient.objects.select_related("clinic"), pk=patient_id)
    clinic = patient.clinic

    logger.info("staff_booking_confirm POST=%s", request.POST.dict())

    staff_id = request.POST.get("staff_id")
    start_iso = request.POST.get("start_at")
    menu = request.POST.get("menu") or "再診"
    treatment_plan_id = request.POST.get("treatment_plan_id")

    logger.info(
        "staff_booking_confirm params staff_id=%r start_iso=%r treatment_plan_id=%r patient_id=%s clinic_id=%s user_id=%s",
        staff_id,
        start_iso,
        treatment_plan_id,
        patient.pk,
        clinic.pk if clinic else None,
        request.user.pk,
    )

    if not staff_id or not start_iso:
        messages.error(
            request,
            f"予約枠の情報が不足しています。staff_id={staff_id!r}, start_at={start_iso!r}"
        )
        logger.warning(
            "staff_booking_confirm missing params staff_id=%r start_at=%r patient_id=%s",
            staff_id,
            start_iso,
            patient.pk,
        )
        return redirect("patients:staff_booking_calendar", patient_id=patient.pk)

    staff = get_object_or_404(User, pk=staff_id)

    try:
        start_naive = datetime.strptime(start_iso, "%Y-%m-%dT%H:%M")
        start_at = timezone.make_aware(start_naive, timezone.get_current_timezone())
        logger.info("staff_booking_confirm parsed start_at=%s", start_at.isoformat())
    except Exception:
        logger.exception(
            "staff_booking_confirm datetime parse error start_iso=%r patient_id=%s",
            start_iso,
            patient.pk,
        )
        messages.error(request, "日時の形式が不正です。")
        return redirect("patients:staff_booking_calendar", patient_id=patient.pk)

    end_at = start_at + timedelta(minutes=DURATION_MIN)

    now = timezone.now()
    logger.info("staff_booking_confirm now=%s", now.isoformat())

    if start_at < now:
        logger.warning(
            "staff_booking_confirm rejected past datetime start_at=%s now=%s patient_id=%s",
            start_at.isoformat(),
            now.isoformat(),
            patient.pk,
        )
        messages.error(request, "過去の日時は選択できません。")
        return redirect("patients:staff_booking_calendar", patient_id=patient.pk)

    is_free = _slot_free_for_staff(clinic, staff, start_at, end_at)
    logger.info(
        "staff_booking_confirm slot availability is_free=%s clinic_id=%s staff_id=%s start_at=%s end_at=%s",
        is_free,
        clinic.pk if clinic else None,
        staff.pk,
        start_at.isoformat(),
        end_at.isoformat(),
    )

    if not is_free:
        messages.error(request, "選択した枠は埋まっています。別の枠を選択してください。")
        return redirect(
            "patients:staff_booking_day",
            patient_id=patient.pk,
            ymd=start_at.date().isoformat(),
        )

    treatment_plan = None
    if treatment_plan_id:
        from apps.treatment_plans.models import TreatmentPlan
        treatment_plan = TreatmentPlan.objects.filter(
            pk=treatment_plan_id,
            patient=patient,
        ).first()
        logger.info(
            "staff_booking_confirm treatment_plan resolved treatment_plan_id=%r found=%s",
            treatment_plan_id,
            treatment_plan.pk if treatment_plan else None,
        )

    appt = Appointment.objects.create(
        clinic=clinic,
        patient=patient,
        assigned_staff=staff,
        start_at=start_at,
        end_at=end_at,
        menu=menu,
        status=Appointment.Status.PENDING,
        created_by=request.user,
        treatment_plan=treatment_plan,
    )

    logger.info(
        "staff_booking_confirm appointment created appointment_id=%s patient_id=%s clinic_id=%s staff_id=%s",
        appt.pk,
        patient.pk,
        clinic.pk if clinic else None,
        staff.pk,
    )

    messages.success(request, "予約を作成しました。")
    return redirect("staff:appointment_detail", appointment_id=appt.pk)

# 予約延長
@login_required(login_url="/patients/login/")
@require_POST
def patient_session_ping_view(request):
    patient_or_resp = require_patient_or_redirect(request)
    if isinstance(patient_or_resp, HttpResponseBase):
        return JsonResponse({"ok": False, "message": "unauthorized"}, status=401)

    request.session.modified = True
    return JsonResponse({"ok": True})

def patient_inquiry_view(request):
    initial = {}

    if request.user.is_authenticated and hasattr(request.user, "patient_profile"):
        patient = request.user.patient_profile
        initial["name"] = f"{patient.last_name} {patient.first_name}"
        if request.user.email:
            initial["email"] = request.user.email

    form = PatientInquiryForm(request.POST or None, initial=initial)

    if request.method == "POST":
        if form.is_valid():
            name = form.cleaned_data["name"]
            email = form.cleaned_data["email"]
            subject = form.cleaned_data["subject"]
            message = form.cleaned_data["message"]

            body = (
                f"患者様からお問い合わせが届きました。\n\n"
                f"お名前: {name}\n"
                f"メールアドレス: {email}\n"
                f"件名: {subject}\n\n"
                f"お問い合わせ内容:\n{message}\n"
            )

            send_mail(
                subject=f"【お問い合わせ】{subject}",
                message=body,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=["support@carefrow.com"],
                fail_silently=False,
            )

            messages.success(request, "お問い合わせを送信しました。")
            return redirect("patients:inquiry_done")

    return render(request, "patients/inquiry_form.html", {"form": form})

def patient_inquiry_done_view(request):
    return render(request, "patients/inquiry_done.html")