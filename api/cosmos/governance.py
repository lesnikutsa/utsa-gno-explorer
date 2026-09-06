"""Request-driven Cosmos governance proposal normalization.

Governance state is queried from the Cosmos SDK LCD/API and does not depend on
historical block retention. The loader follows bounded SDK pagination and keeps
AtomOne-specific proposal messages compatible with generic Cosmos networks.
"""

import re
from typing import Literal

from pydantic import Field

from .errors import MalformedUpstreamResponse
from .schemas import AmountString, StrictModel


GovernanceStatus = Literal["deposit", "voting", "passed", "rejected", "failed", "unknown"]

_STATUS = {
    "PROPOSAL_STATUS_DEPOSIT_PERIOD": "deposit",
    "PROPOSAL_STATUS_VOTING_PERIOD": "voting",
    "PROPOSAL_STATUS_PASSED": "passed",
    "PROPOSAL_STATUS_REJECTED": "rejected",
    "PROPOSAL_STATUS_FAILED": "failed",
}

_TYPE_LABELS = {
    "MsgSoftwareUpgrade": "Upgrade",
    "MsgCancelUpgrade": "Cancel upgrade",
    "MsgUpdateParams": "Params",
    "MsgCommunityPoolSpend": "Community spend",
    "MsgExecLegacyContent": "Legacy exec",
    "MsgProposeConstitutionAmendment": "Constitution",
}


class CosmosGovernanceTally(StrictModel):
    yes: AmountString
    no: AmountString
    no_with_veto: AmountString
    abstain: AmountString


class CosmosGovernanceProposal(StrictModel):
    proposal_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=512)
    proposal_type: str = Field(min_length=1, max_length=80)
    message_type: str | None = Field(default=None, max_length=256)
    status: GovernanceStatus
    proposer: str | None = Field(default=None, max_length=128)
    submit_time: str | None = Field(default=None, max_length=64)
    voting_start_time: str | None = Field(default=None, max_length=64)
    voting_end_time: str | None = Field(default=None, max_length=64)
    tally: CosmosGovernanceTally


class CosmosGovernanceSummary(StrictModel):
    total: int = Field(ge=0, le=2000)
    deposit: int = Field(ge=0, le=2000)
    voting: int = Field(ge=0, le=2000)
    passed: int = Field(ge=0, le=2000)
    rejected: int = Field(ge=0, le=2000)
    failed: int = Field(ge=0, le=2000)
    unknown: int = Field(ge=0, le=2000)


class CosmosGovernancePageResponse(StrictModel):
    network_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    summary: CosmosGovernanceSummary
    proposals: list[CosmosGovernanceProposal] = Field(max_length=2000)


def _mapping(value, name: str) -> dict:
    if not isinstance(value, dict) or len(value) > 256:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _text(value, name: str, maximum: int, *, required: bool = True) -> str | None:
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise MalformedUpstreamResponse(f"invalid {name}")
    value = value.strip()
    if (required and not value) or len(value) > maximum or not value.isprintable():
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value or None


def _amount(value, name: str, *, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value or len(value) > 128 or not value.isdigit():
        raise MalformedUpstreamResponse(f"invalid {name}")
    return str(int(value))


def _proposal_id(value) -> int:
    if isinstance(value, bool):
        raise MalformedUpstreamResponse("invalid proposal id")
    try:
        proposal_id = int(value)
    except (TypeError, ValueError):
        raise MalformedUpstreamResponse("invalid proposal id") from None
    if proposal_id <= 0:
        raise MalformedUpstreamResponse("invalid proposal id")
    return proposal_id


def _humanize_message_type(type_url: str | None) -> str:
    if not type_url:
        return "Other"
    name = type_url.rsplit(".", 1)[-1]
    if name in _TYPE_LABELS:
        return _TYPE_LABELS[name]
    if name.startswith("Msg"):
        name = name[3:]
    words = re.sub(r"(?<!^)(?=[A-Z])", " ", name).strip()
    return words[:80] or "Other"


def _normalize_proposal(raw) -> dict:
    proposal = _mapping(raw, "governance proposal")
    proposal_id = _proposal_id(proposal.get("id"))
    raw_title = proposal.get("title")
    title = raw_title.strip() if isinstance(raw_title, str) else ""
    if not title:
        summary = proposal.get("summary")
        title = summary.strip().splitlines()[0][:512] if isinstance(summary, str) and summary.strip() else f"Proposal #{proposal_id}"
    if len(title) > 512 or not title.isprintable():
        raise MalformedUpstreamResponse("invalid proposal title")

    messages = proposal.get("messages") or []
    if not isinstance(messages, list) or len(messages) > 128:
        raise MalformedUpstreamResponse("invalid proposal messages")
    first = messages[0] if messages else {}
    if first and not isinstance(first, dict):
        raise MalformedUpstreamResponse("invalid proposal message")
    raw_type = first.get("@type") if isinstance(first, dict) else None
    message_type = _text(raw_type, "proposal message type", 256, required=False)

    raw_status = proposal.get("status")
    status = _STATUS.get(raw_status, "unknown") if isinstance(raw_status, str) else "unknown"
    tally = proposal.get("final_tally_result") or {}
    tally = _mapping(tally, "proposal tally")

    normalized = {
        "proposal_id": proposal_id,
        "title": title,
        "proposal_type": _humanize_message_type(message_type),
        "message_type": message_type,
        "status": status,
        "proposer": _text(proposal.get("proposer"), "proposal proposer", 128, required=False),
        "submit_time": _text(proposal.get("submit_time"), "proposal submit time", 64, required=False),
        "voting_start_time": _text(proposal.get("voting_start_time"), "proposal voting start", 64, required=False),
        "voting_end_time": _text(proposal.get("voting_end_time"), "proposal voting end", 64, required=False),
        "tally": {
            "yes": _amount(tally.get("yes_count"), "yes tally", default="0"),
            "no": _amount(tally.get("no_count"), "no tally", default="0"),
            "no_with_veto": _amount(tally.get("no_with_veto_count"), "veto tally", default="0"),
            "abstain": _amount(tally.get("abstain_count"), "abstain tally", default="0"),
        },
    }
    return CosmosGovernanceProposal.model_validate(normalized).model_dump()


async def load_governance_page(service) -> CosmosGovernancePageResponse:
    """Load every proposal available from bounded Cosmos SDK pagination."""
    rows = await service._paginate(
        "governance_proposals",
        "/cosmos/gov/v1/proposals?pagination.reverse=true",
        "proposals",
    )
    proposals = [_normalize_proposal(row) for row in rows]
    proposals.sort(key=lambda item: item["proposal_id"], reverse=True)

    counts = {name: 0 for name in ("deposit", "voting", "passed", "rejected", "failed", "unknown")}
    for proposal in proposals:
        counts[proposal["status"]] += 1

    return CosmosGovernancePageResponse.model_validate({
        "network_id": service.definition.transport.network_id,
        "summary": {"total": len(proposals), **counts},
        "proposals": proposals,
    })
