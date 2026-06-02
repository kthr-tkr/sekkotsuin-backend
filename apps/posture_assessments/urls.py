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
]