"""Bounded CometBFT block metadata and future-height estimation."""

from datetime import timedelta
import math
import re

from .errors import AllEndpointsUnavailable, HistoryUnavailable, MalformedUpstreamResponse
from .parsing import _height, _hex, _identity, _mapping, _timestamp
from .rfc3339 import parse_rfc3339

_PRUNED = re.compile(r"height\s+\d+\s+is not available(?:, lowest height is\s+(\d+))?", re.I)


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
