"""Bounded CometBFT block metadata access and future-height estimation."""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import math
import re
from urllib.parse import urlencode

from .adapter import CosmosAdapter
from .errors import (AllEndpointsUnavailable, HistoryUnavailable,
                     MalformedUpstreamResponse)
from .parsing import parse_node_status
from .parsing import parse_rpc_block

MAX_HEIGHT = 9_223_372_036_854_775_807
METADATA_PAGE_SIZE = 20
SAMPLE_HEADERS = 101
MIN_INTERVALS = 20
STALL_SECONDS = 300
MAX_TRANSACTION_COUNT = 2_147_483_647
_HISTORY_ERROR = re.compile(
    r"height\s+(\d+)\s+is not available(?:, lowest height is\s+(\d+))?", re.IGNORECASE)
_BLOCKCHAIN_HISTORY_ERROR = re.compile(
    r"min height\s+(\d+)\s+can't be greater than max height\s+(\d+)", re.IGNORECASE)


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
        if not all(isinstance(value, str) and 1 <= len(value) <= 128 and len(value) % 2 == 0 and value.isascii()
                   and all(char in "0123456789abcdefABCDEF" for char in value)
                   for value in (block_hash, proposer)):
            raise MalformedUpstreamResponse("invalid block identity")
        txs = item.get("num_txs", header.get("num_txs"))
        if isinstance(txs, bool) or not isinstance(txs, (str, int)):
            raise MalformedUpstreamResponse("invalid transaction count")
        if isinstance(txs, str) and (not txs.isascii() or not txs.isdigit() or len(txs) > 10):
            raise MalformedUpstreamResponse("invalid transaction count")
        transaction_count = int(txs)
        if not 0 <= transaction_count <= MAX_TRANSACTION_COUNT:
            raise MalformedUpstreamResponse("invalid transaction count")
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


def _enough_eta_headers(count: int) -> bool:
    intervals = count - 1
    return intervals >= MIN_INTERVALS and intervals - 2 * max(1, intervals // 10) >= MIN_INTERVALS


@dataclass(frozen=True)
class ObservedHeads:
    observed_height: int
    catching_up: bool
    confirmed_height: int | None
    endpoints: tuple[tuple[str, int, bool], ...]

    @property
    def eta_head(self) -> int | None:
        """A synchronized head is reliable only when no checked node is ahead of it."""
        if self.confirmed_height is None or self.observed_height > self.confirmed_height:
            return None
        return self.confirmed_height


class CosmosBlockService:
    def __init__(self, adapter: CosmosAdapter):
        self.adapter = adapter

    async def heads(self) -> ObservedHeads:
        key = (self.adapter.config.network_id, "block_rpc_heads", ())
        async def load():
            statuses = []
            for endpoint in self.adapter.config.rpc_endpoints:
                try:
                    payload = await self.adapter._transport.get_object(endpoint, "/status")
                    status = parse_node_status(payload, network_id=self.adapter.config.network_id,
                                               expected_chain_id=self.adapter.config.chain_id,
                                               source_host=self.adapter._host(endpoint))
                    statuses.append((endpoint, status.local_height, status.catching_up))
                except Exception:
                    continue
            if not statuses:
                raise AllEndpointsUnavailable("no identity-validated RPC status")
            observed = max(height for _, height, _ in statuses)
            synced = [height for _, height, catching_up in statuses if not catching_up]
            ordered = tuple(sorted(statuses, key=lambda item: item[1], reverse=True))
            observed_catching_up = all(catching_up for _, height, catching_up in statuses
                                       if height == observed)
            return ObservedHeads(observed, observed_catching_up,
                                 max(synced, default=None), ordered)
        return await self.adapter._cache.get_or_load(
            key, self.adapter.config.probe_ttl, load)

    async def _metadata(self, endpoint: str, minimum: int, maximum: int) -> list[dict]:
        path = "/blockchain?" + urlencode({"minHeight": minimum, "maxHeight": maximum})
        payload = await self.adapter._transport.get_object(endpoint, path, accept_error_payload=True)
        if isinstance(payload.get("error"), dict):
            error = payload["error"]
            message = error.get("data") or error.get("message")
            match = _BLOCKCHAIN_HISTORY_ERROR.fullmatch(
                message.strip() if isinstance(message, str) else "")
            if match:
                boundary, reported_maximum = int(match.group(1)), int(match.group(2))
                if (0 < boundary <= MAX_HEIGHT and reported_maximum == maximum
                        and boundary > maximum):
                    raise HistoryUnavailable(minimum, boundary)
            raise MalformedUpstreamResponse("unexpected blockchain error")
        return parse_blockchain(payload, chain_id=self.adapter.config.chain_id, minimum=minimum, maximum=maximum)

    async def window(self, heads: ObservedHeads, count: int) -> list[dict]:
        minimum = max(1, heads.observed_height - count + 1)
        key = (self.adapter.config.network_id, "block_metadata_window",
               (heads.observed_height, count))
        async def load():
            for endpoint, height, _ in heads.endpoints:
                if height < heads.observed_height:
                    continue
                try:
                    return (await self._metadata(endpoint, minimum, heads.observed_height))[:count]
                except Exception:
                    continue
            raise AllEndpointsUnavailable("block metadata unavailable")
        return await self.adapter._cache.get_or_load(
            key, self.adapter.config.cache_ttl, load)

    async def block(self, heads: ObservedHeads, height: int):
        """Direct lookup against every identity-checked RPC that reached the height."""
        key = (self.adapter.config.network_id, "direct_block", (height,))
        async def load():
            observations = []
            for endpoint, local_height, _ in heads.endpoints:
                if local_height < height:
                    continue
                try:
                    payload = await self.adapter._transport.get_object(
                        endpoint, f"/block?height={height}", accept_error_payload=True)
                    if isinstance(payload.get("error"), dict):
                        error = payload["error"]
                        message = error.get("data") or error.get("message")
                        match = _HISTORY_ERROR.fullmatch(
                            message.strip() if isinstance(message, str) else "")
                        if match:
                            requested = int(match.group(1))
                            boundary = int(match.group(2)) if match.group(2) else None
                            if (requested != height or boundary is not None
                                    and not height < boundary <= MAX_HEIGHT):
                                raise MalformedUpstreamResponse("invalid history boundary")
                            observations.append(boundary)
                            continue
                        raise MalformedUpstreamResponse("unexpected block error")
                    result = parse_rpc_block(payload, network_id=self.adapter.config.network_id,
                                             expected_chain_id=self.adapter.config.chain_id)
                    if result.height != height:
                        raise MalformedUpstreamResponse("wrong block height")
                    return result
                except HistoryUnavailable as exc:
                    observations.append(exc.lowest_available_height)
                except Exception:
                    continue
            if observations:
                known = [value for value in observations if value is not None]
                raise HistoryUnavailable(height, min(known) if known else None)
            raise AllEndpointsUnavailable("block unavailable")
        return await self.adapter._cache.get_or_load(
            key, self.adapter.config.cache_ttl, load)

    async def sample(self, heads: ObservedHeads) -> list[dict]:
        key = (self.adapter.config.network_id, "block_eta_sample", (heads.eta_head,))
        async def load():
            maximum = heads.eta_head
            minimum = max(1, maximum - SAMPLE_HEADERS + 1)
            best = []
            history_confirmed = False
            for endpoint, height, catching_up in heads.endpoints:
                if catching_up or height < maximum:
                    continue
                blocks = []
                end = maximum
                try:
                    while end >= minimum:
                        start = max(minimum, end - METADATA_PAGE_SIZE + 1)
                        try:
                            blocks.extend(await self._metadata(endpoint, start, end))
                        except HistoryUnavailable:
                            history_confirmed = True
                            break
                        end = start - 1
                    unique = {item["height"]: item for item in blocks}
                    result = [unique[height] for height in sorted(unique)]
                    if result and result[-1]["height"] == maximum and all(
                            right["height"] == left["height"] + 1
                            for left, right in zip(result, result[1:])):
                        best = result if len(result) > len(best) else best
                        if _enough_eta_headers(len(result)):
                            return result
                except Exception:
                    continue
            if best or history_confirmed:
                return best
            raise AllEndpointsUnavailable("ETA sample unavailable")
        return await self.adapter._cache.get_or_load(key, self.adapter.config.cache_ttl, load)
