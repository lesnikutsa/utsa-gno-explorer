# Account API

`GET /api/accounts/{address}` returns current Gno account metadata and native bank balances. The API reads this state live from the first suitable RPC endpoint selected by the existing chain-ID, catching-up, height-lag, and configured-order checks. Account state is not persisted in PostgreSQL. `observed_height` is the height seen while probing the selected RPC; it does not claim a cryptographic binding between that height and the subsequent ABCI responses.

Balances are native `bank/balances` results. The Topaz `ugnot` denomination is displayed as `GNOT` with six decimals, while unknown denominations retain their raw denomination and amount. Realm token holdings are not included.

The nullable validator relation is an exact match of the requested account address against the persisted `valoper_profiles.operator_address`. It is not a signing-address lookup.

The response uses `found=false` when the RPC confirms the normal missing-account representation (a null auth account and empty bank balance). Invalid Bech32 account addresses return HTTP 422. Missing fresh RPC data, inconsistent RPC responses, and unavailable or inconsistent validator profile data return HTTP 503 with a normalized detail message.

The API process environment must provide `DATABASE_URL` and should provide an ordered comma-separated `GNO_RPC_URLS` list. `GNO_RPC_URL` is a legacy fallback only when `GNO_RPC_URLS` is absent. `GNO_CHAIN_ID` identifies the expected chain, `RPC_MAX_HEIGHT_LAG` controls the non-negative freshness tolerance, and `API_ACCOUNT_RPC_TIMEOUT_SECONDS` controls account RPC calls from 1 through 30 seconds (default 10).
