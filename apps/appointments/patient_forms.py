# apps/appointments/patient_forms.py
from django import forms
from django.utils import timezone

from apps.intakes.models import Intake


class PatientLookupForm(forms.Form):
    last_name = forms.CharField(label="姓", max_length=30)
    first_name = forms.CharField(label="名", max_length=30)
    phone = forms.CharField(label="電話番号", max_length=30)

    def clean_last_name(self):
        return (self.cleaned_data["last_name"] or "").strip()

    def clean_first_name(self):
        return (self.cleaned_data["first_name"] or "").strip()

    def clean_phone(self):
        phone = self.cleaned_data["phone"] or ""
        normalized = "".join(ch for ch in phone if ch.isdigit())
        if not normalized:
            raise forms.ValidationError("電話番号を入力してください。")
        return normalized


class AppointmentCreateForm(forms.Form):
    start_at = forms.DateTimeField(
        label="希望日時",
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
    )
    duration_min = forms.TypedChoiceField(
        label="施術時間（分）",
        choices=[(30, "30分"), (45, "45分"), (60, "60分")],
        coerce=int,
        initial=45,
    )
    menu = forms.ChoiceField(
        label="メニュー",
        choices=[("初診", "初診"), ("再診", "再診"), ("整体", "整体")],
        initial="初診",
    )

    def clean_start_at(self):
        dt = self.cleaned_data["start_at"]
        if dt < timezone.now():
            raise forms.ValidationError("過去の日時は選択できません。")
        return dt


class IntakeForm(forms.ModelForm):
    class Meta:
        model = Intake
        fields = ["chief_complaint", "symptom_type"]