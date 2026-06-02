from django import forms

from .models import PostureAssessment, PostureAssessmentImage


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