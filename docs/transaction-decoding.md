# Transaction decoding architecture

## Normalized summary foundation

Version 1 defines a normalized, chain-neutral transaction summary. The optional
Gno adapter can derive this summary from Amino transactions, while Base64 decode
status still describes transport decoding only and must not be interpreted as
blockchain execution success or failure.

Raw consensus transaction fields remain immutable. `payload_summary` is derived parser metadata, is versioned independently, and may be refreshed when a height is reprocessed. Historical rows where `payload_summary` is `NULL` remain valid and require neither a migration nor a reindex.

The summary stores at most 20 message summaries and has a hard 16 KiB limit measured as deterministic compact UTF-8 JSON. Labels are limited to 80 characters, type identifiers to 160 characters, and family/category/action tokens to 64 characters. Message fields and printable scalar values are also bounded. Message integers may be signed but are limited to 256 bits, and `message_count` is limited to 100,000.

When present, `message_count` cannot be smaller than the supplied or retained messages. `messages_truncated` becomes true when the adapter reports truncation, the count indicates omitted summaries, the 20-message limit is exceeded, or trailing messages are removed to meet the 16 KiB limit. Adapters must never include signatures, Base64 payloads, complete raw transactions, bytes, or other unbounded raw data.

The supervised decoder and JSONB persistence are active in production. The transaction-detail endpoint (`GET /api/blocks/{height}/transactions/{index}`) exposes a bounded public `summary`; the internal `payload_summary` column name is not part of the public contract. Only `type`, `category`, `action`, `label`, `sender`, `recipient`, `amount`, `send`, `package_path`, `package_name`, `function`, `args_count`, `file_count`, `expires_at`, `allow_paths_count`, `spend_limit`, and `spend_period` are copied from message objects. Unknown and unsafe fields are discarded. A malformed stored summary becomes `summary: null`, and historical SQL `NULL` values remain null without invented decoding.

This exposure is limited to transaction detail. Block lists and the block-detail transaction rows remain compact. The transaction-detail page now displays a compact public Transaction Summary using only this public API allowlist. Sender and recipient values are copyable but are not account links because account pages do not exist yet. The summary describes transaction content, not execution success, and Raw Transaction remains available. Gas, fee, execution result, and historical backfill remain deferred. Future Cosmos summaries will use the same generic component and extend the API allowlist deliberately rather than exposing arbitrary adapter output.

## Delivery stages

1. Completed: normalized summary foundation and JSONB persistence.
2. Completed: standalone official Gno Amino decoder.
3. Completed: supervised Python subprocess client and production persistence.
4. Completed: bounded transaction-detail API exposure.
5. Completed: compact allowlisted frontend summary display.
6. Deferred: controlled historical backfill.
7. Deferred: a Cosmos SDK adapter using the same generic client contract.

## Standalone Gno decoder

The repository now contains an isolated Go command in `tools/gno-tx-decoder`.
It uses Gno's official Amino implementation and concrete SDK message
registrations rather than reimplementing Amino in Python. The reviewed
dependency target is `github.com/gnolang/gno` commit
`d14a03770521051749c87364fa8f1b6aae61e508`. The dependency is pinned and the
canonical generated `go.sum` is committed. The helper was verified on exp2
against Topaz block 192805, where it decoded the real transaction as
`gno.vm.MsgCall` with the primary label `Contract Call` and a 445-byte compact
summary.

The command is a long-lived JSONL filter. It reads one request per non-empty
standard-input line and writes exactly one compact JSON response line:

```json
{"id":"request-1","tx_base64":"<base64 transaction>"}
{"protocol_version":1,"id":"request-1","ok":true,"summary":{"schema_version":1,"chain_family":"gno","parse_status":"parsed","message_count":1,"messages_truncated":false,"primary":{"type":"gno.vm.MsgCall","category":"contract","action":"call","label":"Contract Call"},"messages":[{"type":"gno.vm.MsgCall","category":"contract","action":"call","label":"Contract Call","sender":"g1...","package_path":"gno.land/r/demo/example","function":"Render","args_count":0,"send":""}]}}
```

Errors use only the safe codes `invalid_json`, `invalid_request`,
`missing_tx_base64`, `input_too_large`, `invalid_base64`,
`amino_decode_failed`, and `internal_error`. A bad line does not stop later
requests. Request lines are limited to 8 MiB, decoded transactions to 4 MiB,
and printable request IDs to 128 characters.
Each request is protected by its own panic recovery boundary. A recovered panic
returns `internal_error` without panic text or a stack trace and does not stop
the process from accepting the next line.

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
and it neither validates nor executes transactions. The Python client described
below connects it to the production indexer. Historical backfill remains deferred.

## Optional supervised indexer decoder

The Python indexer consumes the standalone helper through a chain-neutral JSONL subprocess client. The configuration default remains disabled for safe deployments, while production enables it explicitly. Each indexer command lazily starts one long-lived child and reuses it for every transaction. Both writing a request and reading its response share the configured non-blocking deadline. A timeout or protocol/process failure terminates the child and prevents another start until the restart cooldown expires; transaction-specific input and Amino errors leave the child healthy.

The child receives only a sanitized `PATH`, `LANG`, and `LC_ALL`; database and
RPC credentials and other indexer environment variables are not inherited.
Child stderr is discarded and never enters indexer logs.

Configuration defaults are `TRANSACTION_DECODER_ENABLED=false`, `TRANSACTION_DECODER_PATH=/opt/utsa-gno-explorer/bin/gno-tx-decoder`, `TRANSACTION_DECODER_CHAIN_FAMILY=gno`, `TRANSACTION_DECODER_TIMEOUT_SECONDS=2`, and `TRANSACTION_DECODER_RESTART_BACKOFF_SECONDS=30`.

Any decoder failure falls back to the bounded generic `unparsed` summary and never blocks consensus indexing. Adapter output is normalized in Python and again at the database boundary. The API boundary independently rebuilds the public allowlisted summary rather than returning JSONB directly. The generic frontend component displays that bounded contract; historical backfill remains deferred. A future Cosmos adapter can use the same generic client by configuring another executable and expected chain family, with deliberate public allowlist extensions as needed.
