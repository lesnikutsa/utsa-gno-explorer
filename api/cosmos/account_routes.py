"""FastAPI router for live Cosmos account, transaction, and governance data."""

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from .account_activity import CosmosAccountActivityResponse, load_account_activity
from .account_detail import CosmosAccountDetailResponse, load_account_snapshot
from .errors import AllEndpointsUnavailable
from .governance import (
    CosmosGovernanceDetailResponse,
    CosmosGovernancePageResponse,
    CosmosGovernanceVotesResponse,
    load_governance_detail,
    load_governance_page,
    load_governance_votes,
)
from .registry import get_network
from .transaction_endpoint_policy import CosmosTransactionHistoryResponse


LOGGER = logging.getLogger(__name__)
router = APIRouter()


def _service(request: Request, network_id: str):
    if get_network(network_id) is None:
        raise HTTPException(status_code=404, detail="Unknown network")
    services = getattr(request.app.state, "cosmos_services", None)
    if not isinstance(services, dict) or network_id not in services:
        raise HTTPException(status_code=503, detail="Network data is temporarily unavailable")
    return services[network_id]


@router.get("/api/networks/{network_id}/endpoint-status")
async def get_cosmos_endpoint_status(request: Request, network_id: str):
    service = _service(request, network_id)
    try:
        return await service.endpoint_status()
    except Exception:
        LOGGER.info("Cosmos endpoint status failed network=%s reason=upstream_unavailable", network_id)
        raise HTTPException(status_code=503, detail="Endpoint status is temporarily unavailable") from None


@router.get(
    "/api/networks/{network_id}/governance",
    response_model=CosmosGovernancePageResponse,
    response_model_exclude_none=True,
)
async def get_cosmos_governance(request: Request, network_id: str):
    service = _service(request, network_id)
    try:
        return await load_governance_page(service)
    except AllEndpointsUnavailable:
        raise HTTPException(status_code=503, detail="Governance data is temporarily unavailable") from None
    except Exception:
        LOGGER.info("Cosmos governance failed network=%s reason=upstream_unavailable", network_id)
        raise HTTPException(status_code=503, detail="Governance data is temporarily unavailable") from None


@router.get(
    "/api/networks/{network_id}/governance/{proposal_id}",
    response_model=CosmosGovernanceDetailResponse,
    response_model_exclude_none=True,
)
async def get_cosmos_governance_detail(request: Request, network_id: str, proposal_id: int):
    service = _service(request, network_id)
    try:
        return await load_governance_detail(service, proposal_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid governance proposal ID") from None
    except AllEndpointsUnavailable:
        raise HTTPException(status_code=503, detail="Governance proposal is temporarily unavailable") from None
    except Exception:
        LOGGER.info("Cosmos governance detail failed network=%s proposal=%s reason=upstream_unavailable", network_id, proposal_id)
        raise HTTPException(status_code=503, detail="Governance proposal is temporarily unavailable") from None


@router.get(
    "/api/networks/{network_id}/governance/{proposal_id}/votes",
    response_model=CosmosGovernanceVotesResponse,
    response_model_exclude_none=True,
)
async def get_cosmos_governance_votes(request: Request, network_id: str, proposal_id: int):
    service = _service(request, network_id)
    try:
        return await load_governance_votes(service, proposal_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid governance proposal ID") from None
    except AllEndpointsUnavailable:
        raise HTTPException(status_code=503, detail="Governance votes are temporarily unavailable") from None
    except Exception:
        LOGGER.info("Cosmos governance votes failed network=%s proposal=%s reason=upstream_unavailable", network_id, proposal_id)
        raise HTTPException(status_code=503, detail="Governance votes are temporarily unavailable") from None


@router.get(
    "/api/networks/{network_id}/accounts/{address}",
    response_model=CosmosAccountDetailResponse,
    response_model_exclude_none=True,
)
async def get_cosmos_account_detail(request: Request, network_id: str, address: str):
    service = _service(request, network_id)
    try:
        return await load_account_snapshot(service, address)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account address") from None
    except AllEndpointsUnavailable:
        raise HTTPException(status_code=503, detail="Account data is temporarily unavailable") from None
    except Exception:
        LOGGER.info("Cosmos account detail failed network=%s reason=upstream_unavailable", network_id)
        raise HTTPException(status_code=503, detail="Account data is temporarily unavailable") from None


@router.get(
    "/api/networks/{network_id}/accounts/{address}/activity",
    response_model=CosmosAccountActivityResponse,
    response_model_exclude_none=True,
)
async def get_cosmos_account_activity(
        request: Request, network_id: str, address: str,
        limit: int = Query(default=10, ge=1, le=10),
        page: int = Query(default=1, ge=1, le=5)):
    service = _service(request, network_id)
    try:
        return await load_account_activity(service, address, limit, page)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid account activity request") from None
    except AllEndpointsUnavailable:
        raise HTTPException(status_code=503, detail="Account activity is temporarily unavailable") from None
    except Exception:
        LOGGER.info("Cosmos account activity failed network=%s reason=upstream_unavailable", network_id)
        raise HTTPException(status_code=503, detail="Account activity is temporarily unavailable") from None


@router.get(
    "/api/networks/{network_id}/transactions/history",
    response_model=CosmosTransactionHistoryResponse,
    response_model_exclude_none=True,
)
async def get_cosmos_transaction_history(
        request: Request, network_id: str,
        limit: int = Query(default=20, ge=1, le=20),
        cursor: str | None = Query(default=None, min_length=1, max_length=80)):
    """Serve cursor pagination without ever issuing a full-chain tx search."""
    service = _service(request, network_id)
    try:
        return await service.transaction_history(limit, cursor)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid transaction history cursor") from None
    except AllEndpointsUnavailable:
        raise HTTPException(status_code=503, detail="Transaction data is temporarily unavailable") from None
    except Exception:
        LOGGER.info("Cosmos transaction history failed network=%s reason=upstream_unavailable", network_id)
        raise HTTPException(status_code=503, detail="Transaction data is temporarily unavailable") from None
