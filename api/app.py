"""FastAPI application for the read-only explorer API."""

from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
import logging
import re
import json
import math
import time
import traceback
from typing import Literal
from decimal import Decimal, ROUND_HALF_UP

from fastapi import FastAPI, HTTPException, Path, Query

from api.config import ConfigError, load_config
from api.account_service import AccountUnavailableError, fetch_live_account, public_rpc_url
from api.network_profile import gno_profile, validate_account_address
from api.transaction_argument_decoder import decode_transaction_arguments
from api.token_identity import extract_token_identity
from api.grc721_identity import classify_grc721
from api.asset_classification import (StaticAssetClassification,
                                      asset_classification_cache)
from indexer.realm_catalog import namespace_key, path_kind as realm_path_kind
from api.realm_application_registry import CURATED_NAMESPACE_KEYS, REALM_APPLICATION_REGISTRY
from api.database import (
    MissingIndexedBlockError,
    MissingIndexerStateError,
    complete_realm_call_coverage_bounds,
    database,
    isoformat_utc_z,
)
from api.schemas import (
    AccountTransactionListItem,
    AccountTransactionsPagination,
    AccountTransactionsResponse,
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
    RpcPool,
    RpcPoolEndpoint,
    NetworkDistributionCountry,
    NetworkDistributionProvider,
    NetworkDistributionRegion,
    NetworkDistributionResponse,
    NetworkDistributionRpcSources,
    NetworkValidators,
    RealmCatalogItem,
    RealmCatalogPagination,
    RealmCatalogResponse,
    RealmCatalogSummary,
    RealmCallListItem,
    RealmCallSource,
    RealmCallsPagination,
    RealmCallsResponse,
    RealmDetailResponse,
    RealmDetailSource,
    RealmMetadataFileResponse,
    RealmMetadataResponse,
    RealmMetadataSummary,
    RealmRankingSource,
    RealmApplicationRankingSource,
    RealmApplicationTopItem,
    RealmApplicationTopResponse,
    RealmNamespaceMember,
    RealmNamespaceTopItem,
    RealmNamespaceTopResponse,
    RealmTopResponse,
    SelectedRpc,
    TransactionDetailResponse,
    TransactionHashLookupResponse,
    TransactionListItem,
    TransactionSummaryResponse,
    TransactionsPagination,
    TransactionsResponse,
    TokenDirectoryItem,
    TokenDirectoryPagination,
    TokenDirectoryResponse,
    TokenDirectorySource,
    TokenDirectorySummary,
    TokenTopActivityItem,
    NativeTokenResponse,
    TokenSupplyResponse,
    AssetDirectoryItem,
    AssetDirectoryResponse,
    AssetDirectorySource,
    AssetDirectorySummary,
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
from api.token_supply import (NATIVE_GNOT_DECIMALS, NATIVE_GNOT_DENOM, decimal_amount,
                              query_native_gnot_supply, query_total_supply, token_supply_cache)

LOGGER = logging.getLogger(__name__)
UNAVAILABLE_DETAIL = "Explorer database is unavailable"

_HASH_RE = re.compile(r"^[0-9A-Fa-f]{64}$")
CALLS_UNAVAILABLE_DETAIL = "Realm call history is not available"
APPLICATION_WINDOW_UNAVAILABLE_DETAIL = "Realm application activity is not available for this window"
TOKEN_CANDIDATE_LIMIT = 1000
ASSET_CANDIDATE_LIMIT = 2000
TOKEN_ACTIVITY_WINDOWS = {"24h": 24, "7d": 168, "30d": 720}


def _active_token_count(source: dict, rows: list[dict]) -> int | None:
    checkpoint = source.get("call_index_checkpoint_at")
    coverage_start = source.get("call_index_coverage_started_at")
    indexed_height = source.get("indexed_height")
    activity_from = source.get("call_index_from_height")
    activity_through = source.get("call_index_through_height")
    if (not isinstance(checkpoint, datetime) or checkpoint.tzinfo is None
            or not isinstance(coverage_start, datetime) or coverage_start.tzinfo is None
            or type(indexed_height) is not int
            or type(activity_from) is not int or activity_from <= 0
            or type(activity_through) is not int or activity_through <= 0
            or activity_from > activity_through or activity_through > indexed_height
            or coverage_start > checkpoint - timedelta(hours=24)):
        return None
    window_start = checkpoint - timedelta(hours=24)
    return sum(1 for row in rows if isinstance(row.get("last_activity_at"), datetime)
               and window_start <= row["last_activity_at"] <= checkpoint)


def _validate_exact_catalog_path(path: str, *, expected_kind: str | None = None) -> str:
    if path != path.strip() or not 1 <= len(path) <= 256:
        raise HTTPException(status_code=422, detail="path is invalid")
    kind = realm_path_kind(path)
    if kind is None:
        raise HTTPException(status_code=422, detail="path is invalid")
    if expected_kind is not None and kind != expected_kind:
        raise HTTPException(status_code=422, detail="Realm calls require a gno.land/r/... path")
    return kind


def _realm_detail_from_rows(*, requested_chain_id: str, requested_path: str, result: dict) -> RealmDetailResponse:
    source, row = result.get("source"), result.get("item")
    if source is None or row is None:
        raise ValueError("Realm catalog source is unavailable")
    if source.get("chain_id") != requested_chain_id or row.get("chain_id") != requested_chain_id or row.get("path") != requested_path:
        raise ValueError("malformed Realm catalog identity")
    item = _realm_catalog_item_from_row(row)
    deploy_tuple = (item.deploy_height, item.deploy_tx_index)
    if (deploy_tuple[0] is None) != (deploy_tuple[1] is None):
        raise ValueError("malformed Realm deploy tuple")
    if item.deploy_height is not None and (item.deploy_height <= 0 or item.deploy_tx_index < 0):
        raise ValueError("malformed Realm deploy position")
    if item.first_seen_height is not None and item.first_seen_height <= 0:
        raise ValueError("malformed Realm first-seen height")
    raw_activity_at = row.get("last_activity_at")
    activity_tuple = (item.last_activity_height, item.last_activity_tx_index, item.last_activity_at)
    if item.kind == "package":
        if item.call_count != 0 or item.successful_call_count != 0 or item.failed_call_count != 0 or item.unknown_result_call_count != 0:
            raise ValueError("malformed Package call counters")
        if any(value is not None for value in activity_tuple):
            raise ValueError("malformed Package activity tuple")
    elif item.call_count == 0:
        if any(value is not None for value in activity_tuple):
            raise ValueError("malformed inactive Realm activity tuple")
    else:
        if any(value is None for value in activity_tuple):
            raise ValueError("missing Realm activity tuple")
        if item.last_activity_height <= 0 or item.last_activity_tx_index < 0:
            raise ValueError("malformed Realm activity position")
        if not isinstance(raw_activity_at, datetime) or raw_activity_at.tzinfo is None:
            raise ValueError("malformed Realm activity timestamp")
    key = namespace_key(item.path) if item.kind == "realm" else None
    application = dict(REALM_APPLICATION_REGISTRY[key]) if key in REALM_APPLICATION_REGISTRY else None
    return RealmDetailResponse(source=RealmDetailSource(
        chain_id=source["chain_id"], indexed_height=source["indexed_height"],
        catalog_observed_height=source["observed_height"], catalog_refreshed_at=isoformat_utc_z(source["refreshed_at"]),
        activity_from_height=source["activity_from_height"], activity_through_height=source["activity_through_height"],
        call_index_from_height=source.get("call_index_from_height"),
        call_index_through_height=source.get("call_index_through_height"),
        call_index_complete=complete_realm_call_coverage_bounds(source, requested_chain_id) is not None,
    ), item=item, namespace_key=key, application=application)


def _bounded_printable_scalar(value: object, *, max_length: int) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value != value.strip() or not 1 <= len(value) <= max_length:
        raise ValueError("malformed Realm call scalar")
    if any(not (" " <= character <= "~") for character in value):
        raise ValueError("malformed Realm call scalar")
    return value


def _exact_int(value: object, *, field: str) -> int:
    if type(value) is not int:
        raise ValueError(f"malformed Realm call {field}")
    return value


def _realm_call_item_from_row(row: dict) -> RealmCallListItem:
    pos = (_exact_int(row["block_height"], field="block height"),
           _exact_int(row["tx_index"], field="tx index"),
           _exact_int(row["message_index"], field="message index"))
    if pos[0] <= 0 or pos[1] < 0 or not 0 <= pos[2] <= 19:
        raise ValueError("malformed Realm call position")
    args_count = row.get("args_count")
    if args_count is not None:
        args_count = _exact_int(args_count, field="args count")
        if not 0 <= args_count <= 100000:
            raise ValueError("malformed Realm call args count")
    function_name = _bounded_printable_scalar(row.get("function_name"), max_length=160)
    send_amount = _bounded_printable_scalar(row.get("send_amount"), max_length=160)
    tx_hash = row.get("tx_hash_hex")
    if tx_hash is not None:
        if not isinstance(tx_hash, str) or not _HASH_RE.fullmatch(tx_hash):
            raise ValueError("malformed transaction hash")
        tx_hash = tx_hash.upper()
    for field in ("gas_wanted", "gas_used"):
        value = row.get(field)
        if value is not None and not re.fullmatch(r"^(0|[1-9][0-9]*)$", str(value)):
            raise ValueError("malformed gas value")
    block_time = row["time_utc"]
    if not isinstance(block_time, datetime) or block_time.tzinfo is None:
        raise ValueError("malformed call timestamp")
    return RealmCallListItem(block_height=pos[0], tx_index=pos[1], message_index=pos[2],
        block_time=isoformat_utc_z(block_time), tx_hash=tx_hash, caller_address=row.get("caller_address"),
        function_name=function_name, args_count=args_count, send_amount=send_amount,
        execution_status=row.get("execution_status"), gas_wanted=row.get("gas_wanted"), gas_used=row.get("gas_used"))


def _realm_calls_from_rows(*, requested_chain_id: str, requested_path: str, limit: int, result: dict) -> RealmCallsResponse:
    detail = _realm_detail_from_rows(requested_chain_id=requested_chain_id, requested_path=requested_path, result=result)
    if detail.item.kind != "realm":
        raise ValueError("Realm call path is not a Realm")
    if not detail.source.call_index_complete or detail.source.call_index_from_height is None or detail.source.call_index_through_height is None:
        raise HTTPException(status_code=409, detail=CALLS_UNAVAILABLE_DETAIL)
    coverage_available = result.get("coverage_available")
    if type(coverage_available) is not bool:
        raise ValueError("malformed Realm call coverage availability")
    if coverage_available is False:
        raise HTTPException(status_code=409, detail=CALLS_UNAVAILABLE_DETAIL)
    raw_rows = result.get("items", [])
    if len(raw_rows) > limit + 1:
        raise ValueError("too many Realm call rows")
    converted = [_realm_call_item_from_row(row) for row in raw_rows]
    seen: set[tuple[int, int, int]] = set()
    previous = None
    for item in converted:
        position = (item.block_height, item.tx_index, item.message_index)
        if position in seen or (previous is not None and position >= previous):
            raise ValueError("malformed Realm call ordering")
        if not detail.source.call_index_from_height <= item.block_height <= detail.source.call_index_through_height:
            raise ValueError("Realm call row outside coverage")
        seen.add(position); previous = position
    items, older = converted[:limit], len(converted) > limit
    tail = items[-1] if older and items else None
    return RealmCallsResponse(source=RealmCallSource(chain_id=detail.source.chain_id, path=requested_path,
        indexed_height=detail.source.indexed_height, from_height=detail.source.call_index_from_height,
        through_height=detail.source.call_index_through_height), items=items,
        pagination=RealmCallsPagination(limit=limit, next_before_height=tail.block_height if tail else None,
            next_before_tx_index=tail.tx_index if tail else None,
            next_before_message_index=tail.message_index if tail else None))
HEX_HASH_RE = re.compile(r"^(?:0[xX])?([0-9a-fA-F]{64})$")
SUMMARY_CORE_FIELDS = ("type", "category", "action", "label")
SUMMARY_FIELD_LIMITS = {"type": 160, "category": 64, "action": 64, "label": 80}
SUMMARY_MESSAGE_FIELDS = SUMMARY_CORE_FIELDS + (
    "sender", "recipient", "amount", "send", "package_path", "package_name",
    "function", "args_count", "file_count", "expires_at", "allow_paths_count",
    "spend_limit", "spend_period",
)
SUMMARY_SCALAR_STRING_LIMIT = 160


def _realm_catalog_item_from_row(row: dict) -> RealmCatalogItem:
    if (realm_path_kind(row["path"]) != row["path_kind"]
            or int(row["successful_call_count"]) + int(row["failed_call_count"])
            + int(row["unknown_result_call_count"]) != int(row["call_count"])):
        raise ValueError("malformed stored Realm catalog row")
    decided = int(row["successful_call_count"]) + int(row["failed_call_count"])
    return RealmCatalogItem(
        path=row["path"], name=row["path"].rsplit("/", 1)[-1], kind=row["path_kind"],
        rpc_visible=row["rpc_visible"], deployer_address=row["deployer_address"],
        deploy_height=row["deploy_height"], deploy_tx_index=row["deploy_tx_index"],
        first_seen_height=row["first_seen_height"], last_activity_height=row["last_activity_height"],
        last_activity_tx_index=row["last_activity_tx_index"],
        last_activity_at=isoformat_utc_z(row["last_activity_at"]) if row["last_activity_at"] else None,
        call_count=row["call_count"], successful_call_count=row["successful_call_count"],
        failed_call_count=row["failed_call_count"], unknown_result_call_count=row["unknown_result_call_count"],
        success_rate=None if decided == 0 else int(row["successful_call_count"]) / decided,
    )
SUMMARY_INTEGER_LIMIT = (1 << 255) - 1
SUMMARY_MAX_BYTES = 16384
JSONB_TIMESTAMP_RE = re.compile(
    r"^(?P<date>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})"
    r"(?:\.(?P<fraction>\d{1,6}))?"
    r"(?P<timezone>Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$"
)
DEFAULT_TRANSACTION_DETAIL_SUMMARY = object()


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
    if not validate_account_address(address, gno_profile(config.chain_id)):
        raise HTTPException(status_code=422, detail="Invalid account address")
    account_started_at = time.perf_counter()
    try:
        try:
            selected_rpc_url = database.fetch_selected_rpc_url(config.chain_id)
        except Exception:
            LOGGER.error("Account selected RPC query failed")
            raise HTTPException(status_code=503, detail=ACCOUNT_UNAVAILABLE_DETAIL) from None
        try:
            result = fetch_live_account(
                address, config, preferred_rpc_url=selected_rpc_url,
            )
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


@app.get(
    "/api/accounts/{address}/transactions",
    response_model=AccountTransactionsResponse,
)
def get_account_transactions(
    address: str,
    limit: int = Query(default=20, ge=1, le=100),
    before_height: int | None = Query(default=None, gt=0),
    before_tx_index: int | None = Query(default=None, ge=0),
) -> AccountTransactionsResponse:
    config = app.state.api_config
    if not validate_account_address(address, gno_profile(config.chain_id)):
        raise HTTPException(status_code=422, detail="Invalid account address")
    if (before_height is None) != (before_tx_index is None):
        raise HTTPException(
            status_code=422,
            detail="before_height and before_tx_index must be provided together",
        )
    try:
        rows = database.fetch_account_transactions(
            address, limit=limit, before_height=before_height,
            before_tx_index=before_tx_index,
        )
    except Exception:
        LOGGER.error("Explorer database Account transactions query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    try:
        page_rows = rows[:limit]
        last_row = page_rows[-1] if len(rows) > limit and page_rows else None
        return AccountTransactionsResponse(
            items=[
                _account_transaction_item_from_row(row, address, gno_profile(config.chain_id))
                for row in page_rows
            ],
            pagination=AccountTransactionsPagination(
                limit=limit,
                next_before_height=last_row["block_height"] if last_row else None,
                next_before_tx_index=last_row["tx_index"] if last_row else None,
            ),
        )
    except Exception:
        LOGGER.error("Explorer database Account transaction data is inconsistent")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


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


def _execution_fields_from_row(row: dict) -> dict:
    """Return only the bounded public execution-result projection."""
    return {field: row.get(field) for field in (
        "execution_status", "gas_wanted", "gas_used", "error", "log", "info",
    )}


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
                **_execution_fields_from_row(row),
            )
            for row in detail["transactions"]
        ],
    )


def _transaction_detail_from_row(
    row: dict,
    message_arguments=None,
    public_summary=DEFAULT_TRANSACTION_DETAIL_SUMMARY,
) -> TransactionDetailResponse:
    if public_summary is DEFAULT_TRANSACTION_DETAIL_SUMMARY:
        public_summary = _public_transaction_summary(row.get("payload_summary"))
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
        summary=public_summary,
        message_arguments=message_arguments,
        **_execution_fields_from_row(row),
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
        message_count=summary.message_count if summary is not None else None,
        **_execution_fields_from_row(row),
    )


def _account_transaction_item_from_row(row: dict, address: str, profile) -> AccountTransactionListItem:
    participation = row.get("participation")
    if not isinstance(participation, list) or not participation:
        raise ValueError("missing Account participation")
    indexed: set[tuple[int, str]] = set()
    for item in participation:
        if not isinstance(item, dict) or set(item) != {"message_index", "role"}:
            raise ValueError("malformed Account participation")
        message_index, role = item["message_index"], item["role"]
        if type(message_index) is not int or not 0 <= message_index <= 19:
            raise ValueError("invalid participant message index")
        if role not in ("sender", "recipient"):
            raise ValueError("invalid participant role")
        indexed.add((message_index, role))
    roles = {role for _, role in indexed}
    directions = {
        frozenset({"sender"}): "outgoing",
        frozenset({"recipient"}): "incoming",
        frozenset({"sender", "recipient"}): "self",
    }
    direction = directions.get(frozenset(roles))
    if direction is None:
        raise ValueError("invalid Account participation roles")
    summary = _public_transaction_summary(row.get("payload_summary"))
    message = None
    if summary is not None:
        for message_index, candidate in enumerate(summary.messages):
            if ((message_index, "sender") in indexed and candidate.sender == address) or (
                (message_index, "recipient") in indexed and candidate.recipient == address
            ):
                message = candidate
                break
    counterparty = None
    amount = None
    tx_type = "unknown"
    operation = "Transaction"
    if message is not None:
        tx_type, operation = message.type, message.label
        amount = message.amount if message.amount is not None else message.send
        candidate = message.recipient if direction == "outgoing" else message.sender
        if (direction != "self" and isinstance(candidate, str)
                and validate_account_address(candidate, profile)):
            counterparty = candidate
    return AccountTransactionListItem(
        block_height=row["block_height"], index=row["tx_index"],
        tx_hash=_normalize_tx_hash(row.get("tx_hash_hex")),
        block_time=isoformat_utc_z(row["time_utc"]), type=tx_type,
        operation=operation,
        message_count=summary.message_count if summary is not None else None,
        direction=direction, counterparty=counterparty, amount=amount,
        **_execution_fields_from_row(row),
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
            url=public_rpc_url(row["rpc_url"]),
            healthy=row["rpc_healthy"],
            catching_up=row["rpc_catching_up"],
            observed_height=row["rpc_observed_height"],
            lag=row["rpc_lag"],
            last_checked_at=isoformat_utc_z(row["rpc_last_checked_at"]),
            latency_ms=row["rpc_latency_ms"],
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
        average_block_time_intervals_seconds=[
            float(value)
            for value in (row.get("average_block_time_intervals_seconds") or [])
        ],
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
        rpc_pool=RpcPool(
            total=row["rpc_pool_total"],
            available=row["rpc_pool_available"],
            last_checked_at=isoformat_utc_z(row["rpc_pool_last_checked_at"]),
            endpoints=[RpcPoolEndpoint(
                **{
                    **endpoint,
                    "url": public_rpc_url(endpoint.get("url")),
                    "last_checked_at": _jsonb_timestamp_utc_z(endpoint.get("last_checked_at")),
                }
            ) for endpoint in (row["rpc_pool_endpoints"] or [])],
        ),
    )


def _jsonb_timestamp_utc_z(value: object) -> str | None:
    """Normalize a timestamp decoded either directly or through PostgreSQL JSONB."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return isoformat_utc_z(value)
    if not isinstance(value, str):
        raise ValueError("Invalid RPC endpoint timestamp")
    match = JSONB_TIMESTAMP_RE.fullmatch(value)
    if match is None:
        raise ValueError("Invalid RPC endpoint timestamp")
    fraction = match.group("fraction")
    normalized = match.group("date")
    if fraction is not None:
        normalized += f".{fraction.ljust(6, '0')}"
    timezone_suffix = match.group("timezone")
    normalized += "+00:00" if timezone_suffix == "Z" else timezone_suffix
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("Invalid RPC endpoint timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError("Invalid RPC endpoint timestamp")
    return isoformat_utc_z(parsed)


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



@app.get("/api/realms/detail", response_model=RealmDetailResponse)
def get_realm_detail(path: str = Query(..., min_length=1, max_length=256)) -> RealmDetailResponse:
    _validate_exact_catalog_path(path)
    try:
        result = database.fetch_realm_detail(chain_id=app.state.api_config.chain_id, path=path)
        if result is None or result.get("item") is None:
            raise HTTPException(status_code=404, detail="Realm catalog path not found")
        return _realm_detail_from_rows(requested_chain_id=app.state.api_config.chain_id, requested_path=path, result=result)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database Realm detail query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/realms/metadata/file", response_model=RealmMetadataFileResponse)
def get_realm_metadata_file(
    path: str = Query(..., min_length=1, max_length=256),
    filename: str = Query(..., min_length=1, max_length=160),
) -> RealmMetadataFileResponse:
    _validate_exact_catalog_path(path)
    if filename != filename.strip() or not filename.isprintable():
        raise HTTPException(status_code=422, detail="filename is invalid")
    try:
        row = database.fetch_realm_metadata_file(chain_id=app.state.api_config.chain_id, path=path, filename=filename)
        if row is None:
            raise HTTPException(status_code=404, detail="Realm metadata file not found")
        if (row.get("chain_id") != app.state.api_config.chain_id
                or row.get("path") != path or row.get("filename") != filename):
            raise ValueError("malformed Realm metadata file identity")
        return RealmMetadataFileResponse(**row)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database Realm metadata file query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/realms/metadata", response_model=RealmMetadataResponse)
def get_realm_metadata(path: str = Query(..., min_length=1, max_length=256)) -> RealmMetadataResponse:
    _validate_exact_catalog_path(path)
    try:
        result = database.fetch_realm_metadata(chain_id=app.state.api_config.chain_id, path=path)
        if result is None or result.get("metadata") is None:
            raise HTTPException(status_code=404, detail="Realm metadata not found")
        row = result["metadata"]
        if row.get("chain_id") != app.state.api_config.chain_id or row.get("path") != path:
            raise ValueError("malformed Realm metadata identity")
        summary_keys = ("file_count", "gno_file_count", "test_file_count", "has_gnomod",
            "total_file_bytes", "total_file_lines", "dependency_count", "qdoc_status", "qdoc_summary",
            "qpkg_json_status", "qpkg_json_summary", "qfuncs_status", "qfuncs_summary", "qrender_status",
            "qrender_byte_count", "qrender_line_count", "qrender_non_empty", "qstorage_status",
            "qstorage_bytes", "qstorage_deposit_ugnot")
        summary_values = {key: row[key] for key in summary_keys}
        capability_values = {
            "qdoc_status": ("qdoc_summary",),
            "qpkg_json_status": ("qpkg_json_summary",),
            "qfuncs_status": ("qfuncs_summary",),
            "qrender_status": ("qrender_byte_count", "qrender_line_count", "qrender_non_empty"),
            "qstorage_status": ("qstorage_bytes", "qstorage_deposit_ugnot"),
        }
        for status_key, value_keys in capability_values.items():
            if summary_values[status_key] != "ok":
                for value_key in value_keys:
                    summary_values[value_key] = None
        dependencies = result["dependencies"]
        return RealmMetadataResponse(chain_id=row["chain_id"], path=row["path"], kind=row["path_kind"],
            observed_height=row["observed_height"], collected_at=isoformat_utc_z(row["collected_at"]),
            collection_status=row["collection_status"],
            summary=RealmMetadataSummary(**summary_values), files=result["files"],
            dependencies=dependencies[:200], dependencies_truncated=len(dependencies) > 200)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database Realm metadata query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/realms/calls", response_model=RealmCallsResponse)
def get_realm_calls(
    path: str = Query(..., min_length=1, max_length=256),
    limit: int = Query(default=25, ge=1, le=100),
    before_height: int | None = Query(default=None, gt=0),
    before_tx_index: int | None = Query(default=None, ge=0),
    before_message_index: int | None = Query(default=None, ge=0, le=19),
) -> RealmCallsResponse:
    _validate_exact_catalog_path(path, expected_kind="realm")
    if sum(value is None for value in (before_height, before_tx_index, before_message_index)) not in (0, 3):
        raise HTTPException(status_code=422, detail="Realm call cursor fields must be supplied together")
    try:
        result = database.fetch_realm_calls(chain_id=app.state.api_config.chain_id, path=path, limit=limit,
            before_height=before_height, before_tx_index=before_tx_index, before_message_index=before_message_index)
        if result is None:
            raise HTTPException(status_code=404, detail="Realm catalog path not found")
        if result.get("source") is None:
            raise HTTPException(status_code=409, detail=CALLS_UNAVAILABLE_DETAIL)
        if type(result.get("coverage_available")) is not bool:
            raise ValueError("malformed Realm call coverage availability")
        if result["coverage_available"] is False:
            raise HTTPException(status_code=409, detail=CALLS_UNAVAILABLE_DETAIL)
        return _realm_calls_from_rows(requested_chain_id=app.state.api_config.chain_id, requested_path=path,
            limit=limit, result=result)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database Realm calls query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None

@app.get("/api/tokens", response_model=TokenDirectoryResponse)
def get_tokens(limit: int = Query(default=50, ge=1, le=100), q: str | None = Query(default=None, min_length=1, max_length=128),
               activity_window: Literal["24h", "7d", "30d"] = Query(default="24h"),
               before_activity_height: int | None = Query(default=None, ge=-1),
               before_path: str | None = Query(default=None, min_length=1, max_length=256)) -> TokenDirectoryResponse:
    """Return confirmed GRC20 Realm tokens using persisted metadata only."""
    if (before_activity_height is None) != (before_path is None):
        raise HTTPException(status_code=422, detail="both token cursor fields are required")
    if activity_window not in TOKEN_ACTIVITY_WINDOWS:
        raise HTTPException(status_code=422, detail="unsupported token activity window")
    search = q.strip().casefold() if q else None
    if q is not None and not search:
        raise HTTPException(status_code=422, detail="q must not be blank")
    try:
        result = database.fetch_token_candidates(chain_id=app.state.api_config.chain_id,
                                                   window_hours=TOKEN_ACTIVITY_WINDOWS[activity_window],
                                                   candidate_limit=TOKEN_CANDIDATE_LIMIT + 1)
        if result is None:
            raise HTTPException(status_code=404, detail="Token directory is not available yet")
        grouped = {row["path"]: {**row, "files": []} for row in result["candidates"]}
        for file in result["files"]:
            if file["path"] not in grouped:
                raise ValueError("token source file without candidate")
            grouped[file["path"]]["files"].append(file)
        if len(grouped) > TOKEN_CANDIDATE_LIMIT:
            raise ValueError("confirmed token candidate bound exceeded")
        items = []
        verified_rows = []
        verified_by_path = {}
        for row in grouped.values():
            identity = extract_token_identity(row["files"])
            if not identity.verified:
                continue
            verified_rows.append(row)
            verified_by_path[row["path"]] = (row, identity)
            key = namespace_key(row["path"])
            decided = int(row["successful_call_count"]) + int(row["failed_call_count"])
            item = TokenDirectoryItem(path=row["path"], namespace_key=key,
                application=dict(REALM_APPLICATION_REGISTRY[key]) if key in REALM_APPLICATION_REGISTRY else None,
                name=identity.name, symbol=identity.symbol, decimals=identity.decimals,
                identity_verified=identity.verified, rpc_visible=row["rpc_visible"],
                direct_call_count=int(row["call_count"]), successful_call_count=int(row["successful_call_count"]),
                failed_call_count=int(row["failed_call_count"]),
                success_rate=int(row["successful_call_count"]) / decided if decided else None,
                last_activity_height=row["last_activity_height"],
                last_activity_at=isoformat_utc_z(row["last_activity_at"]) if row["last_activity_at"] else None,
                metadata_observed_height=int(row["metadata_observed_height"]))
            if search and not any(search in value.casefold() for value in
                                  (item.path, item.namespace_key, item.name or "", item.symbol or "")):
                continue
            position = item.last_activity_height if item.last_activity_height is not None else -1
            if before_activity_height is not None and not (position < before_activity_height or
                    (position == before_activity_height and item.path > before_path)):
                continue
            items.append(item)
        items.sort(key=lambda item: (-(item.last_activity_height if item.last_activity_height is not None else -1), item.path))
        page, tail = items[:limit], (items[limit - 1] if len(items) > limit else None)
        active_count = _active_token_count(result["source"], verified_rows)
        top_activity = None
        if result.get("activity_available") is True:
            ranked = []
            for activity in result.get("activity", []):
                verified = verified_by_path.get(activity["path"])
                if verified is None:
                    continue
                _, identity = verified
                key = namespace_key(activity["path"])
                successful = int(activity["successful_call_count"])
                failed = int(activity["failed_call_count"])
                unknown = int(activity["unknown_result_call_count"])
                direct = int(activity["direct_call_count"])
                if min(successful, failed, unknown) < 0 or successful + failed + unknown != direct:
                    raise ValueError("malformed token activity execution counts")
                decided = successful + failed
                ranked.append(TokenTopActivityItem(
                    path=activity["path"], namespace_key=key,
                    application=dict(REALM_APPLICATION_REGISTRY[key]) if key in REALM_APPLICATION_REGISTRY else None,
                    name=identity.name, symbol=identity.symbol, decimals=identity.decimals,
                    direct_call_count=direct,
                    successful_call_count=successful,
                    failed_call_count=failed,
                    unknown_result_call_count=unknown,
                    success_rate=successful / decided if decided else None,
                    last_activity_height=int(activity["last_activity_height"]),
                    last_activity_at=isoformat_utc_z(activity["last_activity_at"])))
            ranked.sort(key=lambda item: (-item.direct_call_count,
                                          -item.last_activity_height, item.path))
            top_activity = ranked[:3]
        source = result["source"]
        hour_windows = {24: "24h", 168: "7d", 720: "30d"}
        available_windows = [hour_windows[hours] for hours in source.get("available_activity_hours", ())]
        metadata_height = source.get("metadata_observed_height")
        return TokenDirectoryResponse(source=TokenDirectorySource(chain_id=source["chain_id"],
            indexed_height=source["indexed_height"], catalog_observed_height=source["catalog_observed_height"],
            metadata_observed_height=metadata_height, activity_window=activity_window,
            available_activity_windows=available_windows),
            summary=TokenDirectorySummary(token_count=len(verified_rows), active_24h_count=active_count), items=page,
            top_activity=top_activity,
            pagination=TokenDirectoryPagination(next_before_activity_height=(tail.last_activity_height
                if tail and tail.last_activity_height is not None else (-1 if tail else None)),
                next_before_path=tail.path if tail else None))
    except HTTPException:
        raise
    except Exception:
        LOGGER.exception("Explorer database token directory query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/assets", response_model=AssetDirectoryResponse)
def get_assets(limit: int = Query(default=50, ge=1, le=100),
               q: str | None = Query(default=None, min_length=1, max_length=128),
               standard: Literal["all", "grc20", "grc721"] = Query(default="all"),
               before_activity_height: int | None = Query(default=None, ge=-1),
               before_path: str | None = Query(default=None, min_length=1, max_length=256)) -> AssetDirectoryResponse:
    """Return source-verified GRC20 tokens and GRC721 collections from persisted metadata."""
    if (before_activity_height is None) != (before_path is None):
        raise HTTPException(status_code=422, detail="both asset cursor fields are required")
    search = q.strip().casefold() if q else None
    if q is not None and not search:
        raise HTTPException(status_code=422, detail="q must not be blank")
    try:
        result = database.fetch_asset_candidates(chain_id=app.state.api_config.chain_id,
                                                   candidate_limit=ASSET_CANDIDATE_LIMIT + 1)
        if result is None:
            raise HTTPException(status_code=404, detail="Asset directory is not available yet")
        verified: list[AssetDirectoryItem] = []
        seen: set[tuple[str, str]] = set()
        standards_by_path: dict[str, set[str]] = {}
        for candidate in result["candidates"]:
            standards_by_path.setdefault(candidate["path"], set()).add(candidate["standard"])
        chain_id = app.state.api_config.chain_id
        cache_keys: dict[tuple[str, str], tuple[str, str, str, int]] = {}
        static_results: dict[tuple[str, str], StaticAssetClassification] = {}
        misses: dict[tuple[str, str], dict] = {}
        for row in result["candidates"]:
            pair = (row["path"], row["standard"])
            if pair in cache_keys or len(standards_by_path[row["path"]]) != 1:
                continue
            key = (chain_id, row["path"], row["standard"], int(row["metadata_observed_height"]))
            cache_keys[pair] = key
            cached = asset_classification_cache.get(key)
            if cached is None:
                misses[pair] = row
            else:
                static_results[pair] = cached
        files_by_path: dict[str, list[dict]] = {}
        if misses:
            miss_paths = sorted({path for path, _ in misses})
            for file in database.fetch_asset_candidate_files(chain_id=chain_id, paths=miss_paths):
                files_by_path.setdefault(file["path"], []).append(file)
            for pair, row in misses.items():
                files = files_by_path.get(row["path"], [])
                revision = int(row["metadata_observed_height"])
                # A concurrent metadata refresh is retried on the next request, never cached under a stale revision.
                if files and any(int(file["metadata_observed_height"]) != revision for file in files):
                    continue
                if row["standard"] == "grc20":
                    identity = extract_token_identity(files)
                    classification = StaticAssetClassification(identity.verified, identity.name, identity.symbol,
                        identity.decimals, "verified" if identity.verified else "identity_unverified")
                elif row["standard"] == "grc721":
                    result_classification = classify_grc721(files, qfunc_names=set(row.get("qfunc_names") or ()))
                    identity = result_classification.identity
                    classification = StaticAssetClassification(result_classification.status == "verified",
                        identity.name, identity.symbol, None, result_classification.reason)
                else:
                    raise ValueError("unknown asset standard")
                static_results[pair] = classification
                asset_classification_cache.put(cache_keys[pair], classification)
        for row in result["candidates"]:
            if len(standards_by_path[row["path"]]) != 1:
                continue
            key_tuple = (row["path"], row["standard"])
            if key_tuple in seen:
                continue
            seen.add(key_tuple)
            classification = static_results.get(key_tuple)
            if classification is None or not classification.verified:
                continue
            name, symbol, decimals = classification.name, classification.symbol, classification.decimals
            namespace = namespace_key(row["path"])
            decided = int(row["successful_call_count"]) + int(row["failed_call_count"])
            verified.append(AssetDirectoryItem(
                path=row["path"], namespace_key=namespace,
                application=dict(REALM_APPLICATION_REGISTRY[namespace]) if namespace in REALM_APPLICATION_REGISTRY else None,
                name=name, symbol=symbol, standard=row["standard"], decimals=decimals,
                token_count=None, identity_verified=True, rpc_visible=row["rpc_visible"],
                direct_call_count=int(row["call_count"]),
                successful_call_count=int(row["successful_call_count"]),
                failed_call_count=int(row["failed_call_count"]),
                success_rate=int(row["successful_call_count"]) / decided if decided else None,
                last_activity_height=row["last_activity_height"],
                last_activity_at=isoformat_utc_z(row["last_activity_at"]) if row["last_activity_at"] else None,
                metadata_observed_height=int(row["metadata_observed_height"])))
        counts = {kind: sum(item.standard == kind for item in verified) for kind in ("grc20", "grc721")}
        visible = [item for item in verified if standard == "all" or item.standard == standard]
        if search:
            visible = [item for item in visible if any(search in value.casefold()
                       for value in (item.path, item.name, item.symbol))]
        if before_activity_height is not None:
            visible = [item for item in visible if
                       (item.last_activity_height if item.last_activity_height is not None else -1) < before_activity_height or
                       ((item.last_activity_height if item.last_activity_height is not None else -1) == before_activity_height
                        and item.path > before_path)]
        visible.sort(key=lambda item: (-(item.last_activity_height if item.last_activity_height is not None else -1),
                                       item.path, item.standard))
        page = visible[:limit]
        tail = page[-1] if len(visible) > limit else None
        source = result["source"]
        return AssetDirectoryResponse(
            source=AssetDirectorySource(chain_id=source["chain_id"], indexed_height=source["indexed_height"],
                catalog_observed_height=source["catalog_observed_height"],
                metadata_observed_height=source.get("metadata_observed_height")),
            summary=AssetDirectorySummary(asset_count=counts["grc20"] + counts["grc721"],
                grc20_count=counts["grc20"], grc721_count=counts["grc721"]),
            items=page, pagination=TokenDirectoryPagination(
                next_before_activity_height=(tail.last_activity_height if tail and tail.last_activity_height is not None else (-1 if tail else None)),
                next_before_path=tail.path if tail else None))
    except HTTPException:
        raise
    except Exception:
        LOGGER.exception("Explorer database asset directory query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/tokens/native", response_model=NativeTokenResponse)
def get_native_token() -> NativeTokenResponse:
    """Return fixed native GNOT metadata and a best-effort bank supply lookup."""
    key = (app.state.api_config.chain_id, f"native:{NATIVE_GNOT_DENOM}")
    raw = token_supply_cache.get(key)
    if raw is None:
        try:
            rpc_url = database.fetch_selected_rpc_url(app.state.api_config.chain_id)
            if rpc_url is None:
                rpc_url = next(iter(app.state.api_config.rpc_urls), None)
            if rpc_url is not None:
                raw = query_native_gnot_supply(rpc_url=rpc_url)
        except Exception:
            LOGGER.warning("Native GNOT supply RPC query failed")
        if raw is not None:
            token_supply_cache.put(key, raw)
    return NativeTokenResponse(name="GNOT", symbol="GNOT", type="Native",
        base_denom=NATIVE_GNOT_DENOM, decimals=NATIVE_GNOT_DECIMALS,
        raw_total_supply=raw,
        total_supply=decimal_amount(raw, NATIVE_GNOT_DECIMALS) if raw is not None else None,
        available=raw is not None)


def _verified_token_identity(path: str):
    """Prove exact membership using bounded persisted source and directory identity rules."""
    result = database.fetch_verified_token_candidate(chain_id=app.state.api_config.chain_id, path=path)
    if result is None:
        raise HTTPException(status_code=404, detail="Verified token not found")
    identity = extract_token_identity(result["files"])
    if not identity.verified:
        raise HTTPException(status_code=404, detail="Verified token not found")
    return identity


@app.get("/api/tokens/supply", response_model=TokenSupplyResponse)
def get_token_supply(path: str = Query(..., min_length=1, max_length=256)) -> TokenSupplyResponse:
    """Return runtime TotalSupply for one already verified directory token."""
    _validate_exact_catalog_path(path, expected_kind="realm")
    try:
        identity = _verified_token_identity(path)
        key = (app.state.api_config.chain_id, path)
        raw = token_supply_cache.get(key)
        if raw is None:
            try:
                rpc_url = database.fetch_selected_rpc_url(app.state.api_config.chain_id)
                if rpc_url is None:
                    rpc_url = next(iter(app.state.api_config.rpc_urls), None)
                if rpc_url is not None:
                    raw = query_total_supply(rpc_url=rpc_url, path=path)
            except Exception:
                LOGGER.warning("Token TotalSupply RPC query failed")
            if raw is not None:
                token_supply_cache.put(key, raw)
        available = raw is not None
        return TokenSupplyResponse(path=path, raw_total_supply=raw, decimals=identity.decimals,
            total_supply=decimal_amount(raw, identity.decimals) if available else None,
            symbol=identity.symbol, available=available)
    except HTTPException:
        raise
    except Exception:
        LOGGER.exception("Explorer database token verification query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None

@app.get("/api/realms", response_model=RealmCatalogResponse)
def get_realms(
    limit: int = Query(default=25, ge=1, le=100),
    kind: str = Query(default="all", pattern=r"^(all|realm|package)$"),
    q: str | None = Query(default=None),
    before_activity_height: int | None = Query(default=None, ge=-1),
    before_path: str | None = Query(default=None),
) -> RealmCatalogResponse:
    if (before_activity_height is None) != (before_path is None):
        raise HTTPException(status_code=422, detail="Realm cursor fields must be supplied together")
    if q is not None:
        q = q.strip()
        if not 1 <= len(q) <= 128 or any(not (' ' <= char <= '~') for char in q):
            raise HTTPException(status_code=422, detail="q must be 1 through 128 printable characters")
    if before_path is not None:
        if realm_path_kind(before_path) is None:
            raise HTTPException(status_code=422, detail="before_path is invalid")
    try:
        result = database.fetch_realm_catalog(chain_id=app.state.api_config.chain_id,
            limit=limit, kind=kind, q=q,
            before_activity_height=before_activity_height, before_path=before_path)
        if result is None:
            raise HTTPException(status_code=404, detail="Realm catalog not found")
        rows, older = result["items"], len(result["items"]) > limit
        rows = rows[:limit]
        items = [_realm_catalog_item_from_row(row) for row in rows]
        source = result["summary"]
        summary = RealmCatalogSummary(total_items=source["total_items"], total_realms=source["total_realms"],
            total_packages=source["total_packages"], rpc_visible_items=source["rpc_visible_items"],
            active_24h=source["active_24h"], indexed_height=source["indexed_height"],
            catalog_observed_height=source["observed_height"], catalog_refreshed_at=isoformat_utc_z(source["refreshed_at"]),
            activity_from_height=source["activity_from_height"], activity_through_height=source["activity_through_height"])
        tail = rows[-1] if older else None
        return RealmCatalogResponse(summary=summary, items=items, pagination=RealmCatalogPagination(
            next_before_activity_height=tail["last_activity_height"] if tail and tail["last_activity_height"] is not None else (-1 if tail else None),
            next_before_path=tail["path"] if tail else None))
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database Realm catalog query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/realms/top", response_model=RealmTopResponse)
def get_top_realms(limit: int = Query(default=5, ge=1, le=10)) -> RealmTopResponse:
    try:
        result = database.fetch_top_realms(chain_id=app.state.api_config.chain_id, limit=limit)
        if result is None:
            raise HTTPException(status_code=404, detail="Realm catalog not found")
        items = [_realm_catalog_item_from_row(row) for row in result["items"]]
        if len(items) > limit or len({item.path for item in items}) != len(items):
            raise ValueError("malformed Realm ranking")
        previous = None
        for item in items:
            key = (-item.call_count, -(item.last_activity_height if item.last_activity_height is not None else -1), item.path)
            if item.kind != "realm" or not item.rpc_visible or item.call_count <= 0 or (previous is not None and key < previous):
                raise ValueError("malformed Realm ranking")
            previous = key
        source = result["source"]
        return RealmTopResponse(source=RealmRankingSource(
            chain_id=source["chain_id"], indexed_height=source["indexed_height"],
            catalog_observed_height=source["observed_height"], activity_from_height=source["activity_from_height"],
            activity_through_height=source["activity_through_height"],
        ), items=items)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database Realm ranking query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


def _namespace_rate(success: int, failed: int) -> float | None:
    return success / (success + failed) if success + failed else None


def _validate_activity_tuple(height, tx_index, timestamp, *, required: bool) -> None:
    all_null = height is None and tx_index is None and timestamp is None
    all_present = (type(height) is int and height > 0 and type(tx_index) is int and tx_index >= 0
                   and isinstance(timestamp, datetime))
    if not (all_present if required else all_null):
        raise ValueError("inconsistent activity tuple")


_APPLICATION_WINDOW_HOURS = {"24h": 24, "7d": 24 * 7, "30d": 24 * 30}


def _validate_realm_application_source(source: dict, *, chain_id: str, window: str) -> list[str]:
    indexed = source["indexed_height"]
    from_height = source["call_index_from_height"]
    through_height = source["call_index_through_height"]
    timestamps = tuple(source[name] for name in ("coverage_start_at", "window_start_at", "window_end_at"))
    if (source["chain_id"] != chain_id
            or any(type(value) is not int or value <= 0 for value in (indexed, from_height, through_height))
            or from_height > through_height or through_height != indexed
            or any(not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None
                   for value in timestamps)):
        raise ValueError("invalid application ranking source")
    coverage_start, window_start, window_end = timestamps
    expected_duration = timedelta(hours=_APPLICATION_WINDOW_HOURS[window])
    if not coverage_start <= window_start <= window_end or window_end - window_start != expected_duration:
        raise ValueError("invalid application ranking window")
    available_hours = source["available_hours"]
    if (not isinstance(available_hours, (tuple, list))
            or any(type(value) is not int or value not in _APPLICATION_WINDOW_HOURS.values()
                   for value in available_hours)
            or len(set(available_hours)) != len(available_hours)):
        raise ValueError("invalid available application windows")
    available = [key for key, hours in _APPLICATION_WINDOW_HOURS.items() if hours in available_hours]
    if window not in available:
        raise ValueError("selected application window is unavailable")
    return available


@app.get("/api/realm-applications/top", response_model=RealmApplicationTopResponse)
def get_top_realm_applications(
    limit: int = Query(default=3, ge=1, le=10),
    window: Literal["24h", "7d", "30d"] = Query(default="24h"),
) -> RealmApplicationTopResponse:
    try:
        result = database.fetch_top_realm_applications(
            chain_id=app.state.api_config.chain_id, limit=limit, window_hours=_APPLICATION_WINDOW_HOURS[window])
        if result is None:
            raise HTTPException(status_code=404, detail="Realm catalog not found")
        if result.get("coverage_available") is not True:
            raise HTTPException(status_code=409, detail=APPLICATION_WINDOW_UNAVAILABLE_DETAIL)
        source = result["source"]
        available = _validate_realm_application_source(
            source, chain_id=app.state.api_config.chain_id, window=window)
        items, previous, seen = [], None, set()
        for row in result["items"]:
            key = row["namespace_key"]
            counts = [row[name] for name in ("realm_count", "rpc_visible_realm_count", "called_realm_count",
                "direct_call_count", "successful_call_count", "failed_call_count", "unknown_result_call_count")]
            if (namespace_key(f"gno.land/r/{key}") != key or key in seen
                    or any(type(value) is not int or value < 0 for value in counts)
                    or min(counts[:4]) < 1
                    or sum(counts[4:]) != row["direct_call_count"]
                    or row["called_realm_count"] > row["realm_count"]
                    or row["rpc_visible_realm_count"] > row["realm_count"]):
                raise ValueError("invalid application ranking row")
            seen.add(key)
            activity = (row["last_activity_height"], row["last_activity_tx_index"],
                        row["last_activity_message_index"], row["last_activity_at"])
            if (type(activity[0]) is not int or activity[0] <= 0 or type(activity[1]) is not int or activity[1] < 0
                    or type(activity[2]) is not int or not 0 <= activity[2] <= 19 or not isinstance(activity[3], datetime)):
                raise ValueError("invalid application activity")
            order = (-row["direct_call_count"], -activity[0], -activity[1], -activity[2], key)
            if previous is not None and order < previous:
                raise ValueError("invalid application ranking order")
            previous = order
            application = REALM_APPLICATION_REGISTRY.get(key)
            items.append(RealmApplicationTopItem(
                namespace_key=key, application=dict(application) if application else None,
                realm_count=row["realm_count"], rpc_visible_realm_count=row["rpc_visible_realm_count"],
                called_realm_count=row["called_realm_count"], direct_call_count=row["direct_call_count"],
                successful_call_count=row["successful_call_count"], failed_call_count=row["failed_call_count"],
                unknown_result_call_count=row["unknown_result_call_count"],
                success_rate=_namespace_rate(row["successful_call_count"], row["failed_call_count"]),
                last_activity_height=activity[0], last_activity_tx_index=activity[1],
                last_activity_message_index=activity[2], last_activity_at=isoformat_utc_z(activity[3])))
        if len(items) > limit:
            raise ValueError("unbounded application ranking")
        return RealmApplicationTopResponse(source=RealmApplicationRankingSource(
            chain_id=source["chain_id"], indexed_height=source["indexed_height"],
            call_index_from_height=source["call_index_from_height"],
            call_index_through_height=source["call_index_through_height"],
            coverage_start_at=isoformat_utc_z(source["coverage_start_at"]),
            window_start_at=isoformat_utc_z(source["window_start_at"]),
            window_end_at=isoformat_utc_z(source["window_end_at"]), window=window,
            available_windows=available), items=items)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database Realm application ranking query failed")
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None


@app.get("/api/realm-namespaces/top", response_model=RealmNamespaceTopResponse)
def get_top_realm_namespaces(
    limit: int = Query(default=5, ge=1, le=10),
    scope: Literal["all", "curated"] = Query(default="all"),
) -> RealmNamespaceTopResponse:
    try:
        result = database.fetch_top_realm_namespaces(chain_id=app.state.api_config.chain_id, limit=limit,
            curated_only=scope == "curated", curated_namespace_keys=CURATED_NAMESPACE_KEYS)
        if result is None:
            raise HTTPException(status_code=404, detail="Realm catalog not found")
        grouped = {key: [] for key in (row["namespace_key"] for row in result["items"])}
        for row in result["members"]:
            if row.get("namespace_key") not in grouped:
                raise ValueError("unexpected namespace member")
            grouped[row["namespace_key"]].append(row)
        items, previous, seen = [], None, set()
        for row in result["items"]:
            key = row["namespace_key"]
            if namespace_key(f"gno.land/r/{key}") != key or key in seen:
                raise ValueError("invalid namespace")
            seen.add(key)
            counts = [row[name] for name in ("realm_count", "called_realm_count", "rpc_visible_realm_count",
                "direct_call_count", "successful_call_count", "failed_call_count", "unknown_result_call_count")]
            if any(type(value) is not int or value < 0 for value in counts):
                raise ValueError("invalid counts")
            realm_count, called, visible, direct, successful, failed, unknown = counts
            if not (realm_count > 0 and 0 < called <= realm_count and 0 < visible <= realm_count and direct > 0
                    and successful + failed + unknown == direct):
                raise ValueError("inconsistent counts")
            activity = (row["last_activity_height"], row["last_activity_tx_index"], row["last_activity_at"])
            _validate_activity_tuple(*activity, required=True)
            latest_path = row["latest_activity_path"]
            if (row.get("latest_activity_path_kind") != "realm" or namespace_key(latest_path) != key or
                    type(row.get("latest_activity_call_count")) is not int or row["latest_activity_call_count"] <= 0):
                raise ValueError("invalid latest activity Realm")
            first_seen = row["first_seen_height"]
            if first_seen is not None and (type(first_seen) is not int or first_seen <= 0):
                raise ValueError("invalid first seen height")
            order = (-direct, -(activity[0] if activity[0] is not None else -1), key)
            if previous is not None and order < previous:
                raise ValueError("invalid ranking order")
            previous = order
            members = grouped[key]
            paths, converted = [], []
            for member in members:
                path = member["path"]
                if member.get("path_kind") != "realm" or namespace_key(path) != key or path in paths:
                    raise ValueError("invalid member")
                paths.append(path)
                member_counts = [member[n] for n in ("call_count", "successful_call_count", "failed_call_count", "unknown_result_call_count")]
                if any(type(v) is not int or v < 0 for v in member_counts) or sum(member_counts[1:]) != member_counts[0]:
                    raise ValueError("invalid member counts")
                member_activity = (member["last_activity_height"], member["last_activity_tx_index"], member["last_activity_at"])
                _validate_activity_tuple(*member_activity, required=member_counts[0] > 0)
                member_first_seen = member["first_seen_height"]
                if member_first_seen is not None and (type(member_first_seen) is not int or member_first_seen <= 0):
                    raise ValueError("invalid member first seen height")
                converted.append(RealmNamespaceMember(path=path, rpc_visible=member["rpc_visible"],
                    first_seen_height=member_first_seen, last_activity_height=member_activity[0],
                    last_activity_tx_index=member_activity[1], last_activity_at=isoformat_utc_z(member_activity[2]) if member_activity[2] is not None else None,
                    call_count=member_counts[0], successful_call_count=member_counts[1], failed_call_count=member_counts[2],
                    unknown_result_call_count=member_counts[3], success_rate=_namespace_rate(member_counts[1], member_counts[2])))
            if paths != sorted(paths) or len(members) != min(realm_count, 100):
                raise ValueError("invalid member bounds")
            truncated = realm_count > len(members)
            if not truncated and (sum(m["call_count"] for m in members) != direct or
                sum(m["successful_call_count"] for m in members) != successful or
                sum(m["failed_call_count"] for m in members) != failed or sum(m["unknown_result_call_count"] for m in members) != unknown or
                sum(bool(m["rpc_visible"]) for m in members) != visible or sum(m["call_count"] > 0 for m in members) != called):
                raise ValueError("aggregate mismatch")
            if not truncated:
                member_first_seen = [m["first_seen_height"] for m in members if m["first_seen_height"] is not None]
                if (min(member_first_seen) if member_first_seen else None) != first_seen:
                    raise ValueError("aggregate first seen mismatch")
                newest = min((m for m in members if m["call_count"] > 0),
                    key=lambda m: (-m["last_activity_height"], -m["last_activity_tx_index"], m["path"]))
                if (newest["path"], newest["last_activity_height"], newest["last_activity_tx_index"], newest["last_activity_at"]) != (
                        latest_path, activity[0], activity[1], activity[2]):
                    raise ValueError("aggregate latest activity mismatch")
                if row["latest_activity_call_count"] != newest["call_count"]:
                    raise ValueError("aggregate latest activity call count mismatch")
            else:
                returned_latest = next((member for member in members if member["path"] == latest_path), None)
                if returned_latest is not None and row["latest_activity_call_count"] != returned_latest["call_count"]:
                    raise ValueError("truncated latest activity call count mismatch")
            application = REALM_APPLICATION_REGISTRY.get(key)
            if scope == "curated" and application is None:
                raise ValueError("uncurated result")
            items.append(RealmNamespaceTopItem(namespace_key=key, application=dict(application) if application else None,
                realm_count=realm_count, called_realm_count=called, rpc_visible_realm_count=visible,
                direct_call_count=direct, successful_call_count=successful, failed_call_count=failed,
                unknown_result_call_count=unknown, success_rate=_namespace_rate(successful, failed),
                first_seen_height=first_seen, last_activity_height=activity[0], last_activity_tx_index=activity[1],
                last_activity_at=isoformat_utc_z(activity[2]) if activity[2] is not None else None, realms=converted, realms_truncated=truncated))
        if len(items) > limit:
            raise ValueError("too many namespaces")
        source = result["source"]
        return RealmNamespaceTopResponse(source=RealmRankingSource(chain_id=source["chain_id"], indexed_height=source["indexed_height"],
            catalog_observed_height=source["observed_height"], activity_from_height=source["activity_from_height"],
            activity_through_height=source["activity_through_height"]), scope=scope, items=items)
    except HTTPException:
        raise
    except Exception:
        LOGGER.error("Explorer database Realm namespace ranking query failed")
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
    public_summary = _public_transaction_summary(row.get("payload_summary"))
    raw_base64 = row.get("raw_base64")
    decoded_byte_length = row.get("decoded_byte_length")
    has_visible_call = (
        public_summary is not None
        and public_summary.parse_status == "parsed"
        and bool(public_summary.messages)
        and any(message.type == "gno.vm.MsgCall" for message in public_summary.messages)
    )
    message_arguments = None
    if (
        has_visible_call
        and type(raw_base64) is str
        and bool(raw_base64)
        and type(decoded_byte_length) is int
    ):
        try:
            message_arguments = decode_transaction_arguments(
                raw_base64,
                decoded_byte_length,
                app.state.api_config,
            )
        except Exception:
            LOGGER.warning("Transaction argument detail decoding failed")
    return _transaction_detail_from_row(row, message_arguments, public_summary)


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
    except Exception as exc:
        stack = " | ".join(
            f"{frame.filename}:{frame.lineno} in {frame.name}"
            for frame in traceback.extract_tb(exc.__traceback__)
        )
        LOGGER.error("Explorer database block detail query failed; traceback=%s", stack)
        raise HTTPException(status_code=503, detail=UNAVAILABLE_DETAIL) from None
    if detail is None:
        raise HTTPException(status_code=404, detail="Block not found")
    return _block_detail_from_row(detail)
