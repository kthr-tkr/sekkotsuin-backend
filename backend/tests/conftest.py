import os
import tempfile

os.environ.setdefault("MEDIA_DIR", tempfile.mkdtemp(prefix="sekkotsuin-media-"))
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://app:app@localhost:5432/sekkotsuin_test")

from collections.abc import AsyncIterator  # noqa: E402

import pytest  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.db import Base, SessionLocal, engine  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Clinic, ClinicSettings, Role, TreatmentMenu, User  # noqa: E402

PASSWORD = "password123"


@pytest.fixture(scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_tables() -> AsyncIterator[None]:
    yield
    tables = ", ".join(t.name for t in reversed(Base.metadata.sorted_tables))
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture(autouse=True)
def _reset_rate_limits() -> None:
    from app.services.ratelimit import login_limiter, reset_limiter, verify_limiter

    login_limiter.clear()
    verify_limiter.clear()
    reset_limiter.clear()


@pytest.fixture
async def client() -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


async def _make_clinic(slug: str) -> dict[str, int]:
    async with SessionLocal() as db:
        clinic = Clinic(name=f"{slug} 接骨院", booking_slug=slug)
        db.add(clinic)
        await db.flush()
        db.add(ClinicSettings(clinic_id=clinic.id, closed_weekdays=["sun"]))
        users = {
            role: User(
                clinic_id=clinic.id,
                username=f"{slug}-{role.value}",
                full_name=f"{slug} {role.value}",
                role=role,
                hashed_password=hash_password(PASSWORD),
            )
            for role in Role
        }
        menu = TreatmentMenu(clinic_id=clinic.id, name="初診", duration_minutes=60)
        db.add_all([*users.values(), menu])
        await db.commit()
        return {
            "clinic_id": clinic.id,
            "menu_id": menu.id,
            **{f"{r.value}_id": u.id for r, u in users.items()},
        }


@pytest.fixture
async def clinic_a() -> dict[str, int]:
    return await _make_clinic("a")


@pytest.fixture
async def clinic_b() -> dict[str, int]:
    return await _make_clinic("b")


async def login(client: AsyncClient, username: str) -> dict[str, str]:
    res = await client.post("/api/auth/login", data={"username": username, "password": PASSWORD})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.fixture
async def admin_a(client: AsyncClient, clinic_a: dict[str, int]) -> dict[str, str]:
    return await login(client, "a-admin")


@pytest.fixture
async def reception_a(client: AsyncClient, clinic_a: dict[str, int]) -> dict[str, str]:
    return await login(client, "a-reception")


@pytest.fixture
async def admin_b(client: AsyncClient, clinic_b: dict[str, int]) -> dict[str, str]:
    return await login(client, "b-admin")


PATIENT = {
    "last_name": "山田",
    "first_name": "太郎",
    "last_name_kana": "ヤマダ",
    "first_name_kana": "タロウ",
    "birth_date": "1980-04-01",
    "phone": "090-1234-5678",
}
