from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, AdminUser, CurrentUser, not_found
from app.core.security import hash_password
from app.models import Clinic, ClinicSettings, Role, TreatmentMenu, User
from app.schemas.auth import UserOut
from app.schemas.clinic import (
    ClinicOut,
    ClinicSettingsOut,
    ClinicSettingsUpdate,
    TreatmentMenuCreate,
    TreatmentMenuOut,
    TreatmentMenuUpdate,
)
from app.schemas.staff import StaffCreate
from app.services.appointments import get_clinic_settings

router = APIRouter(tags=["clinic"])


@router.get("/clinic", response_model=ClinicOut)
async def get_clinic(db: DB, user: CurrentUser) -> Clinic:
    clinic = await db.get(Clinic, user.clinic_id)
    if clinic is None:
        raise not_found("院")
    return clinic


@router.get("/clinic/settings", response_model=ClinicSettingsOut)
async def get_settings(db: DB, user: CurrentUser) -> ClinicSettings:
    cs = await get_clinic_settings(db, user.clinic_id)
    await db.commit()
    return cs


@router.put("/clinic/settings", response_model=ClinicSettingsOut)
async def update_settings(db: DB, user: AdminUser, body: ClinicSettingsUpdate) -> ClinicSettings:
    cs = await get_clinic_settings(db, user.clinic_id)
    for key, value in body.model_dump().items():
        setattr(cs, key, value)
    await db.commit()
    await db.refresh(cs)
    return cs


# --- 施術メニュー ---


@router.get("/treatment-menus", response_model=list[TreatmentMenuOut])
async def list_menus(db: DB, user: CurrentUser, active_only: bool = False) -> list[TreatmentMenu]:
    stmt = select(TreatmentMenu).where(TreatmentMenu.clinic_id == user.clinic_id)
    if active_only:
        stmt = stmt.where(TreatmentMenu.is_active.is_(True))
    stmt = stmt.order_by(TreatmentMenu.display_order, TreatmentMenu.name, TreatmentMenu.id)
    return list(await db.scalars(stmt))


@router.post("/treatment-menus", response_model=TreatmentMenuOut, status_code=201)
async def create_menu(db: DB, user: AdminUser, body: TreatmentMenuCreate) -> TreatmentMenu:
    menu = TreatmentMenu(clinic_id=user.clinic_id, **body.model_dump())
    db.add(menu)
    await db.commit()
    await db.refresh(menu)
    return menu


async def _get_menu(db: DB, clinic_id: int, menu_id: int) -> TreatmentMenu:
    menu = await db.get(TreatmentMenu, menu_id)
    if menu is None or menu.clinic_id != clinic_id:
        raise not_found("施術メニュー")
    return menu


@router.put("/treatment-menus/{menu_id}", response_model=TreatmentMenuOut)
async def update_menu(
    db: DB, user: AdminUser, menu_id: int, body: TreatmentMenuUpdate
) -> TreatmentMenu:
    menu = await _get_menu(db, user.clinic_id, menu_id)
    for key, value in body.model_dump().items():
        setattr(menu, key, value)
    await db.commit()
    await db.refresh(menu)
    return menu


@router.delete("/treatment-menus/{menu_id}", status_code=204)
async def delete_menu(db: DB, user: AdminUser, menu_id: int) -> None:
    menu = await _get_menu(db, user.clinic_id, menu_id)
    await db.delete(menu)
    await db.commit()


# --- スタッフ ---


@router.get("/staff", response_model=list[UserOut])
async def list_staff(db: DB, user: CurrentUser, role: Role | None = None) -> list[User]:
    stmt = select(User).where(User.clinic_id == user.clinic_id, User.is_active.is_(True))
    if role is not None:
        stmt = stmt.where(User.role == role)
    return list(await db.scalars(stmt.order_by(User.id)))


@router.post("/staff", response_model=UserOut, status_code=201)
async def create_staff(db: DB, user: AdminUser, body: StaffCreate) -> User:
    staff = User(
        clinic_id=user.clinic_id,
        username=body.username,
        full_name=body.full_name,
        role=body.role,
        hashed_password=hash_password(body.password),
    )
    db.add(staff)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "このユーザー名は既に使われています。") from e
    await db.refresh(staff)
    return staff
