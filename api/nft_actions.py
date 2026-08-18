"""Conservative classification of indexed GRC721 call function names."""

from typing import Literal

NftAction = Literal["mint", "transfer", "approval", "burn"]

NFT_ACTION_BY_FUNCTION: dict[str, NftAction] = {
    "Mint": "mint",
    "TransferFrom": "transfer",
    "SafeTransferFrom": "transfer",
    "Approve": "approval",
    "SetApprovalForAll": "approval",
    "Burn": "burn",
}


def classify_nft_action(function_name: str | None) -> NftAction | None:
    """Return an action only for an exact, case-sensitive function-name match."""
    return NFT_ACTION_BY_FUNCTION.get(function_name) if isinstance(function_name, str) else None
