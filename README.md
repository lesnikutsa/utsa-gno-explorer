# utsa-gno-explorer

Custom Gno.land explorer with blocks, validators, uptime and signing history.

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
RPC endpoints from `GNO_RPC_URLS`, a comma-separated ordered list. For temporary
backward compatibility, it also accepts legacy `GNO_RPC_URL` when
`GNO_RPC_URLS` is not set.

```bash
GNO_RPC_URLS="https://gnoland-testnet-rpc.itrocket.net,https://rpc.test13.testnets.gno.land" python scripts/inspect_rpc.py
```

Do not commit private RPC URLs or secrets.

### Run the RPC inspection

```bash
python scripts/inspect_rpc.py
```

The script checks each configured RPC in order with `/status`, prints whether the
check succeeded or failed, rejects catching-up nodes, selects the first healthy
endpoint without silently switching, and then prints the selected RPC clearly.

The output summarizes chain ID, latest block height, signing analysis height
(`latest height - 1`), node version, sync status, latest block metadata, validator
set, `/commit` canonical data, commit precommits, validators that signed or
missed, and basic transaction information available in the block response.

### Run tests

```bash
python -m py_compile scripts/inspect_rpc.py
python -m unittest discover -s tests
```
