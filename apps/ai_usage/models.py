from __future__ import annotations

import math

from django.conf import settings
from django.db import models
from django.utils import timezone


class ClinicAiPlan(models.Model):
    """
    院ごとのAI契約・上限設定。

    例:
    - 月額基本料金: 50,000円
    - 月1,000分まで込み
    - 超過100分ごとに2,000円
    - hard limit 1,500分
    """

    clinic = models.OneToOneField(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="ai_plan",
        verbose_name="院",
    )

    plan_name = models.CharField(
        "プラン名",
        max_length=100,
        default="スタンダード",
        blank=True,
    )

    monthly_base_fee = models.PositiveIntegerField(
        "月額基本料金",
        default=50000,
        help_text="月額基本料金。例: 50000",
    )

    included_minutes = models.PositiveIntegerField(
        "月内込み利用分数",
        default=1000,
        help_text="月額内に含まれるAI録音・文字起こし分数。",
    )

    overage_unit_minutes = models.PositiveIntegerField(
        "超過課金単位分数",
        default=100,
        help_text="超過課金の単位。例: 100分ごと",
    )

    overage_unit_price = models.PositiveIntegerField(
        "超過課金単価",
        default=2000,
        help_text="超過課金単位ごとの金額。例: 100分ごとに2000円",
    )

    warning_threshold_percent = models.PositiveIntegerField(
        "警告しきい値",
        default=80,
        help_text="利用量が何%に達したら警告するか。例: 80",
    )

    danger_threshold_percent = models.PositiveIntegerField(
        "危険しきい値",
        default=90,
        help_text="利用量が何%に達したら強めの警告を出すか。例: 90",
    )

    hard_limit_minutes = models.PositiveIntegerField(
        "強制停止分数",
        default=1500,
        help_text="この分数を超えた場合、AI録音・要約を停止する目安。",
    )

    is_ai_enabled = models.BooleanField(
        "AI機能有効",
        default=True,
    )

    allow_overage = models.BooleanField(
        "超過利用を許可",
        default=True,
        help_text="Falseの場合、込み分数を超えた時点でAI利用を制限する。",
    )

    notes = models.TextField(
        "備考",
        blank=True,
    )

    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "院別AI契約設定"
        verbose_name_plural = "院別AI契約設定"

    def __str__(self) -> str:
        return f"{self.clinic} / {self.plan_name}"

    def calc_overage_fee(self, used_minutes: int) -> int:
        """
        利用分数から超過料金を計算する。

        例:
        included_minutes = 1000
        overage_unit_minutes = 100
        overage_unit_price = 2000

        used_minutes = 1001 -> 2000円
        used_minutes = 1100 -> 2000円
        used_minutes = 1101 -> 4000円
        """
        if used_minutes <= self.included_minutes:
            return 0

        over_minutes = used_minutes - self.included_minutes

        if self.overage_unit_minutes <= 0:
            return 0

        units = math.ceil(over_minutes / self.overage_unit_minutes)
        return units * self.overage_unit_price

    def is_hard_limit_reached(self, used_minutes: int) -> bool:
        return used_minutes >= self.hard_limit_minutes

    def usage_percent(self, used_minutes: int) -> int:
        if self.included_minutes <= 0:
            return 0

        return int((used_minutes / self.included_minutes) * 100)


class AiUsageLog(models.Model):
    """
    AI利用ログ。

    STT、要約、将来的な姿勢分析AIなど、AI処理ごとの利用量を記録する。
    請求・上限判定・管理画面表示の元データになる。
    """

    class UsageType(models.TextChoices):
        STT = "stt", "文字起こし"
        SUMMARY = "summary", "AI要約"
        SOAP = "soap", "SOAP生成"
        TREATMENT_PLAN = "treatment_plan", "施術計画生成"
        POSTURE = "posture", "姿勢分析"
        OTHER = "other", "その他"

    class Status(models.TextChoices):
        SUCCESS = "success", "成功"
        FAILED = "failed", "失敗"
        SKIPPED = "skipped", "スキップ"

    clinic = models.ForeignKey(
        "clinics.Clinic",
        on_delete=models.CASCADE,
        related_name="ai_usage_logs",
        verbose_name="院",
    )

    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
        verbose_name="患者",
    )

    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
        verbose_name="予約",
    )

    intake = models.ForeignKey(
        "intakes.Intake",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
        verbose_name="Web問診",
    )

    recording = models.ForeignKey(
        "intakes.InterviewRecording",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="ai_usage_logs",
        verbose_name="AI録音",
    )

    usage_type = models.CharField(
        "利用種別",
        max_length=50,
        choices=UsageType.choices,
        default=UsageType.OTHER,
    )

    status = models.CharField(
        "処理結果",
        max_length=20,
        choices=Status.choices,
        default=Status.SUCCESS,
    )

    model_name = models.CharField(
        "AIモデル名",
        max_length=100,
        blank=True,
        help_text="例: gpt-4.1-mini, whisper-1 など",
    )

    audio_duration_sec = models.PositiveIntegerField(
        "音声時間 秒",
        default=0,
    )

    transcript_chars = models.PositiveIntegerField(
        "文字起こし文字数",
        default=0,
    )

    input_tokens = models.PositiveIntegerField(
        "入力トークン数",
        default=0,
    )

    output_tokens = models.PositiveIntegerField(
        "出力トークン数",
        default=0,
    )

    estimated_cost_yen = models.PositiveIntegerField(
        "推定AI原価 円",
        default=0,
        help_text="OpenAI等のAPI原価の概算。顧客への請求額ではない。",
    )

    billing_minutes = models.PositiveIntegerField(
        "請求対象分数",
        default=0,
        help_text="音声秒数を切り上げた請求対象分数。例: 61秒なら2分。",
    )

    error_message = models.TextField(
        "エラー内容",
        blank=True,
    )

    metadata = models.JSONField(
        "追加情報",
        default=dict,
        blank=True,
        help_text="処理ID、chunk番号、APIレスポンス情報などを保存。",
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="created_ai_usage_logs",
        verbose_name="実行ユーザー",
    )

    created_at = models.DateTimeField("作成日時", auto_now_add=True)

    class Meta:
        verbose_name = "AI利用ログ"
        verbose_name_plural = "AI利用ログ"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["clinic", "created_at"]),
            models.Index(fields=["clinic", "usage_type", "created_at"]),
            models.Index(fields=["patient", "created_at"]),
            models.Index(fields=["appointment", "created_at"]),
            models.Index(fields=["recording", "created_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.clinic} / {self.get_usage_type_display()} / {self.billing_minutes}分"

    @staticmethod
    def seconds_to_billing_minutes(seconds: int | None) -> int:
        """
        秒数を請求対象分数に変換する。
        1秒でもあれば1分としてカウント。
        """
        if not seconds or seconds <= 0:
            return 0

        return math.ceil(seconds / 60)