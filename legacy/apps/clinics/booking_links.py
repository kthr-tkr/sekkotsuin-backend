from urllib.parse import urlencode

from django.urls import reverse

from apps.appointments.models import Appointment


PUBLIC_BOOKING_SOURCES = (
    Appointment.BookingSource.HP,
    Appointment.BookingSource.LINE,
    Appointment.BookingSource.GOOGLE,
    Appointment.BookingSource.INSTAGRAM,
    Appointment.BookingSource.QR,
    Appointment.BookingSource.FLYER,
    Appointment.BookingSource.REFERRAL,
    Appointment.BookingSource.SMS,
    Appointment.BookingSource.EMAIL,
)

BOOKING_SOURCE_LABELS = dict(Appointment.BookingSource.choices)


def normalize_booking_source(value, *, default=Appointment.BookingSource.UNKNOWN):
    source = str(value or "").strip().lower()
    allowed = {choice[0] for choice in Appointment.BookingSource.choices}
    return source if source in allowed else default


def clinic_booking_path(clinic, source=None):
    if not getattr(clinic, "booking_slug", ""):
        return ""
    path = reverse("clinic_booking_entry", args=[clinic.booking_slug])
    source = normalize_booking_source(source, default="")
    if source:
        return f"{path}?{urlencode({'source': source})}"
    return path


def clinic_booking_url(request, clinic, source=None):
    path = clinic_booking_path(clinic, source=source)
    return request.build_absolute_uri(path) if path else ""


def clinic_booking_link_rows(request, clinic):
    rows = []
    for source in PUBLIC_BOOKING_SOURCES:
        rows.append({
            "source": source,
            "label": BOOKING_SOURCE_LABELS.get(source, source),
            "url": clinic_booking_url(request, clinic, source=source),
            "description": _source_description(source),
        })
    return rows


def _source_description(source):
    return {
        Appointment.BookingSource.HP: "HPの予約ボタンに設定してください。",
        Appointment.BookingSource.LINE: "LINEのリッチメニューやメッセージに設定できます。",
        Appointment.BookingSource.GOOGLE: "Googleビジネスプロフィールの予約リンクに設定できます。",
        Appointment.BookingSource.INSTAGRAM: "Instagramプロフィールや投稿案内に設定できます。",
        Appointment.BookingSource.QR: "院内掲示やカードのQRコード用URLとして利用できます。",
        Appointment.BookingSource.FLYER: "チラシや紙媒体からの予約導線に利用できます。",
        Appointment.BookingSource.REFERRAL: "紹介用の予約導線に利用できます。",
        Appointment.BookingSource.SMS: "SMS案内に利用できます。",
        Appointment.BookingSource.EMAIL: "メール案内に利用できます。",
    }.get(source, "予約導線として利用できます。")
