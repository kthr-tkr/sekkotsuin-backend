from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm

User = get_user_model()

SYMPTOM_TYPE_CHOICES = [
    ("", "選択してください"),
    ("acute", "急性"),
    ("chronic", "慢性"),
    ("unknown", "不明"),
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
        label="急性/慢性",
        required=False,
        choices=SYMPTOM_TYPE_CHOICES,
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    # followups
    followups = forms.CharField(
        label="追加質問",
        required=False,
        help_text="1行に1件ずつ入力",
        widget=forms.Textarea(attrs={"rows": 6, "class": "form-control"}),
    )

    def _split_lines(self, value: str):
        if not value:
            return []
        return [line.strip() for line in value.splitlines() if line.strip()]

    def build_payload(self):
        cd = self.cleaned_data

        return {
            "soap": {
                "S": self._split_lines(cd.get("soap_s", "")),
                "O": self._split_lines(cd.get("soap_o", "")),
                "A": self._split_lines(cd.get("soap_a", "")),
                "P": self._split_lines(cd.get("soap_p", "")),
            },
            "extract": {
                "chief_complaint": cd.get("chief_complaint", "") or "",
                "onset": cd.get("onset", "") or "",
                "trigger": cd.get("trigger", "") or "",
                "severity_0_10": cd.get("severity_0_10", "") or "",
                "locations": self._split_lines(cd.get("locations", "")),
                "qualities": self._split_lines(cd.get("qualities", "")),
                "symptom_type": cd.get("symptom_type", "") or "unknown",
            },
            "followups": self._split_lines(cd.get("followups", "")),
        }

    @classmethod
    def from_note(cls, note):
        soap = note.soap_json or {}
        extract = note.extract_json or {}
        followups = note.followups_json or []

        initial = {
            "soap_s": "\n".join(soap.get("S", [])),
            "soap_o": "\n".join(soap.get("O", [])),
            "soap_a": "\n".join(soap.get("A", [])),
            "soap_p": "\n".join(soap.get("P", [])),
            "chief_complaint": extract.get("chief_complaint", ""),
            "onset": extract.get("onset", ""),
            "trigger": extract.get("trigger", ""),
            "severity_0_10": extract.get("severity_0_10", ""),
            "locations": "\n".join(extract.get("locations", [])),
            "qualities": "\n".join(extract.get("qualities", [])),
            "symptom_type": extract.get("symptom_type", "") or "unknown",
            "followups": "\n".join(followups),
        }
        return cls(initial=initial)