from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.db.models import Q

from apps.appointments.models import Appointment
from apps.clinical_notes.models import ClinicalNote
from apps.clinics.models import ClinicSettings, SalesRecord, StaffLeave, StaffShift, TreatmentMenu
from apps.patients.models import Patient

User = get_user_model()

SYMPTOM_TYPE_CHOICES = [
    ("", "選択してください"),
    ("acute", "急性"),
    ("chronic", "慢性"),
    ("unknown", "不明"),
    ("followup", "通院・再診"),
]


class StaffLoginForm(AuthenticationForm):
    username = forms.CharField(
        label="LOGIN ID",
        widget=forms.TextInput(attrs={"placeholder": "user001", "autocomplete": "username"}),
    )
    password = forms.CharField(
        label="PASSWORD",
        widget=forms.PasswordInput(attrs={"placeholder": "••••••••", "autocomplete": "current-password"}),
    )


class StaffCreateForm(UserCreationForm):
    last_name = forms.CharField(
        label="姓",
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "山田"})
    )
    first_name = forms.CharField(
        label="名",
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "太郎"})
    )
    email = forms.EmailField(
        label="メールアドレス",
        required=False,
        widget=forms.EmailInput(attrs={"placeholder": "example@clinic.com"})
    )
    username = forms.CharField(
        label="ユーザー名",
        max_length=150,
        widget=forms.TextInput(attrs={"placeholder": "yamada"})
    )
    role = forms.ChoiceField(
        label="役割",
        choices=[
            (User.Role.RECEPTION, "受付"),
            (User.Role.PRACTITIONER, "施術者"),
            (User.Role.ADMIN, "管理者"),
        ]
    )

    class Meta:
        model = User
        fields = (
            "last_name",
            "first_name",
            "username",
            "email",
            "role",
            "password1",
            "password2",
        )

    def __init__(self, *args, clinic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinic = clinic

    def save(self, commit=True):
        user = super().save(commit=False)

        if self.clinic is None:
            raise ValueError("clinic が未設定です。StaffCreateForm には clinic を渡してください。")

        user.last_name = self.cleaned_data["last_name"]
        user.first_name = self.cleaned_data["first_name"]
        user.email = self.cleaned_data["email"]
        user.role = self.cleaned_data["role"]
        user.clinic = self.clinic
        user.is_active = True
        user.is_staff = user.role == User.Role.ADMIN

        if commit:
            user.save()
        return user


class StaffMemberEditForm(forms.ModelForm):
    role = forms.ChoiceField(
        label="権限/ロール",
        choices=[
            (User.Role.ADMIN, "管理者"),
            (User.Role.RECEPTION, "受付"),
            (User.Role.PRACTITIONER, "施術者"),
        ],
    )

    class Meta:
        model = User
        fields = (
            "last_name",
            "first_name",
            "email",
            "role",
            "is_active",
        )
        labels = {
            "last_name": "姓",
            "first_name": "名",
            "email": "メールアドレス",
            "is_active": "有効",
        }
        widgets = {
            "last_name": forms.TextInput(attrs={"placeholder": "山田"}),
            "first_name": forms.TextInput(attrs={"placeholder": "太郎"}),
            "email": forms.EmailInput(attrs={"placeholder": "example@clinic.com"}),
        }

    def __init__(self, *args, clinic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinic = clinic

    def clean(self):
        cleaned_data = super().clean()
        if self.clinic is None:
            raise forms.ValidationError("院情報が取得できません。")
        if self.instance and self.instance.pk:
            if self.instance.clinic_id != self.clinic.id:
                raise forms.ValidationError("他院のスタッフは編集できません。")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.clinic is None:
            raise ValueError("StaffMemberEditFormにはclinicが必要です。")
        user.clinic = self.clinic
        user.is_staff = user.role == User.Role.ADMIN
        if commit:
            user.save()
        return user


class ClinicSettingsForm(forms.ModelForm):
    clinic_name = forms.CharField(
        label="院名",
        max_length=100,
        widget=forms.TextInput(attrs={"placeholder": "CareFrow整骨院"}),
    )
    closed_weekdays = forms.MultipleChoiceField(
        label="休診曜日",
        choices=ClinicSettings.WEEKDAY_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )

    class Meta:
        model = ClinicSettings
        fields = (
            "display_name",
            "phone",
            "address",
            "booking_description",
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
            "display_name": forms.TextInput(
                attrs={"placeholder": "予約画面などに表示する院名"}
            ),
            "phone": forms.TextInput(attrs={"placeholder": "03-1234-5678"}),
            "address": forms.TextInput(
                attrs={"placeholder": "東京都〇〇区〇〇 1-2-3"}
            ),
            "booking_description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "予約時の注意事項や患者様へのご案内",
                }
            ),
            "business_start_time": forms.TimeInput(
                attrs={"type": "time"},
                format="%H:%M",
            ),
            "business_end_time": forms.TimeInput(
                attrs={"type": "time"},
                format="%H:%M",
            ),
            "break_start_time": forms.TimeInput(
                attrs={"type": "time"},
                format="%H:%M",
            ),
            "break_end_time": forms.TimeInput(
                attrs={"type": "time"},
                format="%H:%M",
            ),
            "primary_color": forms.TextInput(
                attrs={"placeholder": "#1D4ED8", "data-color-input": "1"}
            ),
            "secondary_color": forms.TextInput(
                attrs={"placeholder": "#0F172A", "data-color-input": "1"}
            ),
            "accent_color": forms.TextInput(
                attrs={"placeholder": "#16A34A", "data-color-input": "1"}
            ),
        }

    def __init__(self, *args, clinic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinic = clinic or getattr(self.instance, "clinic", None)
        if self.clinic is not None:
            self.fields["clinic_name"].initial = self.clinic.name
        self.fields["closed_weekdays"].initial = (
            self.instance.closed_weekdays or []
            if self.instance and self.instance.pk
            else []
        )

    def clean(self):
        cleaned_data = super().clean()
        business_start = cleaned_data.get("business_start_time")
        business_end = cleaned_data.get("business_end_time")
        break_start = cleaned_data.get("break_start_time")
        break_end = cleaned_data.get("break_end_time")

        if business_start and business_end and business_start >= business_end:
            self.add_error(
                "business_end_time",
                "営業終了時刻は営業開始時刻より後にしてください。",
            )

        if bool(break_start) != bool(break_end):
            self.add_error(
                "break_end_time",
                "休憩時間を設定する場合は開始・終了の両方を入力してください。",
            )
        elif break_start and break_end:
            if break_start >= break_end:
                self.add_error(
                    "break_end_time",
                    "休憩終了時刻は休憩開始時刻より後にしてください。",
                )
            elif (
                business_start
                and business_end
                and (
                    break_start < business_start
                    or break_end > business_end
                )
            ):
                self.add_error(
                    "break_end_time",
                    "休憩時間は営業時間内に設定してください。",
                )

        return cleaned_data

    def save(self, commit=True):
        settings = super().save(commit=False)
        if self.clinic is None:
            raise ValueError("ClinicSettingsFormにはclinicが必要です。")
        settings.clinic = self.clinic
        settings.closed_weekdays = list(
            self.cleaned_data.get("closed_weekdays") or []
        )
        self.clinic.name = self.cleaned_data["clinic_name"]

        if commit:
            self.clinic.save(update_fields=["name"])
            settings.save()
        return settings


class TreatmentMenuForm(forms.ModelForm):
    class Meta:
        model = TreatmentMenu
        fields = (
            "name",
            "description",
            "price",
            "duration_minutes",
            "is_active",
            "display_order",
        )
        widgets = {
            "name": forms.TextInput(
                attrs={"placeholder": "例：全身調整 30分"}
            ),
            "description": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": (
                        "予約画面やスタッフ確認用の説明を入力してください。"
                    ),
                }
            ),
            "price": forms.NumberInput(attrs={"min": 0, "step": 1}),
            "duration_minutes": forms.NumberInput(
                attrs={"min": 5, "step": 5}
            ),
            "display_order": forms.NumberInput(attrs={"step": 1}),
        }

    def __init__(self, *args, clinic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinic = clinic or getattr(self.instance, "clinic", None)

    def clean_price(self):
        price = self.cleaned_data.get("price")
        if price is not None and price < 0:
            raise forms.ValidationError("料金は0円以上で入力してください。")
        return price

    def clean_duration_minutes(self):
        duration = self.cleaned_data.get("duration_minutes")
        if duration is None:
            return duration
        if duration < 5:
            raise forms.ValidationError("所要時間は5分以上で入力してください。")
        if duration % 5 != 0:
            raise forms.ValidationError("所要時間は5分単位で入力してください。")
        return duration

    def save(self, commit=True):
        menu = super().save(commit=False)
        if self.clinic is None:
            raise ValueError("TreatmentMenuFormにはclinicが必要です。")
        menu.clinic = self.clinic
        if commit:
            menu.save()
        return menu


class SalesRecordForm(forms.ModelForm):
    amount = forms.IntegerField(
        label="金額",
        required=False,
        min_value=0,
        widget=forms.NumberInput(attrs={"min": 0, "step": 1}),
    )

    class Meta:
        model = SalesRecord
        fields = (
            "patient",
            "appointment",
            "clinical_note",
            "treatment_menu",
            "staff",
            "treatment_date",
            "amount",
            "payment_method",
            "status",
            "memo",
        )
        widgets = {
            "treatment_date": forms.DateInput(attrs={"type": "date"}),
            "memo": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "会計時の補足や返金・キャンセル理由など",
                }
            ),
        }

    def __init__(self, *args, clinic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinic = clinic or getattr(self.instance, "clinic", None)
        if self.clinic is not None:
            self.instance.clinic = self.clinic
            self.fields["patient"].queryset = Patient.objects.filter(
                clinic=self.clinic,
            ).order_by("last_name", "first_name", "id")
            self.fields["appointment"].queryset = Appointment.objects.filter(
                clinic=self.clinic,
            ).select_related("patient").order_by("-start_at")
            self.fields["clinical_note"].queryset = ClinicalNote.objects.filter(
                patient__clinic=self.clinic,
            ).select_related("patient", "appointment").order_by("-created_at")
            self.fields["treatment_menu"].queryset = TreatmentMenu.objects.filter(
                clinic=self.clinic,
            ).order_by("-is_active", "display_order", "name", "id")
            self.fields["staff"].queryset = User.objects.filter(
                clinic=self.clinic,
                role__in=[
                    User.Role.ADMIN,
                    User.Role.RECEPTION,
                    User.Role.PRACTITIONER,
                ],
            ).order_by("last_name", "first_name", "username")

        self.fields["appointment"].required = False
        self.fields["clinical_note"].required = False
        self.fields["treatment_menu"].required = False
        self.fields["staff"].required = False
        self.fields["patient"].empty_label = "患者を選択"
        self.fields["appointment"].empty_label = "予約なし"
        self.fields["clinical_note"].empty_label = "カルテなし"
        self.fields["treatment_menu"].empty_label = "メニュー未選択"
        self.fields["staff"].empty_label = "担当者未選択"

    def clean(self):
        cleaned_data = super().clean()
        patient = cleaned_data.get("patient")
        appointment = cleaned_data.get("appointment")
        clinical_note = cleaned_data.get("clinical_note")
        treatment_menu = cleaned_data.get("treatment_menu")
        staff = cleaned_data.get("staff")
        amount = cleaned_data.get("amount")

        if self.clinic is None:
            raise forms.ValidationError("院情報が取得できません。")

        if patient and patient.clinic_id != self.clinic.id:
            self.add_error("patient", "他院の患者は選択できません。")

        if appointment:
            if appointment.clinic_id != self.clinic.id:
                self.add_error("appointment", "他院の予約は選択できません。")
            if (
                patient
                and appointment.patient_id
                and appointment.patient_id != patient.id
            ):
                self.add_error("appointment", "予約の患者と選択患者が一致していません。")

        if clinical_note:
            if clinical_note.patient.clinic_id != self.clinic.id:
                self.add_error("clinical_note", "他院のカルテは選択できません。")
            if patient and clinical_note.patient_id != patient.id:
                self.add_error("clinical_note", "カルテの患者と選択患者が一致していません。")

        if treatment_menu and treatment_menu.clinic_id != self.clinic.id:
            self.add_error("treatment_menu", "他院の施術メニューは選択できません。")

        if staff and staff.clinic_id != self.clinic.id:
            self.add_error("staff", "他院の担当者は選択できません。")

        if amount is None:
            if treatment_menu:
                cleaned_data["amount"] = treatment_menu.price
            else:
                self.add_error("amount", "金額を入力してください。")

        return cleaned_data

    def save(self, commit=True):
        record = super().save(commit=False)
        if self.clinic is None:
            raise ValueError("SalesRecordFormにはclinicが必要です。")
        record.clinic = self.clinic
        record.amount = self.cleaned_data["amount"]
        if commit:
            record.save()
        return record


class StaffShiftForm(forms.ModelForm):
    class Meta:
        model = StaffShift
        fields = (
            "staff",
            "date",
            "status",
            "start_time",
            "end_time",
            "break_start",
            "break_end",
            "memo",
        )
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "break_start": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "break_end": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "memo": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "シフトに関する補足、研修内容、予約枠調整メモなど",
                }
            ),
        }

    def __init__(self, *args, clinic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinic = clinic or getattr(self.instance, "clinic", None)
        if self.clinic is not None:
            self.instance.clinic = self.clinic
        for field_name in ("start_time", "end_time", "break_start", "break_end"):
            self.fields[field_name].input_formats = ["%H:%M", "%H:%M:%S"]

        if self.clinic is not None:
            staff_roles = [
                User.Role.ADMIN,
                User.Role.RECEPTION,
                User.Role.PRACTITIONER,
            ]
            staff_filter = Q(
                clinic=self.clinic,
                is_active=True,
                role__in=staff_roles,
            )
            if self.instance and self.instance.pk and self.instance.staff_id:
                staff_filter |= Q(pk=self.instance.staff_id, clinic=self.clinic)
            self.fields["staff"].queryset = (
                User.objects
                .filter(staff_filter)
                .order_by("-is_active", "last_name", "first_name", "username")
                .distinct()
            )
        else:
            self.fields["staff"].queryset = User.objects.none()

        self.fields["staff"].empty_label = "スタッフを選択"

    def clean(self):
        cleaned_data = super().clean()
        staff = cleaned_data.get("staff")
        shift_date = cleaned_data.get("date")
        status = cleaned_data.get("status")
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")
        break_start = cleaned_data.get("break_start")
        break_end = cleaned_data.get("break_end")

        if self.clinic is None:
            raise forms.ValidationError("院情報が取得できません。")

        if staff and staff.clinic_id != self.clinic.id:
            self.add_error("staff", "他院のスタッフは選択できません。")

        if status != StaffShift.Status.OFF:
            if not start_time:
                self.add_error("start_time", "休み以外では勤務開始時刻を入力してください。")
            if not end_time:
                self.add_error("end_time", "休み以外では勤務終了時刻を入力してください。")

        if start_time and end_time and start_time >= end_time:
            self.add_error("end_time", "勤務終了時刻は勤務開始時刻より後にしてください。")

        if bool(break_start) != bool(break_end):
            self.add_error("break_end", "休憩時間を設定する場合は開始・終了の両方を入力してください。")
        elif break_start and break_end:
            if break_start >= break_end:
                self.add_error("break_end", "休憩終了時刻は休憩開始時刻より後にしてください。")
            elif start_time and end_time and (
                break_start < start_time
                or break_end > end_time
            ):
                self.add_error("break_end", "休憩時間は勤務時間内に設定してください。")

        if staff and shift_date:
            duplicate = StaffShift.objects.filter(
                clinic=self.clinic,
                staff=staff,
                date=shift_date,
            )
            if self.instance and self.instance.pk:
                duplicate = duplicate.exclude(pk=self.instance.pk)
            if duplicate.exists():
                self.add_error("date", "同じスタッフ・日付のシフトはすでに登録されています。")

        return cleaned_data

    def save(self, commit=True):
        shift = super().save(commit=False)
        if self.clinic is None:
            raise ValueError("StaffShiftFormにはclinicが必要です。")
        shift.clinic = self.clinic
        if commit:
            shift.full_clean()
            shift.save()
        return shift


class StaffLeaveForm(forms.ModelForm):
    class Meta:
        model = StaffLeave
        fields = (
            "staff",
            "leave_type",
            "start_date",
            "end_date",
            "start_time",
            "end_time",
            "status",
            "reason",
            "memo",
        )
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "start_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "end_time": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
            "reason": forms.TextInput(
                attrs={"placeholder": "例：私用、体調不良、研修参加など"}
            ),
            "memo": forms.Textarea(
                attrs={
                    "rows": 4,
                    "placeholder": "予約枠調整やスタッフ間共有用の補足",
                }
            ),
        }

    def __init__(self, *args, clinic=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.clinic = clinic or getattr(self.instance, "clinic", None)
        if self.clinic is not None:
            self.instance.clinic = self.clinic
        for field_name in ("start_time", "end_time"):
            self.fields[field_name].input_formats = ["%H:%M", "%H:%M:%S"]

        if self.clinic is not None:
            staff_roles = [
                User.Role.ADMIN,
                User.Role.RECEPTION,
                User.Role.PRACTITIONER,
            ]
            staff_filter = Q(
                clinic=self.clinic,
                is_active=True,
                role__in=staff_roles,
            )
            if self.instance and self.instance.pk and self.instance.staff_id:
                staff_filter |= Q(pk=self.instance.staff_id, clinic=self.clinic)
            self.fields["staff"].queryset = (
                User.objects
                .filter(staff_filter)
                .order_by("-is_active", "last_name", "first_name", "username")
                .distinct()
            )
        else:
            self.fields["staff"].queryset = User.objects.none()

        self.fields["staff"].empty_label = "スタッフを選択"

    def clean(self):
        cleaned_data = super().clean()
        staff = cleaned_data.get("staff")
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")
        start_time = cleaned_data.get("start_time")
        end_time = cleaned_data.get("end_time")

        if self.clinic is None:
            raise forms.ValidationError("院情報が取得できません。")

        if staff and staff.clinic_id != self.clinic.id:
            self.add_error("staff", "他院のスタッフは選択できません。")

        if start_date and end_date and start_date > end_date:
            self.add_error("end_date", "終了日は開始日以降にしてください。")

        if bool(start_time) != bool(end_time):
            self.add_error("end_time", "時間帯を設定する場合は開始・終了の両方を入力してください。")
        elif start_time and end_time and start_time >= end_time:
            self.add_error("end_time", "終了時刻は開始時刻より後にしてください。")

        return cleaned_data

    def save(self, commit=True):
        leave = super().save(commit=False)
        if self.clinic is None:
            raise ValueError("StaffLeaveFormにはclinicが必要です。")
        leave.clinic = self.clinic
        if commit:
            leave.full_clean()
            leave.save()
        return leave

def _list_to_text(value):
    """
    list / dict / str が混在しても、編集フォーム用のテキストに安全変換する。
    dict は [type] text 形式にして、後で復元しやすくする。
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        text = value.get("text") or value.get("label") or value.get("value")
        item_type = value.get("type", "")

        if text:
            return f"[{item_type}] {text}" if item_type else str(text)

        return str(value)

    if isinstance(value, list):
        lines = []

        for item in value:
            if item is None:
                continue

            if isinstance(item, str):
                if item.strip():
                    lines.append(item.strip())
                continue

            if isinstance(item, dict):
                text = item.get("text") or item.get("label") or item.get("value")
                item_type = item.get("type", "")

                if text:
                    lines.append(f"[{item_type}] {text}" if item_type else str(text))
                else:
                    lines.append(str(item))
                continue

            lines.append(str(item))

        return "\n".join(lines)

    return str(value)


def _text_to_list(value):
    """
    複数行テキストを list[str] に戻す。
    """
    if not value:
        return []

    return [
        line.strip()
        for line in str(value).splitlines()
        if line.strip()
    ]


def _text_to_followups(value):
    """
    [next_check] xxx のような行は dict に戻す。
    それ以外は通常の followup として dict 化する。
    """
    rows = _text_to_list(value)
    results = []

    for row in rows:
        if row.startswith("[") and "]" in row:
            item_type, text = row.split("]", 1)
            item_type = item_type.replace("[", "").strip()
            text = text.strip()

            if text:
                results.append({
                    "type": item_type or "followup",
                    "text": text,
                })
            continue

        results.append({
            "type": "followup",
            "text": row,
        })

    return results


def _safe_choice_value(value, choices, default=""):
    """
    choices に存在しない値が入っていてもフォームを壊さないための保険。
    """
    valid_values = {str(choice[0]) for choice in choices}
    value = "" if value is None else str(value)
    return value if value in valid_values else default

class ClinicalNoteEditForm(forms.Form):
    # SOAP
    soap_s = forms.CharField(
        label="S",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5, "class": "form-control"}),
    )
    soap_o = forms.CharField(
        label="O",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5, "class": "form-control"}),
    )
    soap_a = forms.CharField(
        label="A",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5, "class": "form-control"}),
    )
    soap_p = forms.CharField(
        label="P",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5, "class": "form-control"}),
    )

    # extract
    chief_complaint = forms.CharField(
        label="主訴",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    onset = forms.CharField(
        label="発症",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    trigger = forms.CharField(
        label="きっかけ",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    severity_0_10 = forms.CharField(
        label="痛み(0-10)",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    locations = forms.CharField(
        label="部位",
        required=False,
        help_text="複数ある場合は改行区切り",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
    )
    qualities = forms.CharField(
        label="性状",
        required=False,
        help_text="複数ある場合は改行区切り",
        widget=forms.Textarea(attrs={"rows": 3, "class": "form-control"}),
    )
    symptom_type = forms.ChoiceField(
        label="急性/慢性・来院種別",
        required=False,
        choices=SYMPTOM_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # followups
    followups = forms.CharField(
        label="追加確認事項",
        required=False,
        help_text="1行に1件ずつ入力。例：[next_check] 右膝の荷重時痛を確認",
        widget=forms.Textarea(attrs={"rows": 6, "class": "form-control"}),
    )

    def __init__(self, *args, note=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.note = note
        self.base_extract = {}
        self.base_web_intake_snapshot = {}

        if note is not None:
            self.base_extract = note.extract_json or {}
            self.base_web_intake_snapshot = note.web_intake_snapshot or {}

    def _split_lines(self, value: str):
        return _text_to_list(value)

    def build_payload(self):
        """
        編集フォームの内容から ClinicalNote 保存用 payload を作る。

        重要:
        - 施術セッション由来の extract_json には important_points / progress_change などがある
        - それを消さないように、既存 extract をベースに編集項目だけ上書きする
        """
        cd = self.cleaned_data

        soap = {
            "S": _text_to_list(cd.get("soap_s")),
            "O": _text_to_list(cd.get("soap_o")),
            "A": _text_to_list(cd.get("soap_a")),
            "P": _text_to_list(cd.get("soap_p")),
        }

        extract = dict(self.base_extract or {})

        locations = _text_to_list(cd.get("locations"))
        qualities = _text_to_list(cd.get("qualities"))

        extract.update({
            "chief_complaint": cd.get("chief_complaint", "") or "",
            "onset": cd.get("onset", "") or "",
            "trigger": cd.get("trigger", "") or "",
            "severity_0_10": cd.get("severity_0_10", "") or "",
            "locations": locations,
            "qualities": qualities,
        })

        symptom_type = cd.get("symptom_type") or ""

        if symptom_type:
            # 既存の visit_type は残しつつ、通常カルテ互換の symptom_type も保持
            if symptom_type == "followup":
                extract["visit_type"] = "followup"
                extract["symptom_type"] = extract.get("symptom_type") or "unknown"
            else:
                extract["symptom_type"] = symptom_type
        else:
            extract["symptom_type"] = extract.get("symptom_type") or "unknown"

        # 施術セッション由来の場合、pain_areas / checked_areas 側にも最低限同期
        if extract.get("source") == "treatment_session":
            if locations:
                extract["pain_areas"] = locations

        followups = _text_to_followups(cd.get("followups"))

        return {
            "soap": soap,
            "extract": extract,
            "followups": followups,
        }

    @classmethod
    def from_note(cls, note):
        soap = note.soap_json or {}
        extract = note.extract_json or {}
        followups = note.followups_json or []

        locations = (
            extract.get("locations")
            or extract.get("pain_areas")
            or extract.get("checked_areas")
            or []
        )

        qualities = extract.get("qualities") or []

        symptom_or_visit_type = (
            extract.get("symptom_type")
            or extract.get("visit_type")
            or ""
        )

        symptom_or_visit_type = _safe_choice_value(
            symptom_or_visit_type,
            SYMPTOM_TYPE_CHOICES,
            default="unknown",
        )

        initial = {
            "soap_s": _list_to_text(soap.get("S")),
            "soap_o": _list_to_text(soap.get("O")),
            "soap_a": _list_to_text(soap.get("A")),
            "soap_p": _list_to_text(soap.get("P")),

            "chief_complaint": extract.get("chief_complaint", ""),
            "onset": extract.get("onset", ""),
            "trigger": extract.get("trigger", ""),
            "severity_0_10": extract.get("severity_0_10", ""),
            "locations": _list_to_text(locations),
            "qualities": _list_to_text(qualities),
            "symptom_type": symptom_or_visit_type,

            "followups": _list_to_text(followups),
        }

        return cls(note=note, initial=initial)
