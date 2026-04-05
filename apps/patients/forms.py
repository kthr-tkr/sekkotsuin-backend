from django import forms
from apps.clinics.models import Clinic
from .models import Patient

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
    username = forms.CharField(label="ログインID", max_length=150)
    password = forms.CharField(label="パスワード", widget=forms.PasswordInput)

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

    def clean_username(self):
        return (self.cleaned_data["username"] or "").strip()

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
    def clean_phone(self):
        phone = self.cleaned_data["phone"]

        if not phone.isdigit():
            raise forms.ValidationError("電話番号は数字のみで入力してください")

        if len(phone) < 10 or len(phone) > 11:
            raise forms.ValidationError("正しい電話番号を入力してください")

        return phone