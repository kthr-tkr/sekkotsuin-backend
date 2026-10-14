# apps/appointments/urls.py
from django.urls import path
from . import patient_views

app_name = "appointments"

urlpatterns = [
    # ...既存（staff側など）...

    path("book/", patient_views.book_start, name="book_start"),
    path("book/new/", patient_views.book_new, name="book_new"),
    path("book/complete/<int:appointment_id>/", patient_views.book_complete, name="book_complete"),
    path("book/<int:appointment_id>/intake/", patient_views.book_intake, name="book_intake"),
]
