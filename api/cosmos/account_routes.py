"""FastAPI router for live Cosmos account state."""

import logging

from fastapi import APIRouter, HTTPException, Query, Request

from .account_activity import CosmosAccountActivityResponse, load_account_activity
from .account_detail import CosmosAccountDetailResponse, load_account_snapshot
from .errors import AllEndpointsUnavailable
from .registry import get_network


LOGGER = logging.getLogger(__name__)
router = APIRouter()


def _service(request: Request, network_id: str):
    if get_network(network_id) is None:
        raise HTTPException(status_code=404, detail="Unknown network")
    services = getattr(request.app.state, "cosmos_services", None)
    if not isinstance(services, dict) or network_id not in services:
        raise HTTPException(status_code=503, detail="Network data is temporarily unavailable")
    return services[network_id]


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
