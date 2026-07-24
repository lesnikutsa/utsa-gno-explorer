"""Multi-source peer collection and unique-public-IP aggregation."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import monotonic

from .tendermint import fetch_net_info


class AllSourcesFailed(RuntimeError):
    pass


@dataclass
class SourceResult:
    source_order: int
    rpc_endpoint_id: int
    success: bool
    reported_peer_count: int | None
    accepted_peer_count: int
    duration_ms: int
    error_code: str | None


def _rank(counter, render):
    return [render(key, count) for key, count in sorted(counter.items(), key=lambda item: (-item[1], str(item[0])))]


def collect_distribution(chain_id, sources, geo_records=None, timeout=10, fetch=fetch_net_info, geo_resolver=None):
    selected: dict[str, str] = {}
    conflicts: set[str] = set()
    results = []
    for order, source in enumerate(sources):
        started = monotonic()
        try:
            reported, peers = fetch(source["url"], timeout)
            for peer in peers:
                if peer.node_id in selected and selected[peer.node_id] != peer.ip:
                    conflicts.add(peer.node_id)
                else:
                    selected.setdefault(peer.node_id, peer.ip)
            results.append(SourceResult(order, source["id"], True, reported, len(peers), int((monotonic()-started)*1000), None))
        except ValueError as exc:
            code = str(exc) if str(exc) in {"timeout", "request_error", "invalid_json", "rpc_error", "malformed_net_info"} else "request_error"
            results.append(SourceResult(order, source["id"], False, None, 0, int((monotonic()-started)*1000), code))
    ok = sum(result.success for result in results)
    if not ok:
        raise AllSourcesFailed("all RPC sources failed")
    ips = set(selected.values())
    geo_records = geo_resolver(ips) if geo_resolver else (geo_records or {})
    successful = {ip: geo_records[ip] for ip in ips if ip in geo_records and geo_records[ip].lookup_success}
    regions, countries = Counter(), Counter()
    providers, provider_names = Counter(), defaultdict(set)
    for ip, geo in successful.items():
        if geo.continent_name: regions[geo.continent_name] += 1
        if geo.country_code and geo.country_name: countries[(geo.country_code, geo.country_name)] += 1
        if geo.asn:
            key = ("asn", geo.asn); provider_names[key].add(geo.provider_name or f"AS{geo.asn}")
        elif geo.provider_name:
            key = ("name", geo.provider_name.casefold()); provider_names[key].add(geo.provider_name)
        else: continue
        providers[key] += 1
    provider_rows = []
    for key, count in sorted(providers.items(), key=lambda item: (-item[1], str(item[0]))):
        provider_rows.append({"asn": key[1] if key[0] == "asn" else None, "name": sorted(provider_names[key], key=lambda x: (x.casefold(), x))[0], "count": count})
    return {
        "chain_id": chain_id, "source_kind": "tendermint_net_info", "scanned_at": datetime.now(timezone.utc).isoformat(),
        "rpc_sources_total": len(results), "rpc_sources_ok": ok, "visible_node_ids": len(selected),
        "unique_public_ips": len(ips), "geolocated_node_ids": sum(ip in successful for ip in selected.values()),
        "geolocated_public_ips": len(successful), "node_id_ip_conflicts": len(conflicts),
        "region_count": len(regions), "country_count": len(countries), "provider_count": len(providers),
        "regions": _rank(regions, lambda name, count: {"name": name, "count": count}),
        "countries": _rank(countries, lambda key, count: {"code": key[0], "name": key[1], "count": count}),
        "providers": provider_rows, "sources": [asdict(result) for result in results],
    }
