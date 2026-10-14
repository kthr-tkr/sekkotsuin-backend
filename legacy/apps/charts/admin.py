from django.contrib import admin
from .models import ChartNote

@admin.register(ChartNote)
class ChartNoteAdmin(admin.ModelAdmin):
    list_display = ("created_at", "visit", "version", "state", "created_by")
    list_filter = ("state",)
    search_fields = ("visit__patient__last_name", "visit__patient__first_name",
                     "subjective_text", "objective_text", "assessment_text", "plan_text")
