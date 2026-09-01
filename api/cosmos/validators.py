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
        "jail_eta_seconds": round(remaining * block_seconds) if block_seconds and remaining else 0,
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
    present = {str(item.get("validator_address", "")).upper() for item in signatures
               if isinstance(item, dict) and item.get("block_id_flag") in (2, "BLOCK_ID_FLAG_COMMIT")}
    for address in active_addresses:
        strip.setdefault(address, []).append("signed" if address in present else "missed")

