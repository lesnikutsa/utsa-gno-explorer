import unittest

from api.database import ApiDatabase, VALIDATOR_SEARCH_SQL


class Cursor:
    def __init__(self):
        self.sql = None
        self.parameters = None

    def __enter__(self): return self
    def __exit__(self, *_): pass
    def execute(self, sql, parameters):
        self.sql, self.parameters = sql, parameters
    def fetchall(self): return []


class Connection:
    def __init__(self, cursor): self.value = cursor
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def cursor(self): return self.value


class Pool:
    def __init__(self, cursor): self.value = cursor
    def connection(self, timeout): return Connection(self.value)


class ValidatorSearchContractTests(unittest.TestCase):
    def test_query_contract_and_deterministic_ranking(self):
        self.assertIn("FROM validators validator", VALIDATOR_SEARCH_SQL)
        self.assertIn("profile.signing_address = validator.signing_address", VALIDATOR_SEARCH_SQL)
        self.assertIn("DISTINCT ON (validator.signing_address)", VALIDATOR_SEARCH_SQL)
        self.assertIn("WHEN lower(validator.signing_address) = lower(%s) THEN 0", VALIDATOR_SEARCH_SQL)
        self.assertIn("WHEN lower(profile.operator_address) = lower(%s) THEN 1", VALIDATOR_SEARCH_SQL)
        self.assertIn("WHEN lower(profile.moniker) = lower(%s) THEN 2", VALIDATOR_SEARCH_SQL)
        self.assertIn("THEN 3", VALIDATOR_SEARCH_SQL)
        self.assertIn("lower(moniker) NULLS LAST", VALIDATOR_SEARCH_SQL)
        self.assertIn("address\nLIMIT %s", VALIDATOR_SEARCH_SQL)
        self.assertGreaterEqual(VALIDATOR_SEARCH_SQL.count("ESCAPE"), 4)

    def test_method_uses_parameters_and_escapes_like_metacharacters(self):
        cursor = Cursor()
        database = ApiDatabase()
        database.pool = Pool(cursor)
        self.assertEqual(database.fetch_validator_search(r" %_\\ ", 6), [])
        self.assertIs(cursor.sql, VALIDATOR_SEARCH_SQL)
        self.assertEqual(cursor.parameters[-1], 6)
        self.assertEqual(cursor.parameters[0], r"%_\\")
        self.assertIn(r"\%\_\\", cursor.parameters[3])
        self.assertEqual(len(cursor.parameters), 8)


if __name__ == "__main__":
    unittest.main()
