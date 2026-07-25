# Transaction decoding architecture

## Current stage

This stage defines version 1 of a normalized, chain-neutral transaction summary. It does not decode Gno Amino or Cosmos SDK application messages. Base64 decode status describes transport decoding only and must not be interpreted as blockchain execution success or failure.

Raw consensus transaction fields remain immutable. `payload_summary` is derived parser metadata, is versioned independently, and may be refreshed when a height is reprocessed. Historical rows where `payload_summary` is `NULL` remain valid and require neither a migration nor a reindex.

The summary stores at most 20 message summaries. Labels are limited to 80 characters, type identifiers to 160 characters, and family/category/action tokens to 64 characters. Message fields and printable scalar values are also bounded. Adapters must never include signatures, Base64 payloads, complete raw transactions, bytes, or other unbounded raw data.

Frontend and API exposure are intentionally deferred until useful application-level adapters exist. Gno and Cosmos SDK decoding will use separate adapters, but every adapter must produce the same normalized structure. Unknown message types and malformed adapter output must fall back safely to the generic summary.

## Planned stages

1. Normalized summary foundation.
2. Gno decoder adapter.
3. Controlled historical backfill.
4. API exposure.
5. Compact block-table transaction type.
6. Expanded transaction-detail information.
7. Cosmos SDK adapter.
