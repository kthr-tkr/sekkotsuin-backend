from django.contrib import admin
from .models import Appointment

@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ("start_at", "end_at", "menu", "status", "patient", "assigned_staff")
    list_filter = ("status", "menu")
    search_fields = ("patient__last_name", "patient__first_name", "notes")
