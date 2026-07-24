import unittest
from api.database import ApiDatabase, MissingIndexerStateError, NETWORK_DISTRIBUTION_SQL

class Cursor:
    def __init__(self, row): self.row=row; self.calls=[]
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def execute(self, sql, params): self.calls.append((sql, params))
    def fetchone(self): return self.row
class Connection:
    def __init__(self, cursor): self.value=cursor
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def cursor(self): return self.value
class Pool:
    def __init__(self, cursor): self.cursor=cursor; self.timeouts=[]
    def connection(self, timeout): self.timeouts.append(timeout); return Connection(self.cursor)

class QueryContractTests(unittest.TestCase):
    def test_one_bounded_static_aggregate_query(self):
        cursor=Cursor({"chain_id":"topaz-1", "scanned_at":None}); db=ApiDatabase(); db.pool=Pool(cursor)
        self.assertEqual(db.fetch_network_distribution()["chain_id"], "topaz-1")
        self.assertEqual(len(cursor.calls), 1); self.assertEqual(cursor.calls[0][1], ("default",)); self.assertEqual(db.pool.timeouts, [2.0])
        normalized=" ".join(NETWORK_DISTRIBUTION_SQL.lower().split())
        self.assertIn("from indexer_state state", normalized); self.assertIn("where chain_id = state.chain_id", normalized)
        self.assertIn("order by scanned_at desc, id desc", normalized); self.assertIn("limit 1", normalized)
        for forbidden in ("network_distribution_geo_cache", "network_distribution_snapshot_sources", "rpc_endpoints", "net_info"):
            self.assertNotIn(forbidden, normalized)
    def test_missing_default_state_raises(self):
        cursor=Cursor(None); db=ApiDatabase(); db.pool=Pool(cursor)
        with self.assertRaises(MissingIndexerStateError): db.fetch_network_distribution()

if __name__ == "__main__": unittest.main()
