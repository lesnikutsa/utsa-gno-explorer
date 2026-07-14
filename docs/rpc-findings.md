# RPC findings for Gno.land Testnet 13

This document records the response fields targeted by `scripts/inspect_rpc.py`.
The prototype is intentionally small and should be verified against a real
public Testnet 13 RPC before these paths are treated as stable production input.

## RPC methods used

- `GET /status` for node information, chain ID, preferred `result.build_version`, latest known height, and sync status.
- `GET /block?height=<latest_height>` for latest block header, block hash, proposer, timestamp, and transactions.
- `GET /commit?height=<latest_height - 1>` for signing analysis precommits and canonical commit data.
- `GET /validators?height=<latest_height - 1>` for the validator set that must be compared with the commit at the same height.

## Verified TM2 height relationship

For latest height `H` from `/status`:

- `/block?height=H` is used only for latest block metadata, `result.block_meta.block_id.hash`, header `num_txs`, and transaction summary.
- Block `H` `last_commit` must not be treated as signatures for block `H`.
- Signing and missed-block analysis uses height `H - 1`.
- `/commit?height=H-1` returns `result.signed_header.header`, `result.signed_header.commit`, `result.signed_header.commit.precommits`, and boolean `result.canonical` for that signing height.
- Commit height is derived from `result.signed_header.header.height`; `signed_header.commit.height` is not expected.
- `/validators?height=H-1` must return `result.block_height` for the same height as the commit.
- The prototype fails clearly if the parsed commit height and validator-set `block_height` do not both equal `H - 1`.

## Important response paths

- `/status`:
  - `result.node_info.network` -> chain ID.
  - `result.build_version` -> preferred node/software version.
  - `result.node_info.version` -> fallback node/software version.
  - `result.sync_info.latest_block_height` -> latest height known by the node.
  - `result.sync_info.catching_up` -> catching-up/sync status.
- `/block`:
  - `result.block_meta.block_id.hash` -> latest block hash as base64 bytes; the script preserves base64 and exposes normalized uppercase hex.
  - `result.block.header.height` -> block height.
  - `result.block.header.time` -> block timestamp.
  - `result.block.header.proposer_address` -> proposer address.
  - `result.block.header.num_txs` -> transaction count; the script verifies it equals `len(result.block.data.txs)`.
  - `result.block.data.txs` -> raw base64 transactions present in the block response.
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
- Block hash: `result.block_meta.block_id.hash` preserved as base64 and exposed as normalized hex.
- Timestamp: `result.block.header.time`.
- Proposer address: `result.block.header.proposer_address`.
- Transaction count: `result.block.header.num_txs`, validated against length of `result.block.data.txs`.
- Raw transaction base64, encoded character length, decoded byte length when valid, short preview, and base64 decode status from `result.block.data.txs`.

## Fields useful for Active Validators

- Validator address: `result.validators[].address`.
- Voting power: `result.validators[].voting_power`.
- Public key type and value: `result.validators[].pub_key["@type"]` and `result.validators[].pub_key.value`; `/tm.PubKeyEd25519` is displayed as `Ed25519`.
- Proposer priority: `result.validators[].proposer_priority`, if present and meaningful on the live RPC.
- Validator-set height: `result.block_height` from `/validators?height=<H-1>`.

## Fields useful for signing and missed-block calculations

- Signing analysis height: latest height `H` minus one.
- Validator set at the signing height: `result.validators[]` from `/validators?height=<H-1>`.
- Commit precommits at the signing height: `result.signed_header.commit.precommits` from `/commit?height=<H-1>`.
- Signature validator address: `validator_address` or `address` inside each non-null precommit entry.
- The discovery prototype currently reports signer addresses from non-null precommit entries, but production signing detection must additionally parse `Vote.BlockID` and compare it with the enclosing `Commit.BlockID`. A non-null signature alone is not sufficient.
- Null or non-object precommit entries are treated as not signed and never crash parsing; production indexing must not map null precommits to validators by array position unless that relationship is explicitly verified.
- Missed validators are calculated by subtracting signer addresses from validator addresses at the same height.

## RPC endpoint fallback behavior

- Endpoints are read from `GNO_RPC_URLS` as a comma-separated ordered list.
- Legacy `GNO_RPC_URL` is supported only when `GNO_RPC_URLS` is unset.
- Expected chain ID is read from `GNO_CHAIN_ID` and defaults to `test-13`.
- Maximum acceptable height lag is read from `RPC_MAX_HEIGHT_LAG` and defaults to `10`.
- Every endpoint is probed with `/status` before selection.
- Malformed status responses, wrong chain IDs, and catching-up endpoints are rejected.
- The highest height among healthy endpoints is used as the freshness reference.
- The selected endpoint is the first configured healthy endpoint whose height is within `RPC_MAX_HEIGHT_LAG` of the highest healthy height.
- Health output reports height and lag for every responding healthy endpoint.
- The script fails clearly if no configured endpoint is suitable.

## Live verification

Live verification succeeded on 2026-07-14 from server `exp2` against all five configured public Gno.land Testnet 13 RPC endpoints. All five endpoints reported chain ID `test-13`, `catching_up=false`, and the same latest height at the time of the check. This document intentionally does not pin that live height because it changes continuously.

Confirmed live shapes:

- Block hash is at `result.block_meta.block_id.hash`; `result.block_id` was not present. The hash is base64-encoded bytes.
- Validator public keys use `result.validators[].pub_key["@type"]`, for example `/tm.PubKeyEd25519`, plus `value`.
- Block transactions in `result.block.data.txs` are base64 strings.
- Block transaction count is exposed as `result.block.header.num_txs`.
- Validator responses expose `result.block_height` for the validator-set height.

## Limitations and uncertain fields

- Transaction payloads in `result.block.data.txs` are preserved as base64 and not decoded into full Gno transaction structures yet.
- Validator address formats should be verified on the real Testnet 13 RPC before using them as database keys.
- Commit vote fields, including parsed `Vote.BlockID`, enclosing `Commit.BlockID`, nil-vote representation, validator address paths, and signature fields, need live confirmation for accurate commit/nil/absent/invalid classification.
- The prototype queries only one latest height and one signing height and is not a continuous indexer.

## Still needing verification on real Testnet 13 RPC

- Which public RPC endpoint is most reliable for `GNO_RPC_URLS` ordering.
- Exact node version and chain ID values returned by the live network.
- Exact commit precommit shape, parsed `Vote.BlockID` paths, nil-vote representation, and whether absent signatures are represented with `null`, `absent`, or empty `signature`.
- Whether transaction data is base64, Amino/JSON, or another encoding in live block responses.
