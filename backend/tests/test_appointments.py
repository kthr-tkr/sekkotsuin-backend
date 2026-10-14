from httpx import AsyncClient

from tests.conftest import PATIENT

# 2026-10-15 は木曜日（テスト用院の休診日は日曜）
DAY = "2026-10-15"


def at(hm: str) -> str:
    return f"{DAY}T{hm}:00+09:00"


async def _patient(client: AsyncClient, headers: dict[str, str]) -> int:
    return (await client.post("/api/patients", json=PATIENT, headers=headers)).json()["id"]


async def test_create_uses_menu_duration(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    pid = await _patient(client, admin_a)
    res = await client.post(
        "/api/appointments",
        json={
            "patient_id": pid,
            "treatment_menu_id": clinic_a["menu_id"],
            "start_at": at("10:00"),
            "assigned_staff_id": clinic_a["practitioner_id"],
        },
        headers=admin_a,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["menu_name"] == "初診"
    assert body["end_at"].startswith("2026-10-15T02:00:00")  # 10:00 JST + 60分 = 11:00 JST
    assert body["patient"]["card_no"] == "P000001"
    assert body["assigned_staff"]["id"] == clinic_a["practitioner_id"]


async def test_staff_double_booking_is_rejected(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    staff = clinic_a["practitioner_id"]
    base = {"assigned_staff_id": staff, "start_at": at("10:00"), "end_at": at("11:00")}
    assert (await client.post("/api/appointments", json=base, headers=admin_a)).status_code == 201

    overlap = {**base, "start_at": at("10:30"), "end_at": at("11:30")}
    res = await client.post("/api/appointments", json=overlap, headers=admin_a)
    assert res.status_code == 409

    # 隣接する枠は OK
    adjacent = {**base, "start_at": at("11:00"), "end_at": at("11:30")}
    assert (
        await client.post("/api/appointments", json=adjacent, headers=admin_a)
    ).status_code == 201


async def test_cancelled_frees_slot(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    base = {
        "assigned_staff_id": clinic_a["practitioner_id"],
        "start_at": at("10:00"),
        "end_at": at("11:00"),
    }
    appt = (await client.post("/api/appointments", json=base, headers=admin_a)).json()
    res = await client.patch(
        f"/api/appointments/{appt['id']}", json={"status": "cancelled"}, headers=admin_a
    )
    assert res.status_code == 200
    assert (await client.post("/api/appointments", json=base, headers=admin_a)).status_code == 201


async def test_move_keeps_duration(client: AsyncClient, admin_a: dict[str, str]) -> None:
    base = {"start_at": at("10:00"), "end_at": at("10:45")}
    appt = (await client.post("/api/appointments", json=base, headers=admin_a)).json()
    res = await client.patch(
        f"/api/appointments/{appt['id']}", json={"start_at": at("14:00")}, headers=admin_a
    )
    assert res.status_code == 200
    assert res.json()["end_at"].startswith("2026-10-15T05:45:00")  # 14:45 JST


async def test_patch_rejects_null_start(client: AsyncClient, admin_a: dict[str, str]) -> None:
    appt = (
        await client.post("/api/appointments", json={"start_at": at("10:00")}, headers=admin_a)
    ).json()
    res = await client.patch(
        f"/api/appointments/{appt['id']}", json={"start_at": None}, headers=admin_a
    )
    assert res.status_code == 422


async def test_list_by_range(client: AsyncClient, admin_a: dict[str, str]) -> None:
    for hm in ("09:00", "15:00"):
        await client.post("/api/appointments", json={"start_at": at(hm)}, headers=admin_a)
    res = await client.get(
        "/api/appointments",
        params={"start": at("08:00"), "end": at("12:00")},
        headers=admin_a,
    )
    assert [a["start_at"][:16] for a in res.json()] == ["2026-10-15T00:00"]


async def test_other_clinic_references_rejected(
    client: AsyncClient,
    admin_a: dict[str, str],
    admin_b: dict[str, str],
    clinic_a: dict[str, int],
) -> None:
    pid = await _patient(client, admin_a)
    res = await client.post(
        "/api/appointments", json={"start_at": at("10:00"), "patient_id": pid}, headers=admin_b
    )
    assert res.status_code == 422
    res = await client.post(
        "/api/appointments",
        json={"start_at": at("10:00"), "assigned_staff_id": clinic_a["practitioner_id"]},
        headers=admin_b,
    )
    assert res.status_code == 422


async def test_availability(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    staff = clinic_a["practitioner_id"]
    await client.post(
        "/api/appointments",
        json={"start_at": at("10:00"), "end_at": at("11:00"), "assigned_staff_id": staff},
        headers=admin_a,
    )
    res = await client.get(
        "/api/appointments/availability",
        params={"date": DAY, "duration_minutes": 30, "staff_id": staff},
        headers=admin_a,
    )
    slots = {s["start_at"][11:16]: s["available"] for s in res.json()}
    # 院のタイムゾーン（JST）で返る。デフォルト: 9:00-20:00 / 休憩 13:00-15:00 / 30分単位
    assert res.json()[0]["start_at"] == at("09:00")
    assert slots["09:00"] is True
    assert slots["10:00"] is False
    assert slots["10:30"] is False
    assert slots["11:00"] is True
    assert "12:30" in slots and "13:00" not in slots and "14:30" not in slots
    assert slots["15:00"] is True
    assert "19:30" in slots and "20:00" not in slots

    closed = await client.get(
        "/api/appointments/availability",
        params={"date": "2026-10-18", "duration_minutes": 30},
        headers=admin_a,
    )
    assert closed.json() == []  # 日曜は休診
