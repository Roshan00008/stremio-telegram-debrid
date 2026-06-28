from fastapi import APIRouter, Request
from auth import check_api_key
from services.channels import build_addon_query_suffix, get_effective_channel_ids
from services.stream_builder import build_streams_from_imdb, resolve_tgfile_streams

router = APIRouter(tags=["stream"])

@router.get("/stream/{type}/{stream_id}.json")
@router.get("/{api_key}/stream/{type}/{stream_id}.json")
async def stream_handler(type: str, stream_id: str, request: Request, api_key: str = ""):
    check_api_key(api_key, request.query_params.get("api_key", ""))
    query_param = build_addon_query_suffix(api_key=api_key, request=request)
    channel_ids = get_effective_channel_ids(request)
    streams = []
    if stream_id.startswith("tgfile_"):
        streams = await resolve_tgfile_streams(
            stream_id, query_param, api_key, channel_ids=channel_ids
        )
    elif stream_id.startswith("tt"):
        streams = await build_streams_from_imdb(
            type, stream_id, query_param, api_key, channel_ids=channel_ids
        )
    return {"streams": streams}
