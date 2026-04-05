from django.db import models


class AudioJob(models.Model):
    class Status(models.TextChoices):
        QUEUED = "queued", "待機"
        PROCESSING = "processing", "処理中"
        SUCCESS = "success", "成功"
        FAILED = "failed", "失敗"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="audio_jobs",
    )

    visit = models.ForeignKey(
        "visits.Visit",
        on_delete=models.CASCADE,
        related_name="audio_jobs",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.QUEUED,
    )

    # まずは「診察テキスト」を保存（録音→STTが来たら transcript_text に入る）
    input_text = models.TextField(blank=True)

    # STT結果（将来）
    transcript_text = models.TextField(blank=True)

    # AI要約結果（将来デバッグ用。不要なら空でもOK）
    summary_text = models.TextField(blank=True)

    error_message = models.TextField(blank=True)

    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    
    ai_output_json = models.JSONField(default=dict, blank=True)
    
    safety_hits = models.JSONField(default=list, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["clinic", "created_at"]),
        ]

    def __str__(self):
        return f"AudioJob {self.visit_id} {self.status}"
