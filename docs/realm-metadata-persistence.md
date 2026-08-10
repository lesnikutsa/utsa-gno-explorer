# Realm and Package metadata persistence

This persistence layer prepares bounded PostgreSQL storage for a future metadata
collector. It does not collect RPC data and does not expose metadata through the
API or frontend.

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
* `realm_metadata_refresh_state` holds bounded run-level state for a future
  collector; it does not schedule or execute a run.

## Publication and preservation

A path snapshot is validated before destructive writes and published in one
PostgreSQL transaction. The parent, exact files, derived imports, and aggregate
counters therefore become visible together. A failure rolls the entire
publication back. Identical file fingerprints update current metadata without
churning file or import rows; changed fingerprints replace both child sets.

The fingerprint is SHA-256 over files sorted by their UTF-8 filename. Each exact
filename and exact UTF-8 content is encoded as an unsigned 8-byte big-endian
length followed by its bytes. This is deterministic, ordering-independent, and
unambiguous.

Successful `qdoc`, `qpkg_json`, and `qfuncs` bounded payloads and summaries are
retained if a later attempt fails. The same preservation rule applies to the
successful `qrender` hash/count summary and `qstorage` integer summary while the
current status records the latest attempt. A Render body is never accepted or
persisted.

## Privileges and deferred work

`utsa_gno_indexer` receives `SELECT`, `INSERT`, `UPDATE`, and `DELETE` on the four
tables. `utsa_gno_api` intentionally receives no metadata-table privileges in
this change. Metadata collection, public API access, frontend presentation, and
Render execution are deferred to separately reviewed changes.
