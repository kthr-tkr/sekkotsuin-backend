from django.urls import path
from . import views

app_name = "treatment_plans"

urlpatterns = [
    path("create/patient/<int:patient_id>/", views.plan_create_view, name="plan_create_for_patient"),
    path("create/appointment/<int:appointment_id>/", views.plan_create_view, name="plan_create_for_appointment"),
    path("<int:pk>/", views.plan_detail_view, name="plan_detail"),
    path("<int:pk>/progress/create/", views.progress_create_view, name="progress_create"),
    path("<int:pk>/edit/", views.plan_edit_view, name="plan_edit"),
    path("<int:pk>/status/", views.plan_status_update_view, name="plan_status_update"),
    path("progress/<int:pk>/edit/", views.progress_edit_view, name="progress_edit"),
    path("progress/<int:pk>/delete/", views.progress_delete_view, name="progress_delete"),
    path(
        "create/clinical-note/<int:clinical_note_id>/",
        views.plan_create_from_clinical_note_view,
        name="plan_create_from_clinical_note",
    ),
]

