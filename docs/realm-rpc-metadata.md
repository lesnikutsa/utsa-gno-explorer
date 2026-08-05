# Realm and Package RPC metadata probe

`scripts/probe_realm_rpc_metadata.py` is an operator-run, one-shot capability probe for
Gno RPC metadata query behavior. It discovers response formats safely and does not persist
metadata.

## Queries

Common Realm and Package probes:

- `vm/qfile` with data `<path>` for package file listing.
- `vm/qfile` with data `<path>/<filename>` for at most one bounded `.gno` source sample.
- `vm/qfuncs` with data `<path>`.
- `vm/qdoc` with data `<path>`.
- `vm/qpkg_json` with data `<path>`.

Realm-only probes:

- `vm/qrender` with data `<realm-path>:`.
- `vm/qstorage` with data `<realm-path>`.

Package paths mark `qrender` and `qstorage` as `not_applicable` and do not issue those RPC
queries.

## Safety and scope

The probe reuses the existing configured RPC selection, health, chain-id, stale-endpoint,
timeout, response-size, and UTF-8 validation paths. Output is bounded and sanitized: raw
source, docs, qpkg JSON, Render body, RPC credentials, database URLs, and query payloads are
not printed or written to JSON reports. Error codes are selected from static parser/RPC classifications and are never derived from raw exception text.

This change is capability discovery only. It adds no database persistence, no migrations,
no frontend, no API endpoint, no production service, and no scheduled collector. Import
extraction from the one optional source sample is an approximate diagnostic summary only;
it is not a dependency graph.

Live Topaz support remains unverified until an operator runs this probe against configured
Topaz RPC endpoints.

## CLI examples

Probe one Realm using the first suitable RPC:

```bash
PYTHONPATH=. python scripts/probe_realm_rpc_metadata.py \
  --realm-path gno.land/r/demo/users
```

Probe one Package and write a sanitized JSON report:

```bash
PYTHONPATH=. python scripts/probe_realm_rpc_metadata.py \
  --package-path gno.land/p/demo/avl \
  --json-output /tmp/package-metadata-probe.json
```

Probe every suitable RPC endpoint independently:

```bash
PYTHONPATH=. python scripts/probe_realm_rpc_metadata.py \
  --realm-path gno.land/r/demo/users \
  --all-suitable-rpcs
```

Each endpoint uses its own finalized height, `latest_height - 1`; height differences between
healthy endpoints are reported, not treated as failures. The CLI accepts at most twenty total Realm and Package paths and rejects duplicate paths.

## JSON report

`--json-output` writes schema version `1` with `generated_at`, `chain_id`, endpoint/path
results, query statuses, elapsed times, byte counts, safe error codes, and compact summaries.
The file is written atomically through a temporary file and `os.replace`, with mode `0600`.
The parent directory must already exist, and symlink output targets are refused where
practical.

## Exit codes

- `0`: probe completed and at least one core `qfile`, `qfuncs`, or `qdoc` result parsed with status `ok`. Realm-only optional application errors can still be reported for a path.
- `1`: invalid CLI, configuration problem, no suitable RPC, or no path could be meaningfully
  probed.
- `2`: report completed, but at least one response was malformed or oversized.
