# apps/patients/urls.py
from django.urls import path
from . import views

app_name = "patients"

urlpatterns = [
    path("login/", views.patient_login_view, name="login"),
    path("register/", views.patient_register_view, name="register"),
    path("register/complete/", views.patient_register_complete_view, name="register_complete"),
    path("logout/", views.patient_logout_view, name="logout"),
    path("dashboard/", views.patient_dashboard_view, name="dashboard"),

    # 予約（A: カレンダー→日→枠）
    path("booking/", views.booking_calendar_view, name="booking_calendar"),
    path("booking/day/<str:ymd>/", views.booking_day_view, name="booking_day"),
    path("booking/confirm/", views.booking_confirm_view, name="booking_confirm"),
    path("booking/complete/<int:appointment_id>/", views.booking_complete_view, name="booking_complete"),

    # 自分の予約
    path("appointments/", views.patient_my_appointments_view, name="my_appointments"),
    path("profile/", views.patient_profile_view, name="profile"),
    path("appointments/<int:appointment_id>/cancel/", views.appointment_cancel_view, name="appointment_cancel"),
    path("staff-booking/<int:patient_id>/", views.staff_booking_calendar_view, name="staff_booking_calendar"),
    path("staff-booking/<int:patient_id>/<str:ymd>/", views.staff_booking_day_view, name="staff_booking_day"),
    path("staff-booking/<int:patient_id>/confirm/", views.staff_booking_confirm_view, name="staff_booking_confirm"),

]
