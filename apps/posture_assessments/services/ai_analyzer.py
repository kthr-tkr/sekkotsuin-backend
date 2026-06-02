import base64
import json
from pathlib import Path

from django.conf import settings
from openai import OpenAI


POSTURE_ANALYSIS_SCHEMA = {
    "name": "posture_analysis",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "important_points": {
                "type": "array",
                "items": {"type": "string"},
            },
            "overall_summary": {"type": "string"},
            "posture_findings": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "head_neck": {"type": "string"},
                    "shoulder": {"type": "string"},
                    "spine": {"type": "string"},
                    "pelvis": {"type": "string"},
                    "knee": {"type": "string"},
                    "foot": {"type": "string"},
                    "balance": {"type": "string"},
                },
                "required": [
                    "head_neck",
                    "shoulder",
                    "spine",
                    "pelvis",
                    "knee",
                    "foot",
                    "balance",
                ],
            },
            "suspected_load_areas": {
                "type": "array",
                "items": {"type": "string"},
            },
            "clinical_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "treatment_suggestions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "home_care_suggestions": {
                "type": "array",
                "items": {"type": "string"},
            },
            "next_check_points": {
                "type": "array",
                "items": {"type": "string"},
            },
            "risk_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "patient_explanation": {"type": "string"},
        },
        "required": [
            "important_points",
            "overall_summary",
            "posture_findings",
            "suspected_load_areas",
            "clinical_notes",
            "treatment_suggestions",
            "home_care_suggestions",
            "next_check_points",
            "risk_notes",
            "patient_explanation",
        ],
    },
}


def _image_to_data_url(image_path: str) -> str:
    path = Path(image_path)

    suffix = path.suffix.lower()
    if suffix in [".jpg", ".jpeg"]:
        mime = "image/jpeg"
    elif suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    else:
        mime = "image/jpeg"

    with open(path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")

    return f"data:{mime};base64,{encoded}"


def analyze_posture_assessment(assessment):
    """
    姿勢画像をAI分析し、JSONを返す。
    医療診断ではなく、施術者の観察補助として扱う。
    """
    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    images = list(assessment.images.all().order_by("image_type", "id"))

    if not images:
        raise ValueError("姿勢分析用の画像が登録されていません。")

    content = [
        {
            "type": "text",
            "text": """
あなたは接骨院・整体院向けの姿勢観察補助AIです。
以下の画像から、姿勢の傾向・負担がかかりやすい部位・施術で確認すべき点を整理してください。

重要:
- 診断名を断定しないこと
- 画像だけで医学的確定診断をしないこと
- 「可能性」「傾向」「確認が必要」という表現を使うこと
- 施術者が現場で使いやすい表現にすること
- 患者説明にも使える、わかりやすい表現にすること
- 危険所見や画像だけでは判断できない点は risk_notes に入れること

出力は必ず指定JSONスキーマに従ってください。
""",
        }
    ]

    for img in images:
        content.append({
            "type": "text",
            "text": f"画像種別: {img.get_image_type_display()}",
        })
        content.append({
            "type": "image_url",
            "image_url": {
                "url": _image_to_data_url(img.image.path),
            },
        })

    response = client.responses.create(
        model=getattr(settings, "OPENAI_MODEL", "gpt-4o-mini"),
        input=[
            {
                "role": "user",
                "content": content,
            }
        ],
        response_format={
            "type": "json_schema",
            "json_schema": POSTURE_ANALYSIS_SCHEMA,
        },
    )

    raw = response.output_text
    return json.loads(raw)