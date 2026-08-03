# Realm catalog API

`GET /api/realms` is a read-only PostgreSQL endpoint. It never performs a live Realm or Gno RPC request. The list is compact indexed/aggregated data: one `realm_catalog` row per `(chain_id, path)`, not one row per call. `rpc_visible` is the most recent operator-triggered `vm/qpaths` snapshot, while call statistics cover only the configured local rebuild range and successfully decoded bounded transaction summaries.

Parameters are `limit` (1–100, default 25), `kind` (`all`, `realm`, or `package`), printable `q` (1–128 characters), and the paired `before_activity_height`/`before_path` keyset cursor. Results order by last activity descending (missing activity is `-1`) and path ascending. A missing snapshot returns `404 Realm catalog not found`.

A Realm may exist without locally known deployment metadata. Unknown execution results are counted separately and excluded from `success_rate`. Token verification and token classification do not exist yet. Source, documentation, exported functions, Render, storage, balances, and other details are deferred to future bounded on-demand server-side RPC queries.
