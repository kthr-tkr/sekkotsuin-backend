from django.contrib import admin

from .models import Clinic, ClinicSettings, SalesRecord, TreatmentMenu


@admin.register(Clinic)
class ClinicAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "created_at")
    search_fields = ("name",)


@admin.register(ClinicSettings)
class ClinicSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "clinic",
        "display_name",
        "business_start_time",
        "business_end_time",
        "appointment_interval_minutes",
        "updated_at",
    )
    search_fields = ("clinic__name", "display_name", "phone", "address")


@admin.register(TreatmentMenu)
class TreatmentMenuAdmin(admin.ModelAdmin):
    list_display = (
        "clinic",
        "name",
        "price",
        "duration_minutes",
        "is_active",
        "display_order",
        "updated_at",
    )
    list_filter = ("clinic", "is_active")
    search_fields = ("clinic__name", "name", "description")


@admin.register(SalesRecord)
class SalesRecordAdmin(admin.ModelAdmin):
    list_display = (
        "clinic",
        "treatment_date",
        "patient",
        "treatment_menu",
        "amount",
        "payment_method",
        "status",
        "staff",
    )
    list_filter = ("clinic", "payment_method", "status", "treatment_date")
    search_fields = (
        "clinic__name",
        "patient__last_name",
        "patient__first_name",
        "treatment_menu__name",
        "memo",
    )
