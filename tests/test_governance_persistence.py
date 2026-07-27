from dataclasses import replace
import pytest
from governance.gno import GovernanceDiscovery, GovernanceProposalDetail, GovernanceSource, GovernanceVote
from indexer.governance_persistence import (GovernanceChainIdentityError, GovernancePersistenceError,
    IncompleteGovernanceSnapshot, normalize_discovery, voter_key)

def snapshot(**changes):
    vote=GovernanceVote("Alice",None,"YES","CORE","10")
    proposal=GovernanceProposalDetail(0,"Clean title",None,None,"ACTIVE",("CORE",),"body",None,None,None,50.0,20.0,30.0,"parsed","parsed",(vote,),())
    value=GovernanceDiscovery(GovernanceSource("topaz-1","redacted",10,"gno.land/r/gov/dao"),True,1,(proposal,),(),{"proposal/0":"detail\n","proposal/0/votes":"votes\n"})
    return replace(value,**changes)

def test_normalizes_proposal_zero_votes_and_exact_raw():
    rows=normalize_discovery(snapshot(),"topaz-1")
    assert rows[0][0].proposal_id == 0
    assert rows[0][1:3] == ("detail\n","votes\n")
    assert rows[0][3][0][0] == "display:alice"

def test_incomplete_and_cross_chain_rejected():
    with pytest.raises(IncompleteGovernanceSnapshot): normalize_discovery(snapshot(complete=False),"topaz-1")
    with pytest.raises(GovernanceChainIdentityError): normalize_discovery(snapshot(),"other")

@pytest.mark.parametrize("power",["-1","1.2","1e3",""])
def test_invalid_voting_power_rejected(power):
    p=snapshot().proposals[0]; bad=replace(p,votes=(replace(p.votes[0],voting_power=power),))
    with pytest.raises(GovernancePersistenceError): normalize_discovery(replace(snapshot(),proposals=(bad,)),"topaz-1")

def test_voter_key_is_deterministic():
    assert voter_key(" A   User ",None)=="display:a user"
    assert voter_key("ignored","g1"+"a"*38)=="address:g1"+"a"*38
