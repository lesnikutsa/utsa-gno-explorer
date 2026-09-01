"""Pure normalization and liveness helpers for Cosmos validator lists."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_CEILING


def category(validator: dict) -> str:
    if validator.get("jailed") is True:
        return "jailed"
    return "active" if validator.get("status") == "BOND_STATUS_BONDED" else "inactive"


def miss_metrics(missed: int, window: int, minimum_signed: str, block_seconds: float | None):
    required = int((Decimal(minimum_signed) * window).to_integral_value(rounding=ROUND_CEILING))
    allowed = max(0, window - required)
    remaining = max(0, allowed - missed)
    return {
        "signed_percent": float(Decimal(max(0, window - missed)) * 100 / window) if window else None,
        "allowed_misses": allowed,
        "remaining_budget": remaining,
        "jail_eta_seconds": (None if block_seconds is None else
                             round(remaining * block_seconds) if remaining else 0),
    }


def nearest_snapshot(history: list[tuple[datetime, dict]], now: datetime, tolerance=timedelta(minutes=20)):
    target = now.astimezone(timezone.utc) - timedelta(hours=24)
    candidates = [(abs(at - target), values) for at, values in history if abs(at - target) <= tolerance]
    return min(candidates, default=(None, None), key=lambda item: item[0])[1]


def aggregate_commit(strip: dict[str, list[str]], active_addresses: set[str], commit: dict | None):
    """Append one block-centric point for every active consensus address."""
    if commit is None:
        for address in active_addresses:
            strip.setdefault(address, []).append("unknown")
        return
    signatures = commit.get("signatures") if isinstance(commit, dict) else None
    if not isinstance(signatures, list):
        return aggregate_commit(strip, active_addresses, None)
    represented = {str(item.get("validator_address", "")).upper(): item.get("block_id_flag")
                   for item in signatures if isinstance(item, dict) and item.get("validator_address")}
    for address in active_addresses:
        flag = represented.get(address)
        point = ("signed" if flag in (2, "2", "BLOCK_ID_FLAG_COMMIT") else
                 "missed" if flag in (1, 3, "1", "3", "BLOCK_ID_FLAG_ABSENT", "BLOCK_ID_FLAG_NIL") else
                 "unknown")
        strip.setdefault(address, []).append(point)


def signing_height_range(previous_height: int, latest_height: int) -> range:
    """Return only useful missing heights, capped to the newest 50 blocks."""
    if latest_height < 1 or previous_height >= latest_height:
        return range(0)
    return range(max(1, previous_height + 1, latest_height - 49), latest_height + 1)
