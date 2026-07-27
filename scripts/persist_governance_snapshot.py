#!/usr/bin/env python3
"""Discover and atomically persist one complete governance snapshot."""
from __future__ import annotations
import argparse, os, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT))
from governance.gno import DEFAULT_REALM, GovernanceParseError, GovernanceSource, discover_governance
from indexer.database import PostgresDatabase
from indexer.governance_persistence import GovernancePersistenceError
from indexer.rpc import select_rpc
from scripts.inspect_rpc import RpcError, configured_chain_id, configured_max_height_lag, configured_rpc_urls, load_dotenv

def parser():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--realm"); return p

def run(args):
    load_dotenv(); database_url=os.getenv("DATABASE_URL","")
    if not database_url: raise GovernancePersistenceError("DATABASE_URL is required")
    chain=configured_chain_id(); realm=args.realm or os.getenv("GNO_GOVERNANCE_REALM","").strip() or DEFAULT_REALM
    if not realm.startswith("gno.land/r/") or ":" in realm: raise GovernancePersistenceError("invalid governance realm")
    selected=select_rpc(configured_rpc_urls(),chain,configured_max_height_lag(),10)
    source=GovernanceSource(chain,selected.client.base_url.rstrip("/"),selected.latest_height,realm)
    discovery=discover_governance(selected.client,source,capture_raw=True)
    result=PostgresDatabase(database_url).persist_governance_snapshot(discovery,chain)
    print("Governance snapshot persisted:")
    print(f"action={result.action}\nchain_id={chain}\nrealm={realm}\nsource_height={result.source_height}\npages={result.page_count}\nproposals={result.proposal_count}\nvotes={result.vote_count}")
    return 0

def main(argv=None):
    args=parser().parse_args(argv)
    try: return run(args)
    except (RpcError, OSError):
        print("Governance persistence failed: rpc_error", file=sys.stderr); return 1
    except (GovernancePersistenceError, GovernanceParseError, ValueError) as exc:
        print(f"Governance persistence failed: {exc}", file=sys.stderr); return 1
    except Exception:
        print("Governance persistence failed: internal_error",file=sys.stderr); return 1
if __name__=="__main__": raise SystemExit(main())
