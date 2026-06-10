# apps/staff/views.py
import json
import re
from calendar import monthrange
from datetime import date, timedelta

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.db import transaction
from django.db.models import Q, Case, When, Value, IntegerField
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.http import require_POST

from apps.ai_jobs.usecases import run_ai_draft
from apps.appointments.models import Appointment
from apps.charts.models import ChartNote
from apps.clinical_notes.models import ClinicalNote, ClinicalNoteHistory
from apps.clinics.models import Clinic
from apps.intakes.forms import AREA_CHOICES, VISIT_TYPE_CHOICES, SYMPTOM_TYPE_CHOICES
from apps.intakes.models import Intake, InterviewRecording
from apps.patients.models import Patient
from apps.staff.decorators import staff_required
from apps.staff.forms import ClinicalNoteEditForm
from apps.treatment_plans.models import TreatmentPlan
from apps.visits.models import Visit

from .forms import StaffCreateForm
from apps.ai_usage.services import build_ai_usage_summary
from apps.posture_assessments.models import PostureAssessment

INTAKE_FIELD_LABELS = {
    "visit_type": "来院種別",
    "symptom_type": "症状タイプ",
    "chief_complaint": "主訴",
    "onset": "いつから",
    "since": "いつから",
    "trigger": "きっかけ",
    "areas": "痛みの部位",
    "pain_level": "痛みの強さ",
    "severity": "痛みの強さ",
    "pain_qualities": "症状の感じ",
    "qualities": "症状の感じ",
    "other_quality_text": "その他の症状詳細",
    "other_area_text": "その他の部位",
    "free_text": "自由記入",
    "followup_type": "再診区分",
    "followup_change": "前回との変化",
    "followup_change_detail": "変化の詳細",
    "followup_comment": "気になる変化・コメント",
    "agreement": "同意",
    "agreed": "同意",
    "consent_agreed": "同意",
    "confirm_profile": "登録情報確認",
    "source": "来院経路",
    "job": "職業",
    "note": "備考",
    "other_clinic": "他院通院",
    "other_clinic_note": "他院通院メモ",
    "taking_meds": "服薬中",
    "meds_note": "服薬メモ",
    "past_history": "既往歴",
    "history_note": "既往歴メモ",
    "final_note": "最後に伝えたいこと",
    "meta": "進行情報",
    "step1": "ステップ1",
    "step2": "ステップ2",
    "step3": "ステップ3",
    "step4": "ステップ4",
    "symptoms": "症状情報",
    "history": "既往歴など",
    "consent": "同意",
    "branch_selected": "分岐選択済み",
    "intake_mode": "問診モード",
    "current_step": "現在ステップ",
    "completed_steps": "完了ステップ",
}

INTAKE_VALUE_LABELS = {
    "new_issue": "新しい症状",
    "followup": "再診",
    "unknown": "わからない",
    "normal": "通常問診",
    "acute": "急性",
    "chronic": "慢性",
    "2_3days": "2〜3日前",
    "today": "今日",
    "yesterday": "昨日",
    "within_week": "1週間以内",
    "over_week": "1週間以上前",
    "over_month": "1か月以上前",
    "shoulder_r": "右肩",
    "shoulder_l": "左肩",
    "waist": "腰",
    "neck": "首",
    "back": "背中",
    "knee_r": "右ひざ",
    "knee_l": "左ひざ",
    "hip_r": "右股関節",
    "hip_l": "左股関節",
    "elbow_r": "右ひじ",
    "elbow_l": "左ひじ",
    "wrist_r": "右手首",
    "wrist_l": "左手首",
    "ankle_r": "右足首",
    "ankle_l": "左足首",
    "sharp": "鋭い痛み",
    "dull": "鈍い痛み",
    "numb": "しびれ",
    "tight": "張る感じ",
    "heavy": "重だるい",
    "swollen": "腫れぼったい",
    "hot": "熱っぽい",
    "web": "Web予約",
    "walkin": "直接来院",
    "yes": "あり",
    "no": "なし",
    "true": "はい",
    "false": "いいえ",
    "numbness": "しびれ",
    "swelling": "腫れ",
    "heat": "熱感",
    "limited_motion": "動かしにくい",
    "weakness": "力が入りにくい",
    "stiff": "こわばり",
    "tingle": "しびれ",
    "右手背": "右手の甲",
    "右手掌": "右手のひら",
    "左手背": "左手の甲",
    "左手掌": "左手のひら",
    "左背部後": "左背部",
    "右背部後": "右背部",
    "背中中央後": "背中中央",
    "右手首前": "右手首",
    "左手首前": "左手首",
    "右足首前": "右足首",
    "左足首前": "左足首",
    "右手首後": "右手首後ろ",
    "左手首後": "左手首後ろ",
    "右足首後": "右足首後ろ",
    "左足首後": "左足首後ろ",
}

User = get_user_model()


def get_current_clinic(request):
    if hasattr(request.user, "clinic") and request.user.clinic_id:
        return request.user.clinic
    return Clinic.objects.order_by("id").first()


def _compact_dashboard_text(value, fallback="", limit=52):
    if isinstance(value, dict):
        value = value.get("summary") or value.get("possible_findings") or ""

    if isinstance(value, (list, tuple)):
        value = next(
            (
                item
                for item in value
                if isinstance(item, str) and item.strip()
            ),
            "",
        )

    text = " ".join(str(value or "").split())
    if not text:
        return fallback

    for separator in ("。", "！", "？", "\n"):
        text = text.split(separator, 1)[0].strip()

    if len(text) > limit:
        return f"{text[:limit - 1].rstrip()}…"
    return text


def _dashboard_text_list(value):
    if isinstance(value, str):
        value = [value]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []

    texts = []
    for item in value:
        if isinstance(item, dict):
            item = (
                item.get("text")
                or item.get("summary")
                or item.get("label")
                or ""
            )
        text = " ".join(str(item or "").split())
        if text:
            texts.append(text)
    return texts


def _compact_profile_findings(values, fallback="", limit=68):
    texts = []
    for value in values:
        for item in _dashboard_text_list(value):
            text = _compact_dashboard_text(item, limit=42)
            if text and text not in texts:
                texts.append(text)
            if len(texts) >= 2:
                break
        if len(texts) >= 2:
            break

    combined = "、".join(texts)
    if not combined:
        return fallback
    if len(combined) > limit:
        return f"{combined[:limit - 1].rstrip()}…"
    return combined


SPORT_KEYWORDS = {
    "バスケット": ("バスケ", "バスケット"),
    "野球": ("野球",),
    "サッカー": ("サッカー", "フットサル"),
    "テニス": ("テニス",),
    "バレー": ("バレー", "バレーボール"),
    "ゴルフ": ("ゴルフ",),
    "ランニング": ("ランニング", "ジョギング", "マラソン"),
    "陸上": ("陸上",),
    "柔道": ("柔道",),
    "ダンス": ("ダンス",),
    "水泳": ("水泳", "スイミング"),
    "卓球": ("卓球",),
    "バドミントン": ("バドミントン",),
    "ラグビー": ("ラグビー",),
}

LIFESTYLE_KEYWORDS = {
    "デスクワーク": ("デスクワーク", "事務仕事"),
    "長時間座位": ("長時間座位", "座りっぱなし", "座位時間"),
    "立ち仕事": ("立ち仕事", "立位時間"),
    "重量物作業": ("重量物", "重い物", "荷物を持", "持ち上げ"),
    "運転": ("運転", "ドライバー"),
    "介護": ("介護",),
    "育児": ("育児", "抱っこ"),
    "中腰": ("中腰",),
    "前かがみ": ("前かがみ", "前屈姿勢"),
    "パソコン作業": ("パソコン", "PC作業"),
    "スマホ時間": ("スマホ", "携帯を見る"),
    "睡眠不足": ("睡眠不足", "寝不足"),
    "片足荷重": ("片足荷重", "片側荷重"),
}

MOVEMENT_KEYWORDS = {
    "長時間座位": ("長時間座位", "座りっぱなし", "座位時間"),
    "立位作業": ("立ち仕事", "長時間立位"),
    "中腰": ("中腰",),
    "前かがみ": ("前かがみ", "前屈"),
    "重量物の持ち上げ": ("重量物", "重い物", "持ち上げ"),
    "階段": ("階段",),
    "歩行": ("歩行", "歩く"),
    "走行": ("走る", "ランニング", "ダッシュ"),
    "ジャンプ・着地": ("ジャンプ", "着地"),
    "投球": ("投球", "ピッチング"),
    "ラケット動作": ("ラケット", "スマッシュ", "サーブ"),
    "スイング": ("スイング",),
    "握り動作": ("握る", "グリップ"),
}


def _flatten_profile_text(value, depth=0):
    if depth > 5 or value in (None, "", [], {}):
        return []
    if isinstance(value, str):
        text = " ".join(value.split())
        return [text] if text else []
    if isinstance(value, dict):
        texts = []
        for item in value.values():
            texts.extend(_flatten_profile_text(item, depth + 1))
        return texts
    if isinstance(value, (list, tuple, set)):
        texts = []
        for item in value:
            texts.extend(_flatten_profile_text(item, depth + 1))
        return texts
    return []


def _find_profile_values(data, keys):
    if not isinstance(data, (dict, list, tuple)):
        return []

    wanted = {key.lower() for key in keys}
    values = []

    def walk(value, depth=0):
        if depth > 5:
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if str(key).lower() in wanted:
                    values.extend(_flatten_profile_text(item))
                walk(item, depth + 1)
        elif isinstance(value, (list, tuple)):
            for item in value:
                walk(item, depth + 1)

    walk(data)
    return list(dict.fromkeys(values))


def _matched_profile_labels(text, mapping):
    return [
        label
        for label, keywords in mapping.items()
        if any(keyword.lower() in text.lower() for keyword in keywords)
    ]


def extract_keywords_from_patient_sources(
    patient,
    latest_intake=None,
    latest_note=None,
    latest_plan=None,
    latest_assessment=None,
    summary=None,
):
    intake_payload = (
        latest_intake.payload
        if latest_intake and isinstance(latest_intake.payload, dict)
        else {}
    )
    note_extract = (
        latest_note.extract_json
        if latest_note and isinstance(latest_note.extract_json, dict)
        else {}
    )
    note_soap = (
        latest_note.soap_json
        if latest_note and isinstance(latest_note.soap_json, dict)
        else {}
    )
    note_snapshot = (
        latest_note.web_intake_snapshot
        if latest_note and isinstance(latest_note.web_intake_snapshot, dict)
        else {}
    )
    summary = summary if isinstance(summary, dict) else {}

    structured_sources = [
        intake_payload,
        note_extract,
        note_soap,
        note_snapshot,
        summary,
    ]
    source_texts = []
    for source in structured_sources:
        source_texts.extend(_flatten_profile_text(source))

    if latest_intake:
        source_texts.extend(_flatten_profile_text(latest_intake.chief_complaint))
    if latest_note:
        source_texts.extend(_flatten_profile_text(latest_note.followups_json))
    if latest_plan:
        source_texts.extend(_flatten_profile_text({
            "chief_complaint": latest_plan.chief_complaint,
            "exercise_instruction": latest_plan.exercise_instruction,
            "work_instruction": latest_plan.work_instruction,
            "lifestyle_other_instruction": latest_plan.lifestyle_other_instruction,
            "caution_notes": latest_plan.caution_notes,
        }))
    if latest_assessment:
        source_texts.extend(_flatten_profile_text(latest_assessment.memo))

    source_texts = list(dict.fromkeys(text for text in source_texts if text))
    combined_text = " ".join(source_texts)

    job_values = []
    for source in structured_sources:
        job_values.extend(_find_profile_values(
            source,
            ("job", "occupation", "work", "work_style", "仕事内容", "職業"),
        ))

    position_values = []
    for source in structured_sources:
        position_values.extend(_find_profile_values(
            source,
            ("position", "sport_position", "competition_position", "守備位置"),
        ))
    if not position_values:
        position_match = re.search(
            r"(?:ポジション|守備位置)\s*[：:は]?\s*([^\s、。/]{1,16})",
            combined_text,
        )
        if position_match:
            candidate = position_match.group(1).strip()
            if candidate not in {"確認", "未登録", "不明", "なし"}:
                position_values.append(candidate)

    pain_triggers = []
    for source in structured_sources:
        pain_triggers.extend(_find_profile_values(
            source,
            (
                "worse_when",
                "pain_trigger",
                "pain_triggers",
                "aggravating_factors",
                "悪化する時",
                "痛みが出る動作",
            ),
        ))
    pain_triggers = list(dict.fromkeys(
        _compact_dashboard_text(item, limit=34)
        for item in pain_triggers
        if item
    ))[:4]

    note_values = []
    for source in structured_sources:
        note_values.extend(_find_profile_values(
            source,
            (
                "note",
                "final_note",
                "caution",
                "caution_notes",
                "next_check_points",
                "items_to_check_next_time",
            ),
        ))
    if latest_plan and latest_plan.caution_notes:
        note_values.append(latest_plan.caution_notes)
    if latest_assessment and latest_assessment.memo:
        note_values.append(latest_assessment.memo)

    return {
        "source_texts": source_texts,
        "combined_text": combined_text,
        "sports": _matched_profile_labels(combined_text, SPORT_KEYWORDS),
        "lifestyle": _matched_profile_labels(combined_text, LIFESTYLE_KEYWORDS),
        "movements": _matched_profile_labels(combined_text, MOVEMENT_KEYWORDS),
        "job_values": list(dict.fromkeys(job_values)),
        "position_values": list(dict.fromkeys(position_values)),
        "pain_triggers": pain_triggers,
        "notes": list(dict.fromkeys(
            _compact_dashboard_text(item, limit=52)
            for item in note_values
            if item
        ))[:3],
    }


def build_patient_context_profile(
    patient,
    latest_intake=None,
    latest_note=None,
    latest_plan=None,
    latest_assessment=None,
    summary=None,
):
    extracted = extract_keywords_from_patient_sources(
        patient,
        latest_intake=latest_intake,
        latest_note=latest_note,
        latest_plan=latest_plan,
        latest_assessment=latest_assessment,
        summary=summary,
    )

    sports = extracted["sports"]
    lifestyle = extracted["lifestyle"]
    movements = extracted["movements"]
    job_values = extracted["job_values"]

    sports_display = " / ".join(sports) if sports else "未登録"
    position = (
        _compact_dashboard_text(extracted["position_values"][0], limit=30)
        if extracted["position_values"]
        else "未登録"
    )
    work_parts = []
    if job_values:
        work_parts.append(_compact_dashboard_text(job_values[0], limit=34))
    for item in lifestyle:
        if (
            item in {"デスクワーク", "立ち仕事", "重量物作業", "運転", "介護", "育児"}
            and not any(item in existing for existing in work_parts)
        ):
            work_parts.append(item)
    work_style = " / ".join(work_parts[:3]) if work_parts else "未登録"
    lifestyle_display = " / ".join(lifestyle[:4]) if lifestyle else "未登録"
    movement_display = " / ".join(movements[:4]) if movements else "未登録"
    pain_triggers_display = (
        " / ".join(extracted["pain_triggers"])
        if extracted["pain_triggers"]
        else "未登録"
    )
    notes_display = (
        extracted["notes"]
        if extracted["notes"]
        else []
    )

    summary_parts = []
    if sports:
        summary_parts.append(f"競技：{'・'.join(sports[:2])}")
    if work_style != "未登録":
        summary_parts.append(f"仕事：{work_style}")
    if lifestyle:
        summary_parts.append(f"生活負荷：{'・'.join(lifestyle[:2])}")

    has_context = bool(
        sports
        or extracted["position_values"]
        or job_values
        or lifestyle
        or movements
        or extracted["pain_triggers"]
        or extracted["notes"]
    )

    return {
        "sports": sports_display,
        "sports_items": sports,
        "position": position,
        "work_style": work_style,
        "lifestyle": lifestyle_display,
        "lifestyle_items": lifestyle,
        "common_movements": movement_display,
        "movement_items": movements,
        "pain_triggers": pain_triggers_display,
        "pain_trigger_items": extracted["pain_triggers"],
        "notes": notes_display,
        "summary": " / ".join(summary_parts) if summary_parts else "背景情報は未登録です。",
        "has_context": has_context,
        "source_texts": extracted["source_texts"],
        "combined_text": extracted["combined_text"],
    }


def _context_support_for_region(context_profile, region_key):
    if not isinstance(context_profile, dict):
        return "", []

    sports = set(context_profile.get("sports_items") or [])
    lifestyle = set(context_profile.get("lifestyle_items") or [])
    movements = set(context_profile.get("movement_items") or [])
    notes = []
    tags = []

    def add(targets, text, tag):
        if region_key in targets and text not in notes:
            notes.append(text)
            if tag not in tags:
                tags.append(tag)

    if sports & {"バスケット", "サッカー", "バレー", "ランニング", "陸上", "ラグビー"}:
        add({"hip", "knee", "ankle_foot"}, "競技時の荷重バランスを確認", "競技動作")
    if sports & {"野球"} or "投球" in movements:
        add({"shoulder", "thoracic_spine", "elbow", "wrist_forearm"}, "投球動作との関連を確認", "投球")
    if sports & {"テニス", "バドミントン", "卓球"} or "ラケット動作" in movements:
        add({"shoulder", "thoracic_spine", "elbow", "wrist_forearm"}, "ラケット動作との関連を確認", "ラケット")
    if sports & {"ゴルフ"} or "スイング" in movements:
        add({"thoracic_spine", "lumbar_spine", "pelvis", "hip", "elbow", "wrist_forearm"}, "スイング時の連動を確認", "スイング")
    if sports & {"水泳"}:
        add({"shoulder", "thoracic_spine"}, "反復動作と肩甲帯の連動を確認", "水泳")
    if sports & {"柔道", "ダンス"}:
        add({"thoracic_spine", "pelvis", "hip", "knee", "ankle_foot"}, "競技特有の可動域と支持性を確認", "競技動作")

    if lifestyle & {"デスクワーク", "長時間座位", "パソコン作業", "スマホ時間"}:
        add({"head", "neck", "thoracic_spine", "lumbar_spine", "pelvis"}, "座位姿勢による負担を確認", "座位負荷")
    if lifestyle & {"立ち仕事"}:
        add({"pelvis", "knee", "ankle_foot"}, "立位時の左右荷重を確認", "立位負荷")
    if lifestyle & {"重量物作業", "介護", "育児", "中腰", "前かがみ"}:
        add({"lumbar_spine", "pelvis", "hip"}, "持ち上げ・前屈動作を確認", "作業負荷")
    if lifestyle & {"片足荷重"}:
        add({"pelvis", "hip", "knee", "ankle_foot"}, "片側荷重の傾向を確認", "左右荷重")

    return (notes[0] if notes else ""), tags[:2]


def build_body_profile_items(summary, context_profile=None):
    summary = summary if isinstance(summary, dict) else {}
    posture_findings = summary.get("posture_findings") or {}
    joint_assessments = summary.get("joint_assessments") or {}
    if not isinstance(posture_findings, dict):
        posture_findings = {}
    if not isinstance(joint_assessments, dict):
        joint_assessments = {}

    suspected_load_areas = _dashboard_text_list(summary.get("suspected_load_areas"))
    alignment_observations = summary.get("alignment_observations") or {}
    alignment_items = []
    if isinstance(alignment_observations, dict):
        for value in alignment_observations.values():
            alignment_items.extend(_dashboard_text_list(value))
    else:
        alignment_items = _dashboard_text_list(alignment_observations)

    symptom_hypotheses = _dashboard_text_list(summary.get("symptom_relation_hypotheses"))
    clinical_notes = _dashboard_text_list(summary.get("clinical_notes"))
    next_check_points = _dashboard_text_list(summary.get("next_check_points"))

    specs = (
        {
            "key": "head", "label": "頭部", "joints": ("head",),
            "posture_keys": ("head_neck",),
            "keywords": ("頭", "頭部", "前方位", "側屈"),
            "fallback": "前方位・左右傾き・回旋は未評価",
            "aspects": {
                "前方位": ("前方位", "前方偏位"),
                "左右傾き": ("側屈", "左右傾", "傾き"),
                "回旋": ("頭部回旋", "回旋"),
            },
        },
        {
            "key": "neck", "label": "頸部", "joints": ("neck",),
            "posture_keys": ("head_neck",),
            "keywords": ("首", "頚", "頸"),
            "fallback": "屈伸・側屈・回旋可動域は未評価",
            "aspects": {
                "屈曲 / 伸展": ("屈曲", "伸展"),
                "側屈": ("側屈",),
                "回旋": ("回旋",),
            },
        },
        {
            "key": "shoulder", "label": "肩", "joints": ("shoulder",),
            "posture_keys": ("shoulder",),
            "keywords": ("肩", "肩甲"),
            "fallback": "左右差・巻き肩・肩甲帯位置は未評価",
            "aspects": {
                "左右高さ": ("左右差", "高さ", "下制", "挙上"),
                "巻き肩": ("巻き肩",),
                "肩甲帯": ("肩甲",),
            },
        },
        {
            "key": "thoracic_spine", "label": "胸椎 / 背中",
            "joints": ("thoracic_spine",), "posture_keys": ("spine",),
            "keywords": ("背", "胸椎", "脊柱"),
            "fallback": "後弯・回旋・背部緊張は未評価",
            "aspects": {
                "後弯": ("後弯", "猫背"),
                "回旋": ("回旋",),
                "背部緊張": ("緊張", "張り"),
            },
        },
        {
            "key": "lumbar_spine", "label": "腰椎",
            "joints": ("lumbar_pelvis",), "posture_keys": ("spine", "pelvis"),
            "keywords": ("腰", "腰椎", "前弯", "反り腰"),
            "fallback": "前後弯・反り腰・座位負荷は未評価",
            "aspects": {
                "前弯 / 後弯": ("前弯", "後弯"),
                "反り腰": ("反り腰",),
                "座位負荷": ("座位", "デスクワーク"),
            },
        },
        {
            "key": "pelvis", "label": "骨盤",
            "joints": ("lumbar_pelvis",), "posture_keys": ("pelvis",),
            "keywords": ("骨盤", "腰", "臀"),
            "fallback": "前後傾・左右傾斜・回旋は未評価",
            "aspects": {
                "前傾 / 後傾": ("前傾", "後傾"),
                "左右傾斜": ("左右差", "左右傾", "下制"),
                "回旋": ("回旋",),
                "片側荷重": ("片足荷重", "片側荷重"),
            },
        },
        {
            "key": "hip", "label": "股関節", "joints": ("hip",),
            "posture_keys": ("hip", "pelvis"),
            "keywords": ("股関節", "股", "臀", "内旋", "外旋"),
            "fallback": "内外旋・屈伸・内外転は未評価",
            "aspects": {
                "内旋 / 外旋": ("内旋", "外旋"),
                "屈曲 / 伸展": ("屈曲", "伸展"),
                "外転 / 内転": ("外転", "内転"),
            },
        },
        {
            "key": "knee", "label": "膝", "joints": ("knee",),
            "posture_keys": ("knee",),
            "keywords": ("膝", "ニーイン", "ニーアウト", "膝蓋"),
            "fallback": "膝の向き・回旋・伸展位は未評価",
            "aspects": {
                "ニーイン / アウト": ("ニーイン", "ニーアウト"),
                "回旋ストレス": ("内旋", "外旋", "回旋"),
                "過伸展 / 屈曲": ("過伸展", "軽度屈曲"),
                "膝蓋骨": ("膝蓋",),
            },
        },
        {
            "key": "ankle_foot", "label": "足部 / 足首",
            "joints": ("ankle_foot",), "posture_keys": ("ankle_foot", "foot"),
            "keywords": ("足", "足首", "足関節", "踵", "アーチ", "つま先"),
            "fallback": "回内外・足先・アーチ・荷重は未評価",
            "aspects": {
                "回内 / 回外": ("回内", "回外"),
                "つま先": ("つま先", "足先", "外向き", "内向き"),
                "アーチ": ("アーチ",),
                "踵": ("踵", "かかと"),
                "荷重": ("荷重",),
            },
        },
        {
            "key": "elbow", "label": "肘", "joints": ("elbow",),
            "posture_keys": ("elbow",),
            "keywords": ("肘", "肘関節", "内側上顆", "外側上顆"),
            "fallback": "内側ストレス・伸展は必要時に評価",
            "aspects": {
                "内側ストレス": ("内側", "ストレス"),
                "伸展": ("伸展",),
                "投球 / ラケット": ("投球", "ラケット"),
            },
            "optional": True,
        },
        {
            "key": "wrist_forearm", "label": "手首 / 前腕",
            "joints": ("wrist", "forearm", "wrist_forearm"),
            "posture_keys": ("wrist", "forearm"),
            "keywords": ("手首", "手関節", "前腕", "回内", "回外", "握る"),
            "fallback": "回内外・掌背屈・握り動作は必要時に評価",
            "aspects": {
                "回内 / 回外": ("回内", "回外"),
                "掌屈 / 背屈": ("掌屈", "背屈"),
                "握り動作": ("握る", "グリップ"),
            },
            "optional": True,
        },
    )

    check_words = (
        "負担", "左右差", "傾き", "偏位", "前方", "下制", "挙上",
        "巻き肩", "後弯", "前弯", "前傾", "後傾", "ニーイン",
        "ニーアウト", "制限", "回旋", "内旋", "外旋", "回内",
        "回外", "ストレス", "確認", "注意", "可能性", "緊張",
    )
    good_words = ("良好", "安定", "改善", "目立たない", "整って")

    items = []
    for spec in specs:
        joint_sources = []
        for joint_key in spec["joints"]:
            joint = joint_assessments.get(joint_key) or {}
            if isinstance(joint, dict):
                joint_sources.extend([
                    joint.get("summary"),
                    joint.get("possible_findings"),
                    joint.get("check_points"),
                ])
            elif joint:
                joint_sources.append(joint)

        def related(items):
            return [
                item for item in items
                if any(keyword in item for keyword in spec["keywords"])
            ]

        posture_sources = [
            posture_findings.get(key)
            for key in spec["posture_keys"]
            if posture_findings.get(key)
        ]
        related_alignment = related(alignment_items)
        related_hypotheses = related(symptom_hypotheses)
        related_loads = related(suspected_load_areas)
        related_clinical = related(clinical_notes + next_check_points)
        context_note, context_tags = _context_support_for_region(
            context_profile,
            spec["key"],
        )

        source_groups = [
            joint_sources,
            posture_sources,
            related_alignment,
            related_hypotheses,
            related_loads,
            related_clinical,
        ]
        source_values = next((group for group in source_groups if any(group)), [])
        has_clinical_source = bool(source_values)
        if not source_values and context_note:
            source_values = [context_note]

        text = _compact_profile_findings(
            source_values,
            fallback=spec["fallback"],
            limit=76,
        )
        level_source = " ".join([
            text,
            *related_alignment,
            *related_hypotheses,
            *related_loads,
            *related_clinical,
        ])

        if not has_clinical_source and not context_note:
            level = "unassessed"
        elif context_note and not has_clinical_source:
            level = "check"
        elif related_loads or any(word in level_source for word in check_words):
            level = "check"
        elif any(word in level_source for word in good_words):
            level = "good"
        else:
            level = "info"

        evidence_source = " ".join([
            *_flatten_profile_text(source_values),
            *related_alignment,
            *related_hypotheses,
            *related_loads,
            *related_clinical,
        ])
        tags = []
        if level != "unassessed":
            tags = [
                label
                for label, keywords in spec["aspects"].items()
                if any(keyword in evidence_source for keyword in keywords)
            ]
        for tag in context_tags:
            if not any(tag in existing or existing in tag for existing in tags):
                tags.append(tag)
        if not tags:
            tags = ["必要時に評価"] if level == "unassessed" else ["参考所見"]

        items.append({
            "key": spec["key"],
            "label": spec["label"],
            "text": text,
            "level": level,
            "tags": tags[:3],
            "context_note": context_note,
        })

    return items


def _build_patient_body_profile(summary, context_profile=None):
    return build_body_profile_items(summary, context_profile=context_profile)


def _is_staff_user(user, clinic=None):
    if not user or not user.is_authenticated:
        return False

    if user.is_superuser:
        return True

    valid_roles = {
        getattr(User.Role, "ADMIN", "admin"),
        getattr(User.Role, "RECEPTION", "reception"),
        getattr(User.Role, "PRACTITIONER", "practitioner"),
    }

    if getattr(user, "role", None) not in valid_roles:
        return False

    if clinic is not None and hasattr(user, "clinic_id"):
        if user.clinic_id != clinic.id:
            return False

    return True


def _format_answer_value(value):
    if value in [None, "", []]:
        return "-"
    if isinstance(value, list):
        return "、".join(str(v) for v in value if str(v).strip()) or "-"
    if isinstance(value, bool):
        return "はい" if value else "いいえ"
    return str(value)


def _jp_label(key):
    return INTAKE_FIELD_LABELS.get(str(key), str(key))


def _jp_value(value):
    if value in [None, "", []]:
        return "-"

    if isinstance(value, bool):
        return "はい" if value else "いいえ"

    if isinstance(value, list):
        return "、".join(_jp_value(v) for v in value) or "-"

    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            lines.append(f"{_jp_label(k)}：{_jp_value(v)}")
        return "\n".join(lines) if lines else "-"

    s = str(value)
    return INTAKE_VALUE_LABELS.get(s, s)


def staff_login_view(request):
    if request.user.is_authenticated:
        return redirect("staff:dashboard")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "").strip()

        user = authenticate(request, username=username, password=password)
        if user is None:
            messages.error(request, "IDまたはパスワードが正しくありません。")
            return render(request, "staff/login.html")

        clinic = getattr(user, "clinic", None)
        if not _is_staff_user(user, clinic):
            messages.error(request, "スタッフ用アカウントではありません。")
            return render(request, "staff/login.html")

        login(request, user)
        return redirect("staff:dashboard")

    return render(request, "staff/login.html")


@require_POST
def staff_logout_view(request):
    logout(request)
    return redirect("/")


@staff_required
def staff_dashboard_view(request):
    clinic = get_current_clinic(request)
    today = timezone.localdate()

    ai_usage_summary = build_ai_usage_summary(clinic)
    ai_usage_percent_for_bar = min(ai_usage_summary.usage_percent, 100)


    todays_appts = (
        Appointment.objects
        .select_related("patient", "assigned_staff", "intake")
        .filter(
            clinic=clinic,
            start_at__date=today,
        )
        .order_by("start_at")
    )

    total_appointment_count = todays_appts.count()

    waiting_qs = todays_appts.filter(
        status__in=[
            Appointment.Status.BOOKED,
            Appointment.Status.ARRIVED,
        ]
    )

    waiting_count = waiting_qs.count()

    done_count = todays_appts.filter(
        status=Appointment.Status.COMPLETED
    ).count()

    intake_count = Intake.objects.filter(
        clinic=clinic,
        submitted_at__date=today,
    ).count()

    not_intake_count = todays_appts.filter(
        intake__isnull=True
    ).count()

    next_appt = waiting_qs.first()
    appt_cards = todays_appts[:5]

    active_plan_count = 0
    paused_plan_count = 0
    completed_plan_count = 0
    today_progress_count = 0

    ai_count = intake_count
    note_count = intake_count

    return render(request, "staff/dashboard.html", {
        "active": "home",
        "page_title": "Dashboard",
        "today": today,

        "total_appointment_count": total_appointment_count,
        "waiting_count": waiting_count,
        "done_count": done_count,

        "intake_count": intake_count,
        "not_intake_count": not_intake_count,
        "ai_count": ai_count,
        "note_count": note_count,

        "active_plan_count": active_plan_count,
        "paused_plan_count": paused_plan_count,
        "completed_plan_count": completed_plan_count,
        "today_progress_count": today_progress_count,

        "next_appt": next_appt,
        "appointments": appt_cards,

        "ai_usage_summary": ai_usage_summary,
        "ai_usage_percent_for_bar": ai_usage_percent_for_bar,
    })

@staff_required
def staff_intake_view(request):
    return render(request, "staff/intake.html", {
        "active": "intake",
        "page_title": "問診",
    })


@staff_required
def staff_appointments_view(request):
    clinic = get_current_clinic(request)
    today = timezone.localdate()

    day_str = request.GET.get("day") or today.isoformat()
    period = (request.GET.get("period") or "day").strip()
    if period not in ["day", "week", "month", "year"]:
        period = "day"

    staff_id = request.GET.get("staff", "")
    status = request.GET.get("status", "")
    q = (request.GET.get("q", "") or "").strip()

    base_day = parse_date(day_str) or today
    range_start, range_end, range_label = _get_period_range(base_day, period)

    qs = (
        Appointment.objects
        .select_related("patient", "assigned_staff", "intake")
        .filter(
            clinic=clinic,
            start_at__date__gte=range_start,
            start_at__date__lte=range_end,
        )
        .order_by("start_at")
    )

    if staff_id:
        qs = qs.filter(assigned_staff_id=staff_id)

    if status:
        qs = qs.filter(status=status)

    if q:
        qs = qs.filter(
            Q(patient__last_name__icontains=q) |
            Q(patient__first_name__icontains=q) |
            Q(patient__phone__icontains=q) |
            Q(menu__icontains=q) |
            Q(notes__icontains=q)
        )

    appointments = list(qs)

    for a in appointments:
        intake = getattr(a, "intake", None)
        summary = _build_staff_intake_summary(intake)

        a.has_intake = summary["has_intake"]
        a.intake_completed = summary["intake_completed"]
        a.visit_type_label = summary["visit_type_label"]
        a.chief_label = summary["chief_label"]
        a.areas_display = summary["areas_display"]
        a.pain_level_display = summary["pain_level_display"]
        a.intake_kind_label = summary["intake_kind_label"]

        parts = []
        if a.chief_label:
            parts.append(a.chief_label)
        if a.areas_display:
            parts.append("、".join(a.areas_display))
        if a.pain_level_display:
            parts.append(a.pain_level_display)
        if a.visit_type_label:
            parts.append(a.visit_type_label)
        a.intake_one_line = " / ".join(parts) if parts else "-"

    base = (
        Appointment.objects
        .select_related("intake")
        .filter(
            clinic=clinic,
            start_at__date__gte=range_start,
            start_at__date__lte=range_end,
        )
    )
    base_list = list(base)

    stats = {
        "total": len(base_list),
        "not_done": sum(1 for x in base_list if not getattr(getattr(x, "intake", None), "submitted_at", None)),
        "done": sum(1 for x in base_list if getattr(getattr(x, "intake", None), "submitted_at", None)),
        "arrived": sum(1 for x in base_list if x.status == Appointment.Status.ARRIVED),
    }

    staff_users = User.objects.filter(
        clinic=clinic,
        is_active=True,
        role__in=[
            User.Role.ADMIN,
            User.Role.RECEPTION,
            User.Role.PRACTITIONER,
        ],
    ).order_by("username")

    context = {
        "active": "appointments",
        "page_title": "予約管理",
        "day": base_day,
        "period": period,
        "range_start": range_start,
        "range_end": range_end,
        "range_label": range_label,
        "appointments": appointments,
        "stats": stats,
        "staff_users": staff_users,
        "filter_staff": staff_id,
        "filter_status": status,
        "filter_q": q,
        "status_choices": Appointment.Status.choices,
    }

    context["calendar_events"] = _build_calendar_events(appointments)
    context["calendar_day_summary"] = _build_calendar_day_summary(appointments)

    if period == "day":
        context["timeline"] = _build_day_timeline_rows(
            appointments=appointments,
            staff_users=staff_users,
            base_day=base_day,
        )

    return render(request, "staff/appointments_calendar.html", context)


@staff_required
def staff_list(request):
    clinic = get_current_clinic(request)

    users = User.objects.filter(
        clinic=clinic,
        is_active=True,
        role__in=[
            User.Role.ADMIN,
            User.Role.RECEPTION,
            User.Role.PRACTITIONER,
        ],
    ).order_by("last_name", "first_name", "username")

    staff_cards = []
    for user in users:
        full_name = user.get_full_name().strip() or user.username
        staff_cards.append({
            "id": user.id,
            "full_name": full_name,
            "username": user.username,
            "email": user.email,
            "is_superuser": user.is_superuser,
            "is_staff": user.is_staff,
            "role": user.get_role_display() if hasattr(user, "get_role_display") else user.role,
            "today_appointments": 0,
            "active_plans": 0,
            "status_label": "稼働中" if user.is_active else "停止中",
            "status_class": "running" if user.is_active else "stopped",
        })

    return render(request, "staff/staff_list.html", {
        "active": "staffs",
        "page_title": "担当者一覧",
        "staff_cards": staff_cards,
    })


def superuser_required(user):
    return user.is_authenticated and user.is_superuser


@login_required
@user_passes_test(superuser_required)
def staff_create(request):
    clinic = get_current_clinic(request)

    if request.method == "POST":
        form = StaffCreateForm(request.POST, clinic=clinic)
        if form.is_valid():
            form.save()
            messages.success(request, "スタッフを登録しました。")
            return redirect("staff:staff_list")
    else:
        form = StaffCreateForm(clinic=clinic)

    return render(request, "staff/staff_create.html", {
        "active": "staffs",
        "page_title": "スタッフ追加",
        "form": form,
    })


@staff_required
def staff_patient_search_view(request):
    clinic = get_current_clinic(request)
    q = (request.GET.get("q") or "").strip()

    qs = Patient.objects.filter(clinic=clinic).order_by("last_name", "first_name")
    if q:
        qs = qs.filter(
            Q(last_name__icontains=q) |
            Q(first_name__icontains=q) |
            Q(phone__icontains=q)
        )

    patients = qs[:50]

    return render(request, "staff/patients/search.html", {
        "active": "patient_search",
        "page_title": "患者検索",
        "q": q,
        "patients": patients,
    })


@staff_required
def staff_manual_view(request):
    return render(request, "staff/manual.html", {
        "active": "manual",
        "page_title": "操作マニュアル",
    })


@staff_required
def staff_settings_view(request):
    return render(request, "staff/placeholder.html", {
        "active": "settings",
        "page_title": "設定",
    })


def _choice_dict(choices):
    return dict(choices)


def _labels_from_codes(values, choices):
    if not values:
        return []

    cmap = dict(choices)

    if isinstance(values, list):
        return [cmap.get(v, v) for v in values if v]

    if isinstance(values, str):
        values = [v.strip() for v in values.split(",") if v.strip()]
        return [cmap.get(v, v) for v in values]

    return []


def _build_staff_intake_summary(intake):
    data = {
        "has_intake": False,
        "intake_completed": False,
        "visit_type_label": "",
        "chief_label": "",
        "areas_display": [],
        "pain_level_display": "",
        "intake_kind_label": "",
    }

    if not intake:
        return data

    data["has_intake"] = True
    data["intake_completed"] = bool(getattr(intake, "submitted_at", None))

    payload = intake.payload or {}
    extract = payload.get("extract", {}) or {}
    symptoms = payload.get("symptoms", {}) or {}
    step2 = payload.get("step2", {}) or {}
    step3 = payload.get("step3", {}) or {}

    visit_type = payload.get("visit_type") or getattr(intake, "visit_type", "") or ""
    data["visit_type_label"] = _jp_value(visit_type)
    data["intake_kind_label"] = "再診簡易問診" if visit_type == "followup" else "通常問診"

    chief = (
        extract.get("chief_complaint")
        or step2.get("chief_complaint")
        or getattr(intake, "chief_complaint", "")
        or ""
    )
    data["chief_label"] = chief

    areas = (
        extract.get("locations")
        or step3.get("areas")
        or symptoms.get("areas")
        or []
    )
    data["areas_display"] = [_jp_value(x) for x in areas] if areas else []

    pain_level = (
        extract.get("severity_0_10")
        or step3.get("severity")
        or symptoms.get("severity")
        or getattr(intake, "pain_level", None)
    )

    if pain_level not in [None, ""]:
        data["pain_level_display"] = f"{pain_level}/10"

    return data


def _get_period_range(base_day, period):
    if period == "week":
        start = base_day - timedelta(days=base_day.weekday())
        end = start + timedelta(days=6)
        label = f"{start.strftime('%Y/%m/%d')} 〜 {end.strftime('%Y/%m/%d')}"
        return start, end, label

    if period == "month":
        start = base_day.replace(day=1)
        last_day = monthrange(base_day.year, base_day.month)[1]
        end = base_day.replace(day=last_day)
        label = f"{base_day.year}年{base_day.month}月"
        return start, end, label

    if period == "year":
        start = date(base_day.year, 1, 1)
        end = date(base_day.year, 12, 31)
        label = f"{base_day.year}年"
        return start, end, label

    label = base_day.strftime("%Y/%m/%d")
    return base_day, base_day, label


def _build_calendar_events(appointments):
    events = []

    for a in appointments:
        intake = getattr(a, "intake", None)
        summary = _build_staff_intake_summary(intake)

        patient_name = "（患者未確定）"
        if a.patient:
            patient_name = f"{a.patient.last_name} {a.patient.first_name}"

        chief = summary["chief_label"] or "主訴未入力"
        intake_state = "問診未着手"
        if summary["has_intake"]:
            intake_state = "問診完了" if summary["intake_completed"] else "問診入力中"

        visit_type = summary["visit_type_label"] or "-"
        pain = summary["pain_level_display"] or "-"
        areas = "、".join(summary["areas_display"]) if summary["areas_display"] else "-"

        if a.status == Appointment.Status.CANCELLED:
            bg = "#fee2e2"
            border = "#ef4444"
            text = "#991b1b"
        elif a.status == Appointment.Status.ARRIVED:
            bg = "#cffafe"
            border = "#06b6d4"
            text = "#164e63"
        elif summary["has_intake"] and summary["intake_completed"]:
            bg = "#dbeafe"
            border = "#3b82f6"
            text = "#1e3a8a"
        elif summary["has_intake"] and not summary["intake_completed"]:
            bg = "#ffedd5"
            border = "#f97316"
            text = "#9a3412"
        else:
            bg = "#f8fafc"
            border = "#cbd5e1"
            text = "#0f172a"

        events.append({
            "id": str(a.id),
            "title": patient_name,
            "start": a.start_at.isoformat(),
            "end": a.end_at.isoformat() if getattr(a, "end_at", None) else None,
            "backgroundColor": bg,
            "borderColor": border,
            "textColor": text,
            "extendedProps": {
                "appointmentId": a.id,
                "patientName": patient_name,
                "menu": a.menu or "-",
                "staffName": a.assigned_staff.username if a.assigned_staff else "未割当",
                "statusLabel": a.get_status_display(),
                "intakeState": intake_state,
                "intakeCompleted": summary["intake_completed"],
                "intakeKindLabel": summary["intake_kind_label"] or "-",
                "visitTypeLabel": visit_type,
                "chiefLabel": chief,
                "painLevelDisplay": pain,
                "areasDisplay": areas,
                "status": a.status,
                "intakeDetailUrl": reverse("staff:intake_detail", args=[a.intake.id]) if intake else "",
                "recordingUrl": reverse("intakes:recording_new", args=[a.id]),
                "dayUrl": f"{reverse('staff:appointments')}?period=day&day={a.start_at.date().isoformat()}",
            }
        })

    return events


def _is_filled(value):
    return value not in [None, "", [], {}]


def _deep_find_value(data, target_key):
    if isinstance(data, dict):
        if target_key in data and _is_filled(data.get(target_key)):
            return data.get(target_key)

        for _, v in data.items():
            found = _deep_find_value(v, target_key)
            if _is_filled(found):
                return found

    elif isinstance(data, list):
        for item in data:
            found = _deep_find_value(item, target_key)
            if _is_filled(found):
                return found

    return None


def _payload_get(payload, *keys):
    for key in keys:
        found = _deep_find_value(payload, key)
        if _is_filled(found):
            return found
    return None


def _build_calendar_day_summary(appointments):
    summary = {}

    for a in appointments:
        day_key = a.start_at.date().isoformat()
        intake = getattr(a, "intake", None)
        intake_summary = _build_staff_intake_summary(intake)

        if day_key not in summary:
            summary[day_key] = {
                "total": 0,
                "not_done": 0,
                "first_visit": 0,
            }

        summary[day_key]["total"] += 1

        if not intake_summary["intake_completed"]:
            summary[day_key]["not_done"] += 1

        visit_type_label = intake_summary.get("visit_type_label", "") or ""
        menu_text = (a.menu or "").strip()

        if visit_type_label == "初診" or "初診" in menu_text:
            summary[day_key]["first_visit"] += 1

    return summary

def _minutes_from_time(dt, base_day):
    local_dt = timezone.localtime(dt)
    return local_dt.hour * 60 + local_dt.minute


def _build_day_timeline_rows(appointments, staff_users, base_day):
    """
    日表示用：横型スケジュール表データを作成する。
    横軸は 9:00〜19:00、縦軸は施術者。
    """
    start_hour = 8
    end_hour = 20
    start_minutes = start_hour * 60
    end_minutes = end_hour * 60
    total_minutes = end_minutes - start_minutes

    staff_map = {}

    for user in staff_users:
        staff_name = user.get_full_name().strip() or user.username
        staff_map[str(user.id)] = {
            "staff_id": user.id,
            "staff_name": staff_name,
            "appointments": [],
        }

    unassigned_key = "unassigned"
    staff_map[unassigned_key] = {
        "staff_id": None,
        "staff_name": "未割当",
        "appointments": [],
    }

    for a in appointments:
        intake = getattr(a, "intake", None)
        summary = _build_staff_intake_summary(intake)

        patient_name = "（患者未確定）"
        if a.patient:
            patient_name = f"{a.patient.last_name} {a.patient.first_name}"

        start_dt = timezone.localtime(a.start_at)
        end_dt = timezone.localtime(a.end_at) if a.end_at else start_dt + timedelta(minutes=30)

        start_min = start_dt.hour * 60 + start_dt.minute
        end_min = end_dt.hour * 60 + end_dt.minute

        clipped_start = max(start_min, start_minutes)
        clipped_end = min(end_min, end_minutes)

        if clipped_end <= start_minutes or clipped_start >= end_minutes:
            continue

        left_percent = ((clipped_start - start_minutes) / total_minutes) * 100
        width_percent = max(((clipped_end - clipped_start) / total_minutes) * 100, 3)

        intake_state = "問診未着手"
        if summary["has_intake"]:
            intake_state = "問診完了" if summary["intake_completed"] else "問診入力中"

        row_key = str(a.assigned_staff_id) if a.assigned_staff_id else unassigned_key
        if row_key not in staff_map:
            staff_map[row_key] = {
                "staff_id": a.assigned_staff_id,
                "staff_name": a.assigned_staff.username if a.assigned_staff else "未割当",
                "appointments": [],
            }

        staff_map[row_key]["appointments"].append({
            "id": a.id,
            "patient_name": patient_name,
            "start_time": start_dt.strftime("%H:%M"),
            "end_time": end_dt.strftime("%H:%M"),
            "menu": a.menu or "-",
            "status": a.status,
            "status_label": a.get_status_display(),
            "intake_state": intake_state,
            "chief_label": summary["chief_label"] or "主訴未入力",
            "pain_level_display": summary["pain_level_display"] or "-",
            "visit_type_label": summary["visit_type_label"] or "-",
            "areas_display": "、".join(summary["areas_display"]) if summary["areas_display"] else "-",
            "left_percent": round(left_percent, 3),
            "width_percent": round(width_percent, 3),
            "intake_detail_url": reverse("staff:intake_detail", args=[a.intake.id]) if intake else "",
            "recording_url": reverse("intakes:recording_new", args=[a.id]),
            "day_url": f"{reverse('staff:appointments')}?period=day&day={a.start_at.date().isoformat()}",
        })

    rows = list(staff_map.values())

    rows = [
        row for row in rows
        if row["appointments"] or row["staff_id"] is not None
    ]

    rows.sort(key=lambda x: (x["staff_name"] == "未割当", x["staff_name"]))

    return {
        "start_hour": start_hour,
        "end_hour": end_hour,
        "hours": list(range(start_hour, end_hour + 1)),
        "rows": rows,
    }

@staff_required
@require_POST
def staff_appointment_status_update_view(request, pk):
    clinic = get_current_clinic(request)
    appt = get_object_or_404(Appointment, pk=pk, clinic=clinic)

    new_status = (request.POST.get("status") or "").strip()
    valid = {c[0] for c in Appointment.Status.choices}

    if new_status not in valid:
        messages.error(request, "不正なステータスです。")
        return redirect(request.POST.get("next") or "staff:appointments")

    appt.status = new_status
    appt.save(update_fields=["status", "updated_at"])

    messages.success(request, f"ステータスを「{appt.get_status_display()}」に更新しました。")
    return redirect(request.POST.get("next") or "staff:appointments")


@staff_required
@require_POST
def move_appointment_view(request, pk):
    clinic = get_current_clinic(request)

    if not _is_staff_user(request.user, clinic):
        return JsonResponse({"ok": False, "error": "権限がありません。"}, status=403)

    try:
        data = json.loads(request.body.decode("utf-8"))
    except Exception:
        return JsonResponse({"ok": False, "error": "不正なリクエストです。"}, status=400)

    start_raw = data.get("start")
    end_raw = data.get("end")

    start_dt = parse_datetime(start_raw) if start_raw else None
    end_dt = parse_datetime(end_raw) if end_raw else None

    if not start_dt:
        return JsonResponse({"ok": False, "error": "開始日時が不正です。"}, status=400)

    appt = get_object_or_404(Appointment, pk=pk, clinic=clinic)

    if not end_dt:
        if getattr(appt, "end_at", None):
            duration = appt.end_at - appt.start_at
            end_dt = start_dt + duration
        else:
            end_dt = start_dt

    overlap_qs = Appointment.objects.filter(
        clinic=clinic,
        assigned_staff=appt.assigned_staff,
        start_at__lt=end_dt,
        end_at__gt=start_dt,
    ).exclude(pk=appt.pk).exclude(status=Appointment.Status.CANCELLED)

    if overlap_qs.exists():
        return JsonResponse({
            "ok": False,
            "error": "同じ施術者の予約と時間が重複しています。"
        }, status=400)

    appt.start_at = start_dt
    appt.end_at = end_dt
    appt.save(update_fields=["start_at", "end_at", "updated_at"])

    return JsonResponse({
        "ok": True,
        "start": appt.start_at.isoformat(),
        "end": appt.end_at.isoformat() if appt.end_at else None,
    })


@staff_required
def staff_intake_list_view(request):
    clinic = get_current_clinic(request)
    today = timezone.localdate()
    q = (request.GET.get("q", "") or "").strip()

    appts = (
        Appointment.objects
        .select_related("patient", "assigned_staff")
        .filter(clinic=clinic, start_at__date=today)
        .order_by("start_at")
    )

    if q:
        appts = appts.filter(
            Q(patient__last_name__icontains=q) |
            Q(patient__first_name__icontains=q) |
            Q(patient__phone__icontains=q) |
            Q(menu__icontains=q)
        )

    done = appts.filter(intake__isnull=False).count()
    not_done = appts.filter(intake__isnull=True).count()

    return render(request, "staff/intake_list.html", {
        "active": "intake",
        "page_title": "問診",
        "today": today,
        "appointments": appts,
        "stats": {"done": done, "not_done": not_done, "total": appts.count()},
        "filter_q": q,
    })


@staff_required
def staff_intake_detail_view(request, pk):
    clinic = get_current_clinic(request)
    intake = get_object_or_404(
        Intake.objects.select_related("patient", "appointment"),
        pk=pk,
        clinic=clinic
    )

    payload = intake.payload or {}
    extract = payload.get("extract", {}) or {}
    symptoms = payload.get("symptoms", {}) or {}
    history = payload.get("history", {}) or {}

    step2 = payload.get("step2", {}) or {}
    step3 = payload.get("step3", {}) or {}

    extract = {
        "chief_complaint": extract.get("chief_complaint") or step2.get("chief_complaint") or intake.chief_complaint,
        "onset": extract.get("onset") or step2.get("since") or intake.onset,
        "trigger": extract.get("trigger") or step2.get("trigger"),
        "severity_0_10": extract.get("severity_0_10") or step3.get("severity") or symptoms.get("severity"),
        "symptom_type": extract.get("symptom_type") or step2.get("symptom_type") or intake.symptom_type,
        "locations": extract.get("locations") or step3.get("areas") or symptoms.get("areas") or [],
        "qualities": extract.get("qualities") or step3.get("qualities") or symptoms.get("qualities") or [],
        "symptom_details": extract.get("symptom_details") or step3.get("symptom_details") or symptoms.get("symptom_details") or [],
        "worse_when": extract.get("worse_when") or step3.get("worse_when") or symptoms.get("worse_when"),
        "better_when": extract.get("better_when") or step3.get("better_when") or symptoms.get("better_when"),
    }

    visit_type_label = _jp_value(payload.get("visit_type"))

    summary_rows = [
        {"label": "来院種別", "value": _jp_value(payload.get("visit_type"))},
        {"label": "主訴", "value": _jp_value(extract.get("chief_complaint") or intake.chief_complaint)},
        {"label": "症状タイプ", "value": _jp_value(extract.get("symptom_type") or intake.symptom_type)},
        {"label": "いつから", "value": _jp_value(extract.get("onset") or intake.onset)},
        {"label": "きっかけ", "value": _jp_value(extract.get("trigger"))},
        {"label": "痛みの部位", "value": _jp_value(extract.get("locations"))},
        {"label": "痛みの強さ", "value": _jp_value(extract.get("severity_0_10"))},
        {"label": "症状の感じ", "value": _jp_value(extract.get("qualities"))},
        {"label": "当てはまる症状", "value": _jp_value(extract.get("symptom_details"))},
        {"label": "悪化する時", "value": _jp_value(extract.get("worse_when"))},
        {"label": "楽になる時", "value": _jp_value(extract.get("better_when"))},
    ]

    note_rows = [
        {"label": "自由記入", "value": _jp_value(symptoms.get("free_text"))},
        {"label": "その他の部位", "value": _jp_value(symptoms.get("other_area_text"))},
        {"label": "その他の症状詳細", "value": _jp_value(symptoms.get("other_quality_text"))},
    ]

    medical_rows = [
        {"label": "他院通院", "value": _jp_value(history.get("other_clinic"))},
        {"label": "他院通院メモ", "value": _jp_value(history.get("other_clinic_note"))},
        {"label": "服薬中", "value": _jp_value(history.get("taking_meds"))},
        {"label": "服薬メモ", "value": _jp_value(history.get("meds_note"))},
        {"label": "既往歴", "value": _jp_value(history.get("past_history"))},
        {"label": "既往歴メモ", "value": _jp_value(history.get("history_note"))},
        {"label": "最後に伝えたいこと", "value": _jp_value(history.get("final_note"))},
    ]

    summary_rows = [row for row in summary_rows if row["value"] != "-"]
    note_rows = [row for row in note_rows if row["value"] != "-"]
    medical_rows = [row for row in medical_rows if row["value"] != "-"]

    return render(request, "staff/intake_detail.html", {
        "active": "intake",
        "page_title": "問診詳細",
        "intake": intake,
        "payload": payload,
        "extract": extract,
        "symptoms": symptoms,
        "history": history,
        "summary_rows": summary_rows,
        "note_rows": note_rows,
        "medical_rows": medical_rows,
        "visit_type_label": visit_type_label,
    })


@staff_required
def staff_interview_view(request, appointment_id: int):
    clinic = get_current_clinic(request)

    appt = get_object_or_404(
        Appointment.objects.select_related("patient", "assigned_staff"),
        pk=appointment_id,
        clinic=clinic
    )

    if appt.patient_id is None:
        messages.error(request, "この予約は患者が未確定です。先に患者を紐づけてください。")
        return redirect("staff:appointments")

    intake = getattr(appt, "intake", None)
    if intake is None:
        messages.warning(request, "この予約は問診が未提出です。先に問診の確認/入力をお願いします。")
        return redirect("staff:intake")

    visit = (
        Visit.objects
        .filter(clinic=clinic, appointment=appt)
        .order_by("-visited_at")
        .first()
    )

    if visit is None:
        visit = Visit.objects.create(
            clinic=clinic,
            patient=appt.patient,
            appointment=appt,
            intake=intake,
            visited_at=timezone.now(),
            practitioner=appt.assigned_staff,
            status=Visit.Status.IN_PROGRESS,
        )
    else:
        changed = False
        if visit.patient_id != appt.patient_id:
            visit.patient = appt.patient
            changed = True
        if visit.intake_id is None:
            visit.intake = intake
            changed = True
        if visit.practitioner_id is None and appt.assigned_staff_id:
            visit.practitioner = appt.assigned_staff
            changed = True
        if changed:
            visit.save()

    note = ChartNote.objects.filter(visit=visit).order_by("-version").first()

    if request.method == "POST":
        exam_text = (request.POST.get("exam_text") or "").strip()
        if not exam_text:
            messages.error(request, "診察メモを入力してください。")
            return redirect("staff:interview", appointment_id=appt.id)

        job = run_ai_draft(visit=visit, input_text=exam_text)

        if job.status == job.Status.SUCCESS:
            messages.success(request, "SOAP（AI下書き）を作成しました。")
        else:
            messages.error(request, f"AI処理に失敗しました：{job.error_message}")

        return redirect("staff:interview", appointment_id=appt.id)

    note = ChartNote.objects.filter(visit=visit).order_by("-version").first()

    return render(request, "staff/interview.html", {
        "active": "appointments",
        "page_title": "診察（AI Interview）",
        "appointment": appt,
        "visit": visit,
        "intake": intake,
        "note": note,
    })


@staff_required
@require_POST
@transaction.atomic
def register_clinical_note(request, recording_id):
    clinic = get_current_clinic(request)

    if not _is_staff_user(request.user, clinic):
        return HttpResponseForbidden("staff only")

    recording = get_object_or_404(
        InterviewRecording.objects.select_related("appointment", "patient", "intake"),
        pk=recording_id,
        clinic=clinic,
    )

    appointment = recording.appointment
    patient = recording.patient
    intake = recording.intake

    summary = recording.get_active_summary() or {}

    def parse_json_field(name, default):
        raw = request.POST.get(name, "")
        if not raw:
            return default
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return default

    # 元データ
    base_soap = summary.get("soap", {}) or {}
    base_extract = summary.get("extract", {}) or {}
    base_followups = summary.get("followups", []) or {}

    # POST優先
    posted_summary = parse_json_field("summary_json", None)
    posted_soap = parse_json_field("soap_json", None)
    posted_extract = parse_json_field("extract_json", None)
    posted_followups = parse_json_field("followups_json", None)
    posted_locations = parse_json_field("selected_locations_json", None)

    if posted_summary and isinstance(posted_summary, dict):
        soap = posted_summary.get("soap", {}) or {}
        extract = posted_summary.get("extract", {}) or {}
        followups = posted_summary.get("followups", []) or []
    else:
        soap = posted_soap if isinstance(posted_soap, dict) else base_soap
        extract = posted_extract if isinstance(posted_extract, dict) else base_extract
        followups = posted_followups if isinstance(posted_followups, list) else base_followups

    # 部位は selected_locations_json を最優先にして上書き
    if isinstance(posted_locations, list):
        extract["locations"] = posted_locations

    web_snapshot = {}
    if intake:
        web_snapshot = {
            "payload": intake.payload or {},
            "chief_complaint": intake.chief_complaint,
            "symptom_type": intake.symptom_type,
            "onset": intake.onset,
            "submitted_at": intake.submitted_at.isoformat() if intake.submitted_at else None,
        }

    note, created = ClinicalNote.objects.update_or_create(
        appointment=appointment,
        defaults={
            "patient": patient,
            "intake": intake,
            "recording": recording,
            "soap_json": soap,
            "extract_json": extract,
            "followups_json": followups,
            "web_intake_snapshot": web_snapshot,
            "registered_by": request.user,
            "updated_by": request.user,
        },
    )

    messages.success(request, "内容登録（確定保存）が完了しました。")

    next_after_register = (request.POST.get("next_after_register") or "").strip()

    if next_after_register == "treatment_plan":
        return redirect(
            "treatment_plans:plan_create_from_clinical_note",
            clinical_note_id=note.id,
        )

    return redirect("staff:patient_detail", patient_id=patient.id)


@staff_required
def staff_patient_detail_view(request, patient_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の患者情報のみ閲覧できます。")

    patient = get_object_or_404(Patient, pk=patient_id, clinic=clinic)

    active_tab = request.GET.get("tab", "overview")

    # ★ posture を追加
    valid_tabs = [
        "overview",
        "appointments",
        "clinical_notes",
        "treatment_plans",
        "posture",
        "files",
    ]

    if active_tab not in valid_tabs:
        active_tab = "overview"

    now = timezone.now()

    notes = (
        ClinicalNote.objects
        .filter(
            patient=patient,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .select_related("appointment", "recording", "intake")
        .order_by("-created_at")
    )

    treatment_plans = (
        TreatmentPlan.objects
        .filter(
            patient=patient,
            patient__clinic=clinic,
        )
        .select_related("appointment", "intake", "clinical_note", "created_by")
        .prefetch_related("progress_logs")
        .annotate(
            status_order=Case(
                When(status="active", then=Value(0)),
                When(status="paused", then=Value(1)),
                When(status="completed", then=Value(2)),
                default=Value(9),
                output_field=IntegerField(),
            )
        )
        .order_by("status_order", "-created_at")
    )

    appointments = (
        Appointment.objects
        .filter(patient=patient, clinic=clinic)
        .select_related("assigned_staff", "treatment_plan")
        .order_by("-start_at")
    )

    # ★ AI姿勢分析
    posture_assessments = (
        PostureAssessment.objects
        .filter(
            clinic=clinic,
            patient=patient,
        )
        .select_related(
            "created_by",
            "confirmed_by",
            "updated_by",
            "appointment",
            "treatment_session",
            "clinical_note",
        )
        .prefetch_related("images")
        .order_by("-created_at")
    )

    posture_assessment_count = posture_assessments.count()
    latest_posture_assessment = posture_assessments.first()
    posture_summary = (
        latest_posture_assessment.get_active_summary()
        if latest_posture_assessment
        else {}
    )
    if not isinstance(posture_summary, dict):
        posture_summary = {}

    latest_note = notes.first()
    latest_intake = (
        Intake.objects
        .filter(
            clinic=clinic,
            patient=patient,
            patient__clinic=clinic,
        )
        .select_related("appointment")
        .order_by("-submitted_at", "-id")
        .first()
    )
    active_plan = treatment_plans.filter(status="active", is_active=True).first()
    latest_plan = treatment_plans.first()

    latest_extract = latest_note.extract_json if latest_note else {}
    latest_soap = latest_note.soap_json if latest_note else {}
    if not isinstance(latest_extract, dict):
        latest_extract = {}
    if not isinstance(latest_soap, dict):
        latest_soap = {}

    latest_assessment = _compact_dashboard_text(
        latest_soap.get("A"),
        limit=88,
    )
    latest_treatment_policy = _compact_dashboard_text(
        latest_soap.get("P"),
        limit=88,
    )

    patient_context_profile = build_patient_context_profile(
        patient,
        latest_intake=latest_intake,
        latest_note=latest_note,
        latest_plan=active_plan or latest_plan,
        latest_assessment=latest_posture_assessment,
        summary=posture_summary,
    )

    profile_summary = dict(posture_summary)
    profile_clinical_notes = _dashboard_text_list(
        profile_summary.get("clinical_notes")
    )
    profile_clinical_notes.extend(
        item
        for item in (
            latest_extract.get("chief_complaint"),
            latest_assessment,
            latest_treatment_policy,
            latest_posture_assessment.memo if latest_posture_assessment else "",
        )
        if item
    )
    profile_clinical_notes.extend(
        patient_context_profile.get("source_texts") or []
    )
    profile_summary["clinical_notes"] = profile_clinical_notes

    posture_profile_available = any(
        posture_summary.get(key)
        for key in (
            "important_points",
            "posture_findings",
            "joint_assessments",
            "alignment_observations",
            "symptom_relation_hypotheses",
            "suspected_load_areas",
            "next_check_points",
            "clinical_notes",
            "patient_explanation",
            "report_summary_for_patient",
        )
    )
    body_profile_items = build_body_profile_items(
        profile_summary,
        context_profile=patient_context_profile,
    )
    posture_profile_summary = _compact_dashboard_text(
        posture_summary.get("report_summary_for_patient")
        or posture_summary.get("patient_explanation")
        or posture_summary.get("overall_summary"),
        fallback=(
            "問診・カルテ・施術計画の背景情報から、必要時に確認する部位を整理しています。"
            if patient_context_profile["has_context"]
            else "姿勢分析は未実施です。各関節は必要時に評価します。"
        ),
        limit=96,
    )
    posture_attention_source = (
        _dashboard_text_list(posture_summary.get("important_points"))
        + _dashboard_text_list(posture_summary.get("suspected_load_areas"))
        + patient_context_profile.get("notes", [])
        + patient_context_profile.get("pain_trigger_items", [])
    )
    posture_attention_points = [
        _compact_dashboard_text(item, limit=64)
        for item in list(dict.fromkeys(posture_attention_source))[:4]
    ]

    upcoming_appointments = appointments.filter(start_at__gte=now).order_by("start_at")[:4]
    past_appointments = appointments.filter(start_at__lt=now).order_by("-start_at")[:8]

    latest_appointment = appointments.first()

    progress_count = 0
    if active_plan:
        progress_count = active_plan.progress_logs.count()
    elif latest_plan:
        progress_count = latest_plan.progress_logs.count()

    patient_age = None
    if patient.birth_date:
        today = timezone.localdate()
        patient_age = (
            today.year
            - patient.birth_date.year
            - (
                (today.month, today.day)
                < (patient.birth_date.month, patient.birth_date.day)
            )
        )

    patient_gender = ""
    if hasattr(patient, "get_gender_display"):
        patient_gender = patient.get_gender_display()
    elif hasattr(patient, "get_sex_display"):
        patient_gender = patient.get_sex_display()
    else:
        patient_gender = (
            getattr(patient, "gender", "")
            or getattr(patient, "sex", "")
            or ""
        )

    return render(request, "staff/patients/detail.html", {
        "active": "patient_search",
        "page_title": "患者詳細",
        "active_tab": active_tab,

        "patient": patient,
        "patient_age": patient_age,
        "patient_gender": patient_gender,
        "patient_context_profile": patient_context_profile,
        "latest_intake": latest_intake,

        "notes": notes,
        "note_count": notes.count(),

        "treatment_plans": treatment_plans,
        "plan_count": treatment_plans.count(),

        "appointments": appointments[:8],
        "appointment_count": appointments.count(),
        "upcoming_appointments": upcoming_appointments,
        "past_appointments": past_appointments,
        "latest_appointment": latest_appointment,

        "active_plan": active_plan,
        "latest_plan": latest_plan,
        "progress_count": progress_count,

        "latest_note": latest_note,
        "latest_extract": latest_extract,
        "latest_assessment": latest_assessment,
        "latest_treatment_policy": latest_treatment_policy,

        # ★ AI姿勢分析
        "posture_assessments": posture_assessments,
        "posture_assessment_count": posture_assessment_count,
        "latest_posture_assessment": latest_posture_assessment,
        "posture_summary": posture_summary,
        "posture_profile_available": posture_profile_available,
        "posture_profile_summary": posture_profile_summary,
        "body_profile_items": body_profile_items,
        "posture_attention_points": posture_attention_points,

        "file_count": 0,
    })

def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if str(x).strip()]
    if isinstance(v, str):
        return [s.strip() for s in v.split("\n") if s.strip()]
    return [str(v)]

def normalize_print_location_name(name: str) -> str:
    n = str(name or "").strip()

    aliases = {
        "首": "喉前",
        "頚部": "喉前",
        "後頭部後": "首後",

        "肩": "喉前",
        "肩周り": "右肩前",
        "首肩": "喉前",
        "右肩": "右肩前",
        "左肩": "左肩前",

        "胸": "鳩尾前",
        "右胸": "右胸前",
        "左胸": "左胸前",

        "背部": "背中下後",
        "背中": "背中下後",

        "腰": "腰後",
        "腰部": "腰後",
        "右腰": "右腰後",
        "左腰": "左腰後",

        "臀部": "臀裂上後",
        "お尻": "臀裂上後",
        "ヒップ": "臀裂上後",
        "右臀部": "右臀部後",
        "左臀部": "左臀部後",

        "股関節": "右鼠径部前",
        "右股関節": "右鼠径部前",
        "左股関節": "左鼠径部前",

        "右上腕": "右上腕前",
        "左上腕": "左上腕前",
        "右肘": "右肘前",
        "左肘": "左肘前",
        "右前腕": "右前腕前",
        "左前腕": "左前腕前",

        "右大腿": "右大腿前",
        "左大腿": "左大腿前",
        "右膝": "右膝前",
        "左膝": "左膝前",
        "右下腿": "右下腿前",
        "左下腿": "左下腿前",
        "右足": "右足前",
        "左足": "左足前",

        "ひざ": "右膝前",
        "膝": "右膝前",
    }

    return aliases.get(n, n)


def build_print_body_markers(locations):
    """
    施術録印刷用の人体マーカーを作る。
    viewBox="0 0 300 700" 前提。
    recording_detail.html の positionMap と同じ座標系。
    """
    if not locations:
        return []

    position_map = {
        # 前面
        "喉前": {"front": {"x": 155, "y": 118}},
        "右鎖骨前": {"front": {"x": 126, "y": 145}},
        "左鎖骨前": {"front": {"x": 184, "y": 145}},
        "右胸前": {"front": {"x": 132, "y": 184}},
        "左胸前": {"front": {"x": 178, "y": 184}},
        "鳩尾前": {"front": {"x": 155, "y": 215}},
        "右上腹部前": {"front": {"x": 136, "y": 305}},
        "左上腹部前": {"front": {"x": 174, "y": 305}},
        "下腹部前": {"front": {"x": 155, "y": 346}},
        "右肩前": {"front": {"x": 75, "y": 150}},
        "左肩前": {"front": {"x": 235, "y": 150}},
        "右上腕前": {"front": {"x": 75, "y": 240}},
        "左上腕前": {"front": {"x": 235, "y": 240}},
        "右肘前": {"front": {"x": 70, "y": 270}},
        "左肘前": {"front": {"x": 240, "y": 270}},
        "右前腕前": {"front": {"x": 68, "y": 305}},
        "左前腕前": {"front": {"x": 242, "y": 305}},
        "右鼠径部前": {"front": {"x": 138, "y": 345}},
        "左鼠径部前": {"front": {"x": 172, "y": 345}},
        "右大腿前": {"front": {"x": 124, "y": 425}},
        "左大腿前": {"front": {"x": 186, "y": 425}},
        "右膝前": {"front": {"x": 127, "y": 490}},
        "左膝前": {"front": {"x": 189, "y": 490}},
        "右下腿前": {"front": {"x": 127, "y": 580}},
        "左下腿前": {"front": {"x": 186, "y": 580}},
        "右足前": {"front": {"x": 127, "y": 660}},
        "左足前": {"front": {"x": 186, "y": 660}},

        # 背面
        "首後": {"back": {"x": 155, "y": 104}},
        "右肩後": {"back": {"x": 235, "y": 150}},
        "左肩後": {"back": {"x": 75, "y": 150}},
        "右肩甲骨後": {"back": {"x": 132, "y": 185}},
        "左肩甲骨後": {"back": {"x": 178, "y": 185}},
        "背中上後": {"back": {"x": 155, "y": 215}},
        "背中下後": {"back": {"x": 155, "y": 275}},
        "右腰後": {"back": {"x": 186, "y": 308}},
        "左腰後": {"back": {"x": 124, "y": 308}},
        "腰後": {"back": {"x": 155, "y": 308}},
        "右臀部後": {"back": {"x": 186, "y": 360}},
        "左臀部後": {"back": {"x": 124, "y": 360}},
        "臀裂上後": {"back": {"x": 155, "y": 360}},
        "右上腕後": {"back": {"x": 235, "y": 240}},
        "左上腕後": {"back": {"x": 75, "y": 240}},
        "右肘後": {"back": {"x": 240, "y": 270}},
        "左肘後": {"back": {"x": 70, "y": 270}},
        "右前腕後": {"back": {"x": 242, "y": 305}},
        "左前腕後": {"back": {"x": 68, "y": 305}},
        "右大腿後": {"back": {"x": 186, "y": 425}},
        "左大腿後": {"back": {"x": 124, "y": 425}},
        "右膝後": {"back": {"x": 189, "y": 490}},
        "左膝後": {"back": {"x": 127, "y": 490}},
        "右下腿後": {"back": {"x": 186, "y": 580}},
        "左下腿後": {"back": {"x": 127, "y": 580}},
        "右足後": {"back": {"x": 186, "y": 660}},
        "左足後": {"back": {"x": 127, "y": 660}},
    }

    markers = []
    seen = set()

    for raw in locations:
        raw_name = str(raw or "").strip()
        if not raw_name:
            continue

        normalized = normalize_print_location_name(raw_name)

        # 完全一致優先
        matched_key = normalized if normalized in position_map else None

        # 部分一致フォロー
        if not matched_key:
            for key in position_map.keys():
                if key in normalized or normalized in key:
                    matched_key = key
                    break

        if not matched_key:
            continue

        pos_data = position_map.get(matched_key, {})

        for view_name, pos in pos_data.items():
            unique_key = f"{view_name}:{matched_key}"
            if unique_key in seen:
                continue

            seen.add(unique_key)

            markers.append({
                "view": view_name,
                "label": raw_name,
                "normalized": matched_key,
                "x": pos["x"],
                "y": pos["y"],
            })

    return markers

@staff_required
def staff_clinical_note_detail_view(request, pk):
    clinic = get_current_clinic(request)

    note = get_object_or_404(
        ClinicalNote.objects.select_related(
            "patient",
            "appointment",
            "intake",
            "recording",
            "treatment_session",
            "registered_by",
            "updated_by",
        ),
        pk=pk,
        patient__clinic=clinic,
    )

    soap = note.soap_json or {}
    soap_view = {
        "S": _as_list(soap.get("S")),
        "O": _as_list(soap.get("O")),
        "A": _as_list(soap.get("A")),
        "P": _as_list(soap.get("P")),
    }

    extract = note.extract_json or {}
    followups = note.followups_json or []
    histories = note.histories.select_related("edited_by").all()

    is_treatment_session_note = (
        extract.get("source") == "treatment_session"
        or getattr(note, "treatment_session_id", None)
    )

    progress_change = extract.get("progress_change") or {}
    progress_note = extract.get("progress_note") or {}
    next_plan = extract.get("next_plan") or {}

    important_points = extract.get("important_points") or []

    checked_areas = extract.get("checked_areas") or []
    pain_areas = extract.get("pain_areas") or extract.get("locations") or []
    movement_tests = extract.get("movement_tests") or []
    findings = extract.get("findings") or []
    suspected_causes = extract.get("suspected_causes") or []

    performed_treatments = extract.get("performed_treatments") or []
    target_areas = extract.get("target_areas") or []

    explained_to_patient = extract.get("explained_to_patient") or []
    lifestyle_guidance = extract.get("lifestyle_guidance") or []
    home_care = extract.get("home_care") or []
    cautions_until_next_visit = extract.get("cautions_until_next_visit") or []

    relationship_notes = extract.get("relationship_notes") or []
    missing_information = extract.get("missing_information") or []
    safety_notes = extract.get("safety_notes") or []

    visit_type_label = (
        extract.get("visit_type")
        or extract.get("symptom_type")
        or "-"
    )

    chief_complaint_label = extract.get("chief_complaint") or "-"

    location_list = (
        pain_areas
        or extract.get("locations")
        or []
    )

    location_label = " / ".join(location_list) if location_list else "-"

    # followups_json は文字列と dict が混在する可能性があるので、テンプレ用に整形
    followup_items = []
    for item in followups:
        if isinstance(item, dict):
            followup_items.append({
                "type": item.get("type", "followup"),
                "text": item.get("text", ""),
            })
        else:
            followup_items.append({
                "type": "followup",
                "text": str(item),
            })

    if note.treatment_session_id:
        source_label = "施術セッションAI"
        source_badge_class = "session"
    elif note.recording_id:
        source_label = "AI問診録音"
        source_badge_class = "recording"
    else:
        source_label = "手動 / Web問診"
        source_badge_class = "manual"

    context = {
        "active": "patient_search",
        "page_title": "カルテ詳細",

        "note": note,
        "patient": note.patient,
        "appointment": note.appointment,

        "soap_view": soap_view,
        "extract": extract,
        "followups": followups,
        "followup_items": followup_items,
        "histories": histories,

        "is_treatment_session_note": is_treatment_session_note,
        "source_label": source_label,
        "source_badge_class": source_badge_class,

        # 施術セッション由来カルテ用
        "important_points": important_points,
        "progress_change": progress_change,
        "progress_note": progress_note,
        "checked_areas": checked_areas,
        "pain_areas": pain_areas,
        "movement_tests": movement_tests,
        "findings": findings,
        "suspected_causes": suspected_causes,
        "treatment_intent": extract.get("treatment_intent", ""),

        "performed_treatments": performed_treatments,
        "target_areas": target_areas,
        "patient_response": extract.get("patient_response", ""),
        "after_treatment_change": extract.get("after_treatment_change", ""),

        "explained_to_patient": explained_to_patient,
        "lifestyle_guidance": lifestyle_guidance,
        "home_care": home_care,
        "cautions_until_next_visit": cautions_until_next_visit,

        "next_plan": next_plan,
        "next_treatment_policy": extract.get("next_treatment_policy") or next_plan.get("next_treatment_policy", ""),
        "recommended_visit_timing": extract.get("recommended_visit_timing") or next_plan.get("recommended_visit_timing", ""),
        "items_to_check_next_time": extract.get("items_to_check_next_time") or next_plan.get("items_to_check_next_time") or [],

        "relationship_notes": relationship_notes,
        "missing_information": missing_information,
        "safety_notes": safety_notes,
        
        "visit_type_label": visit_type_label,
        "chief_complaint_label": chief_complaint_label,
        "location_label": location_label,
    }

    return render(request, "staff/clinical_notes/detail.html", context)

@staff_required
def staff_clinical_note_print_view(request, pk):
    clinic = get_current_clinic(request)

    note = get_object_or_404(
        ClinicalNote.objects.select_related(
            "patient",
            "appointment",
            "intake",
            "recording",
            "registered_by",
            "updated_by",
        ),
        pk=pk,
        patient__clinic=clinic,
    )

    soap = note.soap_json or {}
    soap_view = {
        "S": _as_list(soap.get("S")),
        "O": _as_list(soap.get("O")),
        "A": _as_list(soap.get("A")),
        "P": _as_list(soap.get("P")),
    }

    extract = note.extract_json or {}
    followups = note.followups_json or []

    progress_change = extract.get("progress_change") or {}
    progress_note = extract.get("progress_note") or {}
    next_plan = extract.get("next_plan") or {}

    important_points = extract.get("important_points") or []

    checked_areas = extract.get("checked_areas") or []
    pain_areas = extract.get("pain_areas") or extract.get("locations") or []
    movement_tests = extract.get("movement_tests") or []
    findings = extract.get("findings") or []
    suspected_causes = extract.get("suspected_causes") or []

    performed_treatments = extract.get("performed_treatments") or []
    target_areas = extract.get("target_areas") or []

    explained_to_patient = extract.get("explained_to_patient") or []
    lifestyle_guidance = extract.get("lifestyle_guidance") or []
    home_care = extract.get("home_care") or []
    cautions_until_next_visit = extract.get("cautions_until_next_visit") or []

    relationship_notes = extract.get("relationship_notes") or []
    missing_information = extract.get("missing_information") or []
    safety_notes = extract.get("safety_notes") or []

    visit_type_label = (
        extract.get("visit_type")
        or extract.get("symptom_type")
        or "-"
    )

    chief_complaint_label = extract.get("chief_complaint") or "-"

    location_list = pain_areas or extract.get("locations") or []
    location_label = " / ".join(location_list) if location_list else "-"

    marker_source_locations = (
        pain_areas
        or checked_areas
        or extract.get("locations")
        or []
    )

    body_markers = build_print_body_markers(marker_source_locations)

    recommended_visit_timing = (
        extract.get("recommended_visit_timing")
        or next_plan.get("recommended_visit_timing")
        or "-"
    )

    next_treatment_policy = (
        extract.get("next_treatment_policy")
        or next_plan.get("next_treatment_policy")
        or "-"
    )

    items_to_check_next_time = (
        extract.get("items_to_check_next_time")
        or next_plan.get("items_to_check_next_time")
        or []
    )

    return render(request, "staff/clinical_notes/print_record.html", {
        "note": note,
        "patient": note.patient,
        "appointment": note.appointment,

        "soap_view": soap_view,
        "extract": extract,
        "followups": followups,

        "chief_complaint_label": chief_complaint_label,
        "visit_type_label": visit_type_label,
        "location_label": location_label,

        "body_markers": body_markers,

        "important_points": important_points,
        "progress_change": progress_change,
        "progress_note": progress_note,

        "checked_areas": checked_areas,
        "pain_areas": pain_areas,
        "movement_tests": movement_tests,
        "findings": findings,
        "suspected_causes": suspected_causes,

        "performed_treatments": performed_treatments,
        "target_areas": target_areas,
        "treatment_intent": extract.get("treatment_intent", ""),

        "patient_response": extract.get("patient_response", ""),
        "after_treatment_change": extract.get("after_treatment_change", ""),

        "explained_to_patient": explained_to_patient,
        "lifestyle_guidance": lifestyle_guidance,
        "home_care": home_care,
        "cautions_until_next_visit": cautions_until_next_visit,

        "recommended_visit_timing": recommended_visit_timing,
        "next_treatment_policy": next_treatment_policy,
        "items_to_check_next_time": items_to_check_next_time,

        "relationship_notes": relationship_notes,
        "missing_information": missing_information,
        "safety_notes": safety_notes,
    })

@staff_required
def staff_clinical_note_edit(request, note_id):
    clinic = get_current_clinic(request)
    note = get_object_or_404(ClinicalNote, id=note_id, patient__clinic=clinic)

    if request.method == "POST":
        form = ClinicalNoteEditForm(request.POST, note=note)
        if form.is_valid():
            payload = form.build_payload()

            ClinicalNoteHistory.objects.create(
                note=note,
                soap_json=note.soap_json or {},
                extract_json=note.extract_json or {},
                followups_json=note.followups_json or [],
                web_intake_snapshot=note.web_intake_snapshot or {},
                edited_by=request.user,
            )

            note.soap_json = payload["soap"]
            note.extract_json = payload["extract"]
            note.followups_json = payload["followups"]
            note.updated_by = request.user

            note.save(update_fields=[
                "soap_json",
                "extract_json",
                "followups_json",
                "updated_by",
                "updated_at",
            ])

            messages.success(request, "カルテを更新しました。")
            return redirect("staff:clinical_note_detail", pk=note.id)
    else:
        form = ClinicalNoteEditForm.from_note(note)

    return render(request, "staff/clinical_notes/edit.html", {
        "note": note,
        "form": form,
    })
