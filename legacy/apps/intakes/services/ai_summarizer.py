# apps/intakes/services/ai_summarizer.py
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

from openai import OpenAI

# SDK例外（バージョン差吸収：無くても動く）
try:
    from openai import BadRequestError, APIError, APITimeoutError, RateLimitError
except Exception:  # pragma: no cover
    BadRequestError = APIError = APITimeoutError = RateLimitError = Exception


# ✅ summary_json のスキーマ（JSON Schema）
SUMMARY_JSON_SCHEMA: Dict[str, Any] = {
    "name": "intake_summary",
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["version", "soap", "extract", "followups", "meta"],
        "properties": {
            "version": {"type": "string"},
            "soap": {
                "type": "object",
                "additionalProperties": False,
                "required": ["S", "O", "A", "P"],
                "properties": {
                    "S": {"type": "array", "items": {"type": "string"}},
                    "O": {"type": "array", "items": {"type": "string"}},
                    "A": {"type": "array", "items": {"type": "string"}},
                    "P": {"type": "array", "items": {"type": "string"}},
                },
            },
            "extract": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "chief_complaint",
                    "onset",
                    "trigger",
                    "severity_0_10",
                    "locations",
                    "qualities",
                    "symptom_type",
                    "red_flags",
                ],
                "properties": {
                    "chief_complaint": {"type": "string"},
                    "onset": {"type": "string"},
                    "trigger": {"type": "string"},
                    "severity_0_10": {"type": ["integer", "null"], "minimum": 0, "maximum": 10},
                    "locations": {"type": "array", "items": {"type": "string"}},
                    "qualities": {"type": "array", "items": {"type": "string"}},
                    "symptom_type": {"type": "string", "enum": ["acute", "chronic", "unknown"]},
                    "red_flags": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["present", "notes"],
                        "properties": {
                            "present": {"type": "boolean"},
                            "notes": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
            "followups": {"type": "array", "items": {"type": "string"}},
            "meta": {
                "type": "object",
                "additionalProperties": False,
                # ✅ propertiesにあるキーは required に全列挙（ここが落とし穴）
                "required": ["language", "model"],
                "properties": {
                    "language": {"type": "string"},
                    "model": {"type": "string"},
                },
            },
        },
    },
}

SYSTEM_PROMPT = """あなたは接骨院の施術者を支援する医療記録アシスタントです。
入力は「施術者」と「患者」の会話文字起こしです。最終判断は施術者が行うため、あなたは事実整理に徹してください。

【出力要件】
- 出力は必ず JSON Schema に“厳密準拠”してください（余計なキー禁止）。
- 断定できない場合は推測しない：unknown/空文字/null/空配列で返す。
- 文章は日本語、医療記録として簡潔に（1項目 = 1事実）。
- SOAP はすべて配列（箇条書き）で返す。各要素は短文（40字程度目安）。
- meta.language は必ず "ja"、meta.model は必ず使用モデル名を入れる。
- version は必ず "1.0" を入れる。

【SOAPの書き方】
S: 主観（症状、痛み、しびれ、困りごと、経過、増悪/寛解、既往、服薬、生活への影響）
O: 客観（観察可能/測定可能な情報。会話から“客観として言える”内容のみ）
A: 評価（問題リスト・可能性・鑑別の方向性。断定診断は避け、〜疑い/〜の可能性で）
P: 計画（次回までの方針、セルフケア、注意喚起、追加確認、検査/紹介の検討）

【抽出(extract)】
- chief_complaint: 主訴を1文で
- onset: 発症時期（例: 昨日/2-3日前/1週間前/数ヶ月前）
- trigger: きっかけ（動作・事故・仕事・運動など）
- severity_0_10: NRSが出ていれば採用（無ければ null）
- locations: 部位（左右含む）
- qualities: 性状（例: ズキズキ/鈍痛/刺す/しびれ/つっぱり/だるい/重い）
- symptom_type: acute/chronic/unknown（判断不能なら unknown）
- red_flags: present と notes（迷ったら false。過剰に赤くしない）

【followups（次に確認すべき質問）】
- 施術に必要で会話に無い項目を最大5つまで
"""

# client は使い回し
_client: Optional[OpenAI] = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY が設定されていません。")
        _client = OpenAI(api_key=api_key)
    return _client


def _extract_json_from_response(resp) -> Dict[str, Any]:
    """
    responses API + json_schema なら通常 output_text に JSON が入る。
    念のため output も走査。
    """
    text = getattr(resp, "output_text", None)
    if isinstance(text, str) and text.strip():
        return json.loads(text)

    output = getattr(resp, "output", None) or []
    for item in output:
        contents = getattr(item, "content", None) or []
        for c in contents:
            if isinstance(c, dict):
                t = c.get("text")
                if isinstance(t, str) and t.strip().startswith("{"):
                    return json.loads(t)
                j = c.get("json")
                if isinstance(j, dict):
                    return j
            else:
                t = getattr(c, "text", None)
                if isinstance(t, str) and t.strip().startswith("{"):
                    return json.loads(t)
                j = getattr(c, "json", None)
                if isinstance(j, dict):
                    return j

    raise RuntimeError("OpenAIレスポンスからJSONを抽出できませんでした。")


def _normalize_summary(data: Dict[str, Any], *, model: str) -> Dict[str, Any]:
    """
    strict を前提にしつつ、念のため出力を正規化して UI 側の事故を減らす。
    """
    if not isinstance(data, dict):
        data = {}

    # meta（必須なので“強制”）
    data["meta"] = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    data["meta"]["model"] = model
    data["meta"]["language"] = data["meta"].get("language") or "ja"

    # version（必須なので“強制”）
    data["version"] = data.get("version") or "1.0"

    # soap（必須）
    soap = data.get("soap") if isinstance(data.get("soap"), dict) else {}
    for k in ["S", "O", "A", "P"]:
        v = soap.get(k)
        if v is None:
            soap[k] = []
        elif isinstance(v, str):
            soap[k] = [v.strip()] if v.strip() else []
        elif isinstance(v, list):
            soap[k] = [str(x).strip() for x in v if str(x).strip()]
        else:
            s = str(v).strip()
            soap[k] = [s] if s else []
    data["soap"] = soap

    # extract（必須）
    ex = data.get("extract") if isinstance(data.get("extract"), dict) else {}
    # 欠けたキーを埋める（schema必須に合わせる）
    ex.setdefault("chief_complaint", "")
    ex.setdefault("onset", "")
    ex.setdefault("trigger", "")
    ex.setdefault("severity_0_10", None)
    ex.setdefault("locations", [])
    ex.setdefault("qualities", [])
    ex.setdefault("symptom_type", "unknown")
    ex.setdefault("red_flags", {"present": False, "notes": []})

    # locations / qualities 正規化
    for k in ["locations", "qualities"]:
        vv = ex.get(k)
        if vv is None:
            ex[k] = []
        elif isinstance(vv, str):
            ex[k] = [vv.strip()] if vv.strip() else []
        elif isinstance(vv, list):
            ex[k] = [str(x).strip() for x in vv if str(x).strip()]
        else:
            s = str(vv).strip()
            ex[k] = [s] if s else []

    # symptom_type 正規化
    if ex.get("symptom_type") not in ("acute", "chronic", "unknown"):
        ex["symptom_type"] = "unknown"

    # red_flags 正規化
    rf = ex.get("red_flags") if isinstance(ex.get("red_flags"), dict) else {}
    rf.setdefault("present", False)
    rf.setdefault("notes", [])
    if not isinstance(rf["present"], bool):
        rf["present"] = bool(rf["present"])
    if isinstance(rf["notes"], str):
        rf["notes"] = [rf["notes"].strip()] if rf["notes"].strip() else []
    elif isinstance(rf["notes"], list):
        rf["notes"] = [str(x).strip() for x in rf["notes"] if str(x).strip()]
    else:
        rf["notes"] = []
    ex["red_flags"] = rf

    data["extract"] = ex

    # followups（必須）
    fu = data.get("followups")
    if fu is None:
        data["followups"] = []
    elif isinstance(fu, list):
        data["followups"] = [str(x).strip() for x in fu if str(x).strip()]
    elif isinstance(fu, str):
        data["followups"] = [fu.strip()] if fu.strip() else []
    else:
        data["followups"] = []

    return data


def summarize_transcript(transcript_text: str, *, model: str = "gpt-4.1-mini") -> Dict[str, Any]:
    """
    文字起こし → summary_json（schema準拠）
    """
    if not transcript_text or not transcript_text.strip():
        # UI側で “空” を流してしまった事故対策
        return _normalize_summary({}, model=model)

    client = _get_client()

    try:
        resp = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "以下が会話の文字起こしです。\n"
                        "-----\n"
                        f"{transcript_text}\n"
                        "-----\n"
                        "この内容をSOAPと抽出情報に整理して返してください。"
                    ),
                },
            ],
            # ✅ responses API の Structured Outputs はここ
            text={
                "format": {
                    "type": "json_schema",
                    "name": SUMMARY_JSON_SCHEMA["name"],
                    "schema": SUMMARY_JSON_SCHEMA["schema"],
                    "strict": True,
                }
            },
        )

        data = _extract_json_from_response(resp)
        return _normalize_summary(data, model=model)

    except BadRequestError as e:
        # schema不整合、入力過大、など
        raise RuntimeError(f"AI要約に失敗しました（BadRequest）: {e}") from e
    except RateLimitError as e:
        raise RuntimeError(f"AI要約に失敗しました（RateLimit）: {e}") from e
    except APITimeoutError as e:
        raise RuntimeError(f"AI要約に失敗しました（Timeout）: {e}") from e
    except APIError as e:
        raise RuntimeError(f"AI要約に失敗しました（APIError）: {e}") from e
    except json.JSONDecodeError as e:
        raise RuntimeError(f"AI出力のJSON解析に失敗しました: {e}") from e


def intake_to_text(intake) -> str:
    """
    Intake（DB） + payload（Web問診）を、LLMに渡しやすいテキストへ整形する。
    個人情報（氏名/住所/電話など）は入れない方針。
    """
    if intake is None:
        return ""

    lines: List[str] = []

    if getattr(intake, "chief_complaint", ""):
        lines.append(f"主訴: {intake.chief_complaint}".strip())
    if getattr(intake, "symptom_type", ""):
        lines.append(f"症状タイプ: {intake.symptom_type}".strip())
    if getattr(intake, "onset", ""):
        lines.append(f"発症時期: {intake.onset}".strip())

    payload: Dict[str, Any] = getattr(intake, "payload", {}) or {}

    for i in range(1, 5):
        key = f"step{i}"
        step_data = payload.get(key)
        if not step_data:
            continue

        lines.append(f"\n[{key}]")
        if isinstance(step_data, dict):
            for k, v in step_data.items():
                if v in (None, "", [], {}):
                    continue
                if isinstance(v, list):
                    vv = " / ".join([str(x) for x in v if x not in (None, "")])
                else:
                    vv = str(v)
                lines.append(f"- {k}: {vv}")
        else:
            lines.append(str(step_data))

    # ai_summary は原則いれない（過去推測に引っ張られるため）
    return "\n".join(lines).strip()