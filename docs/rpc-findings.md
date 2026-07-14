# RPC findings for Gno.land Testnet 13

This document records the response fields targeted by `scripts/inspect_rpc.py`.
The prototype is intentionally small and should be verified against a real
public Testnet 13 RPC before these paths are treated as stable production input.

## RPC methods used

- `GET /status` for node information, chain ID, latest known height, and sync status.
- `GET /block?height=<latest_height>` for latest block header, block hash, transactions, and commit signatures.
- `GET /validators?height=<latest_height>` for the validator set at the inspected height.

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
  - `result.block.last_commit.precommits` or `result.block.last_commit.signatures` -> commit signature entries.
- `/validators`:
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

## Fields useful for signing and missed-block calculations

- Validator set at the inspected height: `result.validators[]` from `/validators?height=<height>`.
- Commit signatures for the latest block: `result.block.last_commit.precommits` or `result.block.last_commit.signatures`.
- Signature validator address: `validator_address` or `address` inside each signature entry.
- Signed detection currently treats entries with a non-empty `signature` as signed, and also recognizes Tendermint-style `block_id_flag` commit values.
- Missed validators are calculated by subtracting signer addresses from validator addresses at the same height.

## Limitations and uncertain fields

- Gno.land RPCs may expose either `precommits` or `signatures` depending on the Tendermint/TM2 response shape.
- Transaction payloads in `result.block.data.txs` may be encoded strings or structured JSON. The prototype reports type, size, and a short preview only.
- Validator address formats should be verified on the real Testnet 13 RPC before using them as database keys.
- Commit signature fields such as `block_id_flag`, `absent`, and `signature` need live confirmation for missed-block accuracy.
- The prototype queries only one height and is not a continuous indexer.

## Still needing verification on real Testnet 13 RPC

- The current public RPC URL to place in `GNO_RPC_URL`.
- Whether `/block?height=<height>` and `/validators?height=<height>` are the correct public endpoint paths for Testnet 13.
- Exact node version and chain ID values returned by the live network.
- Exact commit signature shape and whether absent signatures are represented with `absent`, empty `signature`, or `block_id_flag`.
- Whether transaction data is base64, Amino/JSON, or another encoding in live block responses.
