"""メール（SMTP）と SMS（Twilio）の送信。console は送らずにログだけ出す（開発・テスト用）。"""

import asyncio
import logging
import re
import smtplib
from email.message import EmailMessage
from email.utils import formataddr

import httpx

from app.core.config import settings

log = logging.getLogger(__name__)

MOBILE_RE = re.compile(r"^0[789]0\d{8}$")


def mobile_e164(phone: str) -> str | None:
    """日本の携帯番号（070/080/090）なら E.164 形式（+81...）にする。それ以外は None。"""
    digits = re.sub(r"\D", "", phone)
    if digits.startswith("81") and len(digits) == 12:
        digits = "0" + digits[2:]
    return "+81" + digits[1:] if MOBILE_RE.match(digits) else None


class DeliveryError(RuntimeError):
    pass


def _send_smtp(to: str, subject: str, body: str, from_name: str) -> None:
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, settings.email_from))
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as smtp:
        if settings.smtp_starttls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password)
        smtp.send_message(msg)


async def send_email(to: str, subject: str, body: str, *, from_name: str) -> None:
    if settings.email_provider == "disabled":
        raise DeliveryError("メール送信は無効になっています。")
    if settings.email_provider == "console":
        log.info("[email:console] to=%s subject=%s\n%s", to, subject, body)
        return
    try:
        await asyncio.to_thread(_send_smtp, to, subject, body, from_name)
    except (smtplib.SMTPException, OSError) as e:
        raise DeliveryError(f"メールを送信できませんでした: {e}") from e


async def send_sms(to: str, body: str) -> None:
    if settings.sms_provider == "disabled":
        raise DeliveryError("SMS 送信は無効になっています。")
    if settings.sms_provider == "console":
        log.info("[sms:console] to=%s\n%s", to, body)
        return
    url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Messages.json"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            res = await client.post(
                url,
                data={"To": to, "From": settings.twilio_from_number, "Body": body},
                auth=(settings.twilio_account_sid, settings.twilio_auth_token),
            )
    except httpx.HTTPError as e:
        raise DeliveryError(f"SMS を送信できませんでした: {e}") from e
    if res.status_code >= 300:
        raise DeliveryError(f"SMS を送信できませんでした（{res.status_code}）: {res.text[:200]}")
