"""Pure normalization and liveness helpers for Cosmos validator lists."""

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


def target_height_24h(current_height: int, average_block_seconds: float | None) -> int | None:
    if current_height < 1 or not average_block_seconds or average_block_seconds <= 0:
        return None
    return max(1, current_height - round(86400 / average_block_seconds))


def aggregate_commit(strip: dict[str, list[dict]], active_addresses: set[str], commit: dict | None,
                     validator_addresses: list[str] | None, height: int, block_time: str | None):
    """Append one block-centric point for every active consensus address."""
    if commit is None:
        for address in active_addresses:
            strip.setdefault(address, []).append({"height": height, "status": "unknown", "time": block_time})
        return
    signatures = commit.get("signatures") if isinstance(commit, dict) else None
    if not isinstance(signatures, list):
        return aggregate_commit(strip, active_addresses, None, None, height, block_time)
    if (not isinstance(validator_addresses, list) or not validator_addresses
            or len(set(validator_addresses)) != len(validator_addresses)):
        return aggregate_commit(strip, active_addresses, None, None, height, block_time)
    validator_set = set(validator_addresses)
    participating = set()
    absent_count = 0
    for signature in signatures:
        if not isinstance(signature, dict):
            return aggregate_commit(strip, active_addresses, None, None, height, block_time)
        flag = signature.get("block_id_flag")
        reported = signature.get("validator_address")
        if flag in (2, 3, "2", "3", "BLOCK_ID_FLAG_COMMIT", "BLOCK_ID_FLAG_NIL"):
            if not isinstance(reported, str) or not reported:
                return aggregate_commit(strip, active_addresses, None, None, height, block_time)
            address = reported.upper()
            if address not in validator_set or address in participating:
                return aggregate_commit(strip, active_addresses, None, None, height, block_time)
            participating.add(address)
        elif flag in (1, "1", "BLOCK_ID_FLAG_ABSENT"):
            absent_count += 1
        else:
            return aggregate_commit(strip, active_addresses, None, None, height, block_time)
    missed = validator_set - participating
    if len(participating) + absent_count != len(validator_set) or len(missed) != absent_count:
        return aggregate_commit(strip, active_addresses, None, None, height, block_time)
    for address in active_addresses:
        point = "signed" if address in participating else "missed" if address in missed else "unknown"
        strip.setdefault(address, []).append({"height": height, "status": point, "time": block_time})


def approximate_token_delta(tokens: int, current_power: int, historical_power: int | None) -> int | None:
    if historical_power is None or current_power <= 0 or tokens < 0:
        return None
    return int((Decimal(current_power - historical_power) * Decimal(tokens) / Decimal(current_power)).to_integral_value())


def signing_height_range(previous_height: int, latest_height: int) -> range:
    """Return only useful missing heights, capped to the newest 50 blocks."""
    if latest_height < 1 or previous_height >= latest_height:
        return range(0)
    return range(max(1, previous_height + 1, latest_height - 49), latest_height + 1)
