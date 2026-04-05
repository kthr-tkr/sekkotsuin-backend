from django import forms
from .models import TreatmentPlan, TreatmentProgress


class TreatmentPlanForm(forms.ModelForm):
    class Meta:
        model = TreatmentPlan
        fields = [
            "title",
            "chief_complaint",
            "next_visit_date",
            "visit_guide_type",
            "visit_guide_count",
            "visit_guide_unit_note",
            "bath_instruction",
            "walking_instruction",
            "exercise_instruction",
            "work_instruction",
            "lifestyle_other_instruction",
            "caution_notes",
            "expected_recovery_weeks_min",
            "expected_recovery_weeks_max",
            "rebound_reaction_note",
            "explained_to_patient",
            "is_active",
            "status",
        ]
        widgets = {
            "title": forms.TextInput(attrs={"class": "form-control", "placeholder": "例：腰痛施術計画"}),
            "chief_complaint": forms.TextInput(attrs={"class": "form-control", "placeholder": "主訴"}),
            "next_visit_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),

            "visit_guide_type": forms.Select(attrs={"class": "form-select"}),
            "visit_guide_count": forms.NumberInput(attrs={"class": "form-control", "placeholder": "回数"}),
            "visit_guide_unit_note": forms.TextInput(attrs={"class": "form-control", "placeholder": "例：炎症期は毎日、その後は週2回"}),

            "bath_instruction": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "walking_instruction": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "exercise_instruction": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "work_instruction": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "lifestyle_other_instruction": forms.Textarea(attrs={"class": "form-control", "rows": 3}),

            "caution_notes": forms.Textarea(attrs={"class": "form-control", "rows": 4}),

            "expected_recovery_weeks_min": forms.NumberInput(attrs={"class": "form-control", "placeholder": "最短"}),
            "expected_recovery_weeks_max": forms.NumberInput(attrs={"class": "form-control", "placeholder": "最長"}),

            "rebound_reaction_note": forms.Textarea(attrs={"class": "form-control", "rows": 4}),

            "explained_to_patient": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "is_active": forms.CheckboxInput(attrs={"class": "form-check-input"}),
            "status": forms.Select(attrs={"class": "form-select"}),
        }
        labels = {
            "title": "計画タイトル",
            "chief_complaint": "主訴",
            "next_visit_date": "次回来院日",
            "visit_guide_type": "来院目安区分",
            "visit_guide_count": "来院回数目安",
            "visit_guide_unit_note": "来院目安補足",
            "bath_instruction": "入浴について",
            "walking_instruction": "歩行について",
            "exercise_instruction": "運動について",
            "work_instruction": "就労について",
            "lifestyle_other_instruction": "日常生活その他",
            "caution_notes": "その他注意事項",
            "expected_recovery_weeks_min": "改善目安（最短週）",
            "expected_recovery_weeks_max": "改善目安（最長週）",
            "rebound_reaction_note": "好転反応の説明",
            "explained_to_patient": "患者へ説明済み",
            "is_active": "有効な計画",
            "status": "計画ステータス",
        }


class TreatmentProgressForm(forms.ModelForm):
    class Meta:
        model = TreatmentProgress
        fields = [
            "visit_date",
            "pain_level",
            "symptom_change",
            "adl_status",
            "treatment_detail",
            "post_treatment_response",
            "next_instruction",
            "memo",
        ]
        widgets = {
            "visit_date": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "pain_level": forms.NumberInput(attrs={"class": "form-control", "min": 0, "max": 10}),
            "symptom_change": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "adl_status": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "treatment_detail": forms.Textarea(attrs={"class": "form-control", "rows": 4}),
            "post_treatment_response": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "next_instruction": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "memo": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
        }
        labels = {
            "visit_date": "施術日",
            "pain_level": "痛みレベル",
            "symptom_change": "症状変化",
            "adl_status": "ADL・生活状況",
            "treatment_detail": "施術内容",
            "post_treatment_response": "施術後の反応",
            "next_instruction": "次回までの指示",
            "memo": "備考",
        }