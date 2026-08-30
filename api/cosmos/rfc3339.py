"""Python 3.10-compatible RFC3339 timestamp normalization."""

from datetime import datetime, timezone
import re


_RFC3339 = re.compile(
    r"^(?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2})"
    r"(?:\.(?P<fraction>[0-9]{1,9}))?"
    r"(?P<offset>Z|[+-][0-9]{2}:[0-9]{2})$"
)


def normalize_rfc3339(value: str) -> str:
    """Return an RFC3339 instant in UTC, truncated to microsecond precision."""
    match = _RFC3339.fullmatch(value)
    if match is None:
        raise ValueError("invalid RFC3339 timestamp")
    fraction = match.group("fraction")
    normalized_fraction = f".{fraction[:6].ljust(6, '0')}" if fraction else ""
    offset = "+00:00" if match.group("offset") == "Z" else match.group("offset")
    parsed = datetime.fromisoformat(f"{match.group('date')}{normalized_fraction}{offset}")
    return parsed.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
