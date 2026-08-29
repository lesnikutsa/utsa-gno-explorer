"""Request-driven bounded TTL cache with asynchronous single-flight."""

import asyncio
from collections import OrderedDict
from copy import deepcopy
import time


class RequestCache:
    def __init__(self, *, max_entries: int = 256, clock=time.monotonic):
        if type(max_entries) is not int or not 1 <= max_entries <= 10_000:
            raise ValueError("max_entries is out of bounds")
        self._max_entries = max_entries
        self._clock = clock
        self._entries = OrderedDict()
        self._inflight = {}
        self._lock = asyncio.Lock()

    async def get_or_load(self, key: tuple, ttl: float, loader):
        async with self._lock:
            now = self._clock()
            for expired_key in [item for item, (expires, _) in self._entries.items() if expires <= now]:
                del self._entries[expired_key]
            cached = self._entries.get(key)
            if cached is not None:
                self._entries.move_to_end(key)
                return deepcopy(cached[1])
            future = self._inflight.get(key)
            leader = future is None
            if leader:
                future = asyncio.get_running_loop().create_future()
                future.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)
                self._inflight[key] = future
        if not leader:
            return deepcopy(await asyncio.shield(future))
        try:
            value = await loader()
            stored = deepcopy(value)
            async with self._lock:
                if ttl > 0:
                    self._entries[key] = (self._clock() + ttl, stored)
                    self._entries.move_to_end(key)
                    while len(self._entries) > self._max_entries:
                        self._entries.popitem(last=False)
                self._inflight.pop(key, None)
                future.set_result(stored)
            return deepcopy(stored)
        except BaseException as exc:
            async with self._lock:
                self._inflight.pop(key, None)
                if not future.done():
                    future.set_exception(exc)
            raise
