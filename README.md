# utsa-gno-explorer

Custom Gno.land explorer with blocks, validators, uptime and signing history.

## RPC discovery prototype

This repository currently contains a small Python prototype for inspecting the
Gno.land Testnet 13 RPC before adding an indexer, database, backend, or
frontend.

### Requirements

- Python 3.11+
- `requests`

### Installation

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

### Configuration

Copy the example environment file and set `GNO_RPC_URL` to a public Gno.land
Testnet 13 RPC endpoint:

```bash
cp .env.example .env
export GNO_RPC_URL="https://rpc.test13.gno.land"
```

The script reads the RPC URL only from `GNO_RPC_URL`; do not commit private RPC
URLs or secrets.

### Run the RPC inspection

```bash
python scripts/inspect_rpc.py
```

The output summarizes chain ID, latest height, node version, sync status, latest
block metadata, validator set, commit signatures, validators that signed or
missed, and basic transaction information available in the block response.

### Run tests

```bash
python -m unittest discover -s tests
```
