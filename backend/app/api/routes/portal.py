"""患者向けポータル（院ごとの Web 予約とマイページ）。

- /portal/{slug}/...: 認証なし（院の公開情報・空き枠・登録・ログイン）
- /me/...: 患者トークン（typ=patient）で認証
"""

import secrets
from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import DB, not_found
from app.core.config import settings
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    verify_password,
)
from app.models import (
    Appointment,
    AppointmentStatus,
    BookingSource,
    Clinic,
    ClinicSettings,
    Intake,
    Patient,
    PatientAccount,
    TreatmentMenu,
)
from app.models.appointment import BLOCKING_STATUSES
from app.schemas.portal import (
    MeOut,
    MeUpdate,
    MyAppointment,
    MyBookingCreate,
    PortalClinic,
    PortalLink,
    PortalLogin,
    PortalMenu,
    PortalRegister,
    PortalSlot,
    PortalToken,
)
from app.services import appointments as appt_svc
from app.services.patients import next_card_no
from app.services.ratelimit import login_limiter, verify_limiter

public_router = APIRouter(prefix="/portal/{slug}", tags=["portal"])
me_router = APIRouter(prefix="/me", tags=["portal"])

MAX_UPCOMING = 3  # 1人が持てる将来の予約の数
MIN_LEAD = timedelta(hours=1)  # 予約は開始の1時間前まで


def _invalid(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, msg)


async def _clinic(db: DB, slug: str) -> tuple[Clinic, ClinicSettings]:
    clinic = await db.scalar(select(Clinic).where(Clinic.booking_slug == slug))
    if clinic is None:
        raise not_found("院")
    cs = await appt_svc.get_clinic_settings(db, clinic.id)
    if not cs.portal_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "この院は Web 予約を受け付けていません。")
    return clinic, cs


async def _active_menu(db: DB, clinic_id: int, menu_id: int) -> TreatmentMenu:
    menu = await db.get(TreatmentMenu, menu_id)
    if menu is None or menu.clinic_id != clinic_id or not menu.is_active:
        raise _invalid("施術メニューが見つかりません。")
    return menu


def _issue_token(account: PatientAccount) -> PortalToken:
    return PortalToken(access_token=create_access_token(account.id, "patient"))


# --- 公開 ---


@public_router.get("", response_model=PortalClinic)
async def portal_clinic(db: DB, slug: str) -> PortalClinic:
    clinic, cs = await _clinic(db, slug)
    menus = await db.scalars(
        select(TreatmentMenu)
        .where(TreatmentMenu.clinic_id == clinic.id, TreatmentMenu.is_active.is_(True))
        .order_by(TreatmentMenu.display_order, TreatmentMenu.name, TreatmentMenu.id)
    )
    await db.commit()
    return PortalClinic(
        name=cs.display_name or clinic.name,
        booking_slug=clinic.booking_slug,
        phone=cs.phone,
        address=cs.address,
        booking_description=cs.booking_description,
        business_start_time=cs.business_start_time,
        business_end_time=cs.business_end_time,
        closed_weekdays=cs.closed_weekdays or [],
        booking_window_days=cs.portal_booking_window_days,
        cancel_deadline_hours=cs.portal_cancel_deadline_hours,
        menus=[
            PortalMenu(
                id=m.id,
                name=m.name,
                description=m.description,
                price=m.price,
                duration_minutes=m.duration_minutes,
            )
            for m in menus
        ],
    )


def _bookable(start: datetime, cs: ClinicSettings) -> bool:
    now = datetime.now(UTC)
    return now + MIN_LEAD <= start <= now + timedelta(days=cs.portal_booking_window_days)


@public_router.get("/availability", response_model=list[PortalSlot])
async def portal_availability(
    db: DB, slug: str, day: date = Query(alias="date"), menu_id: int = Query()
) -> list[PortalSlot]:
    """予約できる枠（担当者などの内部情報は返さない）。"""
    clinic, cs = await _clinic(db, slug)
    menu = await _active_menu(db, clinic.id, menu_id)
    slots = await appt_svc.availability(
        db, clinic_id=clinic.id, day=day, duration_minutes=menu.duration_minutes, staff_id=None
    )
    await db.commit()
    return [PortalSlot(start_at=s, end_at=e, available=a and _bookable(s, cs)) for s, e, a in slots]


async def _create_account(
    db: DB, clinic_id: int, patient: Patient, email: str, password: str
) -> PatientAccount:
    account = PatientAccount(
        clinic_id=clinic_id,
        patient_id=patient.id,
        email=email.lower(),
        hashed_password=hash_password(password),
        last_login_at=datetime.now(UTC),
    )
    db.add(account)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "このメールアドレスは既に登録されています。"
        ) from e
    return account


@public_router.post("/register", response_model=PortalToken, status_code=201)
async def portal_register(db: DB, slug: str, body: PortalRegister, request: Request) -> PortalToken:
    """初めての方の登録（患者情報とアカウントを作る）。"""
    verify_limiter.hit(f"register:{request.client.host if request.client else ''}")
    clinic, _ = await _clinic(db, slug)
    exists = await db.scalar(
        select(PatientAccount.id).where(
            PatientAccount.clinic_id == clinic.id, PatientAccount.email == body.email.lower()
        )
    )
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "このメールアドレスは既に登録されています。")
    # 来院歴のある方は本人確認からアカウントを作ってもらう（患者情報の重複を防ぐ）
    same = await db.scalar(
        select(func.count()).where(
            Patient.clinic_id == clinic.id,
            Patient.last_name == body.last_name,
            Patient.first_name == body.first_name,
            Patient.birth_date == body.birth_date,
            Patient.phone == body.phone,
        )
    )
    if same:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "既に患者情報が登録されています。「来院したことがある方」から登録してください。",
        )

    for _ in range(3):
        patient = Patient(
            clinic_id=clinic.id,
            card_no=await next_card_no(db, clinic.id),
            **body.model_dump(exclude={"email", "password"}),
            email=body.email.lower(),
        )
        db.add(patient)
        try:
            await db.flush()
            break
        except IntegrityError:
            await db.rollback()
    else:
        raise HTTPException(status.HTTP_409_CONFLICT, "登録に失敗しました。再試行してください。")
    account = await _create_account(db, clinic.id, patient, body.email, body.password)
    return _issue_token(account)


def _normalize_phone(phone: str) -> str:
    return "".join(ch for ch in phone if ch.isdigit())


@public_router.post("/link", response_model=PortalToken, status_code=201)
async def portal_link(db: DB, slug: str, body: PortalLink, request: Request) -> PortalToken:
    """来院歴のある方: 氏名・生年月日・電話番号で本人確認し、アカウントを作る。"""
    verify_limiter.hit(f"link:{request.client.host if request.client else ''}")
    clinic, _ = await _clinic(db, slug)
    candidates = [
        p
        for p in await db.scalars(
            select(Patient).where(
                Patient.clinic_id == clinic.id,
                Patient.last_name == body.last_name.strip(),
                Patient.first_name == body.first_name.strip(),
                Patient.birth_date == body.birth_date,
            )
        )
        if _normalize_phone(p.phone) == _normalize_phone(body.phone)
    ]
    not_matched = HTTPException(
        status.HTTP_404_NOT_FOUND,
        "入力内容と一致する患者情報が見つかりませんでした。院にお問い合わせください。",
    )
    if len(candidates) != 1:
        raise not_matched
    patient = candidates[0]
    if await db.scalar(select(PatientAccount.id).where(PatientAccount.patient_id == patient.id)):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "既にアカウントがあります。ログインしてください。"
        )
    if not patient.email:
        patient.email = body.email.lower()
    account = await _create_account(db, clinic.id, patient, body.email, body.password)
    return _issue_token(account)


# 存在しないアカウントでもパスワード照合の時間をかけ、応答時間から存在を推測されないようにする
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


@public_router.post("/login", response_model=PortalToken)
async def portal_login(db: DB, slug: str, body: PortalLogin) -> PortalToken:
    clinic, _ = await _clinic(db, slug)
    login_id = body.login_id.strip().lower()
    key = f"login:{clinic.id}:{login_id}"
    login_limiter.hit(key)

    if "@" in login_id:
        stmt = select(PatientAccount).where(
            PatientAccount.clinic_id == clinic.id, PatientAccount.email == login_id
        )
    else:
        stmt = (
            select(PatientAccount)
            .join(Patient, Patient.id == PatientAccount.patient_id)
            .where(Patient.clinic_id == clinic.id, func.lower(Patient.card_no) == login_id)
        )
    account = await db.scalar(stmt)
    # アカウントの有無で応答を変えない（存在確認に使われないように、照合も必ず行う）
    hashed = account.hashed_password if account else _DUMMY_HASH
    ok = verify_password(body.password, hashed)
    if account is None or not ok or not account.is_active:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "メールアドレス（または診察券番号）かパスワードが正しくありません。",
        )
    login_limiter.reset(key)
    account.last_login_at = datetime.now(UTC)
    await db.commit()
    return _issue_token(account)


# --- マイページ（患者トークン） ---

bearer = HTTPBearer(auto_error=False)


async def current_account(
    db: DB, cred: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]
) -> PatientAccount:
    unauthorized = HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        "ログインが必要です。",
        headers={"WWW-Authenticate": "Bearer"},
    )
    sub = decode_access_token(cred.credentials, "patient") if cred else None
    if sub is None or not sub.isdigit():
        raise unauthorized
    account = await db.get(PatientAccount, int(sub))
    if account is None or not account.is_active:
        raise unauthorized
    return account


Account = Annotated[PatientAccount, Depends(current_account)]


async def _me_out(db: DB, account: PatientAccount) -> MeOut:
    patient = await db.get(Patient, account.patient_id)
    clinic = await db.get(Clinic, account.clinic_id)
    assert patient is not None and clinic is not None
    cs = await appt_svc.get_clinic_settings(db, clinic.id)
    return MeOut(
        patient_id=patient.id,
        card_no=patient.card_no,
        last_name=patient.last_name,
        first_name=patient.first_name,
        last_name_kana=patient.last_name_kana,
        first_name_kana=patient.first_name_kana,
        birth_date=patient.birth_date,
        phone=patient.phone,
        email=account.email,
        address=patient.address,
        clinic_name=cs.display_name or clinic.name,
        clinic_slug=clinic.booking_slug,
    )


@me_router.get("", response_model=MeOut)
async def me(db: DB, account: Account) -> MeOut:
    out = await _me_out(db, account)
    await db.commit()
    return out


@me_router.put("", response_model=MeOut)
async def update_me(db: DB, account: Account, body: MeUpdate) -> MeOut:
    patient = await db.get(Patient, account.patient_id)
    assert patient is not None
    patient.phone = body.phone
    patient.address = body.address
    await db.commit()
    return await _me_out(db, account)


def _can_cancel(a: Appointment, cs: ClinicSettings) -> bool:
    return a.status in (
        AppointmentStatus.PENDING,
        AppointmentStatus.BOOKED,
    ) and a.start_at - timedelta(hours=cs.portal_cancel_deadline_hours) > datetime.now(UTC)


@me_router.get("/appointments", response_model=list[MyAppointment])
async def my_appointments(db: DB, account: Account) -> list[MyAppointment]:
    cs = await appt_svc.get_clinic_settings(db, account.clinic_id)
    appts = list(
        await db.scalars(
            select(Appointment)
            .where(
                Appointment.clinic_id == account.clinic_id,
                Appointment.patient_id == account.patient_id,
            )
            .order_by(Appointment.start_at.desc())
            .limit(50)
        )
    )
    intakes = {
        i.appointment_id: i
        for i in await db.scalars(
            select(Intake).where(Intake.appointment_id.in_([a.id for a in appts]))
        )
    }
    now = datetime.now(UTC)
    out = []
    for a in appts:
        intake = intakes.get(a.id)
        token = (
            intake.access_token
            if intake and intake.submitted_at is None and intake.token_expires_at > now
            else None
        )
        out.append(
            MyAppointment(
                id=a.id,
                start_at=a.start_at,
                end_at=a.end_at,
                menu_name=a.menu_name,
                status=a.status,
                can_cancel=_can_cancel(a, cs),
                intake_token=token,
            )
        )
    await db.commit()
    return out


@me_router.post("/appointments", response_model=MyAppointment, status_code=201)
async def book(db: DB, account: Account, body: MyBookingCreate) -> MyAppointment:
    """Web 予約。「問診待ち」で登録し、Web 問診の URL を発行する。"""
    cs = await appt_svc.get_clinic_settings(db, account.clinic_id)
    if not cs.portal_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "現在 Web 予約を受け付けていません。")
    # 院の設定行をロックして、同じ枠への同時予約を直列にする
    await db.execute(select(ClinicSettings).where(ClinicSettings.id == cs.id).with_for_update())
    menu = await _active_menu(db, account.clinic_id, body.treatment_menu_id)
    if not _bookable(body.start_at, cs):
        raise _invalid(
            f"予約は開始の1時間前から{cs.portal_booking_window_days}日先までの枠を選んでください。"
        )

    upcoming = await db.scalar(
        select(func.count()).where(
            Appointment.patient_id == account.patient_id,
            Appointment.status.in_(BLOCKING_STATUSES),
            Appointment.start_at > datetime.now(UTC),
        )
    )
    if (upcoming or 0) >= MAX_UPCOMING:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Web で予約できるのは {MAX_UPCOMING} 件までです。変更は院にお問い合わせください。",
        )

    day = body.start_at.astimezone(settings.tz).date()
    slots = await appt_svc.availability(
        db,
        clinic_id=account.clinic_id,
        day=day,
        duration_minutes=menu.duration_minutes,
        staff_id=None,
    )
    if not any(s == body.start_at and available for s, _, available in slots):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "選んだ時間は予約が埋まりました。別の時間を選んでください。",
        )

    appt = Appointment(
        clinic_id=account.clinic_id,
        patient_id=account.patient_id,
        treatment_menu_id=menu.id,
        menu_name=menu.name,
        start_at=body.start_at,
        end_at=body.start_at + timedelta(minutes=menu.duration_minutes),
        status=AppointmentStatus.PENDING,
        booking_source=BookingSource.HP,
        notes=body.notes,
    )
    db.add(appt)
    await db.flush()
    intake = Intake(
        clinic_id=account.clinic_id,
        patient_id=account.patient_id,
        appointment_id=appt.id,
        access_token=secrets.token_urlsafe(32),
        token_expires_at=datetime.now(UTC) + timedelta(days=settings.intake_token_expire_days),
        payload={},
    )
    db.add(intake)
    await db.commit()
    return MyAppointment(
        id=appt.id,
        start_at=appt.start_at,
        end_at=appt.end_at,
        menu_name=appt.menu_name,
        status=appt.status,
        can_cancel=_can_cancel(appt, cs),
        intake_token=intake.access_token,
    )


@me_router.post("/appointments/{appointment_id}/cancel", response_model=MyAppointment)
async def cancel(db: DB, account: Account, appointment_id: int) -> MyAppointment:
    appt = await db.get(Appointment, appointment_id)
    if appt is None or appt.clinic_id != account.clinic_id or appt.patient_id != account.patient_id:
        raise not_found("予約")
    cs = await appt_svc.get_clinic_settings(db, account.clinic_id)
    if not _can_cancel(appt, cs):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"予約の{cs.portal_cancel_deadline_hours}時間前を過ぎたため、"
            "Web ではキャンセルできません。院にお電話ください。",
        )
    appt.status = AppointmentStatus.CANCELLED
    await db.commit()
    return MyAppointment(
        id=appt.id,
        start_at=appt.start_at,
        end_at=appt.end_at,
        menu_name=appt.menu_name,
        status=appt.status,
        can_cancel=False,
    )
