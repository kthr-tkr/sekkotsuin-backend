from django import forms
from django.contrib.auth import get_user_model
from apps.clinics.models import Clinic
from .models import Patient
from django.contrib.auth.forms import PasswordResetForm, SetPasswordForm

User = get_user_model()


class PatientLoginForm(forms.Form):
    card_number = forms.CharField(
        label="診察券番号",
        max_length=50,
        widget=forms.TextInput(attrs={"placeholder": "例: P12345"}),
    )
    phone = forms.CharField(
        label="電話番号",
        max_length=30,
        widget=forms.TextInput(attrs={"placeholder": "例: 090-1234-5678"}),
    )


BASE_ATTRS = {"class": "", "autocomplete": "off"}  # class は未使用でもOK


class PatientRegisterForm(forms.Form):
    password = forms.CharField(label="パスワード", widget=forms.PasswordInput)
    email = forms.EmailField(label="メールアドレス")

    last_name = forms.CharField(label="姓", max_length=50)
    first_name = forms.CharField(label="名", max_length=50)
    last_name_kana = forms.CharField(label="セイ", max_length=50)
    first_name_kana = forms.CharField(label="メイ", max_length=50)

    birth_date = forms.DateField(
        label="生年月日",
        widget=forms.DateInput(attrs={"type": "date"})
    )
    phone = forms.CharField(label="電話番号", max_length=20)
    address = forms.CharField(label="住所", max_length=255, required=False)

    def clean_email(self):
        email = (self.cleaned_data["email"] or "").strip().lower()
        if not email:
            raise forms.ValidationError("メールアドレスを入力してください。")

        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError("このメールアドレスは既に使用されています。")

        return email

    def clean_last_name(self):
        return (self.cleaned_data["last_name"] or "").strip()

    def clean_first_name(self):
        return (self.cleaned_data["first_name"] or "").strip()

    def clean_last_name_kana(self):
        return (self.cleaned_data["last_name_kana"] or "").strip()

    def clean_first_name_kana(self):
        return (self.cleaned_data["first_name_kana"] or "").strip()

    def clean_phone(self):
        phone = self.cleaned_data["phone"] or ""
        normalized = "".join(ch for ch in phone if ch.isdigit())

        if not normalized:
            raise forms.ValidationError("電話番号を入力してください。")

        if len(normalized) < 10 or len(normalized) > 11:
            raise forms.ValidationError("正しい電話番号を入力してください。")

        return normalized


class PatientProfileForm(forms.ModelForm):
    email = forms.EmailField(
        label="メールアドレス",
        required=True,
        widget=forms.EmailInput(attrs={
            "class": "profile-input",
            "placeholder": "example@example.com",
            "autocomplete": "email",
        }),
    )

    class Meta:
        model = Patient
        fields = [
            "last_name",
            "first_name",
            "last_name_kana",
            "first_name_kana",
            "phone",
            "address",
            "birth_date",
        ]
        widgets = {
            "last_name": forms.TextInput(attrs={
                "class": "profile-input",
                "placeholder": "姓",
            }),
            "first_name": forms.TextInput(attrs={
                "class": "profile-input",
                "placeholder": "名",
            }),
            "last_name_kana": forms.TextInput(attrs={
                "class": "profile-input",
                "placeholder": "セイ",
            }),
            "first_name_kana": forms.TextInput(attrs={
                "class": "profile-input",
                "placeholder": "メイ",
            }),
            "phone": forms.TextInput(attrs={
                "class": "profile-input",
                "placeholder": "09012345678",
            }),
            "address": forms.TextInput(attrs={
                "class": "profile-input",
                "placeholder": "住所を入力",
            }),
            "birth_date": forms.DateInput(attrs={
                "class": "profile-input",
                "type": "date",
            }),
        }
        labels = {
            "last_name": "姓",
            "first_name": "名",
            "last_name_kana": "セイ",
            "first_name_kana": "メイ",
            "phone": "電話番号",
            "address": "住所",
            "birth_date": "生年月日",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields["email"].initial = self.instance.user.email

    def clean_email(self):
        email = (self.cleaned_data["email"] or "").strip().lower()
        if not email:
            raise forms.ValidationError("メールアドレスを入力してください。")

        qs = User.objects.filter(email__iexact=email)
        if self.instance and self.instance.user_id:
            qs = qs.exclude(pk=self.instance.user_id)

        if qs.exists():
            raise forms.ValidationError("このメールアドレスは既に使用されています。")

        return email

    def clean_phone(self):
        phone = self.cleaned_data["phone"] or ""
        normalized = "".join(ch for ch in phone if ch.isdigit())

        if not normalized:
            raise forms.ValidationError("電話番号を入力してください。")

        if len(normalized) < 10 or len(normalized) > 11:
            raise forms.ValidationError("正しい電話番号を入力してください。")

        return normalized

    def save(self, commit=True):
        patient = super().save(commit=False)

        if commit:
            patient.save()

        if patient.user:
            patient.user.email = self.cleaned_data["email"]
            if commit:
                patient.user.save(update_fields=["email"])

        return patient


class PatientPasswordResetForm(PasswordResetForm):
    email = forms.EmailField(
        label="メールアドレス",
        widget=forms.EmailInput(attrs={
            "class": "auth-input",
            "placeholder": "ご登録のメールアドレス",
            "autocomplete": "email",
        }),
    )

    def clean_email(self):
        email = (self.cleaned_data["email"] or "").strip().lower()
        return email


class PatientSetPasswordForm(SetPasswordForm):
    new_password1 = forms.CharField(
        label="新しいパスワード",
        strip=False,
        widget=forms.PasswordInput(attrs={
            "class": "auth-input",
            "placeholder": "新しいパスワード",
            "autocomplete": "new-password",
        }),
    )
    new_password2 = forms.CharField(
        label="新しいパスワード（確認）",
        strip=False,
        widget=forms.PasswordInput(attrs={
            "class": "auth-input",
            "placeholder": "もう一度入力してください",
            "autocomplete": "new-password",
        }),
    )