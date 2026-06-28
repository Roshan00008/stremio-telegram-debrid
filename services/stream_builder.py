import logging
import urllib.parse
from typing import Optional

from config import Config
from services.channels import channel_key
from services.grouping import group_tg_messages
from services.tg_id_parser import TgFileRef, parse_tg_id
from tg_client import tg_client_manager
from utils import (
    format_size,
    get_metadata_from_cinemeta,
    get_search_query_from_filename,
    is_video_file,
    matches_episode,
    matches_subtitle,
    matches_title,
    parse_split_info,
)
from zip_helper import list_zip_files

logger = logging.getLogger("stream_builder")

NOT_WEB_READY = {"notWebReady": True}


def logo_url() -> Optional[str]:
    if getattr(Config, "ADDON_URL", None):
        return f"{Config.ADDON_URL}/stremio_telegram_logo.png"
    return None


async def find_subtitles_for_video(
    video_filename: str,
    api_key: str = "",
    cached_messages=None,
    channel_ids=None,
) -> list:
    subtitles = []
    search_results = cached_messages or []
    query_param = f"?api_key={api_key}" if api_key else ""

    if not search_results:
        query = get_search_query_from_filename(video_filename)
        if query:
            try:
                search_results = await tg_client_manager.search_messages(
                    query=query, limit=20, channel_ids=channel_ids
                )
            except Exception as e:
                logger.error(f"Subtitle search failed for '{query}': {e}")

    seen_msg_ids = set()
    for msg in search_results:
        if msg.id in seen_msg_ids:
            continue

        doc = msg.document or msg.audio or msg.video
        if not doc:
            continue

        sub_fn = getattr(doc, "file_name", "") or ""
        if sub_fn.lower().endswith((".srt", ".vtt", ".ass")):
            if matches_subtitle(video_filename, sub_fn):
                seen_msg_ids.add(msg.id)

                lang = "eng"
                sub_fn_lower = sub_fn.lower()
                if ".spa" in sub_fn_lower or "spanish" in sub_fn_lower:
                    lang = "spa"
                elif ".fre" in sub_fn_lower or "french" in sub_fn_lower:
                    lang = "fre"

                subtitles.append({
                    "id": f"tgsub_{msg.chat.id}_{msg.id}",
                    "url": (
                        f"{Config.ADDON_URL}/stream/subtitle/{msg.chat.id}/{msg.id}/"
                        f"{urllib.parse.quote(sub_fn)}{query_param}"
                    ),
                    "lang": lang,
                })

    return subtitles


def _msg_ids_str(message_ids: list[int]) -> str:
    return ",".join(str(x) for x in message_ids)


async def _append_zip_metas(
    metas: list,
    messages,
    archive_name: str,
    type_: str,
    id_prefix: str,
    chat_id,
    msg_ids: str,
) -> bool:
    try:
        entries = await list_zip_files(tg_client_manager.client, messages)
        video_entries = [e for e in entries if is_video_file(e.filename)]
        if not video_entries:
            return False
        for entry in video_entries:
            tg_id = f"{id_prefix}_{chat_id}_{msg_ids}//{entry.filename}"
            metas.append({
                "id": tg_id,
                "type": type_,
                "name": entry.filename,
                "description": (
                    f"💾 Telegram ZIP Entry\n📦 Size: {format_size(entry.file_size)}\n"
                    f"📂 ZIP Archive: {archive_name}"
                ),
                "poster": logo_url(),
            })
        return True
    except Exception as e:
        logger.error(f"Error reading ZIP archive '{archive_name}': {e}")
        return False


async def build_catalog_metas(grouped_items: list, type_: str) -> list:
    metas = []
    poster = logo_url()

    for item in grouped_items:
        if isinstance(item, tuple):
            base_name, parts = item
            total_size = sum(
                (x.video or x.document or x.audio).file_size
                for x in parts
                if (x.video or x.document or x.audio)
            )
            first_msg = parts[0]
            chat_id = first_msg.chat.id
            msg_ids = _msg_ids_str([x.id for x in parts])

            is_zip = False
            if base_name.lower().endswith(".zip"):
                is_zip = await _append_zip_metas(
                    metas, parts, base_name, type_, "tgfile_splitzip", chat_id, msg_ids
                )

            if not is_zip:
                metas.append({
                    "id": f"tgfile_split_{chat_id}_{msg_ids}",
                    "type": type_,
                    "name": base_name,
                    "description": (
                        f"💾 Telegram File (Split Parts: {len(parts)})\n"
                        f"📦 Total Size: {format_size(total_size)}"
                    ),
                    "poster": poster,
                })
        else:
            msg = item
            media = msg.video or msg.document or msg.audio
            file_name = getattr(media, "file_name", None) or msg.caption or f"Telegram File {msg.id}"
            file_size = media.file_size
            caption = msg.caption or ""

            is_zip = False
            if file_name.lower().endswith(".zip"):
                is_zip = await _append_zip_metas(
                    metas, msg, file_name, type_, "tgfile_zip", msg.chat.id, str(msg.id)
                )

            if not is_zip:
                metas.append({
                    "id": f"tgfile_{msg.chat.id}_{msg.id}",
                    "type": type_,
                    "name": file_name,
                    "description": (
                        f"💾 Telegram File\n📦 Size: {format_size(file_size)}\n💬 {caption}"
                        if caption
                        else f"💾 Telegram File\n📦 Size: {format_size(file_size)}"
                    ),
                    "poster": poster,
                })

    return metas


async def build_meta_from_ref(meta_id: str, ref: TgFileRef, type_: str) -> dict:
    messages = await tg_client_manager.get_messages_batch(ref.message_ids, chat_id=ref.chat_id)
    if not messages:
        return {}

    first_msg = messages[0]
    media = first_msg.video or first_msg.document or first_msg.audio
    first_fn = getattr(media, "file_name", "video.mp4") or "video.mp4"

    if ref.zip_entry_filename:
        file_name = ref.zip_entry_filename
        file_size = 0
        zip_entries = await list_zip_files(tg_client_manager.client, messages)
        for entry in zip_entries:
            if entry.filename == ref.zip_entry_filename:
                file_size = entry.file_size
                break
        description = (
            f"💾 Telegram ZIP Entry\n📦 Size: {format_size(file_size)}\n"
            f"📂 ZIP Archive: {first_fn}"
        )
    elif ref.is_split:
        base_name, _ = parse_split_info(first_fn)
        file_name = base_name or first_fn
        total_size = sum(
            (x.video or x.document or x.audio).file_size
            for x in messages
            if (x.video or x.document or x.audio)
        )
        description = (
            f"💾 Telegram File (Split Parts: {len(messages)})\n"
            f"📦 Total Size: {format_size(total_size)}"
        )
    else:
        file_name = first_fn
        total_size = media.file_size
        caption = first_msg.caption or ""
        description = (
            f"💾 Telegram File\n📦 Size: {format_size(total_size)}\n💬 {caption}"
            if caption
            else f"💾 Telegram File\n📦 Size: {format_size(total_size)}"
        )

    meta = {
        "id": meta_id,
        "type": type_,
        "name": file_name,
        "description": description,
        "poster": logo_url(),
        "background": f"{Config.ADDON_URL}/stremio_telegram_banner.png" if Config.ADDON_URL else None,
        "logo": logo_url(),
    }

    if type_ == "series":
        meta["videos"] = [{
            "id": meta_id,
            "title": file_name,
            "season": 1,
            "episode": 1,
        }]

    return meta


async def _append_zip_streams(
    streams: list,
    messages,
    chat_id,
    msg_ids: str,
    query_param: str,
    api_key: str,
    cached_messages,
    season,
    episode,
    type_: str,
    split_label: str = "",
) -> bool:
    try:
        entries = await list_zip_files(tg_client_manager.client, messages)
        video_entries = [e for e in entries if is_video_file(e.filename)]
        if not video_entries:
            return False
        name_suffix = f" (Split)" if split_label else ""
        for entry in video_entries:
            if type_ == "series" and not matches_episode(entry.filename, season, episode):
                continue
            stream_url = (
                f"{Config.ADDON_URL}/stream/zip/{chat_id}/{msg_ids}/"
                f"{urllib.parse.quote(entry.filename)}{query_param}"
            )
            subtitles = await find_subtitles_for_video(
                entry.filename, api_key=api_key, cached_messages=cached_messages
            )
            streams.append({
                "name": f"▶ TG ZIP Play{name_suffix}",
                "title": f"{entry.filename}\n💾 Stream ZIP entry | 📦 {format_size(entry.file_size)}",
                "url": stream_url,
                "subtitles": subtitles,
                "behaviorHints": NOT_WEB_READY,
            })
        return True
    except Exception as e:
        logger.error(f"Error checking ZIP streams: {e}")
        return False


def _in_selected_channels(chat_id, channel_ids) -> bool:
    if not channel_ids:
        return True
    allowed = {channel_key(c) for c in channel_ids}
    return channel_key(chat_id) in allowed


async def build_streams_from_grouped(
    grouped_results: list,
    type_: str,
    movie_name: str,
    season,
    episode,
    query_param: str,
    api_key: str,
    cached_messages,
    channel_ids=None,
) -> list:
    streams = []

    for item in grouped_results:
        if isinstance(item, tuple):
            base_name, parts = item
            first_msg = parts[0]
            media = first_msg.video or first_msg.document or first_msg.audio
            file_name = getattr(media, "file_name", "") or ""

            if not matches_title(base_name, movie_name):
                continue
            if type_ == "series" and not matches_episode(file_name, season, episode):
                continue

            total_size = sum(
                (x.video or x.document or x.audio).file_size
                for x in parts
                if (x.video or x.document or x.audio)
            )
            msg_ids = _msg_ids_str([x.id for x in parts])
            chat_id = first_msg.chat.id
            if not _in_selected_channels(chat_id, channel_ids):
                continue

            is_zip = False
            if base_name.lower().endswith(".zip"):
                is_zip = await _append_zip_streams(
                    streams, parts, chat_id, msg_ids, query_param, api_key,
                    cached_messages, season, episode, type_, split_label="Split",
                )

            if not is_zip:
                if not is_video_file(base_name):
                    continue
                stream_url = (
                    f"{Config.ADDON_URL}/stream/split/{chat_id}/{msg_ids}/"
                    f"{urllib.parse.quote(base_name)}{query_param}"
                )
                streams.append({
                    "name": "▶ TG Play (Split)",
                    "title": f"{base_name}\n💾 Stitch stream | 📦 {format_size(total_size)}",
                    "url": stream_url,
                    "behaviorHints": NOT_WEB_READY,
                })
        else:
            msg = item
            media = msg.video or msg.document or msg.audio
            file_name = getattr(media, "file_name", None) or msg.caption or ""

            if not matches_title(file_name, movie_name):
                continue
            if type_ == "series" and not matches_episode(file_name, season, episode):
                continue

            file_size = media.file_size
            chat_id = msg.chat.id
            if not _in_selected_channels(chat_id, channel_ids):
                continue

            is_zip = False
            if file_name.lower().endswith(".zip"):
                is_zip = await _append_zip_streams(
                    streams, msg, chat_id, str(msg.id), query_param, api_key,
                    cached_messages, season, episode, type_,
                )

            if not is_zip:
                if not is_video_file(file_name):
                    continue
                stream_url = (
                    f"{Config.ADDON_URL}/stream/file/{chat_id}/{msg.id}/"
                    f"{urllib.parse.quote(file_name)}{query_param}"
                )
                subtitles = await find_subtitles_for_video(
                    file_name, api_key=api_key, cached_messages=cached_messages
                )
                streams.append({
                    "name": "▶ TG Play",
                    "title": f"{file_name}\n💾 Telegram File | 📦 {format_size(file_size)}",
                    "url": stream_url,
                    "subtitles": subtitles,
                    "behaviorHints": NOT_WEB_READY,
                })

    return streams


async def resolve_tgfile_streams(
    stream_id: str,
    query_param: str,
    api_key: str,
    channel_ids=None,
) -> list:
    streams = []
    ref = parse_tg_id(stream_id)
    if not ref:
        return streams
    if channel_ids and not _in_selected_channels(ref.chat_id, channel_ids):
        return streams

    if ref.zip_entry_filename:
        try:
            messages = await tg_client_manager.get_messages_batch(ref.message_ids, chat_id=ref.chat_id)
            if not messages:
                return streams

            zip_entries = await list_zip_files(tg_client_manager.client, messages)
            file_size = 0
            for entry in zip_entries:
                if entry.filename == ref.zip_entry_filename:
                    file_size = entry.file_size
                    break

            msg_ids = _msg_ids_str(ref.message_ids)
            chat_id = ref.chat_id
            stream_url = (
                f"{Config.ADDON_URL}/stream/zip/{chat_id}/{msg_ids}/"
                f"{urllib.parse.quote(ref.zip_entry_filename)}{query_param}"
            )
            subtitles = await find_subtitles_for_video(ref.zip_entry_filename, api_key=api_key)
            streams.append({
                "name": "▶ TG ZIP Play",
                "title": (
                    f"{ref.zip_entry_filename}\n💾 Stream ZIP entry | 📦 {format_size(file_size)}"
                ),
                "url": stream_url,
                "subtitles": subtitles,
                "behaviorHints": NOT_WEB_READY,
            })
        except Exception as e:
            logger.error(f"Failed resolving zip stream for {stream_id}: {e}")
        return streams

    if ref.is_split:
        try:
            messages = await tg_client_manager.get_messages_batch(ref.message_ids, chat_id=ref.chat_id)
            if not messages:
                return streams

            first_msg = messages[0]
            media = first_msg.video or first_msg.document or first_msg.audio
            first_fn = getattr(media, "file_name", "video.mp4") or "video.mp4"
            base_name, _ = parse_split_info(first_fn)
            if not base_name:
                base_name = first_fn

            total_size = sum(
                (m.video or m.document or m.audio).file_size
                for m in messages
                if (m.video or m.document or m.audio)
            )
            msg_ids = _msg_ids_str(ref.message_ids)
            stream_url = (
                f"{Config.ADDON_URL}/stream/split/{ref.chat_id}/{msg_ids}/"
                f"{urllib.parse.quote(base_name)}{query_param}"
            )
            streams.append({
                "name": "▶ TG Play (Split)",
                "title": f"{base_name}\n💾 Stitch stream | 📦 {format_size(total_size)}",
                "url": stream_url,
                "behaviorHints": NOT_WEB_READY,
            })
        except Exception as e:
            logger.error(f"Failed resolving split stream for {stream_id}: {e}")
        return streams

    try:
        msg = await tg_client_manager.get_message(ref.message_ids[0], chat_id=ref.chat_id)
        media = msg.video or msg.document or msg.audio
        file_name = getattr(media, "file_name", "video.mp4") or "video.mp4"
        file_size = media.file_size
        stream_url = (
            f"{Config.ADDON_URL}/stream/file/{ref.chat_id}/{ref.message_ids[0]}/"
            f"{urllib.parse.quote(file_name)}{query_param}"
        )
        subtitles = await find_subtitles_for_video(file_name, api_key=api_key)
        streams.append({
            "name": "▶ TG Play",
            "title": f"{file_name}\n💾 Direct stream | 📦 {format_size(file_size)}",
            "url": stream_url,
            "subtitles": subtitles,
            "behaviorHints": NOT_WEB_READY,
        })
    except Exception as e:
        logger.error(f"Failed resolving direct stream for {stream_id}: {e}")

    return streams


async def build_streams_from_imdb(
    type_: str,
    stream_id: str,
    query_param: str,
    api_key: str,
    channel_ids=None,
) -> list:
    imdb_id = stream_id
    season = None
    episode = None

    if ":" in stream_id:
        parts = stream_id.split(":")
        imdb_id = parts[0]
        season = int(parts[1])
        episode = int(parts[2])

    try:
        meta = await get_metadata_from_cinemeta(type_, imdb_id)
        movie_name = meta.get("name")
        if not movie_name:
            return []

        logger.info(f"Resolved IMDb {imdb_id} to '{movie_name}'. Searching Telegram...")
        tg_results = await tg_client_manager.search_messages(
            query=movie_name, limit=50, channel_ids=channel_ids
        )
        grouped_results = group_tg_messages(tg_results)
        return await build_streams_from_grouped(
            grouped_results, type_, movie_name, season, episode,
            query_param, api_key, tg_results, channel_ids=channel_ids,
        )
    except Exception as e:
        logger.error(f"Cinemeta search/resolve failed: {e}")
        return []
