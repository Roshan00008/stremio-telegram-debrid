import logging
from typing import Optional, Union

from pyrogram import Client, filters
from pyrogram.types import Message

from config import Config
from services.channel_store import channel_store
from services.channels import channel_key
from tg_client import tg_client_manager

logger = logging.getLogger("manager_bot")

_manager_client: Optional[Client] = None


def _is_admin(user_id: int) -> bool:
    allowed = Config.get_manager_user_ids()
    if not allowed:
        return False
    return user_id in allowed


def _parse_channel_arg(text: str) -> Optional[Union[int, str]]:
    text = text.strip()
    if not text:
        return None
    if text.startswith("@"):
        return text.lstrip("@")
    if text.startswith("-") or text.isdigit():
        try:
            return int(text)
        except ValueError:
            return text
    return text


async def _resolve_and_add(channel_ref: Union[int, str], active: bool = True) -> tuple[bool, str]:
    try:
        chat = await tg_client_manager.client.get_chat(channel_ref)
        channel_store.add_channel(
            chat.id,
            title=chat.title or str(chat.id),
            username=chat.username or "",
            active=active,
        )
        await tg_client_manager._resolve_channel(chat.id)
        return True, f"Added: {chat.title} ({chat.id})"
    except Exception as e:
        return False, f"Failed to add channel: {e}"


async def start_manager_bot() -> None:
    global _manager_client
    if not Config.MANAGER_BOT_TOKEN:
        return
    if not Config.get_manager_user_ids():
        logger.warning("MANAGER_BOT_TOKEN set but MANAGER_USER_IDS is empty; manager bot disabled")
        return

    _manager_client = Client(
        name="tg_stremio_manager",
        api_id=Config.API_ID,
        api_hash=Config.API_HASH,
        bot_token=Config.MANAGER_BOT_TOKEN,
        in_memory=True,
        no_updates=False,
    )

    admin_filter = filters.create(lambda _, __, m: _is_admin(m.from_user.id if m.from_user else 0))

    @_manager_client.on_message(filters.command("start") & admin_filter)
    async def cmd_start(_: Client, message: Message):
        await message.reply_text(
            "**Stremio Channel Manager**\n\n"
            "/channels — list configured channels\n"
            "/discover — list your joined channels (user session)\n"
            "/add `<id or @username>` — add a channel\n"
            "/remove `<id>` — remove a channel\n"
            "/on `<id>` — enable channel for streaming\n"
            "/off `<id>` — disable channel\n\n"
            "Web admin: `{url}/admin?api_key=YOUR_KEY`".format(url=Config.ADDON_URL),
            disable_web_page_preview=True,
        )

    @_manager_client.on_message(filters.command("channels") & admin_filter)
    async def cmd_channels(_: Client, message: Message):
        channels = channel_store.list_channels()
        if not channels:
            await message.reply_text("No channels configured. Use /add or the web admin panel.")
            return
        lines = []
        for ch in channels:
            status = "ON" if ch.get("active", True) else "OFF"
            title = ch.get("title", ch["id"])
            lines.append(f"• [{status}] {title} (`{ch['id']}`)")
        await message.reply_text("**Configured channels:**\n" + "\n".join(lines))

    @_manager_client.on_message(filters.command("discover") & admin_filter)
    async def cmd_discover(_: Client, message: Message):
        if not Config.USER_SESSION_STRING:
            await message.reply_text("Discovery requires USER_SESSION_STRING (not bot-only mode).")
            return
        known = {channel_key(ch["id"]) for ch in channel_store.list_channels()}
        lines = []
        count = 0
        async for dialog in tg_client_manager.client.get_dialogs(limit=200):
            if not dialog.chat or dialog.chat.type not in ("channel", "supergroup"):
                continue
            key = channel_key(dialog.chat.id)
            if key in known:
                continue
            title = dialog.chat.title or str(dialog.chat.id)
            lines.append(f"• {title} (`{dialog.chat.id}`)")
            count += 1
            if count >= 20:
                break
        if not lines:
            await message.reply_text("No new channels found in your dialogs.")
            return
        await message.reply_text(
            "**Joinable channels (not yet added):**\n" + "\n".join(lines) +
            "\n\nAdd with: /add `-100...`"
        )

    @_manager_client.on_message(filters.command("add") & admin_filter)
    async def cmd_add(_: Client, message: Message):
        arg = (message.text or "").split(maxsplit=1)
        if len(arg) < 2:
            await message.reply_text("Usage: /add `-1001234567890` or /add `@channelname`")
            return
        ref = _parse_channel_arg(arg[1])
        if ref is None:
            await message.reply_text("Invalid channel reference.")
            return
        ok, msg = await _resolve_and_add(ref, active=True)
        await message.reply_text(msg)

    @_manager_client.on_message(filters.command("remove") & admin_filter)
    async def cmd_remove(_: Client, message: Message):
        arg = (message.text or "").split(maxsplit=1)
        if len(arg) < 2:
            await message.reply_text("Usage: /remove `-1001234567890`")
            return
        ref = _parse_channel_arg(arg[1])
        if ref is None or not channel_store.remove_channel(ref):
            await message.reply_text("Channel not found.")
            return
        await message.reply_text(f"Removed channel `{ref}`.")

    @_manager_client.on_message(filters.command(["on", "off"]) & admin_filter)
    async def cmd_toggle(_: Client, message: Message):
        cmd = (message.text or "").split()[0].lstrip("/")
        arg = (message.text or "").split(maxsplit=1)
        if len(arg) < 2:
            await message.reply_text(f"Usage: /{cmd} `-1001234567890`")
            return
        ref = _parse_channel_arg(arg[1])
        active = cmd == "on"
        if ref is None or not channel_store.set_active(ref, active):
            await message.reply_text("Channel not found.")
            return
        state = "enabled" if active else "disabled"
        await message.reply_text(f"Channel `{ref}` {state}.")

    await _manager_client.start()
    me = await _manager_client.get_me()
    logger.info(f"Manager bot started: @{me.username}")


async def stop_manager_bot() -> None:
    global _manager_client
    if _manager_client:
        try:
            await _manager_client.stop()
        except Exception as e:
            logger.warning(f"Error stopping manager bot: {e}")
        _manager_client = None
