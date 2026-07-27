from dataclasses import replace
import math
import random
import pytest
from governance.gno import GovernanceDiscovery, GovernanceProposalDetail, GovernanceSource, GovernanceVote
from indexer.governance_persistence import (GovernanceChainIdentityError, GovernancePersistenceError,
    IncompleteGovernanceSnapshot, normalize_discovery, voter_key, _content)


def proposal(proposal_id=0, *, votes=None, votes_status="parsed", **changes):
    votes = (GovernanceVote("Alice", None, "YES", "CORE", "10"),) if votes is None else votes
    value = GovernanceProposalDetail(proposal_id, f"Clean title {proposal_id}", None, None, "ACTIVE", ("CORE",), "body", None, None, None, 50.0, 20.0, 30.0, "parsed", votes_status, tuple(votes), ())
    return replace(value, **changes)


def snapshot(proposals=None, **changes):
    proposals = (proposal(),) if proposals is None else tuple(proposals)
    raw = {}
    for item in proposals:
        raw[f"proposal/{item.proposal_id}"] = f"detail {item.proposal_id}\n"
        raw[f"proposal/{item.proposal_id}/votes"] = f"votes {item.proposal_id}\n"
    value = GovernanceDiscovery(GovernanceSource("topaz-1", "redacted", 10, "gno.land/r/gov/dao"), True, 1, proposals, (), raw)
    return replace(value, **changes)


def test_normalizes_proposal_zero_votes_and_exact_raw():
    rows = normalize_discovery(snapshot(), "topaz-1")
    assert rows[0].proposal.proposal_id == 0
    assert (rows[0].raw_detail, rows[0].raw_votes) == ("detail 0\n", "votes 0\n")
    assert rows[0].votes[0][0] == "display:alice"


def test_canonicalizes_descending_shuffled_proposals_and_votes():
    items = [proposal(i, votes=(GovernanceVote("Zed", None, "NO", "CORE", "2"), GovernanceVote("Alice", None, "YES", "CORE", "1"))) for i in range(20, -1, -1)]
    descending = normalize_discovery(snapshot(items), "topaz-1")
    random.Random(7).shuffle(items)
    shuffled = normalize_discovery(snapshot(items), "topaz-1")
    assert [row.proposal.proposal_id for row in descending] == list(range(21))
    assert _content(descending) == _content(shuffled)
    assert [vote[0] for vote in descending[0].votes] == ["display:alice", "display:zed"]


def test_complete_empty_full_discovery_is_valid():
    assert normalize_discovery(snapshot((), page_count=1), "topaz-1") == ()
    with pytest.raises(GovernancePersistenceError):
        normalize_discovery(snapshot((), page_count=0), "topaz-1")


def test_incomplete_cross_chain_and_unparsed_rejected():
    with pytest.raises(IncompleteGovernanceSnapshot): normalize_discovery(snapshot(complete=False), "topaz-1")
    with pytest.raises(GovernanceChainIdentityError): normalize_discovery(snapshot(), "other")
    with pytest.raises(IncompleteGovernanceSnapshot): normalize_discovery(snapshot((proposal(votes=(), votes_status="unparsed"),)), "topaz-1")


@pytest.mark.parametrize("power", ["-1", "1.2", "1e3", "", "1" * 79])
def test_invalid_voting_power_rejected(power):
    bad = proposal(votes=(GovernanceVote("Alice", None, "YES", "CORE", power),))
    with pytest.raises(GovernancePersistenceError): normalize_discovery(snapshot((bad,)), "topaz-1")


@pytest.mark.parametrize("value", [math.nan, math.inf, -1, 101, "10"])
def test_invalid_percentage_rejected(value):
    with pytest.raises(GovernancePersistenceError): normalize_discovery(snapshot((proposal(yes_percent=value),)), "topaz-1")


@pytest.mark.parametrize("field,value", [
    ("title", ""), ("author_display", "x" * 1001), ("author_address", "g1bad"),
    ("eligible_tiers", ("",)), ("description", "x" * 100001),
    ("executor_creation_realm", "x" * 1001), ("rejection_reason", "x" * 10001),
    ("parse_warnings", (object(),)),
])
def test_invalid_proposal_fields_rejected(field, value):
    with pytest.raises(GovernancePersistenceError): normalize_discovery(snapshot((replace(proposal(), **{field: value}),)), "topaz-1")


def test_confirmed_empty_votes_are_valid():
    rows = normalize_discovery(snapshot((proposal(votes=(), votes_status="empty"),)), "topaz-1")
    assert rows[0].votes == ()


def test_voter_key_is_deterministic():
    assert voter_key(" A   User ", None) == "display:a user"
    assert voter_key("ignored", "g1" + "a" * 38) == "address:g1" + "a" * 38
