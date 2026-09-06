"""Request-driven Cosmos governance proposal normalization.

Governance state is queried from the Cosmos SDK LCD/API and does not depend on
historical block retention. The loaders follow bounded SDK pagination and keep
AtomOne-specific proposal messages compatible with generic Cosmos networks.
"""

import asyncio
import json
import re
from typing import Literal

from pydantic import Field

from .errors import MalformedUpstreamResponse
from .schemas import AmountString, StrictModel


GovernanceStatus = Literal["deposit", "voting", "passed", "rejected", "failed", "unknown"]
GovernanceVoteOption = Literal["yes", "no", "no_with_veto", "abstain", "unspecified"]

_STATUS = {
    "PROPOSAL_STATUS_DEPOSIT_PERIOD": "deposit",
    "PROPOSAL_STATUS_VOTING_PERIOD": "voting",
    "PROPOSAL_STATUS_PASSED": "passed",
    "PROPOSAL_STATUS_REJECTED": "rejected",
    "PROPOSAL_STATUS_FAILED": "failed",
}

_VOTE_OPTIONS = {
    "VOTE_OPTION_YES": "yes",
    "VOTE_OPTION_NO": "no",
    "VOTE_OPTION_NO_WITH_VETO": "no_with_veto",
    "VOTE_OPTION_ABSTAIN": "abstain",
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
    deposit_end_time: str | None = Field(default=None, max_length=64)
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


class CosmosGovernanceCoin(StrictModel):
    denom: str = Field(min_length=1, max_length=128)
    amount: AmountString


class CosmosGovernanceMessage(StrictModel):
    message_type: str | None = Field(default=None, max_length=256)
    content: str = Field(min_length=2, max_length=16000)


class CosmosGovernanceDetailResponse(StrictModel):
    network_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    proposal: CosmosGovernanceProposal
    summary: str | None = Field(default=None, max_length=20000)
    metadata: str | None = Field(default=None, max_length=4096)
    total_deposit: list[CosmosGovernanceCoin] = Field(max_length=64)
    messages: list[CosmosGovernanceMessage] = Field(max_length=32)


class CosmosGovernanceVoteChoice(StrictModel):
    option: GovernanceVoteOption
    weight: str = Field(min_length=1, max_length=64, pattern=r"^[0-9]+(?:\.[0-9]+)?$")


class CosmosGovernanceVote(StrictModel):
    voter: str = Field(min_length=1, max_length=128)
    options: list[CosmosGovernanceVoteChoice] = Field(min_length=1, max_length=16)


class CosmosGovernanceVotesResponse(StrictModel):
    network_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    proposal_id: int = Field(gt=0)
    total: int = Field(ge=0, le=2000)
    votes: list[CosmosGovernanceVote] = Field(max_length=2000)


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


def _long_text(value, name: str, maximum: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum:
        raise MalformedUpstreamResponse(f"invalid {name}")
    value = value.strip()
    if not value:
        return None
    if any(ord(char) < 32 and char not in "\n\r\t" for char in value):
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _amount(value, name: str, *, default: str | None = None) -> str:
    if value is None and default is not None:
        return default
    if not isinstance(value, str) or not value or len(value) > 128 or not value.isdigit():
        raise MalformedUpstreamResponse(f"invalid {name}")
    return str(int(value))


def _weight(value, name: str) -> str:
    if not isinstance(value, str) or len(value) > 64 or re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) is None:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


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


def _normalize_tally(raw) -> dict:
    tally = _mapping(raw or {}, "proposal tally")
    return {
        "yes": _amount(tally.get("yes_count"), "yes tally", default="0"),
        "no": _amount(tally.get("no_count"), "no tally", default="0"),
        "no_with_veto": _amount(tally.get("no_with_veto_count"), "veto tally", default="0"),
        "abstain": _amount(tally.get("abstain_count"), "abstain tally", default="0"),
    }


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

    normalized = {
        "proposal_id": proposal_id,
        "title": title,
        "proposal_type": _humanize_message_type(message_type),
        "message_type": message_type,
        "status": status,
        "proposer": _text(proposal.get("proposer"), "proposal proposer", 128, required=False),
        "submit_time": _text(proposal.get("submit_time"), "proposal submit time", 64, required=False),
        "deposit_end_time": _text(proposal.get("deposit_end_time"), "proposal deposit end", 64, required=False),
        "voting_start_time": _text(proposal.get("voting_start_time"), "proposal voting start", 64, required=False),
        "voting_end_time": _text(proposal.get("voting_end_time"), "proposal voting end", 64, required=False),
        "tally": _normalize_tally(proposal.get("final_tally_result") or {}),
    }
    return CosmosGovernanceProposal.model_validate(normalized).model_dump()


def _normalize_coin(raw, name: str) -> dict:
    coin = _mapping(raw, name)
    return CosmosGovernanceCoin.model_validate({
        "denom": _text(coin.get("denom"), f"{name} denom", 128),
        "amount": _amount(coin.get("amount"), f"{name} amount"),
    }).model_dump()


def _normalize_message(raw) -> dict:
    message = _mapping(raw, "governance message")
    message_type = _text(message.get("@type"), "governance message type", 256, required=False)
    try:
        content = json.dumps(message, ensure_ascii=False, indent=2, sort_keys=True)
    except (TypeError, ValueError):
        raise MalformedUpstreamResponse("invalid governance message") from None
    if len(content) > 15999:
        content = content[:15998] + "…"
    return CosmosGovernanceMessage.model_validate({"message_type": message_type, "content": content}).model_dump()


def _normalize_vote(raw, proposal_id: int) -> dict:
    vote = _mapping(raw, "governance vote")
    raw_id = vote.get("proposal_id")
    if raw_id is not None and _proposal_id(raw_id) != proposal_id:
        raise MalformedUpstreamResponse("governance vote proposal mismatch")
    voter = _text(vote.get("voter"), "governance voter", 128)
    raw_options = vote.get("options")
    if raw_options is None and vote.get("option") is not None:
        raw_options = [{"option": vote.get("option"), "weight": "1"}]
    if not isinstance(raw_options, list) or not 1 <= len(raw_options) <= 16:
        raise MalformedUpstreamResponse("invalid governance vote options")
    options = []
    for raw_option in raw_options:
        option = _mapping(raw_option, "governance vote option")
        raw_name = option.get("option")
        normalized_name = _VOTE_OPTIONS.get(raw_name, "unspecified") if isinstance(raw_name, str) else "unspecified"
        options.append({"option": normalized_name, "weight": _weight(option.get("weight") or "1", "governance vote weight")})
    return CosmosGovernanceVote.model_validate({"voter": voter, "options": options}).model_dump()


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


async def load_governance_detail(service, proposal_id: int) -> CosmosGovernanceDetailResponse:
    """Load one proposal and a live tally when the upstream exposes one."""
    proposal_id = _proposal_id(proposal_id)
    proposal_payload, tally_payload = await asyncio.gather(
        service._rest(
            f"governance_proposal_{proposal_id}",
            f"/cosmos/gov/v1/proposals/{proposal_id}",
        ),
        service._rest(
            f"governance_tally_{proposal_id}",
            f"/cosmos/gov/v1/proposals/{proposal_id}/tally",
        ),
        return_exceptions=True,
    )
    if isinstance(proposal_payload, BaseException):
        raise proposal_payload
    payload = _mapping(proposal_payload, "governance proposal response")
    raw = _mapping(payload.get("proposal"), "governance proposal")
    normalized = _normalize_proposal(raw)
    if normalized["proposal_id"] != proposal_id:
        raise MalformedUpstreamResponse("governance proposal id mismatch")

    if isinstance(tally_payload, dict):
        try:
            normalized["tally"] = _normalize_tally(tally_payload.get("tally") or {})
        except MalformedUpstreamResponse:
            pass

    raw_deposit = raw.get("total_deposit") or []
    if not isinstance(raw_deposit, list) or len(raw_deposit) > 64:
        raise MalformedUpstreamResponse("invalid governance total deposit")
    raw_messages = raw.get("messages") or []
    if not isinstance(raw_messages, list) or len(raw_messages) > 128:
        raise MalformedUpstreamResponse("invalid governance messages")

    return CosmosGovernanceDetailResponse.model_validate({
        "network_id": service.definition.transport.network_id,
        "proposal": normalized,
        "summary": _long_text(raw.get("summary"), "proposal summary", 20000),
        "metadata": _long_text(raw.get("metadata"), "proposal metadata", 4096),
        "total_deposit": [_normalize_coin(item, "proposal deposit") for item in raw_deposit],
        "messages": [_normalize_message(item) for item in raw_messages[:32]],
    })


async def load_governance_votes(service, proposal_id: int) -> CosmosGovernanceVotesResponse:
    """Load the bounded voter list only when the detail page asks for it."""
    proposal_id = _proposal_id(proposal_id)
    rows = await service._paginate(
        f"governance_votes_{proposal_id}",
        f"/cosmos/gov/v1/proposals/{proposal_id}/votes",
        "votes",
    )
    votes = [_normalize_vote(row, proposal_id) for row in rows]
    return CosmosGovernanceVotesResponse.model_validate({
        "network_id": service.definition.transport.network_id,
        "proposal_id": proposal_id,
        "total": len(votes),
        "votes": votes,
    })
