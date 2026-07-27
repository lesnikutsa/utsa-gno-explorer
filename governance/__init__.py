"""Read-only Gno governance discovery."""

from .gno import (
    DEFAULT_REALM,
    GovernanceDiscovery,
    GovernanceParseError,
    GovernanceProposalDetail,
    GovernanceProposalSummary,
    GovernanceSource,
    GovernanceVote,
    discover_governance,
    pager_paths,
    parse_detail,
    parse_proposal_list,
    parse_votes,
)

__all__ = [
    "DEFAULT_REALM",
    "GovernanceDiscovery",
    "GovernanceParseError",
    "GovernanceProposalDetail",
    "GovernanceProposalSummary",
    "GovernanceSource",
    "GovernanceVote",
    "discover_governance",
    "pager_paths",
    "parse_detail",
    "parse_proposal_list",
    "parse_votes",
]
