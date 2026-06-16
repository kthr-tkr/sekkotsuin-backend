from datetime import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils import timezone

class Clinic(models.Model):
    name = models.CharField(max_length=100)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name


color_validator = RegexValidator(
    regex=r"^#[0-9A-Fa-f]{6}$",
    message="カラーコードは #RRGGBB 形式で入力してください。",
)


class ClinicSettings(models.Model):
    WEEKDAY_CHOICES = [
        ("mon", "月曜日"),
        ("tue", "火曜日"),
        ("wed", "水曜日"),
        ("thu", "木曜日"),
        ("fri", "金曜日"),
        ("sat", "土曜日"),
        ("sun", "日曜日"),
    ]
    APPOINTMENT_INTERVAL_CHOICES = [
        (5, "5分"),
        (10, "10分"),
        (15, "15分"),
        (20, "20分"),
        (30, "30分"),
        (60, "60分"),
    ]

    clinic = models.OneToOneField(
        Clinic,
        on_delete=models.CASCADE,
        related_name="settings",
        verbose_name="院",
    )
    display_name = models.CharField(
        "表示用院名",
        max_length=120,
        blank=True,
    )
    phone = models.CharField(
        "電話番号",
        max_length=30,
        blank=True,
    )
    address = models.CharField(
        "住所",
        max_length=255,
        blank=True,
    )
    booking_description = models.TextField(
        "予約画面に表示する説明文",
        blank=True,
    )
    business_start_time = models.TimeField(
        "営業開始時刻",
        default=time(9, 0),
    )
    business_end_time = models.TimeField(
        "営業終了時刻",
        default=time(20, 0),
    )
    break_start_time = models.TimeField(
        "休憩開始時刻",
        default=time(13, 0),
        null=True,
        blank=True,
    )
    break_end_time = models.TimeField(
        "休憩終了時刻",
        default=time(15, 0),
        null=True,
        blank=True,
    )
    appointment_interval_minutes = models.PositiveSmallIntegerField(
        "予約受付単位",
        choices=APPOINTMENT_INTERVAL_CHOICES,
        default=30,
    )
    closed_weekdays = models.JSONField(
        "休診曜日",
        default=list,
        blank=True,
    )
    primary_color = models.CharField(
        "メインカラー",
        max_length=7,
        default="#1D4ED8",
        validators=[color_validator],
    )
    secondary_color = models.CharField(
        "サブカラー",
        max_length=7,
        default="#0F172A",
        validators=[color_validator],
    )
    accent_color = models.CharField(
        "アクセントカラー",
        max_length=7,
        default="#16A34A",
        validators=[color_validator],
    )
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        verbose_name = "院設定"
        verbose_name_plural = "院設定"

    def __str__(self):
        return f"{self.clinic} / 院設定"

    def clean(self):
        errors = {}

        if (
            self.business_start_time
            and self.business_end_time
            and self.business_start_time >= self.business_end_time
        ):
            errors["business_end_time"] = (
                "営業終了時刻は営業開始時刻より後にしてください。"
            )

        has_break_start = self.break_start_time is not None
        has_break_end = self.break_end_time is not None
        if has_break_start != has_break_end:
            errors["break_end_time"] = (
                "休憩時間を設定する場合は開始・終了の両方を入力してください。"
            )
        elif has_break_start and has_break_end:
            if self.break_start_time >= self.break_end_time:
                errors["break_end_time"] = (
                    "休憩終了時刻は休憩開始時刻より後にしてください。"
                )
            elif (
                self.business_start_time
                and self.business_end_time
                and (
                    self.break_start_time < self.business_start_time
                    or self.break_end_time > self.business_end_time
                )
            ):
                errors["break_end_time"] = (
                    "休憩時間は営業時間内に設定してください。"
                )

        valid_weekdays = {value for value, _ in self.WEEKDAY_CHOICES}
        invalid_weekdays = set(self.closed_weekdays or []) - valid_weekdays
        if invalid_weekdays:
            errors["closed_weekdays"] = "休診曜日の指定が不正です。"

        if errors:
            raise ValidationError(errors)


class TreatmentMenu(models.Model):
    clinic = models.ForeignKey(
        Clinic,
        on_delete=models.CASCADE,
        related_name="treatment_menus",
        verbose_name="院",
    )
    name = models.CharField("メニュー名", max_length=120)
    description = models.TextField("説明", blank=True)
    price = models.PositiveIntegerField(
        "料金",
        default=0,
        validators=[MinValueValidator(0)],
        help_text="税込または院内運用に合わせた表示用料金です。",
    )
    duration_minutes = models.PositiveSmallIntegerField(
        "所要時間",
        default=30,
        validators=[MinValueValidator(5)],
    )
    is_active = models.BooleanField("有効", default=True)
    display_order = models.IntegerField("並び順", default=0)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        ordering = ("display_order", "name", "id")
        verbose_name = "施術メニュー"
        verbose_name_plural = "施術メニュー"

    def __str__(self):
        return f"{self.clinic} / {self.name}"

    def clean(self):
        errors = {}

        if self.price is not None and self.price < 0:
            errors["price"] = "料金は0円以上で入力してください。"

        if self.duration_minutes is not None:
            if self.duration_minutes < 5:
                errors["duration_minutes"] = "所要時間は5分以上で入力してください。"
            elif self.duration_minutes % 5 != 0:
                errors["duration_minutes"] = "所要時間は5分単位で入力してください。"

        if errors:
            raise ValidationError(errors)


class SalesRecord(models.Model):
    class PaymentMethod(models.TextChoices):
        CASH = "cash", "現金"
        CARD = "card", "カード"
        QR = "qr", "QR決済"
        BANK_TRANSFER = "bank_transfer", "銀行振込"
        OTHER = "other", "その他"

    class Status(models.TextChoices):
        UNPAID = "unpaid", "未払い"
        PAID = "paid", "支払い済み"
        CANCELED = "canceled", "キャンセル"

    clinic = models.ForeignKey(
        Clinic,
        on_delete=models.CASCADE,
        related_name="sales_records",
        verbose_name="院",
    )
    patient = models.ForeignKey(
        "patients.Patient",
        on_delete=models.PROTECT,
        related_name="sales_records",
        verbose_name="患者",
    )
    appointment = models.ForeignKey(
        "appointments.Appointment",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_records",
        verbose_name="予約",
    )
    clinical_note = models.ForeignKey(
        "clinical_notes.ClinicalNote",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_records",
        verbose_name="カルテ",
    )
    treatment_menu = models.ForeignKey(
        TreatmentMenu,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_records",
        verbose_name="施術メニュー",
    )
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sales_records",
        verbose_name="担当者",
    )
    treatment_date = models.DateField(
        "施術日",
        default=timezone.localdate,
        db_index=True,
    )
    amount = models.PositiveIntegerField(
        "金額",
        default=0,
        validators=[MinValueValidator(0)],
    )
    payment_method = models.CharField(
        "支払方法",
        max_length=20,
        choices=PaymentMethod.choices,
        default=PaymentMethod.CASH,
    )
    status = models.CharField(
        "ステータス",
        max_length=20,
        choices=Status.choices,
        default=Status.PAID,
    )
    memo = models.TextField("メモ", blank=True)
    created_at = models.DateTimeField("作成日時", auto_now_add=True)
    updated_at = models.DateTimeField("更新日時", auto_now=True)

    class Meta:
        ordering = ("-treatment_date", "-created_at", "-id")
        indexes = [
            models.Index(fields=["clinic", "treatment_date"]),
            models.Index(fields=["clinic", "status"]),
            models.Index(fields=["clinic", "payment_method"]),
        ]
        verbose_name = "売上実績"
        verbose_name_plural = "売上実績"

    def __str__(self):
        return f"{self.treatment_date} {self.patient} {self.amount}円"

    def clean(self):
        errors = {}

        if not self.clinic_id:
            errors["clinic"] = "院情報は必須です。"

        if not self.patient_id:
            errors["patient"] = "患者は必須です。"
        elif self.clinic_id and self.patient.clinic_id != self.clinic_id:
            errors["patient"] = "患者は同じ院に所属している必要があります。"

        if not self.treatment_date:
            errors["treatment_date"] = "施術日は必須です。"

        if self.amount is not None and self.amount < 0:
            errors["amount"] = "金額は0円以上で入力してください。"

        if self.appointment_id:
            if self.clinic_id and self.appointment.clinic_id != self.clinic_id:
                errors["appointment"] = "予約は同じ院に所属している必要があります。"
            if (
                self.patient_id
                and self.appointment.patient_id
                and self.appointment.patient_id != self.patient_id
            ):
                errors["appointment"] = "予約の患者と売上の患者が一致していません。"

        if self.clinical_note_id:
            note_patient_id = self.clinical_note.patient_id
            if self.patient_id and note_patient_id != self.patient_id:
                errors["clinical_note"] = "カルテの患者と売上の患者が一致していません。"
            note_clinic_id = getattr(
                self.clinical_note.appointment,
                "clinic_id",
                None,
            )
            if self.clinic_id and note_clinic_id != self.clinic_id:
                errors["clinical_note"] = "カルテは同じ院に所属している必要があります。"

        if self.treatment_menu_id:
            if (
                self.clinic_id
                and self.treatment_menu.clinic_id != self.clinic_id
            ):
                errors["treatment_menu"] = "施術メニューは同じ院に所属している必要があります。"

        if self.staff_id:
            staff_clinic_id = getattr(self.staff, "clinic_id", None)
            if self.clinic_id and staff_clinic_id != self.clinic_id:
                errors["staff"] = "担当者は同じ院に所属している必要があります。"

        if errors:
            raise ValidationError(errors)
