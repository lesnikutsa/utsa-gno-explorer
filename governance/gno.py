"""Bounded parsing and discovery of GovDAO qrender documents."""
from __future__ import annotations

import re
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from typing import Callable

from scripts.inspect_rpc import GnoRpcClient, RpcError

DEFAULT_REALM = "gno.land/r/gov/dao"
MAX_GOVERNANCE_PAGES = 100
MAX_GOVERNANCE_PROPOSALS = 1000
MAX_RENDER_BYTES = 1024 * 1024
MAX_TEXT_CHARS = 100_000
MAX_WARNINGS = 50

_HEADER = re.compile(r"^#{2,3}\s+(?:\[)?Prop\s+#([0-9]+)\s*-\s*(.+?)(?:\]\([^)]*\))?\s*$", re.I)
_FIELD = re.compile(r"^(Author|Status|Tiers eligible to vote):\s*(.*?)\s*$", re.I)
_LINK = re.compile(r"\[[^]]*\]\(([^)]+)\)")
_ADDRESS = re.compile(r"\bg1[023456789ac-hj-np-z]{38}\b")
_PAGE = re.compile(r"^(?:" + re.escape(DEFAULT_REALM) + r":)?\?page=([1-9][0-9]*)$")


class GovernanceParseError(ValueError):
    """The source cannot be interpreted safely."""


@dataclass(frozen=True)
class GovernanceSource:
    chain_id: str
    rpc_url: str
    observed_height: int
    realm_path: str


@dataclass(frozen=True)
class GovernanceProposalSummary:
    proposal_id: int
    title: str
    author_display: str | None
    author_address: str | None
    status: str
    eligible_tiers: tuple[str, ...] = ()
    parse_warnings: tuple[str, ...] = ()


@dataclass(frozen=True)
class GovernanceVote:
    voter_display: str
    voter_address: str | None
    option: str | None
    tier: str | None
    voting_power: str | None


@dataclass(frozen=True)
class GovernanceProposalDetail:
    proposal_id: int
    title: str
    author_display: str | None
    author_address: str | None
    status: str
    eligible_tiers: tuple[str, ...]
    description: str
    executor_text: str | None
    executor_creation_realm: str | None
    detail_parse_status: str
    votes_parse_status: str
    votes: tuple[GovernanceVote, ...]
    parse_warnings: tuple[str, ...]


@dataclass(frozen=True)
class GovernanceDiscovery:
    source: GovernanceSource
    complete: bool
    page_count: int
    proposals: tuple[GovernanceProposalDetail, ...]
    warnings: tuple[str, ...] = ()
    raw_renders: dict[str, str] = field(default_factory=dict, repr=False, compare=False)

    def to_dict(self, include_raw: bool = False) -> dict:
        proposals = [asdict(item) for item in self.proposals]
        counts = Counter(item.status.lower() for item in self.proposals)
        output = {
            "source": asdict(self.source), "complete": self.complete,
            "page_count": self.page_count, "proposal_count": len(proposals),
            "status_counts": {name: counts[name] for name in ("active", "accepted", "rejected", "unknown")},
            "proposals": proposals, "warnings": list(self.warnings),
        }
        if include_raw:
            output["raw_renders"] = self.raw_renders
        return output


def _text(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()
    return value[:limit]


def _display(value: str) -> tuple[str | None, str | None]:
    value = _text(value, 1000)
    link = re.fullmatch(r"\[([^]]+)\]\([^)]+\)", value)
    display = _text(link.group(1) if link else value, 1000) or None
    address = _ADDRESS.search(value)
    return display, address.group(0) if address else None


def _status(value: str) -> tuple[str, str | None]:
    normalized = value.strip().upper()
    if normalized in {"ACTIVE", "ACCEPTED", "REJECTED"}:
        return normalized, None
    return "UNKNOWN", f"Unknown governance status: {_text(value, 100)}"


def parse_proposal_list(render: str) -> tuple[list[GovernanceProposalSummary], list[str]]:
    _validate_size(render)
    lines = render.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    starts = [(i, _HEADER.match(line.strip())) for i, line in enumerate(lines)]
    starts = [(i, m) for i, m in starts if m]
    proposals: list[GovernanceProposalSummary] = []
    warnings: list[str] = []
    for pos, (start, match) in enumerate(starts):
        assert match
        end = starts[pos + 1][0] if pos + 1 < len(starts) else len(lines)
        values: dict[str, str] = {}
        for line in lines[start + 1:end]:
            field_match = _FIELD.match(line.strip())
            if field_match:
                values[field_match.group(1).lower()] = field_match.group(2)
        if "status" not in values:
            raise GovernanceParseError(f"Proposal {match.group(1)} has no status")
        status, warning = _status(values["status"])
        local = (warning,) if warning else ()
        if warning: warnings.append(warning)
        author, address = _display(values.get("author", ""))
        tiers = tuple(x.strip().upper() for x in values.get("tiers eligible to vote", "").split(",") if x.strip())
        proposals.append(GovernanceProposalSummary(int(match.group(1)), _text(match.group(2), 1000), author, address, status, tiers, local))
    seen: dict[int, GovernanceProposalSummary] = {}
    for proposal in proposals:
        previous = seen.get(proposal.proposal_id)
        if previous and previous != proposal:
            raise GovernanceParseError(f"Conflicting duplicate proposal ID {proposal.proposal_id}")
        seen[proposal.proposal_id] = proposal
    return list(seen.values()), warnings[:MAX_WARNINGS]


def pager_paths(render: str, realm: str) -> list[str]:
    paths = []
    pattern = re.compile(r"^(?:" + re.escape(realm) + r":)?\?page=([1-9][0-9]*)$")
    for target in _LINK.findall(render):
        if pattern.fullmatch(target.strip()):
            page = pattern.fullmatch(target.strip()).group(1)
            paths.append("" if page == "1" else "?page=" + page)
    return list(dict.fromkeys(paths))


def parse_detail(render: str, requested_id: int) -> dict:
    _validate_size(render)
    lines = render.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    header_index = next((i for i, line in enumerate(lines) if _HEADER.match(line.strip())), None)
    if header_index is None:
        raise GovernanceParseError(f"Proposal {requested_id} detail has no ID/title")
    match = _HEADER.match(lines[header_index].strip()); assert match
    if int(match.group(1)) != requested_id:
        raise GovernanceParseError(f"Proposal detail ID does not match requested ID {requested_id}")
    values = {}
    for line in lines[header_index + 1:]:
        fm = _FIELD.match(line.strip())
        if fm: values[fm.group(1).lower()] = fm.group(2)
    author, address = _display(values.get("author", ""))
    status, warning = _status(values.get("status", ""))
    stop_markers = ("This proposal contains the following metadata:", "Actions", "Detailed voting list", "---", "Status:")
    body_start = header_index + 1
    while body_start < len(lines) and (not lines[body_start].strip() or _FIELD.match(lines[body_start].strip())): body_start += 1
    body_end = next((i for i in range(body_start, len(lines)) if any(lines[i].strip().startswith(x) for x in stop_markers)), len(lines))
    executor_realm = next((line.split(":", 1)[1].strip() for line in lines if line.strip().startswith("Executor created in:")), None)
    metadata_index = next((i for i, line in enumerate(lines) if line.strip() == "This proposal contains the following metadata:"), None)
    executor = None
    if metadata_index is not None:
        executor_lines = []
        for line in lines[metadata_index + 1:]:
            if line.strip().startswith(("Executor created in:", "---")): break
            executor_lines.append(line)
        executor = _text("\n".join(executor_lines)) or None
    return {"proposal_id": requested_id, "title": _text(match.group(2), 1000), "author_display": author,
            "author_address": address, "status": status, "eligible_tiers": tuple(x.strip().upper() for x in values.get("tiers eligible to vote", "").split(",") if x.strip()),
            "description": _text("\n".join(lines[body_start:body_end])), "executor_text": executor,
            "executor_creation_realm": _text(executor_realm, 1000) if executor_realm else None,
            "warnings": [warning] if warning else []}


def parse_votes(render: str) -> tuple[str, tuple[GovernanceVote, ...], list[str]]:
    _validate_size(render)
    text = _text(render)
    if not text or re.search(r"\b(?:no votes|no vote has been cast)\b", text, re.I): return "empty", (), []
    votes = []
    pattern = re.compile(r"^[-*]\s+(.+?)\s*\|\s*(YES|NO|ABSTAIN)(?:\s*\|\s*(T[123]))?(?:\s*\|\s*([^|]+))?\s*$", re.I)
    for line in text.splitlines():
        match = pattern.match(line.strip())
        if match:
            display, address = _display(match.group(1))
            votes.append(GovernanceVote(display or "", address, match.group(2).upper(), match.group(3).upper() if match.group(3) else None, _text(match.group(4), 100) if match.group(4) else None))
    if votes: return "parsed", tuple(votes), []
    return "unparsed", (), ["Votes render format was not recognized"]


def discover_governance(client: GnoRpcClient, source: GovernanceSource, max_pages: int = MAX_GOVERNANCE_PAGES,
                        max_proposals: int = MAX_GOVERNANCE_PROPOSALS, proposal_id: int | None = None) -> GovernanceDiscovery:
    if not 1 <= max_pages <= MAX_GOVERNANCE_PAGES or not 1 <= max_proposals <= MAX_GOVERNANCE_PROPOSALS:
        raise GovernanceParseError("Discovery limits exceed hard safety limits")
    raw, warnings, summaries = {}, [], {}
    page_count, complete = 0, True
    if proposal_id is not None:
        summaries[proposal_id] = None
    else:
        queue, visited = deque([""]), set()
        while queue:
            path = queue.popleft()
            if path in visited: continue
            if page_count >= max_pages: complete = False; warnings.append("Governance page limit reached"); break
            visited.add(path); render = _render(client, source.realm_path, path); raw[f"list/{path or 'root'}"] = render; page_count += 1
            parsed, page_warnings = parse_proposal_list(render); warnings.extend(page_warnings)
            for item in parsed:
                old = summaries.get(item.proposal_id)
                if old is not None and old != item: raise GovernanceParseError(f"Conflicting duplicate proposal ID {item.proposal_id}")
                summaries[item.proposal_id] = item
            if len(summaries) > max_proposals: raise GovernanceParseError("Governance proposal limit exceeded")
            pages = pager_paths(render, source.realm_path)
            queue.extend(p for p in pages if p not in visited)
            if not pages and path == "" and len(parsed) >= 5:
                complete = False; warnings.append("Pagination format was not recognized; list may be incomplete")
    details = []
    for pid in sorted(summaries, reverse=True):
        detail_render = _render(client, source.realm_path, str(pid)); votes_render = _render(client, source.realm_path, f"{pid}/votes")
        raw[f"proposal/{pid}"] = detail_render; raw[f"proposal/{pid}/votes"] = votes_render
        detail = parse_detail(detail_render, pid); vote_status, votes, vote_warnings = parse_votes(votes_render)
        details.append(GovernanceProposalDetail(**{k: detail[k] for k in ("proposal_id", "title", "author_display", "author_address", "status", "eligible_tiers", "description", "executor_text", "executor_creation_realm")}, detail_parse_status="parsed", votes_parse_status=vote_status, votes=votes, parse_warnings=tuple((detail["warnings"] + vote_warnings)[:MAX_WARNINGS])))
    return GovernanceDiscovery(source, complete, page_count, tuple(details), tuple(warnings[:MAX_WARNINGS]), raw)


def _render(client: GnoRpcClient, realm: str, path: str) -> str:
    return client.abci_query("vm/qrender", f"{realm}:{path}")


def _validate_size(render: str) -> None:
    if not isinstance(render, str): raise GovernanceParseError("Render must be text")
    if len(render.encode("utf-8")) > MAX_RENDER_BYTES: raise GovernanceParseError("Governance render exceeds size limit")
