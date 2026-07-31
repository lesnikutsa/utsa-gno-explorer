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
