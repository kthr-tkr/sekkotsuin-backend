from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.appointments.models import Appointment
from apps.patients.models import Patient
from apps.staff.decorators import staff_required
from apps.staff.views import get_current_clinic

import json

from django.http import JsonResponse

from .forms import (
    PostureAssessmentCreateForm,
    PostureAssessmentImageUploadForm,
    PostureComparisonCreateForm,
)
from .models import (
    PostureAssessment,
    PostureAssessmentImage,
    PostureComparison,
)

from django.views.decorators.http import require_POST

from .services.ai_analyzer import (
    analyze_posture_assessment,
    analyze_posture_comparison,
)
from .services.comparison_builder import build_posture_comparison_json
from .services.image_converter import normalize_posture_image

from .services.measurements import build_measurements_for_image

LANDMARK_KEYS_BY_IMAGE_TYPE = {
    PostureAssessmentImage.ImageType.FRONT: {
        "nose",
        "chin",
        "left_ear",
        "right_ear",
        "left_shoulder",
        "right_shoulder",
        "left_elbow",
        "right_elbow",
        "left_wrist",
        "right_wrist",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
        "left_foot",
        "right_foot",
        "left_big_toe",
        "right_big_toe",
    },
    PostureAssessmentImage.ImageType.SIDE_RIGHT: {
        "ear",
        "shoulder",
        "elbow",
        "wrist",
        "hip",
        "knee",
        "ankle",
        "heel",
        "toe",
    },
    PostureAssessmentImage.ImageType.BACK: {
        "head_center",
        "neck_center",
        "left_shoulder",
        "right_shoulder",
        "left_scapula",
        "right_scapula",
        "spine_upper",
        "spine_mid",
        "spine_lower",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
        "left_heel",
        "right_heel",
    },
}

REQUIRED_LANDMARK_KEYS_BY_IMAGE_TYPE = {
    PostureAssessmentImage.ImageType.FRONT: {
        "left_shoulder",
        "right_shoulder",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
    },
    PostureAssessmentImage.ImageType.SIDE_RIGHT: {
        "ear",
        "shoulder",
        "hip",
        "knee",
        "ankle",
    },
    PostureAssessmentImage.ImageType.BACK: {
        "head_center",
        "left_shoulder",
        "right_shoulder",
        "left_hip",
        "right_hip",
        "left_knee",
        "right_knee",
        "left_ankle",
        "right_ankle",
    },
}

def _same_clinic(user, clinic) -> bool:
    user_clinic = getattr(user, "clinic", None)

    if user.is_superuser and user_clinic is None:
        return True

    return user_clinic == clinic


@staff_required
def posture_list_view(request, patient_id):
    clinic = get_current_clinic(request)

    patient = get_object_or_404(
        Patient.objects.select_related("clinic"),
        pk=patient_id,
        clinic=clinic,
    )

    assessments = (
        PostureAssessment.objects
        .filter(clinic=clinic, patient=patient)
        .prefetch_related("images")
        .order_by("-created_at")
    )

    latest_assessment = assessments.first()

    return render(request, "posture_assessments/list.html", {
        "active": "patient_search",
        "page_title": "AI姿勢分析",
        "patient": patient,
        "assessments": assessments,
        "latest_assessment": latest_assessment,
    })


@staff_required
def posture_create_view(request, patient_id):
    clinic = get_current_clinic(request)

    patient = get_object_or_404(
        Patient.objects.select_related("clinic"),
        pk=patient_id,
        clinic=clinic,
    )

    now = timezone.now()

    appointment = (
        Appointment.objects
        .filter(
            clinic=clinic,
            patient=patient,
            start_at__gte=now,
        )
        .order_by("start_at")
        .first()
    )

    if appointment is None:
        appointment = (
            Appointment.objects
            .filter(
                clinic=clinic,
                patient=patient,
            )
            .order_by("-start_at")
            .first()
        )

    if request.method == "POST":
        form = PostureAssessmentCreateForm(request.POST)
        upload_form = PostureAssessmentImageUploadForm(request.POST, request.FILES)

        if form.is_valid() and upload_form.is_valid():
            assessment = form.save(commit=False)
            assessment.clinic = clinic
            assessment.patient = patient
            assessment.appointment = appointment
            assessment.status = PostureAssessment.Status.DRAFT
            assessment.created_by = request.user
            assessment.updated_by = request.user
            assessment.full_clean()
            assessment.save()

            try:
                _save_uploaded_images(
                    assessment=assessment,
                    upload_form=upload_form,
                    user=request.user,
                )
            except ValueError as e:
                assessment.delete()
                messages.error(request, str(e))
                return render(request, "posture_assessments/form.html", {
                    "active": "patient_search",
                    "page_title": "AI姿勢分析作成",
                    "patient": patient,
                    "appointment": appointment,
                    "form": form,
                    "upload_form": upload_form,
                })

            messages.success(request, "AI姿勢分析を作成しました。")
            return redirect("posture_assessments:detail", assessment_id=assessment.id)

        messages.error(request, "入力内容を確認してください。")

    else:
        form = PostureAssessmentCreateForm(initial={
            "title": "AI姿勢分析",
        })
        upload_form = PostureAssessmentImageUploadForm()

    return render(request, "posture_assessments/form.html", {
        "active": "patient_search",
        "page_title": "AI姿勢分析作成",
        "patient": patient,
        "appointment": appointment,
        "form": form,
        "upload_form": upload_form,
    })


def _normalize_assessment_summary(summary):
    summary = summary or {}
    if not summary:
        return {}

    posture_findings = {
        **(summary.get("posture_findings") or {}),
    }
    ankle_foot = (
        posture_findings.get("ankle_foot")
        or posture_findings.get("foot")
        or ""
    )
    posture_findings["ankle_foot"] = ankle_foot
    posture_findings["foot"] = ankle_foot

    view_summaries = summary.get("view_summaries") or {}
    joint_assessments = summary.get("joint_assessments") or {}
    alignment_observations = summary.get("alignment_observations") or {}

    return {
        **summary,
        "important_points": summary.get("important_points") or [],
        "overall_summary": summary.get("overall_summary") or "",
        "view_summaries": {
            "front": view_summaries.get("front") or "",
            "side_right": view_summaries.get("side_right") or "",
            "back": view_summaries.get("back") or "",
        },
        "posture_findings": posture_findings,
        "joint_assessments": joint_assessments,
        "alignment_observations": {
            "frontal_plane": (
                alignment_observations.get("frontal_plane") or []
            ),
            "sagittal_plane": (
                alignment_observations.get("sagittal_plane") or []
            ),
            "posterior_view": (
                alignment_observations.get("posterior_view") or []
            ),
            "center_of_gravity": (
                alignment_observations.get("center_of_gravity") or []
            ),
        },
        "symptom_relation_hypotheses": (
            summary.get("symptom_relation_hypotheses") or []
        ),
        "suspected_load_areas": summary.get("suspected_load_areas") or [],
        "clinical_notes": summary.get("clinical_notes") or [],
        "treatment_suggestions": summary.get("treatment_suggestions") or [],
        "home_care_suggestions": summary.get("home_care_suggestions") or [],
        "next_check_points": summary.get("next_check_points") or [],
        "risk_notes": summary.get("risk_notes") or [],
        "patient_explanation": summary.get("patient_explanation") or "",
        "report_summary_for_patient": (
            summary.get("report_summary_for_patient")
            or summary.get("patient_explanation")
            or ""
        ),
    }


def _build_view_summary_cards(summary):
    view_summaries = summary.get("view_summaries") or {}
    return [
        {
            "key": "front",
            "label": "正面評価",
            "text": view_summaries.get("front") or "新しいAI分析後に表示されます。",
        },
        {
            "key": "side_right",
            "label": "右側面評価",
            "text": (
                view_summaries.get("side_right")
                or "新しいAI分析後に表示されます。"
            ),
        },
        {
            "key": "back",
            "label": "背面評価",
            "text": view_summaries.get("back") or "新しいAI分析後に表示されます。",
        },
    ]


def _build_joint_assessment_cards(summary):
    joint_assessments = summary.get("joint_assessments") or {}
    specs = [
        ("head", "頭部"),
        ("neck", "頚部"),
        ("shoulder", "肩・肩甲帯"),
        ("thoracic_spine", "胸椎・胸郭"),
        ("lumbar_pelvis", "腰椎・骨盤帯"),
        ("hip", "股関節"),
        ("knee", "膝関節"),
        ("ankle_foot", "足関節・足部"),
    ]

    cards = []
    for key, label in specs:
        item = joint_assessments.get(key) or {}
        cards.append({
            "key": key,
            "label": label,
            "summary": item.get("summary") or "新しいAI分析後に表示されます。",
            "possible_findings": item.get("possible_findings") or [],
            "check_points": item.get("check_points") or [],
        })

    return cards


def _build_alignment_groups(summary):
    observations = summary.get("alignment_observations") or {}
    return [
        {
            "key": "frontal_plane",
            "label": "前額面・正面",
            "items": observations.get("frontal_plane") or [],
        },
        {
            "key": "sagittal_plane",
            "label": "矢状面・右側面",
            "items": observations.get("sagittal_plane") or [],
        },
        {
            "key": "posterior_view",
            "label": "背面",
            "items": observations.get("posterior_view") or [],
        },
        {
            "key": "center_of_gravity",
            "label": "重心・荷重",
            "items": observations.get("center_of_gravity") or [],
        },
    ]


def _build_assessment_image_cards(images):
    image_map = {
        image.image_type: image
        for image in images
    }

    return [
        {
            "key": PostureAssessmentImage.ImageType.FRONT,
            "label": "正面",
            "description": "肩・骨盤・膝の左右差を確認します",
            "image": image_map.get(PostureAssessmentImage.ImageType.FRONT),
        },
        {
            "key": PostureAssessmentImage.ImageType.SIDE_RIGHT,
            "label": "右側面",
            "description": "頭部前方位や体幹の傾向を確認します",
            "image": image_map.get(PostureAssessmentImage.ImageType.SIDE_RIGHT),
        },
        {
            "key": PostureAssessmentImage.ImageType.BACK,
            "label": "背面",
            "description": "背面から肩・骨盤・重心の傾向を確認します",
            "image": image_map.get(PostureAssessmentImage.ImageType.BACK),
        },
    ]


def _build_assessment_score_context(summary):
    if not summary:
        return {
            "has_score": False,
            "score": None,
            "label": "未算出",
            "note": "AI分析後に、姿勢の確認ポイント数から参考値を表示します。",
            "important_count": 0,
            "risk_count": 0,
            "load_count": 0,
        }

    important_count = len(summary.get("important_points") or [])
    risk_count = len(summary.get("risk_notes") or [])
    load_count = len(summary.get("suspected_load_areas") or [])
    has_home_care = bool(summary.get("home_care_suggestions"))
    has_next_checks = bool(summary.get("next_check_points"))
    support_bonus = (3 if has_home_care else 0) + (3 if has_next_checks else 0)
    score = (
        86
        - important_count * 5
        - risk_count * 4
        - load_count * 2
        + support_bonus
    )
    score = round(max(35, min(95, score)))

    if score >= 76:
        label = "安定傾向"
    elif score >= 60:
        label = "確認ポイントあり"
    else:
        label = "要確認"

    return {
        "has_score": True,
        "score": score,
        "label": label,
        "note": "AI分析結果の重要ポイントや注意事項の数から作成した参考値です。診断ではありません。",
        "important_count": important_count,
        "risk_count": risk_count,
        "load_count": load_count,
        "has_home_care": has_home_care,
        "has_next_checks": has_next_checks,
    }


def _build_assessment_report_steps(summary):
    steps = []

    for item in summary.get("treatment_suggestions") or []:
        steps.append({
            "title": "姿勢改善・施術方針",
            "text": item,
            "source": "treatment",
        })

    for item in summary.get("next_check_points") or []:
        steps.append({
            "title": "次回の確認ポイント",
            "text": item,
            "source": "next_check",
        })

    fallback_steps = [
        {
            "title": "Step1 痛み・負担の管理",
            "text": "痛みや違和感の出方を確認し、日常生活で負担が強くなりやすい動きを整理します。",
            "source": "fallback",
        },
        {
            "title": "Step2 姿勢改善・筋肉ケア",
            "text": "姿勢の傾向に合わせて、筋肉や関節の状態を施術者の評価と合わせて確認します。",
            "source": "fallback",
        },
        {
            "title": "Step3 再発予防・パフォーマンスアップ",
            "text": "生活習慣や動作のくせを確認し、良い状態を保ちやすい体づくりを目指します。",
            "source": "fallback",
        },
    ]

    for fallback_step in fallback_steps:
        if len(steps) >= 3:
            break
        steps.append(fallback_step)

    return steps[:3]


def _build_assessment_load_mechanisms(summary):
    items = []

    for item in summary.get("symptom_relation_hypotheses") or []:
        items.append({
            "label": "症状との関連仮説",
            "text": item,
        })

    for joint_label, joint in [
        ("頭部・首", (summary.get("joint_assessments") or {}).get("head") or {}),
        ("頚部", (summary.get("joint_assessments") or {}).get("neck") or {}),
        ("肩・肩甲帯", (summary.get("joint_assessments") or {}).get("shoulder") or {}),
        ("胸椎・胸郭", (summary.get("joint_assessments") or {}).get("thoracic_spine") or {}),
        ("腰椎・骨盤", (summary.get("joint_assessments") or {}).get("lumbar_pelvis") or {}),
        ("股関節", (summary.get("joint_assessments") or {}).get("hip") or {}),
        ("膝", (summary.get("joint_assessments") or {}).get("knee") or {}),
        ("足関節・足部", (summary.get("joint_assessments") or {}).get("ankle_foot") or {}),
    ]:
        for finding in joint.get("possible_findings") or []:
            items.append({
                "label": joint_label,
                "text": finding,
            })

    for item in summary.get("clinical_notes") or []:
        items.append({
            "label": "施術者の確認事項",
            "text": item,
        })

    return items[:8]


def _shorten_body_map_text(value, fallback, limit=38):
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
        text = f"{text[:limit - 1].rstrip()}…"
    return text


def _build_assessment_body_map_items(summary):
    posture_findings = summary.get("posture_findings") or {}
    joint_assessments = summary.get("joint_assessments") or {}
    suspected_load_areas = [
        str(item).strip()
        for item in summary.get("suspected_load_areas") or []
        if str(item).strip()
    ]
    symptom_hypotheses = [
        str(item).strip()
        for item in summary.get("symptom_relation_hypotheses") or []
        if str(item).strip()
    ]
    part_specs = (
        {
            "key": "head_neck",
            "label": "頭・首",
            "column": "left",
            "joints": ("head", "neck"),
            "keywords": ("頭", "首", "頚"),
            "fallback": "頭・首の位置関係を確認します",
        },
        {
            "key": "shoulder",
            "label": "肩",
            "column": "right",
            "joints": ("shoulder",),
            "keywords": ("肩", "肩甲"),
            "fallback": "肩の高さや左右差を確認します",
        },
        {
            "key": "spine",
            "label": "背中",
            "column": "left",
            "joints": ("thoracic_spine",),
            "keywords": ("背", "胸椎", "脊柱"),
            "fallback": "背中のラインを確認します",
        },
        {
            "key": "pelvis",
            "label": "骨盤",
            "column": "right",
            "joints": ("lumbar_pelvis", "hip"),
            "keywords": ("骨盤", "腰", "股関節", "臀"),
            "fallback": "骨盤の傾きや左右差を確認します",
        },
        {
            "key": "knee",
            "label": "膝",
            "column": "left",
            "joints": ("knee",),
            "keywords": ("膝",),
            "fallback": "膝の向きや負担を確認します",
        },
        {
            "key": "ankle_foot",
            "label": "足部",
            "column": "right",
            "joints": ("ankle_foot",),
            "keywords": ("足", "足首", "足関節", "踵"),
            "fallback": "足部の向きや荷重を確認します",
        },
    )
    check_words = (
        "負担",
        "左右差",
        "傾き",
        "偏位",
        "前方",
        "過伸展",
        "確認が必要",
        "注意",
    )
    good_words = ("良好", "安定", "整って", "改善", "目立たない")

    body_map_items = []
    for spec in part_specs:
        related_loads = [
            item
            for item in suspected_load_areas
            if any(keyword in item for keyword in spec["keywords"])
        ]
        related_hypotheses = [
            item
            for item in symptom_hypotheses
            if any(keyword in item for keyword in spec["keywords"])
        ]

        source_text = posture_findings.get(spec["key"])
        if not source_text:
            for joint_key in spec["joints"]:
                joint = joint_assessments.get(joint_key) or {}
                source_text = (
                    joint.get("summary")
                    or joint.get("possible_findings")
                )
                if source_text:
                    break
        if not source_text and related_hypotheses:
            source_text = related_hypotheses[0]
        if not source_text and related_loads:
            source_text = related_loads[0]

        text = _shorten_body_map_text(source_text, spec["fallback"])
        combined_text = " ".join(
            [text, *related_loads, *related_hypotheses]
        )
        if related_loads or any(
            word in combined_text for word in check_words
        ):
            level = "check"
        elif any(word in combined_text for word in good_words):
            level = "good"
        else:
            level = "info"

        body_map_items.append({
            "key": spec["key"],
            "label": spec["label"],
            "text": text,
            "level": level,
            "column": spec["column"],
        })

    return body_map_items


@staff_required
def posture_detail_view(request, assessment_id):
    clinic = get_current_clinic(request)

    assessment = get_object_or_404(
        PostureAssessment.objects
        .select_related(
            "clinic",
            "patient",
            "appointment",
            "treatment_session",
            "clinical_note",
            "created_by",
            "confirmed_by",
            "updated_by",
        )
        .prefetch_related("images"),
        pk=assessment_id,
        clinic=clinic,
    )

    images = assessment.images.all()

    image_map = {
        image.image_type: image
        for image in images
    }

    summary = _normalize_assessment_summary(assessment.get_active_summary() or {})
    important_points = summary.get("important_points") or []
    posture_findings = summary.get("posture_findings") or {}
    recommended_checks = summary.get("recommended_checks") or []
    next_action = summary.get("next_action") or []
    image_cards = _build_assessment_image_cards(images)
    assessment_score = _build_assessment_score_context(summary)
    view_summary_cards = _build_view_summary_cards(summary)
    joint_assessment_cards = _build_joint_assessment_cards(summary)
    alignment_groups = _build_alignment_groups(summary)

    return render(request, "posture_assessments/detail.html", {
        "active": "patient_search",
        "page_title": "AI姿勢分析詳細",
        "assessment": assessment,
        "patient": assessment.patient,
        "images": images,
        "image_map": image_map,
        "summary": summary,
        "important_points": important_points,
        "posture_findings": posture_findings,
        "recommended_checks": recommended_checks,
        "next_action": next_action,
        "image_cards": image_cards,
        "assessment_score": assessment_score,
        "view_summary_cards": view_summary_cards,
        "joint_assessment_cards": joint_assessment_cards,
        "alignment_groups": alignment_groups,
    })


@staff_required
def posture_assessment_report_view(request, assessment_id):
    clinic = get_current_clinic(request)

    assessment = get_object_or_404(
        PostureAssessment.objects
        .select_related(
            "clinic",
            "patient",
            "appointment",
            "treatment_session",
            "clinical_note",
            "created_by",
            "confirmed_by",
            "updated_by",
        )
        .prefetch_related("images"),
        pk=assessment_id,
        clinic=clinic,
    )

    images = assessment.images.all()
    image_map = {
        image.image_type: image
        for image in images
    }
    summary = _normalize_assessment_summary(
        assessment.get_active_summary() or {}
    )
    image_cards = _build_assessment_image_cards(images)
    assessment_score = _build_assessment_score_context(summary)
    view_summary_cards = _build_view_summary_cards(summary)
    alignment_groups = _build_alignment_groups(summary)
    report_steps = _build_assessment_report_steps(summary)
    load_mechanisms = _build_assessment_load_mechanisms(summary)
    body_map_items = _build_assessment_body_map_items(summary)
    home_care_items = summary.get("home_care_suggestions") or [
        "スタッフの指示に合わせて、無理のない範囲で行ってください。",
    ]
    risk_notes = summary.get("risk_notes") or [
        "画像の評価は撮影角度、立ち位置、服装、カメラ距離の影響を受ける可能性があります。",
        "本レポートは診断ではなく、施術者の評価を補助する参考情報です。",
        "痛みやしびれが強い場合は、画像だけで判断せずスタッフへ相談してください。",
    ]
    report_summary = (
        summary.get("report_summary_for_patient")
        or summary.get("patient_explanation")
        or summary.get("overall_summary")
        or "AI分析後に、姿勢の特徴と今後の改善方針を患者さん向けに表示します。"
    )
    patient_message = (
        summary.get("patient_explanation")
        or summary.get("report_summary_for_patient")
        or "姿勢の状態は、日常の動きや症状と合わせて確認することが大切です。無理のない範囲で、一緒に良い変化を目指していきましょう。"
    )

    return render(request, "posture_assessments/assessment_report.html", {
        "active": "patient_search",
        "page_title": "姿勢評価レポート / 改善プラン",
        "assessment": assessment,
        "patient": assessment.patient,
        "patient_age": _get_patient_age(assessment.patient),
        "patient_gender": _get_patient_gender_display(assessment.patient),
        "report_created_at": timezone.now(),
        "images": images,
        "image_map": image_map,
        "image_cards": image_cards,
        "summary": summary,
        "assessment_score": assessment_score,
        "view_summary_cards": view_summary_cards,
        "alignment_groups": alignment_groups,
        "report_steps": report_steps,
        "load_mechanisms": load_mechanisms,
        "body_map_items": body_map_items,
        "home_care_items": home_care_items,
        "risk_notes": risk_notes,
        "report_summary": report_summary,
        "patient_message": patient_message,
    })


@staff_required
def posture_upload_images_view(request, assessment_id):
    clinic = get_current_clinic(request)

    assessment = get_object_or_404(
        PostureAssessment.objects.select_related("clinic", "patient"),
        pk=assessment_id,
        clinic=clinic,
    )

    if request.method != "POST":
        return redirect("posture_assessments:detail", assessment_id=assessment.id)

    upload_form = PostureAssessmentImageUploadForm(request.POST, request.FILES)

    if upload_form.is_valid():
        try:
            _save_uploaded_images(
                assessment=assessment,
                upload_form=upload_form,
                user=request.user,
            )

            assessment.updated_by = request.user
            assessment.save(update_fields=["updated_by", "updated_at"])

            messages.success(request, "姿勢画像を更新しました。")

        except ValueError as e:
            messages.error(request, str(e))
    else:
        messages.error(request, "画像のアップロードに失敗しました。")

    return redirect("posture_assessments:detail", assessment_id=assessment.id)


def _save_uploaded_images(assessment, upload_form, user):
    cd = upload_form.cleaned_data

    image_specs = [
        ("front_image", PostureAssessmentImage.ImageType.FRONT, 1),
        ("side_right_image", PostureAssessmentImage.ImageType.SIDE_RIGHT, 2),
        ("back_image", PostureAssessmentImage.ImageType.BACK, 3),
    ]

    for field_name, image_type, order in image_specs:
        image_file = cd.get(field_name)
        if not image_file:
            continue

        # 先に変換する。失敗した場合、既存画像は消さない。
        normalized_image = normalize_posture_image(image_file)

        # 変換成功後に同じ種類の画像を差し替え
        PostureAssessmentImage.objects.filter(
            assessment=assessment,
            image_type=image_type,
        ).delete()

        PostureAssessmentImage.objects.create(
            assessment=assessment,
            image_type=image_type,
            image=normalized_image,
            order=order,
            uploaded_by=user,
        )

@staff_required
@require_POST
def posture_assessment_analyze_view(request, assessment_id):
    import traceback

    clinic = get_current_clinic(request)

    assessment = get_object_or_404(
        PostureAssessment.objects
        .select_related(
            "clinic",
            "patient",
            "appointment",
            "treatment_session",
            "clinical_note",
        )
        .prefetch_related("images"),
        pk=assessment_id,
        clinic=clinic,
    )

    if not assessment.images.exists():
        messages.error(request, "姿勢分析用の画像が登録されていません。")
        return redirect("posture_assessments:detail", assessment_id=assessment.id)

    try:
        assessment.status = PostureAssessment.Status.ANALYZING
        assessment.ai_error_message = ""
        assessment.updated_by = request.user
        assessment.save(update_fields=[
            "status",
            "ai_error_message",
            "updated_by",
            "updated_at",
        ])

        result = analyze_posture_assessment(assessment)

        meta = result.get("meta", {}) if isinstance(result, dict) else {}
        model_name = meta.get("model", "")

        assessment.ai_summary_json = result
        assessment.ai_model_name = model_name
        assessment.status = PostureAssessment.Status.ANALYZED
        assessment.ai_error_message = ""
        assessment.analyzed_at = timezone.now()
        assessment.updated_by = request.user

        assessment.save(update_fields=[
            "ai_summary_json",
            "ai_model_name",
            "status",
            "ai_error_message",
            "analyzed_at",
            "updated_by",
            "updated_at",
        ])

        messages.success(request, "AI姿勢分析が完了しました。")

    except Exception as e:
        error_text = str(e)[:1200]

        print("===== posture assessment analyze error =====")
        print(traceback.format_exc())

        try:
            assessment.status = PostureAssessment.Status.FAILED
            assessment.ai_error_message = error_text
            assessment.updated_by = request.user
            assessment.save(update_fields=[
                "status",
                "ai_error_message",
                "updated_by",
                "updated_at",
            ])
        except Exception:
            print("===== failed to save posture assessment error state =====")
            print(traceback.format_exc())

        messages.error(request, f"AI姿勢分析に失敗しました: {error_text}")

    return redirect("posture_assessments:detail", assessment_id=assessment.id)

@staff_required
def posture_comparison_list_view(request, patient_id):
    clinic = get_current_clinic(request)

    patient = get_object_or_404(
        Patient.objects.select_related("clinic"),
        pk=patient_id,
        clinic=clinic,
    )

    comparisons = (
        PostureComparison.objects
        .filter(
            clinic=clinic,
            patient=patient,
        )
        .select_related(
            "before_assessment",
            "after_assessment",
            "created_by",
            "updated_by",
        )
        .prefetch_related(
            "before_assessment__images",
            "after_assessment__images",
        )
        .order_by("-created_at")
    )

    latest_comparison = comparisons.first()

    return render(request, "posture_assessments/comparison_list.html", {
        "active": "patient_search",
        "page_title": "姿勢比較分析一覧",
        "patient": patient,
        "comparisons": comparisons,
        "latest_comparison": latest_comparison,
    })

@staff_required
def posture_comparison_create_view(request, patient_id):
    clinic = get_current_clinic(request)

    patient = get_object_or_404(
        Patient.objects.select_related("clinic"),
        pk=patient_id,
        clinic=clinic,
    )

    assessments = (
        PostureAssessment.objects
        .filter(
            clinic=clinic,
            patient=patient,
        )
        .prefetch_related("images")
        .order_by("-created_at")
    )

    if assessments.count() < 2:
        messages.warning(request, "Before/After比較には、姿勢分析が2件以上必要です。")
        return redirect("posture_assessments:list", patient_id=patient.id)

    if request.method == "POST":
        before_id = request.POST.get("before_assessment")
        after_id = request.POST.get("after_assessment")
        title = request.POST.get("title") or "姿勢Before/After比較"
        memo = request.POST.get("memo") or ""

        if not before_id or not after_id:
            messages.error(request, "BeforeとAfterを選択してください。")
            return redirect("posture_assessments:list", patient_id=patient.id)

        if before_id == after_id:
            messages.error(request, "BeforeとAfterには別の姿勢分析を選択してください。")
            return redirect("posture_assessments:list", patient_id=patient.id)

        before_assessment = get_object_or_404(
            PostureAssessment,
            pk=before_id,
            clinic=clinic,
            patient=patient,
        )

        after_assessment = get_object_or_404(
            PostureAssessment,
            pk=after_id,
            clinic=clinic,
            patient=patient,
        )

        comparison = PostureComparison(
            clinic=clinic,
            patient=patient,
            title=title,
            before_assessment=before_assessment,
            after_assessment=after_assessment,
            memo=memo,
            status=PostureComparison.Status.DRAFT,
            created_by=request.user,
            updated_by=request.user,
        )

        comparison.full_clean()
        comparison.save()

        messages.success(request, "Before/After比較を作成しました。")
        return redirect(
            "posture_assessments:comparison_detail",
            comparison_id=comparison.id,
        )

    form = PostureComparisonCreateForm(
        clinic=clinic,
        patient=patient,
        initial={
            "title": "姿勢Before/After比較",
        },
    )

    return render(request, "posture_assessments/comparison_form.html", {
        "active": "patient_search",
        "page_title": "姿勢Before/After比較作成",
        "patient": patient,
        "form": form,
        "assessments": assessments,
    })


def _normalize_comparison_summary(summary):
    summary = summary or {}
    if not summary:
        return {}

    return {
        **summary,
        "improved_points": summary.get("improved_points") or [],
        "unchanged_points": summary.get("unchanged_points") or [],
        "important_changes": summary.get("important_changes") or [],
        "overall_comparison_summary": (
            summary.get("overall_comparison_summary")
            or summary.get("overall_summary")
            or ""
        ),
        "worsened_or_remaining_points": (
            summary.get("worsened_or_remaining_points")
            or summary.get("worse_or_attention_points")
            or []
        ),
        "clinical_check_points": (
            summary.get("clinical_check_points")
            or summary.get("clinical_notes")
            or []
        ),
        "next_session_check_points": (
            summary.get("next_session_check_points")
            or summary.get("next_focus")
            or []
        ),
        "measurement_based_findings": (
            summary.get("measurement_based_findings") or []
        ),
        "treatment_focus_suggestions": (
            summary.get("treatment_focus_suggestions") or []
        ),
        "home_care_suggestions": (
            summary.get("home_care_suggestions") or []
        ),
        "risk_notes": summary.get("risk_notes") or [],
        "patient_explanation": summary.get("patient_explanation") or "",
    }


def _build_report_image_pairs(comparison):
    before_image_map = {
        image.image_type: image
        for image in comparison.before_assessment.images.all()
    }
    after_image_map = {
        image.image_type: image
        for image in comparison.after_assessment.images.all()
    }

    return [
        {
            "key": PostureAssessmentImage.ImageType.FRONT,
            "label": "正面",
            "before": before_image_map.get(PostureAssessmentImage.ImageType.FRONT),
            "after": after_image_map.get(PostureAssessmentImage.ImageType.FRONT),
        },
        {
            "key": PostureAssessmentImage.ImageType.SIDE_RIGHT,
            "label": "右側面",
            "before": before_image_map.get(PostureAssessmentImage.ImageType.SIDE_RIGHT),
            "after": after_image_map.get(PostureAssessmentImage.ImageType.SIDE_RIGHT),
        },
        {
            "key": PostureAssessmentImage.ImageType.BACK,
            "label": "背面",
            "before": before_image_map.get(PostureAssessmentImage.ImageType.BACK),
            "after": after_image_map.get(PostureAssessmentImage.ImageType.BACK),
        },
    ]


def _build_comparison_overview_context(comparison):
    image_type_labels = {
        PostureAssessmentImage.ImageType.FRONT: "正面",
        PostureAssessmentImage.ImageType.SIDE_RIGHT: "右側面",
        PostureAssessmentImage.ImageType.BACK: "背面",
    }
    measurement_labels = {
        "shoulder_slope_deg": ("肩の傾き", "°"),
        "pelvis_slope_deg": ("骨盤の傾き", "°"),
        "left_knee_medial_shift_pct": ("左膝の内外側偏位", "%"),
        "right_knee_medial_shift_pct": ("右膝の内外側偏位", "%"),
        "forward_head_shift_pct": ("頭部前方偏位", "%"),
        "ear_shoulder_angle_deg": ("耳・肩角度", "°"),
        "trunk_lean_deg": ("体幹傾斜", "°"),
        "back_shoulder_slope_deg": ("肩の傾き", "°"),
        "back_pelvis_slope_deg": ("骨盤の傾き", "°"),
        "head_to_pelvis_center_shift_pct": ("頭部・骨盤中心偏位", "%"),
    }
    trend_labels = {
        "improved": "改善傾向",
        "worsened": "要確認",
        "unchanged": "大きな変化なし",
        "unknown": "判定保留",
    }
    trend_counts = {
        "improved": 0,
        "worsened": 0,
        "unchanged": 0,
        "unknown": 0,
    }
    trend_rows = {
        "improved": [],
        "worsened": [],
        "unchanged": [],
        "unknown": [],
    }
    comparison_diff_groups = []

    for image_type, items in (
        (comparison.comparison_json or {}).get("items") or {}
    ).items():
        rows = []

        for key, values in items.items():
            label, unit = measurement_labels.get(key, (key, ""))
            trend = values.get("trend") or "unknown"
            if trend not in trend_counts:
                trend = "unknown"
            trend_counts[trend] += 1
            row = {
                "key": key,
                "label": label,
                "unit": unit,
                "before": values.get("before"),
                "after": values.get("after"),
                "delta": values.get("delta"),
                "trend": trend,
                "trend_label": trend_labels.get(
                    trend,
                    trend_labels["unknown"],
                ),
            }
            rows.append(row)
            trend_rows[trend].append({
                **row,
                "image_type": image_type,
                "image_label": image_type_labels.get(image_type, image_type),
            })

        if rows:
            comparison_diff_groups.append({
                "image_type": image_type,
                "label": image_type_labels.get(image_type, image_type),
                "rows": rows,
            })

    known_trend_count = (
        trend_counts["improved"]
        + trend_counts["worsened"]
        + trend_counts["unchanged"]
    )
    posture_score = None
    posture_score_label = "未算出"

    if known_trend_count:
        score = 50 + (
            (trend_counts["improved"] - trend_counts["worsened"])
            / known_trend_count
            * 50
        )
        posture_score = round(max(0, min(100, score)))

        if posture_score >= 65:
            posture_score_label = "改善傾向"
        elif posture_score >= 45:
            posture_score_label = "安定傾向"
        else:
            posture_score_label = "要確認"

    score_summary = {
        "before": 50 if posture_score is not None else None,
        "after": posture_score,
        "delta": posture_score - 50 if posture_score is not None else None,
        "delta_class": "neutral",
        "delta_label": "未算出",
    }

    if score_summary["delta"] is not None:
        if score_summary["delta"] > 0:
            score_summary["delta_class"] = "up"
            score_summary["delta_label"] = f"+{score_summary['delta']}pt"
        elif score_summary["delta"] < 0:
            score_summary["delta_class"] = "down"
            score_summary["delta_label"] = f"{score_summary['delta']}pt"
        else:
            score_summary["delta_label"] = "±0pt"

    return comparison_diff_groups, {
        "trend_counts": trend_counts,
        "trend_rows": trend_rows,
        "score": posture_score,
        "has_score": posture_score is not None,
        "score_label": posture_score_label,
        "score_summary": score_summary,
        "measurement_count": sum(trend_counts.values()),
    }


def _get_patient_age(patient):
    birth_date = getattr(patient, "birth_date", None)
    if not birth_date:
        return None

    today = timezone.localdate()
    return (
        today.year
        - birth_date.year
        - ((today.month, today.day) < (birth_date.month, birth_date.day))
    )


def _get_patient_gender_display(patient):
    if hasattr(patient, "get_gender_display"):
        return patient.get_gender_display()
    if hasattr(patient, "get_sex_display"):
        return patient.get_sex_display()
    return getattr(patient, "gender", "") or getattr(patient, "sex", "") or ""


@staff_required
def posture_comparison_detail_view(request, comparison_id):
    clinic = get_current_clinic(request)

    comparison = get_object_or_404(
        PostureComparison.objects
        .select_related(
            "clinic",
            "patient",
            "before_assessment",
            "after_assessment",
            "created_by",
            "confirmed_by",
            "updated_by",
        )
        .prefetch_related(
            "before_assessment__images",
            "after_assessment__images",
        ),
        pk=comparison_id,
        clinic=clinic,
    )

    before_images = comparison.before_assessment.images.all()
    after_images = comparison.after_assessment.images.all()

    before_image_map = {
        image.image_type: image
        for image in before_images
    }

    after_image_map = {
        image.image_type: image
        for image in after_images
    }

    measurement_specs = {
        PostureAssessmentImage.ImageType.FRONT: [
            ("shoulder_slope_deg", "肩の傾き", "°"),
            ("pelvis_slope_deg", "骨盤の傾き", "°"),
            ("left_knee_medial_shift_pct", "左膝の内外側偏位", "%"),
            ("right_knee_medial_shift_pct", "右膝の内外側偏位", "%"),
        ],
        PostureAssessmentImage.ImageType.SIDE_RIGHT: [
            ("forward_head_shift_pct", "頭部前方偏位", "%"),
            ("ear_shoulder_angle_deg", "耳・肩角度", "°"),
            ("trunk_lean_deg", "体幹傾斜", "°"),
        ],
        PostureAssessmentImage.ImageType.BACK: [
            ("back_shoulder_slope_deg", "肩の傾き", "°"),
            ("back_pelvis_slope_deg", "骨盤の傾き", "°"),
            ("head_to_pelvis_center_shift_pct", "頭部・骨盤中心偏位", "%"),
        ],
    }

    def build_measurement_rows(image):
        if not image:
            return []

        items = (image.measurements_json or {}).get("items") or {}
        return [
            {
                "key": key,
                "label": label,
                "unit": unit,
                "display_value": (
                    "未計測"
                    if items.get(key) is None
                    else f"{items[key]}{unit}"
                ),
            }
            for key, label, unit in measurement_specs.get(image.image_type, [])
        ]

    image_pairs = [
        {
            "key": PostureAssessmentImage.ImageType.FRONT,
            "label": "正面",
            "before": before_image_map.get(PostureAssessmentImage.ImageType.FRONT),
            "after": after_image_map.get(PostureAssessmentImage.ImageType.FRONT),
        },
        {
            "key": PostureAssessmentImage.ImageType.SIDE_RIGHT,
            "label": "右側面",
            "before": before_image_map.get(PostureAssessmentImage.ImageType.SIDE_RIGHT),
            "after": after_image_map.get(PostureAssessmentImage.ImageType.SIDE_RIGHT),
        },
        {
            "key": PostureAssessmentImage.ImageType.BACK,
            "label": "背面",
            "before": before_image_map.get(PostureAssessmentImage.ImageType.BACK),
            "after": after_image_map.get(PostureAssessmentImage.ImageType.BACK),
        },
    ]

    for pair in image_pairs:
        before_image = pair["before"]
        after_image = pair["after"]
        pair["before_landmarks_script_id"] = (
            f"posture-landmarks-{before_image.id}" if before_image else ""
        )
        pair["after_landmarks_script_id"] = (
            f"posture-landmarks-{after_image.id}" if after_image else ""
        )
        pair["before_measurement_rows"] = build_measurement_rows(before_image)
        pair["after_measurement_rows"] = build_measurement_rows(after_image)

    image_type_labels = {
        PostureAssessmentImage.ImageType.FRONT: "正面",
        PostureAssessmentImage.ImageType.SIDE_RIGHT: "右側面",
        PostureAssessmentImage.ImageType.BACK: "背面",
    }
    measurement_labels = {
        key: (label, unit)
        for specs in measurement_specs.values()
        for key, label, unit in specs
    }
    trend_labels = {
        "improved": "改善傾向",
        "worsened": "要確認",
        "unchanged": "大きな変化なし",
        "unknown": "判定保留",
    }
    trend_counts = {
        "improved": 0,
        "worsened": 0,
        "unchanged": 0,
        "unknown": 0,
    }
    comparison_diff_groups = []

    for image_type, items in (
        (comparison.comparison_json or {}).get("items") or {}
    ).items():
        rows = []

        for key, values in items.items():
            label, unit = measurement_labels.get(key, (key, ""))
            trend = values.get("trend") or "unknown"
            if trend not in trend_counts:
                trend = "unknown"
            trend_counts[trend] += 1
            rows.append({
                "key": key,
                "label": label,
                "unit": unit,
                "before": values.get("before"),
                "after": values.get("after"),
                "delta": values.get("delta"),
                "trend": trend,
                "trend_label": trend_labels.get(
                    trend,
                    trend_labels["unknown"],
                ),
            })

        if rows:
            comparison_diff_groups.append({
                "image_type": image_type,
                "label": image_type_labels.get(image_type, image_type),
                "rows": rows,
            })

    known_trend_count = (
        trend_counts["improved"]
        + trend_counts["worsened"]
        + trend_counts["unchanged"]
    )
    posture_score = None
    posture_score_label = "未算出"

    if known_trend_count:
        score = 50 + (
            (trend_counts["improved"] - trend_counts["worsened"])
            / known_trend_count
            * 50
        )
        posture_score = round(max(0, min(100, score)))

        if posture_score >= 65:
            posture_score_label = "改善傾向"
        elif posture_score >= 45:
            posture_score_label = "安定傾向"
        else:
            posture_score_label = "要確認"

    comparison_overview = {
        "trend_counts": trend_counts,
        "score": posture_score,
        "has_score": posture_score is not None,
        "score_label": posture_score_label,
        "measurement_count": sum(trend_counts.values()),
    }

    summary = comparison.get_active_summary() or {}
    if summary:
        summary = {
            **summary,
            "overall_comparison_summary": (
                summary.get("overall_comparison_summary")
                or summary.get("overall_summary")
                or ""
            ),
            "worsened_or_remaining_points": (
                summary.get("worsened_or_remaining_points")
                or summary.get("worse_or_attention_points")
                or []
            ),
            "clinical_check_points": (
                summary.get("clinical_check_points")
                or summary.get("clinical_notes")
                or []
            ),
            "next_session_check_points": (
                summary.get("next_session_check_points")
                or summary.get("next_focus")
                or []
            ),
            "measurement_based_findings": (
                summary.get("measurement_based_findings") or []
            ),
            "treatment_focus_suggestions": (
                summary.get("treatment_focus_suggestions") or []
            ),
            "home_care_suggestions": (
                summary.get("home_care_suggestions") or []
            ),
        }

    return render(request, "posture_assessments/comparison_detail.html", {
        "active": "patient_search",
        "page_title": "姿勢Before/After比較詳細",
        "comparison": comparison,
        "patient": comparison.patient,
        "before_assessment": comparison.before_assessment,
        "after_assessment": comparison.after_assessment,
        "image_pairs": image_pairs,
        "comparison_diff_groups": comparison_diff_groups,
        "comparison_overview": comparison_overview,
        "summary": summary,
    })


@staff_required
def posture_comparison_report_view(request, comparison_id):
    clinic = get_current_clinic(request)

    comparison = get_object_or_404(
        PostureComparison.objects
        .select_related(
            "clinic",
            "patient",
            "before_assessment",
            "after_assessment",
            "created_by",
            "updated_by",
        )
        .prefetch_related(
            "before_assessment__images",
            "after_assessment__images",
        ),
        pk=comparison_id,
        clinic=clinic,
    )

    image_pairs = _build_report_image_pairs(comparison)
    comparison_diff_groups, comparison_overview = _build_comparison_overview_context(
        comparison
    )
    summary = _normalize_comparison_summary(comparison.get_active_summary() or {})

    pair_trend_map = {}
    for group in comparison_diff_groups:
        counts = {
            "improved": 0,
            "worsened": 0,
            "unchanged": 0,
            "unknown": 0,
        }
        for row in group["rows"]:
            trend = row.get("trend") or "unknown"
            if trend not in counts:
                trend = "unknown"
            counts[trend] += 1

        if counts["worsened"]:
            trend = "worsened"
            trend_label = "確認が必要"
        elif counts["improved"]:
            trend = "improved"
            trend_label = "改善傾向"
        elif counts["unchanged"]:
            trend = "unchanged"
            trend_label = "大きな変化なし"
        elif counts["unknown"]:
            trend = "unknown"
            trend_label = "判定保留"
        else:
            trend = "unknown"
            trend_label = "未計測"

        pair_trend_map[group["image_type"]] = {
            "trend": trend,
            "trend_label": trend_label,
        }

    for pair in image_pairs:
        pair.update(pair_trend_map.get(pair["key"], {
            "trend": "unknown",
            "trend_label": "未計測",
        }))

    comparison_period_days = None
    if comparison.before_assessment.created_at and comparison.after_assessment.created_at:
        before_date = timezone.localtime(
            comparison.before_assessment.created_at
        ).date()
        after_date = timezone.localtime(
            comparison.after_assessment.created_at
        ).date()
        comparison_period_days = (after_date - before_date).days

    ai_steps = []
    for text in summary.get("treatment_focus_suggestions") or []:
        ai_steps.append({
            "title": "施術フォーカス",
            "text": text,
        })

    for text in summary.get("next_session_check_points") or []:
        ai_steps.append({
            "title": "次回確認",
            "text": text,
        })

    fallback_steps = [
        {
            "title": "Step1 痛み・負担の管理",
            "text": "痛みや違和感の出方を確認し、日常生活で負担が強くなりやすい動きを整理します。",
        },
        {
            "title": "Step2 姿勢改善・筋肉ケア",
            "text": "姿勢の傾向に合わせて、筋肉の緊張や関節の動きを無理のない範囲で整えていきます。",
        },
        {
            "title": "Step3 再発予防・パフォーマンスアップ",
            "text": "動作のくせや生活習慣を確認し、良い状態を保ちやすい体づくりを目指します。",
        },
    ]

    for fallback_step in fallback_steps:
        if len(ai_steps) >= 3:
            break
        ai_steps.append(fallback_step)

    home_care_items = summary.get("home_care_suggestions") or [
        "スタッフの指示に合わせて、無理のない範囲で行ってください。",
    ]

    risk_notes = summary.get("risk_notes") or [
        "画像評価は撮影角度・立ち位置・服装・カメラ距離の影響を受けるため、施術者の評価と合わせて判断します。",
        "数値は診断ではなく、姿勢の傾向を確認するための参考情報です。",
        "痛みや神経症状が強い場合は、画像だけで判断せず詳しい確認が必要です。",
    ]

    return render(request, "posture_assessments/comparison_report.html", {
        "active": "patient_search",
        "page_title": "姿勢評価レポート",
        "comparison": comparison,
        "patient": comparison.patient,
        "patient_age": _get_patient_age(comparison.patient),
        "patient_gender": _get_patient_gender_display(comparison.patient),
        "report_created_at": timezone.now(),
        "before_assessment": comparison.before_assessment,
        "after_assessment": comparison.after_assessment,
        "image_pairs": image_pairs,
        "summary": summary,
        "comparison_json": comparison.comparison_json or {},
        "comparison_diff_groups": comparison_diff_groups,
        "comparison_overview": comparison_overview,
        "comparison_period_days": comparison_period_days,
        "score_summary": comparison_overview["score_summary"],
        "report_steps": ai_steps[:3],
        "home_care_items": home_care_items,
        "risk_notes": risk_notes,
    })


@staff_required
@require_POST
def posture_comparison_analyze_view(request, comparison_id):
    import traceback

    clinic = get_current_clinic(request)

    comparison = get_object_or_404(
        PostureComparison.objects
        .select_related(
            "clinic",
            "patient",
            "before_assessment",
            "after_assessment",
        )
        .prefetch_related(
            "before_assessment__images",
            "after_assessment__images",
        ),
        pk=comparison_id,
        clinic=clinic,
    )

    if not comparison.before_assessment.images.exists():
        messages.error(request, "Before側の姿勢画像が登録されていません。")
        return redirect("posture_assessments:comparison_detail", comparison_id=comparison.id)

    if not comparison.after_assessment.images.exists():
        messages.error(request, "After側の姿勢画像が登録されていません。")
        return redirect("posture_assessments:comparison_detail", comparison_id=comparison.id)

    try:
        comparison.comparison_json = build_posture_comparison_json(comparison)
        comparison.status = PostureComparison.Status.ANALYZING
        comparison.ai_error_message = ""
        comparison.updated_by = request.user
        comparison.save(update_fields=[
            "comparison_json",
            "status",
            "ai_error_message",
            "updated_by",
            "updated_at",
        ])

        result = analyze_posture_comparison(comparison)

        meta = result.get("meta", {}) if isinstance(result, dict) else {}
        model_name = meta.get("model", "")

        comparison.ai_summary_json = result
        comparison.ai_model_name = model_name
        comparison.status = PostureComparison.Status.ANALYZED
        comparison.ai_error_message = ""
        comparison.analyzed_at = timezone.now()
        comparison.updated_by = request.user

        comparison.save(update_fields=[
            "ai_summary_json",
            "ai_model_name",
            "status",
            "ai_error_message",
            "analyzed_at",
            "updated_by",
            "updated_at",
        ])

        messages.success(request, "AI姿勢比較分析が完了しました。")

    except Exception as e:
        error_text = str(e)[:1200]

        print("===== posture comparison analyze error =====")
        print(traceback.format_exc())

        try:
            comparison.status = PostureComparison.Status.FAILED
            comparison.ai_error_message = error_text
            comparison.updated_by = request.user
            comparison.save(update_fields=[
                "status",
                "ai_error_message",
                "updated_by",
                "updated_at",
            ])
        except Exception:
            print("===== failed to save posture comparison error state =====")
            print(traceback.format_exc())

        messages.error(request, f"AI姿勢比較分析に失敗しました: {error_text}")

    return redirect("posture_assessments:comparison_detail", comparison_id=comparison.id)

@staff_required
@require_POST
def posture_delete_view(request, assessment_id):
    clinic = get_current_clinic(request)

    assessment = get_object_or_404(
        PostureAssessment.objects
        .select_related("clinic", "patient")
        .prefetch_related("images"),
        pk=assessment_id,
        clinic=clinic,
    )

    patient_id = assessment.patient_id
    title = assessment.title

    assessment.delete()

    messages.success(request, f"姿勢分析「{title}」を削除しました。")
    return redirect("posture_assessments:list", patient_id=patient_id)

@staff_required
@require_POST
def posture_image_landmarks_save_view(request, image_id):
    clinic = get_current_clinic(request)

    image = get_object_or_404(
        PostureAssessmentImage.objects.select_related(
            "assessment",
            "assessment__clinic",
            "assessment__patient",
        ),
        pk=image_id,
        assessment__clinic=clinic,
    )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except json.JSONDecodeError:
        return JsonResponse({
            "ok": False,
            "message": "JSONの形式が正しくありません。",
        }, status=400)

    points = payload.get("points") or {}

    allowed_keys = LANDMARK_KEYS_BY_IMAGE_TYPE.get(
        image.image_type,
        set(),
    )

    required_keys = REQUIRED_LANDMARK_KEYS_BY_IMAGE_TYPE.get(
        image.image_type,
        set(),
    )

    if not allowed_keys:
        return JsonResponse({
            "ok": False,
            "message": "この画像種別はランドマーク保存に対応していません。",
        }, status=400)

    cleaned_points = {}

    for key, value in points.items():
        if key not in allowed_keys:
            continue

        if not isinstance(value, dict):
            continue

        try:
            x = float(value.get("x"))
            y = float(value.get("y"))
        except (TypeError, ValueError):
            continue

        if x < 0 or x > 100 or y < 0 or y > 100:
            continue

        cleaned_points[key] = {
            "x": round(x, 2),
            "y": round(y, 2),
        }

    if not required_keys.issubset(cleaned_points.keys()):
        missing = sorted(required_keys - cleaned_points.keys())

        return JsonResponse({
            "ok": False,
            "message": f"必要なランドマークが不足しています: {', '.join(missing)}",
        }, status=400)

    image.landmarks_json = {
        "version": 2,
        "mode": payload.get("mode") or "manual",
        "image_type": image.image_type,
        "unit": "percent",
        "points": cleaned_points,
        "updated_by": request.user.id,
        "updated_at": timezone.now().isoformat(),
    }

    try:
        image_width = image.image.width
        image_height = image.image.height
    except Exception:
        image_width = None
        image_height = None

    image.measurements_json = build_measurements_for_image(
        image_type=image.image_type,
        points=cleaned_points,
        image_width=image_width,
        image_height=image_height,
    )

    image.save(update_fields=[
        "landmarks_json",
        "measurements_json",
    ])

    return JsonResponse({
        "ok": True,
        "message": "姿勢ラインを保存しました。",
        "landmarks": image.landmarks_json,
        "measurements": image.measurements_json,
    })
