#!/usr/bin/env python3
"""One-shot, operator-controlled fixed-height vm/qpaths catalog refresh."""
from __future__ import annotations
import logging, sys, time
from pathlib import Path
from urllib.parse import urlsplit
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
from indexer.config import load_config
from indexer.database import PostgresDatabase
from indexer.realm_catalog import parse_qpaths, path_kind
from indexer.rpc import probe_rpc_endpoints, suitable_rpc_probes

LOCK_ID = 0x5245414C4D515054
LOGGER = logging.getLogger("realm_catalog_refresh")

QPATHS_QUERY_PATH = "vm/qpaths?limit=10000"
QPATHS_QUERY_DATA = "gno.land/"


def fetch_realm_paths(client, height: int):
    """Fetch only canonical on-chain realm and package paths."""
    return parse_qpaths(
        client.abci_query(QPATHS_QUERY_PATH, QPATHS_QUERY_DATA, height)
    )

def persist_refresh(cursor, chain_id: str, height: int, endpoint_id: int | None, paths):
    paths = tuple(paths)
    if not paths or len(paths) > 10_000 or len({path for path, _ in paths}) != len(paths):
        raise ValueError("invalid_qpaths_set")
    if any(path_kind(path) != kind for path, kind in paths):
        raise ValueError("invalid_qpaths_set")
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_ID,))
    cursor.execute("UPDATE realm_catalog SET rpc_visible=false,updated_at=now() WHERE chain_id=%s AND rpc_visible", (chain_id,))
    for path, kind in paths:
        cursor.execute("""INSERT INTO realm_catalog(chain_id,path,path_kind,seen_via_rpc,rpc_visible,last_rpc_seen_at)
          VALUES (%s,%s,%s,true,true,now()) ON CONFLICT(chain_id,path) DO UPDATE SET
          path_kind=EXCLUDED.path_kind,seen_via_rpc=true,rpc_visible=true,last_rpc_seen_at=now(),updated_at=now()""",
          (chain_id,path,kind))
    cursor.execute("SELECT count(*) FROM realm_catalog WHERE chain_id=%s AND rpc_visible", (chain_id,))
    if int(cursor.fetchone()[0]) != len(paths): raise RuntimeError("row_count_mismatch")
    cursor.execute("""INSERT INTO realm_catalog_state(chain_id,observed_height,rpc_path_count,source_rpc_endpoint_id,refreshed_at)
      VALUES (%s,%s,%s,%s,now()) ON CONFLICT(chain_id) DO UPDATE SET observed_height=EXCLUDED.observed_height,
      rpc_path_count=EXCLUDED.rpc_path_count,source_rpc_endpoint_id=EXCLUDED.source_rpc_endpoint_id,
      refreshed_at=EXCLUDED.refreshed_at,updated_at=now()""", (chain_id,height,len(paths),endpoint_id))

def main() -> int:
    started=time.monotonic(); probes = []
    try:
        config=load_config(); db=PostgresDatabase(config.database_url)
        preferred=db.get_selected_rpc_url(config.chain_id)
        urls=([preferred] if preferred else [])+[u for u in config.rpc_urls if u != preferred]
        probes=probe_rpc_endpoints(urls,config.chain_id,config.max_height_lag)
        candidate=suitable_rpc_probes(probes)[0]; height=int(candidate.latest_height)-1
        paths=fetch_realm_paths(candidate.client, height)
        with db.connect() as connection:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM rpc_endpoints WHERE chain_id=%s AND url=%s",(config.chain_id,candidate.url)); row=cursor.fetchone()
                persist_refresh(cursor,config.chain_id,height,int(row[0]) if row else None,paths)
            connection.commit()
        realms=sum(kind=='realm' for _,kind in paths)
        LOGGER.info("chain=%s rpc_host=%s height=%s realms=%s packages=%s total=%s elapsed=%.3f status=success",
          config.chain_id,urlsplit(candidate.url).hostname,height,realms,len(paths)-realms,len(paths),time.monotonic()-started)
        return 0
    except Exception as exc:
        LOGGER.error("chain=%s elapsed=%.3f status=%s",getattr(locals().get('config'), 'chain_id','unknown'),time.monotonic()-started,type(exc).__name__[:40])
        return 1
    finally:
        closed = set()
        for probe in probes:
            client = probe.client
            if client is not None and id(client) not in closed:
                closed.add(id(client))
                client.close()
if __name__ == '__main__': logging.basicConfig(level=logging.INFO,format='%(message)s'); sys.exit(main())
