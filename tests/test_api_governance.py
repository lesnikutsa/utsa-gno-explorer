from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

from fastapi.testclient import TestClient

from api.config import ApiConfig
import api.app as module

REALM = "gno.land/r/gov/dao"
NOW = datetime(2026, 7, 27, 20, 25, 20, tzinfo=timezone.utc)
ADDRESS = "g1" + "a" * 38


def proposal(proposal_id):
    return {"proposal_id": proposal_id, "title": f"Proposal {proposal_id}", "author_display": ADDRESS,
            "author_address": ADDRESS, "status": "ACCEPTED", "eligible_tiers": ["T1"],
            "yes_percent": Decimal("100.0000"), "no_percent": Decimal("0"),
            "abstain_percent": None, "voter_count": 1}


def source(items):
    ids = [item["proposal_id"] for item in items]
    return {"current_chain_id": "topaz-1", "chain_id": "topaz-1", "realm_path": REALM,
            "source_height": 243022, "page_count": 5, "proposal_count": len(items),
            "first_proposal_id": min(ids) if ids else None, "latest_proposal_id": max(ids) if ids else None,
            "last_success_at": NOW, "actual_proposal_count": len(items),
            "actual_first_proposal_id": min(ids) if ids else None,
            "actual_latest_proposal_id": max(ids) if ids else None,
            "active_count": 0, "accepted_count": len(items), "rejected_count": 0, "unknown_count": 0}


class FakeDatabase:
    def __init__(self):
        self.items = [proposal(i) for i in range(20, -1, -1)]
        self.fail = False
    def open(self, config): pass
    def close(self): pass
    def fetch_governance_proposals(self, *, realm_path, limit, before_proposal_id):
        if self.fail: raise RuntimeError("postgresql://secret")
        rows = [p for p in self.items if before_proposal_id is None or p["proposal_id"] < before_proposal_id]
        return {"source": source(self.items), "items": deepcopy(rows[:limit + 1])}
    def fetch_governance_proposal_detail(self, *, realm_path, proposal_id):
        item = next((deepcopy(p) for p in self.items if p["proposal_id"] == proposal_id), None)
        result = {"source": source(self.items), "proposal": item, "votes": []}
        if item is not None:
            item.update(description="Description", executor_text=None, executor_creation_realm=None,
                        rejection_reason=None, detail_parse_status="parsed", votes_parse_status="parsed",
                        first_observed_height=243022, last_observed_height=243022,
                        first_observed_at=NOW, last_observed_at=NOW)
            result["votes"] = [{"voter_display": ADDRESS, "voter_address": ADDRESS, "option": "YES",
                "tier": "T1", "voting_power": "999999999999999999999999999999999999",
                "first_observed_height": 243022, "last_observed_height": 243022,
                "first_observed_at": NOW, "last_observed_at": NOW}]
        return result


def client(fake):
    stack = patch.object(module, "database", fake)
    config = patch.object(module, "load_config", return_value=ApiConfig(database_url="postgresql://secret"))
    stack.start(); config.start()
    test_client = TestClient(module.app)
    test_client.__enter__()
    test_client._patches = (stack, config)
    return test_client


def close(c):
    c.__exit__(None, None, None)
    for p in c._patches: p.stop()


def test_list_cursor_limits_zero_and_public_boundary():
    fake = FakeDatabase(); c = client(fake)
    try:
        first = c.get("/api/governance/proposals?limit=20")
        assert first.status_code == 200
        body = first.json()
        assert [x["proposal_id"] for x in body["items"]] == list(range(20, 0, -1))
        assert body["pagination"] == {"limit": 20, "next_before_proposal_id": 1}
        assert body["source"]["proposal_count"] == 21 and body["source"]["latest_proposal_id"] == 20
        assert isinstance(body["items"][0]["yes_percent"], float)
        assert not ({"raw_detail_render", "parse_warnings", "voter_key", "updated_at"} & set(body["items"][0]))
        second = c.get("/api/governance/proposals?limit=20&before_proposal_id=1").json()
        assert [x["proposal_id"] for x in second["items"]] == [0]
        assert c.get("/api/governance/proposals?before_proposal_id=0").json()["items"] == []
        for value in (1, 100): assert c.get(f"/api/governance/proposals?limit={value}").status_code == 200
        for value in (0, 101): assert c.get(f"/api/governance/proposals?limit={value}").status_code == 422
    finally: close(c)


def test_detail_zero_votes_and_safe_errors():
    fake = FakeDatabase(); c = client(fake)
    try:
        for proposal_id in (0, 20):
            response = c.get(f"/api/governance/proposals/{proposal_id}")
            assert response.status_code == 200
            assert response.json()["proposal"]["votes"][0]["voting_power"].startswith("999")
            assert "voter_key" not in response.text
        assert c.get("/api/governance/proposals/999").status_code == 404
        assert c.get("/api/governance/proposals/-1").status_code == 422
        fake.fail = True
        response = c.get("/api/governance/proposals")
        assert response.status_code == 503 and "postgresql://secret" not in response.text
    finally: close(c)


def test_inconsistent_state_and_vote_contract_are_rejected():
    fake = FakeDatabase()
    original = fake.fetch_governance_proposals
    fake.fetch_governance_proposals = lambda **kw: {**original(**kw), "source": {**source(fake.items), "accepted_count": 20}}
    c = client(fake)
    try: assert c.get("/api/governance/proposals").status_code == 503
    finally: close(c)
    fake = FakeDatabase(); original_detail = fake.fetch_governance_proposal_detail
    def malformed(**kw):
        value = original_detail(**kw); value["votes"] = []; value["proposal"]["voter_count"] = 0; return value
    fake.fetch_governance_proposal_detail = malformed
    c = client(fake)
    try: assert c.get("/api/governance/proposals/20").status_code == 503
    finally: close(c)
