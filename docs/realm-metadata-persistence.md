# Realm and Package metadata persistence

This persistence layer supports a manual, one-shot metadata collector. It does
not expose metadata through the API or frontend.

## Manual collection

No schedule, timer, or recurring service is installed. An operator runs the
collector only when desired:

```sh
sudo -u utsa-gno sh -c '
  set -a
  . /etc/utsa-gno-explorer/indexer.env
  . /etc/utsa-gno-explorer/rpc.env
  set +a
  cd /opt/utsa-gno-explorer
  exec .venv/bin/python scripts/refresh_realm_metadata.py
'
```

Use `--limit 5` for a small smoke run, or repeat
`--path gno.land/r/example` for targeted current catalog paths. Collection is
sequential and anchored to the current `realm_catalog_state` height. It is safe
to rerun: unchanged file fingerprints avoid child-row churn, and a failed path
preserves its previously published metadata. Render responses are summarized in
memory; qrender bodies are never persisted, logged, or included in reports.

## Schema

The schema contains exactly four metadata tables:

* `realm_metadata` holds one current snapshot per chain and Gno path, including
  bounded capability state and the last successful optional metadata values.
* `realm_metadata_files` holds every UTF-8 text file in the published `qfile`
  snapshot. A file is limited to 1 MiB, a snapshot to 256 files, and the total
  persisted content for a path to 8 MiB.
* `realm_metadata_imports` holds canonical `gno.land/r/...` and
  `gno.land/p/...` imports extracted from persisted Gno source. An import target
  need not exist in `realm_catalog`.
* `realm_metadata_refresh_state` holds bounded run-level state for the manual
  collector; it does not schedule or execute a run.

## Publication and preservation

A path snapshot is validated before destructive writes and published in one
PostgreSQL transaction. The parent, exact files, derived imports, and aggregate
counters therefore become visible together. A failure rolls the entire
publication back. Identical file fingerprints update current metadata without
churning file or import rows; changed fingerprints replace both child sets.
Publication locks the exact `realm_catalog` parent row before reading current
metadata, which serializes first publication for that path without a global lock.
The validated non-empty `qfile` listing is supplied separately from fetched
content, and publication requires their filename sets to match exactly. A stale
height, or an older collection at the same height, cannot replace the current
canonical snapshot.

The fingerprint is SHA-256 over files sorted by their UTF-8 filename. Each exact
filename and exact UTF-8 content is encoded as an unsigned 8-byte big-endian
length followed by its bytes. This is deterministic, ordering-independent, and
unambiguous.

Successful `qdoc`, `qpkg_json`, and `qfuncs` bounded payloads and summaries are
retained if a later attempt fails. The same preservation rule applies to the
successful `qrender` hash/count summary and `qstorage` integer summary while the
current status records the latest attempt. A Render body is never accepted or
persisted.
Successful JSON summaries are derived by rerunning the capability-specific
bounded parser over the raw JSON payload; callers cannot supply summaries.
PostgreSQL-incompatible NUL characters are rejected in file content and in
bounded JSON string values and keys before publication.

Refresh-run updates are ordered by observed height and start time. Starting or
failing a later run without a successful checkpoint preserves the most recent
successful height and timestamp rather than erasing them.

## Privileges and deferred work

The explicit metadata DML contract for `utsa_gno_indexer` is `SELECT`, `INSERT`,
`UPDATE`, and `DELETE` on all four tables. In the documented production setup the
writer also owns the schema and tables, so its effective owner privileges may be
broader. `utsa_gno_api` remains the strict privilege boundary and intentionally
receives no metadata-table access. Metadata collection, public API access,
frontend presentation, and Render execution are deferred to separately reviewed
changes.
