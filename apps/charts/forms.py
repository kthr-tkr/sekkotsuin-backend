from django import forms
from .models import ChartNote

class ChartNoteForm(forms.ModelForm):
    class Meta:
        model = ChartNote
        fields = ["subjective_text", "objective_text", "assessment_text", "plan_text"]
        widgets = {
            "subjective_text": forms.Textarea(attrs={"rows": 6}),
            "objective_text": forms.Textarea(attrs={"rows": 6}),
            "assessment_text": forms.Textarea(attrs={"rows": 6}),
            "plan_text": forms.Textarea(attrs={"rows": 6}),
        }
