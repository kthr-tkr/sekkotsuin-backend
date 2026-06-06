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
    front_image = forms.FileField(
        label="正面",
        required=False,
        widget=forms.FileInput(attrs={
            "accept": ".jpg,.jpeg,.png,.webp,.heic,.heif,image/jpeg,image/png,image/webp,image/heic,image/heif",
            "capture": "environment",
            "class": "form-control",
        }),
    )

    side_right_image = forms.FileField(
        label="右側面",
        required=False,
        widget=forms.FileInput(attrs={
            "accept": ".jpg,.jpeg,.png,.webp,.heic,.heif,image/jpeg,image/png,image/webp,image/heic,image/heif",
            "capture": "environment",
            "class": "form-control",
        }),
    )

    back_image = forms.FileField(
        label="背面",
        required=False,
        widget=forms.FileInput(attrs={
            "accept": ".jpg,.jpeg,.png,.webp,.heic,.heif,image/jpeg,image/png,image/webp,image/heic,image/heif",
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

        if clinic is None or patient is None:
            assessments = PostureAssessment.objects.none()
        else:
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
        created_text = obj.created_at.strftime("%Y-%m-%d %H:%M") if obj.created_at else "-"
        return f"{created_text} / {obj.title} / {obj.get_status_display()} / 画像{image_count}枚"

    def clean(self):
        cleaned_data = super().clean()

        before = cleaned_data.get("before_assessment")
        after = cleaned_data.get("after_assessment")

        if not self.clinic or not self.patient:
            raise forms.ValidationError("院情報または患者情報を取得できませんでした。")

        if before and after and before.id == after.id:
            raise forms.ValidationError("BeforeとAfterには別の姿勢分析を選択してください。")

        if before:
            if before.clinic_id != self.clinic.id:
                self.add_error("before_assessment", "Before分析の院情報が一致していません。")

            if before.patient_id != self.patient.id:
                self.add_error("before_assessment", "Before分析の患者と比較対象の患者が一致していません。")

        if after:
            if after.clinic_id != self.clinic.id:
                self.add_error("after_assessment", "After分析の院情報が一致していません。")

            if after.patient_id != self.patient.id:
                self.add_error("after_assessment", "After分析の患者と比較対象の患者が一致していません。")

        return cleaned_data