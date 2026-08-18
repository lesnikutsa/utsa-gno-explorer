from datetime import datetime, timezone
from unittest.mock import patch

import pytest

try:
    from fastapi.testclient import TestClient
except RuntimeError as exc:
    pytest.skip(f"FastAPI TestClient is unavailable: {exc}", allow_module_level=True)

from api.config import ApiConfig

ADDRESS = "g16mldrfu90pe5r97cjm3xk02m7a3d0z8g9g3r75"
OTHER = "g1jg8mtutu9khhfwc4nxmuhcpftf0pajdhfvsqf5"
TIME = datetime(2026, 7, 31, tzinfo=timezone.utc)
DATABASE_URL = "postgresql://api:password@example.invalid/explorer"


def summary(messages):
    primary = {key: messages[0][key] for key in ("type", "category", "action", "label")}
    return {"schema_version": 1, "chain_family": "gno", "parse_status": "parsed", "message_count": len(messages), "messages_truncated": False, "primary": primary, "messages": messages}


def message(sender=ADDRESS, recipient=OTHER, amount="12ugnot", send=None, label="Send Tokens", tx_type="gno.bank.MsgSend"):
    return {"type": tx_type, "category": "bank", "action": "send", "label": label, "sender": sender, "recipient": recipient, "amount": amount, "send": send}


def row(height, index, participation, payload=None, **overrides):
    value = {"block_height": height, "tx_index": index, "tx_hash_hex": f"{height * 10 + index:064x}", "time_utc": TIME, "payload_summary": summary([message()]) if payload is None else payload, "participation": participation}
    value.update(overrides)
    return value


class FakeDatabase:
    def __init__(self, rows=(), error=None):
        self.rows, self.error, self.calls = list(rows), error, []
    def open(self, config): pass
    def close(self): pass
    def fetch_account_transactions(self, address, *, limit, before_height, before_tx_index):
        self.calls.append((address, limit, before_height, before_tx_index))
        if self.error: raise self.error
        return self.rows[:limit + 1]
    def fetch_selected_rpc_url(self, chain_id):
        raise AssertionError("Account RPC path must not be used")


def client(database):
    from api import app as module
    db_patch = patch.object(module, "database", database)
    config_patch = patch.object(module, "load_config", return_value=ApiConfig(database_url=DATABASE_URL))
    db_patch.start(); config_patch.start()
    test_client = TestClient(module.app)
    test_client._account_patches = (db_patch, config_patch)
    return test_client


def request(database, path=f"/api/accounts/{ADDRESS}/transactions"):
    test_client = client(database)
    try:
        with test_client as opened:
            return opened.get(path)
    finally:
        for item in test_client._account_patches: item.stop()


def test_newest_first_empty_and_single_database_query():
    response = request(FakeDatabase([row(12, 1, [{"message_index": 0, "role": "sender"}]), row(11, 0, [{"message_index": 0, "role": "sender"}])]))
    assert response.status_code == 200
    assert [(item["block_height"], item["index"]) for item in response.json()["items"]] == [(12, 1), (11, 0)]
    assert all(item["operation"] == "Transfer" for item in response.json()["items"])
    empty = FakeDatabase()
    assert request(empty).json()["items"] == []
    assert empty.calls == [(ADDRESS, 20, None, None)]


def test_account_transaction_includes_validated_message_count():
    messages = [message(), message(sender=OTHER, recipient=ADDRESS)]
    response = request(FakeDatabase([
        row(12, 0, [{"message_index": 0, "role": "sender"}], summary(messages)),
    ]))
    assert response.status_code == 200
    assert response.json()["items"][0]["message_count"] == 2


def test_validation_cursor_and_pagination_contract():
    assert request(FakeDatabase(), "/api/accounts/not-an-address/transactions").status_code == 422
    assert request(FakeDatabase(), f"/api/accounts/{ADDRESS}/transactions?before_height=8").status_code == 422
    database = FakeDatabase([row(9, i, [{"message_index": 0, "role": "sender"}]) for i in (2, 1, 0)])
    response = request(database, f"/api/accounts/{ADDRESS}/transactions?limit=2&before_height=10&before_tx_index=3")
    assert database.calls == [(ADDRESS, 2, 10, 3)]
    assert response.json()["pagination"] == {"limit": 2, "next_before_height": 9, "next_before_tx_index": 1}
    last = request(FakeDatabase(database.rows[:2]), f"/api/accounts/{ADDRESS}/transactions?limit=2").json()
    assert last["pagination"]["next_before_height"] is None and last["pagination"]["next_before_tx_index"] is None


def test_directions_matching_message_amount_counterparty_and_contract_send():
    cases = [
        ([{"message_index": 0, "role": "sender"}], message(), "outgoing", OTHER),
        ([{"message_index": 0, "role": "recipient"}], message(sender=OTHER, recipient=ADDRESS), "incoming", OTHER),
        ([{"message_index": 0, "role": "sender"}, {"message_index": 0, "role": "recipient"}], message(sender=ADDRESS, recipient=ADDRESS), "self", None),
    ]
    for participation, relevant_message, direction, counterparty in cases:
        data = request(FakeDatabase([row(4, 0, participation, summary([relevant_message]))])).json()["items"][0]
        assert (data["direction"], data["counterparty"], data["amount"]) == (direction, counterparty, "12ugnot")
    messages = [message(sender=OTHER, recipient=OTHER, label="Ignored"), message(label="Call", amount=None, send="7ugnot", tx_type="gno.vm.MsgCall")]
    payload = summary(messages)
    data = request(FakeDatabase([row(5, 0, [{"message_index": 1, "role": "sender"}], payload)])).json()["items"][0]
    assert (data["operation"], data["amount"]) == ("Transfer", "7ugnot")
    messages[1]["amount"] = "3ugnot"
    data = request(FakeDatabase([row(5, 0, [{"message_index": 1, "role": "sender"}], summary(messages))])).json()["items"][0]
    assert data["amount"] == "3ugnot"


def test_malformed_summary_is_generic_but_bad_participation_fails_closed():
    data = request(FakeDatabase([row(3, 0, [{"message_index": 0, "role": "sender"}], {"bad": "raw"})])).json()["items"][0]
    assert {key: data[key] for key in ("type", "operation", "counterparty", "amount")} == {"type": "unknown", "operation": "Transaction", "counterparty": None, "amount": None}
    for participation in ([], [{"message_index": 0, "role": "observer"}], [{}]):
        response = request(FakeDatabase([row(3, 0, participation)]))
        assert response.status_code == 503
        assert response.json() == {"detail": "Explorer database is unavailable"}
        assert "DATABASE_URL" not in response.text and "payload_summary" not in response.text


def test_database_failure_is_safe_and_repeated_participation_is_one_item():
    assert request(FakeDatabase(error=RuntimeError("SQL DATABASE_URL"))).json() == {"detail": "Explorer database is unavailable"}
    participation = [{"message_index": 0, "role": "sender"}, {"message_index": 0, "role": "sender"}]
    assert len(request(FakeDatabase([row(2, 0, participation)])).json()["items"]) == 1


def test_execution_fields_are_propagated_without_private_result_data():
    response = request(FakeDatabase([row(
        2, 0, [{"message_index": 0, "role": "sender"}],
        execution_status="success", gas_wanted="5000000", gas_used="934971",
        error=None, log="msg:0,success:true,log:,events:[]", info="",
        raw_result={"private": True}, events=[{"private": True}],
        data_base64="cHJpdmF0ZQ==", source_rpc_endpoint_id=7,
    )]))
    payload = response.json()
    item = payload["items"][0]
    assert {key: item[key] for key in ("execution_status", "gas_wanted", "gas_used", "error", "log", "info")} == {
        "execution_status": "success", "gas_wanted": "5000000", "gas_used": "934971",
        "error": None, "log": "msg:0,success:true,log:,events:[]", "info": "",
    }
    for private in ("raw_result", "events", "data_base64", "source_rpc_endpoint_id"):
        assert private not in item
    assert {"private": True} not in item.values()
