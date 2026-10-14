"""シフトと休暇。"""

from datetime import date

from fastapi import APIRouter, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api.deps import DB, AdminUser, CurrentUser, not_found
from app.models import LeaveStatus, Role, StaffLeave, StaffShift, User
from app.schemas.operations import LeaveCreate, LeaveDecision, LeaveOut, ShiftOut, ShiftUpsert
from app.services.ai.quota import month_range

router = APIRouter(tags=["schedule"])


async def _staff_or_422(db: DB, clinic_id: int, staff_id: int) -> User:
    staff = await db.get(User, staff_id)
    if staff is None or staff.clinic_id != clinic_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "スタッフが見つかりません。")
    return staff


@router.get("/shifts", response_model=list[ShiftOut])
async def list_shifts(
    db: DB,
    user: CurrentUser,
    month: str = Query(pattern=r"^\d{4}-\d{2}$", description="YYYY-MM"),
) -> list[StaffShift]:
    start, end = month_range(date.fromisoformat(f"{month}-01"))
    rows = await db.scalars(
        select(StaffShift)
        .where(
            StaffShift.clinic_id == user.clinic_id,
            StaffShift.date >= start.date(),
            StaffShift.date < end.date(),
        )
        .order_by(StaffShift.date, StaffShift.staff_id)
    )
    return list(rows)


@router.put("/shifts/{staff_id}/{day}", response_model=ShiftOut)
async def upsert_shift(
    db: DB, user: AdminUser, staff_id: int, day: date, body: ShiftUpsert
) -> StaffShift:
    await _staff_or_422(db, user.clinic_id, staff_id)
    shift = await db.scalar(
        select(StaffShift).where(StaffShift.staff_id == staff_id, StaffShift.date == day)
    )
    if shift is None:
        shift = StaffShift(clinic_id=user.clinic_id, staff_id=staff_id, date=day)
        db.add(shift)
    for k, v in body.model_dump().items():
        setattr(shift, k, v)
    await db.commit()
    await db.refresh(shift)
    return shift


@router.delete("/shifts/{staff_id}/{day}", status_code=204)
async def delete_shift(db: DB, user: AdminUser, staff_id: int, day: date) -> None:
    shift = await db.scalar(
        select(StaffShift).where(
            StaffShift.clinic_id == user.clinic_id,
            StaffShift.staff_id == staff_id,
            StaffShift.date == day,
        )
    )
    if shift is not None:
        await db.delete(shift)
        await db.commit()


async def _leave_or_404(db: DB, clinic_id: int, leave_id: int) -> StaffLeave:
    leave = await db.scalar(
        select(StaffLeave)
        .where(StaffLeave.id == leave_id)
        .options(selectinload(StaffLeave.staff))
        .execution_options(populate_existing=True)
    )
    if leave is None or leave.clinic_id != clinic_id:
        raise not_found("休暇")
    return leave


@router.get("/leaves", response_model=list[LeaveOut])
async def list_leaves(
    db: DB,
    user: CurrentUser,
    status_: LeaveStatus | None = Query(None, alias="status"),
    month: str | None = Query(None, pattern=r"^\d{4}-\d{2}$"),
) -> list[StaffLeave]:
    stmt = select(StaffLeave).where(StaffLeave.clinic_id == user.clinic_id)
    if status_:
        stmt = stmt.where(StaffLeave.status == status_)
    if month:
        start, end = month_range(date.fromisoformat(f"{month}-01"))
        stmt = stmt.where(StaffLeave.start_date < end.date(), StaffLeave.end_date >= start.date())
    rows = await db.scalars(
        stmt.options(selectinload(StaffLeave.staff)).order_by(
            StaffLeave.start_date.desc(), StaffLeave.id.desc()
        )
    )
    return list(rows)


@router.post("/leaves", response_model=LeaveOut, status_code=201)
async def request_leave(db: DB, user: CurrentUser, body: LeaveCreate) -> StaffLeave:
    staff_id = body.staff_id or user.id
    if staff_id != user.id and user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "他のスタッフの休暇は申請できません。")
    await _staff_or_422(db, user.clinic_id, staff_id)
    leave = StaffLeave(
        clinic_id=user.clinic_id,
        staff_id=staff_id,
        **body.model_dump(exclude={"staff_id"}),
    )
    # 管理者が登録する休暇は承認済みとする
    if user.role == Role.ADMIN:
        leave.status = LeaveStatus.APPROVED
        leave.decided_by_id = user.id
    db.add(leave)
    await db.commit()
    return await _leave_or_404(db, user.clinic_id, leave.id)


@router.post("/leaves/{leave_id}/decide", response_model=LeaveOut)
async def decide_leave(db: DB, user: AdminUser, leave_id: int, body: LeaveDecision) -> StaffLeave:
    leave = await _leave_or_404(db, user.clinic_id, leave_id)
    if leave.status != LeaveStatus.REQUESTED:
        raise HTTPException(status.HTTP_409_CONFLICT, "申請中の休暇のみ承認・却下できます。")
    leave.status = body.status
    leave.decided_by_id = user.id
    await db.commit()
    return await _leave_or_404(db, user.clinic_id, leave_id)


@router.post("/leaves/{leave_id}/cancel", response_model=LeaveOut)
async def cancel_leave(db: DB, user: CurrentUser, leave_id: int) -> StaffLeave:
    leave = await _leave_or_404(db, user.clinic_id, leave_id)
    if leave.staff_id != user.id and user.role != Role.ADMIN:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "自分の休暇のみ取り消せます。")
    if leave.status in (LeaveStatus.REJECTED, LeaveStatus.CANCELED):
        raise HTTPException(status.HTTP_409_CONFLICT, "この休暇は取り消せません。")
    leave.status = LeaveStatus.CANCELED
    await db.commit()
    return await _leave_or_404(db, user.clinic_id, leave_id)
