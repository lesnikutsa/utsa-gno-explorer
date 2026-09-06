from types import SimpleNamespace
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.cosmos.account_routes import router
from api.cosmos.governance import load_governance_page


def proposal(proposal_id, status, title, message_type, *, yes="10", no="0", veto=None, abstain="0"):
    tally = {"yes_count": yes, "no_count": no, "abstain_count": abstain}
    if veto is not None:
        tally["no_with_veto_count"] = veto
    return {
        "id": str(proposal_id),
        "title": title,
        "summary": "Summary",
        "messages": [{"@type": message_type}],
        "status": status,
        "proposer": "atone1proposer",
        "submit_time": "2026-06-01T00:00:00Z",
        "voting_start_time": "2026-06-02T00:00:00Z",
        "voting_end_time": "2026-06-09T00:00:00Z",
        "final_tally_result": tally,
    }


class FakeService:
    def __init__(self, rows):
        self.rows = rows
        self.definition = SimpleNamespace(transport=SimpleNamespace(network_id="atomone-mainnet"))
        self.calls = []

    async def _paginate(self, name, path, field):
        self.calls.append((name, path, field))
        return list(self.rows)


class CosmosGovernanceTests(unittest.IsolatedAsyncioTestCase):
    async def test_loads_all_paginated_proposals_sorts_and_counts_statuses(self):
        service = FakeService([
            proposal(19, "PROPOSAL_STATUS_REJECTED", "Params", "/atomone.gov.v1.MsgUpdateParams", yes="4", no="6"),
            proposal(21, "PROPOSAL_STATUS_PASSED", "AtomOne v4 Upgrade", "/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade", yes="25", abstain="1"),
            proposal(20, "PROPOSAL_STATUS_VOTING_PERIOD", "Constitution", "/atomone.gov.v1.MsgProposeConstitutionAmendment", yes="5", no="2", veto="1", abstain="2"),
        ])

        result = await load_governance_page(service)

        self.assertEqual([item.proposal_id for item in result.proposals], [21, 20, 19])
        self.assertEqual(result.summary.total, 3)
        self.assertEqual(result.summary.passed, 1)
        self.assertEqual(result.summary.voting, 1)
        self.assertEqual(result.summary.rejected, 1)
        self.assertEqual(result.proposals[0].proposal_type, "Upgrade")
        self.assertEqual(result.proposals[1].proposal_type, "Constitution")
        self.assertEqual(result.proposals[2].proposal_type, "Params")
        self.assertEqual(result.proposals[0].tally.no_with_veto, "0")
        self.assertEqual(service.calls, [("governance_proposals", "/cosmos/gov/v1/proposals?pagination.reverse=true", "proposals")])

    async def test_unknown_message_and_status_degrade_without_losing_proposal(self):
        row = proposal(1, "PROPOSAL_STATUS_UNSPECIFIED", "Custom action", "/custom.module.v1.MsgDoSomething")
        service = FakeService([row])
        result = await load_governance_page(service)
        self.assertEqual(result.proposals[0].status, "unknown")
        self.assertEqual(result.proposals[0].proposal_type, "Do Something")
        self.assertEqual(result.summary.unknown, 1)


class CosmosGovernanceRouteTests(unittest.TestCase):
    def test_governance_route_uses_registered_cosmos_service(self):
        service = FakeService([
            proposal(21, "PROPOSAL_STATUS_PASSED", "AtomOne v4 Upgrade", "/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade")
        ])
        app = FastAPI()
        app.include_router(router)
        app.state.cosmos_services = {"atomone-mainnet": service}
        with TestClient(app) as client:
            response = client.get("/api/networks/atomone-mainnet/governance")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["summary"]["total"], 1)
        self.assertEqual(body["proposals"][0]["proposal_id"], 21)
