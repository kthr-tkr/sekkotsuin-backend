from httpx import AsyncClient

from tests.conftest import PATIENT

START = "2026-10-15T10:00:00+09:00"


async def _appointment_with_intake(
    client: AsyncClient, headers: dict[str, str], staff_id: int
) -> dict:
    pid = (await client.post("/api/patients", json=PATIENT, headers=headers)).json()["id"]
    appt = (
        await client.post(
            "/api/appointments",
            json={"patient_id": pid, "start_at": START, "assigned_staff_id": staff_id},
            headers=headers,
        )
    ).json()
    token = (
        await client.post(
            "/api/intakes", json={"patient_id": pid, "appointment_id": appt["id"]}, headers=headers
        )
    ).json()["access_token"]
    await client.put(
        f"/api/public/intakes/{token}",
        json={"chief_complaint": "腰が痛い", "pain_scale": 6, "consent_agreed": True},
    )
    return appt


async def test_create_from_appointment_prefills(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    appt = await _appointment_with_intake(client, admin_a, clinic_a["practitioner_id"])
    res = await client.post(
        "/api/clinical-notes", json={"appointment_id": appt["id"]}, headers=admin_a
    )
    assert res.status_code == 201, res.text
    note = res.json()
    assert note["patient"]["id"] == appt["patient_id"]
    assert note["practitioner"]["id"] == clinic_a["practitioner_id"]
    assert note["visited_at"].startswith("2026-10-15T01:00:00")
    assert note["subjective"] == "腰が痛い"
    assert note["pain_scale_before"] == 6
    assert note["intake_id"] is not None
    assert note["status"] == "draft"

    # 同じ予約から再度作ると既存のカルテが返る
    again = await client.post(
        "/api/clinical-notes", json={"appointment_id": appt["id"]}, headers=admin_a
    )
    assert again.json()["id"] == note["id"]


async def test_update_keeps_revision_history(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    appt = await _appointment_with_intake(client, admin_a, clinic_a["practitioner_id"])
    note = (
        await client.post(
            "/api/clinical-notes", json={"appointment_id": appt["id"]}, headers=admin_a
        )
    ).json()
    body = {
        "visited_at": note["visited_at"],
        "practitioner_id": note["practitioner"]["id"],
        "subjective": "腰が痛い",
        "objective": "前屈で疼痛",
        "assessment": "筋筋膜性腰痛",
        "plan": "週2回",
        "pain_scale_before": 6,
        "pain_scale_after": 3,
    }
    res = await client.put(f"/api/clinical-notes/{note['id']}", json=body, headers=admin_a)
    assert res.status_code == 200, res.text
    assert res.json()["pain_scale_after"] == 3

    # 内容が変わらない保存では履歴を増やさない
    await client.put(f"/api/clinical-notes/{note['id']}", json=body, headers=admin_a)
    revs = (await client.get(f"/api/clinical-notes/{note['id']}/revisions", headers=admin_a)).json()
    assert len(revs) == 1
    assert revs[0]["snapshot"]["objective"] == ""  # 変更前の内容
    assert revs[0]["edited_by"]["username"] == "a-admin"


async def test_pain_scale_range(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    appt = await _appointment_with_intake(client, admin_a, clinic_a["practitioner_id"])
    note = (
        await client.post(
            "/api/clinical-notes", json={"appointment_id": appt["id"]}, headers=admin_a
        )
    ).json()
    res = await client.put(
        f"/api/clinical-notes/{note['id']}",
        json={"visited_at": note["visited_at"], "pain_scale_after": 11},
        headers=admin_a,
    )
    assert res.status_code == 422


async def test_finalize_completes_appointment(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    appt = await _appointment_with_intake(client, admin_a, clinic_a["practitioner_id"])
    note = (
        await client.post(
            "/api/clinical-notes", json={"appointment_id": appt["id"]}, headers=admin_a
        )
    ).json()
    res = await client.post(f"/api/clinical-notes/{note['id']}/finalize", headers=admin_a)
    assert res.json()["status"] == "finalized"
    assert res.json()["finalized_at"] is not None
    appt_after = (await client.get(f"/api/appointments/{appt['id']}", headers=admin_a)).json()
    assert appt_after["status"] == "completed"


async def test_list_and_without_appointment(
    client: AsyncClient, admin_a: dict[str, str], clinic_a: dict[str, int]
) -> None:
    pid = (await client.post("/api/patients", json=PATIENT, headers=admin_a)).json()["id"]
    res = await client.post(
        "/api/clinical-notes", json={"patient_id": pid, "visited_at": START}, headers=admin_a
    )
    assert res.status_code == 201
    assert res.json()["appointment_id"] is None

    listed = await client.get("/api/clinical-notes", params={"patient_id": pid}, headers=admin_a)
    assert listed.json()["total"] == 1
    drafts = await client.get(
        "/api/clinical-notes", params={"status": "finalized"}, headers=admin_a
    )
    assert drafts.json()["total"] == 0

    bad = await client.post("/api/clinical-notes", json={}, headers=admin_a)
    assert bad.status_code == 422


async def test_other_clinic_isolation(
    client: AsyncClient,
    admin_a: dict[str, str],
    admin_b: dict[str, str],
    clinic_a: dict[str, int],
) -> None:
    appt = await _appointment_with_intake(client, admin_a, clinic_a["practitioner_id"])
    res = await client.post(
        "/api/clinical-notes", json={"appointment_id": appt["id"]}, headers=admin_b
    )
    assert res.status_code == 404
    note = (
        await client.post(
            "/api/clinical-notes", json={"appointment_id": appt["id"]}, headers=admin_a
        )
    ).json()
    assert (
        await client.get(f"/api/clinical-notes/{note['id']}", headers=admin_b)
    ).status_code == 404
    res = await client.put(
        f"/api/clinical-notes/{note['id']}",
        json={"visited_at": note["visited_at"]},
        headers=admin_b,
    )
    assert res.status_code == 404
    assert (await client.get("/api/clinical-notes", headers=admin_b)).json()["total"] == 0
    # 他院の担当者は指定できない
    other_staff = (await client.get("/api/staff", headers=admin_b)).json()[0]["id"]
    res = await client.put(
        f"/api/clinical-notes/{note['id']}",
        json={"visited_at": note["visited_at"], "practitioner_id": other_staff},
        headers=admin_a,
    )
    assert res.status_code == 422
