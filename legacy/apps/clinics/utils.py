from django.core.exceptions import ImproperlyConfigured
from apps.clinics.models import Clinic


def get_single_clinic_or_raise():
    clinic = Clinic.objects.order_by("id").first()
    if not clinic:
        raise ImproperlyConfigured(
            "Clinic が未作成です。bootstrap_single_clinic を実行してください。"
        )
    return clinic


def get_current_clinic():
    """
    単院版では常に唯一の Clinic を返す。
    将来 SaaS 化する場合は、この関数の中身を差し替える。
    """
    return get_single_clinic_or_raise()