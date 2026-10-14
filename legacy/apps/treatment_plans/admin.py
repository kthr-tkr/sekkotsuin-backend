from django.contrib import admin
from .models import TreatmentPlan, TreatmentProgress


@admin.register(TreatmentPlan)
class TreatmentPlanAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "patient",
        "title",
        "chief_complaint",
        "next_visit_date",
        "is_active",
        "explained_to_patient",
        "created_at",
    )
    list_filter = ("is_active", "explained_to_patient", "visit_guide_type", "created_at")
    search_fields = ("patient__last_name", "patient__first_name", "title", "chief_complaint")


@admin.register(TreatmentProgress)
class TreatmentProgressAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "plan",
        "visit_date",
        "pain_level",
        "created_by",
        "created_at",
    )
    list_filter = ("visit_date", "created_at")
    search_fields = ("plan__patient__last_name", "plan__patient__first_name", "symptom_change", "memo")