import unittest

from scripts.migrate_transaction_hashes import MigrationPreconditionError, _backfill


class BackfillCursor:
    def __init__(self, rows):
        self.rows = rows
        self.pending = []

    def execute(self, sql, params):
        last_id, limit = params
        self.pending = [row for row in self.rows if row[0] > last_id][:limit]

    def fetchall(self):
        result, self.pending = self.pending, []
        return result

    def executemany(self, sql, values):
        self.updates = values


class TransactionHashMigrationTests(unittest.TestCase):
    def test_backfill_hashes_decoded_bytes_in_id_order(self):
        cursor = BackfillCursor([(1, b""), (2, b"abc")])
        _backfill(cursor, 10)
        self.assertEqual(cursor.updates, [
            ("E3B0C44298FC1C149AFBF4C8996FB92427AE41E4649B934CA495991B7852B855", 1),
            ("BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD", 2),
        ])

    def test_duplicate_hash_fails_without_discarding_rows(self):
        with self.assertRaisesRegex(MigrationPreconditionError, "duplicate"):
            _backfill(BackfillCursor([(1, b"same"), (2, b"same")]), 10)


if __name__ == "__main__":
    unittest.main()
