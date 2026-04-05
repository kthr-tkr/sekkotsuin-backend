from django.contrib import admin
from .models import AudioJob

@admin.register(AudioJob)
class AudioJobAdmin(admin.ModelAdmin):
    list_display = ("created_at", "visit", "status", "started_at", "finished_at")
    list_filter = ("status",)
    search_fields = ("visit__patient__last_name", "visit__patient__first_name", "error_message")
