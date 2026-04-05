"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),

    # トップ：患者/管理者の分岐ホーム
    path("", TemplateView.as_view(template_name="home.html"), name="home"),

    # スタッフ（病院側）
    path("staff/", include(("apps.staff.urls", "staff"), namespace="staff")),

    # 既存
    path("visits/", include(("apps.visits.urls", "visits"), namespace="visits")),
    
    path("patients/", include(("apps.patients.urls", "patients"), namespace="patients")),
    
    path("intakes/", include(("apps.intakes.urls", "intakes"), namespace="intakes")),
    
    path("treatment_plans/", include(("apps.treatment_plans.urls"), namespace="treatment_plans")),

]

