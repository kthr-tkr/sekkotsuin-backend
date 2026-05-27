from django.contrib import admin

from .models import AiUsageLog, ClinicAiPlan


@admin.register(ClinicAiPlan)
class ClinicAiPlanAdmin(admin.ModelAdmin):
    list_display = (
        "clinic",
        "plan_name",
        "monthly_base_fee",
        "included_minutes",
        "overage_unit_minutes",
        "overage_unit_price",
        "hard_limit_minutes",
        "is_ai_enabled",
        "allow_overage",
        "updated_at",
    )

    list_filter = (
        "plan_name",
        "is_ai_enabled",
        "allow_overage",
    )

    search_fields = (
        "clinic__name",
        "plan_name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )


@admin.register(AiUsageLog)
class AiUsageLogAdmin(admin.ModelAdmin):
    list_display = (
        "created_at",
        "clinic",
        "patient",
        "appointment",
        "usage_type",
        "status",
        "model_name",
        "billing_minutes",
        "audio_duration_sec",
        "transcript_chars",
        "estimated_cost_yen",
    )

    list_filter = (
        "usage_type",
        "status",
        "model_name",
        "created_at",
    )

    search_fields = (
        "clinic__name",
        "patient__last_name",
        "patient__first_name",
        "model_name",
    )

    readonly_fields = (
        "created_at",
    )

    date_hierarchy = "created_at"