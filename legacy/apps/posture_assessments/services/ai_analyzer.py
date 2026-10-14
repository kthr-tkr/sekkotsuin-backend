import base64
import json
import mimetypes
import re

from django.conf import settings
from openai import OpenAI


def _joint_assessment_schema(description):
    return {
        "type": "object",
        "additionalProperties": False,
        "description": description,
        "properties": {
            "summary": {"type": "string"},
            "possible_findings": {
                "type": "array",
                "items": {"type": "string"},
            },
            "check_points": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "summary",
            "possible_findings",
            "check_points",
        ],
    }


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
                "description": "三方向画像と主訴情報を統合した施術者向け全体サマリー。",
            },
            "view_summaries": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "front": {"type": "string"},
                    "side_right": {"type": "string"},
                    "back": {"type": "string"},
                },
                "required": [
                    "front",
                    "side_right",
                    "back",
                ],
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
                    "hip": {
                        "type": "string",
                        "description": "股関節周囲のアライメント、左右差、荷重傾向。",
                    },
                    "knee": {
                        "type": "string",
                        "description": "膝の向き、左右差、ニーイン・ニーアウト傾向。",
                    },
                    "ankle_foot": {
                        "type": "string",
                        "description": "足関節、足部、踵の向き、接地、左右差の傾向。",
                    },
                    "foot": {
                        "type": "string",
                        "description": "既存画面互換用。ankle_footと同じ内容を簡潔に記載する。",
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
                    "hip",
                    "knee",
                    "ankle_foot",
                    "foot",
                    "balance",
                ],
            },
            "joint_assessments": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "head": _joint_assessment_schema(
                        "頭部位置、傾き、重心線との関係。"
                    ),
                    "neck": _joint_assessment_schema(
                        "頚部アライメントと負担の可能性。"
                    ),
                    "shoulder": _joint_assessment_schema(
                        "肩甲帯、肩関節周囲の左右差と位置関係。"
                    ),
                    "thoracic_spine": _joint_assessment_schema(
                        "胸椎後弯、体幹上部、胸郭の姿勢傾向。"
                    ),
                    "lumbar_pelvis": _joint_assessment_schema(
                        "腰椎・骨盤帯の傾き、偏位、負担の可能性。"
                    ),
                    "hip": _joint_assessment_schema(
                        "股関節と下肢ライン、荷重の左右差。"
                    ),
                    "knee": _joint_assessment_schema(
                        "膝関節の向き、過伸展、屈曲、内外反傾向。"
                    ),
                    "ankle_foot": _joint_assessment_schema(
                        "足関節・足部・踵の向き、接地、支持性の傾向。"
                    ),
                },
                "required": [
                    "head",
                    "neck",
                    "shoulder",
                    "thoracic_spine",
                    "lumbar_pelvis",
                    "hip",
                    "knee",
                    "ankle_foot",
                ],
            },
            "alignment_observations": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "frontal_plane": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "sagittal_plane": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "posterior_view": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "center_of_gravity": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "frontal_plane",
                    "sagittal_plane",
                    "posterior_view",
                    "center_of_gravity",
                ],
            },
            "symptom_relation_hypotheses": {
                "type": "array",
                "items": {"type": "string"},
                "description": "主訴情報がある場合の、姿勢所見と症状の関連仮説。因果関係は断定しない。",
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
            "report_summary_for_patient": {
                "type": "string",
                "description": "患者向けレポートに使える、前向きで簡潔な姿勢評価まとめ。",
            },
            "meta": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "source": {"type": "string"},
                    "assessment_id": {"type": "integer"},
                    "model": {"type": "string"},
                    "image_count": {"type": "integer"},
                    "schema_version": {"type": "integer"},
                    "privacy_mode": {"type": "string"},
                    "storage_safe": {"type": "boolean"},
                },
                "required": [
                    "source",
                    "assessment_id",
                    "model",
                    "image_count",
                    "schema_version",
                    "privacy_mode",
                    "storage_safe",
                ],
            },
        },
        "required": [
            "important_points",
            "overall_summary",
            "view_summaries",
            "posture_findings",
            "joint_assessments",
            "alignment_observations",
            "symptom_relation_hypotheses",
            "suspected_load_areas",
            "clinical_notes",
            "treatment_suggestions",
            "home_care_suggestions",
            "next_check_points",
            "risk_notes",
            "patient_explanation",
            "report_summary_for_patient",
            "meta",
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
            "overall_comparison_summary": {
                "type": "string",
                "description": "画像所見と計測値差分を統合した比較サマリー。診断ではなく観察補助として記載する。",
            },
            "improved_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "改善している可能性がある姿勢傾向。",
            },
            "worsened_or_remaining_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "悪化と断定せず、注意・再確認・継続対応が必要な姿勢傾向。",
            },
            "unchanged_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "大きな変化が見られない、または継続確認が必要な点。",
            },
            "measurement_based_findings": {
                "type": "array",
                "items": {"type": "string"},
                "description": "comparison_jsonのbefore、after、delta、trendを根拠にした計測値ベースの所見。",
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
            "clinical_check_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "施術者が触診・動作評価・症状確認で確かめるべきポイント。",
            },
            "treatment_focus_suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "施術方針の候補。断定せず施術者判断の補助として記載する。",
            },
            "home_care_suggestions": {
                "type": "array",
                "items": {"type": "string"},
                "description": "患者へ説明可能な安全な範囲のセルフケア候補。",
            },
            "next_session_check_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": "次回施術・次回撮影で重点的に確認すべき姿勢、動作、症状。",
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
            "overall_comparison_summary",
            "improved_points",
            "worsened_or_remaining_points",
            "unchanged_points",
            "measurement_based_findings",
            "body_area_comparison",
            "clinical_check_points",
            "treatment_focus_suggestions",
            "home_care_suggestions",
            "next_session_check_points",
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

REQUIRED_ASSESSMENT_RISK_NOTES = [
    "画像解析は撮影角度、立ち位置、服装、カメラ距離の影響を受けます。",
    "本結果は診断ではなく、施術者の評価補助として扱ってください。",
    "痛み、しびれ、筋力低下、夜間痛などがある場合は画像だけで判断せず、問診・徒手検査・必要に応じた医療機関への相談を優先してください。",
]

REQUIRED_COMPARISON_RISK_NOTES = [
    "画像解析は撮影角度・立ち位置・服装・カメラ距離の影響を受けるため、同条件での再確認が必要です。",
    "計測値は診断ではなく、施術者による姿勢評価・触診・動作確認の補助として扱ってください。",
    "痛みや神経症状が強い場合は画像だけで判断せず、問診・徒手検査・必要に応じた医療機関への相談を優先してください。",
]

PRIVATE_CONTEXT_KEYS = {
    "name",
    "full_name",
    "patient_name",
    "first_name",
    "last_name",
    "kana",
    "phone",
    "phone_number",
    "email",
    "address",
    "postal_code",
    "birth_date",
    "birthday",
    "dob",
    "patient_id",
    "user_id",
    "氏名",
    "名前",
    "患者名",
    "ふりがな",
    "電話",
    "電話番号",
    "メール",
    "住所",
    "郵便番号",
    "生年月日",
}


def _is_private_context_key(key):
    normalized = str(key).strip().lower()
    return normalized in PRIVATE_CONTEXT_KEYS


def _sanitize_ai_context(value, patient):
    if isinstance(value, dict):
        return {
            key: _sanitize_ai_context(item, patient)
            for key, item in value.items()
            if key != "meta" and not _is_private_context_key(key)
        }

    if isinstance(value, list):
        return [
            _sanitize_ai_context(item, patient)
            for item in value[:30]
        ]

    if not isinstance(value, str):
        return value

    last_name = getattr(patient, "last_name", "") or ""
    first_name = getattr(patient, "first_name", "") or ""
    identifiers = {
        last_name,
        first_name,
        f"{last_name} {first_name}".strip(),
        f"{last_name}{first_name}".strip(),
    }

    sanitized = value
    for identifier in sorted(
        (item for item in identifiers if item),
        key=len,
        reverse=True,
    ):
        sanitized = sanitized.replace(identifier, "[匿名]")

    sanitized = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        "[メール情報省略]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"(?<!\d)(?:0\d{1,4}[-ー－]?\d{1,4}[-ー－]?\d{3,4})(?!\d)",
        "[電話情報省略]",
        sanitized,
    )

    return sanitized[:3000]


def _select_context_fields(data, allowed_keys):
    if not isinstance(data, dict):
        return {}

    return {
        key: data.get(key)
        for key in allowed_keys
        if data.get(key) not in (None, "", [], {})
    }


def _build_assessment_clinical_context(assessment):
    patient = assessment.patient
    context = {}

    if assessment.memo:
        context["assessment_memo"] = assessment.memo

    appointment = assessment.appointment
    if appointment:
        appointment_context = {
            "menu": appointment.menu,
            "notes": appointment.notes,
        }
        context["appointment"] = {
            key: value
            for key, value in appointment_context.items()
            if value
        }

    treatment_session = assessment.treatment_session
    if treatment_session:
        session_summary = treatment_session.active_summary or {}
        if not isinstance(session_summary, dict):
            session_summary = {}

        context["treatment_session"] = {
            "title": treatment_session.title or "",
            "memo": treatment_session.memo or "",
            "session_summary": _select_context_fields(
                session_summary.get("session_summary") or {},
                [
                    "chief_complaint",
                    "overall_summary",
                    "progress_change",
                ],
            ),
            "clinical_assessment": _select_context_fields(
                session_summary.get("clinical_assessment") or {},
                [
                    "checked_areas",
                    "pain_areas",
                    "movement_tests",
                    "findings",
                    "suspected_causes",
                    "treatment_intent",
                ],
            ),
            "soap": _select_context_fields(
                session_summary.get("soap") or {},
                ["S", "O", "A", "P"],
            ),
        }

    clinical_note = assessment.clinical_note
    if clinical_note:
        extract = clinical_note.extract_json or {}
        soap = clinical_note.soap_json or {}
        web_snapshot = clinical_note.web_intake_snapshot or {}
        if not isinstance(extract, dict):
            extract = {}
        if not isinstance(soap, dict):
            soap = {}
        if not isinstance(web_snapshot, dict):
            web_snapshot = {}

        snapshot_payload = web_snapshot.get("payload") or {}
        if not isinstance(snapshot_payload, dict):
            snapshot_payload = {}

        context["clinical_note"] = {
            "extract": _select_context_fields(
                extract,
                [
                    "chief_complaint",
                    "overall_summary",
                    "progress_change",
                    "symptom_type",
                    "severity_0_10",
                    "locations",
                    "qualities",
                    "symptom_details",
                    "worse_when",
                    "better_when",
                    "checked_areas",
                    "pain_areas",
                    "movement_tests",
                    "findings",
                    "suspected_causes",
                    "treatment_intent",
                ],
            ),
            "soap": _select_context_fields(
                soap,
                ["S", "O", "A", "P"],
            ),
            "followups": clinical_note.followups_json or [],
            "web_intake": {
                **_select_context_fields(
                    web_snapshot,
                    [
                        "chief_complaint",
                        "onset",
                        "symptom_type",
                    ],
                ),
                "extract": _select_context_fields(
                    snapshot_payload.get("extract") or {},
                    [
                        "chief_complaint",
                        "severity_0_10",
                        "locations",
                        "qualities",
                        "symptom_details",
                        "worse_when",
                        "better_when",
                    ],
                ),
                "symptoms": _select_context_fields(
                    snapshot_payload.get("symptoms") or {},
                    [
                        "areas",
                        "severity",
                        "qualities",
                        "symptom_details",
                        "worse_when",
                        "better_when",
                        "free_text",
                    ],
                ),
            },
        }

    return _sanitize_ai_context(context, patient)


def _has_meaningful_context(value):
    if isinstance(value, dict):
        return any(_has_meaningful_context(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_meaningful_context(item) for item in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value not in (None, False)


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
    姿勢画像と匿名化した主訴情報をAI分析し、構造化JSONを返す。

    注意:
    - 医療診断ではない
    - 施術者の観察補助
    - 画像だけで断定しない
    - 患者氏名など不要な個人情報を送らない
    - S3保存/ローカル保存どちらでも動作する
    """
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY が設定されていません。")

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    patient = assessment.patient
    image_content = _build_image_content(assessment)
    image_count = assessment.images.count()
    model_name = getattr(settings, "OPENAI_VISION_MODEL", "gpt-4o-mini")
    clinical_context = _build_assessment_clinical_context(assessment)
    has_clinical_context = _has_meaningful_context(clinical_context)
    clinical_context_text = (
        json.dumps(clinical_context, ensure_ascii=False, indent=2)
        if has_clinical_context
        else "主訴・施術メモ情報なし。画像所見のみで整理してください。"
    )

    prompt = f"""
あなたは接骨院・整体院の施術者を支援する、姿勢観察・アライメント評価補助AIです。
以下の正面・右側面・背面画像と、匿名化された主訴・施術情報をもとに、現場で確認しやすい構造化分析を作成してください。

# プライバシー
- 匿名患者として扱う
- 氏名、連絡先、住所などの個人情報を推測・出力しない
- meta.privacy_mode は "no_patient_name" とする

# 匿名化された主訴・施術情報
{clinical_context_text}

# 目的
- 正面・右側面・背面の各画像を分けて評価する
- 関節・部位ごとに観察所見、可能性、施術者が確認すべき点を整理する
- 前額面・矢状面・背面・重心の観点でアライメントを整理する
- 主訴情報がある場合のみ、姿勢所見との関連仮説を整理する
- 施術前の触診、可動域、筋力、動作、神経学的所見の確認ポイントを示す
- 患者さんへ不安を煽らず説明できる文章を作る

# 必ず守るルール
- 医療診断名を断定しない
- 画像だけで病名、原因、骨格変形、筋力低下を確定しない
- 「傾向があります」「可能性があります」「確認が必要です」「施術者の評価と合わせて判断します」を使う
- 画像から確認できない触診所見、可動域、筋力、疼痛誘発、神経症状は推測で確定しない
- 危険な断定、治療保証、改善保証はしない
- 施術者の判断を補助する表現にする
- 左右や前後の方向を記載する場合は、画像上で確認できる範囲に限定する
- 撮影条件による見え方の差を考慮する

# 正面画像の評価観点
- 頭部の左右傾き
- 肩の高さ差
- 体幹の左右偏位
- 骨盤の高さ差
- 膝の向き、ニーイン・ニーアウト傾向
- 足部の向きと左右差
- 左右荷重の偏りの可能性
- 正面から見た全体バランス

# 右側面画像の評価観点
- 頭部前方位
- 耳・肩・股関節・膝・足首の位置関係
- 猫背傾向、胸椎後弯傾向
- 骨盤前傾・後傾の可能性
- 膝の過伸展・軽度屈曲傾向
- 重心の前後偏位
- 首・肩・腰・膝への負担の可能性

# 背面画像の評価観点
- 後頭部・首の傾き
- 肩甲帯の左右差
- 肩甲骨位置の左右差
- 背部ライン、脊柱偏位の可能性
- 骨盤の左右差
- 下肢ラインの左右差
- 足部・踵の傾きの可能性

# 関節別評価
joint_assessments の各部位について、次の3項目を必ず記載してください。
- summary: 画像上の位置関係と全体要約
- possible_findings: 考えられる姿勢傾向。診断名ではなく仮説
- check_points: 施術者が問診・触診・可動域・筋力・動作評価で確認すべき具体項目

# 主訴との関連
- 主訴・症状情報がある場合、symptom_relation_hypotheses に姿勢所見との関連仮説を記載する
- 因果関係は断定しない
- 主訴情報がない場合、symptom_relation_hypotheses は空配列にする
- 症状と画像所見が一致しない可能性も明記する

# 必須の注意事項
risk_notes には、少なくとも次の内容を必ず含めてください。
1. 画像解析は撮影角度、立ち位置、服装、カメラ距離の影響を受ける
2. 本結果は診断ではなく、施術者の評価補助である
3. 痛み、しびれ、筋力低下、夜間痛などがある場合は画像だけで判断しない

# 出力品質
- important_points は施術者が最初に確認すべき内容を3〜6件に絞る
- view_summaries は画像ごとの所見を簡潔にまとめる。画像がない方向は評価不可とする
- posture_findings は部位別の全体傾向をまとめる
- alignment_observations は観察事実と仮説を混同しない
- clinical_notes は施術者が現場で使える確認項目にする
- treatment_suggestions は施術方針の候補として書く
- home_care_suggestions は症状を悪化させない安全な候補に限定する
- patient_explanation は会話でそのまま使える、やさしく前向きな文章にする
- report_summary_for_patient は患者向けレポートに載せられる簡潔な文章にする
- meta は source="posture_assessment"、assessment_id={assessment.id}、model="{model_name}"、
  image_count={image_count}、schema_version=2、privacy_mode="no_patient_name" とする
""".strip()

    response = client.responses.create(
        model=model_name,
        input=[
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "あなたは接骨院・整体院向けの姿勢観察・アライメント評価補助AIです。"
                            "診断ではなく、施術者の問診・触診・動作評価・患者説明を補助してください。"
                            "患者氏名など不要な個人情報を出力しないでください。"
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

    result = _sanitize_ai_context(result, patient)

    if not has_clinical_context:
        result["symptom_relation_hypotheses"] = []

    posture_findings = result.get("posture_findings")
    if not isinstance(posture_findings, dict):
        posture_findings = {}

    ankle_foot = (
        posture_findings.get("ankle_foot")
        or posture_findings.get("foot")
        or ""
    )
    posture_findings["ankle_foot"] = ankle_foot
    posture_findings["foot"] = ankle_foot
    result["posture_findings"] = posture_findings

    risk_notes = result.get("risk_notes")
    if not isinstance(risk_notes, list):
        risk_notes = []

    for required_note in REQUIRED_ASSESSMENT_RISK_NOTES:
        if required_note not in risk_notes:
            risk_notes.append(required_note)

    result["risk_notes"] = risk_notes
    result["patient_explanation"] = (
        result.get("patient_explanation")
        or "画像から確認できる姿勢の傾向を整理しました。症状や動き方も一緒に確認しながら、無理のない範囲で整えていきましょう。"
    )
    result["report_summary_for_patient"] = (
        result.get("report_summary_for_patient")
        or result["patient_explanation"]
    )
    result["meta"] = {
        "source": "posture_assessment",
        "assessment_id": assessment.id,
        "model": model_name,
        "image_count": image_count,
        "schema_version": 2,
        "privacy_mode": "no_patient_name",
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
    before = comparison.before_assessment
    after = comparison.after_assessment

    image_content = _build_comparison_image_content(comparison)

    before_summary = _sanitize_ai_context(
        before.get_active_summary() or {},
        patient,
    )
    after_summary = _sanitize_ai_context(
        after.get_active_summary() or {},
        patient,
    )
    comparison_title = _sanitize_ai_context(comparison.title, patient)
    comparison_memo = _sanitize_ai_context(comparison.memo or "-", patient)
    before_title = _sanitize_ai_context(before.title, patient)
    before_memo = _sanitize_ai_context(before.memo or "-", patient)
    after_title = _sanitize_ai_context(after.title, patient)
    after_memo = _sanitize_ai_context(after.memo or "-", patient)
    comparison_data = comparison.comparison_json or {}
    comparison_items = comparison_data.get("items") or {}
    comparison_data_text = (
        json.dumps(comparison_data, ensure_ascii=False, indent=2)
        if comparison_items
        else "計測値差分データなし。画像と既存AI分析結果を中心に比較してください。"
    )

    prompt = f"""
あなたは接骨院・整骨院向けの姿勢Before/After比較補助AIです。
以下のBefore画像、After画像、既存のAI姿勢分析結果、計測値差分、比較メモをもとに、姿勢の変化を整理してください。

# 患者情報
- 匿名患者として扱い、氏名などの個人情報は出力しない

# 比較情報
- 比較タイトル: {comparison_title}
- 比較メモ: {comparison_memo}

# Before情報
- Before撮影日: {before.created_at.strftime("%Y-%m-%d %H:%M")}
- Beforeタイトル: {before_title}
- Beforeメモ: {before_memo}
- Before AI分析結果:
{json.dumps(before_summary, ensure_ascii=False, indent=2)}

# After情報
- After撮影日: {after.created_at.strftime("%Y-%m-%d %H:%M")}
- Afterタイトル: {after_title}
- Afterメモ: {after_memo}
- After AI分析結果:
{json.dumps(after_summary, ensure_ascii=False, indent=2)}

# Before/After計測値差分
{comparison_data_text}

# 計測値差分の読み方
- before / after は各撮影時の参考計測値
- delta は after - before
- trend が improved の場合は、絶対値が小さくなった参考判定
- trend が worsened の場合は、絶対値が大きくなった参考判定
- trend が unchanged の場合は、閾値内で大きな差を確認しにくい参考判定
- trend が unknown の場合は、数値だけでは判断できない
- trendをそのまま医学的改善・悪化と断定せず、画像所見と施術者評価を合わせて解釈する

# 目的
- 施術者がBefore/Afterの変化を短時間で把握できるようにする
- 計測値差分と画像所見が一致する点、不一致の可能性がある点を整理する
- 改善している可能性がある点を整理する
- 大きく変化していない点を整理する
- 施術者が触診・動作評価・症状確認で確かめるべき点を整理する
- 次回施術の重点候補と安全なセルフケア候補を整理する
- 患者さんに前向きに説明できる文章を作る

# 必ず守るルール
- 医療診断名を断定しない
- 画像だけで原因を確定しない
- 計測値は診断値ではなく、姿勢観察と施術者評価を補助する参考値として扱う
- 「改善しています」と断定せず「整ってきている可能性」「軽減しているように見える」などにする
- 「悪化」と断定せず「引き続き確認が必要」「撮影条件の影響も考えられる」と表現する
- 撮影角度、立ち位置、服装、カメラ距離、光の条件で画像と計測値に誤差が出ることを考慮する
- 患者説明は不安を煽らず、前向きでわかりやすくする
- 施術者の判断を補助する表現にする
- measurement_based_findingsには、利用可能なcomparison_jsonの具体的な項目名・方向・trendを根拠として含める
- comparison_jsonが空の場合はmeasurement_based_findingsを空配列にし、画像と既存AI分析結果だけで比較する
- risk_notesには必ず次の3点を含める
  1. 画像解析は撮影角度・立ち位置・服装・カメラ距離の影響を受ける
  2. 数値は診断ではなく、施術者の評価補助として扱う
  3. 痛みや神経症状が強い場合は画像だけで判断しない

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

# 出力品質
- overall_comparison_summaryは画像所見と計測値差分を統合して簡潔にまとめる
- measurement_based_findingsは数値を過大評価せず「傾向」「可能性」「確認が必要」を用いる
- clinical_check_pointsは施術者が現場で確認できる具体的な評価項目にする
- treatment_focus_suggestionsは施術方針の候補として記載する
- patient_explanationは改善の可能性と継続確認点を患者さんに説明しやすい表現にする
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

    if not comparison_items:
        result["measurement_based_findings"] = []

    risk_notes = result.get("risk_notes")
    if not isinstance(risk_notes, list):
        risk_notes = []

    for required_note in REQUIRED_COMPARISON_RISK_NOTES:
        if required_note not in risk_notes:
            risk_notes.append(required_note)

    result["risk_notes"] = risk_notes
    result["meta"] = {
        "source": "posture_comparison",
        "comparison_id": comparison.id,
        "before_assessment_id": before.id,
        "after_assessment_id": after.id,
        "model": getattr(settings, "OPENAI_VISION_MODEL", "gpt-4o-mini"),
        "before_image_count": before.images.count(),
        "after_image_count": after.images.count(),
        "measurement_comparison_available": bool(comparison_items),
        "storage_safe": True,
    }

    return result
