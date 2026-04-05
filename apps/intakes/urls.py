from django.urls import path
from . import views

app_name = "intakes"

urlpatterns = [
    # 患者：問診開始・分岐
    path("appointment/<int:appointment_id>/start/", views.intake_start_view, name="intake_start"),

    # 患者：同じ症状の簡易問診
    path("appointment/<int:appointment_id>/followup/", views.intake_followup_view, name="intake_followup"),

    # 患者：通常4ステップ問診
    path("appointment/<int:appointment_id>/", views.intake_wizard, name="intake"),

    # 患者：完了
    path("appointment/<int:appointment_id>/done/", views.intake_done, name="intake_done"),

    # スタッフ（1画面編集）
    path("staff/appointment/<int:appointment_id>/", views.intake_staff_edit, name="intake_staff_edit"),

    path("staff/appointments/<int:appointment_id>/record/", views.record_page, name="record_page"),
    path("staff/recordings/<int:recording_id>/upload/", views.upload_recording, name="upload_recording"),
    path("staff/recordings/<int:recording_id>/process/", views.process_recording, name="process_recording"),
    path("staff/recordings/<int:recording_id>/", views.recording_detail, name="recording_detail"),
    path("staff/appointments/<int:appointment_id>/recording/new/", views.recording_new, name="recording_new"),
    path("staff/recordings/<int:recording_id>/confirm/", views.recording_confirm, name="recording_confirm"),
]