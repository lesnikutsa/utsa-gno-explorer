# Transaction decoding architecture

## Current stage

This stage defines version 1 of a normalized, chain-neutral transaction summary. It does not decode Gno Amino or Cosmos SDK application messages. Base64 decode status describes transport decoding only and must not be interpreted as blockchain execution success or failure.

Raw consensus transaction fields remain immutable. `payload_summary` is derived parser metadata, is versioned independently, and may be refreshed when a height is reprocessed. Historical rows where `payload_summary` is `NULL` remain valid and require neither a migration nor a reindex.

The summary stores at most 20 message summaries and has a hard 16 KiB limit measured as deterministic compact UTF-8 JSON. Labels are limited to 80 characters, type identifiers to 160 characters, and family/category/action tokens to 64 characters. Message fields and printable scalar values are also bounded. Message integers may be signed but are limited to 256 bits, and `message_count` is limited to 100,000.

When present, `message_count` cannot be smaller than the supplied or retained messages. `messages_truncated` becomes true when the adapter reports truncation, the count indicates omitted summaries, the 20-message limit is exceeded, or trailing messages are removed to meet the 16 KiB limit. Adapters must never include signatures, Base64 payloads, complete raw transactions, bytes, or other unbounded raw data.

Frontend and API exposure are intentionally deferred until useful application-level adapters exist. Gno and Cosmos SDK decoding will use separate adapters, but every adapter must produce the same normalized structure. Unknown message types and malformed adapter output must fall back safely to the generic summary. Adapter output is never trusted directly: persistence performs final normalization before serializing it into JSONB.

## Planned stages

1. Normalized summary foundation.
2. Gno decoder adapter.
3. Controlled historical backfill.
4. API exposure.
5. Compact block-table transaction type.
6. Expanded transaction-detail information.
7. Cosmos SDK adapter.
