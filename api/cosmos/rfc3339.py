"""Python 3.10 compatible RFC3339 parsing used by all Cosmos responses."""

from datetime import datetime, timedelta, timezone
import re

_RFC3339 = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2})T(?P<time>\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,9}))?(?P<zone>Z|[+-]\d{2}:\d{2})$"
)


def parse_rfc3339(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp is not text")
    match = _RFC3339.fullmatch(value)
    if not match:
        raise ValueError("invalid RFC3339 timestamp")
    zone = match.group("zone")
    if zone == "Z":
        offset = timezone.utc
    else:
        hours, minutes = map(int, zone[1:].split(":"))
        if hours > 23 or minutes > 59:
            raise ValueError("invalid RFC3339 offset")
        delta = timedelta(hours=hours, minutes=minutes)
        offset = timezone(delta if zone[0] == "+" else -delta)
    fraction = (match.group("fraction") or "")[:6].ljust(6, "0")
    parsed = datetime.strptime(
        f"{match.group('date')}T{match.group('time')}", "%Y-%m-%dT%H:%M:%S"
    ).replace(microsecond=int(fraction or "0"), tzinfo=offset)
    return parsed.astimezone(timezone.utc)


def normalize_rfc3339(value: str) -> str:
    return parse_rfc3339(value).isoformat(timespec="microseconds").replace("+00:00", "Z")
