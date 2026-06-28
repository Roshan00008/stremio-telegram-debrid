import urllib.parse
from typing import List, Optional, Union

from fastapi import HTTPException, Request

from config import Config


def channel_key(channel_id: Union[int, str]) -> str:
    if isinstance(channel_id, int):
        return str(channel_id)
    return str(channel_id).strip().lstrip("@")


def _allowed_channel_map() -> dict:
    return {channel_key(cid): cid for cid in Config.get_channel_ids()}


def filter_to_allowed(channel_ids: List[Union[int, str]]) -> List[Union[int, str]]:
    allowed = _allowed_channel_map()
    result = []
    seen = set()
    for cid in channel_ids:
        key = channel_key(cid)
        if key in allowed and key not in seen:
            seen.add(key)
            result.append(allowed[key])
    return result


def get_effective_channel_ids(
    request: Optional[Request] = None,
    channels_param: str = "",
) -> List[Union[int, str]]:
    default = Config.get_active_channel_ids()
    raw = channels_param.strip()
    if not raw and request is not None:
        raw = request.query_params.get("channels", "").strip()

    if raw:
        selected = filter_to_allowed(Config._parse_channel_ids(raw))
        return selected if selected else default
    return default


def assert_channel_allowed(
    chat_id: Union[int, str],
    request: Optional[Request] = None,
) -> None:
    key = channel_key(chat_id)
    if key not in _allowed_channel_map():
        raise HTTPException(status_code=403, detail="Channel not configured")

    active_keys = {channel_key(c) for c in get_effective_channel_ids(request)}
    if key not in active_keys:
        raise HTTPException(status_code=403, detail="Channel not selected")


def build_addon_query_suffix(
    api_key: str = "",
    request: Optional[Request] = None,
) -> str:
    parts = []
    if api_key:
        parts.append(f"api_key={urllib.parse.quote(api_key)}")
    elif request is not None:
        qk = request.query_params.get("api_key", "").strip()
        if qk:
            parts.append(f"api_key={urllib.parse.quote(qk)}")
    channels = ""
    if request is not None:
        channels = request.query_params.get("channels", "").strip()
    if channels:
        parts.append(f"channels={urllib.parse.quote(channels)}")
    return ("?" + "&".join(parts)) if parts else ""


def channels_query_suffix(request: Optional[Request] = None, api_key: str = "") -> str:
    return build_addon_query_suffix(api_key=api_key, request=request)
