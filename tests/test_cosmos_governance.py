from types import SimpleNamespace
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.cosmos.account_routes import router
from api.cosmos.governance import load_governance_detail, load_governance_page, load_governance_votes


def proposal(proposal_id, status, title, message_type, *, yes="10", no="0", veto=None, abstain="0"):
    tally = {"yes_count": yes, "no_count": no, "abstain_count": abstain}
    if veto is not None:
        tally["no_with_veto_count"] = veto
    return {
        "id": str(proposal_id),
        "title": title,
        "summary": "Summary\nwith a second line.",
        "metadata": "ipfs://proposal-metadata",
        "messages": [{"@type": message_type, "authority": "atone1authority"}],
        "status": status,
        "proposer": "atone1proposer",
        "submit_time": "2026-06-01T00:00:00Z",
        "deposit_end_time": "2026-06-02T00:00:00Z",
        "voting_start_time": "2026-06-02T00:00:00Z",
        "voting_end_time": "2026-06-09T00:00:00Z",
        "total_deposit": [{"denom": "uatone", "amount": "1000000"}],
        "final_tally_result": tally,
    }


class FakeService:
    def __init__(self, rows, *, votes=None, live_tally=None):
        self.rows = rows
        self.votes = list(votes or [])
        self.live_tally = live_tally
        self.definition = SimpleNamespace(transport=SimpleNamespace(network_id="atomone-mainnet"))
        self.calls = []
        self.rest_calls = []

    async def _paginate(self, name, path, field):
        self.calls.append((name, path, field))
        return list(self.votes if field == "votes" else self.rows)

    async def _rest(self, name, path):
        self.rest_calls.append((name, path))
        if path.endswith("/tally"):
            return {"tally": self.live_tally or self.rows[0]["final_tally_result"]}
        if "/cosmos/gov/v1/proposals/" in path:
            return {"proposal": self.rows[0]}
        raise RuntimeError("unexpected REST path")


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

    async def test_detail_preserves_description_deposit_messages_and_uses_live_tally(self):
        row = proposal(21, "PROPOSAL_STATUS_PASSED", "AtomOne v4 Upgrade", "/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade")
        service = FakeService([row], live_tally={"yes_count": "30", "no_count": "2", "no_with_veto_count": "1", "abstain_count": "3"})

        result = await load_governance_detail(service, 21)

        self.assertEqual(result.proposal.proposal_id, 21)
        self.assertEqual(result.proposal.tally.yes, "30")
        self.assertEqual(result.proposal.tally.no_with_veto, "1")
        self.assertEqual(result.summary, "Summary\nwith a second line.")
        self.assertEqual(result.metadata, "ipfs://proposal-metadata")
        self.assertEqual(result.total_deposit[0].denom, "uatone")
        self.assertEqual(result.total_deposit[0].amount, "1000000")
        self.assertEqual(result.messages[0].message_type, "/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade")
        self.assertIn('"authority": "atone1authority"', result.messages[0].content)
        self.assertEqual(service.rest_calls, [
            ("governance_proposal_21", "/cosmos/gov/v1/proposals/21"),
            ("governance_tally_21", "/cosmos/gov/v1/proposals/21/tally"),
        ])

    async def test_votes_support_weighted_and_legacy_vote_shapes(self):
        row = proposal(21, "PROPOSAL_STATUS_PASSED", "AtomOne v4 Upgrade", "/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade")
        service = FakeService([row], votes=[
            {"proposal_id": "21", "voter": "atone1alice", "options": [
                {"option": "VOTE_OPTION_YES", "weight": "0.750000000000000000"},
                {"option": "VOTE_OPTION_ABSTAIN", "weight": "0.250000000000000000"},
            ]},
            {"proposal_id": "21", "voter": "atone1bob", "option": "VOTE_OPTION_NO"},
        ])

        result = await load_governance_votes(service, 21)

        self.assertEqual(result.total, 2)
        self.assertEqual(result.votes[0].options[0].option, "yes")
        self.assertEqual(result.votes[0].options[1].option, "abstain")
        self.assertEqual(result.votes[1].options[0].option, "no")
        self.assertEqual(result.votes[1].options[0].weight, "1")
        self.assertEqual(service.calls, [("governance_votes_21", "/cosmos/gov/v1/proposals/21/votes", "votes")])


class CosmosGovernanceRouteTests(unittest.TestCase):
    def app(self, service):
        app = FastAPI()
        app.include_router(router)
        app.state.cosmos_services = {"atomone-mainnet": service}
        return app

    def test_governance_route_uses_registered_cosmos_service(self):
        service = FakeService([
            proposal(21, "PROPOSAL_STATUS_PASSED", "AtomOne v4 Upgrade", "/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade")
        ])
        with TestClient(self.app(service)) as client:
            response = client.get("/api/networks/atomone-mainnet/governance")
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["summary"]["total"], 1)
        self.assertEqual(body["proposals"][0]["proposal_id"], 21)

    def test_governance_detail_and_votes_routes_are_request_driven(self):
        row = proposal(21, "PROPOSAL_STATUS_PASSED", "AtomOne v4 Upgrade", "/cosmos.upgrade.v1beta1.MsgSoftwareUpgrade")
        service = FakeService([row], votes=[{"proposal_id": "21", "voter": "atone1alice", "option": "VOTE_OPTION_YES"}])
        with TestClient(self.app(service)) as client:
            detail = client.get("/api/networks/atomone-mainnet/governance/21")
            votes = client.get("/api/networks/atomone-mainnet/governance/21/votes")
        self.assertEqual(detail.status_code, 200)
        self.assertEqual(detail.json()["proposal"]["title"], "AtomOne v4 Upgrade")
        self.assertEqual(votes.status_code, 200)
        self.assertEqual(votes.json()["votes"][0]["voter"], "atone1alice")
