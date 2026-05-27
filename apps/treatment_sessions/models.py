from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils import timezone


class TreatmentSession(models.Model):
    """
    来院〜施術終了までの1回分の施術セッション。

    役割:
    - 問診だけでなく、施術中の会話・処置内容・説明内容をまとめて管理する
    - 長時間録音の親データになる
    - 最終的にClinicalNote / TreatmentProgress / TreatmentPlanと連携する
    """

    class Status(models.TextChoices):
        PENDING = "pending", "準備中"
        RECORDING = "recording", "録音中"
        UPLOADED = "uploaded", "アップロード済み"
        TRANSCRIBING = "transcribing", "文字起こし中"
        SUMMARIZING = "summarizing", "要約中"
        DONE = "done", "完了"
        FAILED = "failed", "失敗"
        CANCELED = "canceled", "キャンセル"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="treatment_sessions",
        verbose_name="院",
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.CASCADE,
        related_name="treatment_sessions",
        verbose_name="患者",
    )

    appointment = models.OneToOneField(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="treatment_session",
        verbose_name="予約",
    )

    intake = models.ForeignKey(
        "intakes.Intake",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="treatment_sessions",
        verbose_name="Web問診",
    )

    clinical_note = models.ForeignKey(
        "clinical_notes.ClinicalNote",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="treatment_sessions",
        verbose_name="カルテ",
    )

    treatment_plan = models.ForeignKey(
        "treatment_plans.TreatmentPlan",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="treatment_sessions",
        verbose_name="施術計画",
    )

    title = models.CharField(
        "セッション名",
        max_length=120,
        blank=True,
        help_text="例: 初回施術、再診、腰痛施術など",
    )

    status = models.CharField(
        "ステータス",
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )

    started_at = models.DateTimeField(
        "開始日時",
        null=True,
        blank=True,
    )

    ended_at = models.DateTimeField(
        "終了日時",
        null=True,
        blank=True,
    )

    total_duration_sec = models.PositiveIntegerField(
        "合計録音秒数",
        default=0,
    )

    transcript_text = models.TextField(
        "統合文字起こし",
        blank=True,
    )

    transcript_json = models.JSONField(
        "統合文字起こしJSON",
        default=dict,
        blank=True,
    )

    summary_json = models.JSONField(
        "AI統合要約",
        default=dict,
        blank=True,
    )

    confirmed_summary_json = models.JSONField(
        "確定済み要約",
        default=dict,
        blank=True,
    )

    summary_status = models.CharField(
        "要約確認状態",
        max_length=30,
        default="draft",
        help_text="draft / confirmed など",
    )

    error_message = models.TextField(
        "エラー内容",
        blank=True,
    )

    memo = models.TextField(
        "スタッフメモ",
        blank=True,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_treatment_sessions",
        verbose_name="作成者",
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="updated_treatment_sessions",
        verbose_name="更新者",
    )

    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="confirmed_treatment_sessions",
        verbose_name="要約確定者",
    )

    confirmed_at = models.DateTimeField(
        "要約確定日時",
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "施術セッション"
        verbose_name_plural = "施術セッション"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "created_at"]),
            models.Index(fields=["clinic", "status", "created_at"]),
            models.Index(fields=["patient", "created_at"]),
            models.Index(fields=["appointment"]),
        ]

    def __str__(self) -> str:
        return f"{self.patient} / {self.started_at or self.created_at}"

    @property
    def active_summary(self) -> dict:
        """
        確定済み要約があればそれを優先。
        なければAI下書き要約を返す。
        """
        if self.confirmed_summary_json:
            return self.confirmed_summary_json
        return self.summary_json or {}

    def mark_started(self):
        self.status = self.Status.RECORDING
        if not self.started_at:
            self.started_at = timezone.now()

    def mark_ended(self):
        self.status = self.Status.UPLOADED
        if not self.ended_at:
            self.ended_at = timezone.now()

    def mark_confirmed(self, *, user, data: dict):
        self.confirmed_summary_json = data or {}
        self.summary_status = "confirmed"
        self.confirmed_by = user
        self.confirmed_at = timezone.now()


class TreatmentSessionChunk(models.Model):
    """
    長時間録音を分割した音声チャンク。

    将来的に:
    - 5分ごとに音声を分割
    - chunkごとにSTT
    - chunkごとに小要約
    - 最後にTreatmentSessionへ統合要約
    """

    class Status(models.TextChoices):
        PENDING = "pending", "準備中"
        UPLOADED = "uploaded", "アップロード済み"
        TRANSCRIBING = "transcribing", "文字起こし中"
        SUMMARIZED = "summarized", "要約済み"
        FAILED = "failed", "失敗"

    session = models.ForeignKey(
        TreatmentSession,
        on_delete=models.CASCADE,
        related_name="chunks",
        verbose_name="施術セッション",
    )

    chunk_index = models.PositiveIntegerField(
        "チャンク番号",
        default=0,
        help_text="0始まり。録音順に並べる。",
    )

    audio_file = models.FileField(
        "音声ファイル",
        upload_to="treatment_session_audio/%Y/%m/",
        blank=True,
        null=True,
    )

    mime_type = models.CharField(
        "MIME Type",
        max_length=100,
        blank=True,
    )

    duration_sec = models.PositiveIntegerField(
        "録音秒数",
        default=0,
    )

    transcript_text = models.TextField(
        "文字起こし",
        blank=True,
    )

    transcript_json = models.JSONField(
        "文字起こしJSON",
        default=dict,
        blank=True,
    )

    summary_json = models.JSONField(
        "チャンク要約",
        default=dict,
        blank=True,
    )

    status = models.CharField(
        "ステータス",
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING,
    )

    error_message = models.TextField(
        "エラー内容",
        blank=True,
    )

    metadata = models.JSONField(
        "追加情報",
        default=dict,
        blank=True,
    )

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "施術セッションチャンク"
        verbose_name_plural = "施術セッションチャンク"
        ordering = ["session", "chunk_index"]
        constraints = [
            models.UniqueConstraint(
                fields=["session", "chunk_index"],
                name="unique_treatment_session_chunk_index",
            )
        ]
        indexes = [
            models.Index(fields=["session", "chunk_index"]),
            models.Index(fields=["session", "status"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self) -> str:
        return f"session={self.session_id} / chunk={self.chunk_index}"