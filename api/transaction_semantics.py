"""Conservative human-readable transaction intent classification."""

BASE_OPERATIONS = {
    "gno.bank.MsgSend": "Coin Transfer",
    "gno.vm.MsgAddPackage": "Deployment",
    "gno.vm.MsgRun": "Package Run",
}

STANDARD_OPERATIONS = {
    "grc721": {
        "Mint": "NFT Mint",
        "TransferFrom": "NFT Transfer",
        "SafeTransferFrom": "NFT Transfer",
        "Approve": "NFT Approval",
        "SetApprovalForAll": "NFT Approval",
        "Burn": "NFT Burn",
    },
    "grc20": {
        "Transfer": "GRC20 Transfer",
        "TransferFrom": "GRC20 Transfer",
        "Approve": "GRC20 Approval",
    },
}


def semantic_transaction_operation(
    raw_type: str,
    current_operation: str,
    package_path: str | None = None,
    function: str | None = None,
    verified_standard: str | None = None,
) -> str:
    """Return intent only for exact base messages or verified asset calls."""
    if raw_type in BASE_OPERATIONS:
        return BASE_OPERATIONS[raw_type]
    if raw_type != "gno.vm.MsgCall":
        return current_operation
    if not package_path or not function:
        return "Contract Call"
    return STANDARD_OPERATIONS.get(verified_standard, {}).get(function, "Contract Call")
