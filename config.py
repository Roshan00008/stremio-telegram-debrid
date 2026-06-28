import os

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass


def _parse_channel_ids(raw: str) -> list:
    if not raw:
        return []
    parts = [p.strip() for p in str(raw).split(",") if p.strip()]
    ids = []
    for p in parts:
        if p.startswith("-") or p.isdigit():
            try:
                ids.append(int(p))
            except ValueError:
                ids.append(p)
        else:
            ids.append(p.lstrip("@"))
    return ids


class Config:
    PORT = int(os.getenv("PORT", 7860))
    ADDON_URL = os.getenv("ADDON_URL", f"http://localhost:{PORT}").rstrip("/")
    API_KEY = os.getenv("API_KEY", "")
    CACHE_TTL = int(os.getenv("CACHE_TTL", 1800))
    TIMEZONE = os.getenv("TIMEZONE", "UTC")

    API_ID = os.getenv("API_ID")
    API_HASH = os.getenv("API_HASH")
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    USER_SESSION_STRING = os.getenv("USER_SESSION_STRING", "")

    TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
    ACTIVE_CHANNEL_IDS = os.getenv("ACTIVE_CHANNEL_IDS", "")
    LOG_CHANNEL_ID = os.getenv("LOG_CHANNEL_ID")

    CHANNEL_STORE_PATH = os.getenv("CHANNEL_STORE_PATH", "data/channels.json")
    MANAGER_BOT_TOKEN = os.getenv("MANAGER_BOT_TOKEN", "")
    MANAGER_USER_IDS = os.getenv("MANAGER_USER_IDS", "")

    _parse_channel_ids = staticmethod(_parse_channel_ids)

    @classmethod
    def get_manager_user_ids(cls) -> list:
        if not cls.MANAGER_USER_IDS:
            return []
        result = []
        for part in str(cls.MANAGER_USER_IDS).split(","):
            part = part.strip()
            if part.isdigit():
                result.append(int(part))
        return result

    @classmethod
    def get_channel_ids(cls) -> list:
        from services.channel_store import channel_store
        channel_store.ensure_initialized()
        ids = channel_store.get_configured_ids()
        if ids:
            return ids
        if not cls.TELEGRAM_CHANNEL_ID:
            return []
        if isinstance(cls.TELEGRAM_CHANNEL_ID, int):
            return [cls.TELEGRAM_CHANNEL_ID]
        if isinstance(cls.TELEGRAM_CHANNEL_ID, list):
            return cls.TELEGRAM_CHANNEL_ID
        return _parse_channel_ids(cls.TELEGRAM_CHANNEL_ID)

    @classmethod
    def get_active_channel_ids(cls) -> list:
        from services.channel_store import channel_store
        channel_store.ensure_initialized()
        if channel_store.get_configured_ids():
            return channel_store.get_active_ids()
        allowed = cls.get_channel_ids()
        if not cls.ACTIVE_CHANNEL_IDS:
            return allowed
        selected = _parse_channel_ids(cls.ACTIVE_CHANNEL_IDS)
        allowed_map = {
            (str(c).lstrip("@") if not isinstance(c, int) else str(c)): c for c in allowed
        }
        result = []
        for cid in selected:
            key = str(cid).lstrip("@") if not isinstance(cid, int) else str(cid)
            if key in allowed_map:
                result.append(allowed_map[key])
        return result if result else allowed

    @classmethod
    def validate(cls):
        missing = []
        if not cls.API_ID:
            missing.append("API_ID")
        if not cls.API_HASH:
            missing.append("API_HASH")
        if not cls.BOT_TOKEN and not cls.USER_SESSION_STRING:
            missing.append("BOT_TOKEN or USER_SESSION_STRING")

        from services.channel_store import channel_store
        channel_store.ensure_initialized()
        has_channels = bool(channel_store.get_configured_ids())
        if not has_channels and not cls.TELEGRAM_CHANNEL_ID:
            missing.append("TELEGRAM_CHANNEL_ID (or add channels later via /admin)")

        if missing:
            raise ValueError(
                f"Missing critical configuration variables: {', '.join(missing)}. "
                "Please configure them in your environment or a .env file."
            )

        try:
            cls.API_ID = int(cls.API_ID)
        except (ValueError, TypeError):
            raise ValueError("API_ID must be a valid integer.")

        if cls.TELEGRAM_CHANNEL_ID and isinstance(cls.TELEGRAM_CHANNEL_ID, str):
            parsed = _parse_channel_ids(cls.TELEGRAM_CHANNEL_ID)
            if len(parsed) == 1:
                cls.TELEGRAM_CHANNEL_ID = parsed[0]
            elif parsed:
                cls.TELEGRAM_CHANNEL_ID = parsed

        if cls.LOG_CHANNEL_ID and isinstance(cls.LOG_CHANNEL_ID, str):
            val = cls.LOG_CHANNEL_ID.strip()
            if val.startswith("-") or val.isdigit():
                try:
                    cls.LOG_CHANNEL_ID = int(val)
                except ValueError:
                    pass
