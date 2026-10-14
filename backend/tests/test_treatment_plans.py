import base64
import struct
import zlib

from httpx import AsyncClient

from tests.conftest import PATIENT


def tiny_png() -> str:
    """1x1 の PNG を data URL で返す。"""

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))

    raw = b"\x89PNG\r\n\x1a\n"
    raw += chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
    raw += chunk(b"IDAT", zlib.compress(b"\x00\xff\xff\xff"))
    raw += chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(raw).decode()


def plan_body(**overrides) -> dict:
    return {
        "title": "腰痛改善プラン",
        "chief_complaint": "腰が痛い",
        "start_date": "2026-10-15",
        "visit_guide_type": "weekly",
        "visit_guide_count": 2,
        "exercise_instruction": "痛みが出ない範囲で散歩",
        "expected_recovery_weeks_min": 4,
        "expected_recovery_weeks_max": 8,
        "status": "active",
        **overrides,
    }


async def _patient(client: AsyncClient, headers: dict[str, str]) -> int:
    return (await client.post("/api/patients", json=PATIENT, headers=headers)).json()["id"]


async def test_create_from_clinical_note(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid = await _patient(client, admin_a)
    note = (
        await client.post(
            "/api/clinical-notes",
            json={"patient_id": pid, "visited_at": "2026-10-15T10:00:00+09:00"},
            headers=admin_a,
        )
    ).json()
    await client.put(
        f"/api/clinical-notes/{note['id']}",
        json={
            "visited_at": note["visited_at"],
            "subjective": "腰が痛い\n朝がつらい",
            "assessment": "筋筋膜性腰痛",
        },
        headers=admin_a,
    )
    res = await client.post(
        "/api/treatment-plans",
        json={"patient_id": pid, "clinical_note_id": note["id"]},
        headers=admin_a,
    )
    assert res.status_code == 201, res.text
    plan = res.json()
    assert plan["chief_complaint"] == "腰が痛い"
    assert plan["title"] == "筋筋膜性腰痛"
    assert plan["start_date"] == "2026-10-15"
    assert plan["latest_consent"] is None


async def test_update_status_sets_end_date(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid = await _patient(client, admin_a)
    plan = (
        await client.post("/api/treatment-plans", json={"patient_id": pid}, headers=admin_a)
    ).json()
    res = await client.put(
        f"/api/treatment-plans/{plan['id']}",
        json=plan_body(status="completed"),
        headers=admin_a,
    )
    assert res.status_code == 200, res.text
    assert res.json()["end_date"] is not None
    res = await client.put(f"/api/treatment-plans/{plan['id']}", json=plan_body(), headers=admin_a)
    assert res.json()["end_date"] is None

    bad = plan_body(expected_recovery_weeks_min=8, expected_recovery_weeks_max=4)
    res = await client.put(f"/api/treatment-plans/{plan['id']}", json=bad, headers=admin_a)
    assert res.status_code == 422


async def test_progress_lists_notes_in_period(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid = await _patient(client, admin_a)
    for day in ("2026-10-10", "2026-10-16", "2026-10-20"):
        await client.post(
            "/api/clinical-notes",
            json={"patient_id": pid, "visited_at": f"{day}T10:00:00+09:00"},
            headers=admin_a,
        )
    plan = (
        await client.post(
            "/api/treatment-plans",
            json={"patient_id": pid, "start_date": "2026-10-15"},
            headers=admin_a,
        )
    ).json()
    res = await client.get(f"/api/treatment-plans/{plan['id']}/progress", headers=admin_a)
    assert [n["visited_at"][:10] for n in res.json()] == ["2026-10-16", "2026-10-20"]


async def test_consent_signature_and_outdated(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid = await _patient(client, admin_a)
    plan = (
        await client.post("/api/treatment-plans", json={"patient_id": pid}, headers=admin_a)
    ).json()
    await client.put(f"/api/treatment-plans/{plan['id']}", json=plan_body(), headers=admin_a)

    res = await client.post(
        f"/api/treatment-plans/{plan['id']}/consents",
        json={"signed_name": "山田 太郎", "signature_data_url": tiny_png()},
        headers=admin_a,
    )
    assert res.status_code == 201, res.text
    consent = res.json()
    assert consent["plan_snapshot"]["title"] == "腰痛改善プラン"
    assert consent["witnessed_by"]["username"] == "a-admin"

    # 署名付きURLで画像を取得できる（認証ヘッダー不要）
    img = await client.get(consent["signature_url"])
    assert img.status_code == 200
    assert img.content.startswith(b"\x89PNG")
    tampered = consent["signature_url"].replace("sig=", "sig=0")
    assert (await client.get(tampered)).status_code == 404

    detail = (await client.get(f"/api/treatment-plans/{plan['id']}", headers=admin_a)).json()
    assert detail["latest_consent"]["id"] == consent["id"]
    assert detail["consent_outdated"] is False

    # 署名後に計画を変えると再署名が必要になる
    await client.put(
        f"/api/treatment-plans/{plan['id']}",
        json=plan_body(exercise_instruction="ストレッチを毎日"),
        headers=admin_a,
    )
    detail = (await client.get(f"/api/treatment-plans/{plan['id']}", headers=admin_a)).json()
    assert detail["consent_outdated"] is True
    # ステータスの変更だけなら再署名は不要
    await client.put(
        f"/api/treatment-plans/{plan['id']}",
        json=plan_body(exercise_instruction="ストレッチを毎日", status="paused"),
        headers=admin_a,
    )


async def test_consent_rejects_non_png(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid = await _patient(client, admin_a)
    plan = (
        await client.post("/api/treatment-plans", json={"patient_id": pid}, headers=admin_a)
    ).json()
    fake = "data:image/png;base64," + base64.b64encode(b"not a png").decode()
    res = await client.post(
        f"/api/treatment-plans/{plan['id']}/consents",
        json={"signed_name": "山田", "signature_data_url": fake},
        headers=admin_a,
    )
    assert res.status_code == 422


async def test_files_endpoint_rejects_traversal(client: AsyncClient) -> None:
    res = await client.get("/api/files/../../etc/passwd", params={"exp": 9999999999, "sig": "x"})
    assert res.status_code == 404


async def test_other_clinic_isolation(
    client: AsyncClient, admin_a: dict[str, str], admin_b: dict[str, str]
) -> None:
    pid = await _patient(client, admin_a)
    assert (
        await client.post("/api/treatment-plans", json={"patient_id": pid}, headers=admin_b)
    ).status_code == 404
    plan = (
        await client.post("/api/treatment-plans", json={"patient_id": pid}, headers=admin_a)
    ).json()
    for method, url, kw in (
        ("GET", f"/api/treatment-plans/{plan['id']}", {}),
        ("PUT", f"/api/treatment-plans/{plan['id']}", {"json": plan_body()}),
        ("GET", f"/api/treatment-plans/{plan['id']}/progress", {}),
        (
            "POST",
            f"/api/treatment-plans/{plan['id']}/consents",
            {"json": {"signed_name": "x", "signature_data_url": tiny_png()}},
        ),
    ):
        res = await client.request(method, url, headers=admin_b, **kw)
        assert res.status_code == 404, (method, url)
    assert (await client.get("/api/treatment-plans", headers=admin_b)).json()["total"] == 0


def test_storage_rejects_unsafe_keys() -> None:
    from app.services.storage import storage

    for key in ("../../etc/passwd.png", "/etc/passwd.png", "signatures/../../x.png", "a/b.exe"):
        assert storage.path_for(key) is None
