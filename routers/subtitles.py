import logging
import urllib.parse
from fastapi import APIRouter, Request
from auth import check_api_key
from services.channels import get_effective_channel_ids
from services.stream_builder import find_subtitles_for_video
from tg_client import tg_client_manager
from utils import get_metadata_from_cinemeta, matches_episode

logger = logging.getLogger("stremio_addon")
router = APIRouter(tags=["subtitles"])

@router.get("/subtitles/{type}/{id}.json")
@router.get("/subtitles/{type}/{id}/{extra}.json")
@router.get("/{api_key}/subtitles/{type}/{id}.json")
@router.get("/{api_key}/subtitles/{type}/{id}/{extra}.json")
async def subtitles_handler(type: str, id: str, request: Request, extra: str = None, api_key: str = ""):
    check_api_key(api_key, request.query_params.get("api_key", ""))
    subtitles = []

    if id.startswith("tgfile_"):
        parts = id.split("_")
        if len(parts) >= 3:
            chat_id = parts[1]
            msg_id = parts[2]
            try:
                try:
                    chat_id_val = int(chat_id)
                except ValueError:
                    chat_id_val = chat_id
                msg = await tg_client_manager.get_message(int(msg_id), chat_id=chat_id_val)
                media = msg.video or msg.document or msg.audio
                video_filename = getattr(media, "file_name", "") or ""
                if video_filename:
                    channel_ids = get_effective_channel_ids(request)
                    subtitles = await find_subtitles_for_video(
                        video_filename,
                        api_key=api_key,
                        channel_ids=channel_ids,
                    )
            except Exception as e:
                logger.error(f"Failed to resolve subtitles for direct catalog ID {id}: {e}")

    elif id.startswith("tt"):
        imdb_id = id
        season = None
        episode = None
        if ":" in id:
            parts = id.split(":")
            imdb_id = parts[0]
            season = int(parts[1])
            episode = int(parts[2])
        try:
            video_filename = None
            if extra:
                decoded_extra = urllib.parse.unquote(extra)
                if "?" in decoded_extra:
                    decoded_extra = decoded_extra.split("?", 1)[0]
                params = urllib.parse.parse_qs(decoded_extra)
                if "filename" in params:
                    video_filename = params["filename"][0]
            if video_filename:
                logger.info(f"Resolving subtitles directly for filename: '{video_filename}'")
                channel_ids = get_effective_channel_ids(request)
                subtitles = await find_subtitles_for_video(
                    video_filename, api_key=api_key, channel_ids=channel_ids
                )
            else:
                meta = await get_metadata_from_cinemeta(type, imdb_id)
                movie_name = meta.get("name")
                if movie_name:
                    channel_ids = get_effective_channel_ids(request)
                    tg_results = await tg_client_manager.search_messages(
                        query=movie_name, limit=50, channel_ids=channel_ids
                    )
                    for msg in tg_results:
                        media = msg.video or msg.document or msg.audio
                        fn = getattr(media, "file_name", "") or msg.caption or ""
                        if type == "series" and not matches_episode(fn, season, episode):
                            continue
                        video_filename = fn
                        break
                    if video_filename:
                        subtitles = await find_subtitles_for_video(video_filename, api_key=api_key, cached_messages=tg_results)
        except Exception as e:
            logger.error(f"Failed to resolve subtitles for IMDb ID {id}: {e}")

    return {"subtitles": subtitles}
