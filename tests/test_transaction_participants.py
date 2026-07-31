from indexer.transaction_participants import TransactionParticipant, extract_transaction_participants


ADDRESS = "g16mldrfu90pe5r97cjm3xk02m7a3d0z8g9g3r75"
OTHER = "g1jg8mtutu9khhfwc4nxmuhcpftf0pajdhfvsqf5"


def summary(messages, status="parsed"):
    return {"parse_status": status, "messages": messages}


def test_sender_and_recipient_preserve_message_index_and_role():
    assert extract_transaction_participants(summary([
        {"sender": ADDRESS}, {"sender": ADDRESS, "recipient": OTHER},
    ])) == [
        TransactionParticipant(0, "sender", ADDRESS),
        TransactionParticipant(1, "recipient", OTHER),
        TransactionParticipant(1, "sender", ADDRESS),
    ]


def test_self_transfer_preserves_both_roles():
    assert set(extract_transaction_participants(summary([
        {"sender": ADDRESS, "recipient": ADDRESS},
    ]))) == {
        TransactionParticipant(0, "sender", ADDRESS),
        TransactionParticipant(0, "recipient", ADDRESS),
    }


def test_invalid_unsupported_and_malformed_summaries_are_safe():
    assert extract_transaction_participants(summary([{"sender": "G1INVALID"}])) == []
    assert extract_transaction_participants(summary([{"sender": ADDRESS}], "unsupported")) == []
    assert extract_transaction_participants({"parse_status": "parsed", "messages": "bad"}) == []

from unittest.mock import MagicMock

from indexer.database import _upsert_transactions


def normalized_summary(messages, status="parsed"):
    primary = {"type": "gno.vm.MsgCall", "category": "contract", "action": "call", "label": "Call Contract"}
    return {"schema_version": 1, "chain_family": "gno", "parse_status": status, "message_count": len(messages), "messages_truncated": False, "primary": primary, "messages": [{**primary, **item} for item in messages]}


def stored_transaction(payload):
    return {"index": 0, "raw_base64": "YWJj", "raw_base64_length": 4, "decoded_bytes": b"abc", "decoded_byte_length": 3, "decode_status": "decoded", "tx_hash_hex": "BA7816BF8F01CFEA414140DE5DAE2223B00361A396177A9CB410FF61F20015AD", "payload_summary": payload}


def test_persistence_upserts_then_deletes_stale_and_inserts_on_same_cursor():
    cursor = MagicMock()
    parsed = type("Parsed", (), {"height": 7, "transactions": [stored_transaction(normalized_summary([{"sender": ADDRESS}, {"recipient": OTHER}]))]})()
    _upsert_transactions(cursor, parsed)
    assert "INSERT INTO transactions" in cursor.execute.call_args_list[0].args[0]
    assert "DELETE FROM transaction_participants" in cursor.execute.call_args_list[1].args[0]
    rows = cursor.executemany.call_args.args[1]
    assert rows == [(7, 0, 0, "sender", ADDRESS), (7, 0, 1, "recipient", OTHER)]


def test_parsed_to_unparsed_refresh_deletes_and_inserts_none():
    cursor = MagicMock()
    parsed = type("Parsed", (), {"height": 7, "transactions": [stored_transaction(normalized_summary([], "unparsed"))]})()
    _upsert_transactions(cursor, parsed)
    assert "DELETE FROM transaction_participants" in cursor.execute.call_args_list[1].args[0]
    cursor.executemany.assert_not_called()


def test_malformed_summary_does_not_interrupt_persistence():
    cursor = MagicMock()
    parsed = type("Parsed", (), {"height": 7, "transactions": [stored_transaction({"messages": "malformed"})]})()
    _upsert_transactions(cursor, parsed)
    assert cursor.execute.call_count == 2
    cursor.executemany.assert_not_called()
