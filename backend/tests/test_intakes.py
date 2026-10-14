from datetime import UTC, datetime, timedelta

from httpx import AsyncClient
from sqlalchemy import update

from app.core.db import SessionLocal
from app.models import Intake
from tests.conftest import PATIENT

ANSWERS = {
    "chief_complaint": "腰が痛い",
    "symptom_type": "acute",
    "onset": "3日前",
    "pain_areas": ["lower_back"],
    "pain_scale": 7,
    "consent_agreed": True,
}


async def _setup(client: AsyncClient, headers: dict[str, str]) -> tuple[int, dict]:
    pid = (await client.post("/api/patients", json=PATIENT, headers=headers)).json()["id"]
    appt = (
        await client.post(
            "/api/appointments",
            json={
                "patient_id": pid,
                "start_at": "2026-10-15T10:00:00+09:00",
                "status": "pending",
            },
            headers=headers,
        )
    ).json()
    return pid, appt


async def test_issue_and_submit(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid, appt = await _setup(client, admin_a)
    res = await client.post(
        "/api/intakes", json={"patient_id": pid, "appointment_id": appt["id"]}, headers=admin_a
    )
    assert res.status_code == 201, res.text
    intake = res.json()
    token = intake["access_token"]
    assert intake["submitted_at"] is None

    # 同じ予約で再発行すると既存のものが返る
    again = await client.post(
        "/api/intakes", json={"patient_id": pid, "appointment_id": appt["id"]}, headers=admin_a
    )
    assert again.json()["id"] == intake["id"]

    # 患者側（認証なし）
    pub = await client.get(f"/api/public/intakes/{token}")
    assert pub.status_code == 200
    assert pub.json()["patient_display_name"] == "山田 様"
    assert pub.json()["submitted"] is False
    assert "birth_date" not in pub.text

    res = await client.put(f"/api/public/intakes/{token}", json=ANSWERS)
    assert res.status_code == 200, res.text
    assert res.json()["submitted"] is True

    # 二重送信は不可
    assert (await client.put(f"/api/public/intakes/{token}", json=ANSWERS)).status_code == 409

    # スタッフ側で内容と予約ステータスを確認
    detail = (await client.get(f"/api/intakes/{intake['id']}", headers=admin_a)).json()
    assert detail["chief_complaint"] == "腰が痛い"
    assert detail["payload"]["answers"]["pain_scale"] == 7
    appt_after = (await client.get(f"/api/appointments/{appt['id']}", headers=admin_a)).json()
    assert appt_after["status"] == "booked"

    listed = await client.get("/api/intakes", params={"submitted": True}, headers=admin_a)
    assert listed.json()["total"] == 1


async def test_consent_required(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid, _ = await _setup(client, admin_a)
    token = (await client.post("/api/intakes", json={"patient_id": pid}, headers=admin_a)).json()[
        "access_token"
    ]
    res = await client.put(
        f"/api/public/intakes/{token}", json={**ANSWERS, "consent_agreed": False}
    )
    assert res.status_code == 422


async def test_expired_or_unknown_token(client: AsyncClient, admin_a: dict[str, str]) -> None:
    assert (await client.get("/api/public/intakes/unknown")).status_code == 404

    pid, _ = await _setup(client, admin_a)
    intake = (await client.post("/api/intakes", json={"patient_id": pid}, headers=admin_a)).json()
    async with SessionLocal() as db:
        await db.execute(
            update(Intake)
            .where(Intake.id == intake["id"])
            .values(token_expires_at=datetime.now(UTC) - timedelta(minutes=1))
        )
        await db.commit()
    assert (await client.get(f"/api/public/intakes/{intake['access_token']}")).status_code == 404


async def test_other_clinic_cannot_issue_or_read(
    client: AsyncClient, admin_a: dict[str, str], admin_b: dict[str, str]
) -> None:
    pid, appt = await _setup(client, admin_a)
    res = await client.post("/api/intakes", json={"patient_id": pid}, headers=admin_b)
    assert res.status_code == 404
    intake = (await client.post("/api/intakes", json={"patient_id": pid}, headers=admin_a)).json()
    assert (await client.get(f"/api/intakes/{intake['id']}", headers=admin_b)).status_code == 404
