from fastapi import APIRouter

from config import Config
from tg_client import tg_client_manager

router = APIRouter(tags=["channels"])


@router.get("/channels.json")
async def list_channels():
    channels = await tg_client_manager.get_channels_info()
    active_keys = {
        str(c).lstrip("@") if not isinstance(c, int) else str(c)
        for c in Config.get_active_channel_ids()
    }
    for ch in channels:
        cid = ch["id"]
        key = str(cid).lstrip("@") if not isinstance(cid, int) else str(cid)
        ch["active_by_default"] = key in active_keys
    return {"channels": channels}
