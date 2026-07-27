"""Atomic PostgreSQL persistence for complete, fixed-height governance discoveries."""
from __future__ import annotations
import json, re
from dataclasses import dataclass
from decimal import Decimal
from governance.gno import (GovernanceDiscovery, MAX_GOVERNANCE_PAGES, MAX_GOVERNANCE_PROPOSALS,
    MAX_RENDER_BYTES, MAX_TEXT_CHARS, MAX_TOTAL_RAW_BYTES, proposal_raw_renders)

GOVERNANCE_ADVISORY_LOCK = -7046029254386353127
_STATUSES = {"ACTIVE", "ACCEPTED", "REJECTED", "UNKNOWN"}
_TRANSITIONS = {"ACTIVE": _STATUSES - {"UNKNOWN", "ACTIVE"}, "UNKNOWN": _STATUSES - {"UNKNOWN"}}
_ADDRESS = re.compile(r"^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$")
_POWER = re.compile(r"^[0-9]+$")

class GovernancePersistenceError(RuntimeError): pass
class GovernanceChainIdentityError(GovernancePersistenceError): pass
class IncompleteGovernanceSnapshot(GovernancePersistenceError): pass
class StaleGovernanceSnapshot(GovernancePersistenceError): pass
class GovernanceSnapshotConflict(GovernancePersistenceError): pass
class GovernanceStoredStateError(GovernancePersistenceError): pass

@dataclass(frozen=True)
class GovernancePersistenceResult:
    action: str; source_height: int; page_count: int; proposal_count: int; vote_count: int
    inserted_proposals: int = 0; updated_proposals: int = 0

def voter_key(display: str, address: str | None) -> str:
    return f"address:{address.lower()}" if address else f"display:{' '.join(display.split()).casefold()}"

def _fail(condition, message, cls=GovernancePersistenceError):
    if condition: raise cls(message)

def normalize_discovery(discovery: GovernanceDiscovery, configured_chain_id: str):
    _fail(not isinstance(discovery, GovernanceDiscovery), "a GovernanceDiscovery is required")
    source=discovery.source
    _fail(not discovery.complete, "only a complete full discovery may be persisted", IncompleteGovernanceSnapshot)
    _fail(not source.chain_id or len(source.chain_id)>128 or source.chain_id != configured_chain_id, "governance source chain does not match configured chain", GovernanceChainIdentityError)
    _fail(not source.realm_path or len(source.realm_path)>512 or source.observed_height < 1, "invalid governance source")
    _fail(not 0 <= discovery.page_count <= MAX_GOVERNANCE_PAGES or len(discovery.proposals)>MAX_GOVERNANCE_PROPOSALS, "governance snapshot exceeds bounds")
    _fail(bool(discovery.proposals) != bool(discovery.page_count), "page and proposal counts are inconsistent")
    ids=[p.proposal_id for p in discovery.proposals]; _fail(len(ids)!=len(set(ids)), "duplicate proposal ID")
    total=sum(len(v.encode()) for v in discovery.raw_renders.values()); _fail(total>MAX_TOTAL_RAW_BYTES, "raw renders exceed total limit")
    rows=[]
    for p in discovery.proposals:
        detail_raw,votes_raw=proposal_raw_renders(discovery,p.proposal_id)
        _fail(detail_raw is None or votes_raw is None, f"proposal {p.proposal_id} raw renders are missing")
        _fail(any(len(x.encode())>MAX_RENDER_BYTES for x in (detail_raw,votes_raw)), "raw render exceeds limit")
        _fail(p.proposal_id<0 or p.status not in _STATUSES or p.detail_parse_status not in {"parsed","partial"} or p.votes_parse_status not in {"parsed","empty","unparsed"}, "invalid proposal state")
        _fail(not 1<=len(p.title)<=1000 or len(p.description)>MAX_TEXT_CHARS, "proposal text exceeds bounds")
        keys=set(); votes=[]
        for v in p.votes:
            key=voter_key(v.voter_display,v.voter_address)
            _fail(key in keys, "duplicate voter key"); keys.add(key)
            _fail(not v.voter_display or len(v.voter_display)>1000 or (v.voter_address is not None and not _ADDRESS.fullmatch(v.voter_address)), "invalid voter identity")
            _fail(v.option not in {"YES","NO","ABSTAIN"} or not v.tier or len(v.tier)>64 or not _POWER.fullmatch(v.voting_power) or len(v.voting_power)>78, "invalid vote")
            votes.append((key,v.voter_display,v.voter_address,v.option,v.tier,Decimal(v.voting_power)))
        rows.append((p,detail_raw,votes_raw,tuple(votes)))
    return tuple(rows)

_PROPOSAL_COLUMNS="proposal_id,title,author_display,author_address,status,eligible_tiers,description,executor_text,executor_creation_realm,rejection_reason,yes_percent,no_percent,abstain_percent,detail_parse_status,votes_parse_status,parse_warnings,raw_detail_render,raw_votes_render,first_observed_height,last_observed_height,first_observed_at,last_observed_at"

def _load(cursor, chain, realm):
    cursor.execute("SELECT source_height,page_count,proposal_count,first_proposal_id,latest_proposal_id FROM governance_sync_state WHERE chain_id=%s AND realm_path=%s FOR UPDATE",(chain,realm)); state=cursor.fetchone()
    cursor.execute(f"SELECT {_PROPOSAL_COLUMNS} FROM governance_proposals WHERE chain_id=%s AND realm_path=%s ORDER BY proposal_id",(chain,realm)); proposals=cursor.fetchall()
    cursor.execute("SELECT proposal_id,voter_key,voter_display,voter_address,option,tier,voting_power,first_observed_height,last_observed_height,first_observed_at,last_observed_at FROM governance_votes WHERE chain_id=%s AND realm_path=%s ORDER BY proposal_id,voter_key",(chain,realm)); votes=cursor.fetchall()
    if state is None:
        _fail(bool(proposals or votes),"rows exist without governance sync state",GovernanceStoredStateError)
    else:
        ids=[int(r[0]) for r in proposals]
        _fail(state[2]!=len(ids) or state[3]!=(min(ids) if ids else None) or state[4]!=(max(ids) if ids else None),"stored governance counts are inconsistent",GovernanceStoredStateError)
        _fail(any(r[4] not in _STATUSES or r[18]<1 or r[19]<r[18] or r[19]>state[0] or (r[16] and len(r[16].encode())>MAX_RENDER_BYTES) or (r[17] and len(r[17].encode())>MAX_RENDER_BYTES) for r in proposals),"stored proposal is inconsistent",GovernanceStoredStateError)
    return state,proposals,votes

def _content(rows):
    proposals=[]; votes=[]
    for p,dr,vr,pvotes in rows:
        percentages = tuple(Decimal(str(value)) if value is not None else None for value in
                            (p.yes_percent, p.no_percent, p.abstain_percent))
        proposals.append((p.proposal_id,p.title,p.author_display,p.author_address,p.status,tuple(p.eligible_tiers),p.description,p.executor_text,p.executor_creation_realm,p.rejection_reason,*percentages,p.detail_parse_status,p.votes_parse_status,tuple(p.parse_warnings),dr,vr))
        votes.extend((p.proposal_id,)+v for v in pvotes)
    return proposals,votes

def _stored_content(proposals,votes):
    ps=[tuple(list(r[:5])+[tuple(r[5]),*r[6:15],tuple(r[15]),r[16],r[17]]) for r in proposals]
    vs=[tuple(r[:6])+(Decimal(r[6]),) for r in votes]
    return ps,vs

def persist_governance_snapshot_cursor(cursor, discovery, configured_chain_id):
    rows=normalize_discovery(discovery,configured_chain_id); chain=discovery.source.chain_id; realm=discovery.source.realm_path; height=discovery.source.observed_height
    cursor.execute("SELECT pg_advisory_xact_lock(%s)",(GOVERNANCE_ADVISORY_LOCK,))
    cursor.execute("SELECT chain_id FROM indexer_state WHERE state_key=%s",("default",)); identity=cursor.fetchone()
    _fail(identity is not None and identity[0]!=chain,"indexer state belongs to another chain",GovernanceChainIdentityError)
    state,stored,stored_votes=_load(cursor,chain,realm)
    incoming_content=_content(rows)
    if state and state[0]>height: raise StaleGovernanceSnapshot("governance snapshot is stale")
    if state and state[0]==height:
        same_meta=(state[1],state[2],state[3],state[4])==(discovery.page_count,len(rows),min((r[0].proposal_id for r in rows),default=None),max((r[0].proposal_id for r in rows),default=None))
        if same_meta and _stored_content(stored,stored_votes)==incoming_content:
            return GovernancePersistenceResult("unchanged",height,discovery.page_count,len(rows),len(incoming_content[1]))
        raise GovernanceSnapshotConflict("same-height governance snapshot differs")
    old={int(r[0]):r for r in stored}; incoming_ids={r[0].proposal_id for r in rows}
    _fail(not set(old).issubset(incoming_ids),"a stored proposal is missing from newer snapshot",GovernanceSnapshotConflict)
    for p,_,_,_ in rows:
        if p.proposal_id in old:
            previous=old[p.proposal_id][4]
            _fail(previous!=p.status and p.status not in _TRANSITIONS.get(previous,set()),"invalid governance status transition",GovernanceSnapshotConflict)
    for p,dr,vr,votes in rows:
        cursor.execute("""INSERT INTO governance_proposals(chain_id,realm_path,proposal_id,title,author_display,author_address,status,eligible_tiers,description,executor_text,executor_creation_realm,rejection_reason,yes_percent,no_percent,abstain_percent,detail_parse_status,votes_parse_status,parse_warnings,raw_detail_render,raw_votes_render,first_observed_height,last_observed_height) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s) ON CONFLICT(chain_id,realm_path,proposal_id) DO UPDATE SET title=EXCLUDED.title,author_display=EXCLUDED.author_display,author_address=EXCLUDED.author_address,status=EXCLUDED.status,eligible_tiers=EXCLUDED.eligible_tiers,description=EXCLUDED.description,executor_text=EXCLUDED.executor_text,executor_creation_realm=EXCLUDED.executor_creation_realm,rejection_reason=EXCLUDED.rejection_reason,yes_percent=EXCLUDED.yes_percent,no_percent=EXCLUDED.no_percent,abstain_percent=EXCLUDED.abstain_percent,detail_parse_status=EXCLUDED.detail_parse_status,votes_parse_status=EXCLUDED.votes_parse_status,parse_warnings=EXCLUDED.parse_warnings,raw_detail_render=EXCLUDED.raw_detail_render,raw_votes_render=EXCLUDED.raw_votes_render,last_observed_height=EXCLUDED.last_observed_height,last_observed_at=now(),updated_at=now()""",(chain,realm,p.proposal_id,p.title,p.author_display,p.author_address,p.status,json.dumps(p.eligible_tiers),p.description,p.executor_text,p.executor_creation_realm,p.rejection_reason,p.yes_percent,p.no_percent,p.abstain_percent,p.detail_parse_status,p.votes_parse_status,json.dumps(p.parse_warnings),dr,vr,height,height))
        keys=[v[0] for v in votes]
        cursor.execute("DELETE FROM governance_votes WHERE chain_id=%s AND realm_path=%s AND proposal_id=%s AND NOT (voter_key=ANY(%s))",(chain,realm,p.proposal_id,keys))
        for v in votes:
            cursor.execute("""INSERT INTO governance_votes(chain_id,realm_path,proposal_id,voter_key,voter_display,voter_address,option,tier,voting_power,first_observed_height,last_observed_height) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(chain_id,realm_path,proposal_id,voter_key) DO UPDATE SET voter_display=EXCLUDED.voter_display,voter_address=EXCLUDED.voter_address,option=EXCLUDED.option,tier=EXCLUDED.tier,voting_power=EXCLUDED.voting_power,last_observed_height=EXCLUDED.last_observed_height,last_observed_at=now(),updated_at=now()""",(chain,realm,p.proposal_id,*v,height,height))
    ids=sorted(incoming_ids)
    cursor.execute("""INSERT INTO governance_sync_state(chain_id,realm_path,source_height,page_count,proposal_count,first_proposal_id,latest_proposal_id) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(chain_id,realm_path) DO UPDATE SET source_height=EXCLUDED.source_height,page_count=EXCLUDED.page_count,proposal_count=EXCLUDED.proposal_count,first_proposal_id=EXCLUDED.first_proposal_id,latest_proposal_id=EXCLUDED.latest_proposal_id,last_success_at=now(),updated_at=now()""",(chain,realm,height,discovery.page_count,len(rows),ids[0] if ids else None,ids[-1] if ids else None))
    verified_state,verified,verified_votes=_load(cursor,chain,realm)
    _fail(verified_state[:5]!=(height,discovery.page_count,len(rows),ids[0] if ids else None,ids[-1] if ids else None) or _stored_content(verified,verified_votes)!=incoming_content,"post-write governance verification failed")
    inserted=sum(p.proposal_id not in old for p,_,_,_ in rows)
    return GovernancePersistenceResult("applied",height,discovery.page_count,len(rows),len(incoming_content[1]),inserted,len(rows)-inserted)
