from django.contrib import admin
from .models import Visit
from apps.ai_jobs.usecases import run_ai_draft

@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ("visited_at", "patient", "status", "practitioner", "appointment")
    list_filter = ("status",)
    search_fields = ("patient__last_name", "patient__first_name", "memo")
    actions = ["generate_ai_draft"]

    @admin.action(description="カルテ案を作成（テキスト入力）")
    def generate_ai_draft(self, request, queryset):
        for v in queryset:
            run_ai_draft(v, input_text="（テスト）診察で聞いた内容をここに入れる想定。腰部の痛みが動作時に増強。")
        self.message_user(request, "カルテ案を作成しました（ChartNoteを確認してください）")
