"""PostgreSQL writes for the bounded indexer."""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any

class DatabaseError(RuntimeError): pass
class FinalizedDataConflict(DatabaseError): pass

class PostgresDatabase:
    def __init__(self, database_url: str):
        self.database_url = database_url
    def connect(self):
        try:
            import psycopg
        except ImportError as exc:
            raise DatabaseError("Install psycopg to write to PostgreSQL, or use --dry-run") from exc
        return psycopg.connect(self.database_url)
    def get_checkpoint(self) -> int | None:
        with self.connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT last_finalized_height FROM indexer_state WHERE state_key = %s", ("default",))
            row = cur.fetchone(); return row[0] if row else None
    def write_height(self, parsed, chain_id: str, rpc_url: str, finalized_tip: int) -> None:
        with self.connect() as conn:
            with conn.cursor() as cur:
                write_height_cursor(cur, parsed, chain_id, rpc_url, finalized_tip)
            conn.commit()


def _json(v): return json.dumps(v) if v is not None else None

def write_height_cursor(cur, parsed, chain_id: str, rpc_url: str, finalized_tip: int) -> None:
    b=parsed.block; h=parsed.height
    cur.execute("SELECT block_hash_base64, block_hash_hex FROM blocks WHERE height = %s", (h,))
    row=cur.fetchone()
    if row and (row[0] != b["hash_base64"] or row[1] != b["hash_hex"]):
        raise FinalizedDataConflict(f"Conflicting finalized block hash at height {h}")
    cur.execute("""
        INSERT INTO blocks(height, block_hash_base64, block_hash_hex, time_utc, proposer_address, tx_count, raw_block_response)
        VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb)
        ON CONFLICT (height) DO UPDATE SET updated_at=now()
    """, (h,b["hash_base64"],b["hash_hex"],b["time"],b["proposer_address"],b["tx_count"],_json(parsed.raw_block)))
    for tx in parsed.transactions:
        cur.execute("""
          INSERT INTO transactions(block_height, tx_index, raw_base64, raw_base64_length, decoded_bytes, decoded_byte_length, decode_status)
          VALUES (%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT (block_height, tx_index) DO UPDATE SET raw_base64=EXCLUDED.raw_base64, raw_base64_length=EXCLUDED.raw_base64_length, decoded_bytes=EXCLUDED.decoded_bytes, decoded_byte_length=EXCLUDED.decoded_byte_length, decode_status=EXCLUDED.decode_status
        """, (h,tx["index"],tx["raw_base64"],tx["raw_base64_length"],tx["decoded_bytes"],tx["decoded_byte_length"],tx["decode_status"]))
    for i,v in enumerate(parsed.validators):
        cur.execute("""INSERT INTO validators(signing_address, public_key_type, public_key_value, first_seen_height, last_seen_height)
          VALUES (%s,%s,%s,%s,%s) ON CONFLICT (signing_address) DO UPDATE SET last_seen_height=GREATEST(validators.last_seen_height, EXCLUDED.last_seen_height), first_seen_height=LEAST(validators.first_seen_height, EXCLUDED.first_seen_height), updated_at=now()""",
          (v["address"],v.get("pub_key_type") or "unknown",v.get("pub_key_value") or "",h,h))
        cur.execute("""INSERT INTO validator_set_members(height, signing_address, voting_power, proposer_priority, validator_index, raw_validator)
          VALUES (%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (height, signing_address) DO UPDATE SET voting_power=EXCLUDED.voting_power, proposer_priority=EXCLUDED.proposer_priority, validator_index=EXCLUDED.validator_index, raw_validator=EXCLUDED.raw_validator""",
          (h,v["address"],v.get("voting_power") or 0,v.get("proposer_priority"),i,_json(v)))
    for s in parsed.signatures:
        cur.execute("""INSERT INTO validator_signatures(height, signing_address, vote_status, signed, vote_block_id_hash_base64, vote_block_id_hash_hex, vote_block_id_parts_total, vote_block_id_is_zero, block_id_matches_commit, signature_base64, raw_precommit)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb) ON CONFLICT (height, signing_address) DO UPDATE SET vote_status=EXCLUDED.vote_status, signed=EXCLUDED.signed, vote_block_id_hash_base64=EXCLUDED.vote_block_id_hash_base64, vote_block_id_hash_hex=EXCLUDED.vote_block_id_hash_hex, vote_block_id_parts_total=EXCLUDED.vote_block_id_parts_total, vote_block_id_is_zero=EXCLUDED.vote_block_id_is_zero, block_id_matches_commit=EXCLUDED.block_id_matches_commit, signature_base64=EXCLUDED.signature_base64, raw_precommit=EXCLUDED.raw_precommit, updated_at=now()""",
          (h,s["signing_address"],s["vote_status"],s["signed"],s["vote_block_id_hash_base64"],s["vote_block_id_hash_hex"],s["vote_block_id_parts_total"],s["vote_block_id_is_zero"],s["block_id_matches_commit"],s["signature_base64"],_json(s["raw_precommit"])))
    cur.execute("INSERT INTO rpc_endpoints(url, chain_id, is_selected, last_checked_at, last_selected_at, latest_observed_height, observed_lag, catching_up, healthy) VALUES (%s,%s,true,now(),now(),%s,0,false,true) ON CONFLICT (url) DO UPDATE SET is_selected=true,last_checked_at=now(),last_selected_at=now(),latest_observed_height=EXCLUDED.latest_observed_height,healthy=true RETURNING id", (rpc_url,chain_id,finalized_tip+1))
    endpoint_id=cur.fetchone()[0]
    cur.execute("INSERT INTO rpc_endpoint_checks(rpc_endpoint_id, chain_id, latest_observed_height, observed_lag, catching_up, healthy, selected_for_cycle, switch_reason) VALUES (%s,%s,%s,0,false,true,true,%s)", (endpoint_id,chain_id,finalized_tip+1,"bounded one-shot"))
    cur.execute("INSERT INTO indexer_state(state_key, chain_id, last_finalized_height, finalized_tip_height, selected_rpc_endpoint_id) VALUES ('default',%s,%s,%s,%s) ON CONFLICT (state_key) DO UPDATE SET last_finalized_height=EXCLUDED.last_finalized_height, finalized_tip_height=EXCLUDED.finalized_tip_height, selected_rpc_endpoint_id=EXCLUDED.selected_rpc_endpoint_id, updated_at=now()", (chain_id,h,finalized_tip,endpoint_id))
