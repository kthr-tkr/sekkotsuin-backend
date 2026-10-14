from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from django.db.models import Sum
from django.utils import timezone

from .models import AiUsageLog, ClinicAiPlan


@dataclass
class AiUsageSummary:
    clinic_id: int
    year: int
    month: int
    used_minutes: int
    included_minutes: int
    remaining_minutes: int
    usage_percent: int
    monthly_base_fee: int
    overage_fee: int
    estimated_cost_yen: int
    warning_level: str
    warning_message: str
    is_ai_enabled: bool
    can_use_ai: bool


def get_month_range(target_date: date | None = None):
    if target_date is None:
        target_date = timezone.localdate()

    start = date(target_date.year, target_date.month, 1)

    if target_date.month == 12:
        next_month = date(target_date.year + 1, 1, 1)
    else:
        next_month = date(target_date.year, target_date.month + 1, 1)

    return start, next_month


def get_or_create_clinic_ai_plan(clinic) -> ClinicAiPlan:
    plan, _ = ClinicAiPlan.objects.get_or_create(
        clinic=clinic,
        defaults={
            "plan_name": "スタンダード",
            "monthly_base_fee": 50000,
            "included_minutes": 1000,
            "overage_unit_minutes": 100,
            "overage_unit_price": 2000,
            "warning_threshold_percent": 80,
            "danger_threshold_percent": 90,
            "hard_limit_minutes": 1500,
            "is_ai_enabled": True,
            "allow_overage": True,
        },
    )
    return plan


def get_monthly_ai_usage_minutes(clinic, target_date: date | None = None) -> int:
    start, next_month = get_month_range(target_date)

    result = (
        AiUsageLog.objects.filter(
            clinic=clinic,
            status=AiUsageLog.Status.SUCCESS,
            created_at__date__gte=start,
            created_at__date__lt=next_month,
        )
        .aggregate(total=Sum("billing_minutes"))
    )

    return result["total"] or 0


def get_monthly_ai_estimated_cost_yen(clinic, target_date: date | None = None) -> int:
    start, next_month = get_month_range(target_date)

    result = (
        AiUsageLog.objects.filter(
            clinic=clinic,
            status=AiUsageLog.Status.SUCCESS,
            created_at__date__gte=start,
            created_at__date__lt=next_month,
        )
        .aggregate(total=Sum("estimated_cost_yen"))
    )

    return result["total"] or 0


def get_ai_usage_warning(plan: ClinicAiPlan, used_minutes: int) -> tuple[str, str]:
    if not plan.is_ai_enabled:
        return "disabled", "AI機能は現在無効になっています。管理者に確認してください。"

    if used_minutes >= plan.hard_limit_minutes:
        return (
            "hard_limit",
            "今月のAI録音上限に達しました。管理者による上限変更が必要です。",
        )

    if used_minutes > plan.included_minutes:
        return (
            "overage",
            f"無料枠を超過しました。以降は{plan.overage_unit_minutes}分ごとに{plan.overage_unit_price:,}円が加算されます。",
        )

    usage_percent = plan.usage_percent(used_minutes)

    if usage_percent >= plan.danger_threshold_percent:
        remaining = max(plan.included_minutes - used_minutes, 0)
        return (
            "danger",
            f"AI録音利用が上限に近づいています。今月の残り利用可能時間は {remaining}分です。",
        )

    if usage_percent >= plan.warning_threshold_percent:
        remaining = max(plan.included_minutes - used_minutes, 0)
        return (
            "warning",
            f"AI録音利用が上限の{plan.warning_threshold_percent}%に達しました。今月の残り利用可能時間は {remaining}分です。",
        )

    return "none", ""


def can_use_ai_for_clinic(plan: ClinicAiPlan, used_minutes: int) -> bool:
    if not plan.is_ai_enabled:
        return False

    if used_minutes >= plan.hard_limit_minutes:
        return False

    if not plan.allow_overage and used_minutes >= plan.included_minutes:
        return False

    return True


def build_ai_usage_summary(clinic, target_date: date | None = None) -> AiUsageSummary:
    if target_date is None:
        target_date = timezone.localdate()

    plan = get_or_create_clinic_ai_plan(clinic)

    used_minutes = get_monthly_ai_usage_minutes(clinic, target_date)
    estimated_cost_yen = get_monthly_ai_estimated_cost_yen(clinic, target_date)

    included_minutes = plan.included_minutes
    remaining_minutes = max(included_minutes - used_minutes, 0)
    usage_percent = plan.usage_percent(used_minutes)
    overage_fee = plan.calc_overage_fee(used_minutes)

    warning_level, warning_message = get_ai_usage_warning(plan, used_minutes)
    can_use_ai = can_use_ai_for_clinic(plan, used_minutes)

    return AiUsageSummary(
        clinic_id=clinic.id,
        year=target_date.year,
        month=target_date.month,
        used_minutes=used_minutes,
        included_minutes=included_minutes,
        remaining_minutes=remaining_minutes,
        usage_percent=usage_percent,
        monthly_base_fee=plan.monthly_base_fee,
        overage_fee=overage_fee,
        estimated_cost_yen=estimated_cost_yen,
        warning_level=warning_level,
        warning_message=warning_message,
        is_ai_enabled=plan.is_ai_enabled,
        can_use_ai=can_use_ai,
    )


def get_clinic_from_recording(recording):
    """
    InterviewRecording から clinic を取得する。
    現在確認済みのルート:
    - recording.appointment.clinic
    - recording.appointment.patient.clinic
    - recording.intake.patient.clinic
    """

    appointment = getattr(recording, "appointment", None)
    intake = getattr(recording, "intake", None)

    if appointment:
        clinic = getattr(appointment, "clinic", None)
        if clinic:
            return clinic

        patient = getattr(appointment, "patient", None)
        if patient:
            clinic = getattr(patient, "clinic", None)
            if clinic:
                return clinic

    if intake:
        patient = getattr(intake, "patient", None)
        if patient:
            clinic = getattr(patient, "clinic", None)
            if clinic:
                return clinic

    clinic = getattr(recording, "clinic", None)
    if clinic:
        return clinic

    return None


def create_ai_usage_log_for_recording(
    *,
    recording,
    usage_type: str,
    model_name: str = "",
    transcript_text: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    estimated_cost_yen: int = 0,
    status: str = AiUsageLog.Status.SUCCESS,
    error_message: str = "",
    created_by=None,
    metadata: dict | None = None,
    count_billing_minutes: bool = True,
) -> AiUsageLog:
    duration_sec = getattr(recording, "duration_sec", 0) or 0

    billing_minutes = (
        AiUsageLog.seconds_to_billing_minutes(duration_sec)
        if count_billing_minutes
        else 0
    )

    appointment = getattr(recording, "appointment", None)
    intake = getattr(recording, "intake", None)

    patient = None

    if appointment:
        patient = getattr(appointment, "patient", None)

    if patient is None and intake:
        patient = getattr(intake, "patient", None)

    clinic = get_clinic_from_recording(recording)

    if clinic is None:
        raise ValueError("AI利用ログ作成に必要な clinic が取得できませんでした。")

    return AiUsageLog.objects.create(
        clinic=clinic,
        patient=patient,
        appointment=appointment,
        intake=intake,
        recording=recording,
        usage_type=usage_type,
        status=status,
        model_name=model_name or "",
        audio_duration_sec=duration_sec,
        billing_minutes=billing_minutes,
        transcript_chars=len(transcript_text or ""),
        input_tokens=input_tokens or 0,
        output_tokens=output_tokens or 0,
        estimated_cost_yen=estimated_cost_yen or 0,
        error_message=error_message or "",
        metadata=metadata or {},
        created_by=created_by,
    )