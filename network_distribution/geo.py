"""Bounded GeoIP/ASN lookup and cache orchestration."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import requests


@dataclass(frozen=True)
class GeoRecord:
    ip: str
    lookup_success: bool
    continent_name: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    region_name: str | None = None
    asn: int | None = None
    provider_name: str | None = None
    lookup_provider: str = "ipwho.is"
    fetched_at: datetime | None = None
    expires_at: datetime | None = None
    error_code: str | None = None


def lookup_ip(ip: str, api_url: str, timeout: int, success_ttl: int, failure_ttl: int) -> GeoRecord:
    now = datetime.now(timezone.utc)
    error = None
    data = None
    try:
        response = requests.get(f"{api_url}/{ip}", timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except requests.Timeout:
        error = "timeout"
    except (requests.RequestException, ValueError):
        error = "request_error"
    if not isinstance(data, dict) or data.get("success") is not True:
        error = error or "lookup_failed"
        return GeoRecord(ip, False, fetched_at=now, expires_at=now + timedelta(seconds=failure_ttl), error_code=error)
    connection = data.get("connection") if isinstance(data.get("connection"), dict) else {}
    try:
        asn = int(connection.get("asn")) if connection.get("asn") is not None else None
        asn = asn if asn and asn > 0 else None
    except (TypeError, ValueError):
        asn = None
    provider = connection.get("org") or connection.get("isp") or (f"AS{asn}" if asn else None)
    code = data.get("country_code")
    code = code.upper() if isinstance(code, str) and len(code) == 2 and code.isascii() and code.isalpha() else None
    return GeoRecord(ip, True, data.get("continent"), code, data.get("country"), data.get("region"), asn,
                     str(provider)[:255] if provider else None, fetched_at=now,
                     expires_at=now + timedelta(seconds=success_ttl))


def resolve_geo(ips: set[str], cached: dict[str, GeoRecord], config) -> tuple[dict[str, GeoRecord], list[GeoRecord]]:
    now = datetime.now(timezone.utc)
    usable = {ip: row for ip, row in cached.items() if row.expires_at and row.expires_at > now}
    missing = sorted(ips - usable.keys())[:config.geo_max_lookups]
    with ThreadPoolExecutor(max_workers=config.geo_concurrency) as executor:
        refreshed = list(executor.map(lambda ip: lookup_ip(ip, config.geo_api_url, config.geo_timeout,
                                                           config.geo_cache_ttl, config.geo_failure_ttl), missing))
    result = dict(usable)
    result.update({row.ip: row for row in refreshed})
    return result, refreshed
