# Cosmos Governance page plan

Scope: Cosmos / AtomOne only. Gno routes, components and styles are out of scope.

## Phase 1
- Add a Cosmos `governance` public capability and `/networks/:id/governance` route.
- Add Governance to the Cosmos sidebar after Validators.
- Build a request-driven proposals list using Cosmos SDK `/cosmos/gov/v1/proposals` with endpoint failover.
- Reuse the existing Overview governance parameter aggregation for voting/deposit parameters where practical.
- Summary: voting proposals, voting period, quorum, threshold, minimum deposit.
- Proposal table: proposal id, type, title, status, voting end, compact tally.
- Degrade cleanly when a selected provider cannot serve governance data.

## Phase 2
- Proposal detail route with content, deposit, voting window, current/final tally and metadata.

## Non-goals
- No Gno changes.
- No IBC page.
- No wallet/vote transaction signing.
- No database/indexer dependency.
