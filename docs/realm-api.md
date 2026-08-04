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

The source records `chain_id`, `indexed_height`, `catalog_observed_height`, `activity_from_height`, and `activity_through_height`. Present activity should be described as **Indexed direct calls since #<activity_from_height>**. `indexed_height` can exceed `activity_through_height` while Realm activity backfill or catalog refresh has not reached the current indexer height. Source, aggregates, and members are read in one repeatable-read, read-only transaction.

Compact response example (metrics are illustrative):

```json
{"source":{"chain_id":"topaz-1","indexed_height":50,"catalog_observed_height":49,"activity_from_height":1,"activity_through_height":45},"scope":"all","items":[{"namespace_key":"gnoswap","application":{"display_name":"GnoSwap","category":"DeFi","description":null,"website":null,"metadata_source":"curated_registry"},"realm_count":1,"called_realm_count":1,"rpc_visible_realm_count":1,"direct_call_count":2,"successful_call_count":1,"failed_call_count":0,"unknown_result_call_count":1,"success_rate":1.0,"first_seen_height":2,"last_activity_height":40,"last_activity_tx_index":1,"last_activity_at":"2026-08-04T00:00:00Z","realms":[{"path":"gno.land/r/gnoswap/example","rpc_visible":true,"first_seen_height":2,"last_activity_height":40,"last_activity_tx_index":1,"last_activity_at":"2026-08-04T00:00:00Z","call_count":2,"successful_call_count":1,"failed_call_count":0,"unknown_result_call_count":1,"success_rate":1.0}],"realms_truncated":false}]}
```

The response's `source.activity_from_height` identifies the beginning of the indexed measurement range; the metric must not be interpreted as usage since genesis unless that range begins at genesis. Package imports are not measured, and no time-window ranking exists yet. The source also reports the chain, current indexed height, catalog observation height, and activity-through height used by the consistent read-only database snapshot.
