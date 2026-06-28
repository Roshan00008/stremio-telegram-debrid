import logging
from fastapi import APIRouter, Depends
from auth import verify_api_key
from services.stream_builder import build_meta_from_ref
from services.tg_id_parser import parse_tg_id

logger = logging.getLogger("stremio_addon")
router = APIRouter(tags=["meta"])

@router.get("/meta/{type}/{meta_id}.json", dependencies=[Depends(verify_api_key)])
@router.get("/{api_key}/meta/{type}/{meta_id}.json", dependencies=[Depends(verify_api_key)])
async def meta_handler(type: str, meta_id: str, api_key: str = ""):
    if not meta_id.startswith("tgfile_"):
        return {"meta": {}}
    try:
        ref = parse_tg_id(meta_id)
        if not ref:
            return {"meta": {}}
        meta = await build_meta_from_ref(meta_id, ref, type)
        return {"meta": meta}
    except Exception as e:
        logger.error(f"Failed to generate metadata for {meta_id}: {e}")
        return {"meta": {}}
