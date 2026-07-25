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

## Standalone Gno decoder

The repository now contains an isolated Go command in `tools/gno-tx-decoder`.
It uses Gno's official Amino implementation and concrete SDK message
registrations rather than reimplementing Amino in Python. The
`github.com/gnolang/gno` dependency is pinned to reviewed commit
`d14a03770521051749c87364fa8f1b6aae61e508`.

The command is a long-lived JSONL filter. It reads one request per non-empty
standard-input line and writes exactly one compact JSON response line:

```json
{"id":"request-1","tx_base64":"<base64 transaction>"}
{"protocol_version":1,"id":"request-1","ok":true,"summary":{"schema_version":1,"chain_family":"gno","parse_status":"parsed","message_count":1,"messages_truncated":false,"primary":{"type":"gno.vm.MsgCall","category":"contract","action":"call","label":"Contract Call"},"messages":[]}}
```

Errors use only the safe codes `invalid_json`, `invalid_request`,
`missing_tx_base64`, `input_too_large`, `invalid_base64`,
`amino_decode_failed`, and `internal_error`. A bad line does not stop later
requests. Request lines are limited to 8 MiB, decoded transactions to 4 MiB,
and printable request IDs to 128 characters.

The decoder recognizes `vm.MsgCall`, `vm.MsgRun`, `vm.MsgAddPackage`,
`bank.MsgSend`, `auth.MsgCreateSession`, `auth.MsgRevokeSession`, and
`auth.MsgRevokeAllSessions`. All recognized messages produce `parsed`; any
unknown concrete message, or a transaction with no messages, produces
`unsupported`. The first decoded message is primary. The full message count is
preserved, while no more than 20 ordered summaries are retained.

Output follows the version 1 normalization limits: compact summaries are at
most 16,384 bytes, labels are at most 80 Unicode characters, type names at
most 160, category/action tokens at most 64, scalar details at most 160, and a
message has no more than 16 explicit fields. Trailing summaries are removed
when necessary without changing the primary message or full count.

Only bounded identifying details and counts are emitted. The command never
emits the original Base64, decoded bytes, signatures, public keys, the full
memo, call arguments, session allow-path values, package file names or bodies,
source code, raw Amino JSON, arbitrary transaction structs, or raw Go errors.

This helper performs offline binary decoding only. It initializes no Gno
application, VM keeper, node, database, RPC client, or other network client,
and it neither validates nor executes transactions. It is not connected to the
Python indexer, so production behavior is unchanged. A later stage will add a
supervised long-lived Python adapter after verification against real Topaz
transactions. Historical backfill remains deferred.
