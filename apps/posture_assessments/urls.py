from django.urls import path

from . import views

app_name = "posture_assessments"

urlpatterns = [
    path(
        "patients/<int:patient_id>/",
        views.posture_list_view,
        name="list",
    ),
    path(
        "patients/<int:patient_id>/new/",
        views.posture_create_view,
        name="create",
    ),
    path(
        "patients/<int:patient_id>/comparisons/",
        views.posture_comparison_list_view,
        name="comparison_list",
    ),
    path(
        "patients/<int:patient_id>/comparisons/new/",
        views.posture_comparison_create_view,
        name="comparison_create",
    ),
    path(
        "<int:assessment_id>/",
        views.posture_detail_view,
        name="detail",
    ),
    path(
        "<int:assessment_id>/upload/",
        views.posture_upload_images_view,
        name="upload",
    ),
    path(
        "<int:assessment_id>/analyze/",
        views.posture_assessment_analyze_view,
        name="analyze",
    ),
    path(
        "<int:assessment_id>/delete/",
        views.posture_delete_view,
        name="delete",
    ),
    path(
        "comparisons/<int:comparison_id>/",
        views.posture_comparison_detail_view,
        name="comparison_detail",
    ),
    path(
        "comparisons/<int:comparison_id>/report/",
        views.posture_comparison_report_view,
        name="comparison_report",
    ),
    path(
        "comparisons/<int:comparison_id>/analyze/",
        views.posture_comparison_analyze_view,
        name="comparison_analyze",
    ),
    path(
        "images/<int:image_id>/landmarks/save/",
        views.posture_image_landmarks_save_view,
        name="image_landmarks_save",
    ),
]
