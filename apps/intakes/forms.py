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
        label="主な症状について",
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
        label="お悩みのきっかけなどはございましたか？",
        widget=forms.Textarea(attrs={
            "rows": 4,
            "placeholder": "例：重い荷物を持ち上げた後",
            "class": "intake-textarea",
        }),
    )
    worse_when = forms.CharField(
        required=False,
        max_length=255,
        label="どのようなときに気になったり、悪化しますか？",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "intake-textarea",
            "placeholder": "例：歩く時、階段、朝起きた時、前かがみ など"
        }),
    )

    better_when = forms.CharField(
        required=False,
        max_length=255,
        label="どのような時に楽になりますか？",
        widget=forms.Textarea(attrs={
            "rows": 3,
            "class": "intake-textarea",
            "placeholder": "例：横になる、温める、安静にする など"
        }),
    )

# --- Step3 ---
AREA_CHOICES = [
    # 前面
    ("喉前", "首"),
    ("右肩前", "右肩"),
    ("左肩前", "左肩"),
    ("右上腕前", "右上腕"),
    ("左上腕前", "左上腕"),
    ("右肘前", "右肘"),
    ("左肘前", "左肘"),
    ("右前腕前", "右前腕"),
    ("左前腕前", "左前腕"),
    ("右手前", "右手"),
    ("左手前", "左手"),
    ("右胸前", "右胸"),
    ("左胸前", "左胸"),
    ("鳩尾前", "みぞおち"),
    ("右鼠径部前", "右股関節"),
    ("左鼠径部前", "左股関節"),
    ("右大腿前", "右太もも"),
    ("左大腿前", "左太もも"),
    ("右膝前", "右膝"),
    ("左膝前", "左膝"),
    ("右下腿前", "右すね"),
    ("左下腿前", "左すね"),
    ("右足前", "右足"),
    ("左足前", "左足"),

    # 背面
    ("首後", "首の後ろ"),
    ("右肩後", "右肩後ろ"),
    ("左肩後", "左肩後ろ"),
    ("右肩甲骨後", "右肩甲骨"),
    ("左肩甲骨後", "左肩甲骨"),
    ("背中上後", "背中上部"),
    ("背中下後", "背中下部"),
    ("腰後", "腰"),
    ("右腰後", "右腰"),
    ("左腰後", "左腰"),
    ("右臀部後", "右臀部"),
    ("左臀部後", "左臀部"),
    ("右上腕後", "右上腕後ろ"),
    ("左上腕後", "左上腕後ろ"),
    ("右肘後", "右肘後ろ"),
    ("左肘後", "左肘後ろ"),
    ("右前腕後", "右前腕後ろ"),
    ("左前腕後", "左前腕後ろ"),
    ("右大腿後", "右太もも後ろ"),
    ("左大腿後", "左太もも後ろ"),
    ("右膝後", "右膝後ろ"),
    ("左膝後", "左膝後ろ"),
    ("右下腿後", "右ふくらはぎ"),
    ("左下腿後", "左ふくらはぎ"),
    ("右足後", "右足後ろ"),
    ("左足後", "左足後ろ"),

    # 手指
    ("左手背", "左手の甲"),
    ("左手掌", "左手のひら"),
    ("左母指前", "左親指"),
    ("左示指前", "左人差し指"),
    ("左中指前", "左中指"),
    ("左環指前", "左薬指"),
    ("左小指前", "左小指"),

    ("右手背", "右手の甲"),
    ("右手掌", "右手のひら"),
    ("右母指前", "右親指"),
    ("右示指前", "右人差し指"),
    ("右中指前", "右中指"),
    ("右環指前", "右薬指"),
    ("右小指前", "右小指"),

    # 足指・足裏
    ("右足背前", "右足の甲"),
    ("左足背前", "左足の甲"),
    ("右母趾前", "右親指"),
    ("右第2趾前", "右第2趾"),
    ("右第3趾前", "右第3趾"),
    ("右第4趾前", "右第4趾"),
    ("右小趾前", "右小趾"),

    ("左母趾前", "左親指"),
    ("左第2趾前", "左第2趾"),
    ("左第3趾前", "左第3趾"),
    ("左第4趾前", "左第4趾"),
    ("左小趾前", "左小趾"),

    ("右足底後", "右足裏"),
    ("左足底後", "左足裏"),
    ("右踵後", "右かかと"),
    ("左踵後", "左かかと"),

    ("other", "その他"),
]

PAIN_QUALITIES = [
    ("sharp", "ズキズキ"),
    ("dull", "重だるい"),
    ("stiff", "こわばり"),
    ("tingle", "しびれ"),
    ("hot", "熱っぽい"),
    ("swelling", "腫れ"),
    ("limited_motion", "動かしにくい"),
    ("weakness", "力が入りにくい"),
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

    symptom_details = forms.MultipleChoiceField(
        required=False,
        choices=SYMPTOM_DETAIL_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        label="当てはまる症状（複数可）"
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