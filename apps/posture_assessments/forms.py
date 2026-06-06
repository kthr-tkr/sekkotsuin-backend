from django import forms

from .models import PostureAssessment, PostureAssessmentImage, PostureComparison


class PostureAssessmentCreateForm(forms.ModelForm):
    class Meta:
        model = PostureAssessment
        fields = ["title", "memo"]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "例）AI姿勢分析",
            }),
            "memo": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "例）右膝痛あり。バスケット後に痛みが出る。",
            }),
        }


class PostureAssessmentImageUploadForm(forms.Form):
    front_image = forms.ImageField(
        label="正面",
        required=False,
        widget=forms.FileInput(attrs={
            "accept": "image/*",
            "capture": "environment",
            "class": "form-control",
        }),
    )

    side_right_image = forms.ImageField(
        label="右側面",
        required=False,
        widget=forms.FileInput(attrs={
            "accept": "image/*",
            "capture": "environment",
            "class": "form-control",
        }),
    )

    back_image = forms.ImageField(
        label="背面",
        required=False,
        widget=forms.FileInput(attrs={
            "accept": "image/*",
            "capture": "environment",
            "class": "form-control",
        }),
    )

    def has_any_image(self):
        cd = self.cleaned_data
        return bool(
            cd.get("front_image")
            or cd.get("side_right_image")
            or cd.get("back_image")
        )
        
class PostureComparisonCreateForm(forms.ModelForm):
    before_assessment = forms.ModelChoiceField(
        queryset=PostureAssessment.objects.none(),
        label="Before",
        empty_label="Beforeにする姿勢分析を選択してください",
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
    )

    after_assessment = forms.ModelChoiceField(
        queryset=PostureAssessment.objects.none(),
        label="After",
        empty_label="Afterにする姿勢分析を選択してください",
        widget=forms.Select(attrs={
            "class": "form-control",
        }),
    )

    class Meta:
        model = PostureComparison
        fields = [
            "title",
            "before_assessment",
            "after_assessment",
            "memo",
        ]
        widgets = {
            "title": forms.TextInput(attrs={
                "class": "form-control",
                "placeholder": "例）初回施術前後の姿勢比較",
            }),
            "memo": forms.Textarea(attrs={
                "class": "form-control",
                "rows": 4,
                "placeholder": "例）初回施術前と施術後の比較。右膝痛の変化を確認。",
            }),
        }

    def __init__(self, *args, clinic=None, patient=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.clinic = clinic
        self.patient = patient

        assessments = (
            PostureAssessment.objects
            .filter(
                clinic=clinic,
                patient=patient,
            )
            .prefetch_related("images")
            .order_by("-created_at")
        )

        self.fields["before_assessment"].queryset = assessments
        self.fields["after_assessment"].queryset = assessments

        self.fields["before_assessment"].label_from_instance = self._assessment_label
        self.fields["after_assessment"].label_from_instance = self._assessment_label

    def _assessment_label(self, obj):
        image_count = obj.images.count()
        return f"{obj.created_at:%Y-%m-%d %H:%M} / {obj.title} / {obj.get_status_display()} / 画像{image_count}枚"

    def clean(self):
        cleaned_data = super().clean()

        before = cleaned_data.get("before_assessment")
        after = cleaned_data.get("after_assessment")

        if before and after and before.id == after.id:
            raise forms.ValidationError("BeforeとAfterには別の姿勢分析を選択してください。")

        if before and self.patient and before.patient_id != self.patient.id:
            raise forms.ValidationError("Before分析の患者が一致していません。")

        if after and self.patient and after.patient_id != self.patient.id:
            raise forms.ValidationError("After分析の患者が一致していません。")

        if before and self.clinic and before.clinic_id != self.clinic.id:
            raise forms.ValidationError("Before分析の院情報が一致していません。")

        if after and self.clinic and after.clinic_id != self.clinic.id:
            raise forms.ValidationError("After分析の院情報が一致していません。")

        return cleaned_data