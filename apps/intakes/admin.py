from django.contrib import admin
from .models import Intake

@admin.register(Intake)
class IntakeAdmin(admin.ModelAdmin):
    list_display = ("submitted_at", "patient", "symptom_type", "chief_complaint", "appointment")
    list_filter = ("symptom_type",)
    search_fields = ("patient__last_name", "patient__first_name", "chief_complaint")
