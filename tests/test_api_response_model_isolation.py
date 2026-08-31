"""Regression coverage for Gno/Cosmos response-model name isolation."""

from api.app import app
from api.schemas import BlockDetailResponse, TransactionDetailResponse, TransactionsResponse
from api.cosmos.schemas import (
    BlockDetailResponse as CosmosBlockDetailResponse,
    TransactionDetailResponse as CosmosTransactionDetailResponse,
    TransactionsResponse as CosmosTransactionsResponse,
)


def response_model(path):
    return next(route.response_model for route in app.routes if getattr(route, "path", None) == path)


def test_gno_routes_keep_gno_response_models_after_cosmos_imports():
    assert response_model("/api/blocks/{height}") is BlockDetailResponse
    assert response_model("/api/transactions") is TransactionsResponse
    assert response_model("/api/blocks/{height}/transactions/{index}") is TransactionDetailResponse


def test_cosmos_routes_use_explicit_cosmos_response_models():
    assert response_model("/api/networks/{network_id}/blocks/{height}/detail") is CosmosBlockDetailResponse
    assert response_model("/api/networks/{network_id}/transactions") is CosmosTransactionsResponse
    assert response_model("/api/networks/{network_id}/blocks/{height}/transactions/{index}") is CosmosTransactionDetailResponse
