import re
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select, update

from app.core.db import SessionLocal
from app.models import Appointment, ClinicSettings, Notification, Patient
from app.services.notify import queue
from app.services.notify.senders import DeliveryError, mobile_e164
from tests.conftest import PATIENT
from tests.test_portal import PASSWORD, _register, at, next_weekday


async def _notifications() -> list[Notification]:
    async with SessionLocal() as db:
        return list(await db.scalars(select(Notification).order_by(Notification.id)))


async def _settings(clinic_id: int, **values) -> None:
    async with SessionLocal() as db:
        await db.execute(
            update(ClinicSettings).where(ClinicSettings.clinic_id == clinic_id).values(**values)
        )
        await db.commit()


def test_mobile_e164() -> None:
    assert mobile_e164("090-1234-5678") == "+819012345678"
    assert mobile_e164("+81 80 1234 5678") == "+818012345678"
    assert mobile_e164("03-1234-5678") is None  # 固定電話には SMS を送らない
    assert mobile_e164("0120-123-456") is None


async def test_booking_and_cancel_notifications(
    client: AsyncClient, clinic_a: dict[str, int]
) -> None:
    await _settings(clinic_a["clinic_id"], notify_sms_enabled=True)
    patient = await _register(client)  # PATIENT の電話は 090（携帯）
    booked = (
        await client.post(
            "/api/me/appointments",
            json={
                "treatment_menu_id": clinic_a["menu_id"],
                "start_at": at(next_weekday(), "10:00"),
            },
            headers=patient,
        )
    ).json()
    sent = await _notifications()
    assert {(n.kind, n.channel, n.to) for n in sent} == {
        ("booking_confirmed", "email", "taro@example.com"),
        ("booking_confirmed", "sms", "+819012345678"),
    }
    email = next(n for n in sent if n.channel == "email")
    assert f"/q/{booked['intake_token']}" in email.body  # 問診の URL が入っている
    assert "/c/a/mypage" in email.body

    assert await queue.send_pending() == 2
    assert {n.status for n in await _notifications()} == {"sent"}

    await client.post(f"/api/me/appointments/{booked['id']}/cancel", headers=patient)
    kinds = [n.kind for n in await _notifications()]
    assert kinds.count("cancelled") == 2


async def test_staff_booking_notifies_only_when_asked(
    client: AsyncClient, admin_a: dict[str, str]
) -> None:
    pid = (
        await client.post(
            "/api/patients", json={**PATIENT, "email": "p@example.com"}, headers=admin_a
        )
    ).json()["id"]
    start = at(next_weekday(), "10:00")
    await client.post(
        "/api/appointments", json={"patient_id": pid, "start_at": start}, headers=admin_a
    )
    assert await _notifications() == []
    await client.post(
        "/api/appointments",
        json={"patient_id": pid, "start_at": at(next_weekday(), "15:00"), "notify_patient": True},
        headers=admin_a,
    )
    # SMS は院の設定で無効（初期値）なのでメールだけ
    assert [(n.kind, n.channel) for n in await _notifications()] == [("booking_confirmed", "email")]


async def _appointment_at(client, headers, pid: int, start: datetime, created_ago: timedelta):
    appt = (
        await client.post(
            "/api/appointments",
            json={"patient_id": pid, "start_at": start.isoformat()},
            headers=headers,
        )
    ).json()
    async with SessionLocal() as db:
        await db.execute(
            update(Appointment)
            .where(Appointment.id == appt["id"])
            .values(created_at=datetime.now(UTC) - created_ago)
        )
        await db.commit()
    return appt


async def test_reminders(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid = (
        await client.post(
            "/api/patients", json={**PATIENT, "email": "r@example.com"}, headers=admin_a
        )
    ).json()["id"]
    soon = datetime.now(UTC).replace(microsecond=0, second=0) + timedelta(hours=20)
    later = soon + timedelta(days=3)
    due = await _appointment_at(client, admin_a, pid, soon, timedelta(days=5))
    await _appointment_at(client, admin_a, pid, later, timedelta(days=5))  # まだ先
    # リマインドの時刻を過ぎてから入った直前の予約には送らない
    await _appointment_at(client, admin_a, pid, soon + timedelta(hours=1), timedelta(hours=1))

    async with SessionLocal() as db:
        assert await queue.schedule_reminders(db) == 1
    async with SessionLocal() as db:
        assert await queue.schedule_reminders(db) == 0  # 二重に送らない
    reminders = [n for n in await _notifications() if n.kind == "reminder"]
    assert [n.appointment_id for n in reminders] == [due["id"]]

    # 患者がリマインドを止めている場合は送らない
    async with SessionLocal() as db:
        await db.execute(update(Patient).where(Patient.id == pid).values(reminders_enabled=False))
        await db.commit()
    await _appointment_at(client, admin_a, pid, soon + timedelta(hours=2), timedelta(days=5))
    async with SessionLocal() as db:
        assert await queue.schedule_reminders(db) == 0


async def test_password_reset(client: AsyncClient, clinic_a: dict[str, int]) -> None:
    await _register(client)
    res = await client.post("/api/portal/a/password-reset", json={"email": "TARO@example.com"})
    assert res.status_code == 202
    # 登録されていないアドレスでも同じ応答（存在を推測されない）
    res2 = await client.post("/api/portal/a/password-reset", json={"email": "no@example.com"})
    assert (res2.status_code, res2.json()) == (202, res.json())

    mails = [n for n in await _notifications() if n.kind == "password_reset"]
    assert len(mails) == 1 and mails[0].to == "taro@example.com"
    token = re.search(r"reset\?token=([\w-]+)", mails[0].body).group(1)  # type: ignore[union-attr]

    short = await client.post(
        "/api/portal/a/password-reset/confirm", json={"token": token, "password": "short"}
    )
    assert short.status_code == 422
    res = await client.post(
        "/api/portal/a/password-reset/confirm", json={"token": token, "password": "new-pass-123"}
    )
    assert res.status_code == 200, res.text
    login = {"login_id": "taro@example.com", "password": "new-pass-123"}
    assert (await client.post("/api/portal/a/login", json=login)).status_code == 200
    old = {"login_id": "taro@example.com", "password": PASSWORD}
    assert (await client.post("/api/portal/a/login", json=old)).status_code == 401
    # 同じリンクは二度使えない
    again = await client.post(
        "/api/portal/a/password-reset/confirm", json={"token": token, "password": "x-pass-1234"}
    )
    assert again.status_code == 400

    for _ in range(2):
        await client.post("/api/portal/a/password-reset", json={"email": "taro@example.com"})
    res = await client.post("/api/portal/a/password-reset", json={"email": "taro@example.com"})
    assert res.status_code == 429


async def test_send_intake_link(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    pid = (
        await client.post(
            "/api/patients", json={**PATIENT, "email": "i@example.com"}, headers=admin_a
        )
    ).json()["id"]
    intake = (await client.post("/api/intakes", json={"patient_id": pid}, headers=admin_a)).json()
    url = f"/api/intakes/{intake['id']}/send"
    res = await client.post(url, json={"channels": ["sms"]}, headers=admin_a)
    assert res.status_code == 422  # SMS は院の設定で無効
    res = await client.post(url, json={"channels": ["email"]}, headers=admin_a)
    assert res.status_code == 202
    assert res.json()[0]["to"] == "i@example.com"

    await _settings(clinic_a["clinic_id"], notify_sms_enabled=True)
    res = await client.post(url, json={"channels": ["sms"]}, headers=admin_a)
    assert res.json()[0]["to"] == "+819012345678"


async def test_failed_delivery_retries_with_backoff(
    client: AsyncClient, admin_a: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    pid = (
        await client.post(
            "/api/patients", json={**PATIENT, "email": "f@example.com"}, headers=admin_a
        )
    ).json()["id"]
    intake = (await client.post("/api/intakes", json={"patient_id": pid}, headers=admin_a)).json()
    await client.post(
        f"/api/intakes/{intake['id']}/send", json={"channels": ["email"]}, headers=admin_a
    )

    async def boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise DeliveryError("SMTP down")

    monkeypatch.setattr(queue, "send_email", boom)
    assert await queue.send_pending() == 1  # 失敗後は間隔をあけるので、すぐには再試行しない
    n = (await _notifications())[0]
    assert (n.status, n.attempts, n.error_message) == ("queued", 1, "SMTP down")
    assert n.next_attempt_at is not None

    for _ in range(2):
        async with SessionLocal() as db:
            await db.execute(update(Notification).values(next_attempt_at=None))
            await db.commit()
        await queue.send_pending()
    n = (await _notifications())[0]
    assert (n.status, n.attempts) == ("failed", 3)


async def test_notification_log_is_admin_only_and_isolated(
    client: AsyncClient,
    admin_a: dict[str, str],
    reception_a: dict[str, str],
    admin_b: dict[str, str],
) -> None:
    await client.post(
        "/api/appointments",
        json={
            "patient_id": (
                await client.post(
                    "/api/patients", json={**PATIENT, "email": "l@example.com"}, headers=admin_a
                )
            ).json()["id"],
            "start_at": at(next_weekday(), "10:00"),
            "notify_patient": True,
        },
        headers=admin_a,
    )
    assert (await client.get("/api/notifications", headers=reception_a)).status_code == 403
    assert (await client.get("/api/notifications", headers=admin_a)).json()["total"] == 1
    assert (await client.get("/api/notifications", headers=admin_b)).json()["total"] == 0
