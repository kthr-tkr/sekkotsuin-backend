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
from .services.image_converter import normalize_posture_image

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

    summary = assessment.get_active_summary() or {}
    important_points = summary.get("important_points") or []
    posture_findings = summary.get("posture_findings") or {}
    recommended_checks = summary.get("recommended_checks") or []
    next_action = summary.get("next_action") or []

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
        .select_related("clinic", "patient")
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

    def serialize_landmarks(image):
        if not image:
            return "{}"

        return json.dumps(
            image.landmarks_json or {},
            ensure_ascii=False,
        )

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
        pair["before_landmarks_json"] = serialize_landmarks(pair["before"])
        pair["after_landmarks_json"] = serialize_landmarks(pair["after"])

    summary = comparison.get_active_summary() or {}

    return render(request, "posture_assessments/comparison_detail.html", {
        "active": "patient_search",
        "page_title": "姿勢Before/After比較詳細",
        "comparison": comparison,
        "patient": comparison.patient,
        "before_assessment": comparison.before_assessment,
        "after_assessment": comparison.after_assessment,
        "image_pairs": image_pairs,
        "summary": summary,
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
        comparison.status = PostureComparison.Status.ANALYZING
        comparison.ai_error_message = ""
        comparison.updated_by = request.user
        comparison.save(update_fields=[
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

    allowed_keys = {
        "ear",
        "shoulder",
        "hip",
        "knee",
        "ankle",
    }

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

    required_keys = {"ear", "shoulder", "hip", "knee", "ankle"}

    if not required_keys.issubset(cleaned_points.keys()):
        return JsonResponse({
            "ok": False,
            "message": "耳・肩・骨盤・膝・足首の5点が必要です。",
        }, status=400)

    image.landmarks_json = {
        "version": 1,
        "mode": "manual",
        "image_type": image.image_type,
        "points": cleaned_points,
        "updated_by": request.user.id,
        "updated_at": timezone.now().isoformat(),
    }
    image.save(update_fields=["landmarks_json"])

    return JsonResponse({
        "ok": True,
        "message": "姿勢ラインを保存しました。",
        "landmarks": image.landmarks_json,
    })