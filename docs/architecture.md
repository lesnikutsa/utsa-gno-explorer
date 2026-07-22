# Architecture

## Canonical transaction hashes

For every successfully Base64-decoded `result.block.data.txs[index]` value, the indexer stores `SHA-256(decoded transaction bytes)` as exactly 64 uppercase hexadecimal characters without a `0x` prefix. The decoded byte sequence is used unchanged; the Base64 text and structured fields are never hashed. Invalid Base64 rows retain a null hash. Hash-based routes/search and structured Amino message parsing are deliberately deferred.


This document describes the first explorer architecture checkpoint. It is a design document only: it does not introduce a continuous indexer, PostgreSQL server, Docker Compose, backend API, or frontend.

## Goals

The first production-ready explorer data model must support:

- latest block lists and block detail pages;
- transaction summaries attached to blocks;
- active validator sets by finalized height;
- validator signing and missed-block history;
- validator uptime over the latest 1,000 finalized heights;
- recent signed/missed squares over the latest 100 finalized heights;
- recent network-wide misses;
- RPC endpoint health, freshness checks, and switching records;
- resumable indexing after process restart.

## Components

1. **RPC discovery and selection** probes configured public RPC endpoints with `/status`, rejects unhealthy endpoints, and chooses a healthy endpoint within the configured height lag.
2. **Height planner** reads latest RPC height `H` only to derive `finalized_tip = H - 1`, then starts from `indexer_state.last_finalized_height + 1`.
3. **Finalized-height processor** iterates each target finalized height `S` sequentially, fetches `/block?height=S`, `/commit?height=S`, and `/validators?height=S`, verifies every parsed height equals `S`, and writes one complete height in a single PostgreSQL transaction.
4. **PostgreSQL database** stores normalized explorer data plus limited raw JSONB fields useful for auditing changing RPC shapes.
5. **Future API and UI** read from PostgreSQL only. They do not call RPC endpoints directly for indexed pages.

## Verified TM2 height model

For a latest RPC height `H` returned by `/status`:

- `H` only defines `finalized_tip = H - 1`.
- The next target finalized height is `S = indexer_state.last_finalized_height + 1`.
- The indexer must process every intermediate `S` sequentially while `S <= finalized_tip`; downtime must not create gaps.
- For each `S`, `/block?height=S`, `/commit?height=S`, and `/validators?height=S` must be requested at the same height.
- The parsed block height, commit header height, and validator-set height must all equal `S`.
- Null precommits are evidence that some vote is absent, but they must not be mapped to validators by array position unless that positional relationship is explicitly verified. Address matching is used for non-null votes, and array position must not be the sole evidence of signing. A validator counts as signed only when its non-null precommit `Vote.BlockID` matches the enclosing `Commit.BlockID`; a non-null signature alone is insufficient.

This model is refined from the RPC discovery prototype and must remain an indexer invariant.

## Data model summary

- `blocks` stores one row per block height with base64 and normalized hex hashes, UTC network time, proposer address, transaction count, and optional retained block RPC JSON.
- `transactions` stores ordered transactions per block, preserving raw base64 and decoded bytes when decoding succeeds.
- `validators` stores stable validator identity by signing address, with public key type and value.
- `validator_set_members` stores the active set membership and voting power for each finalized height.
- `validator_signatures` stores one normalized vote result per validator per finalized height: `commit`, `nil`, `absent`, or `invalid`.
- `rpc_endpoints` stores current endpoint health metadata without secrets.
- `rpc_endpoint_checks` stores append-only health checks and selection/switch events for auditing.
- `indexer_state` stores the checkpoint that makes indexing resumable.

No speculative application, account, contract, event, or frontend tables are included in this checkpoint.

## Storage decisions

### Block hashes

Block hashes are stored both as:

- `block_hash_base64`, exactly as returned by TM2 RPC;
- `block_hash_hex`, normalized uppercase hexadecimal derived from decoded hash bytes.

The base64 value preserves source fidelity. The hex value supports user-facing search, copy/paste, and future API filters.

### Validator identity

The validator signing address from the validator set is the primary stable explorer key for matching non-null precommit votes, signatures, and misses. Public key type and value are also stored because display labels and key formats can differ across TM2 versions. Voting power is stored in `validator_set_members`, not only in `validators`, because it can change by height.

### Transactions

Transactions are stored as raw base64 plus decode metadata. When base64 decoding succeeds, decoded bytes are stored in `decoded_bytes`; higher-level Gno transaction parsing is intentionally deferred. If decoding fails, the row remains useful through `raw_base64`, lengths, and `decode_status`.


### Vote status semantics

Gno TM2 precommit votes are normalized before uptime or recent-square calculations:

- `commit`: a non-null precommit whose parsed `Vote.BlockID` matches the enclosing `Commit.BlockID`; only this state counts as signed.
- `nil`: a non-null precommit with zero `Vote.BlockID`; it is unsigned for uptime and should appear as a missed/nil square.
- `absent`: no precommit was present for the validator signing address; it is unsigned for uptime and appears as an absent square.
- `invalid`: malformed, unmatched, or non-zero non-matching vote data requiring investigation; it is unsigned for uptime and must be visually distinguishable from ordinary missed votes in future UI/API.

A non-null signature alone is not enough to count a vote as signed. The parser must compare parsed vote BlockID information with the enclosing commit BlockID.

### JSONB usage

JSONB is limited to raw RPC response retention and small parsed metadata that may be useful while RPC shapes are still being verified. Core explorer queries must use normalized columns and indexes.

### Raw RPC response retention

Raw responses are optional and should be retained for a short operational window, such as 7 to 30 days, or until disk pressure requires pruning. Retention is for debugging parser changes and RPC inconsistencies, not for primary application queries.

### Timestamps

Network timestamps use `TIMESTAMPTZ`. The indexer stores and displays them as UTC. Database defaults such as `now()` are used only for local ingestion metadata.

### Validator-set changes

Every finalized height has its own validator-set membership rows. Validator rows are upserted by signing address, while membership and voting power are recorded per height. This supports joins against the exact validator set that was responsible for each commit height. Vote status separates successful commit votes from nil, absent, and invalid votes so future uptime and UI state are not inferred from raw signature presence alone.

## Idempotency and transactions

One target finalized height `S` must be processed inside a single database transaction:

1. upsert block `S` metadata and transactions;
2. upsert validators seen in the validator set at `S`;
3. insert or update `validator_set_members` for `S`;
4. insert or update `validator_signatures` for `S`;
5. update current endpoint health metadata and append endpoint check history as needed;
6. advance `indexer_state.last_finalized_height` only to `S` after all previous steps succeed.

If any step fails, the transaction rolls back and `indexer_state` is not advanced. Reprocessing the same height is safe because primary keys and unique constraints prevent duplicate block, transaction, validator-set, and signature records. The processor then continues with `S + 1` and never skips intermediate heights.

## Assumptions and unverified behavior

- The exact live field paths for non-null precommit `Vote.BlockID`, enclosing `Commit.BlockID`, nil votes, and validator signing addresses still need follow-up verification before implementation.
- Full Gno transaction decoding is out of scope for this checkpoint.
- Public RPC endpoint reliability and ordering should be revisited before production indexing.
- This design stores no secrets and assumes private RPC credentials, if ever needed, are supplied only through runtime secret management.
