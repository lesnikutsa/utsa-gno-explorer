import math
import unittest
from pathlib import Path

from indexer.database import response_seconds_to_latency_ms


ROOT = Path(__file__).resolve().parents[1]


class RpcLatencySchemaTests(unittest.TestCase):
    def test_fresh_schema_and_migration_define_bounded_nullable_latency(self):
        schema = (ROOT / "database/schema.sql").read_text()
        migration = (ROOT / "database/migrations/0005_add_rpc_endpoint_latency.sql").read_text()
        self.assertIn("latency_ms INTEGER", schema)
        self.assertIn("ADD COLUMN IF NOT EXISTS latency_ms INTEGER", migration)
        self.assertIn("latency_ms BETWEEN 0 AND 30000", migration)
        self.assertNotIn("DROP ", migration.upper())

    def test_response_seconds_conversion(self):
        self.assertEqual(response_seconds_to_latency_ms(0), 0)
        self.assertEqual(response_seconds_to_latency_ms(0.0434), 43)
        self.assertEqual(response_seconds_to_latency_ms(0.0435), 44)
        self.assertEqual(response_seconds_to_latency_ms(31), 30000)
        for value in (None, -1, True, False, math.nan, math.inf, "1"):
            self.assertIsNone(response_seconds_to_latency_ms(value))

    def test_network_query_is_one_bounded_operation_without_rpc_client(self):
        database_source = (ROOT / "api/database.py").read_text()
        app_source = (ROOT / "api/app.py").read_text()
        query = database_source.split('NETWORK_SQL = """', 1)[1].split('"""', 1)[0]
        method = database_source.split("def fetch_network_overview", 1)[1].split("def fetch_network_distribution", 1)[0]
        self.assertEqual(method.count("cursor.execute("), 1)
        self.assertEqual(query.count("FROM rpc_endpoints bounded"), 1)
        self.assertIn("LIMIT 32", query)
        self.assertNotIn("probe_rpc", app_source)
        self.assertNotIn("last_error',", query)


if __name__ == "__main__":
    unittest.main()
