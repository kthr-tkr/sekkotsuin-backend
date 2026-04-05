# apps/intakes/services/intake_sync.py
from __future__ import annotations
from typing import Any, Dict

from apps.intakes.models import Intake


def _safe_str(v: Any) -> str:
    return (v or "").strip() if isinstance(v, str) or v is None else str(v).strip()


def _pick_first_nonempty(*vals: Any) -> str:
    for v in vals:
        s = _safe_str(v)
        if s:
            return s
    return ""


def sync_intake_columns_from_summary(intake: Intake, summary_json: Dict[str, Any]) -> None:
    """
    summary_json.extract の値を Intake のカラムに同期する。
    extract が薄い/無い場合は soap から最低限を補完する（安全側）。
    """
    summary_json = summary_json or {}
    extract = summary_json.get("extract") or {}
    soap = summary_json.get("soap") or {}

    # 1) chief_complaint（主訴）
    # extract > soap.s の順で補完（soap.sは文章なので短く切るのもアリ）
    cc = _pick_first_nonempty(extract.get("chief_complaint"), soap.get("s"))
    if cc:
        # 長くなりすぎたらカラム制約に合わせて丸める（255）
        intake.chief_complaint = cc[:255]

    # 2) onset（いつから）
    onset = _pick_first_nonempty(extract.get("onset"))
    if onset:
        intake.onset = onset[:100]

    # 3) symptom_type（急性/慢性/不明）
    symptom_type = extract.get("symptom_type") or Intake.SymptomType.UNKNOWN
    allowed = {Intake.SymptomType.ACUTE, Intake.SymptomType.CHRONIC, Intake.SymptomType.UNKNOWN}
    intake.symptom_type = symptom_type if symptom_type in allowed else Intake.SymptomType.UNKNOWN