# apps/staff/views.py
import json
import re
from calendar import monthrange
from datetime import date, datetime, time, timedelta
from io import BytesIO

import qrcode

from django.contrib import messages
from django.contrib.auth import authenticate, get_user_model, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.core.exceptions import ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import (
    Q,
    Case,
    When,
    Value,
    IntegerField,
    Exists,
    OuterRef,
    Subquery,
    Count,
    Sum,
)
from django.db.models.functions import TruncDate
from django.http import Http404, HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time
from django.views.decorators.http import require_GET, require_POST

from apps.ai_jobs.usecases import run_ai_draft
from apps.appointments.models import Appointment
from apps.charts.models import ChartNote
from apps.clinical_notes.models import ClinicalNote, ClinicalNoteHistory
from apps.clinics.models import (
    Clinic,
    ClinicSettings,
    PatientShareToken,
    SalesRecord,
    StaffLeave,
    StaffShift,
    TreatmentMenu,
)
from apps.intakes.forms import AREA_CHOICES, VISIT_TYPE_CHOICES, SYMPTOM_TYPE_CHOICES
from apps.intakes.models import Intake, InterviewRecording
from apps.patients.models import Patient
from apps.staff.decorators import staff_required
from apps.staff.forms import ClinicalNoteEditForm
from apps.treatment_plans.models import TreatmentPlan
from apps.treatment_sessions.models import TreatmentSession
from apps.visits.models import Visit

from .forms import (
    ClinicSettingsForm,
    SalesRecordForm,
    StaffCreateForm,
    StaffLeaveForm,
    StaffShiftForm,
    StaffMemberEditForm,
    TreatmentMenuForm,
)
from apps.ai_usage.models import AiUsageLog, ClinicAiPlan
from apps.ai_usage.services import build_ai_usage_summary, get_month_range
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


def _profile_section(summary, *aliases):
    if not isinstance(summary, dict):
        return {}

    normalized_aliases = {
        re.sub(r"[^a-z0-9]", "", alias.lower())
        for alias in aliases
    }
    for key, value in summary.items():
        normalized_key = re.sub(r"[^a-z0-9]", "", str(key).lower())
        if normalized_key in normalized_aliases:
            return value
    return {}


def _profile_joint_value(joint_assessments, *aliases):
    value = _profile_section(joint_assessments, *aliases)
    if value not in (None, "", [], {}):
        return value
    return {}


def _patient_profile_source_values(patient):
    values = []
    for field_name in (
        "sports",
        "sport",
        "competition",
        "sport_position",
        "position",
        "occupation",
        "job",
        "work_style",
        "lifestyle",
        "daily_life",
        "chief_complaint",
        "memo",
        "note",
    ):
        if not hasattr(patient, field_name):
            continue
        value = getattr(patient, field_name, None)
        if callable(value):
            continue
        values.extend(_flatten_profile_text(value))
    return values


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
    source_texts.extend(_patient_profile_source_values(patient))

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
    posture_findings = _profile_section(
        summary,
        "posture_findings",
        "postureFinding",
        "postureFindings",
        "posture_observations",
    )
    joint_assessments = _profile_section(
        summary,
        "joint_assessments",
        "jointAssessment",
        "jointAssessments",
        "joints",
    )
    if not isinstance(posture_findings, dict):
        posture_findings = {}
    if not isinstance(joint_assessments, dict):
        joint_assessments = {}

    suspected_load_areas = _dashboard_text_list(_profile_section(
        summary,
        "suspected_load_areas",
        "suspectedLoadAreas",
        "load_areas",
    ))
    alignment_observations = _profile_section(
        summary,
        "alignment_observations",
        "alignmentObservations",
        "alignment",
    )
    alignment_items = []
    if isinstance(alignment_observations, dict):
        for value in alignment_observations.values():
            alignment_items.extend(_dashboard_text_list(value))
    else:
        alignment_items = _dashboard_text_list(alignment_observations)

    symptom_hypotheses = _dashboard_text_list(_profile_section(
        summary,
        "symptom_relation_hypotheses",
        "symptomRelationHypotheses",
        "symptom_hypotheses",
    ))
    clinical_notes = _dashboard_text_list(_profile_section(
        summary,
        "clinical_notes",
        "clinicalNotes",
        "practitioner_notes",
    ))
    next_check_points = _dashboard_text_list(_profile_section(
        summary,
        "next_check_points",
        "nextCheckPoints",
        "check_points",
    ))

    specs = (
        {
            "key": "head", "label": "頭部",
            "joints": ("head", "head_neck", "headNeck"),
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
            "key": "neck", "label": "頸部",
            "joints": ("neck", "cervical_spine", "cervicalSpine"),
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
            "key": "shoulder", "label": "肩",
            "joints": ("shoulder", "shoulders", "scapula"),
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
            "joints": ("thoracic_spine", "thoracicSpine", "thoracic"),
            "posture_keys": ("spine", "thoracic_spine", "thoracicSpine"),
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
            "joints": ("lumbar_pelvis", "lumbarPelvis", "lumbar_spine", "lumbarSpine"),
            "posture_keys": ("spine", "lumbar_spine", "lumbarSpine", "pelvis"),
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
            "joints": ("lumbar_pelvis", "lumbarPelvis", "pelvis"),
            "posture_keys": ("pelvis", "lumbar_pelvis", "lumbarPelvis"),
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
            "key": "hip", "label": "股関節",
            "joints": ("hip", "hips", "hip_joint", "hipJoint"),
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
            "key": "knee", "label": "膝",
            "joints": ("knee", "knees", "knee_joint", "kneeJoint"),
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
            "joints": ("ankle_foot", "ankleFoot", "ankle", "foot"),
            "posture_keys": ("ankle_foot", "ankleFoot", "ankle", "foot"),
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
            "key": "elbow", "label": "肘",
            "joints": ("elbow", "elbows", "elbow_joint", "elbowJoint"),
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
            "joints": ("wrist", "forearm", "wrist_forearm", "wristForearm"),
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
        joint_check_points = []
        for joint_key in spec["joints"]:
            joint = _profile_joint_value(joint_assessments, joint_key)
            if isinstance(joint, dict):
                joint_sources.extend([
                    _profile_section(joint, "summary", "overview"),
                    _profile_section(
                        joint,
                        "possible_findings",
                        "possibleFindings",
                        "findings",
                    ),
                ])
                joint_check_points.extend(_dashboard_text_list(
                    _profile_section(
                        joint,
                        "check_points",
                        "checkPoints",
                        "next_check_points",
                    )
                ))
            elif joint:
                joint_sources.append(joint)

        def related(items):
            return [
                item for item in items
                if any(keyword in item for keyword in spec["keywords"])
            ]

        posture_sources = []
        for posture_key in spec["posture_keys"]:
            value = _profile_section(posture_findings, posture_key)
            if value not in (None, "", [], {}):
                posture_sources.append(value)
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

        related_checks = related(next_check_points)
        check_point = _compact_profile_findings(
            [joint_check_points, related_checks],
            fallback=(
                context_note
                if context_note and not has_clinical_source
                else "施術者の評価と合わせて必要時に確認"
            ),
            limit=58,
        )
        source_label = (
            "姿勢分析"
            if joint_sources or posture_sources or related_alignment
            else "関連情報"
            if related_hypotheses or related_loads or related_clinical
            else "背景情報"
            if context_note
            else "未評価"
        )

        items.append({
            "key": spec["key"],
            "label": spec["label"],
            "text": text,
            "level": level,
            "tags": tags[:3],
            "context_note": context_note,
            "check_point": check_point,
            "source_label": source_label,
        })

    return items


def build_patient_profile_context(
    patient,
    latest_intake=None,
    latest_note=None,
    latest_plan=None,
    latest_posture_assessment=None,
):
    posture_summary_source = "none"
    posture_summary = {}
    if latest_posture_assessment:
        confirmed_summary = latest_posture_assessment.confirmed_summary_json
        ai_summary = latest_posture_assessment.ai_summary_json
        if isinstance(confirmed_summary, dict) and confirmed_summary:
            posture_summary = confirmed_summary
            posture_summary_source = "confirmed"
        elif isinstance(ai_summary, dict) and ai_summary:
            posture_summary = ai_summary
            posture_summary_source = "ai"

    latest_extract = (
        latest_note.extract_json
        if latest_note and isinstance(latest_note.extract_json, dict)
        else {}
    )
    latest_soap = (
        latest_note.soap_json
        if latest_note and isinstance(latest_note.soap_json, dict)
        else {}
    )
    latest_assessment_text = _compact_dashboard_text(
        _profile_section(latest_soap, "A", "assessment"),
        limit=88,
    )
    latest_treatment_policy = _compact_dashboard_text(
        _profile_section(latest_soap, "P", "plan"),
        limit=88,
    )

    patient_context_profile = build_patient_context_profile(
        patient,
        latest_intake=latest_intake,
        latest_note=latest_note,
        latest_plan=latest_plan,
        latest_assessment=latest_posture_assessment,
        summary=posture_summary,
    )

    profile_summary = dict(posture_summary)
    profile_clinical_notes = _dashboard_text_list(_profile_section(
        profile_summary,
        "clinical_notes",
        "clinicalNotes",
        "practitioner_notes",
    ))
    profile_clinical_notes.extend(_flatten_profile_text(
        latest_posture_assessment.memo
        if latest_posture_assessment
        else ""
    ))
    profile_clinical_notes.extend(_flatten_profile_text({
        "extract": latest_extract,
        "soap": latest_soap,
        "followups": latest_note.followups_json if latest_note else [],
    }))
    profile_clinical_notes.extend(_flatten_profile_text({
        "chief_complaint": latest_intake.chief_complaint,
        "payload": latest_intake.payload,
    } if latest_intake else {}))
    profile_clinical_notes.extend(_flatten_profile_text({
        "chief_complaint": latest_plan.chief_complaint,
        "exercise_instruction": latest_plan.exercise_instruction,
        "work_instruction": latest_plan.work_instruction,
        "lifestyle_other_instruction": latest_plan.lifestyle_other_instruction,
        "caution_notes": latest_plan.caution_notes,
    } if latest_plan else {}))
    profile_clinical_notes.extend(_patient_profile_source_values(patient))
    profile_summary["clinical_notes"] = list(dict.fromkeys(
        item for item in profile_clinical_notes if item
    ))

    posture_profile_available = any(
        _profile_section(posture_summary, *aliases)
        for aliases in (
            ("important_points", "importantPoints"),
            ("posture_findings", "postureFindings"),
            ("joint_assessments", "jointAssessments"),
            ("alignment_observations", "alignmentObservations"),
            ("symptom_relation_hypotheses", "symptomRelationHypotheses"),
            ("suspected_load_areas", "suspectedLoadAreas"),
            ("next_check_points", "nextCheckPoints"),
            ("clinical_notes", "clinicalNotes"),
            ("patient_explanation", "patientExplanation"),
            ("report_summary_for_patient", "reportSummaryForPatient"),
        )
    )
    body_profile_items = build_body_profile_items(
        profile_summary,
        context_profile=patient_context_profile,
    )
    posture_profile_summary = _compact_dashboard_text(
        _profile_section(
            posture_summary,
            "report_summary_for_patient",
            "reportSummaryForPatient",
        )
        or _profile_section(
            posture_summary,
            "patient_explanation",
            "patientExplanation",
        )
        or _profile_section(
            posture_summary,
            "overall_summary",
            "overallSummary",
        ),
        fallback=(
            "問診・カルテ・施術計画の背景情報から、必要時に確認する部位を整理しています。"
            if patient_context_profile["has_context"]
            else "姿勢分析は未実施です。各関節は必要時に評価します。"
        ),
        limit=96,
    )
    posture_attention_source = (
        _dashboard_text_list(_profile_section(
            posture_summary,
            "important_points",
            "importantPoints",
        ))
        + _dashboard_text_list(_profile_section(
            posture_summary,
            "suspected_load_areas",
            "suspectedLoadAreas",
        ))
        + patient_context_profile.get("notes", [])
        + patient_context_profile.get("pain_trigger_items", [])
    )

    return {
        "posture_summary": posture_summary,
        "posture_summary_source": posture_summary_source,
        "posture_profile_available": posture_profile_available,
        "posture_profile_summary": posture_profile_summary,
        "body_profile_items": body_profile_items,
        "posture_attention_points": [
            _compact_dashboard_text(item, limit=64)
            for item in list(dict.fromkeys(posture_attention_source))[:4]
        ],
        "patient_context_profile": patient_context_profile,
        "latest_extract": latest_extract,
        "latest_soap": latest_soap,
        "latest_assessment": latest_assessment_text,
        "latest_treatment_policy": latest_treatment_policy,
    }


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


def build_dashboard_today_tasks(clinic, today, today_appointments):
    from apps.intakes.views import build_interview_recording_flow_state
    from apps.treatment_sessions.views import (
        build_treatment_session_flow_state,
    )

    today_appointments = list(today_appointments[:20])
    appointment_ids = [
        appointment.id
        for appointment in today_appointments
    ]

    today_recordings = {
        recording.appointment_id: recording
        for recording in (
            InterviewRecording.objects
            .filter(
                clinic=clinic,
                patient__clinic=clinic,
                appointment__clinic=clinic,
                appointment_id__in=appointment_ids,
            )
            .select_related("patient", "appointment")
            .order_by("created_at")
        )
    }
    today_sessions = {
        session.appointment_id: session
        for session in (
            TreatmentSession.objects
            .filter(
                clinic=clinic,
                patient__clinic=clinic,
                appointment__clinic=clinic,
                appointment_id__in=appointment_ids,
            )
            .select_related("patient", "appointment")
            .order_by("-created_at")
        )
    }

    appointment_items = []
    for appointment in today_appointments:
        patient = appointment.patient
        recording = today_recordings.get(appointment.id)
        session = today_sessions.get(appointment.id)
        appointment_items.append({
            "appointment": appointment,
            "patient": patient,
            "precheck_url": (
                reverse(
                    "staff:pre_treatment_check",
                    args=[patient.id],
                )
                if patient
                else ""
            ),
            "patient_url": (
                reverse(
                    "staff:patient_detail",
                    args=[patient.id],
                )
                if patient
                else ""
            ),
            "initial_recording_url": (
                reverse(
                    "intakes:recording_detail",
                    args=[recording.id],
                )
                if recording
                else (
                    reverse(
                        "intakes:recording_new",
                        args=[appointment.id],
                    )
                    if patient
                    else ""
                )
            ),
            "initial_recording_label": (
                "初診録音を確認"
                if recording
                else "初診録音"
            ),
            "treatment_recording_url": (
                reverse(
                    "treatment_sessions:detail",
                    args=[session.id],
                )
                if session
                else (
                    reverse(
                        "treatment_sessions:start",
                        args=[appointment.id],
                    )
                    if patient
                    else ""
                )
            ),
            "treatment_recording_label": (
                "施術録音を確認"
                if session
                else "施術録音"
            ),
        })

    recording_confirmation_qs = (
        InterviewRecording.objects
        .filter(
            clinic=clinic,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .exclude(summary_json={})
        .filter(
            Q(confirmed_summary_json__isnull=True)
            | Q(confirmed_summary_json={})
        )
        .select_related("patient", "appointment")
        .order_by("-created_at")
    )
    session_confirmation_qs = (
        TreatmentSession.objects
        .filter(
            clinic=clinic,
            patient__clinic=clinic,
        )
        .filter(
            Q(appointment__isnull=True)
            | Q(appointment__clinic=clinic)
        )
        .exclude(summary_json={})
        .filter(
            Q(confirmed_summary_json__isnull=True)
            | Q(confirmed_summary_json={})
        )
        .select_related("patient", "appointment")
        .order_by("-created_at")
    )

    confirmation_waiting_count = (
        recording_confirmation_qs.count()
        + session_confirmation_qs.count()
    )
    confirmation_items = [
        {
            "patient": recording.patient,
            "type": "初診録音",
            "created_at": recording.created_at,
            "status": "カルテ案確認待ち",
            "url": reverse(
                "intakes:recording_confirm",
                args=[recording.id],
            ),
        }
        for recording in recording_confirmation_qs[:10]
    ]
    confirmation_items.extend({
        "patient": session.patient,
        "type": "通院施術録音",
        "created_at": session.created_at,
        "status": "カルテ案確認待ち",
        "url": reverse(
            "treatment_sessions:session_confirm",
            args=[session.id],
        ),
    } for session in session_confirmation_qs[:10])
    confirmation_items = sorted(
        confirmation_items,
        key=lambda item: item["created_at"],
        reverse=True,
    )[:10]

    recording_attention_q = (
        Q(status__in=[
            InterviewRecording.Status.TRANSCRIBING,
            InterviewRecording.Status.SUMMARIZING,
            InterviewRecording.Status.FAILED,
        ])
        | ~Q(error_message="")
        | (
            Q(audio_file__isnull=False)
            & ~Q(audio_file="")
            & Q(transcript_text="")
        )
        | (~Q(transcript_text="") & Q(summary_json={}))
    )
    recording_attention_qs = (
        InterviewRecording.objects
        .filter(
            recording_attention_q,
            clinic=clinic,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .select_related("patient", "appointment")
        .order_by("-created_at")
    )
    session_attention_q = (
        Q(status__in=[
            TreatmentSession.Status.TRANSCRIBING,
            TreatmentSession.Status.SUMMARIZING,
            TreatmentSession.Status.FAILED,
        ])
        | ~Q(error_message="")
        | (
            Q(chunks__isnull=False)
            & Q(transcript_text="")
        )
        | (~Q(transcript_text="") & Q(summary_json={}))
    )
    session_attention_qs = (
        TreatmentSession.objects
        .filter(
            session_attention_q,
            clinic=clinic,
            patient__clinic=clinic,
        )
        .filter(
            Q(appointment__isnull=True)
            | Q(appointment__clinic=clinic)
        )
        .select_related("patient", "appointment")
        .prefetch_related("chunks")
        .order_by("-created_at")
        .distinct()
    )
    recording_attention_count = (
        recording_attention_qs.count()
        + session_attention_qs.count()
    )
    recording_attention_items = []
    for recording in recording_attention_qs[:15]:
        state = build_interview_recording_flow_state(recording)
        if state["key"] in {
            "error",
            "transcribing",
            "summarizing",
            "transcription_waiting",
            "summary_waiting",
        }:
            recording_attention_items.append({
                "patient": recording.patient,
                "type": "初診録音",
                "created_at": recording.created_at,
                "status": state["label"],
                "tone": state["tone"],
                "url": reverse(
                    "intakes:recording_detail",
                    args=[recording.id],
                ),
            })
    for session in session_attention_qs[:15]:
        state = build_treatment_session_flow_state(
            session,
            session.chunks.all(),
        )
        if state["key"] in {
            "error",
            "transcribing",
            "summarizing",
            "transcription_waiting",
            "summary_waiting",
        }:
            recording_attention_items.append({
                "patient": session.patient,
                "type": "通院施術録音",
                "created_at": session.created_at,
                "status": state["label"],
                "tone": state["tone"],
                "url": reverse(
                    "treatment_sessions:detail",
                    args=[session.id],
                ),
            })
    recording_attention_items = sorted(
        recording_attention_items,
        key=lambda item: item["created_at"],
        reverse=True,
    )[:10]

    today_notes_qs = (
        ClinicalNote.objects
        .filter(
            patient__clinic=clinic,
            appointment__clinic=clinic,
            created_at__date=today,
        )
        .select_related("patient", "appointment")
        .order_by("-created_at")
    )
    report_items = [
        {
            "note": note,
            "patient": note.patient,
            "created_at": note.created_at,
            "url": reverse(
                "staff:patient_aftercare_report",
                args=[note.id],
            ),
        }
        for note in today_notes_qs[:10]
    ]

    return {
        "today_appointment_items": appointment_items,
        "today_note_count": today_notes_qs.count(),
        "confirmation_waiting_count": confirmation_waiting_count,
        "confirmation_waiting_items": confirmation_items,
        "recording_attention_count": recording_attention_count,
        "recording_attention_items": recording_attention_items,
        "today_report_items": report_items,
    }


@staff_required
def staff_dashboard_view(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のダッシュボードのみ閲覧できます。")

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
    today_tasks = build_dashboard_today_tasks(
        clinic,
        today,
        todays_appts,
    )

    active_plan_count = 0
    paused_plan_count = 0
    completed_plan_count = 0
    today_progress_count = 0

    ai_count = today_tasks["confirmation_waiting_count"]
    note_count = today_tasks["today_note_count"]

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
        **today_tasks,

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
    clinic = getattr(request.user, "clinic", None)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の予約のみ閲覧できます。")

    today = timezone.localdate()
    clinic_settings = ClinicSettings.objects.filter(clinic=clinic).first()

    view_mode = (request.GET.get("view") or "calendar").strip()
    if view_mode not in ["calendar", "staff", "timeline"]:
        view_mode = "calendar"

    day_str = request.GET.get("date") or request.GET.get("day") or today.isoformat()
    period = (request.GET.get("period") or "day").strip()
    if period not in ["day", "week", "month", "year"]:
        period = "day"
    if view_mode == "timeline":
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

    selected_staff = None
    if staff_id:
        selected_staff = (
            User.objects
            .filter(
                pk=staff_id,
                clinic=clinic,
                role__in=_shift_staff_roles(),
            )
            .first()
        )
    staff_candidate_context = _build_appointment_staff_candidates(
        clinic,
        target_date=base_day,
        current_staff=selected_staff,
    )
    staff_users = staff_candidate_context["users"]
    if staff_candidate_context["date_unknown"]:
        appointment_staff_notice = (
            "予約日時を選択すると、シフト・休暇情報に基づいて担当者候補を絞り込めます。"
        )
    else:
        appointment_staff_notice = (
            "担当者候補は、対象日のシフト・休暇情報をもとに表示しています。シフト反映済み / 勤務可能な担当者のみ表示"
        )
    appointment_staff_warning = ""
    if not staff_candidate_context["has_candidates"]:
        appointment_staff_warning = (
            "対象日に勤務可能な担当者がいません。シフトまたは休暇設定を確認してください。"
        )
    elif staff_candidate_context["current_staff_outside_candidates"]:
        appointment_staff_warning = (
            "現在の担当者は、この日時では勤務候補外です。必要に応じて担当者を変更してください。"
        )

    appointment_form_patients = (
        Patient.objects
        .filter(clinic=clinic)
        .order_by("last_name", "first_name", "card_no", "id")[:500]
    )
    appointment_form_staff = (
        User.objects
        .filter(
            clinic=clinic,
            is_active=True,
            role__in=_shift_staff_roles(),
        )
        .order_by("last_name", "first_name", "username")
    )
    appointment_form_menus = (
        TreatmentMenu.objects
        .filter(clinic=clinic, is_active=True)
        .order_by("display_order", "name", "id")
    )

    context = {
        "active": "appointments",
        "page_title": "予約管理",
        "day": base_day,
        "period": period,
        "view_mode": view_mode,
        "range_start": range_start,
        "range_end": range_end,
        "range_label": range_label,
        "appointments": appointments,
        "stats": stats,
        "staff_users": staff_users,
        "appointment_form_patients": appointment_form_patients,
        "appointment_form_staff": appointment_form_staff,
        "appointment_form_menus": appointment_form_menus,
        "appointment_staff_notice": appointment_staff_notice,
        "appointment_staff_warning": appointment_staff_warning,
        "filter_staff": staff_id,
        "filter_status": status,
        "filter_q": q,
        "status_choices": Appointment.Status.choices,
        "clinic_settings": clinic_settings,
        "calendar_slot_min": (
            clinic_settings.business_start_time.strftime("%H:%M:%S")
            if clinic_settings
            else "08:00:00"
        ),
        "calendar_slot_max": (
            clinic_settings.business_end_time.strftime("%H:%M:%S")
            if clinic_settings
            else "20:00:00"
        ),
        "calendar_slot_duration": (
            f"00:{clinic_settings.appointment_interval_minutes:02d}:00"
            if clinic_settings
            and clinic_settings.appointment_interval_minutes < 60
            else (
                "01:00:00"
                if clinic_settings
                else "00:30:00"
            )
        ),
        "calendar_slot_minutes": (
            clinic_settings.appointment_interval_minutes
            if clinic_settings
            else 30
        ),
    }

    context["calendar_events"] = _build_calendar_events(appointments)
    context["calendar_day_summary"] = _build_calendar_day_summary(appointments)
    context["staff_availability_rows"] = _build_staff_availability_rows(
        clinic,
        base_day,
        clinic_settings=clinic_settings,
    )

    if view_mode == "timeline":
        context["staff_slot_timeline"] = build_staff_appointment_timeline(
            clinic,
            base_day,
            clinic_settings=clinic_settings,
        )
        context["timeline_previous_date"] = base_day - timedelta(days=1)
        context["timeline_next_date"] = base_day + timedelta(days=1)

    if period == "day":
        context["timeline"] = _build_day_timeline_rows(
            appointments=appointments,
            staff_users=staff_users,
            base_day=base_day,
            clinic_settings=clinic_settings,
        )

    return render(request, "staff/appointments_calendar.html", context)


@staff_required
def staff_list(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のスタッフのみ閲覧できます。")

    staff_roles = [
        User.Role.ADMIN,
        User.Role.RECEPTION,
        User.Role.PRACTITIONER,
    ]
    today = timezone.localdate()
    month_start, next_month = get_month_range(today)

    users = list(
        User.objects
        .filter(clinic=clinic, role__in=staff_roles)
        .order_by("-is_active", "last_name", "first_name", "username")
    )
    user_ids = [user.id for user in users]

    today_appointments = {
        row["assigned_staff"]: row["count"]
        for row in (
            Appointment.objects
            .filter(
                clinic=clinic,
                assigned_staff_id__in=user_ids,
                start_at__date=today,
            )
            .values("assigned_staff")
            .annotate(count=Count("id"))
        )
    }
    month_sales = {
        row["staff"]: {
            "count": row["count"],
            "total": row["total"] or 0,
        }
        for row in (
            SalesRecord.objects
            .filter(
                clinic=clinic,
                staff_id__in=user_ids,
                status=SalesRecord.Status.PAID,
                treatment_date__gte=month_start,
                treatment_date__lt=next_month,
            )
            .values("staff")
            .annotate(count=Count("id"), total=Sum("amount"))
        )
    }

    staff_cards = []
    for user in users:
        full_name = user.get_full_name().strip() or user.username
        sales = month_sales.get(user.id, {"count": 0, "total": 0})
        show_in_assignment = user.is_active and user.role in staff_roles
        staff_cards.append({
            "id": user.id,
            "full_name": full_name,
            "display_name": full_name,
            "username": user.username,
            "email": user.email,
            "is_superuser": user.is_superuser,
            "is_staff": user.is_staff,
            "role": user.get_role_display() if hasattr(user, "get_role_display") else user.role,
            "role_value": user.role,
            "is_active": user.is_active,
            "today_appointments": today_appointments.get(user.id, 0),
            "month_sales_count": sales["count"],
            "month_sales_total": sales["total"],
            "month_sales_display": _format_yen(sales["total"]),
            "last_login": user.last_login,
            "show_in_reservations": show_in_assignment,
            "show_in_sales": show_in_assignment,
            "status_label": "有効" if user.is_active else "無効",
            "status_class": "running" if user.is_active else "stopped",
            "edit_url": reverse("staff:staff_member_update", args=[user.id]),
            "toggle_url": reverse("staff:staff_member_toggle", args=[user.id]),
            "shift_url": (
                reverse("staff:staff_shift_month")
                + f"?staff={user.id}"
            ),
            "leave_url": (
                reverse("staff:staff_leave_list")
                + f"?staff={user.id}"
            ),
        })

    return render(request, "staff/staff_list.html", {
        "active": "staffs",
        "page_title": "担当者一覧",
        "staff_cards": staff_cards,
        "active_staff_count": sum(1 for user in users if user.is_active),
        "inactive_staff_count": sum(1 for user in users if not user.is_active),
        "today_appointment_total": sum(today_appointments.values()),
        "month_sales_total_display": _format_yen(
            sum(item["total"] for item in month_sales.values())
        ),
        "shift_month_url": reverse("staff:staff_shift_month"),
        "leave_list_url": reverse("staff:staff_leave_list"),
        "shift_features": [
            "予約枠連動 準備中",
        ],
    })


def superuser_required(user):
    return user.is_authenticated and user.is_superuser


@staff_required
def staff_create(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のスタッフのみ作成できます。")

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
def staff_member_update_view(request, staff_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のスタッフのみ編集できます。")

    staff_user = get_object_or_404(
        User,
        pk=staff_id,
        clinic=clinic,
        role__in=[
            User.Role.ADMIN,
            User.Role.RECEPTION,
            User.Role.PRACTITIONER,
        ],
    )
    if request.method == "POST":
        form = StaffMemberEditForm(
            request.POST,
            instance=staff_user,
            clinic=clinic,
        )
        if form.is_valid():
            form.save()
            messages.success(request, "スタッフ情報を保存しました。")
            return redirect("staff:staff_list")
    else:
        form = StaffMemberEditForm(instance=staff_user, clinic=clinic)

    return render(request, "staff/staff_member_form.html", {
        "active": "staffs",
        "page_title": "スタッフ編集",
        "form": form,
        "staff_user": staff_user,
    })


@staff_required
@require_POST
def staff_member_toggle_view(request, staff_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のスタッフのみ変更できます。")

    staff_user = get_object_or_404(
        User,
        pk=staff_id,
        clinic=clinic,
        role__in=[
            User.Role.ADMIN,
            User.Role.RECEPTION,
            User.Role.PRACTITIONER,
        ],
    )
    if staff_user.id == request.user.id and staff_user.is_active:
        messages.error(request, "自分自身を無効化することはできません。")
        return redirect("staff:staff_list")

    staff_user.is_active = not staff_user.is_active
    staff_user.save(update_fields=["is_active"])
    if staff_user.is_active:
        messages.success(request, "スタッフを再有効化しました。")
    else:
        messages.success(request, "スタッフを無効化しました。")
    return redirect("staff:staff_list")


def _parse_shift_month(request):
    today = timezone.localdate()
    try:
        year = int(request.GET.get("year") or today.year)
        month = int(request.GET.get("month") or today.month)
        if month < 1 or month > 12:
            raise ValueError
        month_start = date(year, month, 1)
    except (TypeError, ValueError):
        month_start = date(today.year, today.month, 1)

    last_day = monthrange(month_start.year, month_start.month)[1]
    month_end = date(month_start.year, month_start.month, last_day)
    if month_start.month == 12:
        next_month = date(month_start.year + 1, 1, 1)
    else:
        next_month = date(month_start.year, month_start.month + 1, 1)
    if month_start.month == 1:
        prev_month = date(month_start.year - 1, 12, 1)
    else:
        prev_month = date(month_start.year, month_start.month - 1, 1)
    return month_start, month_end, next_month, prev_month


def _shift_staff_roles():
    return [
        User.Role.ADMIN,
        User.Role.RECEPTION,
        User.Role.PRACTITIONER,
    ]


def _appointment_staff_target_date(value):
    if not value:
        return None
    if isinstance(value, datetime):
        if timezone.is_naive(value):
            value = timezone.make_aware(value, timezone.get_current_timezone())
        return timezone.localtime(value).date()
    if isinstance(value, date):
        return value
    return None


def _appointment_staff_local_datetime(value):
    if not value or not isinstance(value, datetime):
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return timezone.localtime(value)


def _normalize_appointment_datetime(value):
    if not value or not isinstance(value, datetime):
        return None
    if timezone.is_naive(value):
        value = timezone.make_aware(value, timezone.get_current_timezone())
    return value


def _appointment_staff_target_range(target_date=None, target_start=None, target_end=None):
    start_dt = _appointment_staff_local_datetime(target_start)
    end_dt = _appointment_staff_local_datetime(target_end)
    resolved_date = (
        _appointment_staff_target_date(start_dt)
        or _appointment_staff_target_date(target_date)
    )
    start_time = start_dt.time() if start_dt else None
    # TODO: 予約作成フォーム側で終了時刻が未確定の場合は開始時刻のみで判定する。
    end_time = end_dt.time() if end_dt else None
    return resolved_date, start_time, end_time


def _time_ranges_overlap(start_a, end_a, start_b, end_b):
    if start_a is None or start_b is None:
        return True

    if end_a is None:
        end_a = start_a
    if end_b is None:
        end_b = start_b

    if start_a == end_a:
        return start_b <= start_a < end_b
    if start_b == end_b:
        return start_a <= start_b < end_a
    return start_a < end_b and start_b < end_a


def _clinic_half_day_leave_window(clinic_settings, leave_type):
    if (
        clinic_settings
        and clinic_settings.break_start_time
        and clinic_settings.break_end_time
    ):
        if leave_type == StaffLeave.LeaveType.MORNING_OFF:
            return (
                clinic_settings.business_start_time or time(0, 0),
                clinic_settings.break_start_time,
            )
        if leave_type == StaffLeave.LeaveType.AFTERNOON_OFF:
            return (
                clinic_settings.break_end_time,
                clinic_settings.business_end_time or time(23, 59, 59),
            )

    if leave_type == StaffLeave.LeaveType.MORNING_OFF:
        return time(0, 0), time(12, 0)
    if leave_type == StaffLeave.LeaveType.AFTERNOON_OFF:
        return time(12, 0), time(23, 59, 59)
    return None, None


def _staff_leave_candidate_reason(leave):
    return {
        StaffLeave.LeaveType.MORNING_OFF: "午前休のため候補外",
        StaffLeave.LeaveType.AFTERNOON_OFF: "午後休のため候補外",
        StaffLeave.LeaveType.PAID_LEAVE: "承認済み休暇のため候補外",
        StaffLeave.LeaveType.ABSENCE: "欠勤のため候補外",
        StaffLeave.LeaveType.TRAINING: "研修のため候補外",
        StaffLeave.LeaveType.OTHER: "承認済み休暇のため候補外",
    }.get(leave.leave_type, "承認済み休暇のため候補外")


def _staff_leave_overlaps_appointment(leave, target_start_time, target_end_time, clinic_settings):
    if leave.start_time and leave.end_time:
        return _time_ranges_overlap(
            target_start_time,
            target_end_time,
            leave.start_time,
            leave.end_time,
        )

    if leave.leave_type in [
        StaffLeave.LeaveType.PAID_LEAVE,
        StaffLeave.LeaveType.ABSENCE,
        StaffLeave.LeaveType.TRAINING,
        StaffLeave.LeaveType.OTHER,
    ]:
        return True

    if leave.leave_type in [
        StaffLeave.LeaveType.MORNING_OFF,
        StaffLeave.LeaveType.AFTERNOON_OFF,
    ]:
        leave_start, leave_end = _clinic_half_day_leave_window(
            clinic_settings,
            leave.leave_type,
        )
        if target_start_time is None:
            return True
        return _time_ranges_overlap(
            target_start_time,
            target_end_time,
            leave_start,
            leave_end,
        )

    return True


def _build_appointment_staff_candidates(
    clinic,
    target_date=None,
    target_start=None,
    target_end=None,
    current_staff=None,
):
    """
    予約担当者候補を、対象日のシフト・承認済み休暇から絞り込む。
    予約時刻が分かる場合は、午前休・午後休・時間帯指定休暇を重なりで判定する。
    """
    target_date, target_start_time, target_end_time = _appointment_staff_target_range(
        target_date=target_date,
        target_start=target_start,
        target_end=target_end,
    )
    base_qs = (
        User.objects
        .filter(
            clinic=clinic,
            is_active=True,
            role__in=_shift_staff_roles(),
        )
        .order_by("last_name", "first_name", "username")
    )

    if target_date is None:
        users = list(base_qs)
        return {
            "users": users,
            "is_filtered": False,
            "date_unknown": True,
            "has_candidates": bool(users),
            "current_staff_outside_candidates": False,
            "excluded_reasons": {},
        }

    available_shift_statuses = [
        StaffShift.Status.WORKING,
        StaffShift.Status.HALF_DAY,
        StaffShift.Status.TRAINING,
    ]
    shift_staff_ids = set(
        StaffShift.objects
        .filter(
            clinic=clinic,
            date=target_date,
            status__in=available_shift_statuses,
        )
        .values_list("staff_id", flat=True)
    )
    clinic_settings = ClinicSettings.objects.filter(clinic=clinic).first()
    leave_staff_ids = set()
    excluded_reasons = {}
    approved_leaves = (
        StaffLeave.objects
        .filter(
            clinic=clinic,
            status=StaffLeave.Status.APPROVED,
            start_date__lte=target_date,
            end_date__gte=target_date,
        )
        .select_related("staff")
    )
    for leave in approved_leaves:
        if _staff_leave_overlaps_appointment(
            leave,
            target_start_time,
            target_end_time,
            clinic_settings,
        ):
            leave_staff_ids.add(leave.staff_id)
            excluded_reasons[leave.staff_id] = _staff_leave_candidate_reason(leave)

    candidate_ids = shift_staff_ids - leave_staff_ids
    users = list(base_qs.filter(id__in=candidate_ids))

    current_staff_outside = False
    if (
        current_staff
        and getattr(current_staff, "clinic_id", None) == clinic.id
        and current_staff.id not in {user.id for user in users}
    ):
        current_staff_outside = True
        users.append(current_staff)

    for user in users:
        user.is_appointment_staff_candidate = user.id in candidate_ids
        user.appointment_staff_note = (
            "勤務候補"
            if user.is_appointment_staff_candidate
            else excluded_reasons.get(user.id, "シフト外のため候補外")
        )

    return {
        "users": users,
        "is_filtered": True,
        "date_unknown": False,
        "has_candidates": bool(candidate_ids),
        "current_staff_outside_candidates": current_staff_outside,
        "excluded_reasons": excluded_reasons,
    }


def _is_staff_available_for_appointment(clinic, staff_user, target_dt, target_end_dt=None):
    if not staff_user:
        return True, ""
    target_date = _appointment_staff_target_date(target_dt)
    if target_date is None:
        return True, ""
    candidates = _build_appointment_staff_candidates(
        clinic,
        target_date=target_date,
        target_start=target_dt,
        target_end=target_end_dt,
    )
    candidate_ids = {user.id for user in candidates["users"] if user.is_appointment_staff_candidate}
    if staff_user.id in candidate_ids:
        return True, ""
    reason = candidates.get("excluded_reasons", {}).get(
        staff_user.id,
        "シフト外のため候補外",
    )
    return (
        False,
        f"この日時では、担当者が勤務候補外です（{reason}）。シフトまたは休暇設定を確認してください。",
    )


def _closed_weekday_key(target_date):
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][target_date.weekday()]


def check_appointment_availability(
    *,
    clinic,
    start_at,
    end_at=None,
    assigned_staff=None,
    exclude_appointment_id=None,
):
    errors = []
    warnings = []
    conflict_appointments = []

    def add_error(message):
        if message not in errors:
            errors.append(message)

    def add_warning(message):
        if message not in warnings:
            warnings.append(message)

    start_at = _normalize_appointment_datetime(start_at)
    end_at = _normalize_appointment_datetime(end_at)
    clinic_settings = ClinicSettings.objects.filter(clinic=clinic).first()
    if start_at and not end_at:
        minutes = (
            clinic_settings.appointment_interval_minutes
            if clinic_settings
            else 30
        )
        end_at = start_at + timedelta(minutes=minutes or 30)

    if not start_at:
        add_error("予約開始日時が不正です。")
        return {
            "is_valid": False,
            "errors": errors,
            "warnings": warnings,
            "conflict_appointments": conflict_appointments,
        }

    if not end_at or end_at <= start_at:
        add_error("予約終了日時は開始日時より後にしてください。")
        return {
            "is_valid": False,
            "errors": errors,
            "warnings": warnings,
            "conflict_appointments": conflict_appointments,
        }

    local_start = timezone.localtime(start_at)
    local_end = timezone.localtime(end_at)
    target_date = local_start.date()
    start_time = local_start.time()
    end_time = local_end.time()

    if local_start.date() != local_end.date():
        add_error("日付をまたぐ予約は登録できません。")

    if clinic_settings:
        closed_weekdays = clinic_settings.closed_weekdays or []
        if _closed_weekday_key(target_date) in closed_weekdays:
            add_error("休診曜日です。予約日時を確認してください。")

        if (
            clinic_settings.business_start_time
            and start_time < clinic_settings.business_start_time
        ) or (
            clinic_settings.business_end_time
            and end_time > clinic_settings.business_end_time
        ):
            add_error("営業時間外です。予約日時を確認してください。")

        if (
            clinic_settings.break_start_time
            and clinic_settings.break_end_time
            and _time_ranges_overlap(
                start_time,
                end_time,
                clinic_settings.break_start_time,
                clinic_settings.break_end_time,
            )
        ):
            add_warning("休憩時間と重なっています。予約日時を確認してください。")

    if assigned_staff:
        if getattr(assigned_staff, "clinic_id", None) != clinic.id:
            add_error("他院の担当者は選択できません。")
        else:
            shift = (
                StaffShift.objects
                .filter(
                    clinic=clinic,
                    staff=assigned_staff,
                    date=target_date,
                )
                .first()
            )
            if shift is None:
                add_error("対象日の勤務シフトがありません。")
            elif shift.status == StaffShift.Status.OFF:
                add_error("この担当者は対象日に休みです。")
            elif shift.start_time and shift.end_time and (
                start_time < shift.start_time
                or end_time > shift.end_time
            ):
                add_error("この担当者の勤務時間外です。")

            is_available, availability_error = _is_staff_available_for_appointment(
                clinic,
                assigned_staff,
                start_at,
                end_at,
            )
            if not is_available:
                add_error(availability_error)

            overlap_qs = (
                Appointment.objects
                .filter(
                    clinic=clinic,
                    assigned_staff=assigned_staff,
                    start_at__lt=end_at,
                    end_at__gt=start_at,
                )
                .exclude(
                    status__in=[
                        Appointment.Status.CANCELLED,
                        Appointment.Status.NO_SHOW,
                    ]
                )
                .select_related("patient", "assigned_staff")
                .order_by("start_at")
            )
            if exclude_appointment_id:
                overlap_qs = overlap_qs.exclude(pk=exclude_appointment_id)

            conflict_appointments = list(overlap_qs)
            if conflict_appointments:
                add_error("この担当者は同じ時間帯に別の予約があります。")

    return {
        "is_valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "conflict_appointments": conflict_appointments,
    }


def _shift_status_class(status):
    return {
        StaffShift.Status.WORKING: "working",
        StaffShift.Status.OFF: "off",
        StaffShift.Status.HALF_DAY: "half-day",
        StaffShift.Status.TRAINING: "training",
        StaffShift.Status.OTHER: "other",
    }.get(status, "other")


def _leave_type_class(leave_type):
    return {
        StaffLeave.LeaveType.PAID_LEAVE: "paid-leave",
        StaffLeave.LeaveType.MORNING_OFF: "morning-off",
        StaffLeave.LeaveType.AFTERNOON_OFF: "afternoon-off",
        StaffLeave.LeaveType.ABSENCE: "absence",
        StaffLeave.LeaveType.TRAINING: "training",
        StaffLeave.LeaveType.OTHER: "other",
    }.get(leave_type, "other")


def _leave_status_class(status):
    return {
        StaffLeave.Status.REQUESTED: "requested",
        StaffLeave.Status.APPROVED: "approved",
        StaffLeave.Status.REJECTED: "rejected",
        StaffLeave.Status.CANCELED: "canceled",
    }.get(status, "requested")


def _format_leave_period(leave):
    if leave.start_date == leave.end_date:
        return leave.start_date.strftime("%Y/%m/%d")
    return f"{leave.start_date.strftime('%Y/%m/%d')}〜{leave.end_date.strftime('%Y/%m/%d')}"


def _format_leave_time(leave):
    if leave.start_time and leave.end_time:
        return f"{leave.start_time.strftime('%H:%M')}〜{leave.end_time.strftime('%H:%M')}"
    return "終日"


def _format_shift_time(shift):
    if shift.status == StaffShift.Status.OFF:
        return "休み"
    if shift.start_time and shift.end_time:
        return f"{shift.start_time.strftime('%H:%M')}〜{shift.end_time.strftime('%H:%M')}"
    return shift.get_status_display()


def _format_time_range(start_value, end_value, fallback="-"):
    if start_value and end_value:
        return f"{start_value.strftime('%H:%M')}〜{end_value.strftime('%H:%M')}"
    return fallback


def _build_staff_appointment_item(appointment):
    patient_name = "（患者未確定）"
    if appointment.patient:
        patient_name = f"{appointment.patient.last_name} {appointment.patient.first_name}"

    local_start = timezone.localtime(appointment.start_at)
    local_end = (
        timezone.localtime(appointment.end_at)
        if appointment.end_at
        else local_start + timedelta(minutes=30)
    )
    return {
        "id": appointment.id,
        "time_label": f"{local_start.strftime('%H:%M')}〜{local_end.strftime('%H:%M')}",
        "patient_name": patient_name,
        "menu": appointment.menu or "-",
        "status": appointment.status,
        "status_label": appointment.get_status_display(),
        "pre_check_url": (
            reverse("staff:pre_treatment_check", args=[appointment.patient_id])
            if appointment.patient_id
            else ""
        ),
        "day_url": (
            f"{reverse('staff:appointments')}?period=day&day={local_start.date().isoformat()}"
        ),
    }


def _build_staff_availability_rows(clinic, base_day, clinic_settings=None):
    staff_users = list(
        User.objects
        .filter(
            clinic=clinic,
            is_active=True,
            role__in=_shift_staff_roles(),
        )
        .order_by("last_name", "first_name", "username")
    )
    staff_ids = [user.id for user in staff_users]

    shifts = {
        shift.staff_id: shift
        for shift in StaffShift.objects.filter(
            clinic=clinic,
            staff_id__in=staff_ids,
            date=base_day,
        ).select_related("staff")
    }

    leaves_by_staff = {staff_id: [] for staff_id in staff_ids}
    for leave in (
        StaffLeave.objects
        .filter(
            clinic=clinic,
            staff_id__in=staff_ids,
            start_date__lte=base_day,
            end_date__gte=base_day,
        )
        .select_related("staff")
        .order_by("start_time", "leave_type", "id")
    ):
        leaves_by_staff.setdefault(leave.staff_id, []).append(leave)

    appointments_by_staff = {staff_id: [] for staff_id in staff_ids}
    unassigned_appointments = []
    day_appointments = (
        Appointment.objects
        .select_related("patient", "assigned_staff")
        .filter(clinic=clinic, start_at__date=base_day)
        .order_by("start_at")
    )
    for appointment in day_appointments:
        item = _build_staff_appointment_item(appointment)
        if appointment.assigned_staff_id in appointments_by_staff:
            appointments_by_staff[appointment.assigned_staff_id].append(item)
        elif appointment.assigned_staff_id is None:
            unassigned_appointments.append(item)

    rows = []
    for user in staff_users:
        shift = shifts.get(user.id)
        leaves = leaves_by_staff.get(user.id, [])
        approved_leaves = [
            leave
            for leave in leaves
            if leave.status == StaffLeave.Status.APPROVED
        ]
        full_day_leave = any(
            _staff_leave_overlaps_appointment(
                leave,
                None,
                None,
                clinic_settings,
            )
            and leave.leave_type not in [
                StaffLeave.LeaveType.MORNING_OFF,
                StaffLeave.LeaveType.AFTERNOON_OFF,
            ]
            and not (leave.start_time and leave.end_time)
            for leave in approved_leaves
        )
        partial_leave = any(
            leave.leave_type in [
                StaffLeave.LeaveType.MORNING_OFF,
                StaffLeave.LeaveType.AFTERNOON_OFF,
            ]
            or (leave.start_time and leave.end_time)
            for leave in approved_leaves
        )
        appointment_items = appointments_by_staff.get(user.id, [])
        appointment_count = len(appointment_items)

        if not shift:
            shift_label = "シフト未設定"
            work_time_label = "-"
            break_time_label = "-"
            availability_label = "予約不可" if appointment_count == 0 else "要確認"
            availability_class = "unavailable" if appointment_count == 0 else "check"
        elif shift.status == StaffShift.Status.OFF:
            shift_label = shift.get_status_display()
            work_time_label = "休み"
            break_time_label = "-"
            availability_label = "予約不可" if appointment_count == 0 else "要確認"
            availability_class = "unavailable" if appointment_count == 0 else "check"
        elif full_day_leave:
            shift_label = "承認済み休暇"
            work_time_label = _format_time_range(shift.start_time, shift.end_time)
            break_time_label = _format_time_range(shift.break_start, shift.break_end)
            availability_label = "予約不可" if appointment_count == 0 else "要確認"
            availability_class = "unavailable" if appointment_count == 0 else "check"
        elif partial_leave:
            shift_label = shift.get_status_display()
            work_time_label = _format_time_range(shift.start_time, shift.end_time)
            break_time_label = _format_time_range(shift.break_start, shift.break_end)
            availability_label = "要確認"
            availability_class = "check"
        elif appointment_count >= 6:
            shift_label = shift.get_status_display()
            work_time_label = _format_time_range(shift.start_time, shift.end_time)
            break_time_label = _format_time_range(shift.break_start, shift.break_end)
            availability_label = "混雑"
            availability_class = "busy"
        elif appointment_count >= 3:
            shift_label = shift.get_status_display()
            work_time_label = _format_time_range(shift.start_time, shift.end_time)
            break_time_label = _format_time_range(shift.break_start, shift.break_end)
            availability_label = "やや混雑"
            availability_class = "crowded"
        else:
            shift_label = shift.get_status_display()
            work_time_label = _format_time_range(shift.start_time, shift.end_time)
            break_time_label = _format_time_range(shift.break_start, shift.break_end)
            availability_label = "空きあり"
            availability_class = "available"

        leave_badges = []
        for leave in leaves:
            leave_badges.append({
                "label": leave.get_leave_type_display(),
                "status_label": leave.get_status_display(),
                "time_label": _format_leave_time(leave),
                "class": _leave_type_class(leave.leave_type),
                "status_class": _leave_status_class(leave.status),
            })

        rows.append({
            "staff_id": user.id,
            "staff_name": user.get_full_name().strip() or user.username,
            "shift_label": shift_label,
            "work_time_label": work_time_label,
            "break_time_label": break_time_label,
            "leave_badges": leave_badges,
            "appointment_count": appointment_count,
            "appointments": appointment_items,
            "availability_label": availability_label,
            "availability_class": availability_class,
        })

    if unassigned_appointments:
        rows.append({
            "staff_id": None,
            "staff_name": "未割当",
            "shift_label": "担当未設定",
            "work_time_label": "-",
            "break_time_label": "-",
            "leave_badges": [],
            "appointment_count": len(unassigned_appointments),
            "appointments": unassigned_appointments,
            "availability_label": "要確認",
            "availability_class": "check",
        })

    return rows


def _staff_shift_initial(clinic, request):
    clinic_settings = ClinicSettings.objects.filter(clinic=clinic).first()
    initial = {
        "date": timezone.localdate(),
        "status": StaffShift.Status.WORKING,
        "start_time": time(9, 0),
        "end_time": time(18, 0),
        "break_start": time(13, 0),
        "break_end": time(14, 0),
    }
    if clinic_settings:
        initial.update({
            "start_time": clinic_settings.business_start_time,
            "end_time": clinic_settings.business_end_time,
            "break_start": clinic_settings.break_start_time,
            "break_end": clinic_settings.break_end_time,
        })

    shift_date = parse_date(request.GET.get("date") or "")
    if shift_date:
        initial["date"] = shift_date

    staff_id = request.GET.get("staff")
    if staff_id:
        staff_user = (
            User.objects
            .filter(
                pk=staff_id,
                clinic=clinic,
                is_active=True,
                role__in=_shift_staff_roles(),
            )
            .first()
        )
        if staff_user:
            initial["staff"] = staff_user
    return initial


@staff_required
def staff_shift_month_view(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のシフトのみ閲覧できます。")

    month_start, month_end, next_month, prev_month = _parse_shift_month(request)
    month_days = [
        month_start + timedelta(days=offset)
        for offset in range((month_end - month_start).days + 1)
    ]
    selected_staff_id = request.GET.get("staff") or ""
    selected_staff = None

    shifts = list(
        StaffShift.objects
        .filter(
            clinic=clinic,
            date__gte=month_start,
            date__lt=next_month,
        )
        .select_related("staff")
        .order_by("staff__last_name", "staff__first_name", "date")
    )
    shifted_staff_ids = {shift.staff_id for shift in shifts}
    leaves = list(
        StaffLeave.objects
        .filter(
            clinic=clinic,
            start_date__lte=month_end,
            end_date__gte=month_start,
        )
        .exclude(status__in=[
            StaffLeave.Status.REJECTED,
            StaffLeave.Status.CANCELED,
        ])
        .select_related("staff")
        .order_by("staff__last_name", "staff__first_name", "start_date")
    )
    leave_staff_ids = {leave.staff_id for leave in leaves}
    staff_qs = (
        User.objects
        .filter(clinic=clinic, role__in=_shift_staff_roles())
        .filter(Q(is_active=True) | Q(id__in=shifted_staff_ids | leave_staff_ids))
        .order_by("-is_active", "last_name", "first_name", "username")
    )
    if selected_staff_id:
        selected_staff = get_object_or_404(
            User,
            pk=selected_staff_id,
            clinic=clinic,
            role__in=_shift_staff_roles(),
        )
        staff_qs = staff_qs.filter(pk=selected_staff.id)

    shift_map = {}
    for shift in shifts:
        shift.status_class = _shift_status_class(shift.status)
        shift.time_label = _format_shift_time(shift)
        shift.edit_url = reverse("staff:staff_shift_update", args=[shift.id])
        shift_map[(shift.staff_id, shift.date)] = shift

    leave_map = {}
    for leave in leaves:
        leave.type_class = _leave_type_class(leave.leave_type)
        leave.status_class = _leave_status_class(leave.status)
        leave.period_label = _format_leave_period(leave)
        leave.time_label = _format_leave_time(leave)
        leave.edit_url = reverse("staff:staff_leave_update", args=[leave.id])
        current_day = max(leave.start_date, month_start)
        last_day = min(leave.end_date, month_end)
        while current_day <= last_day:
            leave_map.setdefault((leave.staff_id, current_day), []).append(leave)
            current_day += timedelta(days=1)

    rows = []
    for staff_user in staff_qs:
        full_name = (
            f"{staff_user.last_name} {staff_user.first_name}".strip()
            or staff_user.username
        )
        cells = []
        for day in month_days:
            shift = shift_map.get((staff_user.id, day))
            cells.append({
                "date": day,
                "is_today": day == timezone.localdate(),
                "shift": shift,
                "leaves": leave_map.get((staff_user.id, day), []),
                "create_url": (
                    reverse("staff:staff_shift_create")
                    + f"?staff={staff_user.id}&date={day.isoformat()}"
                ),
            })
        rows.append({
            "staff": staff_user,
            "name": full_name,
            "is_active": staff_user.is_active,
            "cells": cells,
        })

    query_staff = f"&staff={selected_staff.id}" if selected_staff else ""
    return render(request, "staff/staff_shift_month.html", {
        "active": "shifts",
        "page_title": "スタッフシフト管理",
        "clinic": clinic,
        "month_start": month_start,
        "month_end": month_end,
        "today": timezone.localdate(),
        "month_days": month_days,
        "rows": rows,
        "selected_staff": selected_staff,
        "staff_options": (
            User.objects
            .filter(clinic=clinic, role__in=_shift_staff_roles())
            .order_by("-is_active", "last_name", "first_name", "username")
        ),
        "prev_month_url": (
            reverse("staff:staff_shift_month")
            + f"?year={prev_month.year}&month={prev_month.month}{query_staff}"
        ),
        "next_month_url": (
            reverse("staff:staff_shift_month")
            + f"?year={next_month.year}&month={next_month.month}{query_staff}"
        ),
        "current_month_url": reverse("staff:staff_shift_month"),
        "create_url": reverse("staff:staff_shift_create"),
    })


@staff_required
def staff_shift_create_view(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のシフトのみ作成できます。")

    if request.method == "POST":
        form = StaffShiftForm(request.POST, clinic=clinic)
        if form.is_valid():
            shift = form.save()
            messages.success(request, "スタッフシフトを登録しました。")
            return redirect(
                reverse("staff:staff_shift_month")
                + f"?year={shift.date.year}&month={shift.date.month}"
            )
    else:
        form = StaffShiftForm(
            clinic=clinic,
            initial=_staff_shift_initial(clinic, request),
        )

    return render(request, "staff/staff_shift_form.html", {
        "active": "shifts",
        "page_title": "シフト登録",
        "form": form,
        "is_edit": False,
    })


@staff_required
def staff_shift_update_view(request, shift_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のシフトのみ編集できます。")

    shift = get_object_or_404(
        StaffShift.objects.select_related("clinic", "staff"),
        pk=shift_id,
        clinic=clinic,
    )
    if request.method == "POST":
        form = StaffShiftForm(request.POST, instance=shift, clinic=clinic)
        if form.is_valid():
            shift = form.save()
            messages.success(request, "スタッフシフトを保存しました。")
            return redirect(
                reverse("staff:staff_shift_month")
                + f"?year={shift.date.year}&month={shift.date.month}&staff={shift.staff_id}"
            )
    else:
        form = StaffShiftForm(instance=shift, clinic=clinic)

    return render(request, "staff/staff_shift_form.html", {
        "active": "shifts",
        "page_title": "シフト編集",
        "form": form,
        "is_edit": True,
        "shift": shift,
    })


def _parse_leave_month(request):
    month_start, month_end, next_month, prev_month = _parse_shift_month(request)
    return month_start, month_end, next_month, prev_month


@staff_required
def staff_leave_list_view(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の休暇のみ閲覧できます。")

    month_start, month_end, next_month, prev_month = _parse_leave_month(request)
    staff_id = request.GET.get("staff") or ""
    leave_type = request.GET.get("leave_type") or ""
    status = request.GET.get("status") or ""

    leaves = (
        StaffLeave.objects
        .filter(
            clinic=clinic,
            start_date__lte=month_end,
            end_date__gte=month_start,
        )
        .select_related("staff")
        .order_by("start_date", "staff__last_name", "staff__first_name", "id")
    )
    selected_staff = None
    if staff_id:
        selected_staff = get_object_or_404(
            User,
            pk=staff_id,
            clinic=clinic,
            role__in=_shift_staff_roles(),
        )
        leaves = leaves.filter(staff=selected_staff)
    if leave_type in dict(StaffLeave.LeaveType.choices):
        leaves = leaves.filter(leave_type=leave_type)
    else:
        leave_type = ""
    if status in dict(StaffLeave.Status.choices):
        leaves = leaves.filter(status=status)
    else:
        status = ""

    leave_items = []
    for leave in leaves:
        leave.type_class = _leave_type_class(leave.leave_type)
        leave.status_class = _leave_status_class(leave.status)
        leave.period_label = _format_leave_period(leave)
        leave.time_label = _format_leave_time(leave)
        leave.staff_name = (
            f"{leave.staff.last_name} {leave.staff.first_name}".strip()
            or leave.staff.username
        )
        leave.edit_url = reverse("staff:staff_leave_update", args=[leave.id])
        leave_items.append(leave)

    staff_options = (
        User.objects
        .filter(clinic=clinic, role__in=_shift_staff_roles())
        .order_by("-is_active", "last_name", "first_name", "username")
    )
    query_staff = f"&staff={selected_staff.id}" if selected_staff else ""
    query_type = f"&leave_type={leave_type}" if leave_type else ""
    query_status = f"&status={status}" if status else ""
    query_tail = f"{query_staff}{query_type}{query_status}"

    return render(request, "staff/staff_leave_list.html", {
        "active": "leaves",
        "page_title": "休暇・有給管理",
        "clinic": clinic,
        "month_start": month_start,
        "month_end": month_end,
        "leaves": leave_items,
        "staff_options": staff_options,
        "selected_staff": selected_staff,
        "filters": {
            "staff": staff_id,
            "leave_type": leave_type,
            "status": status,
        },
        "leave_type_choices": StaffLeave.LeaveType.choices,
        "status_choices": StaffLeave.Status.choices,
        "prev_month_url": (
            reverse("staff:staff_leave_list")
            + f"?year={prev_month.year}&month={prev_month.month}{query_tail}"
        ),
        "next_month_url": (
            reverse("staff:staff_leave_list")
            + f"?year={next_month.year}&month={next_month.month}{query_tail}"
        ),
        "current_month_url": reverse("staff:staff_leave_list"),
        "create_url": reverse("staff:staff_leave_create"),
        "shift_month_url": reverse("staff:staff_shift_month"),
    })


def _staff_leave_initial(clinic, request):
    today = timezone.localdate()
    initial = {
        "start_date": today,
        "end_date": today,
        "leave_type": StaffLeave.LeaveType.PAID_LEAVE,
        "status": StaffLeave.Status.APPROVED,
    }
    leave_date = parse_date(request.GET.get("date") or "")
    if leave_date:
        initial["start_date"] = leave_date
        initial["end_date"] = leave_date
    staff_id = request.GET.get("staff")
    if staff_id:
        staff_user = (
            User.objects
            .filter(
                pk=staff_id,
                clinic=clinic,
                is_active=True,
                role__in=_shift_staff_roles(),
            )
            .first()
        )
        if staff_user:
            initial["staff"] = staff_user
    return initial


@staff_required
def staff_leave_create_view(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の休暇のみ作成できます。")

    if request.method == "POST":
        form = StaffLeaveForm(request.POST, clinic=clinic)
        if form.is_valid():
            leave = form.save()
            messages.success(request, "スタッフ休暇を登録しました。")
            return redirect(
                reverse("staff:staff_leave_list")
                + f"?year={leave.start_date.year}&month={leave.start_date.month}&staff={leave.staff_id}"
            )
    else:
        form = StaffLeaveForm(
            clinic=clinic,
            initial=_staff_leave_initial(clinic, request),
        )

    return render(request, "staff/staff_leave_form.html", {
        "active": "leaves",
        "page_title": "休暇登録",
        "form": form,
        "is_edit": False,
    })


@staff_required
def staff_leave_update_view(request, leave_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の休暇のみ編集できます。")

    leave = get_object_or_404(
        StaffLeave.objects.select_related("clinic", "staff"),
        pk=leave_id,
        clinic=clinic,
    )
    if request.method == "POST":
        form = StaffLeaveForm(request.POST, instance=leave, clinic=clinic)
        if form.is_valid():
            leave = form.save()
            messages.success(request, "スタッフ休暇を保存しました。")
            return redirect(
                reverse("staff:staff_leave_list")
                + f"?year={leave.start_date.year}&month={leave.start_date.month}&staff={leave.staff_id}"
            )
    else:
        form = StaffLeaveForm(instance=leave, clinic=clinic)

    return render(request, "staff/staff_leave_form.html", {
        "active": "leaves",
        "page_title": "休暇編集",
        "form": form,
        "is_edit": True,
        "leave": leave,
    })


@staff_required
def staff_patient_search_view(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の患者情報のみ閲覧できます。")

    q = (request.GET.get("q") or "").strip()
    selected_filter = (request.GET.get("filter") or "").strip()
    valid_filters = {
        "",
        "today",
        "recent",
        "no_note",
        "confirmation_waiting",
        "posture",
        "plan",
        "attention",
    }
    if selected_filter not in valid_filters:
        selected_filter = ""

    today = timezone.localdate()
    recent_from = today - timedelta(days=30)

    latest_intake = (
        Intake.objects
        .filter(
            clinic=clinic,
            patient=OuterRef("pk"),
        )
        .order_by("-submitted_at", "-id")
    )
    latest_appointment = (
        Appointment.objects
        .filter(
            clinic=clinic,
            patient=OuterRef("pk"),
        )
        .order_by("-start_at")
    )
    latest_completed_appointment = (
        Appointment.objects
        .filter(
            clinic=clinic,
            patient=OuterRef("pk"),
            status=Appointment.Status.COMPLETED,
        )
        .order_by("-start_at")
    )
    today_appointment = (
        Appointment.objects
        .filter(
            clinic=clinic,
            patient=OuterRef("pk"),
            start_at__date=today,
        )
        .exclude(
            status__in=[
                Appointment.Status.CANCELLED,
                Appointment.Status.NO_SHOW,
            ]
        )
        .order_by("start_at")
    )
    latest_note = (
        ClinicalNote.objects
        .filter(
            patient=OuterRef("pk"),
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .order_by("-created_at")
    )
    latest_plan = (
        TreatmentPlan.objects
        .filter(
            patient=OuterRef("pk"),
            patient__clinic=clinic,
        )
        .order_by("-created_at")
    )
    waiting_recordings = (
        InterviewRecording.objects
        .filter(
            clinic=clinic,
            patient=OuterRef("pk"),
        )
        .exclude(summary_json={})
        .filter(
            Q(confirmed_summary_json__isnull=True)
            | Q(confirmed_summary_json={})
        )
    )
    waiting_sessions = (
        TreatmentSession.objects
        .filter(
            clinic=clinic,
            patient=OuterRef("pk"),
        )
        .exclude(summary_json={})
        .filter(
            Q(confirmed_summary_json__isnull=True)
            | Q(confirmed_summary_json={})
        )
    )
    recording_errors = (
        InterviewRecording.objects
        .filter(
            clinic=clinic,
            patient=OuterRef("pk"),
        )
        .filter(
            Q(status=InterviewRecording.Status.FAILED)
            | ~Q(error_message="")
        )
    )
    session_errors = (
        TreatmentSession.objects
        .filter(
            clinic=clinic,
            patient=OuterRef("pk"),
        )
        .filter(
            Q(status=TreatmentSession.Status.FAILED)
            | ~Q(error_message="")
        )
    )

    qs = (
        Patient.objects
        .filter(clinic=clinic)
        .annotate(
            latest_chief_complaint=Subquery(
                latest_intake.values("chief_complaint")[:1]
            ),
            latest_plan_complaint=Subquery(
                latest_plan.values("chief_complaint")[:1]
            ),
            latest_appointment_at=Subquery(
                latest_appointment.values("start_at")[:1]
            ),
            last_visit_at=Subquery(
                latest_completed_appointment.values("start_at")[:1]
            ),
            today_appointment_id=Subquery(
                today_appointment.values("id")[:1]
            ),
            latest_note_at=Subquery(
                latest_note.values("created_at")[:1]
            ),
            latest_note_id=Subquery(
                latest_note.values("id")[:1]
            ),
            latest_plan_status=Subquery(
                latest_plan.values("status")[:1]
            ),
            has_today_appointment=Exists(today_appointment),
            has_recent_visit=Exists(
                latest_completed_appointment.filter(
                    start_at__date__gte=recent_from,
                )
            ),
            has_clinical_note=Exists(latest_note),
            has_waiting_recording=Exists(waiting_recordings),
            has_waiting_session=Exists(waiting_sessions),
            has_recording_error=Exists(recording_errors),
            has_session_error=Exists(session_errors),
            has_posture_assessment=Exists(
                PostureAssessment.objects.filter(
                    clinic=clinic,
                    patient=OuterRef("pk"),
                )
            ),
            has_treatment_plan=Exists(latest_plan),
        )
        .order_by("last_name", "first_name", "id")
    )
    if q:
        qs = qs.filter(
            Q(last_name__icontains=q)
            | Q(first_name__icontains=q)
            | Q(last_name_kana__icontains=q)
            | Q(first_name_kana__icontains=q)
            | Q(phone__icontains=q)
            | Q(card_no__icontains=q)
            | Q(intakes__chief_complaint__icontains=q)
            | Q(treatment_plans__chief_complaint__icontains=q)
        ).distinct()

    if selected_filter == "today":
        qs = qs.filter(has_today_appointment=True)
    elif selected_filter == "recent":
        qs = qs.filter(has_recent_visit=True)
    elif selected_filter == "no_note":
        qs = qs.filter(has_clinical_note=False)
    elif selected_filter == "confirmation_waiting":
        qs = qs.filter(
            Q(has_waiting_recording=True)
            | Q(has_waiting_session=True)
        )
    elif selected_filter == "posture":
        qs = qs.filter(has_posture_assessment=True)
    elif selected_filter == "plan":
        qs = qs.filter(has_treatment_plan=True)
    elif selected_filter == "attention":
        qs = qs.filter(
            Q(has_waiting_recording=True)
            | Q(has_waiting_session=True)
            | Q(has_recording_error=True)
            | Q(has_session_error=True)
        )

    paginator = Paginator(qs, 25)
    page_obj = paginator.get_page(request.GET.get("page"))
    today_value = timezone.localdate()
    plan_status_labels = dict(TreatmentPlan.STATUS_CHOICES)
    for patient in page_obj.object_list:
        patient.age = (
            today_value.year
            - patient.birth_date.year
            - (
                (today_value.month, today_value.day)
                < (patient.birth_date.month, patient.birth_date.day)
            )
        ) if patient.birth_date else None
        patient.main_complaint = (
            patient.latest_chief_complaint
            or patient.latest_plan_complaint
            or "未登録"
        )
        patient.latest_treatment_status = plan_status_labels.get(
            patient.latest_plan_status,
            "未作成",
        )
        patient.needs_attention = any((
            patient.has_waiting_recording,
            patient.has_waiting_session,
            patient.has_recording_error,
            patient.has_session_error,
        ))

    return render(request, "staff/patients/search.html", {
        "active": "patient_search",
        "page_title": "患者様一覧",
        "q": q,
        "selected_filter": selected_filter,
        "patients": page_obj.object_list,
        "page_obj": page_obj,
        "result_count": paginator.count,
    })


def _kpi_recording_querysets(clinic):
    waiting_recordings = (
        InterviewRecording.objects
        .filter(clinic=clinic)
        .select_related("patient", "appointment")
        .exclude(summary_json={})
        .filter(
            Q(confirmed_summary_json__isnull=True)
            | Q(confirmed_summary_json={})
        )
    )
    waiting_sessions = (
        TreatmentSession.objects
        .filter(clinic=clinic)
        .select_related("patient", "appointment")
        .exclude(summary_json={})
        .filter(
            Q(confirmed_summary_json__isnull=True)
            | Q(confirmed_summary_json={})
        )
    )
    error_recordings = (
        InterviewRecording.objects
        .filter(clinic=clinic)
        .select_related("patient", "appointment")
        .filter(
            Q(status=InterviewRecording.Status.FAILED)
            | ~Q(error_message="")
        )
    )
    error_sessions = (
        TreatmentSession.objects
        .filter(clinic=clinic)
        .select_related("patient", "appointment")
        .filter(
            Q(status=TreatmentSession.Status.FAILED)
            | ~Q(error_message="")
        )
    )
    transcript_only_recordings = (
        InterviewRecording.objects
        .filter(clinic=clinic)
        .select_related("patient", "appointment")
        .exclude(transcript_text="")
        .filter(summary_json={})
    )
    transcript_only_sessions = (
        TreatmentSession.objects
        .filter(clinic=clinic)
        .select_related("patient", "appointment")
        .exclude(transcript_text="")
        .filter(summary_json={})
    )
    no_appointment_sessions = (
        TreatmentSession.objects
        .filter(clinic=clinic, appointment__isnull=True)
        .select_related("patient")
    )
    return {
        "waiting_recordings": waiting_recordings,
        "waiting_sessions": waiting_sessions,
        "error_recordings": error_recordings,
        "error_sessions": error_sessions,
        "transcript_only_recordings": transcript_only_recordings,
        "transcript_only_sessions": transcript_only_sessions,
        "no_appointment_sessions": no_appointment_sessions,
    }


def _build_staff_sales_kpi_context(clinic, today, seven_days_ago):
    month_start, next_month = get_month_range(today)
    paid_records = SalesRecord.objects.filter(
        clinic=clinic,
        status=SalesRecord.Status.PAID,
    )
    unpaid_records = SalesRecord.objects.filter(
        clinic=clinic,
        status=SalesRecord.Status.UNPAID,
    )
    canceled_records = SalesRecord.objects.filter(
        clinic=clinic,
        status=SalesRecord.Status.CANCELED,
    )

    today_paid = paid_records.filter(treatment_date=today)
    month_paid = paid_records.filter(
        treatment_date__gte=month_start,
        treatment_date__lt=next_month,
    )
    seven_day_paid = paid_records.filter(
        treatment_date__gte=seven_days_ago,
        treatment_date__lte=today,
    )
    due_unpaid = unpaid_records.filter(treatment_date__lte=today)
    month_canceled = canceled_records.filter(
        treatment_date__gte=month_start,
        treatment_date__lt=next_month,
    )

    today_sales = today_paid.aggregate(total=Sum("amount"))["total"] or 0
    month_sales = month_paid.aggregate(total=Sum("amount"))["total"] or 0
    seven_day_sales = (
        seven_day_paid.aggregate(total=Sum("amount"))["total"] or 0
    )

    daily_rows = (
        seven_day_paid
        .annotate(day=TruncDate("treatment_date"))
        .values("day")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("day")
    )
    daily_map = {row["day"]: row for row in daily_rows}
    daily_sales = []
    max_daily_sales = 0
    for offset in range(7):
        day = seven_days_ago + timedelta(days=offset)
        row = daily_map.get(day, {})
        amount = row.get("total") or 0
        max_daily_sales = max(max_daily_sales, amount)
        daily_sales.append({
            "day": day,
            "amount": amount,
            "amount_display": _format_yen(amount),
            "count": row.get("count") or 0,
        })
    for row in daily_sales:
        row["bar_percent"] = (
            round(row["amount"] / max_daily_sales * 100)
            if max_daily_sales else 0
        )

    menu_rows = (
        month_paid
        .values("treatment_menu_id", "treatment_menu__name")
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total", "treatment_menu__name")[:8]
    )
    menu_sales = [
        {
            "label": row["treatment_menu__name"] or "メニュー未設定",
            "count": row["count"],
            "total": row["total"] or 0,
            "total_display": _format_yen(row["total"] or 0),
        }
        for row in menu_rows
    ]

    payment_rows = (
        month_paid
        .values("payment_method")
        .annotate(total=Sum("amount"), count=Count("id"))
    )
    payment_map = {row["payment_method"]: row for row in payment_rows}
    payment_sales = []
    for value, label in SalesRecord.PaymentMethod.choices:
        row = payment_map.get(value, {})
        total = row.get("total") or 0
        payment_sales.append({
            "label": label,
            "count": row.get("count") or 0,
            "total": total,
            "total_display": _format_yen(total),
        })

    staff_rows = (
        month_paid
        .values(
            "staff_id",
            "staff__last_name",
            "staff__first_name",
            "staff__username",
        )
        .annotate(total=Sum("amount"), count=Count("id"))
        .order_by("-total", "staff__last_name", "staff__username")[:8]
    )
    staff_sales = []
    for row in staff_rows:
        if row["staff_id"]:
            full_name = " ".join(
                part for part in [
                    row.get("staff__last_name"),
                    row.get("staff__first_name"),
                ] if part
            )
            label = full_name or row.get("staff__username") or "担当者未設定"
        else:
            label = "担当者未設定"
        total = row["total"] or 0
        staff_sales.append({
            "label": label,
            "count": row["count"],
            "total": total,
            "total_display": _format_yen(total),
        })

    unpaid_sales_items = list(
        due_unpaid
        .select_related("patient", "treatment_menu", "staff")
        .order_by("treatment_date", "created_at")[:10]
    )
    for record in unpaid_sales_items:
        record.amount_display = _format_yen(record.amount)
        record.edit_url = reverse("staff:sales_record_update", args=[record.id])

    return {
        "sales_summary": {
            "today_sales": today_sales,
            "today_sales_display": _format_yen(today_sales),
            "month_sales": month_sales,
            "month_sales_display": _format_yen(month_sales),
            "seven_day_sales": seven_day_sales,
            "seven_day_sales_display": _format_yen(seven_day_sales),
            "today_paid_count": today_paid.count(),
            "unpaid_count": due_unpaid.count(),
            "canceled_count": month_canceled.count(),
        },
        "daily_sales": daily_sales,
        "menu_sales": menu_sales,
        "payment_sales": payment_sales,
        "staff_sales": staff_sales,
        "unpaid_sales_items": unpaid_sales_items,
    }


def build_staff_kpi_context(clinic):
    today = timezone.localdate()
    seven_days_ago = today - timedelta(days=6)
    recordings = _kpi_recording_querysets(clinic)
    sales_context = _build_staff_sales_kpi_context(
        clinic,
        today,
        seven_days_ago,
    )

    today_appointments = Appointment.objects.filter(
        clinic=clinic,
        start_at__date=today,
    )
    today_notes = ClinicalNote.objects.filter(
        patient__clinic=clinic,
        appointment__clinic=clinic,
        created_at__date=today,
    )
    today_initial_recordings = InterviewRecording.objects.filter(
        clinic=clinic,
        created_at__date=today,
    )
    today_treatment_sessions = TreatmentSession.objects.filter(
        clinic=clinic,
        created_at__date=today,
    )
    waiting_count = (
        recordings["waiting_recordings"].count()
        + recordings["waiting_sessions"].count()
    )

    today_cards = [
        {
            "label": "本日の予約",
            "value": today_appointments.count(),
            "note": "本日の予約管理へ",
            "tone": "blue",
            "url": f"{reverse('staff:appointments')}?day={today.isoformat()}",
        },
        {
            "label": "来院・対応済み",
            "value": today_appointments.filter(
                status__in=[
                    Appointment.Status.ARRIVED,
                    Appointment.Status.COMPLETED,
                ]
            ).count(),
            "note": "来院・完了ステータス",
            "tone": "green",
            "url": f"{reverse('staff:appointments')}?day={today.isoformat()}",
        },
        {
            "label": "カルテ登録",
            "value": today_notes.count(),
            "note": "本日登録されたカルテ",
            "tone": "navy",
            "url": reverse("staff:dashboard"),
        },
        {
            "label": "録音",
            "value": (
                today_initial_recordings.count()
                + today_treatment_sessions.count()
            ),
            "note": "初診録音・通院施術録音",
            "tone": "blue",
            "url": reverse("staff:dashboard"),
        },
        {
            "label": "患者向けレポート",
            "value": today_notes.count(),
            "note": "本日のカルテから作成可能",
            "tone": "green",
            "url": reverse("staff:dashboard"),
        },
        {
            "label": "カルテ案確認待ち",
            "value": waiting_count,
            "note": "施術者の確認が必要",
            "tone": "warning" if waiting_count else "neutral",
            "url": reverse("staff:dashboard"),
        },
    ]

    recent_cards = [
        {
            "label": "予約",
            "value": Appointment.objects.filter(
                clinic=clinic,
                start_at__date__gte=seven_days_ago,
                start_at__date__lte=today,
            ).count(),
        },
        {
            "label": "新規患者",
            "value": Patient.objects.filter(
                clinic=clinic,
                created_at__date__gte=seven_days_ago,
                created_at__date__lte=today,
            ).count(),
        },
        {
            "label": "カルテ登録",
            "value": ClinicalNote.objects.filter(
                patient__clinic=clinic,
                appointment__clinic=clinic,
                created_at__date__gte=seven_days_ago,
                created_at__date__lte=today,
            ).count(),
        },
        {
            "label": "初診録音",
            "value": InterviewRecording.objects.filter(
                clinic=clinic,
                created_at__date__gte=seven_days_ago,
                created_at__date__lte=today,
            ).count(),
        },
        {
            "label": "通院施術録音",
            "value": TreatmentSession.objects.filter(
                clinic=clinic,
                created_at__date__gte=seven_days_ago,
                created_at__date__lte=today,
            ).count(),
        },
        {
            "label": "姿勢分析",
            "value": PostureAssessment.objects.filter(
                clinic=clinic,
                created_at__date__gte=seven_days_ago,
                created_at__date__lte=today,
            ).count(),
        },
        {
            "label": "施術計画",
            "value": TreatmentPlan.objects.filter(
                patient__clinic=clinic,
                created_at__date__gte=seven_days_ago,
                created_at__date__lte=today,
            ).count(),
        },
        {
            "label": "患者向けレポート",
            "value": ClinicalNote.objects.filter(
                patient__clinic=clinic,
                appointment__clinic=clinic,
                created_at__date__gte=seven_days_ago,
                created_at__date__lte=today,
            ).count(),
        },
    ]

    attention_items = []

    def append_items(queryset, *, kind, state, url_name, priority):
        for item in queryset.order_by("-created_at")[:10]:
            attention_items.append({
                "patient": item.patient,
                "kind": kind,
                "state": state,
                "created_at": item.created_at,
                "url": reverse(url_name, args=[item.id]),
                "priority": priority,
            })

    append_items(
        recordings["waiting_recordings"],
        kind="初診録音",
        state="カルテ案確認待ち",
        url_name="intakes:recording_detail",
        priority=2,
    )
    append_items(
        recordings["waiting_sessions"],
        kind="通院施術録音",
        state="カルテ案確認待ち",
        url_name="treatment_sessions:detail",
        priority=2,
    )
    append_items(
        recordings["error_recordings"],
        kind="初診録音",
        state="エラーあり",
        url_name="intakes:recording_detail",
        priority=0,
    )
    append_items(
        recordings["error_sessions"],
        kind="通院施術録音",
        state="エラーあり",
        url_name="treatment_sessions:detail",
        priority=0,
    )
    append_items(
        recordings["transcript_only_recordings"],
        kind="初診録音",
        state="カルテ案作成待ち",
        url_name="intakes:recording_detail",
        priority=1,
    )
    append_items(
        recordings["transcript_only_sessions"],
        kind="通院施術録音",
        state="カルテ案作成待ち",
        url_name="treatment_sessions:detail",
        priority=1,
    )
    append_items(
        recordings["no_appointment_sessions"],
        kind="通院施術録音",
        state="予約情報なし",
        url_name="treatment_sessions:detail",
        priority=1,
    )
    for record in sales_context["unpaid_sales_items"]:
        attention_items.append({
            "patient": record.patient,
            "kind": "未会計",
            "state": "未会計",
            "created_at": record.created_at,
            "treatment_date": record.treatment_date,
            "amount_display": record.amount_display,
            "url": record.edit_url,
            "priority": 1,
        })
    attention_items = sorted(
        attention_items,
        key=lambda item: (
            item["priority"],
            -item["created_at"].timestamp(),
        ),
    )[:15]

    return {
        "today": today,
        "seven_days_ago": seven_days_ago,
        "today_cards": today_cards,
        "recent_cards": recent_cards,
        "attention_items": attention_items,
        "attention_counts": {
            "confirmation_waiting": waiting_count,
            "recording_errors": (
                recordings["error_recordings"].count()
                + recordings["error_sessions"].count()
            ),
            "summary_waiting": (
                recordings["transcript_only_recordings"].count()
                + recordings["transcript_only_sessions"].count()
            ),
            "unconfirmed": waiting_count,
            "without_appointment": recordings[
                "no_appointment_sessions"
            ].count(),
            "unpaid_sales": sales_context["sales_summary"]["unpaid_count"],
        },
        **sales_context,
    }


@staff_required
def staff_kpi_dashboard_view(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のKPIのみ閲覧できます。")

    return render(request, "staff/kpi_dashboard.html", {
        "active": "kpi",
        "page_title": "KPI",
        **build_staff_kpi_context(clinic),
    })


def _ai_usage_category(log):
    metadata = log.metadata if isinstance(log.metadata, dict) else {}
    source = str(metadata.get("source") or "").lower()

    if log.usage_type == AiUsageLog.UsageType.POSTURE:
        return "posture"
    if log.usage_type == AiUsageLog.UsageType.TREATMENT_PLAN:
        return "treatment_plan"
    if (
        metadata.get("treatment_session_id")
        or "treatment_session" in source
    ):
        return "treatment_session"
    if log.recording_id or "interview" in source:
        return "interview_recording"
    if log.usage_type in {
        AiUsageLog.UsageType.SUMMARY,
        AiUsageLog.UsageType.SOAP,
    }:
        return "clinical_summary"
    return "other"


def _ai_usage_warning_context(plan, used_minutes):
    if plan is None:
        return {
            "level": "unconfigured",
            "label": "プラン未設定",
            "message": "AI料金プランが未設定です。利用ログは引き続き確認できます。",
        }
    if not plan.is_ai_enabled:
        return {
            "level": "disabled",
            "label": "AI機能停止中",
            "message": "この院のAI機能は現在無効です。",
        }
    if used_minutes >= plan.hard_limit_minutes:
        return {
            "level": "danger",
            "label": "利用制限対象",
            "message": "hard limitに達しています。上限設定をご確認ください。",
        }

    usage_percent = plan.usage_percent(used_minutes)
    if usage_percent >= 100:
        return {
            "level": "overage",
            "label": "上限超過",
            "message": "上限を超過しています。追加利用またはプラン変更をご検討ください。",
        }
    if usage_percent >= 90:
        return {
            "level": "danger",
            "label": "上限間近",
            "message": "月間上限に近づいています。",
        }
    if usage_percent >= 70:
        return {
            "level": "warning",
            "label": "注意",
            "message": "AI利用量が増えています。残り分数にご注意ください。",
        }
    return {
        "level": "normal",
        "label": "通常",
        "message": "AI利用量は通常範囲です。",
    }


def _safe_metadata_id(metadata, *keys):
    if not isinstance(metadata, dict):
        return None
    for key in keys:
        value = metadata.get(key)
        if value in (None, ""):
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return None


def build_ai_usage_dashboard_context(clinic):
    today = timezone.localdate()
    month_start, next_month = get_month_range(today)
    seven_days_ago = today - timedelta(days=6)

    month_logs = list(
        AiUsageLog.objects
        .filter(
            clinic=clinic,
            status=AiUsageLog.Status.SUCCESS,
            created_at__date__gte=month_start,
            created_at__date__lt=next_month,
        )
        .only(
            "id",
            "usage_type",
            "billing_minutes",
            "input_tokens",
            "output_tokens",
            "estimated_cost_yen",
            "metadata",
            "recording_id",
        )
    )
    monthly = {
        "recording_minutes": sum(log.billing_minutes for log in month_logs),
        "transcription_count": sum(
            log.usage_type == AiUsageLog.UsageType.STT
            for log in month_logs
        ),
        "summary_count": sum(
            log.usage_type in {
                AiUsageLog.UsageType.SUMMARY,
                AiUsageLog.UsageType.SOAP,
            }
            for log in month_logs
        ),
        "posture_count": sum(
            log.usage_type == AiUsageLog.UsageType.POSTURE
            for log in month_logs
        ),
        "input_tokens": sum(log.input_tokens for log in month_logs),
        "output_tokens": sum(log.output_tokens for log in month_logs),
        "estimated_cost_yen": sum(
            log.estimated_cost_yen for log in month_logs
        ),
    }
    posture_assessment_count = PostureAssessment.objects.filter(
        clinic=clinic,
        status__in=[
            PostureAssessment.Status.ANALYZED,
            PostureAssessment.Status.CONFIRMED,
        ],
    ).filter(
        Q(
            analyzed_at__date__gte=month_start,
            analyzed_at__date__lt=next_month,
        )
        | Q(
            analyzed_at__isnull=True,
            created_at__date__gte=month_start,
            created_at__date__lt=next_month,
        )
    ).count()
    monthly["posture_count"] = max(
        monthly["posture_count"],
        posture_assessment_count,
    )

    plan = ClinicAiPlan.objects.filter(clinic=clinic).first()
    if plan:
        included_minutes = plan.included_minutes
        usage_percent = plan.usage_percent(monthly["recording_minutes"])
        remaining_minutes = max(
            included_minutes - monthly["recording_minutes"],
            0,
        )
        overage_fee = plan.calc_overage_fee(
            monthly["recording_minutes"]
        )
    else:
        included_minutes = 0
        usage_percent = 0
        remaining_minutes = None
        overage_fee = 0

    monthly.update({
        "included_minutes": included_minutes,
        "remaining_minutes": remaining_minutes,
        "usage_percent": usage_percent,
        "usage_percent_bar": min(usage_percent, 100),
        "overage_fee": overage_fee,
    })
    warning = _ai_usage_warning_context(
        plan,
        monthly["recording_minutes"],
    )

    daily_rows = list(
        AiUsageLog.objects
        .filter(
            clinic=clinic,
            status=AiUsageLog.Status.SUCCESS,
            created_at__date__gte=seven_days_ago,
            created_at__date__lte=today,
        )
        .annotate(day=TruncDate("created_at"))
        .values("day")
        .annotate(
            recording_minutes=Sum("billing_minutes"),
            process_count=Count("id"),
            estimated_cost_yen=Sum("estimated_cost_yen"),
        )
        .order_by("day")
    )
    daily_map = {row["day"]: row for row in daily_rows}
    daily_usage = []
    for offset in range(7):
        day = seven_days_ago + timedelta(days=offset)
        row = daily_map.get(day, {})
        daily_usage.append({
            "day": day,
            "recording_minutes": row.get("recording_minutes") or 0,
            "process_count": row.get("process_count") or 0,
            "estimated_cost_yen": row.get("estimated_cost_yen") or 0,
        })
    max_minutes = max(
        (row["recording_minutes"] for row in daily_usage),
        default=0,
    )
    max_processes = max(
        (row["process_count"] for row in daily_usage),
        default=0,
    )
    for row in daily_usage:
        row["minutes_percent"] = (
            round(row["recording_minutes"] / max_minutes * 100)
            if max_minutes else 0
        )
        row["process_percent"] = (
            round(row["process_count"] / max_processes * 100)
            if max_processes else 0
        )

    category_specs = {
        "interview_recording": "初診録音",
        "treatment_session": "通院施術録音",
        "posture": "姿勢分析",
        "clinical_summary": "カルテ要約",
        "treatment_plan": "施術計画",
        "other": "その他",
    }
    category_map = {
        key: {
            "key": key,
            "label": label,
            "count": 0,
            "recording_minutes": 0,
            "estimated_cost_yen": 0,
        }
        for key, label in category_specs.items()
    }
    for log in month_logs:
        item = category_map[_ai_usage_category(log)]
        item["count"] += 1
        item["recording_minutes"] += log.billing_minutes
        item["estimated_cost_yen"] += log.estimated_cost_yen
    category_usage = list(category_map.values())

    recent_logs = list(
        AiUsageLog.objects
        .filter(clinic=clinic)
        .select_related(
            "patient",
            "appointment",
            "recording",
        )
        .order_by("-created_at")[:30]
    )
    session_ids = {
        session_id
        for log in recent_logs
        if (
            session_id := _safe_metadata_id(
                log.metadata,
                "treatment_session_id",
                "session_id",
            )
        )
    }
    posture_ids = {
        assessment_id
        for log in recent_logs
        if (
            assessment_id := _safe_metadata_id(
                log.metadata,
                "posture_assessment_id",
                "assessment_id",
            )
        )
    }
    sessions = TreatmentSession.objects.filter(
        clinic=clinic,
        pk__in=session_ids,
    ).in_bulk()
    assessments = PostureAssessment.objects.filter(
        clinic=clinic,
        pk__in=posture_ids,
    ).in_bulk()

    recent_items = []
    for log in recent_logs:
        category_key = _ai_usage_category(log)
        related_url = ""
        related_label = ""
        if (
            log.recording_id
            and log.recording
            and log.recording.clinic_id == clinic.id
        ):
            related_url = reverse(
                "intakes:recording_detail",
                args=[log.recording_id],
            )
            related_label = "初診録音詳細"
        else:
            session_id = _safe_metadata_id(
                log.metadata,
                "treatment_session_id",
                "session_id",
            )
            assessment_id = _safe_metadata_id(
                log.metadata,
                "posture_assessment_id",
                "assessment_id",
            )
            if session_id in sessions:
                related_url = reverse(
                    "treatment_sessions:detail",
                    args=[session_id],
                )
                related_label = "通院施術録音詳細"
            elif assessment_id in assessments:
                related_url = reverse(
                    "posture_assessments:detail",
                    args=[assessment_id],
                )
                related_label = "姿勢分析詳細"
            elif log.patient_id and log.patient.clinic_id == clinic.id:
                related_url = reverse(
                    "staff:patient_detail",
                    args=[log.patient_id],
                )
                related_label = "患者詳細"

        patient_name = "患者情報なし"
        if log.patient_id and log.patient.clinic_id == clinic.id:
            patient_name = str(log.patient)
        elif log.appointment_id:
            patient_name = (
                f"予約 #{log.appointment_id}"
            )

        recent_items.append({
            "log": log,
            "category_label": category_specs[category_key],
            "patient_name": patient_name,
            "related_url": related_url,
            "related_label": related_label,
        })

    plan_context = None
    if plan:
        plan_context = {
            "name": plan.plan_name or "名称未設定",
            "monthly_base_fee": plan.monthly_base_fee,
            "included_minutes": plan.included_minutes,
            "used_minutes": monthly["recording_minutes"],
            "remaining_minutes": remaining_minutes,
            "overage_unit_minutes": plan.overage_unit_minutes,
            "overage_unit_price": plan.overage_unit_price,
            "overage_fee": overage_fee,
            "hard_limit_minutes": plan.hard_limit_minutes,
            "is_ai_enabled": plan.is_ai_enabled,
            "allow_overage": plan.allow_overage,
        }

    return {
        "today": today,
        "month_start": month_start,
        "monthly_usage": monthly,
        "usage_warning": warning,
        "daily_usage": daily_usage,
        "category_usage": category_usage,
        "plan": plan_context,
        "recent_usage_items": recent_items,
    }


@staff_required
def staff_ai_usage_dashboard_view(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のAI利用状況のみ閲覧できます。")

    return render(request, "staff/ai_usage_dashboard.html", {
        "active": "ai_usage",
        "page_title": "AI利用量・コスト管理",
        **build_ai_usage_dashboard_context(clinic),
    })


@staff_required
def staff_manual_view(request):
    return render(request, "staff/manual.html", {
        "active": "manual",
        "page_title": "操作マニュアル",
    })


@staff_required
def staff_settings_view(request):
    return redirect("staff:clinic_settings")


@staff_required
def staff_clinic_settings_view(request):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の設定のみ編集できます。")

    clinic_settings, _ = ClinicSettings.objects.get_or_create(
        clinic=clinic,
    )
    if request.method == "POST":
        form = ClinicSettingsForm(
            request.POST,
            instance=clinic_settings,
            clinic=clinic,
        )
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "院設定を保存しました。")
            return redirect("staff:clinic_settings")
    else:
        form = ClinicSettingsForm(
            instance=clinic_settings,
            clinic=clinic,
        )

    return render(request, "staff/clinic_settings.html", {
        "active": "settings",
        "page_title": "院設定",
        "clinic": clinic,
        "clinic_settings": clinic_settings,
        "form": form,
    })


def _format_yen(value):
    try:
        return f"¥{int(value):,}"
    except (TypeError, ValueError):
        return "¥0"


def _require_staff_clinic(request, message):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return None, HttpResponseForbidden(message)
    return clinic, None


@staff_required
def staff_treatment_menu_list_view(request):
    clinic, forbidden_response = _require_staff_clinic(
        request,
        "所属院の施術メニューのみ閲覧できます。",
    )
    if forbidden_response:
        return forbidden_response

    menus = list(
        TreatmentMenu.objects
        .filter(clinic=clinic)
        .order_by("display_order", "name", "id")
    )
    for menu in menus:
        menu.price_display = _format_yen(menu.price)

    return render(request, "staff/treatment_menu_list.html", {
        "active": "treatment_menus",
        "page_title": "施術メニュー・料金設定",
        "clinic": clinic,
        "menus": menus,
        "active_menu_count": sum(1 for menu in menus if menu.is_active),
    })


@staff_required
def staff_treatment_menu_create_view(request):
    clinic, forbidden_response = _require_staff_clinic(
        request,
        "所属院の施術メニューのみ作成できます。",
    )
    if forbidden_response:
        return forbidden_response

    if request.method == "POST":
        form = TreatmentMenuForm(request.POST, clinic=clinic)
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "施術メニューを登録しました。")
            return redirect("staff:treatment_menu_list")
    else:
        form = TreatmentMenuForm(clinic=clinic)

    return render(request, "staff/treatment_menu_form.html", {
        "active": "treatment_menus",
        "page_title": "施術メニューを追加",
        "clinic": clinic,
        "form": form,
        "is_edit": False,
        "menu": None,
    })


@staff_required
def staff_treatment_menu_update_view(request, menu_id):
    clinic, forbidden_response = _require_staff_clinic(
        request,
        "所属院の施術メニューのみ編集できます。",
    )
    if forbidden_response:
        return forbidden_response

    menu = get_object_or_404(TreatmentMenu, pk=menu_id, clinic=clinic)
    if request.method == "POST":
        form = TreatmentMenuForm(request.POST, instance=menu, clinic=clinic)
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "施術メニューを保存しました。")
            return redirect("staff:treatment_menu_list")
    else:
        form = TreatmentMenuForm(instance=menu, clinic=clinic)

    return render(request, "staff/treatment_menu_form.html", {
        "active": "treatment_menus",
        "page_title": "施術メニューを編集",
        "clinic": clinic,
        "form": form,
        "is_edit": True,
        "menu": menu,
    })


@staff_required
@require_POST
def staff_treatment_menu_toggle_view(request, menu_id):
    clinic, forbidden_response = _require_staff_clinic(
        request,
        "所属院の施術メニューのみ変更できます。",
    )
    if forbidden_response:
        return forbidden_response

    menu = get_object_or_404(TreatmentMenu, pk=menu_id, clinic=clinic)
    menu.is_active = not menu.is_active
    menu.save(update_fields=["is_active", "updated_at"])
    if menu.is_active:
        messages.success(request, "施術メニューを再有効化しました。")
    else:
        messages.success(request, "施術メニューを無効化しました。")
    return redirect("staff:treatment_menu_list")


def _own_object_or_none(model, clinic, pk, **extra_filters):
    if not pk:
        return None
    try:
        pk = int(pk)
    except (TypeError, ValueError):
        return None
    filters = {"pk": pk, **extra_filters}
    return model.objects.filter(**filters).first()


def _build_sales_record_initial(request, clinic):
    initial = {
        "treatment_date": timezone.localdate(),
        "staff": request.user if request.user.clinic_id == clinic.id else None,
    }

    patient = _own_object_or_none(
        Patient,
        clinic,
        request.GET.get("patient") or request.GET.get("patient_id"),
        clinic=clinic,
    )
    if patient:
        initial["patient"] = patient

    appointment = _own_object_or_none(
        Appointment,
        clinic,
        request.GET.get("appointment") or request.GET.get("appointment_id"),
        clinic=clinic,
    )
    if appointment:
        initial["appointment"] = appointment
        if appointment.patient_id:
            initial["patient"] = appointment.patient
        initial["treatment_date"] = timezone.localtime(
            appointment.start_at
        ).date()

    clinical_note = _own_object_or_none(
        ClinicalNote,
        clinic,
        request.GET.get("clinical_note") or request.GET.get("note_id"),
        patient__clinic=clinic,
    )
    if clinical_note:
        initial["clinical_note"] = clinical_note
        initial["patient"] = clinical_note.patient
        initial["appointment"] = clinical_note.appointment
        initial["treatment_date"] = timezone.localtime(
            clinical_note.appointment.start_at
        ).date()

    treatment_menu = _own_object_or_none(
        TreatmentMenu,
        clinic,
        request.GET.get("treatment_menu") or request.GET.get("menu_id"),
        clinic=clinic,
    )
    if treatment_menu:
        initial["treatment_menu"] = treatment_menu
        initial["amount"] = treatment_menu.price

    return initial


def _sales_form_context(clinic, form, *, is_edit=False, record=None):
    menu_prices = {
        str(menu.id): menu.price
        for menu in form.fields["treatment_menu"].queryset
    }
    return {
        "active": "sales",
        "page_title": "売上実績を編集" if is_edit else "売上実績を登録",
        "clinic": clinic,
        "form": form,
        "is_edit": is_edit,
        "record": record,
        "menu_prices": menu_prices,
    }


@staff_required
def staff_sales_record_list_view(request):
    clinic, forbidden_response = _require_staff_clinic(
        request,
        "所属院の売上実績のみ閲覧できます。",
    )
    if forbidden_response:
        return forbidden_response

    qs = (
        SalesRecord.objects
        .filter(clinic=clinic)
        .select_related(
            "patient",
            "appointment",
            "clinical_note",
            "treatment_menu",
            "staff",
        )
        .order_by("-treatment_date", "-created_at", "-id")
    )

    date_from = parse_date(request.GET.get("date_from") or "")
    date_to = parse_date(request.GET.get("date_to") or "")
    q = (request.GET.get("q") or "").strip()
    payment_method = request.GET.get("payment_method") or ""
    status = request.GET.get("status") or ""
    menu_id = request.GET.get("treatment_menu") or ""

    if date_from:
        qs = qs.filter(treatment_date__gte=date_from)
    if date_to:
        qs = qs.filter(treatment_date__lte=date_to)
    if q:
        qs = qs.filter(
            Q(patient__last_name__icontains=q)
            | Q(patient__first_name__icontains=q)
            | Q(patient__last_name_kana__icontains=q)
            | Q(patient__first_name_kana__icontains=q)
            | Q(patient__phone__icontains=q)
            | Q(patient__card_no__icontains=q)
            | Q(memo__icontains=q)
        )
    if payment_method:
        qs = qs.filter(payment_method=payment_method)
    if status:
        qs = qs.filter(status=status)
    if menu_id:
        qs = qs.filter(treatment_menu_id=menu_id)

    total_amount = qs.exclude(
        status=SalesRecord.Status.CANCELED,
    ).aggregate(total=Sum("amount"))["total"] or 0

    paginator = Paginator(qs, 20)
    page_obj = paginator.get_page(request.GET.get("page"))
    for record in page_obj.object_list:
        record.amount_display = _format_yen(record.amount)

    return render(request, "staff/sales_record_list.html", {
        "active": "sales",
        "page_title": "売上管理",
        "clinic": clinic,
        "page_obj": page_obj,
        "records": page_obj.object_list,
        "total_amount_display": _format_yen(total_amount),
        "payment_method_choices": SalesRecord.PaymentMethod.choices,
        "status_choices": SalesRecord.Status.choices,
        "treatment_menus": TreatmentMenu.objects.filter(
            clinic=clinic,
        ).order_by("display_order", "name", "id"),
        "filters": {
            "date_from": request.GET.get("date_from", ""),
            "date_to": request.GET.get("date_to", ""),
            "q": q,
            "payment_method": payment_method,
            "status": status,
            "treatment_menu": menu_id,
        },
    })


@staff_required
def staff_sales_record_create_view(request):
    clinic, forbidden_response = _require_staff_clinic(
        request,
        "所属院の売上実績のみ登録できます。",
    )
    if forbidden_response:
        return forbidden_response

    if request.method == "POST":
        form = SalesRecordForm(request.POST, clinic=clinic)
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "売上実績を登録しました。")
            return redirect("staff:sales_record_list")
    else:
        form = SalesRecordForm(
            clinic=clinic,
            initial=_build_sales_record_initial(request, clinic),
        )

    return render(
        request,
        "staff/sales_record_form.html",
        _sales_form_context(clinic, form),
    )


@staff_required
def staff_sales_record_update_view(request, record_id):
    clinic, forbidden_response = _require_staff_clinic(
        request,
        "所属院の売上実績のみ編集できます。",
    )
    if forbidden_response:
        return forbidden_response

    record = get_object_or_404(
        SalesRecord.objects.select_related(
            "patient",
            "appointment",
            "clinical_note",
            "treatment_menu",
            "staff",
        ),
        pk=record_id,
        clinic=clinic,
    )
    if request.method == "POST":
        form = SalesRecordForm(request.POST, instance=record, clinic=clinic)
        if form.is_valid():
            with transaction.atomic():
                form.save()
            messages.success(request, "売上実績を保存しました。")
            return redirect("staff:sales_record_list")
    else:
        form = SalesRecordForm(instance=record, clinic=clinic)

    return render(
        request,
        "staff/sales_record_form.html",
        _sales_form_context(clinic, form, is_edit=True, record=record),
    )


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
        local_start = timezone.localtime(a.start_at)
        local_end = (
            timezone.localtime(a.end_at)
            if getattr(a, "end_at", None)
            else local_start + timedelta(minutes=30)
        )

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
                "patientId": a.patient_id or "",
                "patientName": patient_name,
                "menu": a.menu or "-",
                "menuValue": a.menu or "",
                "assignedStaffId": a.assigned_staff_id or "",
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
                "notes": a.notes or "",
                "startDate": local_start.date().isoformat(),
                "startTime": local_start.strftime("%H:%M"),
                "endTime": local_end.strftime("%H:%M"),
                "intakeDetailUrl": reverse("staff:intake_detail", args=[a.intake.id]) if intake else "",
                "initialRecordingUrl": (
                    reverse("intakes:recording_new", args=[a.id])
                    if a.patient_id
                    else ""
                ),
                "treatmentRecordingUrl": (
                    reverse("treatment_sessions:start", args=[a.id])
                    if a.patient_id
                    else ""
                ),
                "dayUrl": f"{reverse('staff:appointments')}?period=day&day={local_start.date().isoformat()}",
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


def _build_day_timeline_rows(
    appointments,
    staff_users,
    base_day,
    clinic_settings=None,
):
    """
    日表示用：横型スケジュール表データを作成する。
    横軸は 9:00〜19:00、縦軸は施術者。
    """
    start_hour = (
        clinic_settings.business_start_time.hour
        if clinic_settings
        else 8
    )
    end_hour = (
        clinic_settings.business_end_time.hour
        + (1 if clinic_settings.business_end_time.minute else 0)
        if clinic_settings
        else 20
    )
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
            "patient_id": a.patient_id or "",
            "patient_name": patient_name,
            "start_time": start_dt.strftime("%H:%M"),
            "end_time": end_dt.strftime("%H:%M"),
            "menu": a.menu or "-",
            "menu_value": a.menu or "",
            "assigned_staff_id": a.assigned_staff_id or "",
            "status": a.status,
            "status_label": a.get_status_display(),
            "intake_state": intake_state,
            "chief_label": summary["chief_label"] or "主訴未入力",
            "pain_level_display": summary["pain_level_display"] or "-",
            "visit_type_label": summary["visit_type_label"] or "-",
            "areas_display": "、".join(summary["areas_display"]) if summary["areas_display"] else "-",
            "notes": a.notes or "",
            "appointment_date": start_dt.date().isoformat(),
            "left_percent": round(left_percent, 3),
            "width_percent": round(width_percent, 3),
            "intake_detail_url": reverse("staff:intake_detail", args=[a.intake.id]) if intake else "",
            "initial_recording_url": (
                reverse("intakes:recording_new", args=[a.id])
                if a.patient_id
                else ""
            ),
            "treatment_recording_url": (
                reverse("treatment_sessions:start", args=[a.id])
                if a.patient_id
                else ""
            ),
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


def _timeline_local_datetime(target_date, target_time):
    value = datetime.combine(target_date, target_time)
    return timezone.make_aware(value) if timezone.is_naive(value) else value


def _timeline_patient_name(appointment):
    if not appointment.patient:
        return "（患者未確定）"
    return f"{appointment.patient.last_name} {appointment.patient.first_name}"


def _timeline_appointment_data(appointment):
    local_start = timezone.localtime(appointment.start_at)
    local_end = timezone.localtime(appointment.end_at)
    return {
        "id": appointment.id,
        "patient_id": appointment.patient_id or "",
        "patient_name": _timeline_patient_name(appointment),
        "appointment_date": local_start.date().isoformat(),
        "start_time": local_start.strftime("%H:%M"),
        "end_time": local_end.strftime("%H:%M"),
        "assigned_staff_id": appointment.assigned_staff_id or "",
        "menu": appointment.menu or "-",
        "menu_value": appointment.menu or "",
        "status": appointment.status,
        "status_label": appointment.get_status_display(),
        "notes": appointment.notes or "",
    }


def build_staff_appointment_timeline(clinic, target_date, clinic_settings=None):
    """担当者別の日次タイムラインを、対象日分の一括取得データから生成する。"""
    clinic_settings = clinic_settings or ClinicSettings.objects.filter(
        clinic=clinic,
    ).first()
    business_start = (
        clinic_settings.business_start_time
        if clinic_settings and clinic_settings.business_start_time
        else time(9, 0)
    )
    business_end = (
        clinic_settings.business_end_time
        if clinic_settings and clinic_settings.business_end_time
        else time(18, 0)
    )
    slot_minutes = (
        clinic_settings.appointment_interval_minutes
        if clinic_settings and clinic_settings.appointment_interval_minutes
        else 30
    )
    slot_minutes = max(int(slot_minutes or 30), 5)
    is_closed = bool(
        clinic_settings
        and _closed_weekday_key(target_date)
        in (clinic_settings.closed_weekdays or [])
    )

    day_start = _timeline_local_datetime(target_date, business_start)
    day_end = _timeline_local_datetime(target_date, business_end)
    slot_ranges = []
    cursor = day_start
    while cursor < day_end:
        slot_end = min(cursor + timedelta(minutes=slot_minutes), day_end)
        slot_ranges.append((cursor, slot_end))
        cursor += timedelta(minutes=slot_minutes)

    staff_users = list(
        User.objects.filter(
            clinic=clinic,
            is_active=True,
            role__in=_shift_staff_roles(),
        ).order_by("last_name", "first_name", "username")
    )
    staff_ids = [staff.id for staff in staff_users]
    shifts = {
        shift.staff_id: shift
        for shift in StaffShift.objects.filter(
            clinic=clinic,
            staff_id__in=staff_ids,
            date=target_date,
        ).select_related("staff")
    }
    leaves_by_staff = {staff_id: [] for staff_id in staff_ids}
    for leave in StaffLeave.objects.filter(
        clinic=clinic,
        staff_id__in=staff_ids,
        status=StaffLeave.Status.APPROVED,
        start_date__lte=target_date,
        end_date__gte=target_date,
    ).select_related("staff").order_by("start_time", "leave_type", "id"):
        leaves_by_staff.setdefault(leave.staff_id, []).append(leave)

    appointments_by_staff = {staff_id: [] for staff_id in staff_ids}
    blocking_statuses = [
        Appointment.Status.PENDING,
        Appointment.Status.BOOKED,
        Appointment.Status.ARRIVED,
        Appointment.Status.COMPLETED,
    ]
    appointments = list(
        Appointment.objects.filter(
            clinic=clinic,
            assigned_staff_id__in=staff_ids,
            start_at__lt=day_end,
            end_at__gt=day_start,
            status__in=blocking_statuses,
        )
        .select_related("patient", "assigned_staff")
        .order_by("start_at", "id")
    )
    for appointment in appointments:
        appointments_by_staff.setdefault(
            appointment.assigned_staff_id,
            [],
        ).append(appointment)

    rows = []
    for staff in staff_users:
        shift = shifts.get(staff.id)
        leaves = leaves_by_staff.get(staff.id, [])
        staff_appointments = appointments_by_staff.get(staff.id, [])
        rendered_appointments = set()
        cells = []

        for slot_start, slot_end in slot_ranges:
            start_time = timezone.localtime(slot_start).time()
            end_time = timezone.localtime(slot_end).time()
            cell = {
                "state": "available",
                "state_label": "空き",
                "date": target_date.isoformat(),
                "start_time": slot_start.strftime("%H:%M"),
                "end_time": slot_end.strftime("%H:%M"),
                "staff_id": staff.id,
                "appointment": None,
                "is_appointment_start": False,
            }

            overlapping = next(
                (
                    appointment
                    for appointment in staff_appointments
                    if appointment.start_at < slot_end
                    and appointment.end_at > slot_start
                ),
                None,
            )
            if overlapping:
                cell["state"] = "booked"
                cell["state_label"] = "予約あり"
                cell["appointment"] = _timeline_appointment_data(overlapping)
                cell["is_appointment_start"] = overlapping.id not in rendered_appointments
                rendered_appointments.add(overlapping.id)
                cells.append(cell)
                continue

            if is_closed:
                cell["state"] = "off"
                cell["state_label"] = "休診日"
                cells.append(cell)
                continue

            if shift is None or shift.status == StaffShift.Status.OFF:
                cell["state"] = "off"
                cell["state_label"] = "休み" if shift else "シフトなし"
                cells.append(cell)
                continue

            if (
                not shift.start_time
                or not shift.end_time
                or start_time < shift.start_time
                or end_time > shift.end_time
            ):
                cell["state"] = "outside_shift"
                cell["state_label"] = "勤務時間外"
                cells.append(cell)
                continue

            overlapping_leave = next(
                (
                    leave
                    for leave in leaves
                    if _staff_leave_overlaps_appointment(
                        leave,
                        start_time,
                        end_time,
                        clinic_settings,
                    )
                ),
                None,
            )
            if overlapping_leave:
                cell["state"] = "leave"
                cell["state_label"] = overlapping_leave.get_leave_type_display()
                cells.append(cell)
                continue

            staff_break_overlap = (
                shift.break_start
                and shift.break_end
                and _time_ranges_overlap(
                    start_time,
                    end_time,
                    shift.break_start,
                    shift.break_end,
                )
            )
            clinic_break_overlap = (
                clinic_settings
                and clinic_settings.break_start_time
                and clinic_settings.break_end_time
                and _time_ranges_overlap(
                    start_time,
                    end_time,
                    clinic_settings.break_start_time,
                    clinic_settings.break_end_time,
                )
            )
            if staff_break_overlap or clinic_break_overlap:
                cell["state"] = "break"
                cell["state_label"] = "休憩"
            elif shift.status == StaffShift.Status.OTHER:
                cell["state"] = "warning"
                cell["state_label"] = "要確認"

            cells.append(cell)

        staff_name = staff.get_full_name().strip() or staff.username
        rows.append({
            "staff_id": staff.id,
            "staff_name": staff_name,
            "shift_label": shift.get_status_display() if shift else "シフト未設定",
            "shift_time_label": _format_shift_time(shift) if shift else "-",
            "cells": cells,
        })

    return {
        "date": target_date,
        "slot_minutes": slot_minutes,
        "slot_count": len(slot_ranges),
        "slots": [
            {
                "start_time": slot_start.strftime("%H:%M"),
                "end_time": slot_end.strftime("%H:%M"),
            }
            for slot_start, slot_end in slot_ranges
        ],
        "rows": rows,
        "business_time_label": (
            f"{business_start.strftime('%H:%M')}〜{business_end.strftime('%H:%M')}"
        ),
        "is_closed": is_closed,
    }


def _appointment_json_error(errors, status=400, warnings=None):
    if isinstance(errors, str):
        errors = [errors]
    errors = [str(error) for error in (errors or []) if str(error).strip()]
    warnings = [
        str(warning)
        for warning in (warnings or [])
        if str(warning).strip()
    ]
    message = errors[0] if errors else (warnings[0] if warnings else "予約の保存に失敗しました。")
    return JsonResponse({
        "ok": False,
        "error": message,
        "errors": errors,
        "warnings": warnings,
    }, status=status)


def _appointment_request_payload(request):
    if request.content_type and "application/json" in request.content_type:
        try:
            return json.loads(request.body.decode("utf-8") or "{}")
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None
    return request.POST.dict()


def _appointment_validation_messages(exc):
    if hasattr(exc, "message_dict"):
        messages_to_show = []
        for field, messages_for_field in exc.message_dict.items():
            for message in messages_for_field:
                messages_to_show.append(f"{field}: {message}")
        return messages_to_show
    return [str(message) for message in getattr(exc, "messages", [str(exc)])]


def _combine_appointment_local_datetime(target_date, target_time):
    if not target_date or not target_time:
        return None
    value = datetime.combine(target_date, target_time)
    if timezone.is_naive(value):
        value = timezone.make_aware(value)
    return value


def _appointment_default_end_at(clinic, start_at):
    clinic_settings = ClinicSettings.objects.filter(clinic=clinic).first()
    minutes = (
        clinic_settings.appointment_interval_minutes
        if clinic_settings
        else 30
    )
    return start_at + timedelta(minutes=minutes or 30)


def _parse_optional_positive_int(value, label):
    if value in [None, ""]:
        return None, []
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None, [f"{label}が不正です。"]
    if number <= 0:
        return None, [f"{label}が不正です。"]
    return number, []


def _appointment_slot_duration_minutes(clinic_settings, treatment_menu=None, duration_minutes=None):
    if duration_minutes:
        return duration_minutes
    if treatment_menu and treatment_menu.duration_minutes:
        return treatment_menu.duration_minutes
    if clinic_settings and clinic_settings.appointment_interval_minutes:
        return clinic_settings.appointment_interval_minutes
    return 30


def _appointment_slot_interval_minutes(clinic_settings):
    if clinic_settings and clinic_settings.appointment_interval_minutes:
        return clinic_settings.appointment_interval_minutes
    return 30


def _appointment_slot_staff_queryset(clinic):
    return (
        User.objects
        .filter(
            clinic=clinic,
            is_active=True,
            role__in=_shift_staff_roles(),
        )
        .order_by("last_name", "first_name", "username", "id")
    )


def _appointment_staff_display_name(staff_user):
    full_name = staff_user.get_full_name().strip()
    return full_name or staff_user.username


def build_appointment_available_slots(
    *,
    clinic,
    target_date,
    staff_id=None,
    treatment_menu_id=None,
    duration_minutes=None,
    exclude_appointment_id=None,
    limit=50,
):
    clinic_settings = ClinicSettings.objects.filter(clinic=clinic).first()
    errors = []

    if target_date is None:
        return {
            "ok": False,
            "status": 400,
            "date": "",
            "slots": [],
            "errors": ["日付を選択してください。"],
            "message": "",
        }

    duration_minutes, duration_errors = _parse_optional_positive_int(
        duration_minutes,
        "予約時間",
    )
    errors.extend(duration_errors)

    parsed_staff_id, staff_errors = _parse_optional_positive_int(
        staff_id,
        "担当者",
    )
    errors.extend(staff_errors)

    parsed_menu_id, menu_errors = _parse_optional_positive_int(
        treatment_menu_id,
        "施術メニュー",
    )
    errors.extend(menu_errors)

    parsed_exclude_id, exclude_errors = _parse_optional_positive_int(
        exclude_appointment_id,
        "除外予約",
    )
    errors.extend(exclude_errors)

    if errors:
        return {
            "ok": False,
            "status": 400,
            "date": target_date.isoformat(),
            "slots": [],
            "errors": errors,
            "message": "",
        }

    treatment_menu = None
    if parsed_menu_id:
        treatment_menu = get_object_or_404(
            TreatmentMenu,
            pk=parsed_menu_id,
            clinic=clinic,
            is_active=True,
        )

    if parsed_exclude_id:
        get_object_or_404(
            Appointment,
            pk=parsed_exclude_id,
            clinic=clinic,
        )

    if clinic_settings and _closed_weekday_key(target_date) in (clinic_settings.closed_weekdays or []):
        return {
            "ok": False,
            "status": 400,
            "date": target_date.isoformat(),
            "slots": [],
            "errors": ["休診曜日です。"],
            "message": "休診日のため候補を表示できません。",
        }

    business_start = (
        clinic_settings.business_start_time
        if clinic_settings and clinic_settings.business_start_time
        else time(9, 0)
    )
    business_end = (
        clinic_settings.business_end_time
        if clinic_settings and clinic_settings.business_end_time
        else time(18, 0)
    )
    slot_interval = _appointment_slot_interval_minutes(clinic_settings)
    duration = _appointment_slot_duration_minutes(
        clinic_settings,
        treatment_menu=treatment_menu,
        duration_minutes=duration_minutes,
    )

    if business_start >= business_end:
        return {
            "ok": False,
            "status": 400,
            "date": target_date.isoformat(),
            "slots": [],
            "errors": ["営業時間設定を確認してください。"],
            "message": "",
        }

    if parsed_staff_id:
        staff_users = [
            get_object_or_404(
                _appointment_slot_staff_queryset(clinic),
                pk=parsed_staff_id,
            )
        ]
    else:
        working_staff_ids = StaffShift.objects.filter(
            clinic=clinic,
            date=target_date,
            status__in=[
                StaffShift.Status.WORKING,
                StaffShift.Status.HALF_DAY,
                StaffShift.Status.TRAINING,
            ],
        ).values_list("staff_id", flat=True)
        staff_users = list(
            _appointment_slot_staff_queryset(clinic).filter(
                id__in=working_staff_ids,
            )
        )

    slots = []
    current_at = _combine_appointment_local_datetime(target_date, business_start)
    close_at = _combine_appointment_local_datetime(target_date, business_end)
    step = timedelta(minutes=slot_interval)
    duration_delta = timedelta(minutes=duration)

    while current_at and close_at and current_at + duration_delta <= close_at:
        end_at = current_at + duration_delta
        for staff_user in staff_users:
            availability = check_appointment_availability(
                clinic=clinic,
                start_at=current_at,
                end_at=end_at,
                assigned_staff=staff_user,
                exclude_appointment_id=parsed_exclude_id,
            )
            if availability["is_valid"] and not availability["warnings"]:
                start_label = timezone.localtime(current_at).strftime("%H:%M")
                end_label = timezone.localtime(end_at).strftime("%H:%M")
                staff_name = _appointment_staff_display_name(staff_user)
                slots.append({
                    "start_time": start_label,
                    "end_time": end_label,
                    "staff_id": staff_user.id,
                    "staff_name": staff_name,
                    "label": f"{start_label}〜{end_label} {staff_name}",
                })
                if len(slots) >= limit:
                    break
        if len(slots) >= limit:
            break
        current_at = current_at + step

    message = ""
    if not staff_users:
        message = "勤務可能な担当者がいません。"
    elif not slots:
        message = "この条件で空き枠はありません。"

    return {
        "ok": True,
        "status": 200,
        "date": target_date.isoformat(),
        "slots": slots,
        "errors": [],
        "message": message,
    }


def _parse_appointment_api_data(request, clinic, appointment=None):
    payload = _appointment_request_payload(request)
    if payload is None:
        return None, ["不正なリクエストです。"]

    errors = []

    patient_id = payload.get("patient_id") or payload.get("patient")
    patient = None
    if not patient_id:
        errors.append("患者を選択してください。")
    else:
        patient = Patient.objects.filter(pk=patient_id, clinic=clinic).first()
        if patient is None:
            errors.append("患者情報が不正です。")

    assigned_staff_id = payload.get("assigned_staff_id") or payload.get("assigned_staff")
    assigned_staff = None
    if not assigned_staff_id:
        errors.append("担当者を選択してください。")
    else:
        assigned_staff = (
            User.objects
            .filter(
                pk=assigned_staff_id,
                clinic=clinic,
                is_active=True,
                role__in=_shift_staff_roles(),
            )
            .first()
        )
        if assigned_staff is None:
            errors.append("担当者情報が不正です。")

    date_value = parse_date(str(payload.get("appointment_date") or payload.get("date") or ""))
    start_time = parse_time(str(payload.get("start_time") or ""))
    end_time = parse_time(str(payload.get("end_time") or ""))

    if date_value is None:
        errors.append("予約日を入力してください。")
    if start_time is None:
        errors.append("開始時刻を入力してください。")

    start_at = _combine_appointment_local_datetime(date_value, start_time)
    end_at = _combine_appointment_local_datetime(date_value, end_time)
    if start_at and end_at is None:
        end_at = _appointment_default_end_at(clinic, start_at)

    status = (payload.get("status") or "").strip()
    valid_statuses = {choice[0] for choice in Appointment.Status.choices}
    if not status:
        status = appointment.status if appointment else Appointment.Status.BOOKED
    elif status not in valid_statuses:
        errors.append("予約ステータスが不正です。")

    menu = (payload.get("menu") or "").strip() or "初診"
    notes = (payload.get("notes") or payload.get("memo") or "").strip()

    if errors:
        return None, errors

    return {
        "patient": patient,
        "assigned_staff": assigned_staff,
        "start_at": start_at,
        "end_at": end_at,
        "status": status,
        "menu": menu,
        "notes": notes,
    }, []


def _require_appointment_api_clinic(request):
    clinic = getattr(request.user, "clinic", None)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
        or not _is_staff_user(request.user, clinic)
    ):
        return None
    return clinic


@staff_required
def staff_appointment_available_slots_api(request):
    clinic = _require_appointment_api_clinic(request)
    if clinic is None:
        return _appointment_json_error("権限がありません。", status=403)

    target_date = parse_date(str(request.GET.get("date") or ""))
    result = build_appointment_available_slots(
        clinic=clinic,
        target_date=target_date,
        staff_id=request.GET.get("staff_id"),
        treatment_menu_id=request.GET.get("treatment_menu_id"),
        duration_minutes=request.GET.get("duration_minutes"),
        exclude_appointment_id=request.GET.get("exclude_appointment_id"),
    )

    if not result["ok"]:
        return JsonResponse({
            "ok": False,
            "date": result["date"],
            "slots": [],
            "errors": result["errors"],
            "message": result["message"],
        }, status=result["status"])

    return JsonResponse({
        "ok": True,
        "date": result["date"],
        "slots": result["slots"],
        "message": result["message"],
    })


@staff_required
@require_POST
def staff_appointment_create_api(request):
    clinic = _require_appointment_api_clinic(request)
    if clinic is None:
        return _appointment_json_error("権限がありません。", status=403)

    parsed, errors = _parse_appointment_api_data(request, clinic)
    if errors:
        return _appointment_json_error(errors)

    availability = check_appointment_availability(
        clinic=clinic,
        start_at=parsed["start_at"],
        end_at=parsed["end_at"],
        assigned_staff=parsed["assigned_staff"],
    )
    if not availability["is_valid"] or availability["warnings"]:
        return _appointment_json_error(
            availability["errors"] or availability["warnings"],
            warnings=availability["warnings"],
        )

    appointment = Appointment(
        clinic=clinic,
        patient=parsed["patient"],
        start_at=parsed["start_at"],
        end_at=parsed["end_at"],
        menu=parsed["menu"],
        status=parsed["status"],
        assigned_staff=parsed["assigned_staff"],
        created_by=request.user,
        notes=parsed["notes"],
    )
    try:
        with transaction.atomic():
            appointment.save()
    except ValidationError as exc:
        return _appointment_json_error(_appointment_validation_messages(exc))

    return JsonResponse({
        "ok": True,
        "appointment_id": appointment.id,
        "message": "予約を登録しました。",
    })


@staff_required
@require_POST
def staff_appointment_update_api(request, pk):
    clinic = _require_appointment_api_clinic(request)
    if clinic is None:
        return _appointment_json_error("権限がありません。", status=403)

    with transaction.atomic():
        appointment = get_object_or_404(
            Appointment.objects.select_for_update(of=("self",)),
            pk=pk,
            clinic=clinic,
        )
        parsed, errors = _parse_appointment_api_data(
            request,
            clinic,
            appointment=appointment,
        )
        if errors:
            return _appointment_json_error(errors)

        availability = check_appointment_availability(
            clinic=clinic,
            start_at=parsed["start_at"],
            end_at=parsed["end_at"],
            assigned_staff=parsed["assigned_staff"],
            exclude_appointment_id=appointment.pk,
        )
        if not availability["is_valid"] or availability["warnings"]:
            return _appointment_json_error(
                availability["errors"] or availability["warnings"],
                warnings=availability["warnings"],
            )

        appointment.patient = parsed["patient"]
        appointment.start_at = parsed["start_at"]
        appointment.end_at = parsed["end_at"]
        appointment.menu = parsed["menu"]
        appointment.status = parsed["status"]
        appointment.assigned_staff = parsed["assigned_staff"]
        appointment.notes = parsed["notes"]
        try:
            appointment.save()
        except ValidationError as exc:
            return _appointment_json_error(_appointment_validation_messages(exc))

    return JsonResponse({
        "ok": True,
        "appointment_id": appointment.id,
        "message": "予約を更新しました。",
    })


@staff_required
@require_POST
def staff_appointment_status_update_view(request, pk):
    clinic = getattr(request.user, "clinic", None)
    if clinic is None or request.user.clinic_id != clinic.id:
        return HttpResponseForbidden("所属院の予約のみ操作できます。")

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
    # TODO: スタッフ側の予約作成/編集APIを追加する場合も、
    # check_appointment_availability() で同じ可否判定を通す。
    clinic = getattr(request.user, "clinic", None)

    if (
        clinic is None
        or request.user.clinic_id != clinic.id
        or not _is_staff_user(request.user, clinic)
    ):
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

    availability = check_appointment_availability(
        clinic=clinic,
        start_at=start_dt,
        end_at=end_dt,
        assigned_staff=appt.assigned_staff,
        exclude_appointment_id=appt.pk,
    )
    if not availability["is_valid"] or availability["warnings"]:
        messages_to_show = availability["errors"] or availability["warnings"]
        return JsonResponse({
            "ok": False,
            "error": messages_to_show[0],
            "errors": availability["errors"],
            "warnings": availability["warnings"],
        }, status=400)

    appt.start_at = _normalize_appointment_datetime(start_dt)
    appt.end_at = _normalize_appointment_datetime(end_dt)
    appt.save(update_fields=["start_at", "end_at", "updated_at"])

    return JsonResponse({
        "ok": True,
        "start": appt.start_at.isoformat(),
        "end": appt.end_at.isoformat() if appt.end_at else None,
    })


@staff_required
def staff_intake_list_view(request):
    clinic = getattr(request.user, "clinic", None)
    if clinic is None or request.user.clinic_id != clinic.id:
        return HttpResponseForbidden("所属院の問診のみ閲覧できます。")

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
    clinic = getattr(request.user, "clinic", None)
    if clinic is None or request.user.clinic_id != clinic.id:
        return HttpResponseForbidden("所属院の問診のみ閲覧できます。")

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
    clinic = getattr(request.user, "clinic", None)
    if clinic is None or request.user.clinic_id != clinic.id:
        return HttpResponseForbidden("所属院の予約のみ操作できます。")

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
            messages.success(request, "SOAPカルテ案を作成しました。施術者が確認して登録してください。")
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
    clinic = getattr(request.user, "clinic", None)

    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
        or not _is_staff_user(request.user, clinic)
    ):
        return HttpResponseForbidden("所属院の録音のみカルテ登録できます。")

    recording = get_object_or_404(
        InterviewRecording.objects
        .select_related("appointment", "patient", "intake")
        .select_for_update(of=("self",))
        .filter(
            clinic=clinic,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .filter(Q(intake__isnull=True) | Q(intake__clinic=clinic)),
        pk=recording_id,
    )

    if recording.status in {
        InterviewRecording.Status.TRANSCRIBING,
        InterviewRecording.Status.SUMMARIZING,
    }:
        messages.info(
            request,
            "処理中のため、カルテ登録は完了後に行ってください。",
        )
        return redirect(
            "intakes:recording_detail",
            recording_id=recording.id,
        )

    if not recording.confirmed_summary_json:
        messages.warning(
            request,
            "カルテへ登録するには、先にカルテ案を確認してください。",
        )
        return redirect(
            "intakes:recording_detail",
            recording_id=recording.id,
        )

    appointment = recording.appointment
    patient = recording.patient
    intake = recording.intake

    summary = recording.confirmed_summary_json or {}
    soap = summary.get("soap", {}) or {}
    extract = summary.get("extract", {}) or {}
    followups = summary.get("followups", []) or []

    web_snapshot = {}
    if intake:
        web_snapshot = {
            "payload": intake.payload or {},
            "chief_complaint": intake.chief_complaint,
            "symptom_type": intake.symptom_type,
            "onset": intake.onset,
            "submitted_at": intake.submitted_at.isoformat() if intake.submitted_at else None,
        }

    existing_note = (
        ClinicalNote.objects
        .select_for_update(of=("self",))
        .filter(
            appointment=appointment,
            patient=patient,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .first()
    )

    note_content_changed = bool(
        existing_note
        and (
            (existing_note.soap_json or {}) != soap
            or (existing_note.extract_json or {}) != extract
            or (existing_note.followups_json or []) != followups
            or (existing_note.web_intake_snapshot or {}) != web_snapshot
        )
    )
    source_changed = bool(
        existing_note
        and (
            existing_note.recording_id != recording.id
            or existing_note.treatment_session_id is not None
            or existing_note.intake_id != getattr(intake, "id", None)
        )
    )

    if existing_note and not note_content_changed and not source_changed:
        messages.info(request, "この確認内容はすでにカルテへ登録済みです。")
        return redirect("staff:clinical_note_detail", pk=existing_note.id)

    if existing_note and (note_content_changed or source_changed):
        ClinicalNoteHistory.objects.create(
            note=existing_note,
            soap_json=existing_note.soap_json or {},
            extract_json=existing_note.extract_json or {},
            followups_json=existing_note.followups_json or [],
            web_intake_snapshot=existing_note.web_intake_snapshot or {},
            edited_by=request.user,
        )

    note, created = ClinicalNote.objects.update_or_create(
        appointment=appointment,
        defaults={
            "patient": patient,
            "intake": intake,
            "recording": recording,
            "treatment_session": None,
            "soap_json": soap,
            "extract_json": extract,
            "followups_json": followups,
            "web_intake_snapshot": web_snapshot,
            "registered_by": request.user,
            "updated_by": request.user,
        },
    )

    if created:
        messages.success(request, "確認済みのカルテ案をカルテに登録しました。")
    else:
        messages.success(request, "確認済みのカルテ案で既存カルテを更新しました。")

    next_after_register = (request.POST.get("next_after_register") or "").strip()

    if next_after_register == "treatment_plan":
        return redirect(
            "treatment_plans:plan_create_from_clinical_note",
            clinical_note_id=note.id,
        )

    return redirect("staff:patient_detail", patient_id=patient.id)


def normalize_timeline_event(
    *,
    event_date,
    event_type,
    title,
    description,
    status,
    tone="neutral",
    actions=None,
    sort_priority=0,
):
    return {
        "date": event_date,
        "type": event_type,
        "title": title,
        "description": description,
        "status": status,
        "tone": tone,
        "actions": actions or [],
        "sort_priority": sort_priority,
    }


def build_patient_timeline(patient, clinic):
    from apps.intakes.views import build_interview_recording_flow_state
    from apps.treatment_sessions.views import (
        build_treatment_session_flow_state,
    )

    notes = list(
        ClinicalNote.objects
        .filter(
            patient=patient,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .select_related("appointment", "recording", "treatment_session")
        .order_by("-created_at")
    )
    notes_by_recording = {
        note.recording_id: note
        for note in notes
        if note.recording_id
    }
    notes_by_session = {
        note.treatment_session_id: note
        for note in notes
        if note.treatment_session_id
    }

    appointments = list(
        Appointment.objects
        .filter(
            clinic=clinic,
            patient=patient,
            patient__clinic=clinic,
        )
        .select_related("assigned_staff")
        .order_by("-start_at")
    )
    recordings = list(
        InterviewRecording.objects
        .filter(
            clinic=clinic,
            patient=patient,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .filter(Q(intake__isnull=True) | Q(intake__clinic=clinic))
        .select_related("appointment", "intake")
        .order_by("-created_at")
    )
    sessions = list(
        TreatmentSession.objects
        .filter(
            clinic=clinic,
            patient=patient,
            patient__clinic=clinic,
        )
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(intake__isnull=True) | Q(intake__clinic=clinic),
            Q(clinical_note__isnull=True)
            | Q(
                clinical_note__patient__clinic=clinic,
                clinical_note__appointment__clinic=clinic,
            ),
            Q(treatment_plan__isnull=True)
            | Q(treatment_plan__patient__clinic=clinic),
        )
        .select_related(
            "appointment",
            "clinical_note",
            "treatment_plan",
        )
        .prefetch_related("chunks")
        .order_by("-created_at")
    )
    posture_assessments = list(
        PostureAssessment.objects
        .filter(
            clinic=clinic,
            patient=patient,
            patient__clinic=clinic,
        )
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(treatment_session__isnull=True)
            | Q(treatment_session__clinic=clinic),
            Q(clinical_note__isnull=True)
            | Q(
                clinical_note__patient__clinic=clinic,
                clinical_note__appointment__clinic=clinic,
            ),
        )
        .select_related("appointment", "clinical_note")
        .order_by("-created_at")
    )
    treatment_plans = list(
        TreatmentPlan.objects
        .filter(
            patient=patient,
            patient__clinic=clinic,
        )
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(intake__isnull=True) | Q(intake__clinic=clinic),
            Q(clinical_note__isnull=True)
            | Q(
                clinical_note__patient__clinic=clinic,
                clinical_note__appointment__clinic=clinic,
            ),
        )
        .select_related("appointment", "clinical_note")
        .order_by("-created_at")
    )

    events = []
    appointment_tones = {
        Appointment.Status.PENDING: "attention",
        Appointment.Status.BOOKED: "info",
        Appointment.Status.ARRIVED: "processing",
        Appointment.Status.COMPLETED: "done",
        Appointment.Status.CANCELLED: "neutral",
        Appointment.Status.NO_SHOW: "error",
    }
    for appointment in appointments:
        local_start = timezone.localtime(appointment.start_at)
        assigned_name = ""
        if appointment.assigned_staff:
            assigned_name = (
                appointment.assigned_staff.get_full_name()
                or appointment.assigned_staff.username
            )
        description = appointment.menu or "予約"
        if assigned_name:
            description = f"{description} / 担当：{assigned_name}"
        events.append(normalize_timeline_event(
            event_date=appointment.start_at,
            event_type="予約",
            title=appointment.menu or "来院予約",
            description=description,
            status=appointment.get_status_display(),
            tone=appointment_tones.get(appointment.status, "neutral"),
            actions=[
                {
                    "label": "予約一覧で確認",
                    "url": (
                        f"{reverse('staff:appointments')}"
                        f"?period=day&day={local_start.date().isoformat()}"
                    ),
                },
                {
                    "label": "施術前チェックを開く",
                    "url": reverse(
                        "staff:pre_treatment_check",
                        args=[patient.id],
                    ),
                },
            ],
        ))

    for note in notes:
        extract = (
            note.extract_json
            if isinstance(note.extract_json, dict)
            else {}
        )
        soap = (
            note.soap_json
            if isinstance(note.soap_json, dict)
            else {}
        )
        note_description = _compact_dashboard_text(
            extract.get("overall_summary")
            or extract.get("chief_complaint")
            or _profile_section(soap, "S", "subjective"),
            fallback="確定済みカルテを登録しました。",
            limit=100,
        )
        events.append(normalize_timeline_event(
            event_date=note.created_at,
            event_type="カルテ",
            title="施術カルテ",
            description=note_description,
            status="カルテ登録済み",
            tone="done",
            sort_priority=2,
            actions=[
                {
                    "label": "カルテ詳細",
                    "url": reverse(
                        "staff:clinical_note_detail",
                        args=[note.id],
                    ),
                },
                {
                    "label": "施術後サマリーを見る",
                    "url": reverse(
                        "staff:post_treatment_summary",
                        args=[note.id],
                    ),
                },
                {
                    "label": "患者向け説明レポートを開く",
                    "url": reverse(
                        "staff:patient_aftercare_report",
                        args=[note.id],
                    ),
                },
            ],
        ))
        events.append(normalize_timeline_event(
            event_date=note.updated_at,
            event_type="患者向けレポート",
            title="施術後説明レポート",
            description=(
                "本日のまとめ・セルフケア・次回確認ポイントを患者さん向けに表示できます。"
            ),
            status="表示可能",
            tone="confirmed",
            sort_priority=1,
            actions=[
                {
                    "label": "患者向け説明レポートを開く",
                    "url": reverse(
                        "staff:patient_aftercare_report",
                        args=[note.id],
                    ),
                },
                {
                    "label": "施術後サマリーを見る",
                    "url": reverse(
                        "staff:post_treatment_summary",
                        args=[note.id],
                    ),
                },
            ],
        ))

    for recording in recordings:
        note = notes_by_recording.get(recording.id)
        flow_state = build_interview_recording_flow_state(
            recording,
            clinical_note_exists=note is not None,
            clinical_note_is_current=note is not None,
        )
        actions = [{
            "label": "初診録音詳細",
            "url": reverse(
                "intakes:recording_detail",
                args=[recording.id],
            ),
        }]
        if note:
            actions.append({
                "label": "カルテ詳細",
                "url": reverse(
                    "staff:clinical_note_detail",
                    args=[note.id],
                ),
            })
        events.append(normalize_timeline_event(
            event_date=recording.created_at,
            event_type="初診録音",
            title="初診・問診録音",
            description=_compact_dashboard_text(
                recording.transcript_text,
                fallback="問診・主訴・初回評価の録音記録です。",
                limit=100,
            ),
            status=flow_state["label"],
            tone=flow_state["tone"],
            actions=actions,
        ))

    for session in sessions:
        note = notes_by_session.get(session.id) or session.clinical_note
        flow_state = build_treatment_session_flow_state(
            session,
            session.chunks.all(),
            clinical_note_exists=note is not None,
            clinical_note_is_current=note is not None,
        )
        actions = [{
            "label": "通院施術録音詳細",
            "url": reverse(
                "treatment_sessions:detail",
                args=[session.id],
            ),
        }]
        if note:
            actions.append({
                "label": "カルテ詳細",
                "url": reverse(
                    "staff:clinical_note_detail",
                    args=[note.id],
                ),
            })
        events.append(normalize_timeline_event(
            event_date=session.started_at or session.created_at,
            event_type="通院施術録音",
            title=session.title or "通院施術録音",
            description=_compact_dashboard_text(
                session.transcript_text,
                fallback="前回からの変化と本日の施術内容を記録しています。",
                limit=100,
            ),
            status=flow_state["label"],
            tone=flow_state["tone"],
            actions=actions,
        ))

    posture_tones = {
        PostureAssessment.Status.DRAFT: "neutral",
        PostureAssessment.Status.ANALYZING: "processing",
        PostureAssessment.Status.ANALYZED: "info",
        PostureAssessment.Status.CONFIRMED: "confirmed",
        PostureAssessment.Status.FAILED: "error",
    }
    for assessment in posture_assessments:
        summary = assessment.get_active_summary()
        description = _compact_dashboard_text(
            _profile_section(
                summary,
                "report_summary_for_patient",
                "reportSummaryForPatient",
            )
            or _profile_section(
                summary,
                "overall_summary",
                "overallSummary",
            )
            or assessment.memo,
            fallback="姿勢画像と身体バランスの傾向を記録しています。",
            limit=100,
        )
        actions = [{
            "label": "姿勢分析詳細",
            "url": reverse(
                "posture_assessments:detail",
                args=[assessment.id],
            ),
        }]
        if assessment.status in {
            PostureAssessment.Status.ANALYZED,
            PostureAssessment.Status.CONFIRMED,
        }:
            actions.append({
                "label": "患者向け姿勢レポート",
                "url": reverse(
                    "posture_assessments:assessment_report",
                    args=[assessment.id],
                ),
            })
        events.append(normalize_timeline_event(
            event_date=assessment.created_at,
            event_type="姿勢分析",
            title=assessment.title or "AI姿勢分析",
            description=description,
            status=assessment.get_status_display(),
            tone=posture_tones.get(assessment.status, "neutral"),
            actions=actions,
        ))

    plan_tones = {
        "active": "processing",
        "paused": "attention",
        "completed": "done",
    }
    for plan in treatment_plans:
        description = _compact_dashboard_text(
            plan.chief_complaint
            or plan.lifestyle_other_instruction
            or plan.caution_notes,
            fallback="施術目的と今後の進め方をまとめた計画です。",
            limit=100,
        )
        events.append(normalize_timeline_event(
            event_date=plan.created_at,
            event_type="施術計画",
            title=plan.title or "施術計画",
            description=description,
            status=plan.get_status_display(),
            tone=plan_tones.get(plan.status, "neutral"),
            actions=[{
                "label": "施術計画詳細",
                "url": reverse(
                    "treatment_plans:plan_detail",
                    args=[plan.id],
                ),
            }],
        ))

    return sorted(
        events,
        key=lambda event: (
            event["date"],
            event["sort_priority"],
        ),
        reverse=True,
    )


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
        "timeline",
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
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(intake__isnull=True) | Q(intake__clinic=clinic),
            Q(clinical_note__isnull=True)
            | Q(
                clinical_note__patient__clinic=clinic,
                clinical_note__appointment__clinic=clinic,
            ),
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
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(treatment_session__isnull=True)
            | Q(treatment_session__clinic=clinic),
            Q(clinical_note__isnull=True)
            | Q(
                clinical_note__patient__clinic=clinic,
                clinical_note__appointment__clinic=clinic,
            ),
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

    latest_note = notes.first()
    latest_intake = (
        Intake.objects
        .filter(
            clinic=clinic,
            patient=patient,
            patient__clinic=clinic,
        )
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic)
        )
        .select_related("appointment")
        .order_by("-submitted_at", "-id")
        .first()
    )
    active_plan = treatment_plans.filter(status="active", is_active=True).first()
    latest_plan = treatment_plans.first()
    profile_context = build_patient_profile_context(
        patient,
        latest_intake=latest_intake,
        latest_note=latest_note,
        latest_plan=active_plan or latest_plan,
        latest_posture_assessment=latest_posture_assessment,
    )
    posture_summary = profile_context["posture_summary"]
    posture_summary_source = profile_context["posture_summary_source"]
    posture_profile_available = profile_context["posture_profile_available"]
    posture_profile_summary = profile_context["posture_profile_summary"]
    body_profile_items = profile_context["body_profile_items"]
    posture_attention_points = profile_context["posture_attention_points"]
    patient_context_profile = profile_context["patient_context_profile"]
    latest_extract = profile_context["latest_extract"]
    latest_assessment = profile_context["latest_assessment"]
    latest_treatment_policy = profile_context["latest_treatment_policy"]

    upcoming_appointments = appointments.filter(start_at__gte=now).order_by("start_at")[:4]
    past_appointments = appointments.filter(start_at__lt=now).order_by("-start_at")[:8]

    latest_appointment = appointments.first()
    today = timezone.localdate()
    recording_appointment = (
        appointments
        .filter(
            start_at__date=today,
            start_at__gte=now,
        )
        .exclude(
            status__in=[
                Appointment.Status.CANCELLED,
                Appointment.Status.NO_SHOW,
            ]
        )
        .order_by("start_at")
        .first()
    )
    if recording_appointment is None:
        recording_appointment = (
            appointments
            .filter(start_at__date=today)
            .exclude(
                status__in=[
                    Appointment.Status.CANCELLED,
                    Appointment.Status.NO_SHOW,
                ]
            )
            .order_by("-start_at")
            .first()
        )

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

    timeline_events = []
    if active_tab == "timeline":
        timeline_events = build_patient_timeline(patient, clinic)

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
        "recording_appointment": recording_appointment,

        "active_plan": active_plan,
        "latest_plan": latest_plan,
        "progress_count": progress_count,

        "latest_note": latest_note,
        "latest_extract": latest_extract,
        "latest_assessment": latest_assessment,
        "latest_treatment_policy": latest_treatment_policy,
        "timeline_events": timeline_events,

        # ★ AI姿勢分析
        "posture_assessments": posture_assessments,
        "posture_assessment_count": posture_assessment_count,
        "latest_posture_assessment": latest_posture_assessment,
        "posture_summary": posture_summary,
        "posture_summary_source": posture_summary_source,
        "posture_profile_available": posture_profile_available,
        "posture_profile_summary": posture_profile_summary,
        "body_profile_items": body_profile_items,
        "posture_attention_points": posture_attention_points,

        "file_count": 0,
    })


@staff_required
def staff_pre_treatment_check_view(request, patient_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の患者情報のみ閲覧できます。")

    patient = get_object_or_404(
        Patient.objects.select_related("clinic"),
        pk=patient_id,
        clinic=clinic,
    )
    now = timezone.now()
    today = timezone.localdate()

    appointments = (
        Appointment.objects
        .filter(patient=patient, clinic=clinic)
        .select_related("assigned_staff", "treatment_plan")
    )
    today_appointments = (
        appointments
        .filter(start_at__date=today)
        .exclude(
            status__in=[
                Appointment.Status.CANCELLED,
                Appointment.Status.NO_SHOW,
            ]
        )
    )
    today_appointment = (
        today_appointments
        .filter(start_at__gte=now)
        .order_by("start_at")
        .first()
        or today_appointments.order_by("-start_at").first()
    )

    notes = (
        ClinicalNote.objects
        .filter(
            patient=patient,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        .select_related("appointment", "recording", "treatment_session", "intake")
        .order_by("-created_at")
    )
    latest_note = notes.first()

    latest_intake = (
        Intake.objects
        .filter(
            clinic=clinic,
            patient=patient,
            patient__clinic=clinic,
        )
        .filter(Q(appointment__isnull=True) | Q(appointment__clinic=clinic))
        .select_related("appointment")
        .order_by("-submitted_at", "-id")
        .first()
    )

    treatment_plans = (
        TreatmentPlan.objects
        .filter(patient=patient, patient__clinic=clinic)
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(intake__isnull=True) | Q(intake__clinic=clinic),
            Q(clinical_note__isnull=True)
            | Q(
                clinical_note__patient__clinic=clinic,
                clinical_note__appointment__clinic=clinic,
            ),
        )
        .select_related("appointment", "intake", "clinical_note")
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
    latest_plan = treatment_plans.first()

    posture_assessments = (
        PostureAssessment.objects
        .filter(clinic=clinic, patient=patient, patient__clinic=clinic)
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(treatment_session__isnull=True)
            | Q(treatment_session__clinic=clinic),
            Q(clinical_note__isnull=True)
            | Q(
                clinical_note__patient__clinic=clinic,
                clinical_note__appointment__clinic=clinic,
            ),
        )
        .select_related(
            "appointment",
            "treatment_session",
            "clinical_note",
            "confirmed_by",
        )
        .order_by("-created_at")
    )
    latest_posture_assessment = posture_assessments.first()

    profile_context = build_patient_profile_context(
        patient,
        latest_intake=latest_intake,
        latest_note=latest_note,
        latest_plan=latest_plan,
        latest_posture_assessment=latest_posture_assessment,
    )

    latest_extract = profile_context["latest_extract"]
    latest_soap = profile_context["latest_soap"]
    latest_note_summary = {
        "chief_complaint": _compact_dashboard_text(
            latest_extract.get("chief_complaint")
            or _profile_section(latest_soap, "S", "subjective"),
            fallback="未記録",
            limit=72,
        ),
        "subjective": _compact_dashboard_text(
            _profile_section(latest_soap, "S", "subjective"),
            fallback="未記録",
            limit=88,
        ),
        "assessment": _compact_dashboard_text(
            _profile_section(latest_soap, "A", "assessment"),
            fallback="未記録",
            limit=88,
        ),
        "plan": _compact_dashboard_text(
            _profile_section(latest_soap, "P", "plan"),
            fallback="未記録",
            limit=88,
        ),
    }

    plan_visit_parts = []
    if latest_plan and latest_plan.visit_guide_type:
        plan_visit_parts.append(latest_plan.get_visit_guide_type_display())
    if latest_plan and latest_plan.visit_guide_count:
        plan_visit_parts.append(f"{latest_plan.visit_guide_count}回")
    plan_visit_guide = " ".join(plan_visit_parts)
    if latest_plan and latest_plan.visit_guide_unit_note:
        plan_visit_guide = " / ".join(
            item
            for item in (plan_visit_guide, latest_plan.visit_guide_unit_note)
            if item
        )

    latest_plan_summary = {
        "purpose": _compact_dashboard_text(
            (
                latest_plan.title
                or latest_plan.chief_complaint
                if latest_plan
                else ""
            ),
            fallback="未記録",
            limit=72,
        ),
        "policy": _compact_dashboard_text(
            (
                latest_plan.lifestyle_other_instruction
                or latest_plan.exercise_instruction
                or latest_plan.work_instruction
                if latest_plan
                else ""
            ),
            fallback="施術者の評価と合わせて方針を確認します。",
            limit=88,
        ),
        "visit_guide": plan_visit_guide or "未設定",
    }

    today_check_points = list(profile_context["posture_attention_points"])
    for item in profile_context["body_profile_items"]:
        if item["level"] != "check":
            continue
        check_text = f'{item["label"]}：{item["check_point"]}'
        if check_text not in today_check_points:
            today_check_points.append(check_text)
        if len(today_check_points) >= 5:
            break
    if latest_note:
        for item in _dashboard_text_list(latest_note.followups_json):
            compact = _compact_dashboard_text(item, limit=64)
            if compact and compact not in today_check_points:
                today_check_points.append(compact)
            if len(today_check_points) >= 5:
                break
    if not today_check_points:
        today_check_points = [
            "主訴と前回からの変化を確認し、施術者の評価と合わせて判断します。"
        ]

    patient_age = None
    if patient.birth_date:
        patient_age = (
            today.year
            - patient.birth_date.year
            - (
                (today.month, today.day)
                < (patient.birth_date.month, patient.birth_date.day)
            )
        )
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

    return render(request, "staff/patients/pre_treatment_check.html", {
        "active": "patient_search",
        "page_title": "施術前チェック",
        "patient": patient,
        "patient_age": patient_age,
        "patient_gender": patient_gender,
        "today_appointment": today_appointment,
        "recording_appointment": today_appointment,
        "latest_note": latest_note,
        "latest_note_summary": latest_note_summary,
        "latest_intake": latest_intake,
        "latest_plan": latest_plan,
        "latest_plan_summary": latest_plan_summary,
        "latest_posture_assessment": latest_posture_assessment,
        "today_check_points": today_check_points[:5],
        **profile_context,
    })


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, dict):
        v = (
            v.get("text")
            or v.get("summary")
            or v.get("items")
            or []
        )
    if isinstance(v, (list, tuple)):
        items = []
        for x in v:
            if isinstance(x, dict):
                x = x.get("text") or x.get("summary") or x.get("label") or ""
            text = str(x or "").strip()
            if text:
                items.append(text)
        return items
    if isinstance(v, str):
        return [s.strip() for s in v.split("\n") if s.strip()]
    return [str(v)]


def _merge_note_items(*values, limit=None):
    items = []
    for value in values:
        for item in _as_list(value):
            text = " ".join(item.split())
            if text and text not in items:
                items.append(text)
            if limit and len(items) >= limit:
                return items
    return items


def _short_note_text(values, fallback="未記録", limit=86):
    items = _merge_note_items(values, limit=2)
    if not items:
        return fallback
    text = " / ".join(items)
    if len(text) > limit:
        return f"{text[:limit - 1].rstrip()}…"
    return text


def _build_post_treatment_content(
    note,
    source_summary=None,
    source_practitioner_memo="",
):
    source_summary = source_summary if isinstance(source_summary, dict) else {}
    soap = note.soap_json if isinstance(note.soap_json, dict) else {}
    extract = note.extract_json if isinstance(note.extract_json, dict) else {}
    source_soap = _profile_section(source_summary, "soap", "SOAP")
    if not isinstance(source_soap, dict):
        source_soap = {}

    session_summary = _profile_section(
        source_summary,
        "session_summary",
        "sessionSummary",
    )
    source_extract = _profile_section(source_summary, "extract")
    source_treatment = _profile_section(source_summary, "treatment")
    source_explanation = _profile_section(source_summary, "explanation")
    source_next_plan = _profile_section(
        source_summary,
        "next_plan",
        "nextPlan",
    )
    if not isinstance(session_summary, dict):
        session_summary = {}
    if not isinstance(source_extract, dict):
        source_extract = {}
    if not isinstance(source_treatment, dict):
        source_treatment = {}
    if not isinstance(source_explanation, dict):
        source_explanation = {}
    if not isinstance(source_next_plan, dict):
        source_next_plan = {}

    extract_next_plan = _profile_section(extract, "next_plan", "nextPlan")
    if not isinstance(extract_next_plan, dict):
        extract_next_plan = {}

    soap_view = {}
    soap_aliases = {
        "S": ("S", "subjective"),
        "O": ("O", "objective"),
        "A": ("A", "assessment"),
        "P": ("P", "plan"),
    }
    for key, aliases in soap_aliases.items():
        soap_view[key] = _merge_note_items(
            _profile_section(soap, *aliases),
            _profile_section(source_soap, *aliases),
            limit=5,
        )

    followup_next = []
    followup_cautions = []
    followup_guidance = []
    followups = note.followups_json
    if not isinstance(followups, (list, tuple)):
        followups = []
    for item in followups:
        if isinstance(item, dict):
            item_type = str(item.get("type") or "followup")
            item_text = str(item.get("text") or "").strip()
        else:
            item_type = "followup"
            item_text = str(item or "").strip()
        if not item_text:
            continue
        if item_type in {"safety", "caution", "missing_information"}:
            followup_cautions.append(item_text)
        elif item_type in {"guidance", "home_care", "self_care"}:
            followup_guidance.append(item_text)
        else:
            followup_next.append(item_text)

    overall_summary = _short_note_text(
        _merge_note_items(
            extract.get("overall_summary"),
            session_summary.get("overall_summary"),
            source_extract.get("overall_summary"),
            _profile_section(extract, "progress_note", "progressNote"),
            soap_view["A"],
            soap_view["S"],
            limit=3,
        ),
        fallback=(
            "本日の状態と前回からの変化を確認し、施術者の評価に合わせて施術を行いました。"
        ),
        limit=150,
    )

    treatment_items = _merge_note_items(
        extract.get("performed_treatments"),
        extract.get("treatment_detail"),
        extract.get("manual_therapy"),
        extract.get("exercise_therapy"),
        extract.get("physical_therapy"),
        source_treatment.get("performed_treatments"),
        source_treatment.get("target_areas"),
        limit=8,
    )
    patient_guidance_items = _merge_note_items(
        extract.get("explained_to_patient"),
        extract.get("lifestyle_guidance"),
        source_explanation.get("explained_to_patient"),
        source_explanation.get("lifestyle_guidance"),
        followup_guidance,
        limit=7,
    )
    home_care_items = _merge_note_items(
        extract.get("home_care"),
        source_explanation.get("home_care"),
        limit=6,
    )
    next_check_items = _merge_note_items(
        extract.get("items_to_check_next_time"),
        extract_next_plan.get("items_to_check_next_time"),
        source_next_plan.get("items_to_check_next_time"),
        extract.get("next_treatment_policy"),
        extract_next_plan.get("next_treatment_policy"),
        source_next_plan.get("next_treatment_policy"),
        followup_next,
        limit=7,
    )
    caution_items = _merge_note_items(
        extract.get("cautions_until_next_visit"),
        extract.get("safety_notes"),
        extract.get("missing_information"),
        source_explanation.get("cautions_until_next_visit"),
        _profile_section(source_summary, "safety_notes", "safetyNotes"),
        _profile_section(source_summary, "missing_information", "missingInformation"),
        followup_cautions,
        limit=7,
    )
    practitioner_notes = _merge_note_items(
        extract.get("findings"),
        extract.get("suspected_causes"),
        extract.get("relationship_notes"),
        extract.get("treatment_intent"),
        source_treatment.get("patient_response"),
        source_treatment.get("after_treatment_change"),
        source_practitioner_memo,
        limit=7,
    )

    if not treatment_items:
        treatment_items = ["本日の施術内容はカルテ詳細で確認してください。"]
    if not patient_guidance_items:
        patient_guidance_items = [
            "本日の状態と施術内容を確認し、無理のない範囲で経過をみてください。"
        ]
    if not home_care_items:
        home_care_items = [
            "ご自宅では、スタッフの指示に合わせて無理のない範囲で行ってください。"
        ]
    if not next_check_items:
        next_check_items = [
            "症状や動作の変化を次回来院時に確認します。"
        ]
    generic_caution = (
        "痛みや違和感が強い場合は無理をせず中止し、次回来院時にお伝えください。"
    )
    if generic_caution not in caution_items:
        caution_items.append(generic_caution)

    return {
        "soap_view": soap_view,
        "overall_summary": overall_summary,
        "chief_complaint": _short_note_text(
            extract.get("chief_complaint") or soap_view["S"],
            fallback="未記録",
            limit=90,
        ),
        "treatment_items": treatment_items,
        "patient_guidance_items": patient_guidance_items,
        "home_care_items": home_care_items,
        "next_check_items": next_check_items,
        "caution_items": caution_items,
        "practitioner_notes": practitioner_notes,
    }


def _patient_report_text(value):
    text = " ".join(str(value or "").split())
    replacements = (
        ("AIが判断しました", "記録内容をもとに整理しました"),
        ("診断しました", "状態を確認しました"),
        ("診断", "評価"),
        ("必ず改善します", "改善を目指します"),
        ("完治します", "改善を目指します"),
        ("治ります", "改善を目指します"),
    )
    for before, after in replacements:
        text = text.replace(before, after)
    return text


def _patient_report_items(*values, fallback=None, limit=6):
    items = []
    for item in _merge_note_items(*values):
        text = _patient_report_text(item)
        if text and text not in items:
            items.append(text)
        if len(items) >= limit:
            break
    if not items and fallback:
        items.append(fallback)
    return items


def _build_patient_aftercare_content(
    post_summary,
    posture_summary_text="",
    include_posture=False,
    related_plan=None,
):
    soap_view = post_summary.get("soap_view") or {}
    body_condition_sources = [soap_view.get("O")]
    if include_posture and posture_summary_text:
        body_condition_sources.append(posture_summary_text)
    body_condition_sources.append(soap_view.get("A"))
    plan_home_guidance = []
    plan_cautions = []
    if related_plan:
        plan_home_guidance = [
            related_plan.bath_instruction,
            related_plan.walking_instruction,
            related_plan.exercise_instruction,
            related_plan.work_instruction,
            related_plan.lifestyle_other_instruction,
        ]
        plan_cautions = [
            related_plan.caution_notes,
            related_plan.rebound_reaction_note,
        ]

    return {
        "overall_summary": _patient_report_text(
            post_summary.get("overall_summary")
            or "本日の状態を確認し、施術者の評価に合わせて施術を行いました。"
        ),
        "treatment_items": _patient_report_items(
            post_summary.get("treatment_items"),
            fallback="本日の状態に合わせて施術を行いました。",
        ),
        "body_condition_items": _patient_report_items(
            *body_condition_sources,
            fallback="本日の身体の状態は、施術者と一緒に確認しました。",
        ),
        "home_attention_items": _patient_report_items(
            post_summary.get("patient_guidance_items"),
            plan_home_guidance,
            fallback="ご自宅では無理をせず、身体の変化を確認してください。",
        ),
        "home_care_items": _patient_report_items(
            post_summary.get("home_care_items"),
            plan_home_guidance,
            fallback=(
                "スタッフの指示に合わせて、無理のない範囲で行ってください。"
            ),
        ),
        "next_check_items": _patient_report_items(
            post_summary.get("next_check_items"),
            fallback="次回来院時に、症状や動作の変化を確認します。",
        ),
        "caution_items": _patient_report_items(
            post_summary.get("caution_items"),
            plan_cautions,
            fallback=(
                "痛みや違和感が強い場合は無理をせず中止し、スタッフへご相談ください。"
            ),
        ),
    }


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


def _build_post_treatment_related_context(note, clinic):
    source_session = None
    if note.treatment_session_id:
        source_session = (
            TreatmentSession.objects
            .filter(
                pk=note.treatment_session_id,
                clinic=clinic,
                patient=note.patient,
                patient__clinic=clinic,
            )
            .filter(
                Q(appointment__isnull=True)
                | Q(appointment=note.appointment, appointment__clinic=clinic)
            )
            .first()
        )

    source_recording = None
    if note.recording_id:
        source_recording = (
            InterviewRecording.objects
            .filter(
                pk=note.recording_id,
                clinic=clinic,
                patient=note.patient,
                patient__clinic=clinic,
                appointment=note.appointment,
                appointment__clinic=clinic,
            )
            .first()
        )

    source_intake = None
    if note.intake_id:
        source_intake = (
            Intake.objects
            .filter(
                pk=note.intake_id,
                clinic=clinic,
                patient=note.patient,
                patient__clinic=clinic,
            )
            .filter(
                Q(appointment__isnull=True)
                | Q(appointment=note.appointment, appointment__clinic=clinic)
            )
            .first()
        )

    source_summary = {}
    source_type = "manual"
    if source_session:
        source_summary = (
            source_session.confirmed_summary_json
            or source_session.summary_json
            or {}
        )
        source_type = "treatment_session"
    elif source_recording:
        source_summary = (
            source_recording.confirmed_summary_json
            or source_recording.summary_json
            or {}
        )
        source_type = "interview_recording"
    if not isinstance(source_summary, dict):
        source_summary = {}

    post_summary = _build_post_treatment_content(
        note,
        source_summary=source_summary,
        source_practitioner_memo=(
            source_session.memo
            if source_session
            else ""
        ),
    )

    plan_queryset = (
        TreatmentPlan.objects
        .filter(patient=note.patient, patient__clinic=clinic)
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(intake__isnull=True) | Q(intake__clinic=clinic),
            Q(clinical_note__isnull=True)
            | Q(
                clinical_note__patient__clinic=clinic,
                clinical_note__appointment__clinic=clinic,
            ),
        )
        .select_related("appointment", "clinical_note", "intake")
    )
    related_plan_filter = Q(clinical_note=note) | Q(appointment=note.appointment)
    if source_session and source_session.treatment_plan_id:
        related_plan_filter |= Q(pk=source_session.treatment_plan_id)
    related_plan = (
        plan_queryset
        .filter(related_plan_filter)
        .order_by("-is_active", "-created_at")
        .first()
    )
    if related_plan is None:
        related_plan = (
            plan_queryset
            .order_by("-is_active", "-created_at")
            .first()
        )

    posture_queryset = (
        PostureAssessment.objects
        .filter(
            clinic=clinic,
            patient=note.patient,
            patient__clinic=clinic,
        )
        .filter(
            Q(appointment__isnull=True) | Q(appointment__clinic=clinic),
            Q(treatment_session__isnull=True)
            | Q(treatment_session__clinic=clinic),
            Q(clinical_note__isnull=True)
            | Q(
                clinical_note__patient__clinic=clinic,
                clinical_note__appointment__clinic=clinic,
            ),
        )
    )
    related_posture_filter = (
        Q(clinical_note=note)
        | Q(appointment=note.appointment)
    )
    if source_session:
        related_posture_filter |= Q(treatment_session=source_session)
    related_posture_assessment = (
        posture_queryset
        .filter(related_posture_filter)
        .order_by("-created_at")
        .first()
    )
    if related_posture_assessment is None:
        related_posture_assessment = (
            posture_queryset.order_by("-created_at").first()
        )

    posture_summary = {}
    if related_posture_assessment:
        posture_summary = (
            related_posture_assessment.confirmed_summary_json
            or related_posture_assessment.ai_summary_json
            or {}
        )
    posture_summary_text = _compact_dashboard_text(
        _profile_section(
            posture_summary,
            "report_summary_for_patient",
            "reportSummaryForPatient",
        )
        or _profile_section(
            posture_summary,
            "patient_explanation",
            "patientExplanation",
        )
        or _profile_section(
            posture_summary,
            "overall_summary",
            "overallSummary",
        ),
        fallback="姿勢分析の詳細画面で所見を確認できます。",
        limit=110,
    )

    plan_visit_parts = []
    if related_plan and related_plan.visit_guide_type:
        plan_visit_parts.append(related_plan.get_visit_guide_type_display())
    if related_plan and related_plan.visit_guide_count:
        plan_visit_parts.append(f"{related_plan.visit_guide_count}回")
    plan_visit_guide = " ".join(plan_visit_parts)
    if related_plan and related_plan.visit_guide_unit_note:
        plan_visit_guide = " / ".join(
            item
            for item in (plan_visit_guide, related_plan.visit_guide_unit_note)
            if item
        )

    return {
        "post_summary": post_summary,
        "related_plan": related_plan,
        "plan_visit_guide": plan_visit_guide or "未設定",
        "related_posture_assessment": related_posture_assessment,
        "posture_summary_text": posture_summary_text,
        "source_session": source_session,
        "source_recording": source_recording,
        "source_intake": source_intake,
        "source_type": source_type,
    }


def build_patient_aftercare_report_context(note, clinic):
    """スタッフ版と共有版で共通の患者向け表示データを構築する。"""
    related_context = _build_post_treatment_related_context(note, clinic)
    patient_report = _build_patient_aftercare_content(
        related_context["post_summary"],
        posture_summary_text=related_context["posture_summary_text"],
        include_posture=bool(related_context["related_posture_assessment"]),
        related_plan=related_context["related_plan"],
    )
    next_after = max(timezone.now(), note.appointment.end_at)
    next_appointment = (
        Appointment.objects
        .filter(
            clinic=clinic,
            patient=note.patient,
            patient__clinic=clinic,
            start_at__gt=next_after,
        )
        .exclude(
            status__in=[
                Appointment.Status.CANCELLED,
                Appointment.Status.NO_SHOW,
            ]
        )
        .select_related("assigned_staff")
        .order_by("start_at")
        .first()
    )
    return {
        "patient_report": patient_report,
        "next_appointment": next_appointment,
    }


def _patient_share_public_url(request, share_token):
    return request.build_absolute_uri(
        reverse("patients:shared_patient_page", args=[share_token.token])
    )


def _render_qr_png(value):
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(value)
    qr.make(fit=True)
    image = qr.make_image(fill_color="#0f172a", back_color="white")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _patient_share_context(request, note, clinic):
    share_token = (
        PatientShareToken.objects
        .filter(
            clinic=clinic,
            patient=note.patient,
            clinical_note=note,
            purpose=PatientShareToken.Purpose.AFTERCARE_REPORT,
        )
        .order_by("-created_at", "-id")
        .first()
    )
    if share_token is None:
        status_key = "not_issued"
        status_label = "未発行"
    elif not share_token.is_active:
        status_key = "revoked"
        status_label = "無効"
    elif share_token.is_expired:
        status_key = "expired"
        status_label = "期限切れ"
    else:
        status_key = "active"
        status_label = "有効"

    share_url = ""
    if share_token and share_token.is_available:
        share_url = _patient_share_public_url(request, share_token)
    return {
        "share_token": share_token,
        "share_status_key": status_key,
        "share_status_label": status_label,
        "share_url": share_url,
    }


@staff_required
def staff_post_treatment_summary_view(request, note_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のカルテのみ閲覧できます。")

    note = get_object_or_404(
        ClinicalNote.objects.select_related(
            "patient",
            "appointment",
            "appointment__assigned_staff",
            "registered_by",
            "updated_by",
        ),
        pk=note_id,
        patient__clinic=clinic,
        appointment__clinic=clinic,
    )

    related_context = _build_post_treatment_related_context(note, clinic)

    return render(request, "staff/patients/post_treatment_summary.html", {
        "active": "patient_search",
        "page_title": "施術後サマリー",
        "note": note,
        "patient": note.patient,
        "appointment": note.appointment,
        **related_context,
    })


@staff_required
def staff_patient_aftercare_report_view(request, note_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のカルテのみ閲覧できます。")

    note = get_object_or_404(
        ClinicalNote.objects.select_related(
            "patient",
            "appointment",
            "appointment__assigned_staff",
        ),
        pk=note_id,
        patient__clinic=clinic,
        appointment__clinic=clinic,
    )
    report_context = build_patient_aftercare_report_context(note, clinic)
    share_context = _patient_share_context(request, note, clinic)

    return render(
        request,
        "staff/patients/patient_aftercare_report.html",
        {
            "active": "patient_search",
            "page_title": "患者向け施術後説明レポート",
            "note": note,
            "patient": note.patient,
            "appointment": note.appointment,
            **report_context,
            **share_context,
        },
    )


@staff_required
@require_POST
def staff_patient_share_token_create_view(request, note_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のカルテのみ共有できます。")

    with transaction.atomic():
        note = get_object_or_404(
            ClinicalNote.objects.select_for_update(of=("self",)).select_related(
                "patient",
                "appointment",
            ),
            pk=note_id,
            patient__clinic=clinic,
            appointment__clinic=clinic,
        )
        PatientShareToken.objects.filter(
            clinic=clinic,
            patient=note.patient,
            clinical_note=note,
            purpose=PatientShareToken.Purpose.AFTERCARE_REPORT,
            is_active=True,
        ).update(is_active=False, updated_at=timezone.now())
        PatientShareToken.objects.create(
            clinic=clinic,
            patient=note.patient,
            appointment=note.appointment,
            clinical_note=note,
            purpose=PatientShareToken.Purpose.AFTERCARE_REPORT,
            expires_at=timezone.now() + timedelta(days=7),
            created_by=request.user,
        )

    messages.success(
        request,
        "患者向け共有URLを発行しました。有効期限は7日間です。",
    )
    return redirect("staff:patient_aftercare_report", note_id=note.id)


@staff_required
@require_POST
def staff_patient_share_token_revoke_view(request, note_id, share_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の共有URLのみ無効化できます。")

    with transaction.atomic():
        share_token = get_object_or_404(
            PatientShareToken.objects.select_for_update(of=("self",)).select_related(
                "clinical_note",
                "patient",
            ),
            pk=share_id,
            clinic=clinic,
            patient__clinic=clinic,
            clinical_note_id=note_id,
            clinical_note__appointment__clinic=clinic,
            purpose=PatientShareToken.Purpose.AFTERCARE_REPORT,
        )
        if share_token.is_active:
            share_token.is_active = False
            share_token.save(update_fields=["is_active", "updated_at"])
    messages.success(request, "患者向け共有URLを無効化しました。")
    return redirect(
        "staff:patient_aftercare_report",
        note_id=share_token.clinical_note_id,
    )


@staff_required
@require_GET
def staff_patient_share_token_qr_view(request, share_id):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院の共有QRのみ表示できます。")

    share_token = get_object_or_404(
        PatientShareToken.objects.select_related(
            "patient",
            "appointment",
            "clinical_note",
            "clinical_note__appointment",
        ),
        pk=share_id,
        clinic=clinic,
        patient__clinic=clinic,
        clinical_note__appointment__clinic=clinic,
        purpose=PatientShareToken.Purpose.AFTERCARE_REPORT,
        is_active=True,
        expires_at__gt=timezone.now(),
    )
    note = share_token.clinical_note
    if (
        note is None
        or note.patient_id != share_token.patient_id
        or note.appointment.clinic_id != clinic.id
        or (
            share_token.appointment_id
            and share_token.appointment_id != note.appointment_id
        )
    ):
        raise Http404("共有QRを確認できません。")

    share_url = _patient_share_public_url(request, share_token)
    response = HttpResponse(_render_qr_png(share_url), content_type="image/png")
    response["Content-Disposition"] = 'inline; filename="aftercare-report-qr.png"'
    response["Cache-Control"] = "private, no-store, max-age=0"
    response["Pragma"] = "no-cache"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@staff_required
def staff_clinical_note_detail_view(request, pk):
    clinic = get_current_clinic(request)
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のカルテのみ閲覧できます。")

    note = get_object_or_404(
        ClinicalNote.objects.select_related(
            "patient",
            "appointment",
            "intake",
            "recording",
            "treatment_session",
            "registered_by",
            "updated_by",
            "appointment__assigned_staff",
        ),
        pk=pk,
        patient__clinic=clinic,
        appointment__clinic=clinic,
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

    source_session_available = bool(
        note.treatment_session_id
        and note.treatment_session.clinic_id == clinic.id
    )
    source_recording_available = bool(
        note.recording_id
        and note.recording.clinic_id == clinic.id
    )

    session_summary = {}
    if source_session_available:
        treatment_session = note.treatment_session
        session_summary = treatment_session.active_summary or {}
        if not isinstance(session_summary, dict):
            session_summary = {}

    recording_summary = {}
    if source_recording_available:
        recording_summary = note.recording.get_active_summary() or {}
        if not isinstance(recording_summary, dict):
            recording_summary = {}

    session_overview = session_summary.get("session_summary") or {}
    recording_extract = recording_summary.get("extract") or {}
    ai_summary_text = (
        extract.get("overall_summary")
        or session_overview.get("overall_summary")
        or recording_extract.get("overall_summary")
        or progress_note.get("short_summary")
        or progress_note.get("record_text")
        or ""
    )

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

    followup_next = [
        item["text"]
        for item in followup_items
        if item["text"] and item["type"] in {"next_check", "followup"}
    ]
    followup_cautions = [
        item["text"]
        for item in followup_items
        if item["text"] and item["type"] in {"safety", "missing_information"}
    ]

    assessment_items = _merge_note_items(
        soap_view["A"],
        findings,
        suspected_causes,
        extract.get("treatment_intent"),
        limit=4,
    )
    plan_items = _merge_note_items(
        soap_view["P"],
        extract.get("next_treatment_policy"),
        next_plan.get("next_treatment_policy"),
        limit=4,
    )
    treatment_summary_items = _merge_note_items(
        performed_treatments,
        extract.get("treatment_detail"),
        extract.get("manual_therapy"),
        extract.get("exercise_therapy"),
        extract.get("physical_therapy"),
        explained_to_patient,
        lifestyle_guidance,
        home_care,
        limit=8,
    )
    next_check_items = _merge_note_items(
        extract.get("items_to_check_next_time"),
        next_plan.get("items_to_check_next_time"),
        followup_next,
        limit=6,
    )
    caution_summary_items = _merge_note_items(
        safety_notes,
        cautions_until_next_visit,
        missing_information,
        followup_cautions,
        limit=6,
    )
    guidance_summary_items = _merge_note_items(
        explained_to_patient,
        lifestyle_guidance,
        home_care,
        limit=6,
    )

    summary_cards = [
        {
            "label": "主訴",
            "value": _short_note_text(
                chief_complaint_label if chief_complaint_label != "-" else soap_view["S"],
            ),
            "tone": "blue",
        },
        {
            "label": "評価",
            "value": _short_note_text(assessment_items),
            "tone": "orange",
        },
        {
            "label": "施術方針",
            "value": _short_note_text(plan_items),
            "tone": "green",
        },
        {
            "label": "次回確認",
            "value": _short_note_text(next_check_items),
            "tone": "purple",
        },
        {
            "label": "注意点",
            "value": _short_note_text(caution_summary_items),
            "tone": "red",
        },
    ]

    related_plan = (
        TreatmentPlan.objects
        .filter(
            patient=note.patient,
            patient__clinic=clinic,
        )
        .filter(
            Q(clinical_note=note)
            | Q(appointment=note.appointment)
        )
        .order_by("-is_active", "-created_at")
        .first()
    )
    related_posture_assessment = (
        PostureAssessment.objects
        .filter(
            clinic=clinic,
            patient=note.patient,
        )
        .filter(
            Q(clinical_note=note)
            | Q(appointment=note.appointment)
        )
        .order_by("-created_at")
        .first()
    )
    if related_posture_assessment is None:
        related_posture_assessment = (
            PostureAssessment.objects
            .filter(clinic=clinic, patient=note.patient)
            .order_by("-created_at")
            .first()
        )

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
        "summary_cards": summary_cards,
        "assessment_items": assessment_items,
        "plan_items": plan_items,
        "treatment_summary_items": treatment_summary_items,
        "next_check_items": next_check_items,
        "caution_summary_items": caution_summary_items,
        "guidance_summary_items": guidance_summary_items,
        "ai_summary_text": ai_summary_text,
        "related_plan": related_plan,
        "related_posture_assessment": related_posture_assessment,

        "is_treatment_session_note": is_treatment_session_note,
        "source_label": source_label,
        "source_badge_class": source_badge_class,
        "source_session_available": source_session_available,
        "source_recording_available": source_recording_available,

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
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のカルテのみ閲覧できます。")

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
        appointment__clinic=clinic,
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
    if (
        clinic is None
        or not getattr(request.user, "clinic_id", None)
        or request.user.clinic_id != clinic.id
    ):
        return HttpResponseForbidden("所属院のカルテのみ編集できます。")

    note = get_object_or_404(
        ClinicalNote,
        id=note_id,
        patient__clinic=clinic,
        appointment__clinic=clinic,
    )

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
