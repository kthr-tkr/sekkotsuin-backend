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
    path("kpi/", views.staff_kpi_dashboard_view, name="kpi_dashboard"),
    path(
        "ai-usage/",
        views.staff_ai_usage_dashboard_view,
        name="ai_usage_dashboard",
    ),

    # 予約管理
    path("appointments/", staff_appointments_view, name="appointments"),
    path("appointments/<int:pk>/status/", staff_appointment_status_update_view, name="appointment_status"),

    # 旧問診一覧は予約管理へ案内し、予約に紐づく問診詳細は維持する。
    path("intake/", staff_intake_list_view, name="intake"),
    path("intake/<int:pk>/", staff_intake_detail_view, name="intake_detail"),
    
        # ★追加：診察（AI Interview）
    path("interview/<int:appointment_id>/", views.staff_interview_view, name="interview"),
    
    path("patients/", views.staff_patient_search_view, name="patient_search"),
    path("staff/", views.staff_list, name="staff_list"),
    path(
        "settings/members/",
        views.staff_list,
        name="staff_member_list",
    ),
    path("manual/", views.staff_manual_view, name="manual"),
    path("settings/", views.staff_settings_view, name="settings"),
    path(
        "settings/clinic/",
        views.staff_clinic_settings_view,
        name="clinic_settings",
    ),
    path(
        "settings/treatment-menus/",
        views.staff_treatment_menu_list_view,
        name="treatment_menu_list",
    ),
    path(
        "settings/treatment-menus/new/",
        views.staff_treatment_menu_create_view,
        name="treatment_menu_create",
    ),
    path(
        "settings/treatment-menus/<int:menu_id>/edit/",
        views.staff_treatment_menu_update_view,
        name="treatment_menu_update",
    ),
    path(
        "settings/treatment-menus/<int:menu_id>/toggle/",
        views.staff_treatment_menu_toggle_view,
        name="treatment_menu_toggle",
    ),
    path("sales/", views.staff_sales_record_list_view, name="sales_record_list"),
    path("sales/new/", views.staff_sales_record_create_view, name="sales_record_create"),
    path(
        "sales/<int:record_id>/edit/",
        views.staff_sales_record_update_view,
        name="sales_record_update",
    ),
    path("recordings/<int:recording_id>/register/", views.register_clinical_note, name="register_clinical_note"),
    path("clinical_notes/<int:pk>/", views.staff_clinical_note_detail_view, name="clinical_note_detail"),
    path(
        "clinical-notes/<int:note_id>/post-summary/",
        views.staff_post_treatment_summary_view,
        name="post_treatment_summary",
    ),
    path(
        "clinical-notes/<int:note_id>/aftercare-report/",
        views.staff_patient_aftercare_report_view,
        name="patient_aftercare_report",
    ),
    path(
        "clinical-notes/<int:note_id>/share/create/",
        views.staff_patient_share_token_create_view,
        name="patient_share_token_create",
    ),
    path(
        "clinical-notes/<int:note_id>/share/<int:share_id>/revoke/",
        views.staff_patient_share_token_revoke_view,
        name="patient_share_token_revoke",
    ),
    path(
        "share-tokens/<int:share_id>/qr/",
        views.staff_patient_share_token_qr_view,
        name="patient_share_token_qr",
    ),
    path("patients/<int:patient_id>/", views.staff_patient_detail_view, name="patient_detail"),
    path(
        "patients/<int:patient_id>/pre-check/",
        views.staff_pre_treatment_check_view,
        name="pre_treatment_check",
    ),
    path("clinical_notes/<int:note_id>/edit/", views.staff_clinical_note_edit, name="clinical_note_edit"),
    path(
        "api/appointments/create/",
        views.staff_appointment_create_api,
        name="appointment_create_api",
    ),
    path(
        "api/appointments/<int:pk>/update/",
        views.staff_appointment_update_api,
        name="appointment_update_api",
    ),
    path(
        "appointments/api/available-slots/",
        views.staff_appointment_available_slots_api,
        name="appointment_available_slots_api",
    ),
    path("api/appointments/<int:pk>/move/", views.move_appointment_view, name="appointment_move"),
    path("staffs/create/", views.staff_create, name="staff_create"),
    path(
        "settings/members/new/",
        views.staff_create,
        name="staff_member_create",
    ),
    path(
        "settings/members/<int:staff_id>/edit/",
        views.staff_member_update_view,
        name="staff_member_update",
    ),
    path(
        "settings/members/<int:staff_id>/toggle/",
        views.staff_member_toggle_view,
        name="staff_member_toggle",
    ),
    path("shifts/", views.staff_shift_month_view, name="staff_shift_month"),
    path("shifts/new/", views.staff_shift_create_view, name="staff_shift_create"),
    path(
        "shifts/<int:shift_id>/edit/",
        views.staff_shift_update_view,
        name="staff_shift_update",
    ),
    path("leaves/", views.staff_leave_list_view, name="staff_leave_list"),
    path("leaves/new/", views.staff_leave_create_view, name="staff_leave_create"),
    path(
        "leaves/<int:leave_id>/edit/",
        views.staff_leave_update_view,
        name="staff_leave_update",
    ),
    path(
        "clinical_notes/<int:pk>/print/",
        views.staff_clinical_note_print_view,
        name="clinical_note_print",
    ),
]
