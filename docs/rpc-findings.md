# RPC findings for Gno.land Testnet 13

This document records the response fields targeted by `scripts/inspect_rpc.py`.
The prototype is intentionally small and should be verified against a real
public Testnet 13 RPC before these paths are treated as stable production input.

## RPC methods used

- `GET /status` for node information, chain ID, latest known height, and sync status.
- `GET /block?height=<latest_height>` for latest block header, block hash, proposer, timestamp, and transactions.
- `GET /commit?height=<latest_height - 1>` for signing analysis precommits and canonical commit data.
- `GET /validators?height=<latest_height - 1>` for the validator set that must be compared with the commit at the same height.

## Verified TM2 height relationship

For latest height `H` from `/status`:

- `/block?height=H` is used only for latest block metadata and transaction summary.
- Block `H` `last_commit` must not be treated as signatures for block `H`.
- Signing and missed-block analysis uses height `H - 1`.
- `/commit?height=H-1` returns `result.signed_header.header`, `result.signed_header.commit`, `result.signed_header.commit.precommits`, and boolean `result.canonical` for that signing height.
- Commit height is derived from `result.signed_header.header.height`; `signed_header.commit.height` is not expected.
- `/validators?height=H-1` must return `result.block_height` for the same height as the commit.
- The prototype fails clearly if the parsed commit height and validator-set `block_height` do not both equal `H - 1`.

## Important response paths

- `/status`:
  - `result.node_info.network` -> chain ID.
  - `result.node_info.version` -> node/software version.
  - `result.sync_info.latest_block_height` -> latest height known by the node.
  - `result.sync_info.catching_up` -> catching-up/sync status.
- `/block`:
  - `result.block_id.hash` -> latest block hash.
  - `result.block.header.height` -> block height.
  - `result.block.header.time` -> block timestamp.
  - `result.block.header.proposer_address` -> proposer address.
  - `result.block.data.txs` -> raw transactions present in the block response.
- `/commit`:
  - `result.signed_header.header.height` -> signed header height.
  - Commit height is derived from `result.signed_header.header.height`.
  - `result.signed_header.commit.precommits` -> commit precommit entries; entries may be `null`.
  - `result.canonical` -> boolean canonical flag returned by the RPC.
- `/validators`:
  - `result.block_height` -> validator-set block height; this field is required.
  - `result.total` -> total validator count if exposed by the RPC.
  - `result.validators[].address` -> validator address.
  - `result.validators[].voting_power` -> validator voting power.
  - `result.validators[].proposer_priority` -> proposer priority if exposed.
  - `result.validators[].pub_key` -> public key metadata.

## Fields useful for the future Blocks page

- Block height: `result.block.header.height`.
- Block hash: `result.block_id.hash`.
- Timestamp: `result.block.header.time`.
- Proposer address: `result.block.header.proposer_address`.
- Transaction count: length of `result.block.data.txs`.
- Raw transaction previews and byte sizes from `result.block.data.txs`.

## Fields useful for Active Validators

- Validator address: `result.validators[].address`.
- Voting power: `result.validators[].voting_power`.
- Public key type and value: `result.validators[].pub_key.type` and `result.validators[].pub_key.value`.
- Proposer priority: `result.validators[].proposer_priority`, if present and meaningful on the live RPC.
- Validator-set height: `result.block_height` from `/validators?height=<H-1>`.

## Fields useful for signing and missed-block calculations

- Signing analysis height: latest height `H` minus one.
- Validator set at the signing height: `result.validators[]` from `/validators?height=<H-1>`.
- Commit precommits at the signing height: `result.signed_header.commit.precommits` from `/commit?height=<H-1>`.
- Signature validator address: `validator_address` or `address` inside each non-null precommit entry.
- Signed detection currently treats entries with a non-empty `signature` as signed, and also recognizes Tendermint-style `block_id_flag` commit values.
- Null or non-object precommit entries are treated as not signed and never crash parsing.
- Missed validators are calculated by subtracting signer addresses from validator addresses at the same height.

## RPC endpoint fallback behavior

- Endpoints are read from `GNO_RPC_URLS` as a comma-separated ordered list.
- Legacy `GNO_RPC_URL` is supported only when `GNO_RPC_URLS` is unset.
- Each endpoint is checked with `/status` and a timeout.
- Catching-up endpoints are rejected.
- The first healthy endpoint in configured order is selected and printed clearly.
- The script fails clearly if all configured endpoints are unavailable.

## Limitations and uncertain fields

- Transaction payloads in `result.block.data.txs` may be encoded strings or structured JSON. The prototype reports type, size, and a short preview only.
- Validator address formats should be verified on the real Testnet 13 RPC before using them as database keys.
- Commit signature fields such as `block_id_flag`, `absent`, and `signature` need live confirmation for missed-block accuracy.
- The prototype queries only one latest height and one signing height and is not a continuous indexer.

## Still needing verification on real Testnet 13 RPC

- Which public RPC endpoint is most reliable for `GNO_RPC_URLS` ordering.
- Whether any public Testnet 13 RPC truncates `/validators?height=<height>` results without supporting TM2 pagination parameters.
- Exact node version and chain ID values returned by the live network.
- Exact commit precommit shape and whether absent signatures are represented with `null`, `absent`, empty `signature`, or `block_id_flag`.
- Whether transaction data is base64, Amino/JSON, or another encoding in live block responses.
