from django import forms
from .models import Intake

SYMPTOM_LOCATIONS = [
    ("neck", "首"), ("shoulder", "肩"), ("low_back", "腰"), ("knee", "膝"), ("other", "その他"),
]

PAIN_QUALITIES = [
    ("sharp", "ズキズキ"),
    ("dull", "重だるい"),
    ("stiff", "こわばり"),
    ("tingle", "しびれ"),
    ("hot", "熱っぽい"),
    ("swelling", "腫れ"),
    ("other", "その他"),
]

class IntakeAdminForm(forms.ModelForm):
    consent_agreed = forms.BooleanField(required=True, label="個人情報の取り扱いに同意します")
    locations = forms.MultipleChoiceField(
        required=False, choices=SYMPTOM_LOCATIONS, widget=forms.CheckboxSelectMultiple, label="痛む場所"
    )
    severity = forms.IntegerField(required=False, min_value=0, max_value=10, label="痛みの強さ（0〜10）")
    qualities = forms.MultipleChoiceField(
        required=False, choices=PAIN_QUALITIES, widget=forms.CheckboxSelectMultiple, label="症状の感じ"
    )
    free_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 4, "class": "intake-textarea"}),
        label="その他（自由記入）"
    )

    class Meta:
        model = Intake
        fields = ["chief_complaint", "symptom_type", "onset"]

    def clean(self):
        cleaned = super().clean()
        return cleaned

    def apply_payload(self, intake: Intake):
        payload = intake.payload or {}
        payload["consent"] = {
            "agreed": bool(self.cleaned_data.get("consent_agreed")),
        }
        payload["symptoms"] = {
            "location": self.cleaned_data.get("locations") or [],
            "severity": self.cleaned_data.get("severity"),
            "quality": self.cleaned_data.get("qualities") or [],
        }
        payload["free_text"] = self.cleaned_data.get("free_text", "")
        intake.payload = payload

    @classmethod
    def initial_from_payload(cls, intake: Intake):
        p = intake.payload or {}
        return {
            "consent_agreed": (p.get("consent", {}) or {}).get("agreed", False),
            "locations": (p.get("symptoms", {}) or {}).get("location", []),
            "severity": (p.get("symptoms", {}) or {}).get("severity", None),
            "qualities": (p.get("symptoms", {}) or {}).get("quality", []),
            "free_text": p.get("free_text", ""),
        }


# --- Step1 ---
SOURCE_CHOICES = [
    ("web", "Web検索"),
    ("intro", "紹介"),
    ("sign", "看板"),
    ("sns", "SNS"),
    ("other", "その他"),
]

class IntakeStep1Form(forms.Form):
    confirm_profile = forms.BooleanField(required=True, label="登録情報に間違いありません")
    source = forms.ChoiceField(
        required=False,
        choices=SOURCE_CHOICES,
        label="当院を知ったきっかけ",
        widget=forms.Select(attrs={"class": "intake-select"})
    )
    job = forms.CharField(
        required=False,
        max_length=100,
        label="職業（任意）",
        widget=forms.TextInput(attrs={
            "class": "intake-input",
            "placeholder": "例：会社員、学生、主婦"
        }),
    )
    note = forms.CharField(
        required=False,
        label="補足（任意）",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "intake-textarea",
            "placeholder": "気になることがあればご記入ください"
        }),
    )


# --- Step2 ---
SYMPTOM_TYPE_CHOICES = [
    ("acute", "急性"),
    ("chronic", "慢性"),
    ("unknown", "不明"),
]

SINCE_CHOICES = [
    ("today", "今日"),
    ("2_3days", "2〜3日前"),
    ("1week", "1週間前"),
    ("1month", "1ヶ月前"),
    ("3months_plus", "3ヶ月以上前"),
]

class IntakeStep2Form(forms.Form):
    chief_complaint = forms.CharField(
        required=True,
        max_length=255,
        label="主な症状",
        widget=forms.Textarea(attrs={
            "rows": 5,
            "placeholder": "例：朝起きたときに腰が痛い",
            "class": "intake-textarea",
        }),
    )
    symptom_type = forms.ChoiceField(
        required=True,
        choices=SYMPTOM_TYPE_CHOICES,
        label="症状タイプ",
        widget=forms.RadioSelect
    )
    since = forms.ChoiceField(
        required=True,
        choices=SINCE_CHOICES,
        label="いつから症状がありますか？",
        widget=forms.RadioSelect
    )
    trigger = forms.CharField(
        required=True,
        label="症状のきっかけは何ですか？",
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": "例：重い荷物を持ち上げた後",
            "class": "intake-textarea",
        }),
    )


# --- Step3 ---
AREA_CHOICES = [
    ("head", "頭"),
    ("neck", "首"),
    ("shoulder_r", "右肩"),
    ("shoulder_l", "左肩"),
    ("arm_r", "右腕"),
    ("arm_l", "左腕"),
    ("hand_r", "右手"),
    ("hand_l", "左手"),
    ("back", "背中"),
    ("chest", "胸"),
    ("waist", "腰"),
    ("hip_r", "右臀部"),
    ("hip_l", "左臀部"),
    ("thigh_r", "右太もも"),
    ("thigh_l", "左太もも"),
    ("knee_r", "右膝"),
    ("knee_l", "左膝"),
    ("ankle_r", "右足首"),
    ("ankle_l", "左足首"),
    ("other", "その他"),
]

PAIN_QUALITIES = [
    ("sharp", "ズキズキ"),
    ("dull", "重だるい"),
    ("stiff", "こわばり"),
    ("tingle", "しびれ"),
    ("hot", "熱っぽい"),
    ("swelling", "腫れ"),
    ("other", "その他"),
]

class IntakeStep3Form(forms.Form):
    areas = forms.MultipleChoiceField(
        required=True,
        choices=AREA_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        label="痛みや違和感がある部位を選択してください",
    )
    other_area_text = forms.CharField(
        required=False,
        max_length=100,
        label="その他（部位名）",
        widget=forms.TextInput(attrs={
            "class": "intake-input",
            "placeholder": "その他を選択した場合に入力"
        }),
    )

    severity = forms.IntegerField(
        required=True,
        min_value=0,
        max_value=10,
        label="痛みの強さ（0〜10）",
        widget=forms.NumberInput(attrs={
            "type": "range",
            "min": "0",
            "max": "10",
            "step": "1",
            "value": "5",
            "class": "intake-range",
        }),
    )
    qualities = forms.MultipleChoiceField(
        required=False,
        choices=PAIN_QUALITIES,
        widget=forms.CheckboxSelectMultiple,
        label="症状の感じ（複数可）"
    )
    other_quality_text = forms.CharField(
        required=False,
        max_length=100,
        label="その他（症状の感じ）",
        widget=forms.TextInput(attrs={
            "class": "intake-input",
            "placeholder": "例：ピリピリ、圧迫感"
        }),
    )
    free_text = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 4,
            "class": "intake-textarea",
            "placeholder": "補足したい症状があればご記入ください"
        }),
        label="その他（自由記入）"
    )

    def clean(self):
        cleaned = super().clean()

        areas = cleaned.get("areas") or []
        other_text = (cleaned.get("other_area_text") or "").strip()
        if "other" in areas and not other_text:
            self.add_error("other_area_text", "「その他」を選択した場合は部位名を入力してください。")

        qualities = cleaned.get("qualities") or []
        other_quality_text = (cleaned.get("other_quality_text") or "").strip()
        if "other" in qualities and not other_quality_text:
            self.add_error("other_quality_text", "「その他」を選択した場合は症状の感じを入力してください。")

        return cleaned

# --- Step4 ---
class IntakeStep4Form(forms.Form):
    YES_NO = [("no", "いいえ"), ("yes", "はい")]

    other_clinic = forms.ChoiceField(
        required=True,
        choices=YES_NO,
        label="他の医療機関・整体などを受診しましたか？",
        widget=forms.RadioSelect
    )
    other_clinic_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "intake-textarea",
            "placeholder": "受診先・内容があればご記入ください"
        }),
        label="受診先・内容（任意）"
    )

    taking_meds = forms.ChoiceField(
        required=True,
        choices=YES_NO,
        label="服薬中のお薬はありますか？",
        widget=forms.RadioSelect
    )
    meds_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "intake-textarea",
            "placeholder": "お薬の名前・内容があればご記入ください"
        }),
        label="お薬の名前・内容（任意）"
    )

    past_history = forms.ChoiceField(
        required=True,
        choices=YES_NO,
        label="大きなケガ・手術・持病はありますか？",
        widget=forms.RadioSelect
    )
    history_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "intake-textarea",
            "placeholder": "該当する内容があればご記入ください"
        }),
        label="内容（任意）"
    )

    consent_agreed = forms.BooleanField(required=True, label="個人情報の取り扱いに同意します")
    final_note = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={
            "rows": 4,
            "class": "intake-textarea",
            "placeholder": "受付への連絡事項があればご記入ください"
        }),
        label="連絡事項（任意）"
    )

    def clean(self):
        cleaned = super().clean()
        return cleaned

VISIT_TYPE_CHOICES = [
    ("followup", "同じ症状での通院"),
    ("new_issue", "新しい症状"),
    ("unknown", "わからない"),
]

FOLLOWUP_CHANGE_CHOICES = [
    ("better", "良くなった"),
    ("same", "あまり変わらない"),
    ("worse", "悪化した"),
]

FOLLOWUP_CHANGE_DETAIL_CHOICES = [
    ("pain", "痛み"),
    ("range", "動かしにくさ"),
    ("numbness", "しびれ"),
    ("spread", "痛む場所が広がった"),
    ("none", "特になし"),
]


class IntakeStartForm(forms.Form):
    visit_type = forms.ChoiceField(
        required=True,
        choices=VISIT_TYPE_CHOICES,
        label="今回の来院について",
        widget=forms.RadioSelect
    )


class FollowupIntakeForm(forms.Form):
    condition_change = forms.ChoiceField(
        required=True,
        choices=FOLLOWUP_CHANGE_CHOICES,
        label="前回と比べて状態はどうですか？",
        widget=forms.RadioSelect
    )
    pain_level = forms.IntegerField(
        required=True,
        min_value=0,
        max_value=10,
        label="今の痛みの強さ（0〜10）",
        widget=forms.NumberInput(attrs={
            "type": "range",
            "min": "0",
            "max": "10",
            "step": "1",
            "value": "5",
            "class": "intake-range",
        }),
    )
    changes = forms.MultipleChoiceField(
        required=False,
        choices=FOLLOWUP_CHANGE_DETAIL_CHOICES,
        label="気になる変化（複数可）",
        widget=forms.CheckboxSelectMultiple
    )
    comment = forms.CharField(
        required=False,
        label="コメント（任意）",
        widget=forms.Textarea(attrs={
            "rows": 4,
            "class": "intake-textarea",
            "placeholder": "例：腕を上げる時だけ少し痛い"
        }),
    )