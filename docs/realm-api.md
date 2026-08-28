# Realm catalog API

`GET /api/realms` is a read-only PostgreSQL endpoint. It never performs a live Realm or Gno RPC request. The list is compact indexed/aggregated data: one `realm_catalog` row per `(chain_id, path)`, not one row per call. `rpc_visible` is the most recent operator-triggered `vm/qpaths` snapshot, while call statistics cover only the configured local rebuild range and successfully decoded bounded transaction summaries.

Parameters are `limit` (1–100, default 25), `kind` (`all`, `realm`, or `package`), printable `q` (1–128 characters), and the paired `before_activity_height`/`before_path` keyset cursor. Search is a literal case-insensitive substring operation, so `%`, `_`, and backslash have no wildcard meaning. Both summary and items are scoped to the API's configured chain. Results order by last activity descending (missing activity is `-1`) and path ascending. A missing snapshot returns `404 Realm catalog not found`.

A Realm may exist without locally known deployment metadata. Unknown execution results are counted separately and excluded from `success_rate`. Token verification and token classification do not exist yet. Source, documentation, exported functions, Render, storage, balances, and other details are deferred to future bounded on-demand server-side RPC queries.

## Most-called Realms

`GET /api/realms/top?limit=5` returns up to 10 current RPC-visible Realm paths ranked by direct calls found in the Explorer's indexed transaction history. It includes only `path_kind = 'realm'`, `rpc_visible = true`, and `call_count > 0`, ordered by call count descending, last activity height descending (missing height is `-1`), then path ascending.

## Realm namespace ranking

`GET /api/realm-namespaces/top` is a read-only aggregate ranking. `limit` defaults to 5 and accepts 1 through 10. `scope` is `all` (the default) or `curated`. A namespace is the exact first path segment after `gno.land/r/`; case is preserved. A namespace is not automatically an application.

The version-controlled curated registry contains manually reviewed application metadata. With `scope=all`, every qualifying namespace may be returned and unknown namespaces have `application: null`. With `scope=curated`, only registry namespaces are returned and application metadata is always present.

Rows include every Realm in the namespace, including Historical Realms, but a namespace qualifies only when at least one member is visible in the current RPC catalog and its aggregate has at least one indexed direct call. Packages are excluded. Ranking is `direct_call_count` descending, latest activity height descending (null is treated as `-1`), then the exact namespace key in PostgreSQL `C` order.

Each item includes aggregate Realm, called-Realm, RPC-visible-Realm, successful, failed, unknown-result, and direct-call counts; minimum non-null first-seen height; and the linked latest activity height, transaction index, and timestamp. `success_rate` is `successful / (successful + failed)` and is null when that denominator is zero. Unknown results are not failures.

Members are ordered by exact path in `C` order and include both current and Historical Realms. At most 100 members are returned per namespace; `realms_truncated` reports whether more exist.

The source records `chain_id`, `indexed_height`, `catalog_observed_height`, `activity_from_height`, and `activity_through_height`. The former is the first height in the continuous Realm activity measurement range; the latter is the last height whose transaction-derived Realm activity was atomically processed and whose coverage was confirmed. Live indexing advances coverage only for the exact next height; a larger lag requires a full counter rebuild and cannot be repaired from block metadata alone. These fields are distinct from the indexer checkpoint and catalog observation height, even though aligned live indexing normally keeps `activity_through_height` equal to `indexed_height`. Source, aggregates, and members are read in one repeatable-read, read-only transaction.

Compact response example (metrics are illustrative):

```json
{"source":{"chain_id":"pearl-1","indexed_height":50,"catalog_observed_height":49,"activity_from_height":1,"activity_through_height":45},"scope":"all","items":[{"namespace_key":"gnoswap","application":{"display_name":"GnoSwap","category":"DeFi","description":null,"website":null,"metadata_source":"curated_registry"},"realm_count":1,"called_realm_count":1,"rpc_visible_realm_count":1,"direct_call_count":2,"successful_call_count":1,"failed_call_count":0,"unknown_result_call_count":1,"success_rate":1.0,"first_seen_height":2,"last_activity_height":40,"last_activity_tx_index":1,"last_activity_at":"2026-08-04T00:00:00Z","realms":[{"path":"gno.land/r/gnoswap/example","rpc_visible":true,"first_seen_height":2,"last_activity_height":40,"last_activity_tx_index":1,"last_activity_at":"2026-08-04T00:00:00Z","call_count":2,"successful_call_count":1,"failed_call_count":0,"unknown_result_call_count":1,"success_rate":1.0}],"realms_truncated":false}]}
```

The response's `source.activity_from_height` identifies the beginning of the indexed measurement range; the metric must not be interpreted as usage since genesis unless that range begins at genesis. Package imports are not measured by this lifetime endpoint. The source also reports the chain, current indexed height, catalog observation height, and activity-through height used by the consistent read-only database snapshot.

## Time-window Realm application ranking

`GET /api/realm-applications/top` is a separate PostgreSQL-only, read-only ranking for the Applications panel. `limit` defaults to 3 and accepts 1 through 10; `window` defaults to `24h` and accepts only `24h`, `7d`, or `30d`. The accepted values map to fixed server-side durations. The endpoint never performs a live Gno RPC call and does not change the lifetime semantics of `/api/realm-namespaces/top`.

The end of every window is the timestamp of `indexer_state.last_finalized_height`, not the database or API server wall clock. Calls come from `realm_call_index`, are joined to block timestamps and transaction-level execution results, and each direct `MsgCall` row counts once. Only calls inside the selected time range and continuous call-index height range participate. Packages are excluded. A namespace must have at least one current Realm catalog member and at least one RPC-visible Realm.

Namespaces are discovered automatically from the exact first path segment after `gno.land/r/`; address-like segments are retained. The curated application registry is optional presentation metadata: GnoSwap is enriched when present, while any unknown qualifying namespace remains visible with `application: null`. No brand or category is inferred.

The source reports the chain, indexed checkpoint height, call-index from/through heights, coverage start timestamp, selected window start and end timestamps, selected window, and all fully available windows. Coverage must extend continuously through the checkpoint and must begin no later than the requested window start. A published `realm_catalog_state` snapshot for the requested chain is also required because membership and RPC visibility come from that snapshot. Otherwise the endpoint fails closed with `409 Realm application activity is not available for this window`; it never labels partial history as a complete period. Missing catalog/checkpoint state and unexpected database failures also use bounded, static public errors.

Each item includes Realm and RPC-visible Realm counts, distinct called Realm paths, direct/successful/failed/unknown call counts, success rate, and the latest call height, transaction index, message index, and timestamp. Success rate excludes unknown results. Ranking is direct calls descending, latest activity position and timestamp descending, then the exact namespace key in PostgreSQL `C` order.

## Realm or Package detail

`GET /api/realms/detail?path=gno.land/r/gnoswap/app` returns one exact catalog row for a canonical `gno.land/r/...` Realm or `gno.land/p/...` Package path. The path is a query parameter because canonical Gno paths contain `/`; the endpoint does not use a catch-all route. The API is PostgreSQL-only and does not call Gno RPC.

Example response:

```json
{"source":{"chain_id":"pearl-1","indexed_height":50,"catalog_observed_height":49,"catalog_refreshed_at":"2026-08-04T00:00:00Z","activity_from_height":1,"activity_through_height":45,"call_index_from_height":1,"call_index_through_height":50,"call_index_complete":true},"item":{"path":"gno.land/r/gnoswap/app","name":"app","kind":"realm","rpc_visible":true,"deployer_address":null,"deploy_height":2,"deploy_tx_index":0,"first_seen_height":2,"last_activity_height":40,"last_activity_tx_index":1,"last_activity_at":"2026-08-04T00:00:00Z","call_count":2,"successful_call_count":1,"failed_call_count":0,"unknown_result_call_count":1,"success_rate":1.0},"namespace_key":"gnoswap","application":{"display_name":"GnoSwap","category":"DeFi","description":null,"website":null,"metadata_source":"curated_registry"}}
```

Detail responses preserve the `RealmCatalogItem` catalog semantics used by `GET /api/realms`. Realm responses include the exact namespace key and only curated application metadata from the registry. Package responses set `namespace_key` and `application` to `null`; the API does not infer applications or guessed categories.

The detail source is read in one `REPEATABLE READ, READ ONLY` transaction with the exact catalog row, catalog state, call-index state, and default indexer checkpoint. `call_index_complete` is true only when `realm_call_index_state.through_height` equals `indexer_state.last_finalized_height`; missing, behind, ahead, or mismatched coverage is not reported as complete. Missing catalog rows return `404`; malformed paths return `422`; unavailable or inconsistent database state returns `503`.

## Realm or Package metadata

`GET /api/realms/metadata?path=gno.land/r/gnoswap/app` returns the bounded, persisted metadata summary, complete file metadata list, and up to 200 distinct ordered dependencies for an exact canonical Realm or Package path. `dependencies_truncated` indicates additional dependencies. The endpoint is database-backed only; it never performs live RPC. A catalog path may legitimately return `404 Realm metadata not found` until the one-shot collector visits it, and `collection_status=partial` remains a valid useful snapshot.

Only validated qdoc, qpkg_json, and qfuncs summaries are exposed. Raw capability payloads and the qrender body are never returned; qstorage numeric values are decimal strings to preserve precision.

`GET /api/realms/metadata/file?path=gno.land/r/gnoswap/app&filename=main.gno` returns one exact source file from the persisted qfile snapshot. The filename is an exact database key rather than a filesystem path. Source content is omitted from the main metadata response and returned only by this endpoint; neither metadata endpoint contacts RPC.

## Realm recent calls

`GET /api/realms/calls?path=gno.land/r/gnoswap/app` returns a descending page of recent direct calls for one exact canonical Realm path. Package paths are rejected with `422`; malformed paths are rejected with `422`; unknown Realm catalog paths return `404`. The endpoint is PostgreSQL-only, uses `realm_call_index`, and does not inspect `transactions.payload_summary` or call Gno RPC.

Calls are available only when call-index coverage is complete for the default checkpoint. Missing, behind, or ahead coverage returns `409` with a stable `Realm call history is not available` detail instead of returning an implicit partial history, and the page query is not executed while coverage is unavailable. `from_height` is the earliest block height for which the Realm call history is claimed complete; it is not necessarily genesis.

Example response:

```json
{"source":{"chain_id":"pearl-1","path":"gno.land/r/gnoswap/app","indexed_height":50,"from_height":1,"through_height":50},"items":[{"block_height":40,"tx_index":1,"message_index":0,"block_time":"2026-08-04T00:00:00Z","tx_hash":"0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF0123456789ABCDEF","caller_address":"g1qqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqqq","function_name":"Render","args_count":0,"send_amount":"1ugnot","execution_status":"success","gas_wanted":"100000","gas_used":"50000"}],"pagination":{"limit":25,"next_before_height":null,"next_before_tx_index":null,"next_before_message_index":null}}
```

Returned call rows are restricted to the exact claimed coverage range `[from_height, through_height]`. Physical `realm_call_index` rows outside that range are never public, even if they exist in PostgreSQL. Pagination uses `limit` with a default of 25 and a maximum of 100. The cursor consists of all three fields: `before_height`, `before_tx_index`, and `before_message_index`; clients must send all three together or omit all three. The descending database query uses tuple `<` over `(block_height, tx_index, message_index)` and `limit + 1`, never `OFFSET`. When an older row exists, the next cursor is the last visible item returned to the client.

Each `MsgCall` message is returned as its own row, including multiple calls in the same transaction and repeated calls to the same Realm. Rows are not deduplicated by transaction hash. `execution_status`, `gas_wanted`, and `gas_used` are transaction-level fields for the transaction containing the call; they are not message-level execution results. The list intentionally excludes raw transactions, payload summaries, arguments, events, error/log/info text, raw execution results, source, render output, storage, and balances.
