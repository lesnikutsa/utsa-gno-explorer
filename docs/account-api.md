# Account API

`GET /api/accounts/{address}` returns current Gno account metadata and native bank
balances. Account state is read live and is not persisted in PostgreSQL. The Account
service probes all configured RPC endpoints with bounded concurrent discovery, shares
probe work between concurrent callers, and caches successful probe collections for 15
seconds. Suitable candidates still pass chain-ID, catching-up, freshness, and height-lag
validation.

When suitable, Account prefers the canonical endpoint selected and persisted in
PostgreSQL by the continuous indexer. A latency advantage of a few milliseconds does not
move Account away from that canonical endpoint. If the canonical endpoint is unsuitable
or its auth query, bank query, parsing, consistency validation, URL sanitization, or
transport handling fails, Account immediately uses the next request-local suitable
fallback without re-probing. Auth and bank data are always queried from the same
candidate and are never mixed between endpoints. `source.rpc_url` is the sanitized URL
of the endpoint that actually returned the successful consistent response. Account is
read-only with respect to canonical RPC selection and never changes the indexer's
selection. `observed_height` is the finalized height used for the successful candidate's
queries; it does not claim a cryptographic binding between that height and the ABCI
responses.

Balances are native `bank/balances` results. The Gno `ugnot` denomination is displayed as `GNOT` with six decimals, while unknown denominations retain their raw denomination and amount. Realm token holdings are not included.

The nullable validator relation is an exact match of the requested account address against the persisted `valoper_profiles.operator_address`. It is not a signing-address lookup.

The response uses `found=false` when the RPC confirms the normal missing-account representation (a null auth account and empty bank balance). Invalid Bech32 account addresses return HTTP 422. Missing fresh RPC data, inconsistent RPC responses, and unavailable or inconsistent validator profile data return HTTP 503 with a normalized detail message.

In production, static shared network configuration (`GNO_RPC_URLS`, `GNO_CHAIN_ID`,
and `RPC_MAX_HEIGHT_LAG`) comes from `/etc/utsa-gno-explorer/rpc.env`. API database
credentials and API-only settings remain in `/etc/utsa-gno-explorer/api.env`;
`API_ACCOUNT_RPC_TIMEOUT_SECONDS` is API-specific and controls account RPC calls from
1 through 30 seconds (default 10).

## Local Account transaction history

`GET /api/accounts/{address}/transactions` reads PostgreSQL only; it does not perform a Gno RPC request. The read-only API starts from `transaction_participants`, joins the stored transaction and block, and returns `block_height`, `index`, uppercase `tx_hash`, `block_time`, `type`, `operation`, `direction`, `counterparty`, and `amount`. Direction is `outgoing`, `incoming`, or `self` according to the independently indexed sender and recipient roles. This describes decoded transaction content and Account involvement, not execution success.

Pages use descending `(block_height, tx_index)` keyset pagination. `limit` defaults to 20 and is bounded from 1 through 100. `before_height` and `before_tx_index` must be supplied together. Unsupported, undecoded, or address-free historical transactions can be absent, so this endpoint does not claim complete genesis coverage.
