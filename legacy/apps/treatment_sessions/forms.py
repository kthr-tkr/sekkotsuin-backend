from __future__ import annotations

from copy import deepcopy

from django import forms


def _as_dict(value):
    return value if isinstance(value, dict) else {}


def _as_text(value):
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)):
        return "\n".join(_as_lines(value))
    if isinstance(value, dict):
        return str(
            value.get("text")
            or value.get("summary")
            or value.get("label")
            or ""
        ).strip()
    return str(value).strip()


def _as_lines(value):
    if value is None:
        return []
    if isinstance(value, str):
        return [line.strip(" ・\t") for line in value.splitlines() if line.strip()]
    if isinstance(value, (list, tuple)):
        lines = []
        for item in value:
            text = _as_text(item)
            if text:
                lines.extend(
                    line.strip(" ・\t")
                    for line in text.splitlines()
                    if line.strip()
                )
        return lines
    text = _as_text(value)
    return [text] if text else []


def _first_value(container, *keys):
    container = _as_dict(container)
    for key in keys:
        value = container.get(key)
        if value not in (None, "", [], {}):
            return value
    return None


def _merge_lines(*values):
    merged = []
    for value in values:
        for line in _as_lines(value):
            if line not in merged:
                merged.append(line)
    return merged


class TreatmentSessionConfirmForm(forms.Form):
    overall_summary = forms.CharField(
        label="今回の要約",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    soap_s = forms.CharField(
        label="S：主観情報",
        required=False,
        widget=forms.Textarea(attrs={"rows": 7}),
    )
    soap_o = forms.CharField(
        label="O：客観情報",
        required=False,
        widget=forms.Textarea(attrs={"rows": 7}),
    )
    soap_a = forms.CharField(
        label="A：評価",
        required=False,
        widget=forms.Textarea(attrs={"rows": 7}),
    )
    soap_p = forms.CharField(
        label="P：計画",
        required=False,
        widget=forms.Textarea(attrs={"rows": 7}),
    )
    target_areas = forms.CharField(
        label="施術対象部位",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    performed_treatments = forms.CharField(
        label="施術内容",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    patient_response = forms.CharField(
        label="患者反応",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    after_treatment_change = forms.CharField(
        label="施術後の変化",
        required=False,
        widget=forms.Textarea(attrs={"rows": 4}),
    )
    explained_to_patient = forms.CharField(
        label="患者への説明",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    lifestyle_guidance = forms.CharField(
        label="生活上の指導",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    home_care = forms.CharField(
        label="セルフケア",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    next_treatment_policy = forms.CharField(
        label="次回の施術方針",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )
    recommended_visit_timing = forms.CharField(
        label="来院目安",
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    next_check_points = forms.CharField(
        label="次回確認ポイント",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    caution_notes = forms.CharField(
        label="注意事項",
        required=False,
        widget=forms.Textarea(attrs={"rows": 6}),
    )
    followup_items = forms.CharField(
        label="フォローアップ項目（追加確認事項）",
        required=False,
        widget=forms.Textarea(attrs={"rows": 5}),
    )

    def __init__(self, *args, summary=None, **kwargs):
        self.source_summary = deepcopy(summary) if isinstance(summary, dict) else {}
        kwargs.setdefault("initial", self._build_initial(self.source_summary))
        super().__init__(*args, **kwargs)

        for field in self.fields.values():
            field.widget.attrs.setdefault("class", "confirm-textarea")
            field.widget.attrs.setdefault(
                "placeholder",
                "1項目ずつ改行して入力してください。",
            )

    @staticmethod
    def _build_initial(summary):
        session_summary = _as_dict(
            _first_value(summary, "session_summary", "summary")
        )
        soap = _as_dict(_first_value(summary, "soap", "SOAP"))
        treatment = _as_dict(_first_value(summary, "treatment", "treatments"))
        explanation = _as_dict(
            _first_value(summary, "explanation", "patient_guidance")
        )
        next_plan = _as_dict(_first_value(summary, "next_plan", "plan"))
        progress_note = _as_dict(summary.get("progress_note"))

        return {
            "overall_summary": _as_text(
                _first_value(session_summary, "overall_summary", "summary")
                or _first_value(summary, "overall_summary")
                or _first_value(progress_note, "short_summary", "record_text")
            ),
            "soap_s": "\n".join(
                _as_lines(_first_value(soap, "S", "s", "subjective"))
            ),
            "soap_o": "\n".join(
                _as_lines(_first_value(soap, "O", "o", "objective"))
            ),
            "soap_a": "\n".join(
                _as_lines(_first_value(soap, "A", "a", "assessment"))
            ),
            "soap_p": "\n".join(
                _as_lines(_first_value(soap, "P", "p", "plan"))
            ),
            "target_areas": "\n".join(
                _as_lines(_first_value(treatment, "target_areas", "areas"))
            ),
            "performed_treatments": "\n".join(
                _as_lines(
                    _first_value(
                        treatment,
                        "performed_treatments",
                        "treatment_content",
                        "items",
                    )
                )
            ),
            "patient_response": _as_text(
                _first_value(treatment, "patient_response", "response")
            ),
            "after_treatment_change": _as_text(
                _first_value(
                    treatment,
                    "after_treatment_change",
                    "post_treatment_change",
                )
            ),
            "explained_to_patient": "\n".join(
                _as_lines(
                    _first_value(
                        explanation,
                        "explained_to_patient",
                        "patient_explanation",
                    )
                )
            ),
            "lifestyle_guidance": "\n".join(
                _as_lines(
                    _first_value(
                        explanation,
                        "lifestyle_guidance",
                        "guidance",
                    )
                )
            ),
            "home_care": "\n".join(
                _as_lines(
                    _first_value(
                        explanation,
                        "home_care",
                        "home_care_suggestions",
                    )
                )
            ),
            "next_treatment_policy": _as_text(
                _first_value(
                    next_plan,
                    "next_treatment_policy",
                    "treatment_policy",
                )
            ),
            "recommended_visit_timing": _as_text(
                _first_value(
                    next_plan,
                    "recommended_visit_timing",
                    "visit_timing",
                )
            ),
            "next_check_points": "\n".join(
                _as_lines(
                    _first_value(
                        next_plan,
                        "items_to_check_next_time",
                        "next_check_points",
                    )
                    or _first_value(summary, "next_check_points")
                )
            ),
            "caution_notes": "\n".join(
                _merge_lines(
                    _first_value(summary, "safety_notes", "risk_notes"),
                    _first_value(
                        explanation,
                        "cautions_until_next_visit",
                        "cautions",
                    ),
                )
            ),
            "followup_items": "\n".join(
                _as_lines(
                    _first_value(
                        summary,
                        "missing_information",
                        "followups",
                        "followup_items",
                    )
                )
            ),
        }

    def build_confirmed_summary(self):
        summary = deepcopy(self.source_summary)
        if not isinstance(summary, dict):
            summary = {}

        session_summary = _as_dict(summary.get("session_summary"))
        session_summary["overall_summary"] = self.cleaned_data["overall_summary"].strip()
        summary["session_summary"] = session_summary

        soap = _as_dict(summary.get("soap"))
        soap.update(
            {
                "S": _as_lines(self.cleaned_data["soap_s"]),
                "O": _as_lines(self.cleaned_data["soap_o"]),
                "A": _as_lines(self.cleaned_data["soap_a"]),
                "P": _as_lines(self.cleaned_data["soap_p"]),
            }
        )
        summary["soap"] = soap

        treatment = _as_dict(summary.get("treatment"))
        treatment.update(
            {
                "target_areas": _as_lines(self.cleaned_data["target_areas"]),
                "performed_treatments": _as_lines(
                    self.cleaned_data["performed_treatments"]
                ),
                "patient_response": self.cleaned_data["patient_response"].strip(),
                "after_treatment_change": self.cleaned_data[
                    "after_treatment_change"
                ].strip(),
            }
        )
        summary["treatment"] = treatment

        explanation = _as_dict(summary.get("explanation"))
        explanation.update(
            {
                "explained_to_patient": _as_lines(
                    self.cleaned_data["explained_to_patient"]
                ),
                "lifestyle_guidance": _as_lines(
                    self.cleaned_data["lifestyle_guidance"]
                ),
                "home_care": _as_lines(self.cleaned_data["home_care"]),
                "cautions_until_next_visit": _as_lines(
                    self.cleaned_data["caution_notes"]
                ),
            }
        )
        summary["explanation"] = explanation

        next_plan = _as_dict(summary.get("next_plan"))
        next_plan.update(
            {
                "next_treatment_policy": self.cleaned_data[
                    "next_treatment_policy"
                ].strip(),
                "recommended_visit_timing": self.cleaned_data[
                    "recommended_visit_timing"
                ].strip(),
                "items_to_check_next_time": _as_lines(
                    self.cleaned_data["next_check_points"]
                ),
            }
        )
        summary["next_plan"] = next_plan

        summary["safety_notes"] = _as_lines(self.cleaned_data["caution_notes"])
        summary["missing_information"] = _as_lines(
            self.cleaned_data["followup_items"]
        )

        return summary
