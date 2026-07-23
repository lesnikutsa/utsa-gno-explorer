import inspect
import re
import unittest

from api import app
from api.database import NETWORK_SQL
from api.schemas import NetworkResponse


class AverageBlockTimeContractTests(unittest.TestCase):
    def setUp(self):
        self.sql = re.sub(r"\s+", " ", NETWORK_SQL.lower())

    def test_query_uses_a_bounded_indexed_sample(self):
        self.assertIn("from blocks where height <= s.last_finalized_height", self.sql)
        self.assertIn("order by height desc limit 20", self.sql)
        self.assertNotIn("order by height desc limit 100", self.sql)
        self.assertIn("count(*)::bigint as sample_size", self.sql)

    def test_query_validates_continuity_and_endpoint_times(self):
        self.assertIn("maximum_height - minimum_height + 1 = sample_size", self.sql)
        self.assertIn("array_agg(time_utc order by height asc)", self.sql)
        self.assertIn("array_agg(time_utc order by height desc)", self.sql)
        self.assertIn("sample_size >= 2", self.sql)
        self.assertIn("ending_time > starting_time", self.sql)
        self.assertIn("/ (sample_size - 1)", self.sql)
        self.assertRegex(self.sql, r"else null\s+end as average_block_time_seconds")

    def test_query_does_not_use_wall_clock_or_rpc_timestamps(self):
        bounded_sample = self.sql.split("from ( select height, time_utc from blocks", 1)[1].split(") bounded_blocks", 1)[0]
        self.assertNotIn("now()", self.sql)
        self.assertNotIn("current_timestamp", self.sql)
        self.assertNotIn("rpc", bounded_sample)

    def test_schema_mapping_and_endpoint_contract(self):
        fields = NetworkResponse.model_fields
        self.assertIn("average_block_time_seconds", fields)
        self.assertIn("average_block_time_sample_size", fields)
        source = inspect.getsource(app._network_response_from_row)
        self.assertIn('float(row["average_block_time_seconds"])', source)
        self.assertIn('int(row["average_block_time_sample_size"])', source)
        paths = {route.path for route in app.app.routes}
        self.assertIn("/api/network", paths)
        self.assertNotIn("/api/average-block-time", paths)


if __name__ == "__main__":
    unittest.main()
