"""Bounded CometBFT block metadata and future-height estimation."""

from datetime import timedelta
import re

from .errors import AllEndpointsUnavailable, HistoryUnavailable, MalformedUpstreamResponse
from .parsing import _height, _hex, _identity, _mapping, _timestamp, parse_rpc_block
from .rfc3339 import parse_rfc3339

_PRUNED = re.compile(r"height\s+\d+\s+is not available(?:, lowest height is\s+(\d+))?", re.I)
ETA_CHECKPOINT_SPANS = (1000, 500, 200, 80)


def parse_blockchain(payload, *, network_id, expected_chain_id):
    result = _mapping(_mapping(payload).get("result"))
    metas = result.get("block_metas")
    if not isinstance(metas, list) or len(metas) > 101:
        raise MalformedUpstreamResponse("invalid block metadata")
    blocks = []
    for meta in metas:
        meta = _mapping(meta)
        header = _mapping(meta.get("header"))
        _identity(header.get("chain_id"), expected_chain_id)
        count = meta.get("num_txs", "0")
        if isinstance(count, bool) or not isinstance(count, (str, int)) or not str(count).isdigit():
            raise MalformedUpstreamResponse("invalid transaction count")
        blocks.append({"height": _height(header.get("height")),
            "hash": _hex(_mapping(meta.get("block_id")).get("hash"), "block hash", 128),
            "timestamp": _timestamp(header.get("time")),
            "proposer": _hex(header.get("proposer_address"), "proposer address", 128),
            "transaction_count": int(count)})
    return blocks


def estimate_eta(blocks, target_height):
    return estimate_eta_result(blocks, target_height)[0]


def estimate_eta_result(blocks, target_height):
    ordered = sorted(blocks, key=lambda item: item["height"])
    if not ordered or target_height <= ordered[-1]["height"]:
        return None, "insufficient_history"
    intervals = []
    for previous, current in zip(ordered, ordered[1:]):
        if current["height"] != previous["height"] + 1:
            intervals = []
            continue
        seconds = (parse_rfc3339(current["timestamp"]) - parse_rfc3339(previous["timestamp"])).total_seconds()
        if 0 < seconds <= 3600:
            intervals.append(seconds)
    trim = len(intervals) // 10
    usable = sorted(intervals)[trim:len(intervals) - trim if trim else None]
    if len(usable) < 20:
        return None, "insufficient_history"
    seconds = sum(usable) / len(usable)
    remaining = target_height - ordered[-1]["height"]
    try:
        estimated = parse_rfc3339(ordered[-1]["timestamp"]) + timedelta(seconds=seconds * remaining)
    except (OverflowError, ValueError):
        return None, "date_overflow"
    return {"remaining_blocks": remaining, "average_block_seconds": seconds,
            "estimated_at": estimated.isoformat(timespec="microseconds").replace("+00:00", "Z"),
            "sample_intervals": len(usable)}, None


async def checkpoint_average(adapter, latest_height):
    """Calculate a bounded long-range average from at most five block lookups."""
    candidates = await adapter._cached_candidates("rpc")
    latest = None
    endpoint = None
    for candidate in candidates:
        try:
            payload = await adapter._transport.get_object(
                candidate.endpoint, f"/block?height={latest_height}", accept_error_payload=True)
            if isinstance(payload.get("error"), dict):
                continue
            latest = parse_rpc_block(payload, network_id=adapter.config.network_id,
                                     expected_chain_id=adapter.config.chain_id)
            if latest.height == latest_height:
                endpoint = candidate.endpoint
                break
        except Exception:
            continue
    if latest is None or endpoint is None:
        return None
    for span in ETA_CHECKPOINT_SPANS:
        historical_height = latest.height - span
        if historical_height < 1:
            continue
        try:
            payload = await adapter._transport.get_object(
                endpoint, f"/block?height={historical_height}", accept_error_payload=True)
            if isinstance(payload.get("error"), dict):
                continue
            historical = parse_rpc_block(payload, network_id=adapter.config.network_id,
                                         expected_chain_id=adapter.config.chain_id)
            if historical.height != historical_height:
                continue
            actual_span = latest.height - historical.height
            elapsed = (parse_rfc3339(latest.block_time)
                       - parse_rfc3339(historical.block_time)).total_seconds()
            average = elapsed / actual_span
            if actual_span > 0 and 0 < average <= 3600:
                return {"average_block_seconds": average, "sample_intervals": actual_span}
        except Exception:
            continue
    return None


async def metadata(adapter, min_height, max_height):
    path = f"/blockchain?minHeight={min_height}&maxHeight={max_height}"
    observations = []
    for endpoint in adapter.config.rpc_endpoints:
        try:
            payload = await adapter._transport.get_object(endpoint, path, accept_error_payload=True)
            error = payload.get("error")
            if isinstance(error, dict):
                message = str(error.get("data") or error.get("message") or "")
                match = _PRUNED.search(message)
                if match:
                    observations.append(int(match.group(1)) if match.group(1) else None)
                    continue
                raise AllEndpointsUnavailable("metadata unavailable")
            return parse_blockchain(payload, network_id=adapter.config.network_id,
                                    expected_chain_id=adapter.config.chain_id)
        except HistoryUnavailable as exc:
            observations.append(exc.lowest_available_height)
        except Exception:
            continue
    if observations:
        known = [value for value in observations if value is not None]
        raise HistoryUnavailable(min_height, min(known) if known else None)
    raise AllEndpointsUnavailable("block metadata unavailable")


async def metadata_sample(adapter, confirmed_height, *, maximum_headers=101, maximum_requests=6):
    """Load one bounded, contiguous sample despite CometBFT's 20-item page cap."""
    if not 1 <= maximum_headers <= 101 or not 1 <= maximum_requests <= 6:
        raise ValueError("metadata sample bounds are invalid")
    history_observations = []
    for endpoint in adapter.config.rpc_endpoints:
        blocks = {}
        upper = confirmed_height
        known_lowest = None
        for _request_number in range(maximum_requests):
            if upper < 1 or len(blocks) >= maximum_headers:
                break
            lower = max(1, upper - min(20, maximum_headers - len(blocks)) + 1)
            if known_lowest is not None:
                if upper < known_lowest:
                    break
                lower = max(lower, known_lowest)
            path = f"/blockchain?minHeight={lower}&maxHeight={upper}"
            try:
                payload = await adapter._transport.get_object(endpoint, path, accept_error_payload=True)
                error = payload.get("error")
                if isinstance(error, dict):
                    message = str(error.get("data") or error.get("message") or "")
                    match = _PRUNED.search(message)
                    if match:
                        lowest = int(match.group(1)) if match.group(1) else None
                        history_observations.append(lowest)
                        if (lowest is None or lowest < 1 or lowest > confirmed_height
                                or lowest > upper or lowest == known_lowest):
                            break
                        known_lowest = lowest
                        continue
                    else:
                        raise AllEndpointsUnavailable("metadata unavailable")
                page = parse_blockchain(payload, network_id=adapter.config.network_id,
                                        expected_chain_id=adapter.config.chain_id)
                if not page:
                    break
                for block in page:
                    if not lower <= block["height"] <= upper:
                        raise MalformedUpstreamResponse("metadata height outside requested range")
                    previous = blocks.get(block["height"])
                    if previous is not None and previous != block:
                        raise MalformedUpstreamResponse("conflicting duplicate metadata")
                    blocks[block["height"]] = block
                page_low = min(block["height"] for block in page)
                upper = page_low - 1
            except HistoryUnavailable as exc:
                history_observations.append(exc.lowest_available_height)
                break
            except Exception:
                blocks = {}
                break
        if blocks:
            ordered = [blocks[height] for height in sorted(blocks)]
            # Only the newest continuous suffix is useful; never scan across a gap.
            suffix = [ordered[-1]]
            for block in reversed(ordered[:-1]):
                if block["height"] != suffix[0]["height"] - 1:
                    break
                suffix.insert(0, block)
            if suffix[-1]["height"] == confirmed_height:
                return suffix[-maximum_headers:]
    if history_observations:
        known = [height for height in history_observations if height is not None]
        raise HistoryUnavailable(confirmed_height, min(known) if known else None)
    raise AllEndpointsUnavailable("metadata sample unavailable")
