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
        "<int:session_id>/chunks/upload/",
        views.upload_session_chunk_view,
        name="upload_chunk",
    ),
    path(
        "chunks/<int:chunk_id>/transcribe/",
        views.transcribe_session_chunk_view,
        name="transcribe_chunk",
    ),
    path(
        "<int:session_id>/summarize/",
        views.summarize_treatment_session_view,
        name="summarize",
    ),
    path(
        "<int:session_id>/register-clinical-note/",
        views.register_treatment_session_note_view,
        name="register_clinical_note",
    ),
    path(
        "<int:session_id>/",
        views.treatment_session_detail_view,
        name="detail",
    ),
]