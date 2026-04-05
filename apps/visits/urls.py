from django.urls import path
from . import views

app_name = "visits"

urlpatterns = [
    path("", views.visit_list, name="list"),  # ←追加
    path("<int:pk>/", views.visit_detail, name="detail"),
    path("<int:pk>/ai-draft/", views.visit_ai_draft, name="ai_draft"),
    path("<int:pk>/note-save/", views.note_save, name="note_save"),
    path("<int:pk>/note-finalize/", views.note_finalize, name="note_finalize"),
]
