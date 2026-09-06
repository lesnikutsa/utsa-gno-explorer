"""Live, bounded Cosmos/CometBFT consensus diagnostics."""

import asyncio
import base64
from datetime import datetime, timezone
import hashlib
import re

from pydantic import Field

from .errors import AllEndpointsUnavailable, MalformedUpstreamResponse
from .schemas import StrictModel


CURRENT_TTL = 0.8
VALIDATOR_SET_TTL = 15.0
RPC_VIEWS_TTL = 5.0
MAX_VALIDATORS = 2000
_QUORUM = 66.6666667
_HEX = re.compile(r"^[0-9A-Fa-f]{6,128}$")
_STEP_LABELS = {
    0: "Unknown",
    1: "New height",
    2: "New round",
    3: "Propose",
    4: "Prevote",
    5: "Prevote wait",
    6: "Precommit",
    7: "Precommit wait",
    8: "Commit",
}


class ConsensusHashGroup(StrictModel):
    hash: str = Field(min_length=1, max_length=128)
    voting_power: int = Field(ge=0)
    percent: float = Field(ge=0, le=100)


class ConsensusValidatorVote(StrictModel):
    consensus_address: str = Field(min_length=1, max_length=128)
    operator_address: str | None = Field(default=None, max_length=90)
    moniker: str = Field(min_length=1, max_length=256)
    voting_power: int = Field(ge=0)
    voting_power_percent: float = Field(ge=0, le=100)
    proposer: bool
    prevote: str = Field(pattern=r"^(signed|nil|missing|unknown)$")
    prevote_hash: str | None = Field(default=None, max_length=128)
    precommit: str = Field(pattern=r"^(signed|nil|missing|unknown)$")
    precommit_hash: str | None = Field(default=None, max_length=128)


class ConsensusRpcView(StrictModel):
    provider: str = Field(min_length=1, max_length=64)
    status: str = Field(pattern=r"^(healthy|lagging|catching_up|unavailable)$")
    height: int | None = Field(default=None, ge=0)
    block_hash: str | None = Field(default=None, max_length=128)


class CosmosConsensusResponse(StrictModel):
    network_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
    chain_id: str = Field(min_length=1, max_length=128)
    height: int = Field(ge=1)
    round: int = Field(ge=0)
    step: int = Field(ge=0)
    step_label: str = Field(min_length=1, max_length=32)
    start_time: str | None = Field(default=None, max_length=64)
    updated_at: str = Field(min_length=20, max_length=64)
    proposer_address: str | None = Field(default=None, max_length=128)
    proposer_moniker: str | None = Field(default=None, max_length=256)
    total_voting_power: int = Field(ge=0)
    prevote_power_percent: float = Field(ge=0, le=100)
    precommit_power_percent: float = Field(ge=0, le=100)
    prevote_quorum: bool
    precommit_quorum: bool
    prevote_hashes: list[ConsensusHashGroup] = Field(max_length=64)
    precommit_hashes: list[ConsensusHashGroup] = Field(max_length=64)
    prevote_missing_percent: float = Field(ge=0, le=100)
    precommit_missing_percent: float = Field(ge=0, le=100)
    competing_prevote_hashes: bool
    competing_precommit_hashes: bool
    proposal_block_hash: str | None = Field(default=None, max_length=128)
    locked_block_hash: str | None = Field(default=None, max_length=128)
    valid_block_hash: str | None = Field(default=None, max_length=128)
    validators: list[ConsensusValidatorVote] = Field(max_length=MAX_VALIDATORS)
    rpc_views: list[ConsensusRpcView] = Field(max_length=32)
    rpc_height_spread: int = Field(ge=0)
    rpc_diverged: bool


def _mapping(value, name="object"):
    if not isinstance(value, dict) or len(value) > 512:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return value


def _integer(value, name, *, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise MalformedUpstreamResponse(f"invalid {name}")
    if isinstance(value, str) and (not value.isascii() or not value.isdigit() or len(value) > 20):
        raise MalformedUpstreamResponse(f"invalid {name}")
    result = int(value)
    if result < minimum or result > 9_223_372_036_854_775_807:
        raise MalformedUpstreamResponse(f"invalid {name}")
    return result


def _safe_hash(value):
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > 128 or _HEX.fullmatch(text) is None:
        return None
    return text.upper()


def _vote(value, marker):
    if not isinstance(value, str) or len(value) > 4096:
        return "unknown", None
    text = value.strip()
    if not text or text.lower() == "nil-vote":
        return "missing", None
    token = None
    needle = f"({marker})"
    if needle in text:
        tail = text.split(needle, 1)[1].split("@", 1)[0].strip()
        if tail:
            token = tail.split()[0].strip("{},")
    if token is None:
        candidates = re.findall(r"\b[0-9A-Fa-f]{6,128}\b", text)
        token = candidates[-1] if candidates else None
    if token is not None and token.lower() in {"nil", "<nil>"}:
        return "nil", None
    vote_hash = _safe_hash(token)
    if vote_hash:
        return "signed", vote_hash
    if re.search(r"(?:^|\s)(?:nil|<nil>)(?:\s|$)", text, re.IGNORECASE):
        return "nil", None
    return "unknown", None


def _round_state(payload):
    root = _mapping(payload, "consensus payload")
    result = _mapping(root.get("result"), "consensus result")
    return _mapping(result.get("round_state"), "round state")


def _height_round_step(state):
    raw = state.get("height/round/step")
    if isinstance(raw, str):
        parts = raw.split("/")
        if len(parts) == 3:
            return (_integer(parts[0], "height", minimum=1),
                    _integer(parts[1], "round"), _integer(parts[2], "step"))
    return (_integer(state.get("height"), "height", minimum=1),
            _integer(state.get("round"), "round"), _integer(state.get("step"), "step"))


def _active_round_votes(state, round_number):
    rows = state.get("height_vote_set")
    if not isinstance(rows, list) or len(rows) > 128:
        return [], []
    chosen = None
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            row_round = _integer(row.get("round"), "vote round")
        except MalformedUpstreamResponse:
            continue
        if row_round == round_number:
            chosen = row
            break
    if chosen is None:
        return [], []
    prevotes = chosen.get("prevotes")
    precommits = chosen.get("precommits")
    return (prevotes if isinstance(prevotes, list) else [],
            precommits if isinstance(precommits, list) else [])


def _pubkey_hex(public_key):
    if not isinstance(public_key, dict):
        return None
    encoded = public_key.get("value") or public_key.get("key")
    if not isinstance(encoded, str) or len(encoded) > 256:
        return None
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        return None
    if len(raw) != 32:
        return None
    return hashlib.sha256(raw).digest()[:20].hex().upper()


def _staking_identities(rows):
    identities = {}
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        key = _pubkey_hex(row.get("consensus_pubkey") or row.get("consensus_pub_key"))
        if not key:
            continue
        description = row.get("description") if isinstance(row.get("description"), dict) else {}
        moniker = description.get("moniker")
        operator = row.get("operator_address")
        identities[key] = {
            "moniker": moniker.strip()[:256] if isinstance(moniker, str) and moniker.strip() else key[:12],
            "operator_address": operator if isinstance(operator, str) and len(operator) <= 90 else None,
        }
    return identities


def _dump_validators(state):
    section = state.get("validators")
    if not isinstance(section, dict):
        return [], None
    rows = section.get("validators")
    if not isinstance(rows, list) or len(rows) > MAX_VALIDATORS:
        return [], None
    proposer = section.get("proposer") if isinstance(section.get("proposer"), dict) else None
    proposer_address = _safe_hash(proposer.get("address")) if proposer else None
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        address = _safe_hash(row.get("address"))
        if not address:
            continue
        try:
            power = _integer(row.get("voting_power"), "voting power")
        except MalformedUpstreamResponse:
            continue
        result.append({"address": address, "voting_power": power})
    return result, proposer_address


async def _rpc_payload(service, name, path, ttl):
    key = (service.definition.transport.network_id, "consensus_rpc", (name, path))

    async def load():
        candidates = await service.adapter._cached_candidates("rpc")
        for candidate in candidates:
            try:
                payload = await service.adapter._transport.get_object(candidate.endpoint, path, accept_error_payload=True)
                if isinstance(payload, dict) and not isinstance(payload.get("error"), dict):
                    return payload
            except Exception:
                continue
        raise AllEndpointsUnavailable("consensus RPC unavailable")

    return await service.cache.get_or_load(key, ttl, load)


async def _validator_set_fallback(service):
    payload = await _rpc_payload(service, "validator_set", "/validators?per_page=100&page=1", VALIDATOR_SET_TTL)
    result = _mapping(payload.get("result"), "validator set result")
    rows = result.get("validators")
    if not isinstance(rows, list) or len(rows) > 100:
        raise MalformedUpstreamResponse("invalid validator set")
    total = _integer(result.get("total", len(rows)), "validator set total")
    if total > MAX_VALIDATORS:
        raise MalformedUpstreamResponse("validator set too large")
    combined = list(rows)
    pages = (total + 99) // 100
    for page in range(2, pages + 1):
        payload = await _rpc_payload(service, f"validator_set_{page}", f"/validators?per_page=100&page={page}", VALIDATOR_SET_TTL)
        result = _mapping(payload.get("result"), "validator set result")
        page_rows = result.get("validators")
        if not isinstance(page_rows, list) or len(page_rows) > 100:
            raise MalformedUpstreamResponse("invalid validator set page")
        combined.extend(page_rows)
    normalized = []
    for row in combined[:MAX_VALIDATORS]:
        if not isinstance(row, dict):
            continue
        address = _safe_hash(row.get("address"))
        if not address:
            continue
        try:
            power = _integer(row.get("voting_power"), "voting power")
        except MalformedUpstreamResponse:
            continue
        normalized.append({"address": address, "voting_power": power})
    return normalized


def _aggregate_hashes(validators, field, total_power):
    groups = {}
    voted_power = 0
    missing_power = 0
    for validator in validators:
        state = validator[field]
        power = validator["voting_power"]
        vote_hash = validator[f"{field}_hash"]
        if state == "missing" or state == "unknown":
            missing_power += power
            continue
        voted_power += power
        label = vote_hash if state == "signed" and vote_hash else "NIL"
        groups[label] = groups.get(label, 0) + power
    denom = total_power or 1
    rows = [
        {"hash": key, "voting_power": power, "percent": round(min(100.0, power * 100.0 / denom), 4)}
        for key, power in groups.items()
    ]
    rows.sort(key=lambda item: (-item["voting_power"], item["hash"]))
    participation = round(min(100.0, voted_power * 100.0 / denom), 4)
    missing = round(min(100.0, missing_power * 100.0 / denom), 4)
    competing = len([item for item in rows if item["hash"] != "NIL" and item["voting_power"] > 0]) > 1
    return rows, participation, missing, competing


async def _rpc_views(service):
    key = (service.definition.transport.network_id, "consensus_rpc_views", ())

    async def load():
        endpoints = service.definition.transport.rpc_endpoints
        providers = service.definition.endpoint_providers

        async def status_for(index, endpoint):
            label = providers[index].label if index < len(providers) else f"RPC {index + 1}"
            try:
                payload = await service.adapter._transport.get_object(endpoint, "/status")
                result = _mapping(payload.get("result"), "status result")
                node = _mapping(result.get("node_info"), "node info")
                sync = _mapping(result.get("sync_info"), "sync info")
                if node.get("network") != service.definition.transport.chain_id:
                    return {"provider": label, "status": "unavailable", "height": None, "block_hash": None}
                height = _integer(sync.get("latest_block_height"), "latest height")
                catching_up = sync.get("catching_up") is True
                return {"provider": label, "status": "catching_up" if catching_up else "healthy",
                        "height": height, "block_hash": None, "endpoint": endpoint}
            except Exception:
                return {"provider": label, "status": "unavailable", "height": None, "block_hash": None}

        rows = list(await asyncio.gather(*(status_for(i, endpoint) for i, endpoint in enumerate(endpoints))))
        heights = [row["height"] for row in rows if row["height"] is not None]
        if not heights:
            return [], 0, False
        highest = max(heights)
        common = min(heights)
        for row in rows:
            if row["height"] is not None and row["status"] == "healthy" and highest - row["height"] > service.definition.transport.max_height_lag:
                row["status"] = "lagging"

        async def hash_for(row):
            endpoint = row.pop("endpoint", None)
            if endpoint is None or row["status"] == "unavailable":
                return row
            try:
                payload = await service.adapter._transport.get_object(endpoint, f"/block?height={common}", accept_error_payload=True)
                result = _mapping(payload.get("result"), "block result")
                block_id = _mapping(result.get("block_id"), "block id")
                row["block_hash"] = _safe_hash(block_id.get("hash"))
            except Exception:
                row["block_hash"] = None
            return row

        rows = list(await asyncio.gather(*(hash_for(row) for row in rows)))
        hashes = {row["block_hash"] for row in rows if row["block_hash"]}
        return rows, highest - common, len(hashes) > 1

    return await service.cache.get_or_load(key, RPC_VIEWS_TTL, load)


async def load_consensus(service) -> CosmosConsensusResponse:
    current = await _rpc_payload(service, "current", "/consensus_state", CURRENT_TTL)
    state = _round_state(current)
    height, round_number, step = _height_round_step(state)
    prevotes, precommits = _active_round_votes(state, round_number)

    dump_state = None
    try:
        dump = await _rpc_payload(service, "dump", "/dump_consensus_state", VALIDATOR_SET_TTL)
        dump_state = _round_state(dump)
    except Exception:
        dump_state = None

    validator_rows = []
    proposer_address = None
    if dump_state is not None:
        validator_rows, proposer_address = _dump_validators(dump_state)
    if not validator_rows:
        validator_rows = await _validator_set_fallback(service)

    try:
        staking = await service._bonded_validators()
    except Exception:
        staking = []
    identities = _staking_identities(staking)

    total_power = sum(row["voting_power"] for row in validator_rows)
    validators = []
    for index, row in enumerate(validator_rows[:MAX_VALIDATORS]):
        address = row["address"]
        identity = identities.get(address, {})
        prevote_state, prevote_hash = _vote(prevotes[index], "Prevote") if index < len(prevotes) else ("missing", None)
        precommit_state, precommit_hash = _vote(precommits[index], "Precommit") if index < len(precommits) else ("missing", None)
        validators.append({
            "consensus_address": address,
            "operator_address": identity.get("operator_address"),
            "moniker": identity.get("moniker") or address[:12],
            "voting_power": row["voting_power"],
            "voting_power_percent": round(min(100.0, row["voting_power"] * 100.0 / (total_power or 1)), 4),
            "proposer": address == proposer_address,
            "prevote": prevote_state,
            "prevote_hash": prevote_hash,
            "precommit": precommit_state,
            "precommit_hash": precommit_hash,
        })

    prevote_hashes, prevote_power, prevote_missing, competing_prevotes = _aggregate_hashes(validators, "prevote", total_power)
    precommit_hashes, precommit_power, precommit_missing, competing_precommits = _aggregate_hashes(validators, "precommit", total_power)
    rpc_views, rpc_height_spread, rpc_diverged = await _rpc_views(service)

    proposer = next((row for row in validators if row["proposer"]), None)
    clock = getattr(service, "_wall_clock", None)
    now = clock() if callable(clock) else datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    return CosmosConsensusResponse.model_validate({
        "network_id": service.definition.transport.network_id,
        "chain_id": service.definition.transport.chain_id,
        "height": height,
        "round": round_number,
        "step": step,
        "step_label": _STEP_LABELS.get(step, f"Step {step}"),
        "start_time": state.get("start_time") if isinstance(state.get("start_time"), str) else None,
        "updated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "proposer_address": proposer_address,
        "proposer_moniker": proposer.get("moniker") if proposer else None,
        "total_voting_power": total_power,
        "prevote_power_percent": prevote_power,
        "precommit_power_percent": precommit_power,
        "prevote_quorum": prevote_power >= _QUORUM,
        "precommit_quorum": precommit_power >= _QUORUM,
        "prevote_hashes": prevote_hashes,
        "precommit_hashes": precommit_hashes,
        "prevote_missing_percent": prevote_missing,
        "precommit_missing_percent": precommit_missing,
        "competing_prevote_hashes": competing_prevotes,
        "competing_precommit_hashes": competing_precommits,
        "proposal_block_hash": _safe_hash(state.get("proposal_block_hash")),
        "locked_block_hash": _safe_hash(state.get("locked_block_hash")),
        "valid_block_hash": _safe_hash(state.get("valid_block_hash")),
        "validators": validators,
        "rpc_views": rpc_views,
        "rpc_height_spread": rpc_height_spread,
        "rpc_diverged": rpc_diverged,
    })
