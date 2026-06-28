from fastapi import APIRouter
from fastapi.responses import JSONResponse
from auth import get_manifest
from config import Config

router = APIRouter(tags=["manifest"])

@router.api_route("/manifest.json", methods=["GET", "HEAD"])
@router.api_route("/{api_key}/manifest.json", methods=["GET", "HEAD"])
async def manifest_endpoint(api_key: str = ""):
    if Config.API_KEY and api_key != Config.API_KEY:
        return JSONResponse({"detail": "Unauthorized: Invalid API Key"}, status_code=403)
    return get_manifest(api_key)
