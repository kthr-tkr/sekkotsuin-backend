from httpx import AsyncClient

from tests.conftest import PATIENT


async def test_create_assigns_card_no_per_clinic(
    client: AsyncClient, admin_a: dict[str, str], admin_b: dict[str, str]
) -> None:
    r1 = await client.post("/api/patients", json=PATIENT, headers=admin_a)
    r2 = await client.post("/api/patients", json=PATIENT, headers=admin_a)
    rb = await client.post("/api/patients", json=PATIENT, headers=admin_b)
    assert r1.status_code == 201, r1.text
    assert [r1.json()["card_no"], r2.json()["card_no"]] == ["P000001", "P000002"]
    # 院ごとに独立して採番される
    assert rb.json()["card_no"] == "P000001"


async def test_search(client: AsyncClient, admin_a: dict[str, str]) -> None:
    await client.post("/api/patients", json=PATIENT, headers=admin_a)
    other = {**PATIENT, "last_name": "佐藤", "last_name_kana": "サトウ", "phone": "080-0000-0000"}
    await client.post("/api/patients", json=other, headers=admin_a)

    res = await client.get("/api/patients", params={"q": "サトウ"}, headers=admin_a)
    assert res.json()["total"] == 1
    assert res.json()["items"][0]["last_name"] == "佐藤"

    res = await client.get("/api/patients", params={"q": "P000001"}, headers=admin_a)
    assert res.json()["items"][0]["last_name"] == "山田"


async def test_validation(client: AsyncClient, admin_a: dict[str, str]) -> None:
    bad = {**PATIENT, "last_name_kana": "yamada"}
    assert (await client.post("/api/patients", json=bad, headers=admin_a)).status_code == 422


async def test_cannot_access_other_clinic(
    client: AsyncClient, admin_a: dict[str, str], admin_b: dict[str, str]
) -> None:
    pid = (await client.post("/api/patients", json=PATIENT, headers=admin_a)).json()["id"]
    assert (await client.get(f"/api/patients/{pid}", headers=admin_b)).status_code == 404
    res = await client.put(f"/api/patients/{pid}", json=PATIENT, headers=admin_b)
    assert res.status_code == 404
    assert (await client.get("/api/patients", headers=admin_b)).json()["total"] == 0


async def test_update(client: AsyncClient, admin_a: dict[str, str]) -> None:
    pid = (await client.post("/api/patients", json=PATIENT, headers=admin_a)).json()["id"]
    res = await client.put(
        f"/api/patients/{pid}", json={**PATIENT, "notes": "腰痛持ち"}, headers=admin_a
    )
    assert res.status_code == 200
    assert res.json()["notes"] == "腰痛持ち"
    assert res.json()["card_no"] == "P000001"
