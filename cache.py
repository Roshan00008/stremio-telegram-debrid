import time
from collections import OrderedDict
from typing import Any, Optional


class BoundedTTLCache:
    """In-memory cache with TTL expiry and max entry count."""

    def __init__(self, maxsize: int = 500, ttl: float = 1800):
        self.maxsize = maxsize
        self.ttl = ttl
        self._data: OrderedDict[Any, tuple[float, Any]] = OrderedDict()

    def _purge_expired(self) -> None:
        now = time.time()
        expired = [key for key, (expiry, _) in self._data.items() if now > expiry]
        for key in expired:
            del self._data[key]

    def get(self, key: Any, default: Optional[Any] = None) -> Any:
        self._purge_expired()
        if key not in self._data:
            return default
        expiry, value = self._data[key]
        if time.time() > expiry:
            del self._data[key]
            return default
        self._data.move_to_end(key)
        return value

    def set(self, key: Any, value: Any) -> None:
        self._purge_expired()
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = (time.time() + self.ttl, value)
        while len(self._data) > self.maxsize:
            self._data.popitem(last=False)

    def __contains__(self, key: Any) -> bool:
        return self.get(key) is not None
