# apps/staff/urls.py
from django.urls import path
from .views import (
    staff_login_view,
    staff_dashboard_view,
    staff_appointments_view,
    staff_appointment_status_update_view,
    staff_intake_list_view,
    staff_intake_detail_view,
)
from django.contrib.auth.views import LogoutView

from . import views

app_name = "staff"

urlpatterns = [
    path("login/", staff_login_view, name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),

    path("dashboard/", staff_dashboard_view, name="dashboard"),

    # 予約管理
    path("appointments/", staff_appointments_view, name="appointments"),
    path("appointments/<int:pk>/status/", staff_appointment_status_update_view, name="appointment_status"),

    # 問診
    path("intake/", staff_intake_list_view, name="intake"),
    path("intake/<int:pk>/", staff_intake_detail_view, name="intake_detail"),
    
        # ★追加：診察（AI Interview）
    path("interview/<int:appointment_id>/", views.staff_interview_view, name="interview"),
    
    path("patients/", views.staff_patient_search_view, name="patient_search"),
    path("staff/", views.staff_list, name="staff_list"),
    path("manual/", views.staff_manual_view, name="manual"),
    path("settings/", views.staff_settings_view, name="settings"),
    path("recordings/<int:recording_id>/register/", views.register_clinical_note, name="register_clinical_note"),
    path("clinical_notes/<int:pk>/", views.staff_clinical_note_detail_view, name="clinical_note_detail"),
    path("patients/<int:patient_id>/", views.staff_patient_detail_view, name="patient_detail"),
    path("clinical_notes/<int:note_id>/edit/", views.staff_clinical_note_edit, name="clinical_note_edit"),
    path("api/appointments/<int:pk>/move/", views.move_appointment_view, name="appointment_move"),
    path("staffs/create/", views.staff_create, name="staff_create"),
    path(
        "clinical_notes/<int:pk>/print/",
        views.staff_clinical_note_print_view,
        name="clinical_note_print",
    ),
]
