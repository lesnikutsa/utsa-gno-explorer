"""PostgreSQL source selection, cache, locking, and snapshot persistence."""
from __future__ import annotations

import hashlib
import json

from .geo import GeoRecord


def select_sources(connection, chain_id: str, limit: int, max_age: int) -> list[dict]:
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT id, url FROM rpc_endpoints
            WHERE chain_id = %s AND is_enabled AND healthy AND catching_up IS FALSE
              AND last_checked_at IS NOT NULL
              AND last_checked_at >= now() - (%s * interval '1 second')
            ORDER BY is_selected DESC, latest_observed_height DESC NULLS LAST, id ASC
            LIMIT %s
        """, (chain_id, max_age, limit))
        return [{"id": row[0], "url": row[1]} for row in cursor.fetchall()]


def advisory_key(chain_id: str) -> int:
    raw = hashlib.sha256(f"network-distribution:{chain_id}".encode()).digest()[:8]
    return int.from_bytes(raw, "big", signed=True)


def acquire_lock(connection, chain_id: str) -> bool:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_try_advisory_lock(%s)", (advisory_key(chain_id),))
        return bool(cursor.fetchone()[0])


def release_lock(connection, chain_id: str) -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_unlock(%s)", (advisory_key(chain_id),))


def load_geo_cache(connection, ips: set[str]) -> dict[str, GeoRecord]:
    if not ips: return {}
    with connection.cursor() as cursor:
        cursor.execute("""SELECT ip::text, lookup_success, continent_name, country_code, country_name,
            region_name, asn, provider_name, lookup_provider, fetched_at, expires_at, error_code
            FROM network_distribution_geo_cache WHERE ip = ANY(%s::inet[])""", (list(ips),))
        return {row[0]: GeoRecord(*row) for row in cursor.fetchall()}


def save_geo_cache(connection, records: list[GeoRecord]) -> None:
    with connection.cursor() as cursor:
        for row in records:
            cursor.execute("""INSERT INTO network_distribution_geo_cache
                (ip, lookup_success, continent_name, country_code, country_name, region_name, asn,
                 provider_name, lookup_provider, fetched_at, expires_at, error_code)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (ip) DO UPDATE SET lookup_success=excluded.lookup_success,
                continent_name=excluded.continent_name,country_code=excluded.country_code,
                country_name=excluded.country_name,region_name=excluded.region_name,asn=excluded.asn,
                provider_name=excluded.provider_name,lookup_provider=excluded.lookup_provider,
                fetched_at=excluded.fetched_at,expires_at=excluded.expires_at,error_code=excluded.error_code,
                updated_at=now()""", tuple(row.__dict__.values()))
    connection.commit()


def save_snapshot(connection, result: dict, retention: int) -> int:
    columns = ["chain_id","source_kind","scanned_at","rpc_sources_total","rpc_sources_ok","visible_node_ids",
               "unique_public_ips","geolocated_node_ids","geolocated_public_ips","node_id_ip_conflicts",
               "region_count","country_count","provider_count","regions","countries","providers"]
    values = [result[name] for name in columns]
    values[-3:] = [json.dumps(value) for value in values[-3:]]
    with connection.transaction(), connection.cursor() as cursor:
        cursor.execute(f"INSERT INTO network_distribution_snapshots ({','.join(columns)}) VALUES ({','.join(['%s']*len(columns))}) RETURNING id", values)
        snapshot_id = cursor.fetchone()[0]
        for source in result["sources"]:
            cursor.execute("""INSERT INTO network_distribution_snapshot_sources
              (snapshot_id,source_order,rpc_endpoint_id,success,reported_peer_count,accepted_peer_count,duration_ms,error_code)
              VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""", (snapshot_id, source["source_order"], source["rpc_endpoint_id"], source["success"], source["reported_peer_count"], source["accepted_peer_count"], source["duration_ms"], source["error_code"]))
        cursor.execute("""DELETE FROM network_distribution_snapshots WHERE chain_id=%s AND id NOT IN
          (SELECT id FROM network_distribution_snapshots WHERE chain_id=%s ORDER BY scanned_at DESC,id DESC LIMIT %s)""",
          (result["chain_id"], result["chain_id"], retention))
    return snapshot_id
