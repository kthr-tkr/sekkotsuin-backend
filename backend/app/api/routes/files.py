from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.api.deps import not_found
from app.services.storage import storage, verify_signature

router = APIRouter(prefix="/files", tags=["files"])


@router.get("/{key:path}", include_in_schema=False)
async def get_file(key: str, exp: int = Query(), sig: str = Query()) -> FileResponse:
    path = storage.path_for(key)
    if path is None or not verify_signature(key, exp, sig):
        raise not_found("ファイル")
    return FileResponse(path, headers={"Cache-Control": "private, max-age=600"})
