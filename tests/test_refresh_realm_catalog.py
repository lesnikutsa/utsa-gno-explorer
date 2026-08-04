"""Focused orchestration tests for the Realm catalog refresh entry point."""
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from scripts import refresh_realm_catalog as refresh


class Client:
    def __init__(self, payload="gno.land/r/demo"):
        self.payload = payload
        self.closed = False
        self.calls = []

    def abci_query(self, path, data, height):
        self.calls.append((path, data, height))
        return self.payload

    def close(self):
        self.closed = True


class Cursor:
    def __init__(self):
        self.last = None
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def execute(self, sql, params=()):
        normalized = " ".join(sql.split())
        self.executed.append((normalized, params))
        if normalized.startswith("SELECT id FROM rpc_endpoints"):
            self.last = (17,)
        elif normalized.startswith("SELECT observed_height"):
            self.last = None
        elif normalized.startswith("SELECT count(*)"):
            self.last = (1,)
        else:
            self.last = None

    def fetchone(self):
        return self.last


class Connection:
    def __init__(self):
        self.cursor_value = Cursor()
        self.committed = False

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.committed = True


class Database:
    def __init__(self, preferred="https://user:password@preferred.invalid"):
        self.preferred = preferred
        self.connection = Connection()
        self.connected = False

    def get_selected_rpc_url(self, _chain_id):
        return self.preferred

    def connect(self):
        self.connected = True
        return self.connection


class RefreshMainTests(unittest.TestCase):
    def config(self):
        return SimpleNamespace(
            database_url="postgresql://user:secret@db.invalid/db",
            chain_id="topaz-1",
            rpc_urls=("https://fallback.invalid", "https://user:password@preferred.invalid"),
            max_height_lag=5,
        )

    def run_main(self, probes, database=None):
        database = database or Database()
        captured_urls = []

        def probe(urls, *_):
            captured_urls.extend(urls)
            return probes

        with patch.object(refresh, "load_config", return_value=self.config()), \
             patch.object(refresh, "PostgresDatabase", return_value=database), \
             patch.object(refresh, "probe_rpc_endpoints", side_effect=probe), \
             patch.object(refresh, "suitable_rpc_probes", side_effect=lambda values: [p for p in values if p.suitable]):
            with self.assertLogs("realm_catalog_refresh", logging.INFO) as logs:
                code = refresh.main()
        return code, database, captured_urls, "\n".join(logs.output)

    def test_preferred_rpc_is_probed_first_and_success_closes_all_clients(self):
        preferred = Client()
        fallback = Client()
        probes = [
            SimpleNamespace(client=preferred, url="https://user:password@preferred.invalid", latest_height=102, suitable=True),
            SimpleNamespace(client=fallback, url="https://fallback.invalid", latest_height=101, suitable=True),
        ]
        code, database, urls, output = self.run_main(probes)
        self.assertEqual(code, 0)
        self.assertEqual(urls[0], "https://user:password@preferred.invalid")
        self.assertEqual(preferred.calls[0][2], 101)
        self.assertTrue(preferred.closed)
        self.assertTrue(fallback.closed)
        self.assertTrue(database.connection.committed)
        self.assertIn("status=success", output)
        self.assertNotIn("password", output)
        self.assertNotIn("postgresql://", output)

    def test_unsuitable_preferred_uses_fallback(self):
        preferred = Client()
        fallback = Client()
        probes = [
            SimpleNamespace(client=preferred, url="https://preferred.invalid", latest_height=102, suitable=False),
            SimpleNamespace(client=fallback, url="https://fallback.invalid", latest_height=101, suitable=True),
        ]
        code, _, _, _ = self.run_main(probes, Database("https://preferred.invalid"))
        self.assertEqual(code, 0)
        self.assertEqual(preferred.calls, [])
        self.assertEqual(fallback.calls[0][2], 100)

    def test_no_suitable_rpc_fails_and_closes_clients(self):
        client = Client()
        probe = SimpleNamespace(client=client, url="https://token@rpc.invalid", latest_height=10, suitable=False)
        code, database, _, output = self.run_main([probe])
        self.assertEqual(code, 1)
        self.assertFalse(database.connected)
        self.assertTrue(client.closed)
        self.assertIn("status=RuntimeError", output)
        self.assertNotIn("token", output)

    def test_too_low_height_fails_before_fetch_and_closes_client(self):
        client = Client()
        probe = SimpleNamespace(client=client, url="https://rpc.invalid", latest_height=1, suitable=True)
        code, database, _, _ = self.run_main([probe])
        self.assertEqual(code, 1)
        self.assertEqual(client.calls, [])
        self.assertFalse(database.connected)
        self.assertTrue(client.closed)

    def test_invalid_qpaths_fails_before_database_and_closes_client(self):
        client = Client("malformed")
        probe = SimpleNamespace(client=client, url="https://rpc.invalid", latest_height=10, suitable=True)
        code, database, _, output = self.run_main([probe])
        self.assertEqual(code, 1)
        self.assertFalse(database.connected)
        self.assertTrue(client.closed)
        self.assertNotIn("malformed", output)


if __name__ == "__main__":
    unittest.main()
