from django import forms
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils.crypto import get_random_string

from apps.ai_usage.models import ClinicAiPlan
from apps.clinics.models import Clinic, ClinicSettings, TreatmentMenu
from apps.owner_admin.plans import (
    CARE_FROW_PLAN_CHOICES,
    CARE_FROW_PLAN_DEFINITIONS,
    apply_plan_definition,
    normalize_plan_key,
)

User = get_user_model()


STAFF_ROLE_CHOICES = [
    (User.Role.ADMIN, "管理者"),
    (User.Role.RECEPTION, "受付"),
    (User.Role.PRACTITIONER, "施術者"),
]


INITIAL_TREATMENT_MENUS = [
    ("初診", "初回の確認と施術", 5000, 60, 10),
    ("通常施術", "通常の施術メニュー", 5000, 30, 20),
    ("再診", "継続来院時の施術", 4000, 30, 30),
    ("自費施術", "自費メニュー", 7000, 45, 40),
]


class OwnerClinicBaseForm(forms.Form):
    clinic_name = forms.CharField(label="院名", max_length=100)
    booking_slug = forms.SlugField(
        label="予約URL用slug",
        max_length=80,
        required=False,
        help_text="院別予約URL /b/<slug>/ に使用します。空欄の場合は院名から自動生成します。",
    )
    phone = forms.CharField(label="電話番号", max_length=30, required=False)
    address = forms.CharField(label="住所", max_length=255, required=False)
    contact_email = forms.EmailField(
        label="院メール",
        required=False,
        help_text="現行モデルに保存先がないため、永続保存は次フェーズでClinicSettings拡張により対応します。",
    )
    primary_color = forms.CharField(
        label="テーマカラー",
        max_length=7,
        initial="#2563EB",
        help_text="#RRGGBB形式。staff管理画面のアクセント色に使います。",
    )
    status = forms.ChoiceField(
        label="ステータス",
        choices=[("active", "稼働中"), ("suspended", "停止準備中")],
        initial="active",
        help_text="現時点ではOwner画面上の表示のみです。本格停止制御は次フェーズで実装します。",
    )

    def clean_primary_color(self):
        value = (self.cleaned_data.get("primary_color") or "").strip()
        validator = ClinicSettings._meta.get_field("primary_color").validators[0]
        validator(value)
        return value

    def clean_booking_slug(self):
        value = (self.cleaned_data.get("booking_slug") or "").strip().lower()
        if not value:
            return value
        queryset = Clinic.objects.filter(booking_slug=value)
        clinic = getattr(self, "clinic", None)
        if clinic and clinic.pk:
            queryset = queryset.exclude(pk=clinic.pk)
        if queryset.exists():
            raise forms.ValidationError("この予約URL用slugはすでに使われています。")
        return value


class OwnerClinicCreateForm(OwnerClinicBaseForm):
    business_start_time = forms.TimeField(
        label="営業開始時刻",
        widget=forms.TimeInput(attrs={"type": "time"}),
        initial="09:00",
    )
    business_end_time = forms.TimeField(
        label="営業終了時刻",
        widget=forms.TimeInput(attrs={"type": "time"}),
        initial="20:00",
    )
    break_start_time = forms.TimeField(
        label="休憩開始時刻",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
        initial="13:00",
    )
    break_end_time = forms.TimeField(
        label="休憩終了時刻",
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
        initial="15:00",
    )
    appointment_interval_minutes = forms.ChoiceField(
        label="予約受付単位",
        choices=ClinicSettings.APPOINTMENT_INTERVAL_CHOICES,
        initial=30,
    )
    closed_weekdays = forms.MultipleChoiceField(
        label="休診曜日",
        choices=ClinicSettings.WEEKDAY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    plan_key = forms.ChoiceField(
        label="契約プラン",
        choices=CARE_FROW_PLAN_CHOICES,
        initial="standard",
    )
    admin_last_name = forms.CharField(label="初期管理者 姓", max_length=150)
    admin_first_name = forms.CharField(label="初期管理者 名", max_length=150)
    admin_email = forms.EmailField(label="初期管理者 メール", required=False)
    admin_username = forms.CharField(label="初期管理者 ログインID", max_length=150)
    admin_password = forms.CharField(
        label="初期パスワード",
        required=False,
        widget=forms.PasswordInput(render_value=True),
        help_text="未入力の場合はランダム生成し、作成直後に一度だけ表示します。",
    )
    admin_role = forms.ChoiceField(
        label="初期管理者 権限/ロール",
        choices=STAFF_ROLE_CHOICES,
        initial=User.Role.ADMIN,
    )

    def clean_plan_key(self):
        value = self.cleaned_data["plan_key"]
        if value not in CARE_FROW_PLAN_DEFINITIONS:
            raise forms.ValidationError("契約プランの指定が不正です。")
        return value

    def clean_admin_username(self):
        value = (self.cleaned_data.get("admin_username") or "").strip()
        if User.objects.filter(username=value).exists():
            raise forms.ValidationError("このログインIDはすでに使われています。")
        return value

    def clean_admin_email(self):
        value = (self.cleaned_data.get("admin_email") or "").strip()
        if value and User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError("このメールアドレスはすでに使われています。")
        return value

    def clean(self):
        cleaned = super().clean()
        business_start = cleaned.get("business_start_time")
        business_end = cleaned.get("business_end_time")
        break_start = cleaned.get("break_start_time")
        break_end = cleaned.get("break_end_time")
        if business_start and business_end and business_start >= business_end:
            self.add_error("business_end_time", "営業終了時刻は営業開始時刻より後にしてください。")
        if bool(break_start) != bool(break_end):
            self.add_error("break_end_time", "休憩時間は開始・終了の両方を入力してください。")
        elif break_start and break_end:
            if break_start >= break_end:
                self.add_error("break_end_time", "休憩終了時刻は休憩開始時刻より後にしてください。")
            elif business_start and business_end and (
                break_start < business_start or break_end > business_end
            ):
                self.add_error("break_end_time", "休憩時間は営業時間内に設定してください。")
        return cleaned

    @transaction.atomic
    def save(self):
        password = self.cleaned_data.get("admin_password") or get_random_string(14)
        generated_password = "" if self.cleaned_data.get("admin_password") else password

        clinic = Clinic.objects.create(
            name=self.cleaned_data["clinic_name"],
            booking_slug=self.cleaned_data.get("booking_slug") or "",
        )
        ClinicSettings.objects.create(
            clinic=clinic,
            display_name=self.cleaned_data["clinic_name"],
            phone=self.cleaned_data.get("phone") or "",
            address=self.cleaned_data.get("address") or "",
            business_start_time=self.cleaned_data["business_start_time"],
            business_end_time=self.cleaned_data["business_end_time"],
            break_start_time=self.cleaned_data.get("break_start_time"),
            break_end_time=self.cleaned_data.get("break_end_time"),
            appointment_interval_minutes=int(self.cleaned_data["appointment_interval_minutes"]),
            closed_weekdays=list(self.cleaned_data.get("closed_weekdays") or []),
            primary_color=self.cleaned_data["primary_color"],
        )
        ai_plan = ClinicAiPlan(clinic=clinic)
        apply_plan_definition(ai_plan, self.cleaned_data["plan_key"])
        ai_plan.full_clean()
        ai_plan.save()

        admin_user = User.objects.create_user(
            username=self.cleaned_data["admin_username"],
            password=password,
            clinic=clinic,
            role=self.cleaned_data["admin_role"],
            last_name=self.cleaned_data["admin_last_name"],
            first_name=self.cleaned_data["admin_first_name"],
            email=self.cleaned_data.get("admin_email") or "",
            is_active=True,
            is_staff=self.cleaned_data["admin_role"] == User.Role.ADMIN,
        )

        for name, description, price, duration, order in INITIAL_TREATMENT_MENUS:
            TreatmentMenu.objects.create(
                clinic=clinic,
                name=name,
                description=description,
                price=price,
                duration_minutes=duration,
                display_order=order,
                is_active=True,
            )

        return {
            "clinic": clinic,
            "admin_user": admin_user,
            "generated_password": generated_password,
        }


class OwnerClinicEditForm(OwnerClinicBaseForm):
    def __init__(self, *args, clinic, **kwargs):
        self.clinic = clinic
        settings = getattr(clinic, "settings", None)
        initial = kwargs.pop("initial", {})
        initial.update({
            "clinic_name": clinic.name,
            "booking_slug": clinic.booking_slug,
            "phone": getattr(settings, "phone", ""),
            "address": getattr(settings, "address", ""),
            "primary_color": getattr(settings, "primary_color", "#2563EB"),
            "status": "active",
        })
        super().__init__(*args, initial=initial, **kwargs)

    def save(self):
        self.clinic.name = self.cleaned_data["clinic_name"]
        self.clinic.booking_slug = self.cleaned_data.get("booking_slug") or ""
        self.clinic.save(update_fields=["name", "booking_slug"])
        settings, _ = ClinicSettings.objects.get_or_create(clinic=self.clinic)
        settings.phone = self.cleaned_data.get("phone") or ""
        settings.address = self.cleaned_data.get("address") or ""
        settings.primary_color = self.cleaned_data["primary_color"]
        settings.save(update_fields=["phone", "address", "primary_color", "updated_at"])
        return self.clinic


class OwnerClinicSettingsForm(forms.ModelForm):
    closed_weekdays = forms.MultipleChoiceField(
        label="休診曜日",
        choices=ClinicSettings.WEEKDAY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ClinicSettings
        fields = (
            "business_start_time",
            "business_end_time",
            "break_start_time",
            "break_end_time",
            "appointment_interval_minutes",
            "closed_weekdays",
            "primary_color",
            "secondary_color",
            "accent_color",
        )
        widgets = {
            "business_start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "business_end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "break_start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "break_end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def __init__(self, *args, clinic, **kwargs):
        self.clinic = clinic
        instance, _ = ClinicSettings.objects.get_or_create(clinic=clinic)
        kwargs["instance"] = instance
        super().__init__(*args, **kwargs)
        self.fields["closed_weekdays"].initial = instance.closed_weekdays or []

    def save(self, commit=True):
        settings = super().save(commit=False)
        settings.clinic = self.clinic
        settings.closed_weekdays = list(self.cleaned_data.get("closed_weekdays") or [])
        if commit:
            settings.full_clean()
            settings.save()
        return settings


class OwnerPlanForm(forms.Form):
    plan_key = forms.ChoiceField(label="契約プラン", choices=CARE_FROW_PLAN_CHOICES)
    is_ai_enabled = forms.BooleanField(label="AI機能を有効にする", required=False, initial=True)
    allow_overage = forms.BooleanField(label="超過利用を許可する", required=False, initial=True)
    hard_limit_minutes = forms.IntegerField(label="hard limit 分数", min_value=0, required=False)

    def __init__(self, *args, clinic, **kwargs):
        self.clinic = clinic
        plan = ClinicAiPlan.objects.filter(clinic=clinic).first()
        initial = kwargs.pop("initial", {})
        if plan:
            key = normalize_plan_key(plan.plan_name) or "standard"
            initial.update({
                "plan_key": key,
                "is_ai_enabled": plan.is_ai_enabled,
                "allow_overage": plan.allow_overage,
                "hard_limit_minutes": plan.hard_limit_minutes,
            })
        else:
            initial.setdefault("plan_key", "standard")
        super().__init__(*args, initial=initial, **kwargs)

    def clean_plan_key(self):
        value = self.cleaned_data["plan_key"]
        if value not in CARE_FROW_PLAN_DEFINITIONS:
            raise forms.ValidationError("契約プランの指定が不正です。")
        return value

    def save(self):
        plan, _ = ClinicAiPlan.objects.get_or_create(clinic=self.clinic)
        apply_plan_definition(plan, self.cleaned_data["plan_key"])
        plan.is_ai_enabled = bool(self.cleaned_data.get("is_ai_enabled"))
        plan.allow_overage = bool(self.cleaned_data.get("allow_overage"))
        if self.cleaned_data.get("hard_limit_minutes") is not None:
            plan.hard_limit_minutes = self.cleaned_data["hard_limit_minutes"]
        plan.full_clean()
        plan.save()
        return plan


class OwnerStaffCreateForm(forms.Form):
    last_name = forms.CharField(label="姓", max_length=150)
    first_name = forms.CharField(label="名", max_length=150)
    email = forms.EmailField(label="メール", required=False)
    username = forms.CharField(label="ログインID", max_length=150)
    password = forms.CharField(label="初期パスワード", widget=forms.PasswordInput(render_value=True))
    role = forms.ChoiceField(label="権限/ロール", choices=STAFF_ROLE_CHOICES, initial=User.Role.PRACTITIONER)
    is_active = forms.BooleanField(label="有効", required=False, initial=True)
    show_in_reservations = forms.BooleanField(
        label="予約担当に使う",
        required=False,
        initial=True,
        help_text="現時点では有効スタッフとして扱うことで予約担当候補に表示されます。",
    )
    show_in_sales = forms.BooleanField(
        label="売上担当に使う",
        required=False,
        initial=True,
        help_text="現時点では有効スタッフとして扱うことで売上担当候補に表示されます。",
    )

    def __init__(self, *args, clinic, **kwargs):
        self.clinic = clinic
        super().__init__(*args, **kwargs)

    def clean_username(self):
        value = (self.cleaned_data.get("username") or "").strip()
        if User.objects.filter(username=value).exists():
            raise forms.ValidationError("このログインIDはすでに使われています。")
        return value

    def clean_email(self):
        value = (self.cleaned_data.get("email") or "").strip()
        if value and User.objects.filter(email__iexact=value).exists():
            raise forms.ValidationError("このメールアドレスはすでに使われています。")
        return value

    def save(self):
        return User.objects.create_user(
            username=self.cleaned_data["username"],
            password=self.cleaned_data["password"],
            clinic=self.clinic,
            role=self.cleaned_data["role"],
            last_name=self.cleaned_data["last_name"],
            first_name=self.cleaned_data["first_name"],
            email=self.cleaned_data.get("email") or "",
            is_active=bool(self.cleaned_data.get("is_active")),
            is_staff=self.cleaned_data["role"] == User.Role.ADMIN,
        )
