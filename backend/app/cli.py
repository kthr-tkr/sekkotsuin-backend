"""管理用コマンド。

uv run python -m app.cli create-clinic --name "さくら接骨院" --admin admin --password ...
uv run python -m app.cli seed-demo
"""

import argparse
import asyncio
import re

from sqlalchemy import select

from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models import Clinic, ClinicSettings, Role, TreatmentMenu, User


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-_")
    return slug or "clinic"


async def create_clinic(name: str, slug: str | None, admin: str, password: str) -> None:
    async with SessionLocal() as db:
        clinic = Clinic(name=name, booking_slug=slug or _slugify(name))
        db.add(clinic)
        await db.flush()
        db.add(ClinicSettings(clinic_id=clinic.id, display_name=name))
        db.add(
            User(
                clinic_id=clinic.id,
                username=admin,
                full_name="管理者",
                role=Role.ADMIN,
                hashed_password=hash_password(password),
            )
        )
        await db.commit()
        print(f"created clinic id={clinic.id} slug={clinic.booking_slug} admin={admin}")


async def seed_demo() -> None:
    """ローカル開発用のデモデータ（admin / password123）。"""
    async with SessionLocal() as db:
        if await db.scalar(select(User).where(User.username == "admin")):
            print("demo data already exists")
            return
        clinic = Clinic(name="デモ接骨院", booking_slug="demo")
        db.add(clinic)
        await db.flush()
        db.add(ClinicSettings(clinic_id=clinic.id, display_name="デモ接骨院"))
        pw = hash_password("password123")
        db.add_all(
            [
                User(
                    clinic_id=clinic.id,
                    username="admin",
                    full_name="院長 太郎",
                    role=Role.ADMIN,
                    hashed_password=pw,
                ),
                User(
                    clinic_id=clinic.id,
                    username="reception",
                    full_name="受付 花子",
                    role=Role.RECEPTION,
                    hashed_password=pw,
                ),
                User(
                    clinic_id=clinic.id,
                    username="sato",
                    full_name="佐藤 健",
                    role=Role.PRACTITIONER,
                    hashed_password=pw,
                ),
                User(
                    clinic_id=clinic.id,
                    username="suzuki",
                    full_name="鈴木 誠",
                    role=Role.PRACTITIONER,
                    hashed_password=pw,
                ),
                TreatmentMenu(
                    clinic_id=clinic.id,
                    name="初診",
                    price=3000,
                    duration_minutes=60,
                    display_order=1,
                ),
                TreatmentMenu(
                    clinic_id=clinic.id,
                    name="保険施術",
                    price=800,
                    duration_minutes=30,
                    display_order=2,
                ),
                TreatmentMenu(
                    clinic_id=clinic.id,
                    name="骨盤矯正",
                    price=5500,
                    duration_minutes=45,
                    display_order=3,
                ),
            ]
        )
        await db.commit()
        print("seeded demo clinic. login: admin / password123")


def main() -> None:
    parser = argparse.ArgumentParser(prog="app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-clinic")
    p.add_argument("--name", required=True)
    p.add_argument("--slug")
    p.add_argument("--admin", required=True)
    p.add_argument("--password", required=True)
    sub.add_parser("seed-demo")
    args = parser.parse_args()

    if args.command == "create-clinic":
        asyncio.run(create_clinic(args.name, args.slug, args.admin, args.password))
    elif args.command == "seed-demo":
        asyncio.run(seed_demo())


if __name__ == "__main__":
    main()
