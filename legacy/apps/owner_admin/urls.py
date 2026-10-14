from django.urls import path

from . import views

app_name = "owner_admin"

urlpatterns = [
    path("", views.owner_dashboard, name="dashboard"),
    path("clinics/", views.owner_clinic_list, name="clinic_list"),
    path("clinics/new/", views.owner_clinic_create, name="clinic_create"),
    path("clinics/<int:clinic_id>/", views.owner_clinic_detail, name="clinic_detail"),
    path("clinics/<int:clinic_id>/edit/", views.owner_clinic_edit, name="clinic_edit"),
    path(
        "clinics/<int:clinic_id>/settings/",
        views.owner_clinic_settings,
        name="clinic_settings",
    ),
    path("clinics/<int:clinic_id>/plan/", views.owner_clinic_plan, name="clinic_plan"),
    path(
        "clinics/<int:clinic_id>/staff/new/",
        views.owner_clinic_staff_create,
        name="clinic_staff_create",
    ),
]
