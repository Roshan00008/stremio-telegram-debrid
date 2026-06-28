import logging
import asyncio
import functools
import inspect
import re
from hashlib import sha256
from typing import Callable, Optional, AsyncGenerator, Union

from pyrogram import Client, raw, utils
from pyrogram.types import Message
from pyrogram.session.auth import Auth
from pyrogram.session import Session
from pyrogram.file_id import FileId, FileType, ThumbnailSource
from pyrogram.errors import VolumeLocNotFound, CDNFileHashMismatch, FloodWait
from pyrogram.crypto import aes
import pyrogram
from cache import BoundedTTLCache
from config import Config
from services.channels import channel_key, filter_to_allowed
from utils import parse_split_info

logger = logging.getLogger("tg_client")

SEARCH_CONCURRENCY = 3


async def _call_with_flood_wait(coro_factory):
    while True:
        try:
            return await coro_factory()
        except FloodWait as e:
            logger.warning(f"FloodWait {e.value}s, retrying...")
            await asyncio.sleep(e.value + 1)

# Monkey-patch to cache auth keys across media sessions
_original_auth_create = Auth.create
_auth_key_cache = {}

async def _patched_auth_create(self):
    if self.dc_id in _auth_key_cache:
        logger.info(f"Reusing cached auth key for DC{self.dc_id}")
        return _auth_key_cache[self.dc_id]
    
    logger.info(f"Generating new auth key for DC{self.dc_id}...")
    key = await _original_auth_create(self)
    _auth_key_cache[self.dc_id] = key
    return key

Auth.create = _patched_auth_create


# Monkey-patch Client.get_file to reuse media sessions and avoid connection overhead
async def _patched_get_file(
    self: Client,
    file_id: FileId,
    file_size: int = 0,
    limit: int = 0,
    offset: int = 0,
    progress: Callable = None,
    progress_args: tuple = ()
) -> Optional[AsyncGenerator[bytes, None]]:
    async with self.get_file_semaphore:
        file_type = file_id.file_type

        if file_type == FileType.CHAT_PHOTO:
            if file_id.chat_id > 0:
                peer = raw.types.InputPeerUser(
                    user_id=file_id.chat_id,
                    access_hash=file_id.chat_access_hash
                )
            else:
                if file_id.chat_access_hash == 0:
                    peer = raw.types.InputPeerChat(
                        chat_id=-file_id.chat_id
                    )
                else:
                    peer = raw.types.InputPeerChannel(
                        channel_id=utils.get_channel_id(file_id.chat_id),
                        access_hash=file_id.chat_access_hash
                    )

            location = raw.types.InputPeerPhotoFileLocation(
                peer=peer,
                photo_id=file_id.media_id,
                big=file_id.thumbnail_source == ThumbnailSource.CHAT_PHOTO_BIG
            )
        elif file_type == FileType.PHOTO:
            location = raw.types.InputPhotoFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size
            )
        else:
            location = raw.types.InputDocumentFileLocation(
                id=file_id.media_id,
                access_hash=file_id.access_hash,
                file_reference=file_id.file_reference,
                thumb_size=file_id.thumbnail_size
            )

        current = 0
        total = abs(limit) or (1 << 31) - 1
        chunk_size = 1024 * 1024
        offset_bytes = abs(offset) * chunk_size

        dc_id = file_id.dc_id

        async with self.media_sessions_lock:
            session = self.media_sessions.get(dc_id)
            if session is None:
                logger.info(f"Creating new media session for DC{dc_id}...")
                session = Session(
                    self, dc_id,
                    await Auth(self, dc_id, await self.storage.test_mode()).create()
                    if dc_id != await self.storage.dc_id()
                    else await self.storage.auth_key(),
                    await self.storage.test_mode(),
                    is_media=True
                )
                await session.start()

                if dc_id != await self.storage.dc_id():
                    exported_auth = await self.invoke(
                        raw.functions.auth.ExportAuthorization(
                            dc_id=dc_id
                        )
                    )

                    await session.invoke(
                        raw.functions.auth.ImportAuthorization(
                            id=exported_auth.id,
                            bytes=exported_auth.bytes
                        )
                    )
                self.media_sessions[dc_id] = session
            else:
                logger.info(f"Reusing cached media session for DC{dc_id}")

        try:
            r = await session.invoke(
                raw.functions.upload.GetFile(
                    location=location,
                    offset=offset_bytes,
                    limit=chunk_size
                ),
                sleep_threshold=30
            )

            if isinstance(r, raw.types.upload.File):
                while True:
                    chunk = r.bytes

                    yield chunk

                    current += 1
                    offset_bytes += chunk_size

                    if progress:
                        func = functools.partial(
                            progress,
                            min(offset_bytes, file_size)
                            if file_size != 0
                            else offset_bytes,
                            file_size,
                            *progress_args
                        )

                        if inspect.iscoroutinefunction(progress):
                            await func()
                        else:
                            await self.loop.run_in_executor(self.executor, func)

                    if len(chunk) < chunk_size or current >= total:
                        break

                    r = await session.invoke(
                        raw.functions.upload.GetFile(
                            location=location,
                            offset=offset_bytes,
                            limit=chunk_size
                        ),
                        sleep_threshold=30
                    )

            elif isinstance(r, raw.types.upload.FileCdnRedirect):
                cdn_session = Session(
                    self, r.dc_id, await Auth(self, r.dc_id, await self.storage.test_mode()).create(),
                    await self.storage.test_mode(), is_media=True, is_cdn=True
                )

                try:
                    await cdn_session.start()

                    while True:
                        r2 = await cdn_session.invoke(
                            raw.functions.upload.GetCdnFile(
                                file_token=r.file_token,
                                offset=offset_bytes,
                                limit=chunk_size
                            )
                        )

                        if isinstance(r2, raw.types.upload.CdnFileReuploadNeeded):
                            try:
                                await session.invoke(
                                    raw.functions.upload.ReuploadCdnFile(
                                        file_token=r.file_token,
                                        request_token=r2.request_token
                                    )
                                )
                            except VolumeLocNotFound:
                                break
                            else:
                                continue

                        chunk = r2.bytes

                        decrypted_chunk = aes.ctr256_decrypt(
                            chunk,
                            r.encryption_key,
                            bytearray(
                                r.encryption_iv[:-4]
                                + (offset_bytes // 16).to_bytes(4, "big")
                            )
                        )

                        hashes = await session.invoke(
                            raw.functions.upload.GetCdnFileHashes(
                                file_token=r.file_token,
                                offset=offset_bytes
                            )
                        )

                        for i, h in enumerate(hashes):
                            cdn_chunk = decrypted_chunk[h.limit * i: h.limit * (i + 1)]
                            CDNFileHashMismatch.check(
                                h.hash == sha256(cdn_chunk).digest(),
                                "h.hash == sha256(cdn_chunk).digest()"
                            )

                        yield decrypted_chunk

                        current += 1
                        offset_bytes += chunk_size

                        if progress:
                            func = functools.partial(
                                progress,
                                min(offset_bytes, file_size) if file_size != 0 else offset_bytes,
                                file_size,
                                *progress_args
                            )

                            if inspect.iscoroutinefunction(progress):
                                await func()
                            else:
                                await self.loop.run_in_executor(self.executor, func)

                        if len(chunk) < chunk_size or current >= total:
                            break
                finally:
                    await cdn_session.stop()
        except Exception as e:
            if not isinstance(e, (pyrogram.StopTransmission, asyncio.CancelledError)):
                logger.warning(f"Error in media session for DC{dc_id}, discarding from cache: {e}")
                async with self.media_sessions_lock:
                    if self.media_sessions.get(dc_id) is session:
                        self.media_sessions.pop(dc_id, None)
                try:
                    await session.stop()
                except Exception:
                    pass
            raise e

Client.get_file = _patched_get_file


class TelegramClientManager:
    def __init__(self):
        self.client = None
        self.is_running = False
        self._search_cache = BoundedTTLCache(maxsize=200, ttl=Config.CACHE_TTL)
        self._message_cache = BoundedTTLCache(maxsize=1000, ttl=Config.CACHE_TTL)
        self._log_cache = BoundedTTLCache(maxsize=500, ttl=900)
        self._resolved_channels = set()
        self._channel_info = {}

    def initialize(self):
        Config.validate()
        
        if Config.USER_SESSION_STRING:
            logger.info("Initializing User Client...")
            self.client = Client(
                name="tg_stremio_user",
                api_id=Config.API_ID,
                api_hash=Config.API_HASH,
                session_string=Config.USER_SESSION_STRING,
                in_memory=True,
                no_updates=True
            )
        elif Config.BOT_TOKEN:
            logger.info("Initializing Bot Client...")
            self.client = Client(
                name="tg_stremio_bot",
                api_id=Config.API_ID,
                api_hash=Config.API_HASH,
                bot_token=Config.BOT_TOKEN,
                in_memory=True,
                no_updates=True
            )
        else:
            raise ValueError("Neither USER_SESSION_STRING nor BOT_TOKEN is configured!")

    def get_channel_ids(self) -> list:
        return Config.get_channel_ids()

    async def _resolve_channel(self, chat_id) -> bool:
        try:
            chat = await _call_with_flood_wait(lambda: self.client.get_chat(chat_id))
            self._resolved_channels.add(chat_id)
            self._channel_info[channel_key(chat.id)] = {
                "id": chat.id,
                "title": chat.title or str(chat.id),
                "username": chat.username or "",
            }
            return True
        except Exception as e:
            logger.warning(f"Failed to cache channel {chat_id}: {e}")
            return False

    async def get_channels_info(self) -> list:
        if not self.is_running:
            await self.start()
        from services.channel_store import channel_store
        channel_store.ensure_initialized()
        stored = channel_store.list_channels()
        if stored:
            result = []
            for ch in stored:
                key = channel_key(ch["id"])
                if key in self._channel_info:
                    info = dict(self._channel_info[key])
                else:
                    await self._resolve_channel(ch["id"])
                    info = dict(self._channel_info.get(key, {
                        "id": ch["id"],
                        "title": ch.get("title", str(ch["id"])),
                        "username": ch.get("username", ""),
                    }))
                info["active"] = ch.get("active", True)
                result.append(info)
            return result
        result = []
        for chat_id in Config.get_channel_ids():
            key = channel_key(chat_id)
            if key in self._channel_info:
                result.append(self._channel_info[key])
                continue
            await self._resolve_channel(chat_id)
            if key in self._channel_info:
                result.append(self._channel_info[key])
            else:
                result.append({"id": chat_id, "title": str(chat_id), "username": ""})
        return result

    async def check_health(self) -> dict:
        chat_ids = self.get_channel_ids()
        if not self.is_running or not self.client:
            return {
                "status": "unhealthy",
                "client_running": False,
                "channels_configured": len(chat_ids),
                "channels_resolved": 0,
            }

        resolved = 0
        for chat_id in chat_ids:
            if chat_id in self._resolved_channels:
                resolved += 1
            elif await self._resolve_channel(chat_id):
                resolved += 1

        healthy = resolved > 0
        return {
            "status": "healthy" if healthy else "unhealthy",
            "client_running": True,
            "channels_configured": len(chat_ids),
            "channels_resolved": resolved,
        }

    async def start(self):
        if not self.client:
            self.initialize()
        
        if not self.is_running:
            logger.info("Starting Pyrogram client...")
            await self.client.start()
            self.is_running = True
            
            # Resolve target channels on startup to avoid PeerIdInvalid errors
            try:
                chat_ids = self.get_channel_ids()
                
                if Config.USER_SESSION_STRING:
                    cached_count = 0
                    async for dialog in self.client.get_dialogs(limit=400):
                        if dialog.chat.id in chat_ids:
                            logger.info(f"Resolved channel: {dialog.chat.title} ({dialog.chat.id})")
                            cached_count += 1
                            if cached_count >= len(chat_ids):
                                break
                
                for chat_id in chat_ids:
                    await self._resolve_channel(chat_id)
                        
                if Config.LOG_CHANNEL_ID:
                    try:
                        await _call_with_flood_wait(
                            lambda: self.client.get_chat(Config.LOG_CHANNEL_ID)
                        )
                    except Exception as e:
                        logger.warning(f"Failed to cache log channel {Config.LOG_CHANNEL_ID}: {e}")
            except Exception as e:
                logger.warning(f"Failed to resolve target channels on startup: {e}")

    async def stop(self):
        if self.is_running and self.client:
            logger.info("Stopping Pyrogram client...")
            try:
                await asyncio.wait_for(self.client.stop(), timeout=3.0)
            except asyncio.TimeoutError:
                logger.warning("Pyrogram client stop timed out, skipping...")
            except Exception as e:
                logger.warning(f"Error stopping Pyrogram client: {e}")
            self.is_running = False

    async def send_play_log(self, filename: str, chat_id: Union[str, int], message_id: int):
        if not Config.LOG_CHANNEL_ID:
            return
            
        key = (chat_id, message_id)
        if self._log_cache.get(key):
            return
        self._log_cache.set(key, True)
        
        try:
            import datetime
            from datetime import timezone, timedelta
            
            tz_str = getattr(Config, "TIMEZONE", "UTC") or "UTC"
            local_dt = None
            
            try:
                from zoneinfo import ZoneInfo
                local_dt = datetime.datetime.now(ZoneInfo(tz_str))
            except Exception:
                pass
                
            if local_dt is None:
                try:
                    tz_clean = tz_str.upper().replace("UTC", "").replace("GMT", "").strip()
                    if tz_clean and tz_clean[0] in ("+", "-"):
                        sign = 1 if tz_clean[0] == "+" else -1
                        time_parts = tz_clean[1:].split(":")
                        hours = int(time_parts[0])
                        minutes = int(time_parts[1]) if len(time_parts) > 1 else 0
                        td = timedelta(hours=hours, minutes=minutes)
                        local_dt = datetime.datetime.now(timezone(sign * td))
                except Exception:
                    pass
            
            if local_dt is None:
                local_dt = datetime.datetime.now(timezone.utc)
                
            time_str = local_dt.strftime("%Y-%m-%d %H:%M:%S")
            year_str = local_dt.strftime("%Y")
            
            message_text = (
                f"🎬 **Media Stream Log**\n\n"
                f"📁 **File Name:** `{filename}`\n"
                f"📅 **Date & Time:** `{time_str}`\n"
                f"📆 **Year:** `{year_str}`\n"
                f"💬 **Source Channel:** `{chat_id}`\n"
                f"🆔 **Message ID:** `{message_id}`"
            )
            
            await _call_with_flood_wait(
                lambda: self.client.send_message(
                    chat_id=Config.LOG_CHANNEL_ID,
                    text=message_text,
                )
            )
        except Exception as e:
            logger.error(f"Failed to send log to log channel: {e}")

    async def _search_channel(self, chat_id, query_str: str, per_channel_limit: int) -> list:
        while True:
            try:
                results = []
                if query_str:
                    async for msg in self.client.search_messages(
                        chat_id=chat_id, query=query_str, limit=per_channel_limit
                    ):
                        if self._has_media(msg):
                            results.append(msg)
                else:
                    async for msg in self.client.get_chat_history(
                        chat_id=chat_id, limit=per_channel_limit
                    ):
                        if self._has_media(msg):
                            results.append(msg)
                return results
            except FloodWait as e:
                logger.warning(f"FloodWait {e.value}s on channel {chat_id}, retrying...")
                await asyncio.sleep(e.value + 1)

    async def search_messages(
        self, query: str = "", limit: int = 50, channel_ids=None
    ):
        if not self.is_running:
            await self.start()

        query_str = str(query).strip() if query else ""
        chat_ids = (
            filter_to_allowed(channel_ids)
            if channel_ids is not None
            else Config.get_active_channel_ids()
        )
        if not chat_ids:
            return []

        cache_key = f"{query_str}:{limit}:{','.join(channel_key(c) for c in chat_ids)}"
        cached = self._search_cache.get(cache_key)
        if cached is not None:
            return cached

        per_channel_limit = max(100, limit)
        sem = asyncio.Semaphore(SEARCH_CONCURRENCY)

        async def search_one(chat_id):
            async with sem:
                return await self._search_channel(chat_id, query_str, per_channel_limit)

        channel_results = await asyncio.gather(
            *[search_one(chat_id) for chat_id in chat_ids],
            return_exceptions=True,
        )

        results = []
        for chat_id, result in zip(chat_ids, channel_results):
            if isinstance(result, Exception):
                logger.warning(f"Telegram query failed for {chat_id}: {result}")
            else:
                results.extend(result)

        results.sort(key=lambda m: m.date, reverse=True)

        split_bases = set()
        for msg in results:
            media = msg.video or msg.document or msg.audio
            if media:
                fn = getattr(media, "file_name", "") or msg.caption or ""
                base, part = parse_split_info(fn)
                if base:
                    search_query = re.sub(r'[^a-zA-Z0-9\s]', ' ', base)
                    search_query = re.sub(r'\s+', ' ', search_query).strip()
                    words = search_query.split()
                    if words and words[-1].lower() in (
                        'mkv', 'mp4', 'avi', 'mov', 'wmv', 'flv', 'webm', 'ts', 'm4v', 'zip'
                    ):
                        words = words[:-1]
                    if len(words) > 5:
                        search_query = " ".join(words[:5])
                    else:
                        search_query = " ".join(words)
                    for cid in chat_ids:
                        split_bases.add((cid, search_query))

        additional_messages = []
        for chat_id, base in split_bases:
            try:
                logger.info(f"Fetching all split parts matching base: {base}")
                extra = await self._search_channel(chat_id, base, 100)
                additional_messages.extend(extra)
            except Exception as e:
                logger.warning(f"Failed to fetch additional split parts for {base}: {e}")

        deduped = {msg.id: msg for msg in results}
        for msg in additional_messages:
            deduped[msg.id] = msg

        final_results = list(deduped.values())
        final_results.sort(key=lambda m: m.date, reverse=True)
        final_results = final_results[:limit]

        self._search_cache.set(cache_key, final_results)
        return final_results

    async def get_message(self, message_id: int, chat_id: int = None) -> Message:
        messages = await self.get_messages_batch([message_id], chat_id=chat_id)
        if not messages:
            raise ValueError(f"Message {message_id} not found")
        return messages[0]

    async def get_messages_batch(
        self, message_ids: list, chat_id: int = None
    ) -> list:
        if not message_ids:
            return []
        if not self.is_running:
            await self.start()

        target_chat = chat_id if chat_id is not None else self.get_channel_ids()[0]
        missing_ids = [
            mid for mid in message_ids
            if self._message_cache.get(f"{target_chat}:{mid}") is None
        ]

        if missing_ids:
            try:
                fetched = await _call_with_flood_wait(
                    lambda: self.client.get_messages(
                        chat_id=target_chat, message_ids=missing_ids
                    )
                )
                if not isinstance(fetched, list):
                    fetched = [fetched] if fetched else []
                for msg in fetched:
                    if msg:
                        self._message_cache.set(f"{target_chat}:{msg.id}", msg)
            except Exception as e:
                logger.error(
                    f"Failed to fetch messages {missing_ids} in channel {target_chat}: {e}"
                )
                raise e

        result = []
        for mid in message_ids:
            msg = self._message_cache.get(f"{target_chat}:{mid}")
            if msg is not None:
                result.append(msg)
        return result

    def _has_media(self, msg: Message) -> bool:
        return bool(msg.video or msg.document or msg.audio)

tg_client_manager = TelegramClientManager()
