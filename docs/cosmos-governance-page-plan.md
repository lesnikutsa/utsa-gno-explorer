# Cosmos Governance page plan

Scope: Cosmos / AtomOne only. Gno routes, components and styles are out of scope.

## Phase 1
- Add a Cosmos `governance` public capability and `/networks/:id/governance` route.
- Add Governance to the Cosmos sidebar after Validators.
- Build a request-driven proposals list using Cosmos SDK `/cosmos/gov/v1/proposals` with endpoint failover.
- Keep the existing Overview governance parameter aggregation as the source for voting/deposit parameters; do not duplicate unrelated overview logic.
- Summary cards: active/voting proposals, voting period, quorum, threshold, minimum deposit.
- Proposal table: proposal id, type, title, status, voting end, compact tally.
- Page must degrade cleanly if proposals are unavailable from a selected API provider.

## Phase 2
- Proposal detail route with content, deposit, voting window, final/current tally and metadata.

## Non-goals
- No Gno changes.
- No IBC page.
- No wallet/vote transaction signing.
- No database/indexer dependency.
