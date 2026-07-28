"""Atomic PostgreSQL persistence for complete, fixed-height governance discoveries."""
from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any

from governance.gno import (
    MAX_GOVERNANCE_PAGES, MAX_GOVERNANCE_PROPOSALS, MAX_RENDER_BYTES,
    MAX_TEXT_CHARS, MAX_TOTAL_RAW_BYTES, MAX_WARNINGS, GovernanceDiscovery,
    GovernanceListDiscovery, GovernanceProposalDetail, GovernanceVote, proposal_raw_renders,
)

GOVERNANCE_ADVISORY_LOCK = -7046029254386353127
_STATUSES = {"ACTIVE", "ACCEPTED", "REJECTED", "UNKNOWN"}
_DETAIL_STATUSES = {"parsed", "partial"}
_VOTE_STATUSES = {"parsed", "empty", "unparsed"}
_OPTIONS = {"YES", "NO", "ABSTAIN"}
_TRANSITIONS = {"ACTIVE": {"ACCEPTED", "REJECTED"}, "UNKNOWN": {"ACTIVE", "ACCEPTED", "REJECTED"}}
_ADDRESS = re.compile(r"^g1[023456789acdefghjklmnpqrstuvwxyz]{38}$")
_POWER = re.compile(r"^[0-9]{1,78}$")


class GovernancePersistenceError(RuntimeError):
    """Governance snapshot cannot be persisted safely."""


class GovernanceChainIdentityError(GovernancePersistenceError): pass
class IncompleteGovernanceSnapshot(GovernancePersistenceError): pass
class StaleGovernanceSnapshot(GovernancePersistenceError): pass
class GovernanceSnapshotConflict(GovernancePersistenceError): pass
class GovernanceStoredStateError(GovernancePersistenceError): pass


@dataclass(frozen=True)
class GovernancePersistenceResult:
    action: str
    source_height: int
    page_count: int
    proposal_count: int
    vote_count: int
    inserted_proposals: int = 0
    updated_proposals: int = 0


@dataclass(frozen=True)
class _NormalizedProposal:
    proposal: GovernanceProposalDetail
    yes_percent: Decimal | None
    no_percent: Decimal | None
    abstain_percent: Decimal | None
    raw_detail: str
    raw_votes: str
    votes: tuple[tuple[str, str, str | None, str, str, Decimal], ...]


def _raise_if(condition: bool, message: str, error=GovernancePersistenceError) -> None:
    if condition:
        raise error(message)


def _integer(value: Any, minimum: int, maximum: int | None = None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= minimum and (maximum is None or value <= maximum)


def _bounded_text(value: Any, maximum: int, *, nullable: bool = False, nonempty: bool = False) -> bool:
    if value is None:
        return nullable
    return isinstance(value, str) and (not nonempty or bool(value)) and len(value) <= maximum


def voter_key(display: str, address: str | None) -> str:
    normalized_display = " ".join(display.split()).casefold()
    return f"address:{address.lower()}" if address else f"display:{normalized_display}"


def _percentage(value: Any) -> Decimal | None:
    if value is None:
        return None
    _raise_if(isinstance(value, bool) or not isinstance(value, (int, float, Decimal)), "invalid percentage")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise GovernancePersistenceError("invalid percentage") from exc
    _raise_if(not result.is_finite() or result < 0 or result > 100, "invalid percentage")
    canonical = result.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    _raise_if(canonical < 0 or canonical > 100, "invalid percentage")
    return canonical


def normalize_discovery(
    discovery: GovernanceDiscovery, configured_chain_id: str
) -> tuple[_NormalizedProposal, ...]:
    """Validate and canonicalize a complete snapshot without changing source text."""
    _raise_if(not isinstance(discovery, GovernanceDiscovery), "a GovernanceDiscovery is required")
    _raise_if(not isinstance(configured_chain_id, str) or not configured_chain_id, "configured chain ID is required", GovernanceChainIdentityError)
    source = discovery.source
    _raise_if(not discovery.complete, "only a complete full discovery may be persisted", IncompleteGovernanceSnapshot)
    _raise_if(not _bounded_text(source.chain_id, 128, nonempty=True), "invalid source chain ID")
    _raise_if(source.chain_id != configured_chain_id, "governance source chain does not match configured chain", GovernanceChainIdentityError)
    _raise_if(not _bounded_text(source.realm_path, 512, nonempty=True), "invalid governance realm")
    _raise_if(not _integer(source.observed_height, 1), "invalid governance source height")
    _raise_if(not _integer(discovery.page_count, 1, MAX_GOVERNANCE_PAGES), "complete discovery must include at least one bounded list page")
    _raise_if(not isinstance(discovery.proposals, (tuple, list)) or len(discovery.proposals) > MAX_GOVERNANCE_PROPOSALS, "invalid proposal collection")
    _raise_if(not isinstance(discovery.raw_renders, dict), "invalid raw renders")
    total_raw = 0
    for key, value in discovery.raw_renders.items():
        _raise_if(not isinstance(key, str) or not isinstance(value, str), "raw renders must be text")
        size = len(value.encode("utf-8"))
        _raise_if(size > MAX_RENDER_BYTES, "raw render exceeds limit")
        total_raw += size
    _raise_if(total_raw > MAX_TOTAL_RAW_BYTES, "raw renders exceed total limit")

    normalized: list[_NormalizedProposal] = []
    proposal_ids: set[int] = set()
    for proposal in discovery.proposals:
        _raise_if(not isinstance(proposal, GovernanceProposalDetail), "invalid proposal type")
        _raise_if(not _integer(proposal.proposal_id, 0), "invalid proposal ID")
        _raise_if(proposal.proposal_id in proposal_ids, "duplicate proposal ID")
        proposal_ids.add(proposal.proposal_id)
        _raise_if(not _bounded_text(proposal.title, 1000, nonempty=True), "invalid proposal title")
        _raise_if(not _bounded_text(proposal.author_display, 1000, nullable=True), "invalid proposal author display")
        _raise_if(proposal.author_address is not None and (not isinstance(proposal.author_address, str) or not _ADDRESS.fullmatch(proposal.author_address)), "invalid proposal author address")
        _raise_if(proposal.status not in _STATUSES, "invalid proposal status")
        _raise_if(not isinstance(proposal.eligible_tiers, (tuple, list)), "invalid eligible tiers")
        _raise_if(any(not _bounded_text(tier, 64, nonempty=True) or tier != tier.strip() for tier in proposal.eligible_tiers), "invalid eligible tier")
        _raise_if(not _bounded_text(proposal.description, MAX_TEXT_CHARS), "invalid proposal description")
        _raise_if(not _bounded_text(proposal.executor_text, MAX_TEXT_CHARS, nullable=True), "invalid executor text")
        _raise_if(not _bounded_text(proposal.executor_creation_realm, 1000, nullable=True), "invalid executor realm")
        _raise_if(not _bounded_text(proposal.rejection_reason, 10_000, nullable=True), "invalid rejection reason")
        percentages = tuple(_percentage(value) for value in
                            (proposal.yes_percent, proposal.no_percent, proposal.abstain_percent))
        _raise_if(proposal.detail_parse_status not in _DETAIL_STATUSES, "invalid detail parse status")
        _raise_if(proposal.votes_parse_status not in _VOTE_STATUSES, "invalid votes parse status")
        _raise_if(proposal.votes_parse_status == "unparsed", "unparsed votes make the snapshot incomplete", IncompleteGovernanceSnapshot)
        _raise_if(not isinstance(proposal.parse_warnings, (tuple, list)) or len(proposal.parse_warnings) > MAX_WARNINGS or any(not _bounded_text(item, 1000) for item in proposal.parse_warnings), "invalid parse warnings")
        # Ensure only JSON arrays of strings can reach PostgreSQL.
        _raise_if(not isinstance(json.loads(json.dumps(list(proposal.eligible_tiers))), list), "invalid eligible tiers")
        _raise_if(not isinstance(json.loads(json.dumps(list(proposal.parse_warnings))), list), "invalid parse warnings")
        raw_detail, raw_votes = proposal_raw_renders(discovery, proposal.proposal_id)
        _raise_if(not isinstance(raw_detail, str) or not isinstance(raw_votes, str), "proposal raw renders are missing")

        votes: list[tuple[str, str, str | None, str, str, Decimal]] = []
        keys: set[str] = set()
        _raise_if(not isinstance(proposal.votes, (tuple, list)), "invalid vote collection")
        _raise_if(proposal.votes_parse_status == "empty" and bool(proposal.votes), "empty vote status contains votes")
        _raise_if(proposal.votes_parse_status == "parsed" and not proposal.votes, "parsed vote status requires votes")
        for vote in proposal.votes:
            _raise_if(not isinstance(vote, GovernanceVote), "invalid vote type")
            display = " ".join(vote.voter_display.split()) if isinstance(vote.voter_display, str) else ""
            _raise_if(not display or len(vote.voter_display) > 1000, "invalid voter display")
            _raise_if(vote.voter_address is not None and (not isinstance(vote.voter_address, str) or not _ADDRESS.fullmatch(vote.voter_address)), "invalid voter address")
            _raise_if(vote.option not in _OPTIONS, "invalid vote option")
            _raise_if(not isinstance(vote.tier, str) or not vote.tier.strip() or vote.tier != vote.tier.strip() or len(vote.tier) > 64, "invalid vote tier")
            _raise_if(not isinstance(vote.voting_power, str) or not _POWER.fullmatch(vote.voting_power), "invalid voting power")
            key = voter_key(vote.voter_display, vote.voter_address)
            _raise_if(not key or len(key) > 1100 or key in keys, "duplicate or invalid voter key")
            keys.add(key)
            votes.append((key, vote.voter_display, vote.voter_address, vote.option, vote.tier, Decimal(vote.voting_power)))
        votes.sort(key=lambda item: item[0])
        normalized.append(_NormalizedProposal(proposal, *percentages, raw_detail, raw_votes, tuple(votes)))
    normalized.sort(key=lambda item: item.proposal.proposal_id)
    return tuple(normalized)


_PROPOSAL_COLUMNS = "proposal_id,title,author_display,author_address,status,eligible_tiers,description,executor_text,executor_creation_realm,rejection_reason,yes_percent,no_percent,abstain_percent,detail_parse_status,votes_parse_status,parse_warnings,raw_detail_render,raw_votes_render,first_observed_height,last_observed_height,first_observed_at,last_observed_at"


def _valid_stored_text(value: Any, maximum: int, nullable: bool = False, nonempty: bool = False) -> bool:
    return _bounded_text(value, maximum, nullable=nullable, nonempty=nonempty)


def _load(cursor, chain: str, realm: str):
    cursor.execute("SELECT source_height,page_count,proposal_count,first_proposal_id,latest_proposal_id FROM governance_sync_state WHERE chain_id=%s AND realm_path=%s FOR UPDATE", (chain, realm))
    state = cursor.fetchone()
    cursor.execute(f"SELECT {_PROPOSAL_COLUMNS} FROM governance_proposals WHERE chain_id=%s AND realm_path=%s ORDER BY proposal_id ASC", (chain, realm))
    proposals = cursor.fetchall()
    cursor.execute("SELECT proposal_id,voter_key,voter_display,voter_address,option,tier,voting_power,first_observed_height,last_observed_height,first_observed_at,last_observed_at FROM governance_votes WHERE chain_id=%s AND realm_path=%s ORDER BY proposal_id ASC,voter_key ASC", (chain, realm))
    votes = cursor.fetchall()
    if state is None:
        _raise_if(bool(proposals or votes), "governance rows exist without sync state", GovernanceStoredStateError)
        return state, proposals, votes

    source_height, page_count, proposal_count, first_id, latest_id = state
    ids = [row[0] for row in proposals]
    valid_state = (
        _integer(source_height, 1) and _integer(page_count, 1, MAX_GOVERNANCE_PAGES)
        and _integer(proposal_count, 0, MAX_GOVERNANCE_PROPOSALS)
        and proposal_count == len(ids)
        and ((proposal_count == 0 and first_id is None and latest_id is None)
             or (proposal_count > 0 and _integer(first_id, 0) and _integer(latest_id, first_id)
                 and first_id == min(ids) and latest_id == max(ids)))
    )
    _raise_if(not valid_state, "stored governance sync state is inconsistent", GovernanceStoredStateError)
    raw_total = 0
    proposal_id_set = set(ids)
    stored_vote_counts: dict[int, int] = {}
    for vote_row in votes:
        stored_vote_counts[vote_row[0]] = stored_vote_counts.get(vote_row[0], 0) + 1
    for row in proposals:
        (proposal_id, title, author_display, author_address, status, tiers, description,
         executor_text, executor_realm, rejection_reason, yes, no, abstain,
         detail_status, votes_status, warnings, raw_detail, raw_votes, first_height,
         last_height, first_at, last_at) = row
        valid = (
            _integer(proposal_id, 0) and _valid_stored_text(title, 1000, nonempty=True)
            and _valid_stored_text(author_display, 1000, nullable=True)
            and (author_address is None or isinstance(author_address, str) and bool(_ADDRESS.fullmatch(author_address)))
            and status in _STATUSES and isinstance(tiers, list) and all(_valid_stored_text(t, 64, nonempty=True) for t in tiers)
            and _valid_stored_text(description, MAX_TEXT_CHARS)
            and _valid_stored_text(executor_text, MAX_TEXT_CHARS, nullable=True)
            and _valid_stored_text(executor_realm, 1000, nullable=True)
            and _valid_stored_text(rejection_reason, 10_000, nullable=True)
            and all(value is None or isinstance(value, Decimal) and value.is_finite() and 0 <= value <= 100 for value in (yes, no, abstain))
            and detail_status in _DETAIL_STATUSES
            and votes_status in {"parsed", "empty"}
            and ((votes_status == "parsed" and stored_vote_counts.get(proposal_id, 0) > 0)
                 or (votes_status == "empty" and stored_vote_counts.get(proposal_id, 0) == 0))
            and isinstance(warnings, list) and all(_valid_stored_text(w, 1000) for w in warnings)
            and isinstance(raw_detail, str) and len(raw_detail.encode()) <= MAX_RENDER_BYTES
            and isinstance(raw_votes, str) and len(raw_votes.encode()) <= MAX_RENDER_BYTES
            and _integer(first_height, 1) and _integer(last_height, first_height) and last_height <= source_height
            and isinstance(first_at, datetime) and isinstance(last_at, datetime) and last_at >= first_at
        )
        _raise_if(not valid, "stored governance proposal is inconsistent", GovernanceStoredStateError)
        raw_total += len(raw_detail.encode())
        raw_total += len(raw_votes.encode())
    _raise_if(raw_total > MAX_TOTAL_RAW_BYTES, "stored governance raw total exceeds limit", GovernanceStoredStateError)
    seen_votes: set[tuple[int, str]] = set()
    for row in votes:
        proposal_id, key, display, address, option, tier, power, first_height, last_height, first_at, last_at = row
        valid = (
            proposal_id in proposal_id_set and _valid_stored_text(key, 1100, nonempty=True)
            and (proposal_id, key) not in seen_votes and _valid_stored_text(display, 1000, nonempty=True)
            and (address is None or isinstance(address, str) and bool(_ADDRESS.fullmatch(address)))
            and key == voter_key(display, address)
            and option in _OPTIONS and _valid_stored_text(tier, 64, nonempty=True)
            and isinstance(power, Decimal) and power.is_finite() and power >= 0 and power == power.to_integral_value() and len(str(power.to_integral_value())) <= 78
            and _integer(first_height, 1) and _integer(last_height, first_height) and last_height <= source_height
            and isinstance(first_at, datetime) and isinstance(last_at, datetime) and last_at >= first_at
        )
        _raise_if(not valid, "stored governance vote is inconsistent", GovernanceStoredStateError)
        seen_votes.add((proposal_id, key))
    return state, proposals, votes


def _content(rows: tuple[_NormalizedProposal, ...]):
    proposals = []
    votes = []
    for row in rows:
        p = row.proposal
        proposals.append((p.proposal_id, p.title, p.author_display, p.author_address, p.status,
            tuple(p.eligible_tiers), p.description, p.executor_text, p.executor_creation_realm,
            p.rejection_reason, row.yes_percent, row.no_percent, row.abstain_percent,
            p.detail_parse_status, p.votes_parse_status,
            tuple(p.parse_warnings), row.raw_detail, row.raw_votes))
        votes.extend((p.proposal_id,) + vote for vote in row.votes)
    return proposals, votes


def _stored_content(proposals, votes):
    proposal_content = [tuple(list(row[:5]) + [tuple(row[5]), *row[6:15], tuple(row[15]), row[16], row[17]]) for row in proposals]
    vote_content = [tuple(row[:6]) + (Decimal(row[6]),) for row in votes]
    return sorted(proposal_content, key=lambda row: row[0]), sorted(vote_content, key=lambda row: (row[0], row[1]))


def persist_governance_snapshot_cursor(cursor, discovery, configured_chain_id):
    rows = normalize_discovery(discovery, configured_chain_id)
    chain, realm, height = discovery.source.chain_id, discovery.source.realm_path, discovery.source.observed_height
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (GOVERNANCE_ADVISORY_LOCK,))
    cursor.execute("SELECT chain_id FROM indexer_state WHERE state_key=%s", ("default",))
    identity = cursor.fetchone()
    _raise_if(identity is not None and identity[0] != chain, "indexer state belongs to another chain", GovernanceChainIdentityError)
    state, stored, stored_votes = _load(cursor, chain, realm)
    incoming_content = _content(rows)
    ids = [row.proposal.proposal_id for row in rows]
    metadata = (discovery.page_count, len(rows), ids[0] if ids else None, ids[-1] if ids else None)
    if state and state[0] > height:
        raise StaleGovernanceSnapshot("governance snapshot is stale")
    if state and state[0] == height:
        if tuple(state[1:5]) == metadata and _stored_content(stored, stored_votes) == incoming_content:
            return GovernancePersistenceResult("unchanged", height, discovery.page_count, len(rows), len(incoming_content[1]))
        raise GovernanceSnapshotConflict("same-height governance snapshot differs")
    old = {row[0]: row for row in stored}
    _raise_if(not set(old).issubset(ids), "a stored proposal is missing from newer snapshot", GovernanceSnapshotConflict)
    for row in rows:
        p = row.proposal
        if p.proposal_id in old and old[p.proposal_id][4] != p.status:
            _raise_if(p.status not in _TRANSITIONS.get(old[p.proposal_id][4], set()), "invalid governance status transition", GovernanceSnapshotConflict)
        cursor.execute("""INSERT INTO governance_proposals(chain_id,realm_path,proposal_id,title,author_display,author_address,status,eligible_tiers,description,executor_text,executor_creation_realm,rejection_reason,yes_percent,no_percent,abstain_percent,detail_parse_status,votes_parse_status,parse_warnings,raw_detail_render,raw_votes_render,first_observed_height,last_observed_height) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s) ON CONFLICT(chain_id,realm_path,proposal_id) DO UPDATE SET title=EXCLUDED.title,author_display=EXCLUDED.author_display,author_address=EXCLUDED.author_address,status=EXCLUDED.status,eligible_tiers=EXCLUDED.eligible_tiers,description=EXCLUDED.description,executor_text=EXCLUDED.executor_text,executor_creation_realm=EXCLUDED.executor_creation_realm,rejection_reason=EXCLUDED.rejection_reason,yes_percent=EXCLUDED.yes_percent,no_percent=EXCLUDED.no_percent,abstain_percent=EXCLUDED.abstain_percent,detail_parse_status=EXCLUDED.detail_parse_status,votes_parse_status=EXCLUDED.votes_parse_status,parse_warnings=EXCLUDED.parse_warnings,raw_detail_render=EXCLUDED.raw_detail_render,raw_votes_render=EXCLUDED.raw_votes_render,last_observed_height=EXCLUDED.last_observed_height,last_observed_at=now(),updated_at=now()""", (chain, realm, p.proposal_id, p.title, p.author_display, p.author_address, p.status, json.dumps(list(p.eligible_tiers)), p.description, p.executor_text, p.executor_creation_realm, p.rejection_reason, row.yes_percent, row.no_percent, row.abstain_percent, p.detail_parse_status, p.votes_parse_status, json.dumps(list(p.parse_warnings)), row.raw_detail, row.raw_votes, height, height))
        keys = [vote[0] for vote in row.votes]
        if keys:
            cursor.execute("DELETE FROM governance_votes WHERE chain_id=%s AND realm_path=%s AND proposal_id=%s AND NOT (voter_key=ANY(%s::text[]))", (chain, realm, p.proposal_id, keys))
        elif p.votes_parse_status == "empty":
            cursor.execute("DELETE FROM governance_votes WHERE chain_id=%s AND realm_path=%s AND proposal_id=%s", (chain, realm, p.proposal_id))
        for vote in row.votes:
            cursor.execute("""INSERT INTO governance_votes(chain_id,realm_path,proposal_id,voter_key,voter_display,voter_address,option,tier,voting_power,first_observed_height,last_observed_height) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(chain_id,realm_path,proposal_id,voter_key) DO UPDATE SET voter_display=EXCLUDED.voter_display,voter_address=EXCLUDED.voter_address,option=EXCLUDED.option,tier=EXCLUDED.tier,voting_power=EXCLUDED.voting_power,last_observed_height=EXCLUDED.last_observed_height,last_observed_at=now(),updated_at=now()""", (chain, realm, p.proposal_id, *vote, height, height))
    cursor.execute("""INSERT INTO governance_sync_state(chain_id,realm_path,source_height,page_count,proposal_count,first_proposal_id,latest_proposal_id) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(chain_id,realm_path) DO UPDATE SET source_height=EXCLUDED.source_height,page_count=EXCLUDED.page_count,proposal_count=EXCLUDED.proposal_count,first_proposal_id=EXCLUDED.first_proposal_id,latest_proposal_id=EXCLUDED.latest_proposal_id,last_success_at=now(),updated_at=now()""", (chain, realm, height, *metadata))
    verified_state, verified, verified_votes = _load(cursor, chain, realm)
    _raise_if(tuple(verified_state[:5]) != (height, *metadata) or _stored_content(verified, verified_votes) != incoming_content, "post-write governance verification failed")
    inserted = sum(row.proposal.proposal_id not in old for row in rows)
    return GovernancePersistenceResult("applied", height, discovery.page_count, len(rows), len(incoming_content[1]), inserted, len(rows) - inserted)


def select_governance_refresh_ids(
    summaries, stored_statuses: dict[int, str]
) -> tuple[int, ...]:
    """Return deterministic targeted refresh IDs for one complete list scan."""
    selected = []
    for summary in summaries:
        old = stored_statuses.get(summary.proposal_id)
        if old is None or old in {"ACTIVE", "UNKNOWN"} or summary.status in {"ACTIVE", "UNKNOWN"}:
            selected.append(summary.proposal_id)
    return tuple(sorted(selected))


def persist_governance_incremental_cursor(cursor, listed, targeted, configured_chain_id):
    """Validate and atomically apply a list scan plus exact targeted refreshes."""
    _raise_if(not isinstance(listed, GovernanceListDiscovery), "a GovernanceListDiscovery is required")
    _raise_if(not listed.complete, "only a complete list discovery may be persisted", IncompleteGovernanceSnapshot)
    source = listed.source
    _raise_if(source.chain_id != configured_chain_id, "governance source chain does not match configured chain", GovernanceChainIdentityError)
    _raise_if(not _bounded_text(source.realm_path, 512, nonempty=True), "invalid governance realm")
    _raise_if(not _integer(source.observed_height, 1), "invalid governance source height")
    _raise_if(not _integer(listed.page_count, 1, MAX_GOVERNANCE_PAGES), "invalid list page count")
    summaries = {item.proposal_id: item for item in listed.proposals}
    _raise_if(len(summaries) != len(listed.proposals), "duplicate proposal ID")
    _raise_if(len(summaries) > MAX_GOVERNANCE_PROPOSALS, "invalid proposal collection")
    cursor.execute("SELECT pg_advisory_xact_lock(%s)", (GOVERNANCE_ADVISORY_LOCK,))
    cursor.execute("SELECT chain_id FROM indexer_state WHERE state_key=%s", ("default",))
    identity = cursor.fetchone()
    _raise_if(identity is not None and identity[0] != source.chain_id,
              "indexer state belongs to another chain", GovernanceChainIdentityError)
    state, stored, stored_votes = _load(cursor, source.chain_id, source.realm_path)
    height = source.observed_height
    if state and state[0] > height:
        raise StaleGovernanceSnapshot("governance snapshot is stale")
    old = {row[0]: row for row in stored}
    _raise_if(not set(old).issubset(summaries), "a stored proposal is missing from newer list", GovernanceSnapshotConflict)
    for proposal_id, row in old.items():
        new_status = summaries[proposal_id].status
        if row[4] != new_status:
            _raise_if(new_status not in _TRANSITIONS.get(row[4], set()),
                      "invalid governance status transition", GovernanceSnapshotConflict)
    required = set(select_governance_refresh_ids(listed.proposals, {key: row[4] for key, row in old.items()}))
    target_map = {}
    for discovery in targeted:
        _raise_if(not isinstance(discovery, GovernanceDiscovery) or discovery.source != source,
                  "targeted discovery source mismatch")
        _raise_if(len(discovery.proposals) != 1, "targeted discovery must contain exactly one proposal")
        proposal_id = discovery.proposals[0].proposal_id
        _raise_if(proposal_id in target_map, "duplicate targeted discovery")
        _raise_if(proposal_id not in required or proposal_id not in summaries,
                  "unrelated targeted discovery")
        target_map[proposal_id] = discovery
    _raise_if(set(target_map) != required, "selected proposal is missing targeted discovery")
    normalized = {}
    for proposal_id, discovery in target_map.items():
        candidate = GovernanceDiscovery(source, True, 1, discovery.proposals, (), discovery.raw_renders)
        row = normalize_discovery(candidate, configured_chain_id)[0]
        _raise_if(row.proposal.proposal_id != proposal_id, "targeted proposal ID mismatch")
        _raise_if(row.proposal.status != summaries[proposal_id].status
                  and summaries[proposal_id].status != "UNKNOWN",
                  "targeted proposal status differs from list")
        normalized[proposal_id] = row
    ids = sorted(summaries)
    metadata = (listed.page_count, len(ids), ids[0] if ids else None, ids[-1] if ids else None)
    if state and state[0] == height:
        # At one source height, an already-published list is immutable. Targeted rows
        # must also be byte-for-byte equal to make retries idempotent.
        if tuple(state[1:5]) != metadata:
            raise GovernanceSnapshotConflict("same-height governance list differs")
        for proposal_id, row in normalized.items():
            current = next(item for item in stored if item[0] == proposal_id)
            current_votes = [vote for vote in stored_votes if vote[0] == proposal_id]
            if _stored_content([current], current_votes) != _content((row,)):
                raise GovernanceSnapshotConflict("same-height targeted content differs")
        return GovernancePersistenceResult("unchanged", height, listed.page_count, len(ids), len(stored_votes))
    for proposal_id, row in normalized.items():
        p = row.proposal
        cursor.execute("""INSERT INTO governance_proposals(chain_id,realm_path,proposal_id,title,author_display,author_address,status,eligible_tiers,description,executor_text,executor_creation_realm,rejection_reason,yes_percent,no_percent,abstain_percent,detail_parse_status,votes_parse_status,parse_warnings,raw_detail_render,raw_votes_render,first_observed_height,last_observed_height) VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s,%s,%s) ON CONFLICT(chain_id,realm_path,proposal_id) DO UPDATE SET title=EXCLUDED.title,author_display=EXCLUDED.author_display,author_address=EXCLUDED.author_address,status=EXCLUDED.status,eligible_tiers=EXCLUDED.eligible_tiers,description=EXCLUDED.description,executor_text=EXCLUDED.executor_text,executor_creation_realm=EXCLUDED.executor_creation_realm,rejection_reason=EXCLUDED.rejection_reason,yes_percent=EXCLUDED.yes_percent,no_percent=EXCLUDED.no_percent,abstain_percent=EXCLUDED.abstain_percent,detail_parse_status=EXCLUDED.detail_parse_status,votes_parse_status=EXCLUDED.votes_parse_status,parse_warnings=EXCLUDED.parse_warnings,raw_detail_render=EXCLUDED.raw_detail_render,raw_votes_render=EXCLUDED.raw_votes_render,last_observed_height=EXCLUDED.last_observed_height,last_observed_at=now(),updated_at=now()""", (source.chain_id, source.realm_path, proposal_id, p.title, p.author_display, p.author_address, p.status, json.dumps(list(p.eligible_tiers)), p.description, p.executor_text, p.executor_creation_realm, p.rejection_reason, row.yes_percent, row.no_percent, row.abstain_percent, p.detail_parse_status, p.votes_parse_status, json.dumps(list(p.parse_warnings)), row.raw_detail, row.raw_votes, height, height))
        keys = [vote[0] for vote in row.votes]
        if keys:
            cursor.execute("DELETE FROM governance_votes WHERE chain_id=%s AND realm_path=%s AND proposal_id=%s AND NOT (voter_key=ANY(%s::text[]))", (source.chain_id, source.realm_path, proposal_id, keys))
        else:
            cursor.execute("DELETE FROM governance_votes WHERE chain_id=%s AND realm_path=%s AND proposal_id=%s", (source.chain_id, source.realm_path, proposal_id))
        for vote in row.votes:
            cursor.execute("""INSERT INTO governance_votes(chain_id,realm_path,proposal_id,voter_key,voter_display,voter_address,option,tier,voting_power,first_observed_height,last_observed_height) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(chain_id,realm_path,proposal_id,voter_key) DO UPDATE SET voter_display=EXCLUDED.voter_display,voter_address=EXCLUDED.voter_address,option=EXCLUDED.option,tier=EXCLUDED.tier,voting_power=EXCLUDED.voting_power,last_observed_height=EXCLUDED.last_observed_height,last_observed_at=now(),updated_at=now()""", (source.chain_id, source.realm_path, proposal_id, *vote, height, height))
    cursor.execute("""INSERT INTO governance_sync_state(chain_id,realm_path,source_height,page_count,proposal_count,first_proposal_id,latest_proposal_id) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(chain_id,realm_path) DO UPDATE SET source_height=EXCLUDED.source_height,page_count=EXCLUDED.page_count,proposal_count=EXCLUDED.proposal_count,first_proposal_id=EXCLUDED.first_proposal_id,latest_proposal_id=EXCLUDED.latest_proposal_id,last_success_at=now(),updated_at=now()""", (source.chain_id, source.realm_path, height, *metadata))
    inserted = sum(proposal_id not in old for proposal_id in normalized)
    return GovernancePersistenceResult("applied", height, listed.page_count, len(ids),
                                       sum(len(row.votes) for row in normalized.values()),
                                       inserted, len(normalized) - inserted)
