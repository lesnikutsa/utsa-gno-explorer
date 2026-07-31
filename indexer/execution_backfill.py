"""Resumable backfill of canonical execution results for local transactions."""
from __future__ import annotations

from scripts.inspect_rpc import RpcError
from .parsers import parse_block, parse_execution_results
from .rpc import canonical_block_hash_hex, probe_rpc_endpoints, suitable_rpc_probes


def missing_heights(cursor, start: int | None, end: int | None, limit: int) -> list[int]:
    cursor.execute(
        """
        SELECT DISTINCT t.block_height
        FROM transactions t
        LEFT JOIN transaction_execution_results r
          ON (r.block_height, r.tx_index) = (t.block_height, t.tx_index)
        WHERE r.block_height IS NULL
          AND (%s::bigint IS NULL OR t.block_height >= %s::bigint)
          AND (%s::bigint IS NULL OR t.block_height <= %s::bigint)
        ORDER BY t.block_height
        LIMIT %s
        """,
        (start, start, end, end, limit),
    )
    return [int(row[0]) for row in cursor.fetchall()]


def backfill_height(database, height: int, probes) -> None:
    last_error = None
    for probe in suitable_rpc_probes(probes):
        try:
            block_payload = probe.client.get("block", height=height)
            results_payload = probe.client.get("block_results", height=height)
            block = parse_block(block_payload)
            results = parse_execution_results(
                height,
                results_payload,
                len(block["transactions"]),
            )
            with database.connect() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT block_hash_hex FROM blocks WHERE height=%s",
                        (height,),
                    )
                    row = cursor.fetchone()
                    if row is None or row[0] != canonical_block_hash_hex(block_payload):
                        raise RpcError(f"Local block hash mismatch at height {height}")
                    cursor.execute(
                        "SELECT tx_index FROM transactions "
                        "WHERE block_height=%s ORDER BY tx_index",
                        (height,),
                    )
                    if [int(item[0]) for item in cursor.fetchall()] != list(
                        range(len(results))
                    ):
                        raise RpcError(
                            f"Local transaction index mismatch at height {height}"
                        )
                    for result in results:
                        cursor.execute(
                            """
                            INSERT INTO transaction_execution_results(
                                block_height,
                                tx_index,
                                execution_status,
                                gas_wanted,
                                gas_used,
                                error_text,
                                log_text,
                                info_text,
                                data_base64,
                                events,
                                raw_result,
                                source_rpc_endpoint_id
                            )
                            VALUES (
                                %s,
                                %s,
                                %s,
                                %s,
                                %s,
                                %s,
                                %s,
                                %s,
                                %s,
                                %s::jsonb,
                                %s::jsonb,
                                %s
                            )
                            ON CONFLICT (block_height, tx_index) DO NOTHING
                            """,
                            (
                                height,
                                result["tx_index"],
                                result["execution_status"],
                                result["gas_wanted"],
                                result["gas_used"],
                                result["error_text"],
                                result["log_text"],
                                result["info_text"],
                                result["data_base64"],
                                database_json(result["events"]),
                                database_json(result["raw_result"]),
                                database.selected_rpc_endpoint_id,
                            ),
                        )
                connection.commit()
            return
        except (RpcError, OSError) as exc:
            last_error = exc
    raise RpcError(f"Every RPC failed for backfill height {height}: {last_error}")


def database_json(value):
    import json

    return json.dumps(value) if value is not None else None
