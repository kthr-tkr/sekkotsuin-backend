"""
URL configuration for config project.
"""
from django.contrib import admin
from django.http import JsonResponse
from django.urls import path, include
from django.views.generic import TemplateView


def health_check(request):
    return JsonResponse({"status": "ok"})


urlpatterns = [
    path("admin/", admin.site.urls),

    # ヘルスチェック
    path("health/", health_check, name="health"),

    # トップ：患者/管理者の分岐ホーム
    path("", TemplateView.as_view(template_name="home.html"), name="home"),

    # 公開ページ
    path("terms/", TemplateView.as_view(template_name="terms.html"), name="terms"),
    path("privacy/", TemplateView.as_view(template_name="privacy.html"), name="privacy"),
    path("feedback/", TemplateView.as_view(template_name="feedback_form.html"), name="feedback_form"),

    # スタッフ（病院側）
    path("staff/", include(("apps.staff.urls", "staff"), namespace="staff")),

    # 既存
    path("visits/", include(("apps.visits.urls", "visits"), namespace="visits")),
    path("patients/", include(("apps.patients.urls", "patients"), namespace="patients")),
    path("intakes/", include(("apps.intakes.urls", "intakes"), namespace="intakes")),
    path("treatment_plans/", include(("apps.treatment_plans.urls", "apps.treatment_plans"), namespace="treatment_plans")),
]