from django.urls import path

from . import views

app_name = "treatment_sessions"

urlpatterns = [
    path(
        "appointments/<int:appointment_id>/start/",
        views.treatment_session_start_view,
        name="start",
    ),
    path(
        "patients/<int:patient_id>/start/",
        views.treatment_session_start_for_patient_view,
        name="start_for_patient",
    ),
    path(
        "<int:session_id>/",
        views.treatment_session_detail_view,
        name="detail",
    ),
]