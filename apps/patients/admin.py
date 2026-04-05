from django.contrib import admin
from .models import Patient

@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ("id", "last_name", "first_name", "birth_date", "phone", "clinic")
    search_fields = ("last_name", "first_name", "phone")
    list_filter = ("clinic",)
