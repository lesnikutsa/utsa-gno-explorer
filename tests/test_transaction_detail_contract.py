import unittest
from pathlib import Path
from unittest.mock import MagicMock

from api.database import ApiDatabase, TRANSACTION_DETAIL_SQL


ROOT = Path(__file__).resolve().parents[1]


class TransactionDetailContractTests(unittest.TestCase):
    def test_query_contract(self):
        normalized = " ".join(TRANSACTION_DETAIL_SQL.lower().split())
        self.assertIn("from transactions transaction", normalized)
        self.assertIn("join blocks block on block.height = transaction.block_height", normalized)
        self.assertIn("profile.signing_address = block.proposer_address", normalized)
        self.assertIn("transaction.block_height = %s", normalized)
        self.assertIn("transaction.tx_index = %s", normalized)
        self.assertEqual(TRANSACTION_DETAIL_SQL.count("%s"), 2)
        self.assertNotIn("decoded_bytes", normalized)
        self.assertNotIn("payload_summary", normalized)

    def test_fetch_uses_pair_and_returns_one_row(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = {"block_height": 1, "tx_index": 0}
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        pool = MagicMock()
        pool.connection.return_value.__enter__.return_value = connection
        database = ApiDatabase()
        database.pool = pool
        self.assertEqual(database.fetch_transaction_detail(1, 0)["tx_index"], 0)
        cursor.execute.assert_called_once_with(TRANSACTION_DETAIL_SQL, (1, 0))
        cursor.fetchone.assert_called_once_with()

    def test_no_migration_was_added_for_transaction_detail(self):
        migrations = ROOT / "database" / "migrations"
        if migrations.exists():
            self.assertFalse(any("transaction_detail" in path.name for path in migrations.iterdir()))


if __name__ == "__main__":
    unittest.main()
