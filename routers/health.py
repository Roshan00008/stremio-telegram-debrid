from fastapi import APIRouter
from fastapi.responses import JSONResponse
from tg_client import tg_client_manager

router = APIRouter(tags=["health"])

@router.get("/health")
async def health_check():
    info = await tg_client_manager.check_health()
    status_code = 200 if info["status"] == "healthy" else 503
    return JSONResponse(info, status_code=status_code)
