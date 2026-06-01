import json
from typing import Any

from django.conf import settings
from openai import OpenAI


SESSION_SUMMARY_JSON_SCHEMA = {
    "name": "treatment_session_summary",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "important_points": {
                "type": "array",
                "items": {"type": "string"},
            },
            "session_summary": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "chief_complaint": {"type": "string"},
                    "visit_type": {
                        "type": "string",
                        "enum": ["initial", "followup", "unknown"],
                    },
                    "overall_summary": {"type": "string"},
                    "progress_change": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "pain_change": {"type": "string"},
                            "movement_change": {"type": "string"},
                            "daily_life_change": {"type": "string"},
                            "new_symptoms": {"type": "string"},
                            "patient_comment": {"type": "string"},
                        },
                        "required": [
                            "pain_change",
                            "movement_change",
                            "daily_life_change",
                            "new_symptoms",
                            "patient_comment",
                        ],
                    },
                },
                "required": [
                    "chief_complaint",
                    "visit_type",
                    "overall_summary",
                    "progress_change",
                ],
            },
            "clinical_assessment": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "checked_areas": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "pain_areas": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "movement_tests": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "findings": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "suspected_causes": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "treatment_intent": {"type": "string"},
                },
                "required": [
                    "checked_areas",
                    "pain_areas",
                    "movement_tests",
                    "findings",
                    "suspected_causes",
                    "treatment_intent",
                ],
            },
            "treatment": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "performed_treatments": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "target_areas": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "patient_response": {"type": "string"},
                    "after_treatment_change": {"type": "string"},
                },
                "required": [
                    "performed_treatments",
                    "target_areas",
                    "patient_response",
                    "after_treatment_change",
                ],
            },
            "explanation": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "explained_to_patient": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "lifestyle_guidance": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "home_care": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "cautions_until_next_visit": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "explained_to_patient",
                    "lifestyle_guidance",
                    "home_care",
                    "cautions_until_next_visit",
                ],
            },
            "next_plan": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "next_treatment_policy": {"type": "string"},
                    "recommended_visit_timing": {"type": "string"},
                    "items_to_check_next_time": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": [
                    "next_treatment_policy",
                    "recommended_visit_timing",
                    "items_to_check_next_time",
                ],
            },
            "soap": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "S": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "O": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "A": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "P": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                },
                "required": ["S", "O", "A", "P"],
            },
            "progress_note": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "short_summary": {"type": "string"},
                    "record_text": {"type": "string"},
                },
                "required": ["short_summary", "record_text"],
            },
            "relationship_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
            "missing_information": {
                "type": "array",
                "items": {"type": "string"},
            },
            "safety_notes": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
        "required": [
            "important_points",
            "session_summary",
            "clinical_assessment",
            "treatment",
            "explanation",
            "next_plan",
            "soap",
            "progress_note",
            "relationship_notes",
            "missing_information",
            "safety_notes",
        ],
    },
}


def _empty_summary() -> dict[str, Any]:
    return {
        "important_points": [],
        "session_summary": {
            "chief_complaint": "",
            "visit_type": "unknown",
            "overall_summary": "",
            "progress_change": {
                "pain_change": "",
                "movement_change": "",
                "daily_life_change": "",
                "new_symptoms": "",
                "patient_comment": "",
            },
        },
        "clinical_assessment": {
            "checked_areas": [],
            "pain_areas": [],
            "movement_tests": [],
            "findings": [],
            "suspected_causes": [],
            "treatment_intent": "",
        },
        "treatment": {
            "performed_treatments": [],
            "target_areas": [],
            "patient_response": "",
            "after_treatment_change": "",
        },
        "explanation": {
            "explained_to_patient": [],
            "lifestyle_guidance": [],
            "home_care": [],
            "cautions_until_next_visit": [],
        },
        "next_plan": {
            "next_treatment_policy": "",
            "recommended_visit_timing": "",
            "items_to_check_next_time": [],
        },
        "soap": {
            "S": [],
            "O": [],
            "A": [],
            "P": [],
        },
        "progress_note": {
            "short_summary": "",
            "record_text": "",
        },
        "relationship_notes": [],
        "missing_information": [],
        "safety_notes": [],
    }


def _safe_json_loads(text: str) -> dict[str, Any]:
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return _empty_summary()


def summarize_treatment_session(transcript_text: str) -> dict[str, Any]:
    """
    施術セッション専用AI要約。

    目的:
    - 問診ではなく、施術中の会話・評価・施術内容・説明・生活指導を整理する
    - ClinicalNote / TreatmentProgress / TreatmentPlan へ展開しやすいJSONにする
    - 不明な情報は推測せず、missing_information に入れる
    """

    transcript_text = (transcript_text or "").strip()

    if not transcript_text:
        return _empty_summary()

    client = OpenAI(api_key=settings.OPENAI_API_KEY)

    model = getattr(settings, "OPENAI_MODEL", "gpt-4o-mini")

    system_prompt = """
あなたは接骨院・整骨院向けの施術記録AIです。
あなたの役割は、施術中の会話、施術者の評価、実施した施術内容、患者への説明、生活指導、次回方針を、臨床記録として使いやすい形に整理することです。

最重要方針:
- 単なる会話要約ではなく、施術者が後からカルテ・施術経過・次回施術方針にそのまま使える記録を作成してください。
- 「患者が言ったこと」「施術者が確認したこと」「施術者が判断したこと」「実際に行ったこと」「次回見るべきこと」を必ず分けて整理してください。
- 音声文字起こしに含まれる事実を優先し、推測で診断名・疾患名・医学的断定をしないでください。
- ただし、施術者が会話内で示した評価・説明・意図は、臨床記録として分かりやすく整理してください。
- 不明な情報は無理に埋めず、missing_information に入れてください。

重要ポイント:
- important_points には、施術者が画面を開いた瞬間に把握すべき重要事項を3〜6個で出してください。
- 内容は「患者の現在の主訴」「前回からの変化」「施術者の評価」「施術意図」「次回確認すべきこと」を中心にしてください。
- 重要ポイントは短く、実務で使える文章にしてください。
- 例:
  - 腰部症状は軽減傾向だが、右膝痛が残存している
  - ジャンプ着地・切り返し・踏み込みで右膝痛が出る
  - 右膝だけでなく、右腰・股関節・臀部外側の硬さが膝負担に関与している可能性
  - 次回は競技動作時の膝負担と股関節・骨盤周囲の状態を再確認する

抽出ルール:
1. 患者の訴え
- 痛みの部位、痛みが出る動作、違和感、競技・日常生活で困っていることを抽出してください。
- 「右膝が痛い」「ジャンプ着地で痛い」「踏み込みで違和感」など、患者の言葉に近い形で整理してください。

2. 前回からの変化
- 通院・再診と思われる場合は、必ず前回からの変化を整理してください。
- 痛みの変化、動きやすさ、日常生活の変化、スポーツ動作での変化、新しい症状を分けてください。
- 「腰は楽になったが、右膝痛は残る」のように、改善点と残存課題を両方書いてください。

3. 施術者の評価・確認
- 施術者が確認した部位、動作、可動域、荷重、筋緊張、硬さ、違和感を整理してください。
- 膝の痛みでも、腰・股関節・臀部・大腿部など関連部位を確認している場合は必ず記録してください。
- checked_areas には確認した部位を入れてください。
- pain_areas には痛みや違和感が出ている部位を入れてください。
- findings には施術者が確認した具体的な所見を入れてください。
- suspected_causes には、断定ではなく「可能性」「関与が考えられる」表現で原因候補を入れてください。

4. 施術意図
- treatment_intent には「なぜその施術をしたのか」を書いてください。
- 例：
  - 膝局所だけでなく、股関節・臀部周囲の硬さを緩め、膝への負担軽減を狙う
  - バスケット動作時のジャンプ着地・切り返しでの膝負担を減らすため、下肢全体の連動性を整える
- 施術意図は短くてもよいので、必ず臨床的に意味のある文章にしてください。

5. 実施した施術
- performed_treatments には、実際に行った施術・調整・ストレッチ指導・動作確認を入れてください。
- target_areas には施術対象となった部位を入れてください。
- 会話から具体的手技名が不明な場合は、無理に手技名を作らず「右膝周囲の負担軽減を目的とした施術」「股関節周囲の硬さに対する施術」のように表現してください。

6. 患者反応・施術後変化
- 施術後に「軽い」「動きやすい」「違和感が減った」などがあれば必ず patient_response / after_treatment_change に入れてください。
- 変化がない、または不明な場合は無理に改善したと書かないでください。

7. 説明・生活指導・セルフケア
- 施術者が患者に説明した内容、注意点、運動制限、ストレッチ、セルフケア、入浴・運動・スポーツ復帰の注意を分けてください。
- 特に「痛みが出る動作は無理に続けない」「ストレッチは気持ちいい程度」などの具体指示を残してください。

8. 次回方針
- next_treatment_policy には、次回施術で何を確認し、何を狙うかを書いてください。
- items_to_check_next_time には、次回チェックすべき動作・部位・症状を具体的に入れてください。
- スポーツ患者の場合は、競技動作に関する確認項目を優先してください。
- 例：ジャンプ着地、切り返し、踏み込み、荷重時の右膝痛、股関節周囲の硬さ。

9. SOAP
- Sは患者の主観的訴えのみ。
- Oは施術者が確認した客観的所見、動作確認、触診、可動域、硬さなど。
- Aは評価。断定せず、可能性・傾向として書く。
- Pは施術方針、生活指導、次回確認事項。
- 各項目は配列で、短く実用的にしてください。

10. 経過記録
- progress_note.record_text は、そのまま施術経過記録に近い文章として使えるようにしてください。
- 「前回より腰部症状は軽減。右膝痛は残存し、ジャンプ着地・切り返し・踏み込みで痛みあり。右膝周囲に加え、右腰・股関節周囲の硬さを確認。膝への負担軽減を目的に施術し、ストレッチと痛みの出る動作の制限を指導。次回は膝の荷重時痛と股関節・骨盤周囲の状態を再確認する。」
  のような実務向け文章にしてください。

11. 患者対応メモ
- relationship_notes には、患者対応に役立つ軽い情報のみ入れてください。
- 例：バスケットをしている、試合が近い、仕事で座位が多い、育児で抱っこが多い。
- センシティブな私生活情報、家庭トラブル、金銭、政治、宗教などは記録しないでください。

安全ルール:
- 音声にない内容を創作しないでください。
- 医師の診断のような断定表現は避けてください。
- 「炎症がある」と断定せず、会話に基づき「炎症や負担が残っている可能性」のように表現してください。
- 不明な場合は missing_information に入れてください。
- 日本語で出力してください。
- 必ず指定JSONスキーマに一致するJSONのみを返してください。
"""

    user_prompt = f"""
以下は、接骨院の施術セッション中の音声文字起こしです。
この内容を、施術者が後からカルテ・施術経過・次回方針に使えるように整理してください。

今回特に重視すること:
- 画面上部に表示する重要ポイント
- 患者の訴え
- 前回からの変化
- 施術者が確認した部位・動作・硬さ・痛み
- 痛みの出る動作
- 施術者がどこを狙って施術したか
- 実施した施術内容
- 施術後の患者反応
- 患者への説明
- 生活指導・セルフケア
- 次回までの注意点
- 次回施術で確認すべきこと
- SOAP
- 施術経過記録として使える文章
- 患者対応に役立つ軽い会話メモ

文字起こし:
---
{transcript_text}
---
"""

    try:
        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            text={
                "format": {
                    "type": "json_schema",
                    "name": SESSION_SUMMARY_JSON_SCHEMA["name"],
                    "schema": SESSION_SUMMARY_JSON_SCHEMA["schema"],
                    "strict": True,
                }
            },
        )

        output_text = response.output_text
        data = _safe_json_loads(output_text)

        return data

    except Exception:
        raise