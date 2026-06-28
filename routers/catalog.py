import logging
import urllib.parse
from fastapi import APIRouter, Depends, Request
from auth import verify_api_key
from services.channels import get_effective_channel_ids
from services.grouping import group_tg_messages
from services.stream_builder import build_catalog_metas
from tg_client import tg_client_manager

logger = logging.getLogger("stremio_addon")
router = APIRouter(tags=["catalog"])

@router.get("/catalog/{type}/{catalog_id}.json", dependencies=[Depends(verify_api_key)])
@router.get("/catalog/{type}/{catalog_id}/{extra}.json", dependencies=[Depends(verify_api_key)])
@router.get("/{api_key}/catalog/{type}/{catalog_id}.json", dependencies=[Depends(verify_api_key)])
@router.get("/{api_key}/catalog/{type}/{catalog_id}/{extra}.json", dependencies=[Depends(verify_api_key)])
async def catalog_handler(
    request: Request,
    type: str,
    catalog_id: str,
    extra: str = None,
    api_key: str = "",
):
    if type not in ["movie", "series"]:
        return {"metas": []}
    query = ""
    if extra:
        params = urllib.parse.parse_qs(extra)
        if "search" in params:
            query = params["search"][0]
    channel_ids = get_effective_channel_ids(request)
    try:
        messages = await tg_client_manager.search_messages(
            query=query, limit=50, channel_ids=channel_ids
        )
    except Exception as e:
        logger.error(f"Catalog search failed: {e}")
        return {"metas": []}
    grouped_items = group_tg_messages(messages)
    metas = await build_catalog_metas(grouped_items, type)
    return {"metas": metas}
