"""Bounded process cache for revision-scoped static asset classification."""

from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class StaticAssetClassification:
    verified: bool
    name: str | None = None
    symbol: str | None = None
    decimals: int | None = None
    reason: str = "rejected"


class AssetClassificationCache:
    def __init__(self, max_entries: int = 4096):
        if max_entries < 1:
            raise ValueError("max_entries must be positive")
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple[str, str, str, int], StaticAssetClassification] = OrderedDict()
        self._lock = Lock()

    def get(self, key: tuple[str, str, str, int]) -> StaticAssetClassification | None:
        with self._lock:
            value = self._entries.get(key)
            if value is not None:
                self._entries.move_to_end(key)
            return value

    def put(self, key: tuple[str, str, str, int], value: StaticAssetClassification) -> None:
        with self._lock:
            self._entries[key] = value
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()


asset_classification_cache = AssetClassificationCache()
