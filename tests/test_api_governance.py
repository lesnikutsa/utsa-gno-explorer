from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch

import pytest
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


@contextmanager
def make_client(fake):
    with patch.object(module, "database", fake), patch.object(
        module, "load_config", return_value=ApiConfig(database_url="postgresql://secret")
    ):
        with TestClient(module.app) as test_client:
            yield test_client

def test_list_cursor_limits_zero_and_public_boundary():
    fake = FakeDatabase()
    with make_client(fake) as c:
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


def test_detail_zero_votes_and_safe_errors():
    fake = FakeDatabase()
    with make_client(fake) as c:
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


def test_detail_freshness_is_proposal_specific_while_list_is_global():
    fake = FakeDatabase()
    first_time = NOW.replace(hour=17)
    old_time = NOW.replace(hour=18)
    original = fake.fetch_governance_proposal_detail
    def older_terminal(**kwargs):
        result = original(**kwargs)
        result["proposal"].update(
            first_observed_height=239000, last_observed_height=240000,
            first_observed_at=first_time, last_observed_at=old_time,
        )
        result["votes"][0].update(
            first_observed_height=239000, last_observed_height=240000,
            first_observed_at=first_time, last_observed_at=old_time,
        )
        return result
    fake.fetch_governance_proposal_detail = older_terminal
    with make_client(fake) as client:
        assert client.get("/api/governance/proposals").json()["source"]["source_height"] == 243022
        detail_response = client.get("/api/governance/proposals/0")
        assert detail_response.status_code == 200
        detail_source = detail_response.json()["source"]
        assert detail_source["source_height"] == 240000
        assert detail_source["last_success_at"] == "2026-07-27T18:25:20Z"


def test_active_targeted_proposal_exposes_recent_observation():
    fake = FakeDatabase(); fake.items[0]["status"] = "ACTIVE"
    original = fake.fetch_governance_proposal_detail
    def active(**kwargs):
        result = original(**kwargs); result["proposal"]["status"] = "ACTIVE"; return result
    fake.fetch_governance_proposal_detail = active
    with make_client(fake) as client:
        body = client.get("/api/governance/proposals/20").json()
        assert body["source"]["source_height"] == 243022
        assert body["source"]["last_success_at"] == "2026-07-27T20:25:20Z"


def test_inconsistent_state_and_vote_contract_are_rejected():
    fake = FakeDatabase()
    original = fake.fetch_governance_proposals
    fake.fetch_governance_proposals = lambda **kw: {**original(**kw), "source": {**source(fake.items), "accepted_count": 20}}
    with make_client(fake) as c:
        assert c.get("/api/governance/proposals").status_code == 503
    fake = FakeDatabase(); original_detail = fake.fetch_governance_proposal_detail
    def malformed(**kw):
        value = original_detail(**kw); value["votes"] = []; value["proposal"]["voter_count"] = 0; return value
    fake.fetch_governance_proposal_detail = malformed
    with make_client(fake) as c:
        assert c.get("/api/governance/proposals/20").status_code == 503


def test_public_governance_sql_contracts():
    from api.database import (GOVERNANCE_SOURCE_SQL, GOVERNANCE_PROPOSALS_SQL,
        GOVERNANCE_PROPOSAL_DETAIL_SQL, GOVERNANCE_VOTES_SQL)
    source_sql = " ".join(GOVERNANCE_SOURCE_SQL.lower().split())
    list_sql = " ".join(GOVERNANCE_PROPOSALS_SQL.lower().split())
    detail_sql = " ".join(GOVERNANCE_PROPOSAL_DETAIL_SQL.lower().split())
    votes_sql = " ".join(GOVERNANCE_VOTES_SQL.lower().split())
    assert "from indexer_state s" in source_sql and "sync.chain_id = s.chain_id" in source_sql
    assert "s.state_key = %s" in source_sql and "sync.realm_path = %s" in source_sql
    assert "proposal.proposal_id < %s::bigint" in list_sql
    assert "order by proposal.proposal_id desc" in list_sql and "limit %s" in list_sql
    assert "limit 1001" in list_sql and "select *" not in list_sql
    assert "proposal.chain_id = %s" in detail_sql and "proposal.realm_path = %s" in detail_sql
    assert "proposal.proposal_id = %s" in detail_sql
    assert "voting_power::text" in votes_sql and "order by tier asc, voter_key asc" in votes_sql
    assert "limit 1001" in votes_sql
    assert "voter_key" not in votes_sql.split("from governance_votes", 1)[0]
    public_sql = " ".join((source_sql, list_sql, detail_sql, votes_sql))
    for private in ("raw_detail_render", "raw_votes_render", "parse_warnings", "inserted_at", "updated_at", "rpc_url"):
        assert private not in public_sql


def test_governance_database_uses_repeatable_read_read_only_transaction():
    from contextlib import contextmanager
    from api.database import ApiDatabase, GOVERNANCE_TRANSACTION_SQL

    source_row = source([proposal(0)])
    class Cursor:
        def __init__(self): self.statements = []; self.result = None
        def execute(self, sql, parameters=None):
            self.statements.append(sql)
            if "FROM indexer_state" in sql: self.result = source_row
            elif "FROM governance_proposals proposal" in sql: self.result = None
        def fetchone(self): return self.result
        def fetchall(self): return []
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Connection:
        def __init__(self): self.cursor_value = Cursor(); self.transaction_count = 0
        @contextmanager
        def transaction(self):
            self.transaction_count += 1
            yield
        def cursor(self): return self.cursor_value
    class Pool:
        def __init__(self): self.connection_value = Connection()
        @contextmanager
        def connection(self, timeout):
            assert timeout == 2.0
            yield self.connection_value
    database = ApiDatabase(); database.pool = Pool()
    database.fetch_governance_proposals(realm_path=REALM, limit=20, before_proposal_id=None)
    connection = database.pool.connection_value
    assert connection.transaction_count == 1
    assert connection.cursor_value.statements[0] == GOVERNANCE_TRANSACTION_SQL
    connection.cursor_value.statements.clear()
    database.fetch_governance_proposal_detail(realm_path=REALM, proposal_id=0)
    assert connection.transaction_count == 2
    assert connection.cursor_value.statements[0] == GOVERNANCE_TRANSACTION_SQL


def test_missing_snapshot_returns_404_for_both_endpoints():
    fake = FakeDatabase()
    fake.fetch_governance_proposals = lambda **kwargs: None
    fake.fetch_governance_proposal_detail = lambda **kwargs: None
    with make_client(fake) as client:
        assert client.get("/api/governance/proposals").status_code == 404
        assert client.get("/api/governance/proposals/0").status_code == 404


@pytest.mark.parametrize("source_field,bad_value", [
    ("source_height", "243022"), ("source_height", True), ("page_count", "5"),
    ("proposal_count", "21"), ("actual_proposal_count", True),
])
def test_source_numeric_types_are_strict(source_field, bad_value):
    fake = FakeDatabase(); original = fake.fetch_governance_proposals
    def malformed(**kwargs):
        result = original(**kwargs); result["source"][source_field] = bad_value; return result
    fake.fetch_governance_proposals = malformed
    with make_client(fake) as client:
        assert client.get("/api/governance/proposals").status_code == 503


@pytest.mark.parametrize("tiers", ["T1", ["T1", "T1"], [" T1"], [""], ["T1"] * 101])
def test_malformed_eligible_tiers_return_503(tiers):
    fake = FakeDatabase(); fake.items[0]["eligible_tiers"] = tiers
    with make_client(fake) as client:
        assert client.get("/api/governance/proposals").status_code == 503


@pytest.mark.parametrize("value", [Decimal("101"), Decimal("NaN"), "50"])
def test_invalid_percentages_return_503(value):
    fake = FakeDatabase(); fake.items[0]["yes_percent"] = value
    with make_client(fake) as client:
        assert client.get("/api/governance/proposals").status_code == 503


@pytest.mark.parametrize("ids,cursor", [([20, 20], None), ([19, 20], None), ([20], 20)])
def test_invalid_list_page_identity_returns_503(ids, cursor):
    fake = FakeDatabase(); original = fake.fetch_governance_proposals
    def malformed(**kwargs):
        result = original(**kwargs); result["items"] = [proposal(value) for value in ids]; return result
    fake.fetch_governance_proposals = malformed
    query = "/api/governance/proposals" + (f"?before_proposal_id={cursor}" if cursor is not None else "")
    with make_client(fake) as client:
        assert client.get(query).status_code == 503


def detail_mutation_response(mutate):
    fake = FakeDatabase(); original = fake.fetch_governance_proposal_detail
    def malformed(**kwargs):
        result = original(**kwargs); mutate(result); return result
    fake.fetch_governance_proposal_detail = malformed
    with make_client(fake) as client:
        return client.get("/api/governance/proposals/20")


def test_detail_returned_proposal_identity_is_checked():
    assert detail_mutation_response(lambda result: result["proposal"].update(proposal_id=19)).status_code == 503


@pytest.mark.parametrize("status,remove_votes,expected", [
    ("parsed", True, 503), ("empty", True, 200), ("empty", False, 503), ("unparsed", False, 503),
])
def test_detail_vote_parse_contract(status, remove_votes, expected):
    def mutate(result):
        result["proposal"]["votes_parse_status"] = status
        if remove_votes:
            result["votes"] = []; result["proposal"]["voter_count"] = 0
    assert detail_mutation_response(mutate).status_code == expected


@pytest.mark.parametrize("field,value", [
    ("voting_power", "-1"), ("voting_power", "1.0"), ("option", "MAYBE"),
    ("tier", " T1"), ("last_observed_height", 243023),
])
def test_invalid_vote_fields_are_rejected(field, value):
    def mutate(result): result["votes"][0][field] = value
    assert detail_mutation_response(mutate).status_code == 503


def test_duplicate_canonical_display_voters_are_rejected():
    def mutate(result):
        first = result["votes"][0]
        first["voter_address"] = None; first["voter_display"] = " Alice  Smith "
        second = deepcopy(first); second["voter_display"] = "alice smith"
        result["votes"] = [first, second]; result["proposal"]["voter_count"] = 2
    assert detail_mutation_response(mutate).status_code == 503


def test_vote_count_and_timestamp_order_are_checked():
    assert detail_mutation_response(lambda result: result["proposal"].update(voter_count=2)).status_code == 503
    def reverse_time(result): result["votes"][0]["first_observed_at"] = NOW.replace(year=2027)
    assert detail_mutation_response(reverse_time).status_code == 503


def test_more_than_1000_votes_are_rejected():
    def mutate(result):
        result["votes"] = [deepcopy(result["votes"][0]) for _ in range(1001)]
        result["proposal"]["voter_count"] = 1001
    assert detail_mutation_response(mutate).status_code == 503
