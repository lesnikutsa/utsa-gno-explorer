# utsa-gno-explorer

Custom Gno.land explorer with blocks, validators, uptime and signing history.

## Manual Valopers profile sync

The one-shot command reads `gno.land/r/gnops/valopers` at one pinned committed
height and stores bounded profile metadata. It does not alter the active set,
perform governance actions, expose API fields, or schedule itself.

```bash
python scripts/sync_validator_profiles.py --dry-run
python scripts/sync_validator_profiles.py
```

An Operator Address owns a profile; a Signing Address identifies a TM2 signer.
They are not interchangeable and are linked only through the exact decoded
consensus public-key type and base64 value.

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


## Read-only API foundation

This repository now includes the first minimal FastAPI foundation for the v0.6.0 explorer MVP. This PR adds only the API application package and `GET /api/health`; it does not add production API deployment, frontend work, Nginx, HTTPS, systemd units, Docker packaging for the API, schema migrations, or additional API endpoints.

### API installation

Use Python 3.10+ and install the runtime dependencies:

```bash
python -m pip install -r requirements.txt
```

### API configuration

The API requires `DATABASE_URL` in the environment. Keep credentials outside the repository and do not commit secret values. The API also accepts these optional settings with conservative defaults:

- `API_VERSION` (default `0.6.0`)
- `API_INDEXER_LAG_DEGRADED_THRESHOLD` (default `10`)
- `API_RPC_CHECK_STALE_SECONDS` (default `60`)

Example placeholder configuration:

```bash
export DATABASE_URL='postgresql://user:password@127.0.0.1:5432/utsa_gno_explorer'
```

### Run the API locally

```bash
python -m uvicorn api.app:app --host 127.0.0.1 --port 8000
```

### Health check

```bash
curl http://127.0.0.1:8000/api/health
```

`GET /api/health` performs a read-only PostgreSQL check against the existing `indexer_state` and `rpc_endpoints` tables and returns the database/indexer health summary. Degraded health still returns HTTP 200. Database connection failures, failed health queries, and a missing default `indexer_state` row return HTTP 503 with a generic safe response body.

### Network and blocks API

```bash
curl http://127.0.0.1:8000/api/network
curl 'http://127.0.0.1:8000/api/blocks?limit=20'
curl 'http://127.0.0.1:8000/api/blocks?before_height=869000&limit=20'
curl 'http://127.0.0.1:8000/api/blocks?hash=<exact-hash>'
curl http://127.0.0.1:8000/api/blocks/870117
```

`GET /api/network` returns the completed indexer checkpoint, latest indexed block, validator-set aggregate, and selected RPC metadata using read-only PostgreSQL queries. `GET /api/blocks` returns descending block summaries with cursor pagination or exact hash lookup. `GET /api/blocks/{height}` returns a block summary, commit aggregate, and ordered transactions for one stored block.

### Validators API

```bash
curl http://127.0.0.1:8000/api/validators
```

Validator detail uses the exact consensus signing address and includes validator identity,
current active status and voting power, 20-block and 100-block active-membership uptime,
and chronological signing history for up to 100 actual stored blocks:

```bash
curl http://127.0.0.1:8000/api/validators/<consensus-signing-address>
```

Monikers, logos, and operator addresses remain outside this work.

The list response contains the active validator set at the completed checkpoint, current voting power, and 20-block and 100-block active-membership uptime. Addresses are consensus signing addresses.

## Bounded indexer prototype

This repository includes a one-shot bounded PostgreSQL indexer prototype. It is operator-controlled and intentionally does not run as a daemon, scheduler, cron job, or production historical sync.

Example dry run:

```bash
python scripts/index_range.py --start-height 100 --max-heights 3 --dry-run
```

Example PostgreSQL write run after loading `database/schema.sql` into a temporary database:

```bash
DATABASE_URL=postgresql://utsa_gno_indexer:change-me@localhost:5432/utsa_gno_explorer \
INDEXER_HARD_MAX_HEIGHTS=100 \
python scripts/index_range.py --start-height 100 --max-heights 3
```

Safety behavior:

- defaults to at most 10 heights when no explicit `--end-height` is provided;
- rejects ranges above `INDEXER_HARD_MAX_HEIGHTS`;
- rejects an end height above `finalized_tip = latest_rpc_height - 1`;
- processes each finalized height in its own transaction;
- advances `indexer_state.last_finalized_height` only after a full successful height commit;
- supports idempotent reprocessing and stops on conflicting finalized block hashes.

## Foreground continuous indexer prototype

Issue #7 adds a safe foreground continuous indexer. It is still an operator-run prototype: it does not daemonize itself and this repository still does not include systemd, production PostgreSQL deployment, backend API, or frontend work.

Example foreground run against a temporary PostgreSQL database:

```bash
DATABASE_URL=postgresql://utsa_gno_indexer:change-me@localhost:5432/utsa_gno_explorer \
INDEXER_START_HEIGHT=100 \
python scripts/run_indexer.py --batch-size 10
```

Run exactly one probe/catch-up cycle:

```bash
python scripts/run_indexer.py --start-height 100 --once --batch-size 3
```

Run a deterministic validation window:

```bash
python scripts/run_indexer.py --start-height 100 --max-cycles 5 --batch-size 2
```

The continuous indexer probes all configured RPC endpoints once per cycle, records one `rpc_endpoint_checks` row for each endpoint, selects one healthy endpoint, computes `finalized_tip = latest_rpc_height - 1`, and processes at most `INDEXER_BATCH_SIZE` missing finalized heights in strict order. If it is caught up, it writes no heights and sleeps for `INDEXER_POLL_INTERVAL_SECONDS`.

Press Ctrl+C to request graceful shutdown. The process does not start another height after SIGINT or SIGTERM; if a signal arrives while one height is being written, the existing single-height PostgreSQL transaction either commits completely or rolls back through the database driver. The final log line includes the shutdown reason and checkpoint.

A PostgreSQL advisory lock scoped to `GNO_CHAIN_ID` prevents two continuous indexers for the same chain from running at once. A second process exits with a clear fatal error. The lock uses a dedicated PostgreSQL session and is released on normal exit; losing that PostgreSQL connection naturally releases the session lock.

## Production runtime packaging

Production deployment assets are available for the verified foreground continuous indexer without changing indexing semantics:

- PostgreSQL 16 Docker Compose runtime: `deploy/postgres/compose.yml`
- PostgreSQL example environment: `deploy/postgres/postgres.env.example`
- Host systemd unit: `deploy/systemd/utsa-gno-indexer.service`
- Indexer example environment: `deploy/systemd/indexer.env.example`
- PostgreSQL readiness probe: `scripts/wait_for_postgres.py`
- Operator-controlled schema initialization: `scripts/init_database.py`
- Atomic backup script: `scripts/backup_database.py`
- Full operator guide: [Production deployment](docs/production-deployment.md)

Production secrets are expected outside the repository under `/etc/utsa-gno-explorer`. PostgreSQL binds to localhost only, persists data under `/var/lib/utsa-gno-explorer/postgres` by default, and is started only by an explicit operator `docker compose` command. The Python indexer runs on the host as a foreground systemd service and logs to journald.

### Development and integration tests

Production deployments should install only `requirements.txt`. Developers who need to run the optional PostgreSQL integration tests can create a separate local development virtualenv and install:

```bash
python -m pip install -r requirements-dev.txt
RUN_POSTGRES_INTEGRATION=1 python -m unittest tests.test_postgres_integration -v
```

The integration test starts a temporary `postgres:16.14-bookworm` Docker container, initializes the schema with `scripts/init_database.py`, validates a second run, checks catalog objects, verifies incompatible schema rejection, and confirms failed initialization rolls back partial DDL. It is skipped unless `RUN_POSTGRES_INTEGRATION=1` is set and Docker is available.
