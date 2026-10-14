from collections import Counter
from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from apps.ai_usage.models import AiUsageLog, ClinicAiPlan
from apps.appointments.models import Appointment
from apps.clinics.booking_links import clinic_booking_link_rows
from apps.clinics.models import Clinic, ClinicSettings, SalesRecord, TreatmentMenu
from apps.owner_admin.forms import (
    OwnerClinicCreateForm,
    OwnerClinicEditForm,
    OwnerClinicSettingsForm,
    OwnerPlanForm,
    OwnerStaffCreateForm,
)
from apps.owner_admin.plans import (
    CARE_FROW_PLAN_DEFINITIONS,
    plan_definition,
    normalize_plan_key,
)
from apps.patients.models import Patient
from apps.staff.utils import get_staff_display_name

User = get_user_model()


def owner_required(view_func):
    @wraps(view_func)
    @login_required(login_url="staff:login")
    def _wrapped(request, *args, **kwargs):
        # 将来的にCareFrow運営者グループ判定へ拡張する境界。
        if not getattr(request.user, "is_superuser", False):
            return HttpResponseForbidden("CareFrow運営者のみ利用できます。")
        return view_func(request, *args, **kwargs)

    return _wrapped


def _month_range(today=None):
    today = today or timezone.localdate()
    start = date(today.year, today.month, 1)
    if today.month == 12:
        next_month = date(today.year + 1, 1, 1)
    else:
        next_month = date(today.year, today.month + 1, 1)
    return start, next_month


def _format_yen(value):
    return f"¥{int(value or 0):,}"


def _clinic_plan_label(ai_plan):
    if ai_plan is None:
        return "未設定"
    definition = plan_definition(ai_plan.plan_name)
    if definition:
        return definition["display_name"]
    return ai_plan.plan_name or "未設定"


def _clinic_plan_context(ai_plan, used_minutes=0):
    if ai_plan is None:
        return None
    definition = plan_definition(ai_plan.plan_name)
    if definition:
        included = definition["included_minutes"]
        overage_unit = definition["overage_unit_minutes"]
        overage_price = definition["overage_unit_price"]
        monthly_fee = definition["monthly_base_fee"]
        initial_fee = definition["initial_fee"]
        label = definition["display_name"]
        description = definition["description"]
        campaign = definition["campaign"]
    else:
        included = ai_plan.included_minutes
        overage_unit = ai_plan.overage_unit_minutes
        overage_price = ai_plan.overage_unit_price
        monthly_fee = ai_plan.monthly_base_fee
        initial_fee = None
        label = ai_plan.plan_name or "未設定"
        description = ai_plan.notes or "院別設定プランです。"
        campaign = False
    remaining = max(included - used_minutes, 0)
    usage_percent = int((used_minutes / included) * 100) if included else 0
    if used_minutes <= included or overage_unit <= 0:
        overage_fee = 0
    else:
        over_minutes = used_minutes - included
        overage_fee = ((over_minutes + overage_unit - 1) // overage_unit) * overage_price
    return {
        "label": label,
        "plan_name": ai_plan.plan_name,
        "monthly_base_fee": monthly_fee,
        "monthly_base_fee_display": _format_yen(monthly_fee),
        "initial_fee": initial_fee,
        "initial_fee_display": _format_yen(initial_fee) if initial_fee is not None else "個別設定",
        "included_minutes": included,
        "used_minutes": used_minutes,
        "remaining_minutes": remaining,
        "usage_percent": usage_percent,
        "overage_unit_minutes": overage_unit,
        "overage_unit_price": overage_price,
        "overage_unit_price_display": _format_yen(overage_price),
        "overage_fee": overage_fee,
        "overage_fee_display": _format_yen(overage_fee),
        "hard_limit_minutes": ai_plan.hard_limit_minutes,
        "is_ai_enabled": ai_plan.is_ai_enabled,
        "allow_overage": ai_plan.allow_overage,
        "description": description,
        "campaign": campaign,
    }


def _monthly_ai_minutes_by_clinic(month_start, next_month):
    return {
        row["clinic_id"]: row["minutes"] or 0
        for row in (
            AiUsageLog.objects.filter(
                status=AiUsageLog.Status.SUCCESS,
                created_at__date__gte=month_start,
                created_at__date__lt=next_month,
            )
            .values("clinic_id")
            .annotate(minutes=Sum("billing_minutes"))
        )
    }


def _monthly_ai_cost_by_clinic(month_start, next_month):
    return {
        row["clinic_id"]: row["cost"] or 0
        for row in (
            AiUsageLog.objects.filter(
                status=AiUsageLog.Status.SUCCESS,
                created_at__date__gte=month_start,
                created_at__date__lt=next_month,
            )
            .values("clinic_id")
            .annotate(cost=Sum("estimated_cost_yen"))
        )
    }


def _clinic_count_map(model, clinic_field="clinic_id", **filters):
    return {
        row[clinic_field]: row["count"]
        for row in (
            model.objects.filter(**filters)
            .values(clinic_field)
            .annotate(count=Count("id"))
        )
    }


@owner_required
def owner_dashboard(request):
    today = timezone.localdate()
    month_start, next_month = _month_range(today)
    clinics = list(Clinic.objects.order_by("-created_at", "-id"))
    clinic_ids = [clinic.id for clinic in clinics]
    ai_minutes = _monthly_ai_minutes_by_clinic(month_start, next_month)
    ai_costs = _monthly_ai_cost_by_clinic(month_start, next_month)

    plan_rows = ClinicAiPlan.objects.filter(clinic_id__in=clinic_ids)
    plan_counts = Counter(_clinic_plan_label(plan) for plan in plan_rows)
    if len(plan_counts) < len(clinic_ids):
        plan_counts["未設定"] += len(clinic_ids) - sum(plan_counts.values())

    heavy_usage = sorted(
        (
            {
                "clinic": clinic,
                "minutes": ai_minutes.get(clinic.id, 0),
                "cost": ai_costs.get(clinic.id, 0),
                "cost_display": _format_yen(ai_costs.get(clinic.id, 0)),
            }
            for clinic in clinics
        ),
        key=lambda row: row["minutes"],
        reverse=True,
    )[:10]

    context = {
        "active": "dashboard",
        "month_start": month_start,
        "clinic_count": len(clinics),
        "active_clinic_count": len(clinics),
        "stopped_clinic_count": 0,
        "total_ai_minutes": sum(ai_minutes.values()),
        "total_ai_cost": sum(ai_costs.values()),
        "total_ai_cost_display": _format_yen(sum(ai_costs.values())),
        "plan_counts": [
            {"label": label, "count": count}
            for label, count in sorted(plan_counts.items())
        ],
        "recent_clinics": clinics[:8],
        "heavy_usage_clinics": heavy_usage,
    }
    return render(request, "owner_admin/dashboard.html", context)


@owner_required
def owner_clinic_list(request):
    today = timezone.localdate()
    month_start, next_month = _month_range(today)
    clinics = list(Clinic.objects.order_by("name", "id"))
    clinic_ids = [clinic.id for clinic in clinics]
    settings_map = ClinicSettings.objects.filter(clinic_id__in=clinic_ids).in_bulk(field_name="clinic_id")
    plan_map = ClinicAiPlan.objects.filter(clinic_id__in=clinic_ids).in_bulk(field_name="clinic_id")
    staff_counts = _clinic_count_map(
        User,
        clinic_field="clinic_id",
        role__in=[User.Role.ADMIN, User.Role.RECEPTION, User.Role.PRACTITIONER],
    )
    patient_counts = _clinic_count_map(Patient, clinic_field="clinic_id")
    appointment_counts = _clinic_count_map(
        Appointment,
        clinic_field="clinic_id",
        start_at__date__gte=month_start,
        start_at__date__lt=next_month,
    )
    ai_minutes = _monthly_ai_minutes_by_clinic(month_start, next_month)

    clinic_rows = []
    for clinic in clinics:
        clinic_rows.append({
            "clinic": clinic,
            "settings": settings_map.get(clinic.id),
            "plan_label": _clinic_plan_label(plan_map.get(clinic.id)),
            "status_label": "稼働中",
            "staff_count": staff_counts.get(clinic.id, 0),
            "patient_count": patient_counts.get(clinic.id, 0),
            "ai_minutes": ai_minutes.get(clinic.id, 0),
            "appointment_count": appointment_counts.get(clinic.id, 0),
        })

    return render(request, "owner_admin/clinic_list.html", {
        "active": "clinics",
        "clinic_rows": clinic_rows,
        "month_start": month_start,
    })


@owner_required
def owner_clinic_create(request):
    if request.method == "POST":
        form = OwnerClinicCreateForm(request.POST)
        if form.is_valid():
            result = form.save()
            clinic = result["clinic"]
            if result["generated_password"]:
                request.session["owner_created_staff_credentials"] = {
                    "clinic_id": clinic.id,
                    "username": result["admin_user"].username,
                    "password": result["generated_password"],
                }
            messages.success(request, "院と初期管理者を作成しました。")
            return redirect("owner_admin:clinic_detail", clinic_id=clinic.id)
    else:
        form = OwnerClinicCreateForm()
    return render(request, "owner_admin/clinic_form.html", {
        "active": "clinics",
        "form": form,
        "mode": "create",
    })


@owner_required
def owner_clinic_detail(request, clinic_id):
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    today = timezone.localdate()
    month_start, next_month = _month_range(today)
    settings = ClinicSettings.objects.filter(clinic=clinic).first()
    ai_plan = ClinicAiPlan.objects.filter(clinic=clinic).first()
    used_minutes = (
        AiUsageLog.objects.filter(
            clinic=clinic,
            status=AiUsageLog.Status.SUCCESS,
            created_at__date__gte=month_start,
            created_at__date__lt=next_month,
        ).aggregate(total=Sum("billing_minutes"))["total"] or 0
    )
    ai_cost = (
        AiUsageLog.objects.filter(
            clinic=clinic,
            status=AiUsageLog.Status.SUCCESS,
            created_at__date__gte=month_start,
            created_at__date__lt=next_month,
        ).aggregate(total=Sum("estimated_cost_yen"))["total"] or 0
    )
    credentials = request.session.pop("owner_created_staff_credentials", None)
    if credentials and credentials.get("clinic_id") != clinic.id:
        request.session["owner_created_staff_credentials"] = credentials
        credentials = None

    staff_users = list(
        User.objects.filter(clinic=clinic)
        .exclude(role=User.Role.PATIENT)
        .order_by("-is_active", "last_name", "first_name", "username")
    )
    staff_rows = [
        {
            "user": user,
            "display_name": get_staff_display_name(user),
            "role": user.get_role_display(),
        }
        for user in staff_users
    ]
    recent_ai_usage = list(
        AiUsageLog.objects.filter(clinic=clinic)
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(minutes=Sum("billing_minutes"), cost=Sum("estimated_cost_yen"))
        .order_by("-day")[:7]
    )

    return render(request, "owner_admin/clinic_detail.html", {
        "active": "clinics",
        "clinic": clinic,
        "settings": settings,
        "plan": _clinic_plan_context(ai_plan, used_minutes),
        "used_minutes": used_minutes,
        "ai_cost_display": _format_yen(ai_cost),
        "staff_rows": staff_rows,
        "patient_count": Patient.objects.filter(clinic=clinic).count(),
        "appointment_count": Appointment.objects.filter(clinic=clinic).count(),
        "sales_count": SalesRecord.objects.filter(clinic=clinic).count(),
        "menu_count": TreatmentMenu.objects.filter(clinic=clinic).count(),
        "recent_ai_usage": recent_ai_usage,
        "credentials": credentials,
        "booking_link_rows": clinic_booking_link_rows(request, clinic),
    })


@owner_required
def owner_clinic_edit(request, clinic_id):
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    if request.method == "POST":
        form = OwnerClinicEditForm(request.POST, clinic=clinic)
        if form.is_valid():
            form.save()
            messages.success(request, "院情報を保存しました。")
            return redirect("owner_admin:clinic_detail", clinic_id=clinic.id)
    else:
        form = OwnerClinicEditForm(clinic=clinic)
    return render(request, "owner_admin/clinic_form.html", {
        "active": "clinics",
        "clinic": clinic,
        "form": form,
        "mode": "edit",
    })


@owner_required
def owner_clinic_settings(request, clinic_id):
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    if request.method == "POST":
        form = OwnerClinicSettingsForm(request.POST, clinic=clinic)
        if form.is_valid():
            form.save()
            messages.success(request, "院設定を保存しました。")
            return redirect("owner_admin:clinic_detail", clinic_id=clinic.id)
    else:
        form = OwnerClinicSettingsForm(clinic=clinic)
    return render(request, "owner_admin/clinic_settings_form.html", {
        "active": "clinics",
        "clinic": clinic,
        "form": form,
    })


@owner_required
def owner_clinic_plan(request, clinic_id):
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    if request.method == "POST":
        form = OwnerPlanForm(request.POST, clinic=clinic)
        if form.is_valid():
            form.save()
            messages.success(request, "契約プランを保存しました。")
            return redirect("owner_admin:clinic_detail", clinic_id=clinic.id)
    else:
        form = OwnerPlanForm(clinic=clinic)
    return render(request, "owner_admin/clinic_plan_form.html", {
        "active": "clinics",
        "clinic": clinic,
        "form": form,
        "plan_definitions": CARE_FROW_PLAN_DEFINITIONS,
    })


@owner_required
def owner_clinic_staff_create(request, clinic_id):
    clinic = get_object_or_404(Clinic, pk=clinic_id)
    if request.method == "POST":
        form = OwnerStaffCreateForm(request.POST, clinic=clinic)
        if form.is_valid():
            form.save()
            messages.success(request, "院スタッフを追加しました。")
            return redirect("owner_admin:clinic_detail", clinic_id=clinic.id)
    else:
        form = OwnerStaffCreateForm(clinic=clinic)
    return render(request, "owner_admin/staff_form.html", {
        "active": "clinics",
        "clinic": clinic,
        "form": form,
    })
