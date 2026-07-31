import pytest

from indexer.execution_backfill import missing_heights
from indexer.parsers import MAX_RESULT_TEXT_BYTES, parse_execution_results
from scripts.inspect_rpc import RpcError


def payload(items, height="7"):
    return {"result": {"height": height, "results": {"deliver_tx": items}}}


def item(error=None, wanted="5000000", used="934971"):
    return {
        "ResponseBase": {
            "Error": error,
            "Data": None,
            "Events": [],
            "Log": "log",
            "Info": "",
        },
        "GasWanted": wanted,
        "GasUsed": used,
    }


class RecordingCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sql = None
        self.params = None

    def execute(self, sql, params):
        self.sql = sql
        self.params = params

    def fetchall(self):
        return self.rows


def test_missing_heights_supports_unbounded_range():
    cursor = RecordingCursor([(194640,), (333197,)])

    assert missing_heights(cursor, None, None, 25) == [194640, 333197]
    assert cursor.params == (None, None, None, None, 25)
    assert cursor.sql.count("%s::bigint") == 4


def test_missing_heights_preserves_explicit_bounds():
    cursor = RecordingCursor([(333197,)])

    assert missing_heights(cursor, 300000, 340000, 10) == [333197]
    assert cursor.params == (300000, 300000, 340000, 340000, 10)


def test_success_and_gas_normalization():
    result = parse_execution_results(7, payload([item()]), 1)[0]
    assert (
        result["tx_index"],
        result["execution_status"],
        result["gas_wanted"],
        result["gas_used"],
    ) == (0, "success", 5000000, 934971)
    assert result["error_text"] is None


def test_failed_result_preserves_error():
    result = parse_execution_results(
        7,
        payload([item({"code": 12, "message": "denied"})]),
        1,
    )[0]
    assert result["execution_status"] == "failed"
    assert '"message":"denied"' in result["error_text"]


@pytest.mark.parametrize("value", ["-1", "1.2", "", None, True, {}, "9" * 79])
def test_malformed_gas_rejected(value):
    with pytest.raises(RpcError, match="GasUsed"):
        parse_execution_results(7, payload([item(used=value)]), 1)


def test_zero_transaction_absent_deliver_tx_is_accepted():
    assert parse_execution_results(
        7,
        {"result": {"height": "7", "results": {}}},
        0,
    ) == []


@pytest.mark.parametrize(
    "body",
    [
        {"result": {"height": "8", "results": {"deliver_tx": []}}},
        {"result": {"height": "7", "results": {}}},
        {
            "result": {
                "height": "7",
                "results": {"deliver_tx": [item(), item()]},
            }
        },
    ],
)
def test_height_missing_and_count_mismatches_rejected(body):
    with pytest.raises(RpcError):
        parse_execution_results(7, body, 1)


def test_rpc_controlled_text_is_bounded():
    oversized = item()
    oversized["ResponseBase"]["Log"] = "x" * (MAX_RESULT_TEXT_BYTES + 1)
    with pytest.raises(RpcError, match="exceeds"):
        parse_execution_results(7, payload([oversized]), 1)
