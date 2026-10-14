"""通知の文面。メールは件名と本文、SMS は短い本文。"""

from dataclasses import dataclass
from datetime import datetime

from app.core.config import settings

WEEKDAYS = "月火水木金土日"


@dataclass
class Message:
    subject: str
    email_body: str
    sms_body: str


def when(dt: datetime) -> str:
    d = dt.astimezone(settings.tz)
    return f"{d.month}月{d.day}日({WEEKDAYS[d.weekday()]}) {d:%H:%M}"


def _footer(clinic_name: str, phone: str) -> str:
    lines = ["", "――――――――――", clinic_name]
    if phone:
        lines.append(f"TEL {phone}")
    lines.append("※このメールは送信専用です。ご返信いただいてもお答えできません。")
    return "\n".join(lines)


def portal_url(slug: str, path: str = "") -> str:
    return f"{settings.public_app_url.rstrip('/')}/c/{slug}{path}"


def intake_url(token: str) -> str:
    return f"{settings.public_app_url.rstrip('/')}/q/{token}"


def booking_confirmed(
    *,
    name: str,
    clinic: str,
    phone: str,
    slug: str,
    start: datetime,
    menu: str,
    intake_token: str | None,
) -> Message:
    intake = ""
    if intake_token:
        intake = (
            "\nご来院前に Web 問診にご回答ください。回答いただくと予約が確定します。\n"
            f"{intake_url(intake_token)}\n"
        )
    body = (
        f"{name} 様\n\n{clinic}です。ご予約を受け付けました。\n\n"
        f"日時: {when(start)}\nメニュー: {menu or '-'}\n{intake}\n"
        f"予約の確認・キャンセルはマイページから行えます。\n{portal_url(slug, '/mypage')}\n"
        + _footer(clinic, phone)
    )
    sms = f"【{clinic}】{when(start)}のご予約を受け付けました。"
    sms += f"来院前に問診のご回答をお願いします {intake_url(intake_token)}" if intake_token else ""
    return Message(f"【{clinic}】ご予約を受け付けました", body, sms)


def reminder(
    *,
    name: str,
    clinic: str,
    phone: str,
    slug: str,
    start: datetime,
    menu: str,
    intake_token: str | None,
) -> Message:
    intake = (
        f"\nWeb 問診がまだのようです。ご来院前にご回答ください。\n{intake_url(intake_token)}\n"
        if intake_token
        else ""
    )
    body = (
        f"{name} 様\n\n{clinic}です。ご予約の日時が近づきましたのでお知らせします。\n\n"
        f"日時: {when(start)}\nメニュー: {menu or '-'}\n{intake}\n"
        f"変更・キャンセルはマイページ、またはお電話で承ります。\n{portal_url(slug, '/mypage')}\n"
        + _footer(clinic, phone)
    )
    sms = f"【{clinic}】{when(start)}にご予約をいただいています。お気をつけてお越しください。"
    if intake_token:
        sms += f"問診: {intake_url(intake_token)}"
    return Message(f"【{clinic}】ご予約日時のお知らせ", body, sms)


def cancelled(*, name: str, clinic: str, phone: str, slug: str, start: datetime) -> Message:
    body = (
        f"{name} 様\n\n{clinic}です。以下のご予約をキャンセルしました。\n\n"
        f"日時: {when(start)}\n\n"
        f"またのご予約をお待ちしております。\n{portal_url(slug, '/book')}\n"
        + _footer(clinic, phone)
    )
    sms = f"【{clinic}】{when(start)}のご予約をキャンセルしました。"
    return Message(f"【{clinic}】ご予約をキャンセルしました", body, sms)


def intake_link(*, name: str, clinic: str, phone: str, token: str) -> Message:
    body = (
        f"{name} 様\n\n{clinic}です。ご来院前に Web 問診へのご回答をお願いいたします。\n\n"
        f"{intake_url(token)}\n\n所要時間は 3 分ほどです。\n" + _footer(clinic, phone)
    )
    sms = f"【{clinic}】Web 問診へのご回答をお願いします {intake_url(token)}"
    return Message(f"【{clinic}】Web 問診のご案内", body, sms)


def password_reset(*, name: str, clinic: str, phone: str, slug: str, token: str) -> Message:
    url = portal_url(slug, f"/reset?token={token}")
    body = (
        f"{name} 様\n\n{clinic}のマイページのパスワード再設定のご案内です。\n"
        f"以下のリンクから 1 時間以内に新しいパスワードを設定してください。\n\n{url}\n\n"
        "お心当たりがない場合は、このメールを破棄してください。パスワードは変更されません。\n"
        + _footer(clinic, phone)
    )
    return Message(f"【{clinic}】パスワード再設定のご案内", body, "")
