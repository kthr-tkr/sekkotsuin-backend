# apps/patients/urls.py
from django.urls import path
from . import views
from django.contrib.auth import views as auth_views
from django.urls import reverse_lazy

from .forms import PatientPasswordResetForm, PatientSetPasswordForm

app_name = "patients"

urlpatterns = [
    path("login/", views.patient_login_view, name="login"),
    path("register/", views.patient_register_view, name="register"),
    path("register/complete/", views.patient_register_complete_view, name="register_complete"),
    path("logout/", views.patient_logout_view, name="logout"),
    path("dashboard/", views.patient_dashboard_view, name="dashboard"),
    path("session/ping/", views.patient_session_ping_view, name="session_ping"),

    # 予約（A: カレンダー→日→枠）
    path("booking/", views.booking_calendar_view, name="booking_calendar"),
    path("booking/day/<str:ymd>/", views.booking_day_view, name="booking_day"),
    path("booking/confirm/", views.booking_confirm_view, name="booking_confirm"),
    path("booking/complete/<int:appointment_id>/", views.booking_complete_view, name="booking_complete"),
    path("booking/review/", views.booking_review_view, name="booking_review"),

    # 自分の予約
    path("appointments/", views.patient_my_appointments_view, name="my_appointments"),
    path("profile/", views.patient_profile_view, name="profile"),
    path("appointments/<int:appointment_id>/cancel/", views.appointment_cancel_view, name="appointment_cancel"),
    path("staff-booking/<int:patient_id>/", views.staff_booking_calendar_view, name="staff_booking_calendar"),
    path("staff-booking/<int:patient_id>/<str:ymd>/", views.staff_booking_day_view, name="staff_booking_day"),
    path("staff-booking/<int:patient_id>/confirm/", views.staff_booking_confirm_view, name="staff_booking_confirm"),

    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="patients/auth/password_reset_form.html",
            email_template_name="patients/auth/password_reset_email.txt",
            subject_template_name="patients/auth/password_reset_subject.txt",
            success_url=reverse_lazy("patients:password_reset_done"),
            form_class=PatientPasswordResetForm,
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="patients/auth/password_reset_done.html",
        ),
        name="password_reset_done",
    ),
    path(
        "reset/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="patients/auth/password_reset_confirm.html",
            success_url=reverse_lazy("patients:password_reset_complete"),
            form_class=PatientSetPasswordForm,
        ),
        name="password_reset_confirm",
    ),
    path(
        "reset/done/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="patients/auth/password_reset_complete.html",
        ),
        name="password_reset_complete",
    ),
    
    path("inquiry/", views.patient_inquiry_view, name="inquiry"),
    path("inquiry/done/", views.patient_inquiry_done_view, name="inquiry_done"),
]
