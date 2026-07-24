#!/usr/bin/env python3
"""Collect one observed network-distribution snapshot from healthy RPC sources."""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from network_distribution.collector import AllSourcesFailed, collect_distribution
from network_distribution.config import Config
from network_distribution.geo import resolve_geo
from network_distribution.persistence import (acquire_lock, has_geolocated_snapshot, load_geo_cache,
    release_lock, save_geo_cache, save_snapshot, select_sources)

def parser():
    value = lambda text: int(text) if text.isdigit() and 1 <= int(text) <= 20 else (_ for _ in ()).throw(argparse.ArgumentTypeError("must be between 1 and 20"))
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rpc-limit", type=value, help="Maximum healthy RPC sources (1-20; default: environment or 1).")
    p.add_argument("--dry-run", action="store_true", help="Read and collect without PostgreSQL writes.")
    p.add_argument("--pretty", action="store_true", help="Pretty-print JSON output (primarily for dry runs).")
    return p

def run(args):
    import psycopg
    config=Config.from_env(args.rpc_limit)
    with psycopg.connect(config.database_url) as connection:
        if not acquire_lock(connection, config.chain_id): raise RuntimeError("another network-distribution collector is running")
        try:
            sources=select_sources(connection, config.chain_id, config.rpc_limit, config.rpc_health_max_age)
            if not sources: raise RuntimeError("no eligible healthy RPC sources")
            refreshed=[]
            def geo_resolver(ips):
                records, updates=resolve_geo(ips, load_geo_cache(connection, ips), config)
                refreshed.extend(updates); return records
            result=collect_distribution(config.chain_id, sources, timeout=config.rpc_timeout, geo_resolver=geo_resolver)
            if args.dry_run:
                print(json.dumps(result, indent=2 if args.pretty else None, sort_keys=True)); return 0
            if refreshed: save_geo_cache(connection, refreshed)
            if (result["unique_public_ips"] > 0 and result["geolocated_public_ips"] == 0
                    and has_geolocated_snapshot(connection, config.chain_id)):
                print("network distribution snapshot skipped: geo_unavailable")
                return 0
            save_snapshot(connection, result, config.snapshot_retention)
            print(f"network distribution saved: chain={config.chain_id} rpc={result['rpc_sources_ok']}/{result['rpc_sources_total']} nodes={result['visible_node_ids']} ips={result['unique_public_ips']} geolocated_ips={result['geolocated_public_ips']}")
            return 0
        finally:
            failure_in_flight = sys.exc_info()[0] is not None
            try:
                release_lock(connection, config.chain_id)
            except Exception:
                if not failure_in_flight:
                    raise

def main(argv=None):
    args=parser().parse_args(argv)
    try: return run(args)
    except (ValueError, AllSourcesFailed) as exc:
        print(f"network distribution failed: {exc}", file=sys.stderr); return 1
    except RuntimeError as exc:
        message = str(exc)
        if message not in {"another network-distribution collector is running", "no eligible healthy RPC sources"}:
            message = "internal_error"
        print(f"network distribution failed: {message}", file=sys.stderr); return 1
    except Exception:
        print("network distribution failed: internal_error", file=sys.stderr); return 1
if __name__ == "__main__": raise SystemExit(main())
