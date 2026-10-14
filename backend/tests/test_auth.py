from httpx import AsyncClient

from tests.conftest import PASSWORD


async def test_login_and_me(client: AsyncClient, admin_a: dict[str, str]) -> None:
    res = await client.get("/api/auth/me", headers=admin_a)
    assert res.status_code == 200
    assert res.json()["username"] == "a-admin"
    assert res.json()["role"] == "admin"


async def test_login_wrong_password(client: AsyncClient, clinic_a: dict[str, int]) -> None:
    res = await client.post(
        "/api/auth/login", data={"username": "a-admin", "password": PASSWORD + "x"}
    )
    assert res.status_code == 401


async def test_requires_token(client: AsyncClient) -> None:
    assert (await client.get("/api/patients")).status_code == 401
    bad = {"Authorization": "Bearer nope"}
    assert (await client.get("/api/patients", headers=bad)).status_code == 401


async def test_admin_only_endpoints(
    client: AsyncClient, reception_a: dict[str, str], admin_a: dict[str, str]
) -> None:
    menu = {"name": "骨盤矯正", "duration_minutes": 45, "price": 5500}
    res = await client.post("/api/treatment-menus", json=menu, headers=reception_a)
    assert res.status_code == 403
    res = await client.post("/api/treatment-menus", json=menu, headers=admin_a)
    assert res.status_code == 201

    staff = {"username": "new-staff", "full_name": "新人", "password": "longpassword"}
    assert (await client.post("/api/staff", json=staff, headers=reception_a)).status_code == 403
    assert (await client.post("/api/staff", json=staff, headers=admin_a)).status_code == 201
    assert (await client.post("/api/staff", json=staff, headers=admin_a)).status_code == 409
