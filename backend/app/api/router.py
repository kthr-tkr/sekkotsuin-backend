from fastapi import APIRouter

from app.api.routes import appointments, auth, clinic, clinical_notes, intakes, patients

api_router = APIRouter(prefix="/api")
api_router.include_router(auth.router)
api_router.include_router(clinic.router)
api_router.include_router(patients.router)
api_router.include_router(appointments.router)
api_router.include_router(intakes.router)
api_router.include_router(clinical_notes.router)
api_router.include_router(intakes.public_router)
