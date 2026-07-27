import base64
import unittest

from governance.gno import GovernanceSource, discover_governance


class FakeClient:
    def __init__(self, renders): self.renders, self.calls = renders, []
    def abci_query(self, path, data, height=None):
        self.calls.append((path, data, height)); return self.renders[data.split(":", 1)[1]]


class DiscoveryTests(unittest.TestCase):
    def test_pages_cycle_deduplicates_and_sorts(self):
        renders = {
            "": "### Prop #1 - One\nStatus: ACTIVE\n[Next](?page=2)",
            "?page=2": "### Prop #2 - Two\nStatus: ACCEPTED\n[Back](?page=1)",
            "1": "## Prop #1 - One\n\nDesc\n---\nStatus: ACTIVE", "1/votes": "No votes",
            "2": "## Prop #2 - Two\n\nDesc\n---\nStatus: ACCEPTED", "2/votes": "unknown",
        }
        result = discover_governance(FakeClient(renders), GovernanceSource("topaz-1", "rpc", 10, "gno.land/r/gov/dao"))
        self.assertEqual([p.proposal_id for p in result.proposals], [2, 1])
        self.assertEqual(result.page_count, 2)
        self.assertTrue(result.complete)
        self.assertEqual(result.to_dict()["status_counts"]["accepted"], 1)


if __name__ == "__main__": unittest.main()
