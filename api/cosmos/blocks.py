"""Bounded CometBFT block metadata access and future-height estimation."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
from urllib.parse import urlencode

from .adapter import CosmosAdapter
from .errors import (AllEndpointsUnavailable, HistoryUnavailable,
                     MalformedUpstreamResponse)
from .parsing import parse_node_status

MAX_HEIGHT = 9_223_372_036_854_775_807
METADATA_PAGE_SIZE = 20
SAMPLE_HEADERS = 101
MIN_INTERVALS = 20
STALL_SECONDS = 300


def _timestamp(value: object) -> datetime:
    if not isinstance(value, str) or not 20 <= len(value) <= 64:
        raise MalformedUpstreamResponse("invalid block timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise MalformedUpstreamResponse("invalid block timestamp") from None
    if parsed.tzinfo is None:
        raise MalformedUpstreamResponse("invalid block timestamp")
    return parsed.astimezone(timezone.utc)


def _positive_int(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MalformedUpstreamResponse(f"invalid {name}")
    if isinstance(value, str) and (not value.isascii() or not value.isdigit() or len(value) > 19):
        raise MalformedUpstreamResponse(f"invalid {name}")
    result = int(value)
    if not 0 < result <= MAX_HEIGHT:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return result


def parse_blockchain(payload: object, *, chain_id: str, minimum: int, maximum: int) -> list[dict]:
    if not isinstance(payload, dict) or not isinstance(payload.get("result"), dict):
        raise MalformedUpstreamResponse("invalid blockchain response")
    raw = payload["result"].get("block_metas")
    if not isinstance(raw, list) or not 1 <= len(raw) <= METADATA_PAGE_SIZE:
        raise MalformedUpstreamResponse("invalid block metadata list")
    result = []
    seen = set()
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("header"), dict) or not isinstance(item.get("block_id"), dict):
            raise MalformedUpstreamResponse("invalid block metadata")
        header = item["header"]
        height = _positive_int(header.get("height"), "block height")
        if height < minimum or height > maximum or height in seen or header.get("chain_id") != chain_id:
            raise MalformedUpstreamResponse("invalid block metadata range")
        block_hash, proposer = item["block_id"].get("hash"), header.get("proposer_address")
        if not all(isinstance(value, str) and 1 <= len(value) <= 128 and value.isascii()
                   and all(char in "0123456789abcdefABCDEF" for char in value)
                   for value in (block_hash, proposer)):
            raise MalformedUpstreamResponse("invalid block identity")
        txs = item.get("num_txs", header.get("num_txs", "0"))
        transaction_count = _positive_int(txs, "transaction count") if str(txs) != "0" else 0
        timestamp = _timestamp(header.get("time"))
        seen.add(height)
        result.append({"height": height, "hash": block_hash.upper(),
                       "timestamp": timestamp.isoformat().replace("+00:00", "Z"),
                       "proposer": proposer.upper(), "transaction_count": transaction_count,
                       "_time": timestamp})
    result.sort(key=lambda block: block["height"], reverse=True)
    if any(result[index]["height"] - 1 != result[index + 1]["height"] for index in range(len(result) - 1)):
        raise MalformedUpstreamResponse("non-consecutive block metadata")
    return result


def estimate_height_eta(blocks: list[dict], target_height: int, *, now: datetime) -> tuple[dict | None, str | None]:
    """Estimate from a 10%-trimmed mean of recent positive adjacent intervals."""
    ordered = sorted(blocks, key=lambda item: item["height"])
    intervals = []
    for previous, current in zip(ordered, ordered[1:]):
        if current["height"] == previous["height"] + 1:
            seconds = (current["_time"] - previous["_time"]).total_seconds()
            if math.isfinite(seconds) and seconds > 0:
                intervals.append(seconds)
    if len(intervals) < MIN_INTERVALS:
        return None, "insufficient_sample"
    trim = max(1, len(intervals) // 10)
    usable = sorted(intervals)[trim:-trim]
    if len(usable) < MIN_INTERVALS:
        return None, "insufficient_sample"
    latest = ordered[-1]
    if (now.astimezone(timezone.utc) - latest["_time"]).total_seconds() > STALL_SECONDS:
        return None, "network_appears_stalled"
    average = sum(usable) / len(usable)
    remaining = target_height - latest["height"]
    try:
        estimate = latest["_time"] + timedelta(seconds=remaining * average)
    except (OverflowError, ValueError):
        return None, "date_out_of_range"
    return {"current_height": latest["height"], "target_height": target_height,
            "remaining_blocks": remaining, "average_interval_seconds": round(average, 6),
            "sample_interval_count": len(usable), "sample_start_height": ordered[0]["height"],
            "sample_end_height": latest["height"],
            "estimated_at": estimate.isoformat().replace("+00:00", "Z"), "approximate": True,
            "status": "overdue_awaiting" if estimate <= now.astimezone(timezone.utc) else "estimated"}, None


@dataclass(frozen=True)
class ObservedHeads:
    observed_height: int
    catching_up: bool
    confirmed_height: int | None
    endpoint: str
    endpoints: tuple[str, ...]


class CosmosBlockService:
    def __init__(self, adapter: CosmosAdapter):
        self.adapter = adapter

    async def heads(self) -> ObservedHeads:
        statuses = []
        for endpoint in self.adapter.config.rpc_endpoints:
            try:
                payload = await self.adapter._transport.get_object(endpoint, "/status")
                statuses.append((endpoint, parse_node_status(payload, network_id=self.adapter.config.network_id,
                                expected_chain_id=self.adapter.config.chain_id,
                                source_host=self.adapter._host(endpoint))))
            except Exception:
                continue
        if not statuses:
            raise AllEndpointsUnavailable("no identity-validated RPC status")
        synced = [(endpoint, status) for endpoint, status in statuses if not status.catching_up]
        selected = max(synced or statuses, key=lambda pair: pair[1].local_height)
        ordered = tuple(endpoint for endpoint, _ in sorted(synced or statuses,
                        key=lambda pair: pair[1].local_height, reverse=True))
        return ObservedHeads(selected[1].local_height, not bool(synced),
                             max((status.local_height for _, status in synced), default=None), selected[0], ordered)

    async def _metadata(self, endpoint: str, minimum: int, maximum: int) -> list[dict]:
        path = "/blockchain?" + urlencode({"minHeight": minimum, "maxHeight": maximum})
        payload = await self.adapter._transport.get_object(endpoint, path, accept_error_payload=True)
        if isinstance(payload.get("error"), dict):
            raise HistoryUnavailable(minimum)
        return parse_blockchain(payload, chain_id=self.adapter.config.chain_id, minimum=minimum, maximum=maximum)

    async def window(self, heads: ObservedHeads, count: int) -> list[dict]:
        minimum = max(1, heads.observed_height - count + 1)
        for endpoint in heads.endpoints:
            try:
                return (await self._metadata(endpoint, minimum, heads.observed_height))[:count]
            except Exception:
                continue
        raise AllEndpointsUnavailable("block metadata unavailable")

    async def sample(self, heads: ObservedHeads) -> list[dict]:
        key = (self.adapter.config.network_id, "block_eta_sample", (heads.confirmed_height,))
        async def load():
            maximum = heads.confirmed_height
            minimum = max(1, maximum - SAMPLE_HEADERS + 1)
            for endpoint in heads.endpoints:
                blocks = []
                end = maximum
                try:
                    while end >= minimum:
                        start = max(minimum, end - METADATA_PAGE_SIZE + 1)
                        blocks.extend(await self._metadata(endpoint, start, end))
                        end = start - 1
                    unique = {item["height"]: item for item in blocks}
                    result = [unique[height] for height in sorted(unique)]
                    if len(result) != maximum - minimum + 1:
                        raise MalformedUpstreamResponse("incomplete ETA sample")
                    return result
                except Exception:
                    continue
            raise AllEndpointsUnavailable("ETA sample unavailable")
        return await self.adapter._cache.get_or_load(key, self.adapter.config.cache_ttl, load)
