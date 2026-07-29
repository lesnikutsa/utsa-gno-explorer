"""FastAPI application for the read-only explorer API."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import logging
import re
import json
import math
import time
from decimal import Decimal, ROUND_HALF_UP

from fastapi import FastAPI, HTTPException, Path, Query

from api.config import ConfigError, load_config
from api.account_service import AccountUnavailableError, fetch_live_account
from api.network_profile import topaz_profile, validate_account_address
from api.database import (
    MissingIndexedBlockError,
    MissingIndexerStateError,
    database,
    isoformat_utc_z,
)
from api.schemas import (
    AccountResponse,
    BlockCommitSummary,
    BlockDetailResponse,
    BlockSummary,
    BlocksPagination,
    BlockTransactionSummary,
    BlocksResponse,
    HealthResponse,
    GovernanceProposalDetail,
    GovernanceProposalDetailResponse,
    GovernanceProposalListItem,
    GovernanceProposalsPagination,
    GovernanceProposalsResponse,
    GovernanceSourceResponse,
    GovernanceStatusCounts,
    GovernanceVoteResponse,
    NetworkResponse,
    NetworkDistributionCountry,
    NetworkDistributionProvider,
    NetworkDistributionRegion,
    NetworkDistributionResponse,
    NetworkDistributionRpcSources,
    NetworkValidators,
    SelectedRpc,
    TransactionDetailResponse,
    TransactionHashLookupResponse,
    TransactionListItem,
    TransactionSummaryResponse,
    TransactionsPagination,
    TransactionsResponse,
    ValidatorListItem,
    ValidatorSearchItem,
    ValidatorSearchResponse,
    ValidatorCurrentStatus,
    ValidatorDetailResponse,
    ValidatorSigningHistory,
    ValidatorSigningHistoryBatchItem,
    ValidatorSigningHistoryBatchResponse,
    ValidatorSigningHistoryBlock,
    ValidatorSigningHistoryItem,
    ValidatorsResponse,
    ValidatorUptime,
)

LOGGER = logging.getLogger(__name__)
UNAVAILABLE_DETAIL = "Explorer database is unavailable"
HEX_HASH_RE = re.compile(r"^(?:0[xX])?([0-9a-fA-F]{64})$")
SUMMARY_CORE_FIELDS = ("type", "category", "action", "label")
SUMMARY_FIELD_LIMITS = {"type": 160, "category": 64, "action": 64, "label": 80}
SUMMARY_MESSAGE_FIELDS = SUMMARY_CORE_FIELDS + (
    "sender", "recipient", "amount", "send", "package_path", "package_name",
    "function", "args_count", "file_count", "expires_at", "allow_paths_count",
    "spend_limit", "spend_period",
)
SUMMARY_SCALAR_STRING_LIMIT = 160
SUMMARY_INTEGER_LIMIT = (1 << 255) - 1
SUMMARY_MAX_BYTES = 16384


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        config = load_config()
        database.open(config)
        app.state.api_config = config
    except ConfigError as exc:
        LOGGER.error("API configuration error: %s", exc)
        raise RuntimeError("API configuration error") from None
    except Exception:
        LOGGER.error("Explorer database startup failed")
        raise RuntimeError(UNAVAILABLE_DETAIL) from None
    try:
        yield
    finally:
        database.close()


app = FastAPI(title="UTSA Gno.land Explorer API", lifespan=lifespan)

ACCOUNT_UNAVAILABLE_DETAIL = "Account data is temporarily unavailable"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@app.get("/api/accounts/{address}", response_model=AccountResponse)
def get_account(address: str) -> AccountResponse:
    config = app.state.api_config
    if not validate_account_address(address, topaz_profile(config.chain_id)):
        raise HTTPException(status_code=422, detail="Invalid account address")
    account_started_at = time.perf_counter()
    try:
        try:
            result = fetch_live_account(address, config)
            relation_started_at = time.perf_counter()
            try:
                result["validator_relation"] = (
                    database.fetch_account_validator_relation(address) if result["found"] else None
                )
            finally:
                LOGGER.info(
                    "account_validator_relation validator_relation_seconds=%.6f",
                    time.perf_counter() - relation_started_at,
                )
            return AccountResponse(**result)
        except AccountUnavailableError:
            LOGGER.error("Live account RPC data is unavailable")
        except Exception:
            LOGGER.error("Account validator relation query failed")
        raise HTTPException(status_code=503, detail=ACCOUNT_UNAVAILABLE_DETAIL) from None
    finally:
        LOGGER.info(
            "account_request_timing account_total_seconds=%.6f",
            time.perf_counter() - account_started_at,
        )


def _normalize_block_hash(block_hash_hex: str) -> str:
    if block_hash_hex.startswith(("0x", "0X")):
        block_hash_hex = block_hash_hex[2:]
    return block_hash_hex.upper()


def _normalize_tx_hash(tx_hash_hex: str | None) -> str | None:
    if tx_hash_hex is None:
        return None
    normalized = tx_hash_hex[2:] if tx_hash_hex.startswith(("0x", "0X")) else tx_hash_hex
    normalized = normalized.upper()
    return normalized if re.fullmatch(r"[0-9A-F]{64}", normalized) else None


def _public_summary_string(value, maximum: int) -> bool:
    return isinstance(value, str) and 0 < len(value) <= maximum and value.isprintable()


def _public_summary_scalar(value) -> bool:
    if value is None or type(value) is bool:
        return True
    if type(value) is str:
        return len(value) <= SUMMARY_SCALAR_STRING_LIMIT and value.isprintable()
    if type(value) is int:
        return -SUMMARY_INTEGER_LIMIT <= value <= SUMMARY_INTEGER_LIMIT
    return type(value) is float and math.isfinite(value)


def _public_transaction_summary(value) -> TransactionSummaryResponse | None:
    if value is None:
        return None
    try:
        if not isinstance(value, dict) or set((
            "schema_version", "chain_family", "parse_status", "message_count",
            "messages_truncated", "primary", "messages",
        )) - value.keys():
            raise ValueError
        if type(value["schema_version"]) is not int or value["schema_version"] != 1:
            raise ValueError
        chain_family = value["chain_family"]
        if not _public_summary_string(chain_family, 64) or not re.fullmatch(r"[a-z][a-z0-9_-]*", chain_family):
            raise ValueError
        if value["parse_status"] not in ("unparsed", "parsed", "unsupported", "invalid"):
            raise ValueError
        count = value["message_count"]
        if count is not None and (type(count) is not int or not 0 <= count <= 100000):
            raise ValueError
        truncated = value["messages_truncated"]
        if type(truncated) is not bool:
            raise ValueError
        primary_value = value["primary"]
        if not isinstance(primary_value, dict):
            raise ValueError
        primary = {}
        for field in SUMMARY_CORE_FIELDS:
            item = primary_value.get(field)
            if not _public_summary_string(item, SUMMARY_FIELD_LIMITS[field]):
                raise ValueError
            primary[field] = item
        stored_messages = value["messages"]
        if not isinstance(stored_messages, list) or len(stored_messages) > 20:
            raise ValueError
        messages = []
        for stored_message in stored_messages:
            if not isinstance(stored_message, dict):
                raise ValueError
            message = {}
            for field in SUMMARY_MESSAGE_FIELDS:
                if field not in stored_message:
                    continue
                item = stored_message[field]
                if field in SUMMARY_CORE_FIELDS:
                    if not _public_summary_string(item, SUMMARY_FIELD_LIMITS[field]):
                        raise ValueError
                elif not _public_summary_scalar(item):
                    raise ValueError
                message[field] = item
            if any(field not in message for field in SUMMARY_CORE_FIELDS):
                raise ValueError
            messages.append(message)
        if count is not None and count < len(messages):
            raise ValueError
        if count is not None and count > len(messages) and not truncated:
            raise ValueError
        if messages and any(messages[0][field] != primary[field] for field in SUMMARY_CORE_FIELDS):
            raise ValueError
        public = {
            "schema_version": 1, "chain_family": chain_family,
            "parse_status": value["parse_status"], "message_count": count,
            "messages_truncated": truncated, "primary": primary, "messages": messages,
        }
        if len(json.dumps(public, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > SUMMARY_MAX_BYTES:
            raise ValueError
        return TransactionSummaryResponse.model_validate(public)
    except (TypeError, ValueError):
        LOGGER.warning("Stored transaction summary failed public validation")
        return None


def _block_summary_from_row(row: dict) -> BlockSummary:
    return BlockSummary(
        height=row["height"],
        block_hash=_normalize_block_hash(row["block_hash_hex"]),
        time=isoformat_utc_z(row["time_utc"]),
        proposer_address=row["proposer_address"],
        proposer_moniker=row.get("proposer_moniker"),
        tx_count=row["tx_count"],
    )


def _block_detail_from_row(detail: dict) -> BlockDetailResponse:
    block = detail["block"]
    commit = detail["commit"]
    return BlockDetailResponse(
        height=block["height"],
        block_hash=_normalize_block_hash(block["block_hash_hex"]),
        block_hash_base64=block["block_hash_base64"],
        time=isoformat_utc_z(block["time_utc"]),
        proposer_address=block["proposer_address"],
        proposer_moniker=block.get("proposer_moniker"),
        tx_count=block["tx_count"],
        commit=BlockCommitSummary(
            validators=commit["validators"],
            signed=commit["signed"],
            missed=commit["missed"],
            nil=commit["nil"],
            absent=commit["absent"],
            invalid=commit["invalid"],
            unknown=commit["unknown"],
        ),
        transactions=[
            BlockTransactionSummary(
                index=row["tx_index"],
                tx_hash=_normalize_tx_hash(row.get("tx_hash_hex")),
                raw_base64=row["raw_base64"],
                raw_base64_length=row["raw_base64_length"],
                decoded_byte_length=row["decoded_byte_length"],
                decode_status=row["decode_status"],
            )
            for row in detail["transactions"]
        ],
    )


def _transaction_detail_from_row(row: dict) -> TransactionDetailResponse:
    return TransactionDetailResponse(
        block_height=row["block_height"],
        block_hash=_normalize_block_hash(row["block_hash_hex"]),
        block_time=isoformat_utc_z(row["time_utc"]),
        proposer_address=row["proposer_address"],
        proposer_moniker=row.get("proposer_moniker"),
        index=row["tx_index"],
        tx_hash=_normalize_tx_hash(row.get("tx_hash_hex")),
        raw_base64=row["raw_base64"],
        raw_base64_length=row["raw_base64_length"],
        decoded_byte_length=row["decoded_byte_length"],
        decode_status=row["decode_status"],
        summary=_public_transaction_summary(row.get("payload_summary")),
    )


def _transaction_list_item_from_row(row: dict) -> TransactionListItem:
    summary = _public_transaction_summary(row.get("payload_summary"))
    return TransactionListItem(
        block_height=row["block_height"],
        index=row["tx_index"],
        tx_hash=_normalize_tx_hash(row.get("tx_hash_hex")),
        block_time=isoformat_utc_z(row["time_utc"]),
        type=summary.primary.type if summary is not None else "unknown",
        operation=summary.primary.label if summary is not None else "Transaction",
    )


def _health_response_from_row(row: dict, config) -> HealthResponse:
    indexed_height = row["indexed_height"]
    finalized_tip_height = row["finalized_tip_height"]
    indexer_lag = None
    if finalized_tip_height is not None:
        indexer_lag = max(finalized_tip_height - indexed_height, 0)

    rpc_last_checked_at = row["rpc_last_checked_at"]
    degraded = False
    if indexer_lag is not None and indexer_lag > config.indexer_lag_degraded_threshold:
        degraded = True
    if not row["has_healthy_rpc"]:
        degraded = True
    if rpc_last_checked_at is None:
        degraded = True
    else:
        now = utc_now()
        checked_at = rpc_last_checked_at
        if checked_at.tzinfo is None:
            checked_at = checked_at.replace(tzinfo=timezone.utc)
        if (now - checked_at.astimezone(timezone.utc)).total_seconds() > config.rpc_check_stale_seconds:
            degraded = True

    return HealthResponse(
        status="degraded" if degraded else "ok",
        database="ok",
        chain_id=row["chain_id"],
        indexed_height=indexed_height,
        finalized_tip_height=finalized_tip_height,
        indexer_lag=indexer_lag,
        rpc_last_checked_at=isoformat_utc_z(rpc_last_checked_at),
        api_version=config.api_version,
    )


def _governance_datetime(value) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("Invalid stored timestamp")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value


def _governance_source(row: dict, realm_path: str) -> GovernanceSourceResponse:
    current_chain_id = row.get("current_chain_id")
    chain_id = row.get("chain_id")
    count = row["proposal_count"]
    first = row["first_proposal_id"]
    latest = row["latest_proposal_id"]
    actual_count = row.get("actual_proposal_count")
    actual_first = row.get("actual_first_proposal_id")
    actual_latest = row.get("actual_latest_proposal_id")
    if (
        type(current_chain_id) is not str or not 1 <= len(current_chain_id) <= 128
        or type(chain_id) is not str or not 1 <= len(chain_id) <= 128
        or chain_id != current_chain_id
        or type(row.get("realm_path")) is not str or row["realm_path"] != realm_path
        or type(row.get("source_height")) is not int or row["source_height"] < 1
        or type(row.get("page_count")) is not int or not 1 <= row["page_count"] <= 100
        or type(count) is not int or not 0 <= count <= 1000
        or (first is not None and (type(first) is not int or first < 0))
        or (latest is not None and (type(latest) is not int or latest < 0))
        or (count == 0 and (first is not None or latest is not None))
        or (count > 0 and (type(first) is not int or type(latest) is not int or first < 0 or latest < first))
        or type(actual_count) is not int or actual_count < 0
        or (actual_first is not None and (type(actual_first) is not int or actual_first < 0))
        or (actual_latest is not None and (type(actual_latest) is not int or actual_latest < 0))
        or actual_count != count or actual_first != first or actual_latest != latest
        or not isinstance(row.get("last_success_at"), datetime)
    ):
        raise ValueError("Inconsistent governance source")
    data = {
        "chain_id": chain_id, "realm_path": row["realm_path"],
        "source_height": row["source_height"], "page_count": row["page_count"],
        "proposal_count": count, "first_proposal_id": first, "latest_proposal_id": latest,
        "last_success_at": isoformat_utc_z(_governance_datetime(row["last_success_at"])),
    }
    return GovernanceSourceResponse.model_validate(data, strict=True)


def _governance_status_counts(row: dict, proposal_count: int) -> GovernanceStatusCounts:
    values = {name: row[f"{name}_count"] for name in ("active", "accepted", "rejected", "unknown")}
    if any(type(value) is not int or value < 0 for value in values.values()) or sum(values.values()) != proposal_count:
        raise ValueError("Inconsistent governance status counts")
    return GovernanceStatusCounts.model_validate(values, strict=True)


def _governance_tiers(value) -> list[str]:
    if type(value) is not list or len(value) > 100 or any(
        type(tier) is not str or not 1 <= len(tier) <= 64
        or tier != tier.strip() or not tier.isprintable()
        for tier in value
    ) or len(value) != len(set(value)):
        raise ValueError("Invalid eligible tiers")
    return value


def _governance_list_item(row: dict) -> GovernanceProposalListItem:
    data = {key: row.get(key) for key in (
        "proposal_id", "title", "author_display", "author_address", "status",
        "yes_percent", "no_percent", "abstain_percent", "voter_count",
    )}
    data["eligible_tiers"] = _governance_tiers(row.get("eligible_tiers"))
    for key in ("yes_percent", "no_percent", "abstain_percent"):
        value = data[key]
        if value is not None and (type(value) not in (int, float, Decimal) or type(value) is bool):
            raise ValueError("Invalid percentage")
        data[key] = None if value is None else float(value)
        if data[key] is not None and not math.isfinite(data[key]):
            raise ValueError("Invalid percentage")
    return GovernanceProposalListItem.model_validate(data, strict=True)


def _governance_voter_identity(vote: GovernanceVoteResponse) -> tuple[str, str]:
    if vote.voter_address is not None:
        return ("address", vote.voter_address.lower())
    identity = " ".join(vote.voter_display.split()).casefold()
    if not identity:
        raise ValueError("Invalid voter identity")
    return ("display", identity)


def _governance_vote(row: dict, source_height: int) -> GovernanceVoteResponse:
    first, last = row["first_observed_height"], row["last_observed_height"]
    first_at, last_at = _governance_datetime(row["first_observed_at"]), _governance_datetime(row["last_observed_at"])
    if type(first) is not int or type(last) is not int or first < 1 or last < first or last > source_height or last_at < first_at:
        raise ValueError("Invalid vote observations")
    display = row.get("voter_display")
    if type(display) is not str or not display.strip() or not display.isprintable():
        raise ValueError("Invalid voter display")
    if (
        type(row.get("tier")) is not str or row["tier"] != row["tier"].strip()
        or not row["tier"].isprintable()
    ):
        raise ValueError("Invalid vote tier")
    vote = GovernanceVoteResponse.model_validate({
        "voter_display": row["voter_display"], "voter_address": row["voter_address"],
        "option": row["option"], "tier": row["tier"], "voting_power": row["voting_power"],
        "first_observed_height": first, "last_observed_height": last,
    }, strict=True)
    _governance_voter_identity(vote)
    return vote


def _governance_detail(
    result: dict, realm_path: str, expected_proposal_id: int
) -> GovernanceProposalDetailResponse:
    source = _governance_source(result["source"], realm_path)
    _governance_status_counts(result["source"], source.proposal_count)
    proposal = result["proposal"]
    # Detail freshness belongs to this proposal, not the newer global list scan.
    source = source.model_copy(update={
        "source_height": proposal["last_observed_height"],
        "last_success_at": isoformat_utc_z(_governance_datetime(proposal["last_observed_at"])),
    })
    votes = result["votes"]
    if len(votes) > 1000:
        raise ValueError("Too many votes")
    public_votes = [_governance_vote(row, source.source_height) for row in votes]
    identities = [_governance_voter_identity(vote) for vote in public_votes]
    first, last = proposal["first_observed_height"], proposal["last_observed_height"]
    first_at, last_at = _governance_datetime(proposal["first_observed_at"]), _governance_datetime(proposal["last_observed_at"])
    if (
        proposal.get("proposal_id") != expected_proposal_id
        or source.first_proposal_id is None or source.latest_proposal_id is None
        or not source.first_proposal_id <= expected_proposal_id <= source.latest_proposal_id
        or type(proposal.get("voter_count")) is not int
        or len(identities) != len(set(identities)) or type(first) is not int or type(last) is not int
        or first < 1 or last < first or last > source.source_height or last_at < first_at
        or proposal["voter_count"] != len(votes)
        or proposal["votes_parse_status"] == "unparsed"
        or (proposal["votes_parse_status"] == "parsed") != bool(votes)
    ):
        raise ValueError("Inconsistent governance detail")
    base = _governance_list_item(proposal).model_dump()
    base.update({key: proposal[key] for key in (
        "description", "executor_text", "executor_creation_realm", "rejection_reason",
        "detail_parse_status", "votes_parse_status",
    )})
    base.update(first_observed_height=first, last_observed_height=last,
                first_observed_at=isoformat_utc_z(first_at), last_observed_at=isoformat_utc_z(last_at),
                votes=public_votes)
    return GovernanceProposalDetailResponse(source=source, proposal=GovernanceProposalDetail.model_validate(base, strict=True))


def _network_response_from_row(row: dict) -> NetworkResponse:
    indexed_height = row["indexed_height"]
    finalized_tip_height = row["finalized_tip_height"]
    indexer_lag = None
    if finalized_tip_height is not None:
        indexer_lag = max(finalized_tip_height - indexed_height, 0)

    selected_rpc = None
    if row["rpc_url"] is not None:
        selected_rpc = SelectedRpc(
            url=row["rpc_url"],
            healthy=row["rpc_healthy"],
            catching_up=row["rpc_catching_up"],
            observed_height=row["rpc_observed_height"],
            lag=row["rpc_lag"],
            last_checked_at=isoformat_utc_z(row["rpc_last_checked_at"]),
        )

    return NetworkResponse(
        chain_id=row["chain_id"],
        rpc_height=row["rpc_observed_height"] if selected_rpc is not None else None,
        finalized_tip_height=finalized_tip_height,
        indexed_height=indexed_height,
        indexer_lag=indexer_lag,
        average_block_time_seconds=(
            float(row["average_block_time_seconds"])
            if row["average_block_time_seconds"] is not None
            else None
        ),
        average_block_time_sample_size=int(row["average_block_time_sample_size"]),
        latest_block=_block_summary_from_row(
            {
                "height": row["block_height"],
                "block_hash_hex": row["block_hash_hex"],
                "time_utc": row["time_utc"],
                "proposer_address": row["proposer_address"],
                "proposer_moniker": row.get("proposer_moniker"),
                "tx_count": row["tx_count"],
            }
        ),
        validators=NetworkValidators(
            height=indexed_height,
            active_count=row["validator_active_count"],
            total_voting_power=str(row["validator_total_voting_power"]),
        ),
        selected_rpc=selected_rpc,
    )


def _network_distribution_response_from_row(row: dict) -> NetworkDistributionResponse:
    if row["scanned_at"] is None:
        raise LookupError("Network distribution snapshot is missing")
    if not isinstance(row["scanned_at"], datetime):
        raise ValueError("Invalid snapshot timestamp")
    for key in ("chain_id", "source_kind"):
        value = row[key]
        if not _is_canonical_text(value):
            raise ValueError("Invalid snapshot text")
    totals = {
        "rpc_sources_total": row["rpc_sources_total"],
        "rpc_sources_ok": row["rpc_sources_ok"],
        "visible_node_ids": row["visible_node_ids"],
        "unique_public_ips": row["unique_public_ips"],
        "geolocated_node_ids": row["geolocated_node_ids"],
        "geolocated_public_ips": row["geolocated_public_ips"],
        "node_id_ip_conflicts": row["node_id_ip_conflicts"],
        "region_count": row["region_count"],
        "country_count": row["country_count"],
        "provider_count": row["provider_count"],
    }
    if any(type(value) is not int or value < 0 for value in totals.values()):
        raise ValueError("Invalid aggregate count")
    if totals["rpc_sources_ok"] > totals["rpc_sources_total"]:
        raise ValueError("Invalid RPC source counts")
    if totals["geolocated_node_ids"] > totals["visible_node_ids"]:
        raise ValueError("Invalid node geolocation count")
    if totals["geolocated_public_ips"] > totals["unique_public_ips"]:
        raise ValueError("Invalid IP geolocation count")

    definitions = (
        ("regions", "region_count", NetworkDistributionRegion, {"name", "count"}),
        ("countries", "country_count", NetworkDistributionCountry, {"code", "name", "count"}),
        ("providers", "provider_count", NetworkDistributionProvider, {"asn", "name", "count"}),
    )
    parsed = {}
    covered = {}
    for list_key, count_key, model, allowed_keys in definitions:
        values = row[list_key]
        if not isinstance(values, list) or len(values) != totals[count_key]:
            raise ValueError("Invalid aggregate list")
        seen = set()
        parsed_items = []
        count_sum = 0
        for value in values:
            if (not isinstance(value, dict) or set(value) != allowed_keys
                    or type(value.get("count")) is not int or value["count"] < 0):
                raise ValueError("Invalid aggregate item")
            raw_name = value.get("name")
            if not _is_canonical_text(raw_name):
                raise ValueError("Invalid aggregate name")
            if list_key == "countries":
                code = value.get("code")
                if not isinstance(code, str) or re.fullmatch(r"[A-Z]{2}", code, re.ASCII) is None:
                    raise ValueError("Invalid country code")
            if list_key == "providers":
                asn = value.get("asn")
                if asn is not None and (type(asn) is not int or asn <= 0):
                    raise ValueError("Invalid provider ASN")
                key = ("asn", asn) if asn is not None else ("name", " ".join(raw_name.split()).casefold())
            elif list_key == "regions":
                key = " ".join(raw_name.split()).casefold()
            else:
                key = value["code"]
            if key in seen:
                raise ValueError("Duplicate aggregate grouping")
            seen.add(key)
            count_sum += value["count"]
            parsed_items.append(model(
                **value,
                share_percent=_rounded_percent(value["count"], totals["geolocated_public_ips"]),
            ))
        if count_sum > totals["geolocated_public_ips"]:
            raise ValueError("Aggregate coverage exceeds geolocation total")
        parsed[list_key] = parsed_items
        covered[list_key] = count_sum

    return NetworkDistributionResponse(
        chain_id=row["chain_id"], source_kind=row["source_kind"],
        updated_at=isoformat_utc_z(row["scanned_at"]),
        rpc_sources=NetworkDistributionRpcSources(total=totals["rpc_sources_total"], ok=totals["rpc_sources_ok"]),
        visible_node_ids=totals["visible_node_ids"], unique_public_ips=totals["unique_public_ips"],
        geolocated_node_ids=totals["geolocated_node_ids"], geolocated_public_ips=totals["geolocated_public_ips"],
        geolocation_coverage_percent=_rounded_percent(totals["geolocated_public_ips"], totals["unique_public_ips"]),
        node_id_ip_conflicts=totals["node_id_ip_conflicts"], region_count=totals["region_count"],
        country_count=totals["country_count"], provider_count=totals["provider_count"],
        region_covered_public_ips=covered["regions"], country_covered_public_ips=covered["countries"],
        provider_covered_public_ips=covered["providers"],
        region_coverage_percent=_rounded_percent(covered["regions"], totals["unique_public_ips"]),
        country_coverage_percent=_rounded_percent(covered["countries"], totals["unique_public_ips"]),
        provider_coverage_percent=_rounded_percent(covered["providers"], totals["unique_public_ips"]),
        regions=parsed["regions"], countries=parsed["countries"], providers=parsed["providers"],
    )


def _is_canonical_text(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value == value.strip()
        and all(character.isprintable() for character in value)
    )


def _normalize_hash_query(value: str) -> tuple[str | None, str | None]:
    stripped = value.strip()
    if not stripped:
        raise HTTPException(status_code=422, detail="hash must not be empty")
    if len(stripped) > 200:
        raise HTTPException(status_code=422, detail="hash is too long")
    match = HEX_HASH_RE.match(stripped)
    if match is not None:
        return match.group(1).upper(), None
    return None, stripped


def _rounded_percent(numerator: Decimal | int, denominator: Decimal | int) -> float:
    if denominator == 0:
        return 0.0
    value = Decimal(numerator) * Decimal(100) / Decimal(denominator)
    return float(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _validators_response_from_rows(result: dict) -> ValidatorsResponse:
    rows = result["items"]
    total_voting_power = sum((Decimal(row["voting_power"]) for row in rows), Decimal(0))
    checkpoint = result["checkpoint"]
    items = []
    for row in rows:
        active = int(row["active_blocks_1000"])
        signed = int(row["signed_blocks_1000"])
        uptime = ValidatorUptime(
            network_blocks=int(checkpoint["network_blocks_1000"]),
            active_blocks=active,
            signed_blocks=signed,
            nil_blocks=int(row["nil_blocks_1000"]),
            absent_blocks=int(row["absent_blocks_1000"]),
            invalid_blocks=int(row["invalid_blocks_1000"]),
            unknown_blocks=int(row["unknown_blocks_1000"]),
            uptime_percent=_rounded_percent(signed, active),
        )
        items.append(ValidatorListItem(
            address=row["address"],
            public_key_type=row["public_key_type"],
            voting_power=str(row["voting_power"]),
            percent=_rounded_percent(row["voting_power"], total_voting_power),
            proposer_priority=None if row["proposer_priority"] is None else str(row["proposer_priority"]),
            moniker=row.get("moniker"),
            operator_address=row.get("operator_address"),
            server_type=row.get("server_type"),
            valoper_source_height=row.get("valoper_source_height"),
            uptime_1000=uptime,
        ))
    return ValidatorsResponse(
        height=checkpoint["height"], total=len(items),
        total_voting_power=str(total_voting_power), items=items,
    )


def _history_status(row: dict) -> str:
    if row["membership_address"] is None:
        return "not_active"
    if row["signature_address"] is None:
        return "unknown"
    if row["signed"] is True:
        return "commit"
    if row["vote_status"] in ("nil", "absent", "invalid"):
        return row["vote_status"]
    return "unknown"


def _uptime_from_history(items: list[ValidatorSigningHistoryItem]) -> ValidatorUptime:
    statuses = [item.status for item in items]
    active = sum(status != "not_active" for status in statuses)
    counts = {status: statuses.count(status) for status in ("commit", "nil", "absent", "invalid", "unknown")}
    return ValidatorUptime(
        network_blocks=len(items),
        active_blocks=active,
        signed_blocks=counts["commit"],
        nil_blocks=counts["nil"],
        absent_blocks=counts["absent"],
        invalid_blocks=counts["invalid"],
        unknown_blocks=counts["unknown"],
        uptime_percent=_rounded_percent(counts["commit"], active),
    )


def _validator_detail_from_rows(result: dict) -> ValidatorDetailResponse:
    identity = result["identity"]
    current_row = result["current"]
    active = current_row["voting_power"] is not None
    all_history_items = [
        ValidatorSigningHistoryItem(
            height=row["height"], time=isoformat_utc_z(row["time_utc"]), status=_history_status(row)
        )
        for row in result["history"]
    ]
    visible_history_items = all_history_items[-100:]
    heights = [item.height for item in visible_history_items]
    current_power = current_row["voting_power"]
    return ValidatorDetailResponse(
        address=identity["address"],
        public_key_type=identity["public_key_type"],
        public_key_value=identity["public_key_value"],
        first_seen_height=identity["first_seen_height"],
        last_seen_height=identity["last_seen_height"],
        moniker=identity.get("moniker"),
        operator_address=identity.get("operator_address"),
        signing_pubkey=identity.get("signing_pubkey"),
        description=identity.get("description"),
        server_type=identity.get("server_type"),
        valoper_source_height=identity.get("valoper_source_height"),
        current=ValidatorCurrentStatus(
            active=active,
            height=current_row["height"],
            voting_power=str(current_power) if active else None,
            voting_power_percent=_rounded_percent(current_power, current_row["total_voting_power"]) if active else 0.0,
            proposer_priority=(None if not active or current_row["proposer_priority"] is None
                               else str(current_row["proposer_priority"])),
        ),
        uptime_1000=_uptime_from_history(all_history_items),
        signing_history=ValidatorSigningHistory(
            network_blocks=len(visible_history_items),
            start_height=min(heights) if heights else None,
            end_height=max(heights) if heights else None,
            items=visible_history_items,
        ),
    )


def _validator_signing_history_batch_from_rows(result: dict) -> ValidatorSigningHistoryBatchResponse:
    block_rows = result["blocks"]
    block_heights = [row["height"] for row in block_rows]
    if block_heights != sorted(block_heights) or len(block_heights) != len(set(block_heights)):
        raise ValueError("Signing history block axis is invalid")

    expected_addresses = list(result["checkpoint"]["validator_addresses"])
    if len(expected_addresses) != len(set(expected_addresses)):
        raise ValueError("Signing history validator axis contains duplicates")
    expected_address_set = set(expected_addresses)

    grouped: dict[str, list[dict]] = {}
    for row in result["items"]:
        if row["address"] not in expected_address_set:
            raise ValueError("Signing history matrix contains an unexpected validator")
        grouped.setdefault(row["address"], []).append(row)

    items = []
    for address in expected_addresses:
        rows = grouped.get(address, [])
        if [row["height"] for row in rows] != block_heights:
            raise ValueError("Signing history matrix is not aligned")
        items.append(ValidatorSigningHistoryBatchItem(
            address=address,
            statuses=[_history_status(row) for row in rows],
        ))

    blocks = [
        ValidatorSigningHistoryBlock(height=row["height"], time=isoformat_utc_z(row["time_utc"]))
        for row in block_rows
    ]
    return ValidatorSigningHistoryBatchResponse(
        height=result["checkpoint"]["height"],
        network_blocks=len(blocks),
        start_height=block_heights[0] if block_heights else None,
        end_height=block_heights[-1] if block_heights else None,
        blocks=blocks,
        items=items,
    )


@app.get("/api/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    config = app.state.api_config
    try:
        row = database.fetch_health_row()
    except MissingIndexerStateError:
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    except Exception:
        LOGGER.error("Explorer database health query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    return _health_response_from_row(row, config)


@app.get("/api/network", response_model=NetworkResponse)
def get_network() -> NetworkResponse:
    try:
        row = database.fetch_network_overview()
    except (MissingIndexerStateError, MissingIndexedBlockError):
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    except Exception:
        LOGGER.error("Explorer database network query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    return _network_response_from_row(row)


@app.get("/api/network/distribution", response_model=NetworkDistributionResponse)
def get_network_distribution() -> NetworkDistributionResponse:
    try:
        row = database.fetch_network_distribution()
        if row["scanned_at"] is None:
            raise HTTPException(status_code=404, detail="Network distribution snapshot not found")
        return _network_distribution_response_from_row(row)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database network distribution query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/validators", response_model=ValidatorsResponse)
def get_validators() -> ValidatorsResponse:
    try:
        return _validators_response_from_rows(database.fetch_active_validators())
    except Exception:
        LOGGER.error("Explorer database validators query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/search/validators", response_model=ValidatorSearchResponse)
def search_validators(
    q: str = Query(min_length=1),
    limit: int = Query(default=6, ge=1, le=10),
) -> ValidatorSearchResponse:
    query = q.strip()
    if len(query) < 2:
        raise HTTPException(status_code=422, detail="q must contain at least 2 non-whitespace characters")
    if len(query) > 128:
        raise HTTPException(status_code=422, detail="q must contain at most 128 characters")
    try:
        rows = database.fetch_validator_search(query, limit)
    except Exception:
        LOGGER.error("Explorer database validator search query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    return ValidatorSearchResponse(items=[ValidatorSearchItem(**row) for row in rows])


@app.get("/api/validators/signing-history", response_model=ValidatorSigningHistoryBatchResponse)
def get_validator_signing_history(
    limit: int = Query(default=100, ge=1, le=100),
) -> ValidatorSigningHistoryBatchResponse:
    try:
        result = database.fetch_validator_signing_history(limit=limit)
        return _validator_signing_history_batch_from_rows(result)
    except Exception:
        LOGGER.error("Explorer database validator signing history query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/validators/{address}", response_model=ValidatorDetailResponse)
def get_validator_detail(address: str = Path(min_length=1, max_length=128)) -> ValidatorDetailResponse:
    try:
        result = database.fetch_validator_detail(address)
        if result is None:
            raise HTTPException(status_code=404, detail="Validator not found")
        return _validator_detail_from_rows(result)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database validator detail query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/governance/proposals", response_model=GovernanceProposalsResponse)
def get_governance_proposals(
    limit: int = Query(default=20, ge=1, le=100),
    before_proposal_id: int | None = Query(default=None, ge=0),
) -> GovernanceProposalsResponse:
    realm_path = app.state.api_config.governance_realm
    try:
        result = database.fetch_governance_proposals(
            realm_path=realm_path, limit=limit, before_proposal_id=before_proposal_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Governance snapshot not found")
        source = _governance_source(result["source"], realm_path)
        counts = _governance_status_counts(result["source"], source.proposal_count)
        rows = result["items"]
        if type(rows) is not list or len(rows) > limit + 1:
            raise ValueError("Invalid proposal page size")
        page_rows = rows[:limit]
        items = [_governance_list_item(row) for row in page_rows]
        all_items = [_governance_list_item(row) for row in rows]
        ids = [item.proposal_id for item in all_items]
        if (
            any(left <= right for left, right in zip(ids, ids[1:]))
            or len(ids) != len(set(ids))
            or (before_proposal_id is not None and any(item_id >= before_proposal_id for item_id in ids))
            or (source.proposal_count == 0 and ids)
            or (ids and (
                source.first_proposal_id is None or source.latest_proposal_id is None
                or any(not source.first_proposal_id <= item_id <= source.latest_proposal_id for item_id in ids)
            ))
        ):
            raise ValueError("Invalid proposal ordering")
        next_cursor = items[-1].proposal_id if len(rows) > limit and items else None
        return GovernanceProposalsResponse(
            source=source, status_counts=counts, items=items,
            pagination=GovernanceProposalsPagination(
                limit=limit, next_before_proposal_id=next_cursor,
            ),
        )
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database governance list query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/governance/proposals/{proposal_id}", response_model=GovernanceProposalDetailResponse)
def get_governance_proposal(proposal_id: int = Path(ge=0)) -> GovernanceProposalDetailResponse:
    realm_path = app.state.api_config.governance_realm
    try:
        result = database.fetch_governance_proposal_detail(
            realm_path=realm_path, proposal_id=proposal_id,
        )
        if result is None:
            raise HTTPException(status_code=404, detail="Governance snapshot not found")
        if result["proposal"] is None:
            source = _governance_source(result["source"], realm_path)
            _governance_status_counts(result["source"], source.proposal_count)
            raise HTTPException(status_code=404, detail="Governance proposal not found")
        return _governance_detail(result, realm_path, proposal_id)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database governance detail query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/blocks", response_model=BlocksResponse)
def get_blocks(
    limit: int = Query(default=20, ge=1, le=100),
    before_height: int | None = Query(default=None, gt=0),
    hash: str | None = Query(default=None, max_length=200),
) -> BlocksResponse:
    if before_height is not None and hash is not None:
        raise HTTPException(status_code=422, detail="before_height and hash are mutually exclusive")

    try:
        if hash is not None:
            normalized_hex, block_hash_base64 = _normalize_hash_query(hash)
            row = database.fetch_block_by_hash(
                normalized_hex=normalized_hex,
                block_hash_base64=block_hash_base64,
            )
            items = [] if row is None else [_block_summary_from_row(row)]
            return BlocksResponse(
                items=items,
                pagination=BlocksPagination(limit=limit, next_before_height=None),
            )

        rows = database.fetch_blocks(limit=limit, before_height=before_height)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database blocks query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None

    page_rows = rows[:limit]
    next_before_height = page_rows[-1]["height"] if len(rows) > limit and page_rows else None
    return BlocksResponse(
        items=[_block_summary_from_row(row) for row in page_rows],
        pagination=BlocksPagination(limit=limit, next_before_height=next_before_height),
    )


@app.get(
    "/api/blocks/{height}/transactions/{index}",
    response_model=TransactionDetailResponse,
    response_model_exclude_unset=True,
)
def get_transaction_detail(
    height: int = Path(gt=0),
    index: int = Path(ge=0),
) -> TransactionDetailResponse:
    try:
        row = database.fetch_transaction_detail(height, index)
    except Exception:
        LOGGER.error("Explorer database transaction detail query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return _transaction_detail_from_row(row)


@app.get("/api/transactions/by-hash/{tx_hash}", response_model=TransactionHashLookupResponse)
def get_transaction_by_hash(tx_hash: str) -> TransactionHashLookupResponse:
    match = HEX_HASH_RE.fullmatch(tx_hash)
    if match is None:
        raise HTTPException(status_code=422, detail="Invalid transaction hash")
    normalized_hash = match.group(1).upper()
    try:
        row = database.fetch_transaction_by_hash(normalized_hash)
    except Exception:
        LOGGER.error("Explorer database transaction hash query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    if row is None:
        raise HTTPException(status_code=404, detail="Transaction not found")
    return TransactionHashLookupResponse(
        block_height=row["block_height"], index=row["tx_index"],
        tx_hash=str(row["tx_hash_hex"]).upper(),
    )


@app.get("/api/transactions", response_model=TransactionsResponse)
def get_transactions(
    limit: int = Query(default=20, ge=1, le=100),
    before_height: int | None = Query(default=None, gt=0),
    before_tx_index: int | None = Query(default=None, ge=0),
) -> TransactionsResponse:
    if (before_height is None) != (before_tx_index is None):
        raise HTTPException(
            status_code=422,
            detail="before_height and before_tx_index must be provided together",
        )
    try:
        rows = database.fetch_transactions(
            limit=limit,
            before_height=before_height,
            before_tx_index=before_tx_index,
        )
    except Exception:
        LOGGER.error("Explorer database transactions query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None

    page_rows = rows[:limit]
    has_next_page = len(rows) > limit and bool(page_rows)
    last_row = page_rows[-1] if has_next_page else None
    return TransactionsResponse(
        items=[_transaction_list_item_from_row(row) for row in page_rows],
        pagination=TransactionsPagination(
            limit=limit,
            next_before_height=last_row["block_height"] if last_row else None,
            next_before_tx_index=last_row["tx_index"] if last_row else None,
        ),
    )


@app.get("/api/blocks/{height}", response_model=BlockDetailResponse)
def get_block_detail(height: int = Path(gt=0)) -> BlockDetailResponse:
    try:
        detail = database.fetch_block_detail(height)
    except Exception:
        LOGGER.error("Explorer database block detail query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    if detail is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return _block_detail_from_row(detail)
