import hashlib
import io
import unittest
from contextlib import redirect_stderr
from unittest.mock import MagicMock, patch

from scripts.init_database import EXPECTED_INDEXES, EXPECTED_UNIQUES
from scripts.migrate_transaction_hashes import HASH_INDEX, MigrationPreconditionError, _backfill, _catalog_state, main, migrate_transaction_hashes

EMPTY_HASH = "E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855"
ABC_HASH = "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD"


class BackfillCursor:
    def __init__(self, rows):
        self.rows = {row["id"]: dict(row) for row in rows}
        self.pending = []
        self.update_ids = []

    def execute(self, sql, params):
        last_id, limit = params
        eligible = [(row_id, row["decoded_bytes"]) for row_id, row in sorted(self.rows.items())
                    if row_id > last_id and row["decode_status"] == "decoded" and row.get("tx_hash_hex") is None]
        self.pending = eligible[:limit]

    def fetchall(self):
        result, self.pending = self.pending, []
        return result

    def executemany(self, sql, values):
        for tx_hash, row_id in values:
            self.rows[row_id]["tx_hash_hex"] = tx_hash
            self.update_ids.append(row_id)


class CatalogCursor:
    def __init__(self, *, table=True, column=False, constraints=(), indexes=(), public_count=1):
        self.responses = [[(("transactions" if table else None),)]]
        if not table:
            self.responses.append([(public_count,)])
        else:
            self.responses.extend([[('tx_hash_hex',)] if column else [], list(constraints), list(indexes)])
        self.current = []

    def execute(self, _sql):
        self.current = self.responses.pop(0)

    def fetchone(self):
        return self.current[0] if self.current else None

    def fetchall(self):
        return self.current


class FakeConnection:
    def __init__(self):
        self.committed = False
        self.rolled_back = False
        self.cursor_value = MagicMock()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, _exc, _tb):
        self.rolled_back = exc_type is not None

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True


def decoded(row_id, value, raw_base64="deliberately-not-the-source"):
    return {"id": row_id, "decoded_bytes": value, "raw_base64": raw_base64,
            "decode_status": "decoded", "tx_hash_hex": None}


class TransactionHashMigrationTests(unittest.TestCase):
    def test_known_vectors_and_hash_source(self):
        cursor = BackfillCursor([decoded(1, b""), decoded(2, b"abc", "YWJj-is-not-hashed")])
        _backfill(cursor, 10)
        self.assertEqual(cursor.rows[1]["tx_hash_hex"], EMPTY_HASH)
        self.assertEqual(cursor.rows[2]["tx_hash_hex"], ABC_HASH)
        self.assertNotEqual(cursor.rows[2]["tx_hash_hex"], hashlib.sha256(b"YWJj-is-not-hashed").hexdigest().upper())

    def test_batch_size_one_is_ordered_and_updates_all_rows(self):
        cursor = BackfillCursor([decoded(3, b"three"), decoded(1, b"one"), decoded(2, b"two")])
        _backfill(cursor, 1)
        self.assertEqual(cursor.update_ids, [1, 2, 3])
        self.assertTrue(all(cursor.rows[row_id]["tx_hash_hex"] for row_id in (1, 2, 3)))

    def test_duplicate_hashes_are_preserved(self):
        cursor = BackfillCursor([decoded(10, b"same"), decoded(11, b"same")])
        _backfill(cursor, 1)
        expected = hashlib.sha256(b"same").hexdigest().upper()
        self.assertEqual(cursor.update_ids, [10, 11])
        self.assertEqual(cursor.rows[10]["tx_hash_hex"], expected)
        self.assertEqual(cursor.rows[11]["tx_hash_hex"], expected)

    def test_non_decoded_states_remain_null(self):
        rows = [decoded(1, b"abc"),
                {"id": 2, "decoded_bytes": None, "decode_status": "invalid_base64", "tx_hash_hex": None},
                {"id": 3, "decoded_bytes": None, "decode_status": "not_attempted", "tx_hash_hex": None}]
        cursor = BackfillCursor(rows)
        _backfill(cursor, 1)
        self.assertEqual(cursor.update_ids, [1])
        self.assertIsNone(cursor.rows[2]["tx_hash_hex"])
        self.assertIsNone(cursor.rows[3]["tx_hash_hex"])

    def test_catalog_legacy_empty_partial_and_compatible_states(self):
        self.assertEqual(_catalog_state(CatalogCursor()), "legacy")
        self.assertEqual(_catalog_state(CatalogCursor(table=False, public_count=0)), "empty")
        self.assertEqual(_catalog_state(CatalogCursor(column=True)), "unknown")
        constraints = [("transactions_tx_hash_hex_format", True), ("transactions_tx_hash_consistent", True)]
        correct = [(HASH_INDEX, False, "(tx_hash_hex IS NOT NULL)")]
        self.assertEqual(_catalog_state(CatalogCursor(column=True, constraints=constraints, indexes=correct)), "compatible")
        self.assertEqual(_catalog_state(CatalogCursor(constraints=constraints)), "unknown")
        self.assertEqual(_catalog_state(CatalogCursor(indexes=correct)), "unknown")

    def test_wrong_unique_or_predicate_index_is_rejected(self):
        constraints = [("transactions_tx_hash_hex_format", True), ("transactions_tx_hash_consistent", True)]
        unique = [("transactions_tx_hash_hex_unique", True, "(tx_hash_hex IS NOT NULL)")]
        wrong_predicate = [(HASH_INDEX, False, "(tx_hash_hex IS NULL)")]
        self.assertEqual(_catalog_state(CatalogCursor(column=True, constraints=constraints, indexes=unique)), "unknown")
        self.assertEqual(_catalog_state(CatalogCursor(column=True, constraints=constraints, indexes=wrong_predicate)), "unknown")

    def test_final_schema_expects_non_unique_partial_index_and_position_unique(self):
        self.assertEqual(EXPECTED_INDEXES[HASH_INDEX],
                         ("transactions", False, (("tx_hash_hex", "ASC"),), "tx_hash_hex IS NOT NULL"))
        self.assertNotIn("transactions_tx_hash_hex_unique", EXPECTED_INDEXES)
        self.assertIn(("transactions", ("block_height", "tx_index")), EXPECTED_UNIQUES)

    def test_main_sanitizes_failure_output(self):
        secret = "postgresql://user:super-secret-password@example.invalid/db"
        raw = "sensitive raw transaction"
        stderr = io.StringIO()
        with patch.dict("os.environ", {"DATABASE_URL": secret}), patch(
            "scripts.migrate_transaction_hashes.migrate_transaction_hashes", side_effect=MigrationPreconditionError(raw)
        ), redirect_stderr(stderr):
            self.assertEqual(main([]), 1)
        output = stderr.getvalue()
        self.assertNotIn(secret, output)
        self.assertNotIn("super-secret-password", output)
        self.assertNotIn(raw, output)

    def test_failure_rolls_back_and_compatible_run_is_idempotent(self):
        failed = FakeConnection()
        with patch("scripts.migrate_transaction_hashes._catalog_state", return_value="legacy"), \
             patch("scripts.migrate_transaction_hashes._validate_exact_legacy"), \
             patch("scripts.migrate_transaction_hashes._backfill", side_effect=RuntimeError("failure")):
            with self.assertRaises(RuntimeError):
                migrate_transaction_hashes("safe-url", connect=lambda _url: failed)
        self.assertTrue(failed.rolled_back)
        self.assertFalse(failed.committed)

        compatible = FakeConnection()
        with patch("scripts.migrate_transaction_hashes._catalog_state", return_value="compatible"), \
             patch("scripts.migrate_transaction_hashes.fetch_schema_snapshot", return_value={}), \
             patch("scripts.migrate_transaction_hashes.validate_schema_snapshot"):
            self.assertEqual(migrate_transaction_hashes("safe-url", connect=lambda _url: compatible), "already-compatible")
        self.assertFalse(compatible.committed)


if __name__ == "__main__":
    unittest.main()
