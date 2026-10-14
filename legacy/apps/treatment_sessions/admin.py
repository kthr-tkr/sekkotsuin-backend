from django.contrib import admin

from .models import TreatmentSession, TreatmentSessionChunk


class TreatmentSessionChunkInline(admin.TabularInline):
    model = TreatmentSessionChunk
    extra = 0
    fields = (
        "chunk_index",
        "status",
        "duration_sec",
        "mime_type",
        "audio_file",
        "created_at",
    )
    readonly_fields = ("created_at",)


@admin.register(TreatmentSession)
class TreatmentSessionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "clinic",
        "patient",
        "appointment",
        "status",
        "total_duration_sec",
        "summary_status",
        "started_at",
        "ended_at",
        "created_at",
    )

    list_filter = (
        "status",
        "summary_status",
        "clinic",
        "created_at",
    )

    search_fields = (
        "patient__last_name",
        "patient__first_name",
        "title",
        "memo",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
        "confirmed_at",
    )

    inlines = [TreatmentSessionChunkInline]


@admin.register(TreatmentSessionChunk)
class TreatmentSessionChunkAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "session",
        "chunk_index",
        "status",
        "duration_sec",
        "mime_type",
        "created_at",
    )

    list_filter = (
        "status",
        "created_at",
    )

    search_fields = (
        "session__patient__last_name",
        "session__patient__first_name",
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )