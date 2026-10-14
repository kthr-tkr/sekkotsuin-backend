from fastapi import APIRouter

from app.api.routes import (
    ai,
    appointments,
    auth,
    clinic,
    clinical_notes,
    files,
    intakes,
    kpi,
    patients,
    posture,
    sales,
    schedule,
    treatment_plans,
)

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(clinic.router)
api_router.include_router(patients.router)
api_router.include_router(appointments.router)
api_router.include_router(intakes.router)
api_router.include_router(clinical_notes.router)
api_router.include_router(treatment_plans.router)
api_router.include_router(posture.router)
api_router.include_router(sales.router)
api_router.include_router(schedule.router)
api_router.include_router(kpi.router)
api_router.include_router(ai.router)
api_router.include_router(files.router)
api_router.include_router(intakes.public_router)
