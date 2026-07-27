# utsa-gno-explorer

Custom Gno.land explorer with blocks, validators, uptime and signing history.

## Design documentation

- [Architecture](docs/architecture.md)
- [Database schema](docs/database-schema.md)
- [Indexer flow](docs/indexer-flow.md)
- [Backup and recovery](docs/backup-and-recovery.md)
- [Database README](database/README.md)
- [PostgreSQL schema](database/schema.sql)

## Active network

The single-network Explorer runtime now targets **Gno.land Topaz Testnet** with chain ID
`topaz-1`. Topaz is a fresh chain: initialize the existing PostgreSQL database as empty,
do not reuse Testnet 13 rows or checkpoints, and start indexing at block `1`. The ordered
RPC list is `https://rpc.topaz.testnets.gno.land`,
`https://gnoland-testnet-rpc.itrocket.net`, then `https://topaz.rpc.onbloc.xyz`.

## RPC discovery prototype

This repository contains an RPC inspection utility configured for the active
Gno.land Topaz Testnet runtime.

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
chain ID with `GNO_CHAIN_ID` (default `topaz-1`), and limits acceptable endpoint
staleness with `RPC_MAX_HEIGHT_LAG` (default `10`). For temporary backward
compatibility, it also accepts legacy `GNO_RPC_URL` when `GNO_RPC_URLS` is not
set.

```bash
GNO_RPC_URLS="https://rpc.topaz.testnets.gno.land,https://gnoland-testnet-rpc.itrocket.net,https://topaz.rpc.onbloc.xyz" python scripts/inspect_rpc.py
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


## v0.10.0 Transactions List and Global Search

This release adds the cursor-paginated transaction list API, a dedicated **Transactions**
sidebar page, and exact transaction-hash lookup in the global search. Transaction rows expose
the block time, full 64-character hash when available, canonical type, and human-readable
operation through a minimal public response. The sidebar order is **Overview**, **Blocks**, **Transactions**,
then **Validators**. The page presents **TX HASH**, **TIME**, **BLOCK**, and **TYPE**, requests
25 rows, labels its position as **Latest** or **Page N**, provides newer/older pagination,
links hashes to the existing
`/blocks/:block_height/transactions/:index` detail route, links block heights to their blocks,
and places a copy action beside each available hash. Rows without a hash remain available
through their block-height/index detail route.

Global search now accepts block height, exact block hash, exact transaction hash, validator
moniker, validator signing address, and validator operator address. Transaction hashes are
case-insensitive and may include a `0x` or `0X` prefix; partial transaction hash search is not
supported. Blocks no longer have a redundant local exact-search field, while the Validators
table retains its local filter. Transaction detail navigation identifies **Transactions** as
the active section and links back to the transaction list.

Transaction-list pagination uses the paired `block_height`/`tx_index` cursor, with
explicitly typed PostgreSQL parameters for the first page. Exact transaction-hash lookup uses
the existing transaction-hash index with exact equality and `LIMIT 1`. Invalid, missing, and
unavailable lookups return safe 422, 404, and 503 responses, while malformed frontend lookup
responses do not produce unsafe navigation.

Execution result/status, gas wanted/used, transaction fee, and mempool/pending transactions
are not indexed yet. Historical rows without a structured payload summary may appear as a
generic **Transaction**. This release-preparation change updates documentation only and does
not change runtime code, the database schema, migrations, or deployment configuration.

## Read-only API foundation

Global search supports block height, exact block hash, exact transaction hash,
validator moniker, validator signing address, and validator operator address.
Partial transaction hash search is not supported. A matching transaction opens
the existing `/blocks/:block_height/transactions/:index` detail route.

The read-only API contract is version 0.8.0.

### API installation

Use Python 3.10+ and install the runtime dependencies:

```bash
python -m pip install -r requirements.txt
```

### API configuration

The API requires `DATABASE_URL` in the environment. Keep credentials outside the repository and do not commit secret values. The API also accepts these optional settings with conservative defaults:

- `API_VERSION` (default `0.8.0`; update the production environment separately after merge)
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

Validator list and detail responses are enriched from the persisted official Valopers
snapshot by exact, case-sensitive `signing_address` equality. A SQL `LEFT JOIN` keeps
unmatched validators visible with null profile fields; `valoper_source_height` is the
pinned Valopers snapshot height represented by a profile. The API reads PostgreSQL only
and never queries the Valopers RPC directly. Valopers profiles continue to be refreshed
by the existing manual, operator-controlled persistence process.

The full Validators table and the Overview **Validators by Missed Blocks** identities link
to `/validators/<signing-address>`, preserving the exact consensus signing address as the
route identity. The full table supports immediate, case-insensitive partial filtering by
official moniker or signing address over the already loaded active set, without another API
request. Filtering preserves the original voting-power **Power Rank**, while **Active
Validators** remains the complete active-set count.

Validator detail pages refresh every 2 seconds and show **Current Status** plus 100 actual
indexed signing blocks. Signing history distinguishes commit, nil, absent, invalid, unknown,
and not-active states. The profile presents the signing address, operator address, official
Valopers signing public key (`gpub1...`), RPC consensus public-key type and value, and the
Valopers description.

**Peers & Decentralization Map** remains a coming-soon presentation area.

### Network and blocks API

```bash
curl http://127.0.0.1:8000/api/network
curl http://127.0.0.1:8000/api/network/distribution
curl 'http://127.0.0.1:8000/api/blocks?limit=20'
curl 'http://127.0.0.1:8000/api/blocks?before_height=869000&limit=20'
curl 'http://127.0.0.1:8000/api/blocks?hash=<exact-hash>'
curl http://127.0.0.1:8000/api/blocks/870117
curl 'http://127.0.0.1:8000/api/transactions?limit=20'
curl 'http://127.0.0.1:8000/api/transactions?limit=25'
curl 'http://127.0.0.1:8000/api/transactions?before_height=<height>&before_tx_index=<index>&limit=25'
curl 'http://127.0.0.1:8000/api/transactions/by-hash/<exact-transaction-hash>'
```

`GET /api/network` returns the completed indexer checkpoint, latest indexed block, validator-set aggregate, and selected RPC metadata using read-only PostgreSQL queries. `GET /api/blocks` returns descending block summaries with cursor pagination or exact hash lookup. `GET /api/blocks/{height}` returns a block summary, commit aggregate, and ordered transactions for one stored block.

`GET /api/transactions` returns stored transactions in descending `(block_height, index)`
order. Its read-only cursor consists of both `before_height` and `before_tx_index`; the
response supplies both values from the final item whenever another page is available.
The backend default is 20, and clients may explicitly request any supported page size from
1 through 100. The Explorer **Transactions** page requests 25 items to match the existing
Blocks page without changing the general API default. Each item contains the
block height, transaction index, nullable transaction hash, block time, canonical
transaction type, and human-readable operation.

`GET /api/transactions/by-hash/{tx_hash}` performs an exact transaction lookup. It accepts
uppercase or lowercase hashes with an optional `0x` or `0X` prefix, but does not support
partial hashes. A match supplies the block height and transaction index used by the existing
`/blocks/:block_height/transactions/:index` frontend detail route.

`GET /api/network/distribution` returns the latest persisted observed network-distribution
snapshot. It is not a complete network census. Coverage percentages use unique public IPs
as their denominator, while ranking shares use geolocated public IPs. `updated_at` is the
collector scan timestamp. The response exposes no raw peer identity or IP address. HTTP
404 means that no collector snapshot exists yet; HTTP 503 means that the database is
unavailable or persisted aggregate validation failed.

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

The full active-validator table and the Overview **Validators by Missed Blocks** table
show official Valopers monikers when available, fall back to the shortened signing address,
and link identities to the detail route. Inactive indexed validators remain valid detail
pages. Profiles come from the manually persisted official Valopers snapshot, and refresh
remains operator-controlled.
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

## Read-only Valopers source probe

The bounded probe selects a healthy configured RPC, pins its committed latest height,
and requests only the Valopers root render by default:

```bash
python scripts/probe_valopers.py
```

Explicit page and validator detail renders can be requested without parsing or crawling
the root document. All requests in one run use the same pinned height:

```bash
python scripts/probe_valopers.py --page-query '?page=2'
python scripts/probe_valopers.py --operator-address g1xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

The probe validates and decodes bounded render data from the live TM2/Amino
`result.response.ResponseBase.Data` contract. It is read-only and prints only bounded
metadata, a SHA-256 digest, and a short sanitized preview; it does not persist, parse,
or synchronize Valopers data.

### Complete in-memory Valopers snapshot

`python scripts/probe_valopers_snapshot.py` selects one healthy RPC and collects every
Valopers list page and detail sequentially at one pinned height. Collection has fixed
page and profile bounds. Transient RPC request failures have a small bounded retry on the
same endpoint and pinned height; response decoding and consistency failures fail
immediately. Retries never fail over or repin, and exhausting them fails the complete
snapshot without a partial result. Pagination completion comes from the validated official
picker, not page length, and no artificial empty terminal page is requested. Under the
official contract a one-page registry has no picker. The immutable result remains in memory;
database persistence and application integration are intentionally outside this in-memory
probe; the separate persistence process and Explorer consume Valopers profiles.

Add `--parse` to validate and print a bounded summary of either supported document:
a paginated Valopers list or one Valoper detail render. Detail parsing exposes the
moniker, description, operator and signing addresses, signing public key, server type,
and profile path. The current Render output does not expose `KeepRunning`, so it is not
inferred. Signing-public-key validation is syntax and length validation only; it does
not verify a Bech32 checksum or Amino encoding. Parsing remains read-only and does not
persist or synchronize data.

The explicit `abci_query` request height pins the render to that immutable state version.
Current Testnet 13 qrender responses return `Height="0"`, meaning the response does not
duplicate the requested height; any future non-zero reported height must match the pin.

### Manual Valopers snapshot persistence

After merge and operator review, run `python scripts/persist_valopers_snapshot.py` to
collect at one pinned height and populate the two Valopers tables. The complete replacement
uses one PostgreSQL transaction and a dedicated transaction-scoped advisory lock. Stale
and divergent same-height snapshots are rejected; identical same-height snapshots are
unchanged. Empty registries use zero profile rows and one state row. Failures roll back.
No schedule, systemd service, or timer invokes the writer. The API and frontend read the
stored profiles after an operator persists them. This does not claim production contains
populated rows.

Fresh databases use `python scripts/init_database.py`; existing
production databases require the explicit additive migration documented in
[`database/README.md`](database/README.md). The migration is transactional,
preserves indexed data, is safe to rerun after success, and is never run by an
application, service, container, or Compose startup path.

## Governance discovery

`scripts/inspect_governance.py` is a read-only diagnostic tool that discovers proposals
from the configurable `gno.land/r/gov/dao` proxy realm through `vm/qrender`. It selects a
healthy configured RPC, follows bounded internal list pagination, and retrieves proposal
detail and vote renders. It does not modify the database, schema, API, frontend, or
production environment.

```bash
python3 scripts/inspect_governance.py --json
python3 scripts/inspect_governance.py --proposal 20 --raw-dir /tmp/gno-governance-raw
```

Use `--realm` or `GNO_GOVERNANCE_REALM` to override the proxy realm; the CLI option takes
precedence. Raw renders are written only when `--raw-dir` is supplied (or embedded in JSON
only with `--include-raw`). Discovery is parser-based and deliberately reports unknown
formats and ambiguous pagination as incomplete instead of inferring data. This diagnostic
tool is not a production Governance API or a completed Explorer user feature.
