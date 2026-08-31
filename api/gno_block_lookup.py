"""Identity-validated live Gno block lookup and stable future-height ETA."""

from concurrent.futures import Future
from datetime import datetime, timedelta, timezone
import math
from threading import Lock
import time
from typing import Callable

from indexer.rpc import probe_rpc_endpoints, suitable_rpc_probes
from scripts.inspect_rpc import RpcError, result, to_int


ETA_CHECKPOINT_SPANS = (1000, 500, 200, 80)
ETA_CACHE_TTL_SECONDS = 300.0
MAX_AVERAGE_BLOCK_SECONDS = 3600.0

_cache: dict[str, tuple[float, dict | None]] = {}
_inflight: dict[str, Future] = {}
_lock = Lock()


class GnoBlockLookupUnavailable(RuntimeError):
    """No configured RPC supplied trustworthy live chain data."""


def _timestamp(value) -> datetime:
    if not isinstance(value, str) or not value:
        raise RpcError("Malformed RPC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RpcError("Malformed RPC timestamp") from exc
    if parsed.tzinfo is None:
        raise RpcError("Malformed RPC timestamp")
    return parsed.astimezone(timezone.utc)


def _block_header(payload, expected_chain_id: str, expected_height: int) -> tuple[int, datetime]:
    data = result(payload)
    block = data.get("block")
    header = block.get("header") if isinstance(block, dict) else None
    if not isinstance(header, dict) or header.get("chain_id") != expected_chain_id:
        raise RpcError("Wrong-chain or malformed block response")
    height = to_int(header.get("height"))
    if height != expected_height or height is None or height <= 0:
        raise RpcError("RPC block height mismatch")
    return height, _timestamp(header.get("time"))


def _sample(client, chain_id: str, latest_height: int) -> dict | None:
    _, latest_time = _block_header(
        client.get("block", height=latest_height), chain_id, latest_height,
    )
    for span in ETA_CHECKPOINT_SPANS:
        checkpoint = latest_height - span
        if checkpoint < 1:
            continue
        try:
            _, old_time = _block_header(client.get("block", height=checkpoint), chain_id, checkpoint)
            elapsed = (latest_time - old_time).total_seconds()
            average = elapsed / span
            if elapsed > 0 and math.isfinite(average) and 0 < average <= MAX_AVERAGE_BLOCK_SECONDS:
                return {"average_block_seconds": average, "sample_intervals": span,
                        "latest_height": latest_height, "latest_time": latest_time}
        except (RpcError, TypeError, ValueError, OSError):
            continue
    return None


def _cached_sample(chain_id: str, loader: Callable[[], dict | None], clock=time.monotonic):
    now = clock()
    with _lock:
        cached = _cache.get(chain_id)
        if cached is not None and now - cached[0] < ETA_CACHE_TTL_SECONDS:
            return cached[1]
        future = _inflight.get(chain_id)
        owner = future is None
        if owner:
            future = Future()
            _inflight[chain_id] = future
    if not owner:
        return future.result()
    try:
        value = loader()
        with _lock:
            _cache[chain_id] = (clock(), value)
        future.set_result(value)
        return value
    except BaseException as exc:
        future.set_exception(exc)
        raise
    finally:
        with _lock:
            _inflight.pop(chain_id, None)


def clear_gno_eta_cache() -> None:
    """Clear process-local samples (primarily for deterministic tests)."""
    with _lock:
        _cache.clear()
        _inflight.clear()


def lookup_future_block(height: int, config, *, clock=time.monotonic) -> dict:
    probes = probe_rpc_endpoints(list(config.rpc_urls), config.chain_id,
                                config.rpc_max_height_lag, config.account_rpc_timeout_seconds)
    candidates = suitable_rpc_probes(probes)
    if not candidates:
        raise GnoBlockLookupUnavailable("live RPC height unavailable")
    latest_height = max(candidate.latest_height for candidate in candidates)
    try:
        if height <= latest_height:
            return {"state": "not_indexed", "current_height": latest_height, "eta": None}

        def load_sample():
            for candidate in candidates:
                try:
                    return _sample(candidate.client, config.chain_id, candidate.latest_height)
                except (RpcError, TypeError, ValueError, OSError):
                    continue
            raise GnoBlockLookupUnavailable("validated RPC endpoints did not provide a valid latest block")

        sample = _cached_sample(
            config.chain_id,
            load_sample,
            clock,
        )
        remaining = height - latest_height
        eta = None
        if sample is not None:
            try:
                estimated = sample["latest_time"] + timedelta(
                    seconds=sample["average_block_seconds"] * (height - sample["latest_height"]),
                )
                eta = {"remaining_blocks": remaining,
                       "average_block_seconds": sample["average_block_seconds"],
                       "sample_intervals": sample["sample_intervals"],
                       "estimated_at": estimated.isoformat(timespec="microseconds").replace("+00:00", "Z")}
            except (OverflowError, ValueError):
                eta = None
        return {"state": "future", "current_height": latest_height, "eta": eta}
    finally:
        for item in probes:
            client = item.client
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass
