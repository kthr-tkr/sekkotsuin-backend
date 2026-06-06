import base64
import json
import mimetypes

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
                "description": "施術者が最初に確認すべき重要ポイント。3〜6件。",
            },
            "overall_summary": {
                "type": "string",
                "description": "姿勢画像とメモから見た全体サマリー。断定診断ではなく観察補助として記載する。",
            },
            "posture_findings": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "head_neck": {
                        "type": "string",
                        "description": "頭部前方位、首の傾き、頚部への負担傾向。",
                    },
                    "shoulder": {
                        "type": "string",
                        "description": "肩の高さ、巻き肩、左右差、肩甲帯の傾向。",
                    },
                    "spine": {
                        "type": "string",
                        "description": "背骨、胸椎、猫背、体幹の傾きの傾向。",
                    },
                    "pelvis": {
                        "type": "string",
                        "description": "骨盤の左右差、前傾・後傾、回旋傾向。",
                    },
                    "knee": {
                        "type": "string",
                        "description": "膝の向き、左右差、ニーイン・ニーアウト傾向。",
                    },
                    "foot": {
                        "type": "string",
                        "description": "足部の向き、荷重、接地傾向。",
                    },
                    "balance": {
                        "type": "string",
                        "description": "全体重心、左右差、前後バランス。",
                    },
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
                "description": "負担がかかっていそうな部位候補。",
            },
            "clinical_notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "施術者向けの臨床メモ。評価・確認観点・注意点。",
            },
            "treatment_suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "施術方針の候補。断定ではなく施術者判断の補助。",
            },
            "home_care_suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "患者へ伝えられるセルフケア候補。",
            },
            "next_check_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "次回確認すべき姿勢・動作・症状変化。",
            },
            "risk_notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "画像だけでは判断できない点、再撮影推奨、断定回避など。",
            },
            "patient_explanation": {
                "type": "string",
                "description": "患者さんにそのまま説明しやすい、やさしい表現。",
            },
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

POSTURE_COMPARISON_SCHEMA = {
    "name": "posture_comparison_analysis",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "important_changes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Before/Afterで最初に確認すべき重要な変化。3〜6件。",
            },
            "overall_summary": {
                "type": "string",
                "description": "Before/After全体の比較サマリー。診断ではなく観察補助として記載する。",
            },
            "improved_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "改善している可能性がある姿勢傾向。",
            },
            "unchanged_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "大きな変化が見られない、または継続確認が必要な点。",
            },
            "worse_or_attention_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "悪化と断定せず、注意・再確認が必要な点。",
            },
            "body_area_comparison": {
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
            "clinical_notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "施術者向けの比較メモ。評価・触診・動作確認の観点。",
            },
            "next_focus": {
                "type": "array",
                "items": {"type": "string"},
                "description": "次回施術や次回撮影で重点的に確認すべきポイント。",
            },
            "patient_explanation": {
                "type": "string",
                "description": "患者さんにそのまま説明しやすい、前向きでやさしい比較説明。",
            },
            "risk_notes": {
                "type": "array",
                "items": {"type": "string"},
                "description": "画像だけでは判断できない点、撮影条件差、断定回避など。",
            },
        },
        "required": [
            "important_changes",
            "overall_summary",
            "improved_points",
            "unchanged_points",
            "worse_or_attention_points",
            "body_area_comparison",
            "clinical_notes",
            "next_focus",
            "patient_explanation",
            "risk_notes",
        ],
    },
}

IMAGE_TYPE_LABELS = {
    "front": "正面",
    "side_right": "右側面",
    "back": "背面",
}


def _guess_mime_type(file_field) -> str:
    """
    S3 / ローカル保存どちらでも、FileField/ImageField の name からMIMEを推定する。
    """
    name = getattr(file_field, "name", "") or ""
    mime, _ = mimetypes.guess_type(name)

    if mime:
        return mime

    lower_name = name.lower()

    if lower_name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"

    if lower_name.endswith(".png"):
        return "image/png"

    if lower_name.endswith(".webp"):
        return "image/webp"

    return "image/jpeg"


def _image_field_to_data_url(image_field) -> str:
    """
    ImageField/FileField を data URL に変換する。

    重要:
    - img.image.path は使わない
    - S3保存では path が存在しないため、storage経由で open/read する
    - ローカル保存でもS3保存でも同じコードで動く
    """
    if not image_field:
        raise ValueError("画像ファイルが指定されていません。")

    if not getattr(image_field, "name", None):
        raise ValueError("画像ファイル名が空です。")

    mime = _guess_mime_type(image_field)

    try:
        image_field.open("rb")
        binary = image_field.read()
    finally:
        try:
            image_field.close()
        except Exception:
            pass

    if not binary:
        raise ValueError(f"画像ファイルを読み込めませんでした: {image_field.name}")

    encoded = base64.b64encode(binary).decode("utf-8")
    return f"data:{mime};base64,{encoded}"


def _build_image_content(assessment):
    content = []

    images = list(
        assessment.images.all().order_by("order", "image_type", "id")
    )

    if not images:
        raise ValueError("姿勢分析用の画像が登録されていません。")

    for img in images:
        label = IMAGE_TYPE_LABELS.get(
            img.image_type,
            img.get_image_type_display(),
        )

        content.append({
            "type": "input_text",
            "text": f"【{label}画像】この画像から姿勢傾向を確認してください。",
        })

        content.append({
            "type": "input_image",
            "image_url": _image_field_to_data_url(img.image),
        })

    return content

def _build_comparison_image_content(comparison):
    content = []

    before = comparison.before_assessment
    after = comparison.after_assessment

    before_images = list(
        before.images.all().order_by("order", "image_type", "id")
    )
    after_images = list(
        after.images.all().order_by("order", "image_type", "id")
    )

    if not before_images:
        raise ValueError("Before側の姿勢画像が登録されていません。")

    if not after_images:
        raise ValueError("After側の姿勢画像が登録されていません。")

    content.append({
        "type": "input_text",
        "text": "以下はBefore側の姿勢画像です。",
    })

    for img in before_images:
        label = IMAGE_TYPE_LABELS.get(
            img.image_type,
            img.get_image_type_display(),
        )

        content.append({
            "type": "input_text",
            "text": f"【Before：{label}画像】",
        })

        content.append({
            "type": "input_image",
            "image_url": _image_field_to_data_url(img.image),
        })

    content.append({
        "type": "input_text",
        "text": "以下はAfter側の姿勢画像です。",
    })

    for img in after_images:
        label = IMAGE_TYPE_LABELS.get(
            img.image_type,
            img.get_image_type_display(),
        )

        content.append({
            "type": "input_text",
            "text": f"【After：{label}画像】",
        })

        content.append({
            "type": "input_image",
            "image_url": _image_field_to_data_url(img.image),
        })

    return content

def analyze_posture_assessment(assessment):
    """
    姿勢画像をAI分析し、JSONを返す。

    注意:
    - 医療診断ではない
    - 施術者の観察補助
    - 画像だけで断定しない
    - S3保存/ローカル保存どちらでも動作する
    """
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY が設定されていません。")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    patient = assessment.patient
    appointment = assessment.appointment

    patient_name = f"{patient.last_name} {patient.first_name}".strip()

    image_content = _build_image_content(assessment)

    memo = assessment.memo or ""
    appointment_text = "-"

    if appointment and appointment.start_at:
        appointment_text = appointment.start_at.strftime("%Y-%m-%d %H:%M")

    prompt = f"""
あなたは接骨院・整骨院向けの姿勢観察補助AIです。
以下の正面・右側面・背面画像とメモをもとに、姿勢傾向を整理してください。

# 患者情報
- 患者名: {patient_name}
- 予約日時: {appointment_text}
- 撮影メモ・主訴メモ: {memo or "-"}

# 目的
- 施術者が短時間で姿勢傾向を把握できるようにする
- 主訴やメモと姿勢傾向の関連を考える
- 施術前の確認ポイントを整理する
- 患者説明に使える文章を作る

# 必ず守るルール
- 医療診断名を断定しない
- 画像だけで病名や原因を確定しない
- 「可能性」「傾向」「確認が必要」という表現を使う
- 画像から見えないことは無理に書かない
- 危険な断定、治療保証、改善保証はしない
- 施術者の判断を補助する表現にする
- 患者説明は不安を煽らず、前向きでわかりやすくする

# 重点観察ポイント
- 頭部前方位
- 首の傾き
- 肩の左右差
- 巻き肩傾向
- 背中・猫背傾向
- 骨盤の左右差、前傾・後傾、回旋傾向
- 膝の向き、左右差、ニーイン傾向
- 足部の向き、荷重傾向
- 全体の重心バランス
- 主訴との関連がありそうな負担部位

# 出力品質
- important_points は現場で最初に見るべき内容にする
- clinical_notes は施術者が評価時に使える内容にする
- treatment_suggestions は「候補」として書く
- home_care_suggestions は患者に伝えても安全な範囲にする
- risk_notes には「画像だけでは判断できないこと」も含める
""".strip()

    response = client.responses.create(
        model=getattr(settings, "OPENAI_VISION_MODEL", "gpt-4o-mini"),
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "あなたは接骨院・整骨院向けの姿勢観察補助AIです。"
                            "診断ではなく、施術者の観察・説明・記録を補助してください。"
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                    *image_content,
                ],
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": POSTURE_ANALYSIS_SCHEMA["name"],
                "schema": POSTURE_ANALYSIS_SCHEMA["schema"],
                "strict": True,
            }
        },
    )

    raw = response.output_text

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI姿勢分析結果のJSON解析に失敗しました: {e}") from e

    result["meta"] = {
        "source": "posture_assessment",
        "assessment_id": assessment.id,
        "model": getattr(settings, "OPENAI_VISION_MODEL", "gpt-4o-mini"),
        "image_count": assessment.images.count(),
        "storage_safe": True,
    }

    return result

def analyze_posture_comparison(comparison):
    """
    Before/After姿勢画像をAI比較分析し、JSONを返す。

    注意:
    - 医療診断ではない
    - 改善/悪化を断定しない
    - 撮影条件差を考慮する
    - 施術者の観察補助として扱う
    """
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY が設定されていません。")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    patient = comparison.patient
    patient_name = f"{patient.last_name} {patient.first_name}".strip()

    before = comparison.before_assessment
    after = comparison.after_assessment

    image_content = _build_comparison_image_content(comparison)

    before_summary = before.get_active_summary() or {}
    after_summary = after.get_active_summary() or {}

    prompt = f"""
あなたは接骨院・整骨院向けの姿勢Before/After比較補助AIです。
以下のBefore画像、After画像、既存のAI姿勢分析結果、比較メモをもとに、姿勢の変化を整理してください。

# 患者情報
- 患者名: {patient_name}

# 比較情報
- 比較タイトル: {comparison.title}
- 比較メモ: {comparison.memo or "-"}

# Before情報
- Before撮影日: {before.created_at.strftime("%Y-%m-%d %H:%M")}
- Beforeタイトル: {before.title}
- Beforeメモ: {before.memo or "-"}
- Before AI分析結果:
{json.dumps(before_summary, ensure_ascii=False, indent=2)}

# After情報
- After撮影日: {after.created_at.strftime("%Y-%m-%d %H:%M")}
- Afterタイトル: {after.title}
- Afterメモ: {after.memo or "-"}
- After AI分析結果:
{json.dumps(after_summary, ensure_ascii=False, indent=2)}

# 目的
- 施術者がBefore/Afterの変化を短時間で把握できるようにする
- 改善している可能性がある点を整理する
- 大きく変化していない点を整理する
- 引き続き確認すべき点を整理する
- 患者さんに前向きに説明できる文章を作る

# 必ず守るルール
- 医療診断名を断定しない
- 画像だけで原因を確定しない
- 「改善しています」と断定せず「整ってきている可能性」「軽減しているように見える」などにする
- 「悪化」と断定せず「引き続き確認が必要」「撮影条件の影響も考えられる」と表現する
- 撮影角度、立ち位置、服装、距離、光の条件で見え方が変わることを考慮する
- 患者説明は不安を煽らず、前向きでわかりやすくする
- 施術者の判断を補助する表現にする

# 比較観点
- 頭部前方位
- 首の傾き
- 肩の左右差
- 巻き肩傾向
- 背中・猫背傾向
- 骨盤の左右差、前傾・後傾、回旋傾向
- 膝の向き、左右差、ニーイン傾向
- 足部の向き、荷重傾向
- 全体の重心バランス
""".strip()

    response = client.responses.create(
        model=getattr(settings, "OPENAI_VISION_MODEL", "gpt-4o-mini"),
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "あなたは接骨院・整骨院向けの姿勢Before/After比較補助AIです。"
                            "診断ではなく、施術者の観察・説明・記録を補助してください。"
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_text",
                        "text": prompt,
                    },
                    *image_content,
                ],
            },
        ],
        text={
            "format": {
                "type": "json_schema",
                "name": POSTURE_COMPARISON_SCHEMA["name"],
                "schema": POSTURE_COMPARISON_SCHEMA["schema"],
                "strict": True,
            }
        },
    )

    raw = response.output_text

    try:
        result = json.loads(raw)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI姿勢比較結果のJSON解析に失敗しました: {e}") from e

    result["meta"] = {
        "source": "posture_comparison",
        "comparison_id": comparison.id,
        "before_assessment_id": before.id,
        "after_assessment_id": after.id,
        "model": getattr(settings, "OPENAI_VISION_MODEL", "gpt-4o-mini"),
        "before_image_count": before.images.count(),
        "after_image_count": after.images.count(),
        "storage_safe": True,
    }

    return result