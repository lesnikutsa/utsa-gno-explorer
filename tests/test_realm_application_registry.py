import unittest

from api.realm_application_registry import CURATED_NAMESPACE_KEYS, REALM_APPLICATION_REGISTRY
from indexer.realm_catalog import namespace_key


class RealmApplicationRegistryTests(unittest.TestCase):
    def test_registry_is_exact_and_valid(self):
        self.assertEqual(CURATED_NAMESPACE_KEYS, ("gnoswap",))
        self.assertEqual(set(REALM_APPLICATION_REGISTRY), {"gnoswap"})
        metadata = REALM_APPLICATION_REGISTRY["gnoswap"]
        self.assertEqual((metadata["display_name"], metadata["category"]), ("GnoSwap", "DeFi"))
        self.assertIsNone(metadata["description"])
        self.assertIsNone(metadata["website"])
        self.assertEqual(metadata["metadata_source"], "curated_registry")
        self.assertEqual(namespace_key("gno.land/r/gnoswap"), "gnoswap")
        self.assertNotIn("unknown", REALM_APPLICATION_REGISTRY)

    def test_registry_and_entries_are_immutable(self):
        with self.assertRaises(TypeError):
            REALM_APPLICATION_REGISTRY["unknown"] = {}  # type: ignore[index]
        with self.assertRaises(TypeError):
            REALM_APPLICATION_REGISTRY["gnoswap"]["display_name"] = "Changed"  # type: ignore[index]
