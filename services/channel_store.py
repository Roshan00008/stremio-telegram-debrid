import json
import logging
import os
import threading
from datetime import datetime, timezone
from typing import List, Optional, Union

from config import Config, _parse_channel_ids
from services.channels import channel_key

logger = logging.getLogger("channel_store")


class ChannelStore:
    def __init__(self, path: Optional[str] = None):
        self.path = path or Config.CHANNEL_STORE_PATH
        self._lock = threading.Lock()
        self._data = {"channels": []}
        self._initialized = False

    def _ensure_dir(self) -> None:
        directory = os.path.dirname(os.path.abspath(self.path))
        if directory:
            os.makedirs(directory, exist_ok=True)

    def load(self) -> None:
        with self._lock:
            if os.path.exists(self.path):
                try:
                    with open(self.path, encoding="utf-8") as f:
                        self._data = json.load(f)
                    if "channels" not in self._data:
                        self._data = {"channels": []}
                except Exception as e:
                    logger.error(f"Failed to load channel store: {e}")
                    self._data = {"channels": []}
            self._initialized = True

    def save(self) -> None:
        with self._lock:
            self._ensure_dir()
            tmp_path = f"{self.path}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2)
            os.replace(tmp_path, self.path)

    def ensure_initialized(self) -> None:
        if not self._initialized:
            self.load()
        if not self._data["channels"] and Config.TELEGRAM_CHANNEL_ID:
            self.seed_from_env()

    def seed_from_env(self) -> None:
        env_val = os.getenv("TELEGRAM_CHANNEL_ID", "")
        if not env_val:
            return
        parsed = _parse_channel_ids(env_val)
        active_raw = os.getenv("ACTIVE_CHANNEL_IDS", "")
        active_keys = {channel_key(c) for c in _parse_channel_ids(active_raw)} if active_raw else set()

        for cid in parsed:
            key = channel_key(cid)
            if self._find_index(key) is not None:
                continue
            active = key in active_keys if active_keys else True
            self._data["channels"].append({
                "id": cid,
                "title": str(cid),
                "username": cid if isinstance(cid, str) and not str(cid).lstrip("-").isdigit() else "",
                "active": active,
                "added_at": datetime.now(timezone.utc).isoformat(),
            })
        if self._data["channels"]:
            self.save()
            logger.info(f"Seeded {len(self._data['channels'])} channel(s) from environment")

    def list_channels(self) -> list:
        self.ensure_initialized()
        return list(self._data["channels"])

    def get_configured_ids(self) -> List[Union[int, str]]:
        self.ensure_initialized()
        return [ch["id"] for ch in self._data["channels"]]

    def get_active_ids(self) -> List[Union[int, str]]:
        self.ensure_initialized()
        active = [ch["id"] for ch in self._data["channels"] if ch.get("active", True)]
        return active if active else self.get_configured_ids()

    def _find_index(self, key: str) -> Optional[int]:
        for i, ch in enumerate(self._data["channels"]):
            if channel_key(ch["id"]) == key:
                return i
        return None

    def add_channel(
        self,
        channel_id: Union[int, str],
        title: str = "",
        username: str = "",
        active: bool = True,
    ) -> dict:
        self.ensure_initialized()
        key = channel_key(channel_id)
        idx = self._find_index(key)
        if idx is not None:
            ch = self._data["channels"][idx]
            if title:
                ch["title"] = title
            if username:
                ch["username"] = username
            ch["active"] = active
            self.save()
            return ch

        entry = {
            "id": channel_id,
            "title": title or str(channel_id),
            "username": username or "",
            "active": active,
            "added_at": datetime.now(timezone.utc).isoformat(),
        }
        self._data["channels"].append(entry)
        self.save()
        return entry

    def remove_channel(self, channel_id: Union[int, str]) -> bool:
        self.ensure_initialized()
        idx = self._find_index(channel_key(channel_id))
        if idx is None:
            return False
        self._data["channels"].pop(idx)
        self.save()
        return True

    def set_active(self, channel_id: Union[int, str], active: bool) -> bool:
        self.ensure_initialized()
        idx = self._find_index(channel_key(channel_id))
        if idx is None:
            return False
        self._data["channels"][idx]["active"] = active
        self.save()
        return True

    def update_channel_meta(
        self,
        channel_id: Union[int, str],
        title: str = "",
        username: str = "",
    ) -> None:
        self.ensure_initialized()
        idx = self._find_index(channel_key(channel_id))
        if idx is None:
            return
        if title:
            self._data["channels"][idx]["title"] = title
        if username:
            self._data["channels"][idx]["username"] = username
        self.save()


channel_store = ChannelStore()
