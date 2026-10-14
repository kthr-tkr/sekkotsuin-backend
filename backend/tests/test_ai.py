import pytest
from httpx import AsyncClient

from app.services.ai import provider as provider_module
from app.services.ai.jobs import run_pending
from tests.conftest import PATIENT
from tests.test_posture import jpeg_with_gps

AUDIO = ("visit.webm", b"\x1aE\xdf\xa3fake-webm", "audio/webm;codecs=opus")


async def _note(client: AsyncClient, headers: dict[str, str]) -> dict:
    pid = (await client.post("/api/patients", json=PATIENT, headers=headers)).json()["id"]
    return (
        await client.post(
            "/api/clinical-notes",
            json={"patient_id": pid, "visited_at": "2026-10-15T10:00:00+09:00"},
            headers=headers,
        )
    ).json()


async def _upload(client: AsyncClient, headers: dict[str, str], note_id: int, sec: int = 120):
    return await client.post(
        f"/api/clinical-notes/{note_id}/recordings",
        files={"file": AUDIO},
        data={"duration_sec": str(sec)},
        headers=headers,
    )


async def test_recording_pipeline_and_apply(client: AsyncClient, admin_a: dict[str, str]) -> None:
    note = await _note(client, admin_a)
    await client.put(
        f"/api/clinical-notes/{note['id']}",
        json={"visited_at": note["visited_at"], "subjective": "腰痛（手入力）"},
        headers=admin_a,
    )
    res = await _upload(client, admin_a, note["id"])
    assert res.status_code == 201, res.text
    rec = res.json()
    assert rec["status"] == "queued"
    assert rec["mime_type"] == "audio/webm"

    assert await run_pending() == 1
    rec = (await client.get(f"/api/recordings/{rec['id']}", headers=admin_a)).json()
    assert rec["status"] == "done", rec
    assert "腰" in rec["transcript"]
    assert rec["summary"]["soap"]["S"]
    assert (await client.get(rec["audio_url"])).status_code == 200

    res = await client.post(f"/api/recordings/{rec['id']}/apply", headers=admin_a)
    assert res.status_code == 200, res.text
    assert res.json()["applied_at"] is not None
    updated = (await client.get(f"/api/clinical-notes/{note['id']}", headers=admin_a)).json()
    # 記入済みの S には追記し、空の O には設定する
    assert updated["subjective"].startswith("腰痛（手入力）\n・先週から腰痛")
    assert updated["objective"] == "・前屈で腰部に疼痛"
    assert updated["pain_scale_before"] == 6
    revs = (await client.get(f"/api/clinical-notes/{note['id']}/revisions", headers=admin_a)).json()
    assert revs[0]["snapshot"]["subjective"] == "腰痛（手入力）"

    usage = (await client.get("/api/ai/usage", headers=admin_a)).json()
    assert usage["minutes_used"] == 2.0
    assert {t["usage_type"] for t in usage["by_type"]} == {"transcription", "summary"}
    assert usage["cost_yen"] > 0


async def test_recording_validation_and_quota(client: AsyncClient, admin_a: dict[str, str]) -> None:
    note = await _note(client, admin_a)
    res = await client.post(
        f"/api/clinical-notes/{note['id']}/recordings",
        files={"file": ("a.txt", b"x", "text/plain")},
        data={"duration_sec": "10"},
        headers=admin_a,
    )
    assert res.status_code == 415

    settings_res = (await client.get("/api/clinic/settings", headers=admin_a)).json()
    body = {**settings_res, "ai_monthly_minutes_limit": 3}
    body.pop("clinic_id")
    assert (await client.put("/api/clinic/settings", json=body, headers=admin_a)).status_code == 200
    assert (await _upload(client, admin_a, note["id"], sec=120)).status_code == 201
    res = await _upload(client, admin_a, note["id"], sec=120)  # 合計 4 分 > 3 分
    assert res.status_code == 403
    assert "上限" in res.json()["detail"]

    body["ai_enabled"] = False
    await client.put("/api/clinic/settings", json=body, headers=admin_a)
    res = await _upload(client, admin_a, note["id"], sec=10)
    assert res.status_code == 403


async def test_failed_job_retries_then_fails(
    client: AsyncClient, admin_a: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    note = await _note(client, admin_a)
    rec = (await _upload(client, admin_a, note["id"])).json()

    async def boom(self, data, filename, mime):  # noqa: ANN001
        raise RuntimeError("STT unavailable")

    monkeypatch.setattr(provider_module.FakeProvider, "transcribe", boom)
    assert await run_pending() == 3  # 3 回まで再試行する
    rec = (await client.get(f"/api/recordings/{rec['id']}", headers=admin_a)).json()
    assert rec["status"] == "failed"
    assert "STT unavailable" in rec["error_message"]
    assert (
        await client.post(f"/api/recordings/{rec['id']}/apply", headers=admin_a)
    ).status_code == 409

    monkeypatch.undo()
    res = await client.post(f"/api/recordings/{rec['id']}/retry", headers=admin_a)
    assert res.json()["status"] == "queued"
    await run_pending()
    rec = (await client.get(f"/api/recordings/{rec['id']}", headers=admin_a)).json()
    assert rec["status"] == "done"


async def test_posture_ai_analysis(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid = (await client.post("/api/patients", json=PATIENT, headers=admin_a)).json()["id"]
    a = (
        await client.post("/api/posture-assessments", json={"patient_id": pid}, headers=admin_a)
    ).json()
    base = f"/api/posture-assessments/{a['id']}"
    assert (await client.post(f"{base}/analyze", headers=admin_a)).status_code == 422

    await client.put(
        f"{base}/images/front",
        files={"file": ("f.jpg", jpeg_with_gps(300, 400), "image/jpeg")},
        headers=admin_a,
    )
    await client.put(
        base,
        json={
            "title": "姿勢評価",
            "assessed_at": "2026-10-15T10:00:00+09:00",
            "findings": {"regions": {"knee": "右膝がやや内側（手入力）"}},
        },
        headers=admin_a,
    )
    res = await client.post(f"{base}/analyze", headers=admin_a)
    assert res.json()["ai_status"] == "queued"
    assert (await client.post(f"{base}/analyze", headers=admin_a)).status_code == 409

    await run_pending()
    a = (await client.get(base, headers=admin_a)).json()
    assert a["ai_status"] == "done"
    assert a["ai_findings"]["important_points"]

    a = (await client.post(f"{base}/apply-ai", headers=admin_a)).json()
    assert a["findings"]["regions"]["shoulder"] == "右肩がやや低い"
    # AI が空欄にした部位は手入力の所見を残す
    assert a["findings"]["regions"]["knee"] == "右膝がやや内側（手入力）"


async def test_usage_is_admin_only_and_isolated(
    client: AsyncClient,
    admin_a: dict[str, str],
    reception_a: dict[str, str],
    admin_b: dict[str, str],
) -> None:
    assert (await client.get("/api/ai/usage", headers=reception_a)).status_code == 403
    note = await _note(client, admin_a)
    rec = (await _upload(client, admin_a, note["id"])).json()
    await run_pending()
    assert (await client.get("/api/ai/usage", headers=admin_b)).json()["minutes_used"] == 0
    assert (await client.get(f"/api/recordings/{rec['id']}", headers=admin_b)).status_code == 404
    assert (
        await client.post(f"/api/recordings/{rec['id']}/apply", headers=admin_b)
    ).status_code == 404
    res = await _upload(client, admin_b, note["id"])
    assert res.status_code == 404
