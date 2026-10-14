from datetime import UTC, date, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update

from app.core.config import settings
from app.core.db import SessionLocal
from app.models import ClinicSettings
from tests.conftest import PATIENT

PASSWORD = "patient-pass-1"


def next_weekday(days_ahead: int = 2) -> date:
    """テスト院の休診日（日曜）を避けた、数日先の日付。"""
    d = datetime.now(settings.tz).date() + timedelta(days=days_ahead)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


def at(d: date, hm: str) -> str:
    return f"{d.isoformat()}T{hm}:00+09:00"


def register_body(**overrides) -> dict:
    return {**PATIENT, "email": "taro@example.com", "password": PASSWORD, **overrides}


async def _register(client: AsyncClient, **overrides) -> dict[str, str]:
    res = await client.post("/api/portal/a/register", json=register_body(**overrides))
    assert res.status_code == 201, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def test_public_clinic_info(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    res = await client.get("/api/portal/a")
    assert res.status_code == 200
    body = res.json()
    assert body["booking_slug"] == "a"
    assert [m["name"] for m in body["menus"]] == ["初診"]
    assert (await client.get("/api/portal/unknown")).status_code == 404

    async with SessionLocal() as db:
        await db.execute(
            update(ClinicSettings)
            .where(ClinicSettings.clinic_id == clinic_a["clinic_id"])
            .values(portal_enabled=False)
        )
        await db.commit()
    assert (await client.get("/api/portal/a")).status_code == 403


async def test_register_and_me(client: AsyncClient, clinic_a: dict[str, int]) -> None:
    headers = await _register(client)
    me = (await client.get("/api/me", headers=headers)).json()
    assert me["card_no"] == "P000001"
    assert me["email"] == "taro@example.com"
    assert me["clinic_slug"] == "a"

    res = await client.post("/api/portal/a/register", json=register_body(email="TARO@example.com"))
    assert res.status_code == 409  # メールアドレスの重複（大文字小文字は区別しない）
    res = await client.post("/api/portal/a/register", json=register_body(email="other@example.com"))
    assert res.status_code == 409  # 同じ人の二重登録
    assert "来院したことがある方" in res.json()["detail"]

    res = await client.put(
        "/api/me", json={"phone": "080-1111-2222", "address": "東京都"}, headers=headers
    )
    assert res.json()["phone"] == "080-1111-2222"


async def test_link_existing_patient(client: AsyncClient, admin_a: dict[str, str]) -> None:
    await client.post("/api/patients", json=PATIENT, headers=admin_a)
    body = {
        "last_name": "山田",
        "first_name": "太郎",
        "birth_date": "1980-04-01",
        "phone": "09012345678",  # ハイフンなしでも一致する
        "email": "yamada@example.com",
        "password": PASSWORD,
    }
    wrong = await client.post("/api/portal/a/link", json={**body, "phone": "0000"})
    assert wrong.status_code == 404
    res = await client.post("/api/portal/a/link", json=body)
    assert res.status_code == 201, res.text
    headers = {"Authorization": f"Bearer {res.json()['access_token']}"}
    assert (await client.get("/api/me", headers=headers)).json()["card_no"] == "P000001"
    again = await client.post("/api/portal/a/link", json={**body, "email": "x@example.com"})
    assert again.status_code == 409


async def test_login_by_email_or_card_no_and_rate_limit(
    client: AsyncClient, clinic_a: dict[str, int]
) -> None:
    await _register(client)
    for login_id in ("taro@example.com", "p000001"):
        res = await client.post(
            "/api/portal/a/login", json={"login_id": login_id, "password": PASSWORD}
        )
        assert res.status_code == 200, (login_id, res.text)
    bad = {"login_id": "taro@example.com", "password": "wrong"}
    assert (await client.post("/api/portal/a/login", json=bad)).status_code == 401
    missing = {"login_id": "nobody@example.com", "password": "x"}
    assert (await client.post("/api/portal/a/login", json=missing)).status_code == 401
    for _ in range(9):
        await client.post("/api/portal/a/login", json=bad)
    assert (await client.post("/api/portal/a/login", json=bad)).status_code == 429


async def test_patient_and_staff_tokens_are_not_interchangeable(
    client: AsyncClient, admin_a: dict[str, str]
) -> None:
    patient = await _register(client)
    assert (await client.get("/api/patients", headers=patient)).status_code == 401
    assert (await client.get("/api/auth/me", headers=patient)).status_code == 401
    assert (await client.get("/api/me", headers=admin_a)).status_code == 401
    assert (await client.get("/api/me")).status_code == 401


async def test_booking_flow(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    patient = await _register(client)
    day = next_weekday()
    menu_id = clinic_a["menu_id"]  # 60 分
    slots = (
        await client.get(
            "/api/portal/a/availability",
            params={"date": day.isoformat(), "menu_id": menu_id},
        )
    ).json()
    assert slots and "assigned_staff_id" not in slots[0]

    res = await client.post(
        "/api/me/appointments",
        json={"treatment_menu_id": menu_id, "start_at": at(day, "10:00")},
        headers=patient,
    )
    assert res.status_code == 201, res.text
    booked = res.json()
    assert booked["status"] == "pending"
    assert booked["intake_token"]
    assert booked["can_cancel"] is True
    # 発行された問診 URL がそのまま使える
    assert (await client.get(f"/api/public/intakes/{booked['intake_token']}")).status_code == 200

    # スタッフ側には HP からの「問診待ち」の予約として見える
    staff_view = (await client.get(f"/api/appointments/{booked['id']}", headers=admin_a)).json()
    assert (staff_view["status"], staff_view["booking_source"]) == ("pending", "hp")

    # 施術者 1 人の院なので、同じ枠は別の患者が予約できない
    other = await _register(
        client, email="hanako@example.com", first_name="花子", phone="080-0000-0000"
    )
    res = await client.post(
        "/api/me/appointments",
        json={"treatment_menu_id": menu_id, "start_at": at(day, "10:30")},
        headers=other,
    )
    assert res.status_code == 409

    mine = (await client.get("/api/me/appointments", headers=patient)).json()
    assert [a["id"] for a in mine] == [booked["id"]]
    assert (await client.get("/api/me/appointments", headers=other)).json() == []

    # 他人の予約はキャンセルできない
    res = await client.post(f"/api/me/appointments/{booked['id']}/cancel", headers=other)
    assert res.status_code == 404
    res = await client.post(f"/api/me/appointments/{booked['id']}/cancel", headers=patient)
    assert res.json()["status"] == "cancelled"
    # キャンセルで枠が空く
    res = await client.post(
        "/api/me/appointments",
        json={"treatment_menu_id": menu_id, "start_at": at(day, "10:00")},
        headers=other,
    )
    assert res.status_code == 201


async def test_booking_rules(client: AsyncClient, clinic_a: dict[str, int]) -> None:
    patient = await _register(client)
    menu_id = clinic_a["menu_id"]

    def body(start: str) -> dict:
        return {"treatment_menu_id": menu_id, "start_at": start}

    past = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    assert (
        await client.post("/api/me/appointments", json=body(past), headers=patient)
    ).status_code == 422
    far = at(next_weekday(90), "10:00")
    assert (
        await client.post("/api/me/appointments", json=body(far), headers=patient)
    ).status_code == 422
    # 枠の区切りに合わない時刻は予約できない
    odd = at(next_weekday(), "10:07")
    assert (
        await client.post("/api/me/appointments", json=body(odd), headers=patient)
    ).status_code == 409

    for i in range(3):
        res = await client.post(
            "/api/me/appointments", json=body(at(next_weekday(2 + i * 2), "10:00")), headers=patient
        )
        assert res.status_code == 201, res.text
    res = await client.post(
        "/api/me/appointments", json=body(at(next_weekday(9), "10:00")), headers=patient
    )
    assert res.status_code == 409  # 将来の予約は 3 件まで


async def test_cancel_deadline(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    patient = await _register(client)
    me = (await client.get("/api/me", headers=patient)).json()
    # 12 時間後の予約（スタッフが登録）はキャンセル期限（24 時間前）を過ぎている
    soon = (datetime.now(UTC) + timedelta(hours=12)).replace(microsecond=0).isoformat()
    appt = (
        await client.post(
            "/api/appointments",
            json={"patient_id": me["patient_id"], "start_at": soon},
            headers=admin_a,
        )
    ).json()
    mine = (await client.get("/api/me/appointments", headers=patient)).json()
    assert mine[0]["can_cancel"] is False
    res = await client.post(f"/api/me/appointments/{appt['id']}/cancel", headers=patient)
    assert res.status_code == 409
