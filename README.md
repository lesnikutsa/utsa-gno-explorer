# utsa-gno-explorer

Custom Gno.land explorer with blocks, validators, uptime and signing history.

## Design documentation

- [Architecture](docs/architecture.md)
- [Database schema](docs/database-schema.md)
- [Indexer flow](docs/indexer-flow.md)
- [Backup and recovery](docs/backup-and-recovery.md)
- [Database README](database/README.md)
- [PostgreSQL schema](database/schema.sql)

## RPC discovery prototype

This repository currently contains a small Python prototype for inspecting the
Gno.land Testnet 13 RPC before adding an indexer, database, backend, or
frontend.

### Requirements

- Python 3.11+
- `requests` preferred; the script also has a standard-library HTTP fallback if
  `requests` is not installed.

### Installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Configuration

Copy the example environment file and review the ordered public RPC fallbacks:

```bash
cp .env.example .env
```

The script automatically loads simple `KEY=VALUE` entries from `.env`. It reads
RPC endpoints from `GNO_RPC_URLS`, a comma-separated ordered list, validates the
chain ID with `GNO_CHAIN_ID` (default `test-13`), and limits acceptable endpoint
staleness with `RPC_MAX_HEIGHT_LAG` (default `10`). For temporary backward
compatibility, it also accepts legacy `GNO_RPC_URL` when `GNO_RPC_URLS` is not
set.

```bash
GNO_RPC_URLS="https://gnoland-testnet-rpc.itrocket.net,https://rpc.test13.testnets.gno.land" python scripts/inspect_rpc.py
```

Do not commit private RPC URLs or secrets.

### Run the RPC inspection

```bash
python scripts/inspect_rpc.py
```

The script probes every configured RPC with `/status`, prints a health result for
each responding endpoint, rejects malformed status responses, wrong chain IDs,
and catching-up nodes, determines the highest healthy height, and selects the
first configured endpoint whose height is within `RPC_MAX_HEIGHT_LAG` of that
highest height.

The output summarizes chain ID, latest block height, signing analysis height
(`latest height - 1`), node version, sync status, latest block metadata, block
hash in original base64 and normalized hex, validator set, `/commit` canonical
boolean, commit precommits, validators that signed or missed, and basic
transaction information. Transactions are preserved as raw base64 with encoded
length, decoded byte length when valid, a short preview, and a flag indicating
whether base64 decoding succeeded.

### Live verification note

Live verification succeeded on 2026-07-14 from server `exp2` against all five
configured public Gno.land Testnet 13 RPC endpoints. All five reported chain ID
`test-13`, `catching_up=false`, and the same latest height at the time of that
check. The code remains strict and still validates chain ID, sync status,
response shape, and endpoint lag on every run.

### Run tests

```bash
python -m py_compile scripts/inspect_rpc.py
python -m unittest discover -s tests
```
