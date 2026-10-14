from httpx import AsyncClient

from tests.conftest import PATIENT

DAY = "2026-10-15"  # 木曜日


async def _patient(client: AsyncClient, headers: dict[str, str]) -> int:
    return (await client.post("/api/patients", json=PATIENT, headers=headers)).json()["id"]


# --- 売上 ---


async def test_sales_draft_from_note_and_totals(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    await client.put(
        f"/api/treatment-menus/{clinic_a['menu_id']}",
        json={"name": "初診", "price": 3000, "duration_minutes": 60},
        headers=admin_a,
    )
    pid = await _patient(client, admin_a)
    appt = (
        await client.post(
            "/api/appointments",
            json={
                "patient_id": pid,
                "start_at": f"{DAY}T10:00:00+09:00",
                "treatment_menu_id": clinic_a["menu_id"],
                "assigned_staff_id": clinic_a["practitioner_id"],
            },
            headers=admin_a,
        )
    ).json()
    note = (
        await client.post(
            "/api/clinical-notes", json={"appointment_id": appt["id"]}, headers=admin_a
        )
    ).json()

    draft = (
        await client.get(
            "/api/sales/draft", params={"clinical_note_id": note["id"]}, headers=admin_a
        )
    ).json()
    assert draft["amount"] == 3000
    assert draft["description"] == "初診"
    assert draft["treatment_date"] == DAY
    assert draft["staff_id"] == clinic_a["practitioner_id"]

    assert (await client.post("/api/sales", json=draft, headers=admin_a)).status_code == 201
    unpaid = {**draft, "clinical_note_id": None, "amount": 800, "status": "unpaid"}
    assert (await client.post("/api/sales", json=unpaid, headers=admin_a)).status_code == 201

    page = (
        await client.get("/api/sales", params={"start": DAY, "end": DAY}, headers=admin_a)
    ).json()
    assert page["total"] == 2
    assert page["paid_amount"] == 3000
    assert page["unpaid_amount"] == 800

    rec = page["items"][0]
    res = await client.put(
        f"/api/sales/{rec['id']}",
        json={**{k: rec[k] for k in draft}, "status": "paid"},
        headers=admin_a,
    )
    assert res.json()["status"] == "paid"


async def test_sales_rejects_cross_patient_and_clinic(
    client: AsyncClient, admin_a: dict[str, str], admin_b: dict[str, str]
) -> None:
    pid = await _patient(client, admin_a)
    other = await _patient(client, admin_a)
    note = (
        await client.post(
            "/api/clinical-notes",
            json={"patient_id": other, "visited_at": f"{DAY}T10:00:00+09:00"},
            headers=admin_a,
        )
    ).json()
    body = {"patient_id": pid, "clinical_note_id": note["id"], "treatment_date": DAY, "amount": 1}
    assert (await client.post("/api/sales", json=body, headers=admin_a)).status_code == 422
    body = {"patient_id": pid, "treatment_date": DAY, "amount": 1}
    assert (await client.post("/api/sales", json=body, headers=admin_b)).status_code == 404
    assert (await client.get("/api/sales", headers=admin_b)).json()["total"] == 0


# --- シフト・休暇・空き枠 ---


async def _slots(client: AsyncClient, headers: dict[str, str], **params) -> dict[str, bool]:
    res = await client.get(
        "/api/appointments/availability",
        params={"date": DAY, "duration_minutes": 30, **params},
        headers=headers,
    )
    return {s["start_at"][11:16]: s["available"] for s in res.json()}


async def test_shift_limits_availability(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    staff = clinic_a["practitioner_id"]
    res = await client.put(
        f"/api/shifts/{staff}/{DAY}",
        json={"status": "working", "start_time": "10:00", "end_time": "12:00"},
        headers=admin_a,
    )
    assert res.status_code == 200, res.text
    slots = await _slots(client, admin_a, staff_id=staff)
    assert slots["09:30"] is False and slots["10:00"] is True and slots["11:30"] is True
    assert slots["15:00"] is False

    # 予約が入るとその枠は埋まる
    await client.post(
        "/api/appointments",
        json={"start_at": f"{DAY}T10:00:00+09:00", "assigned_staff_id": staff},
        headers=admin_a,
    )
    assert (await _slots(client, admin_a))["10:00"] is False

    await client.put(f"/api/shifts/{staff}/{DAY}", json={"status": "off"}, headers=admin_a)
    assert not any((await _slots(client, admin_a)).values())

    bad = {"status": "working", "start_time": "12:00", "end_time": "10:00"}
    res = await client.put(f"/api/shifts/{staff}/{DAY}", json=bad, headers=admin_a)
    assert res.status_code == 422

    shifts = (await client.get("/api/shifts", params={"month": "2026-10"}, headers=admin_a)).json()
    assert [s["status"] for s in shifts] == ["off"]
    await client.delete(f"/api/shifts/{staff}/{DAY}", headers=admin_a)
    assert (await _slots(client, admin_a))["15:00"] is True


async def test_leave_request_approval_and_availability(
    client: AsyncClient,
    admin_a: dict[str, str],
    clinic_a: dict[str, int],
) -> None:
    from tests.conftest import login

    practitioner = await login(client, "a-practitioner")
    res = await client.post(
        "/api/leaves",
        json={"leave_type": "afternoon_off", "start_date": DAY, "end_date": DAY},
        headers=practitioner,
    )
    assert res.status_code == 201, res.text
    leave = res.json()
    assert leave["status"] == "requested"
    assert leave["staff"]["id"] == clinic_a["practitioner_id"]

    # 申請中は空き枠に影響しない
    assert (await _slots(client, admin_a, staff_id=leave["staff_id"]))["15:00"] is True
    # 施術者は承認できない
    assert (
        await client.post(
            f"/api/leaves/{leave['id']}/decide", json={"status": "approved"}, headers=practitioner
        )
    ).status_code == 403
    res = await client.post(
        f"/api/leaves/{leave['id']}/decide", json={"status": "approved"}, headers=admin_a
    )
    assert res.json()["status"] == "approved"
    slots = await _slots(client, admin_a, staff_id=leave["staff_id"])
    assert slots["10:00"] is True and slots["15:00"] is False  # 午後休

    # 他人の休暇は申請できない（管理者は可）
    res = await client.post(
        "/api/leaves",
        json={
            "staff_id": clinic_a["reception_id"],
            "leave_type": "paid_leave",
            "start_date": DAY,
            "end_date": DAY,
        },
        headers=practitioner,
    )
    assert res.status_code == 403
    res = await client.post(f"/api/leaves/{leave['id']}/cancel", headers=practitioner)
    assert res.json()["status"] == "canceled"
    assert (await _slots(client, admin_a, staff_id=leave["staff_id"]))["15:00"] is True


async def test_admin_counts_as_practitioner_when_none(
    client: AsyncClient, admin_b: dict[str, str], clinic_b: dict[str, int]
) -> None:
    from sqlalchemy import update

    from app.core.db import SessionLocal
    from app.models import User

    async with SessionLocal() as db:
        await db.execute(
            update(User).where(User.id == clinic_b["practitioner_id"]).values(is_active=False)
        )
        await db.commit()
    assert (await _slots(client, admin_b))["10:00"] is True


# --- KPI ---


async def test_kpi_summary(
    client: AsyncClient,
    admin_a: dict[str, str],
    reception_a: dict[str, str],
    clinic_a: dict[str, int],
) -> None:
    assert (await client.get("/api/kpi", headers=reception_a)).status_code == 403
    pid = await _patient(client, admin_a)
    staff = clinic_a["practitioner_id"]
    for hour, status_, source in (
        ("10", "completed", "line"),
        ("11", "completed", "hp"),
        ("12", "cancelled", "line"),
        ("15", "booked", "line"),
    ):
        await client.post(
            "/api/appointments",
            json={
                "patient_id": pid,
                "start_at": f"{DAY}T{hour}:00:00+09:00",
                "assigned_staff_id": staff,
                "status": status_,
                "booking_source": source,
            },
            headers=admin_a,
        )
    for amount, st in ((3000, "paid"), (5000, "paid"), (800, "unpaid")):
        await client.post(
            "/api/sales",
            json={
                "patient_id": pid,
                "staff_id": staff,
                "treatment_date": DAY,
                "amount": amount,
                "status": st,
            },
            headers=admin_a,
        )

    k = (await client.get("/api/kpi", params={"month": "2026-10"}, headers=admin_a)).json()
    assert k["sales_total"] == 8000
    assert k["average_spend"] == 4000
    assert (k["unpaid_count"], k["unpaid_amount"]) == (1, 800)
    assert (k["appointments"], k["visits"], k["cancellations"]) == (4, 2, 1)
    assert k["cancel_rate"] == 0.25
    assert k["booking_sources"][0] == {"source": "line", "count": 2}
    day = next(d for d in k["daily"] if d["date"] == DAY)
    assert (day["sales"], day["visits"]) == (8000, 2)
    assert len(k["daily"]) == 31
    top = k["by_staff"][0]
    assert (top["staff_id"], top["sales"], top["visits"]) == (staff, 8000, 2)
