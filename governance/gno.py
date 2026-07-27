"""Bounded parsing and discovery of official GovDAO qrender documents."""
from __future__ import annotations

import math
import re
from collections import Counter, deque
from dataclasses import asdict, dataclass, field
from typing import Callable

from scripts.inspect_rpc import GnoRpcClient

DEFAULT_REALM = "gno.land/r/gov/dao"
MAX_GOVERNANCE_PAGES = 100
MAX_GOVERNANCE_PROPOSALS = 1000
MAX_RENDER_BYTES = 1024 * 1024
MAX_TOTAL_RAW_BYTES = 16 * 1024 * 1024
MAX_TEXT_CHARS = 100_000
MAX_WARNINGS = 50

_HEADER = re.compile(r"^#{2,3}\s+(?:\[)?Prop\s+#([0-9]+)\s*-\s*(.+?)(?:\]\([^)]*\))?\s*$", re.I)
_LIST_FIELD = re.compile(r"^(?:[-*]\s+)?(Author|Status|Tiers eligible to vote):\s*(.*?)\s*$", re.I)
_LINK = re.compile(r"\[[^]]*\]\(([^)]+)\)")
_ADDRESS = re.compile(r"\bg1[023456789ac-hj-np-z]{38}\b")
_VOTE_GROUP = re.compile(r"^(YES|NO|ABSTAIN)\s+from\s+([^\s]+)\s+\(VPPM\s+([^()]+)\):\s*$", re.I)
_PERCENT = re.compile(r"^(?:[-*]\s+)?(YES|NO|ABSTAIN)\s+PERCENT:\s*(.*?)\s*$", re.I)
_MARKDOWN_ESCAPABLE = frozenset(r"\`*_{}[]()#+-.!|>~")


class GovernanceParseError(ValueError):
    """The governance source cannot be interpreted safely."""


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
    option: str
    tier: str
    voting_power: str


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
    rejection_reason: str | None
    yes_percent: float | None
    no_percent: float | None
    abstain_percent: float | None
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
        proposal_ids = [item.proposal_id for item in self.proposals]
        counts = Counter(item.status.lower() for item in self.proposals)
        output = {
            "source": asdict(self.source),
            "complete": self.complete,
            "page_count": self.page_count,
            "proposal_count": len(proposals),
            "first_proposal_id": min(proposal_ids) if proposal_ids else None,
            "latest_proposal_id": max(proposal_ids) if proposal_ids else None,
            "status_counts": {name: counts[name] for name in ("active", "accepted", "rejected", "unknown")},
            "proposals": proposals,
            "warnings": list(self.warnings),
        }
        if include_raw:
            output["raw_renders"] = self.raw_renders
        return output


def _text(value: str, limit: int = MAX_TEXT_CHARS) -> str:
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\x00", "").strip()[:limit]


def _unescape_markdown_text(value: str) -> str:
    """Remove backslashes only before bounded ASCII Markdown punctuation."""
    normalized = _text(value, 1000)
    result: list[str] = []
    index = 0
    while index < len(normalized):
        if (normalized[index] == "\\" and index + 1 < len(normalized)
                and normalized[index + 1] in _MARKDOWN_ESCAPABLE):
            index += 1
        result.append(normalized[index])
        index += 1
    return _text("".join(result), 1000)


def _display(value: str) -> tuple[str | None, str | None]:
    value = _text(value, 1000)
    link = re.fullmatch(r"\[([^]]+)\]\([^)]+\)", value)
    display = _text(link.group(1) if link else value, 1000) or None
    address = _ADDRESS.search(value)
    return display, address.group(0) if address else None


def _list_status(value: str) -> tuple[str, str | None]:
    status = value.strip().upper()
    if status in {"ACTIVE", "ACCEPTED", "REJECTED"}:
        return status, None
    return "UNKNOWN", f"Unknown governance status: {_text(value, 100)}"


def parse_proposal_list(render: str) -> tuple[list[GovernanceProposalSummary], list[str]]:
    lines = _lines(render)
    starts = [(index, match) for index, line in enumerate(lines) if (match := _HEADER.match(line.strip()))]
    proposals: list[GovernanceProposalSummary] = []
    warnings: list[str] = []
    for position, (start, match) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        values: dict[str, str] = {}
        for line in lines[start + 1:end]:
            if field_match := _LIST_FIELD.match(line.strip()):
                values[field_match.group(1).lower()] = field_match.group(2)
        if "status" not in values:
            raise GovernanceParseError(f"Proposal {match.group(1)} has no status")
        status, warning = _list_status(values["status"])
        if warning:
            warnings.append(warning)
        author, address = _display(values.get("author", ""))
        tiers = _tiers(values.get("tiers eligible to vote", ""))
        proposals.append(GovernanceProposalSummary(
            int(match.group(1)), _unescape_markdown_text(match.group(2)), author, address,
            status, tiers, (warning,) if warning else (),
        ))
    seen: dict[int, GovernanceProposalSummary] = {}
    for proposal in proposals:
        previous = seen.get(proposal.proposal_id)
        if previous is not None and previous != proposal:
            raise GovernanceParseError(f"Conflicting duplicate proposal ID {proposal.proposal_id}")
        seen[proposal.proposal_id] = proposal
    return list(seen.values()), warnings[:MAX_WARNINGS]


def pager_paths(render: str, realm: str) -> list[str]:
    _validate_size(render)
    pattern = re.compile(r"^(?:" + re.escape(realm) + r":)?\?page=([1-9][0-9]*)$")
    paths: list[str] = []
    for target in _LINK.findall(render):
        if match := pattern.fullmatch(target.strip()):
            paths.append("" if match.group(1) == "1" else f"?page={match.group(1)}")
    return list(dict.fromkeys(paths))


def parse_detail(render: str, requested_id: int) -> dict:
    lines = _lines(render)
    header_index = next((index for index, line in enumerate(lines) if _HEADER.match(line.strip())), None)
    if header_index is None:
        raise GovernanceParseError(f"Proposal {requested_id} detail has no ID/title")
    header = _HEADER.match(lines[header_index].strip())
    assert header is not None
    if int(header.group(1)) != requested_id:
        raise GovernanceParseError(f"Proposal detail ID does not match requested ID {requested_id}")

    author = address = None
    for line in lines[header_index + 1:]:
        if match := _LIST_FIELD.match(line.strip()):
            if match.group(1).lower() == "author":
                author, address = _display(match.group(2))
                break

    stats_index = next((index for index in range(len(lines) - 1, header_index, -1)
                        if lines[index].strip().casefold() == "### stats"), None)
    stats_separator = None
    if stats_index is not None:
        stats_separator = next((index for index in range(stats_index - 1, header_index, -1)
                                if lines[index].strip() == "---"), None)
    stats_end = len(lines)
    if stats_index is not None:
        stats_end = next((index for index in range(stats_index + 1, len(lines))
                          if lines[index].strip() == "---"
                          or re.match(r"^\[Detailed voting list\]", lines[index].strip(), re.I)), len(lines))
    stats_lines = lines[stats_index + 1:stats_end] if stats_index is not None else []

    metadata_index = next((index for index, line in enumerate(lines[header_index + 1:], header_index + 1)
                           if line.strip() == "This proposal contains the following metadata:"), None)
    body_start = header_index + 1
    while body_start < len(lines) and (not lines[body_start].strip() or _LIST_FIELD.match(lines[body_start].strip())):
        body_start += 1
    if metadata_index is not None:
        body_end = metadata_index
    elif stats_separator is not None:
        body_end = stats_separator
    elif stats_index is not None:
        body_end = stats_index
    else:
        body_end = len(lines)
    description = _text("\n".join(lines[body_start:body_end]))

    executor_text = None
    executor_realm = None
    if metadata_index is not None:
        metadata_end = stats_separator if stats_separator is not None and stats_separator > metadata_index else len(lines)
        executor_lines: list[str] = []
        for line in lines[metadata_index + 1:metadata_end]:
            if line.strip().startswith("Executor created in:"):
                executor_realm = _text(line.strip().split(":", 1)[1], 1000) or None
                continue
            executor_lines.append(line)
        executor_text = _text("\n".join(executor_lines)) or None

    stats_text = "\n".join(stats_lines)
    if re.search(r"PROPOSAL HAS BEEN ACCEPTED", stats_text, re.I):
        status = "ACCEPTED"
    elif re.search(r"PROPOSAL HAS BEEN DENIED", stats_text, re.I):
        status = "REJECTED"
    elif re.search(r"Proposal is open for votes", stats_text, re.I):
        status = "ACTIVE"
    else:
        status = "UNKNOWN"

    warnings: list[str] = []
    if status == "UNKNOWN":
        warnings.append("Official proposal status section was not recognized")
    tiers = ()
    rejection_reason = None
    percentages: dict[str, float | None] = {"YES": None, "NO": None, "ABSTAIN": None}
    for line in stats_lines:
        stripped = line.strip()
        if match := _LIST_FIELD.match(stripped):
            if match.group(1).lower() == "tiers eligible to vote":
                tiers = _tiers(match.group(2))
        reason_match = re.match(r"^(?:[-*]\s+)?REASON:\s*(.*)$", stripped, re.I)
        if reason_match:
            rejection_reason = _text(reason_match.group(1), 10_000) or None
        if match := _PERCENT.match(stripped):
            raw = match.group(2)
            try:
                value = float(raw[:-1].strip()) if raw.endswith("%") else math.nan
            except ValueError:
                value = math.nan
            if math.isfinite(value) and 0 <= value <= 100:
                percentages[match.group(1).upper()] = value
            else:
                warnings.append(f"Invalid {match.group(1).upper()} percentage")
    return {
        "proposal_id": requested_id,
        "title": _unescape_markdown_text(header.group(2)),
        "author_display": author,
        "author_address": address,
        "status": status,
        "eligible_tiers": tiers,
        "description": description,
        "executor_text": executor_text,
        "executor_creation_realm": executor_realm,
        "rejection_reason": rejection_reason,
        "yes_percent": percentages["YES"],
        "no_percent": percentages["NO"],
        "abstain_percent": percentages["ABSTAIN"],
        "detail_parse_status": "parsed" if status != "UNKNOWN" else "partial",
        "warnings": warnings[:MAX_WARNINGS],
    }


def parse_votes(render: str) -> tuple[str, tuple[GovernanceVote, ...], list[str]]:
    lines = _lines(render)
    content_lines = [line.strip() for line in lines
                     if line.strip()
                     and not re.fullmatch(r"#\s+Proposal\s+#[0-9]+\s+-\s+Vote List", line.strip(), re.I)]
    if len(content_lines) == 1 and re.fullmatch(
        r"(?:No one voted yet\.?|No votes\.?|No vote has been cast\.?)", content_lines[0], re.I
    ):
        return "empty", (), []
    votes: list[GovernanceVote] = []
    group: tuple[str, str, str] | None = None
    invalid = False
    for line in lines:
        stripped = line.strip()
        if not stripped or re.fullmatch(r"#\s+Proposal\s+#[0-9]+\s+-\s+Vote List", stripped, re.I):
            continue
        if match := _VOTE_GROUP.fullmatch(stripped):
            group = (match.group(1).upper(), _text(match.group(2), 100), _text(match.group(3), 100))
            continue
        if stripped.startswith(("- ", "* ")) and group:
            voter = stripped[2:].strip()
            display, address = _display(voter)
            if display:
                votes.append(GovernanceVote(display, address, *group))
                continue
        invalid = True
    if votes and not invalid:
        return "parsed", tuple(votes), []
    return "unparsed", (), ["Votes render format was not recognized"]


def discover_governance(
    client: GnoRpcClient,
    source: GovernanceSource,
    max_pages: int = MAX_GOVERNANCE_PAGES,
    max_proposals: int = MAX_GOVERNANCE_PROPOSALS,
    proposal_id: int | None = None,
    capture_raw: bool = False,
    raw_sink: Callable[[str, str], None] | None = None,
) -> GovernanceDiscovery:
    if not 1 <= max_pages <= MAX_GOVERNANCE_PAGES or not 1 <= max_proposals <= MAX_GOVERNANCE_PROPOSALS:
        raise GovernanceParseError("Discovery limits exceed hard safety limits")
    raw: dict[str, str] = {}
    raw_bytes = 0

    def fetch(name: str, path: str) -> str:
        nonlocal raw_bytes
        render = client.abci_query("vm/qrender", f"{source.realm_path}:{path}", height=source.observed_height)
        _validate_size(render)
        if raw_sink:
            raw_sink(name, render)
        if capture_raw:
            raw_bytes += len(render.encode("utf-8"))
            if raw_bytes > MAX_TOTAL_RAW_BYTES:
                raise GovernanceParseError("Captured raw renders exceed total size limit")
            raw[name] = render
        return render

    warnings: list[str] = []
    summaries: dict[int, GovernanceProposalSummary | None] = {}
    page_count, complete = 0, True
    if proposal_id is not None:
        summaries[proposal_id] = None
    else:
        queue, visited = deque([""]), set()
        while queue:
            path = queue.popleft()
            if path in visited:
                continue
            if page_count >= max_pages:
                complete = False
                warnings.append("Governance page limit reached")
                break
            visited.add(path)
            render = fetch(f"list/{path or 'root'}", path)
            page_count += 1
            parsed, page_warnings = parse_proposal_list(render)
            warnings.extend(page_warnings)
            for item in parsed:
                old = summaries.get(item.proposal_id)
                if old is not None and old != item:
                    raise GovernanceParseError(f"Conflicting duplicate proposal ID {item.proposal_id}")
                summaries[item.proposal_id] = item
            if len(summaries) > max_proposals:
                raise GovernanceParseError("Governance proposal limit exceeded")
            pages = pager_paths(render, source.realm_path)
            queue.extend(page for page in pages if page not in visited)
            if not pages and path == "" and len(parsed) >= 5:
                complete = False
                warnings.append("Pagination format was not recognized; list may be incomplete")

    details: list[GovernanceProposalDetail] = []
    for proposal_id_value in sorted(summaries, reverse=True):
        summary = summaries[proposal_id_value]
        detail = parse_detail(fetch(f"proposal/{proposal_id_value}", str(proposal_id_value)), proposal_id_value)
        vote_status, votes, vote_warnings = parse_votes(fetch(f"proposal/{proposal_id_value}/votes", f"{proposal_id_value}/votes"))
        detail_warnings = list(detail["warnings"]) + vote_warnings
        if summary:
            if (_unescape_markdown_text(summary.title).casefold()
                    != _unescape_markdown_text(detail["title"]).casefold()):
                detail_warnings.append("Proposal title differs between list and detail renders")
            if detail["status"] == "UNKNOWN":
                detail["status"] = summary.status
            elif summary.status != "UNKNOWN" and summary.status != detail["status"]:
                detail_warnings.append("Proposal status differs between list and detail renders")
            if not detail["eligible_tiers"]:
                detail["eligible_tiers"] = summary.eligible_tiers
            elif summary.eligible_tiers and summary.eligible_tiers != detail["eligible_tiers"]:
                detail_warnings.append("Eligible tiers differ between list and detail renders")
            if detail["author_display"] is None:
                detail["author_display"] = summary.author_display
                detail["author_address"] = summary.author_address
        details.append(GovernanceProposalDetail(
            **{key: detail[key] for key in (
                "proposal_id", "title", "author_display", "author_address", "status", "eligible_tiers",
                "description", "executor_text", "executor_creation_realm", "rejection_reason",
                "yes_percent", "no_percent", "abstain_percent", "detail_parse_status",
            )},
            votes_parse_status=vote_status,
            votes=votes,
            parse_warnings=tuple(detail_warnings[:MAX_WARNINGS]),
        ))
    return GovernanceDiscovery(source, complete, page_count, tuple(details), tuple(warnings[:MAX_WARNINGS]), raw)


def _tiers(value: str) -> tuple[str, ...]:
    return tuple(part.strip().upper() for part in value.split(",") if part.strip())


def _lines(render: str) -> list[str]:
    _validate_size(render)
    return render.replace("\r\n", "\n").replace("\r", "\n").split("\n")


def _validate_size(render: str) -> None:
    if not isinstance(render, str):
        raise GovernanceParseError("Render must be text")
    if len(render.encode("utf-8")) > MAX_RENDER_BYTES:
        raise GovernanceParseError("Governance render exceeds size limit")
