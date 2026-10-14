from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.routing import APIRoute

from app.api.router import api_router
from app.core.config import settings


def _operation_id(route: APIRoute) -> str:
    # OpenAPI から生成するフロントの型名を読みやすくする（例: patients-list_patients）
    return f"{route.tags[0]}-{route.name}" if route.tags else route.name


app = FastAPI(title=settings.app_name, generate_unique_id_function=_operation_id)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
