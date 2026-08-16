# Contract asset discovery

The unified `/api/assets` directory is derived only from persisted Realm catalog,
metadata, imports, qfunc metadata, and source files. It never executes Realm code.
Native GNOT is intentionally excluded and remains available from `/api/tokens/native`.
The compatibility `/api/tokens` endpoint retains its existing GRC20 contract.

## GRC20 contract

GRC20 verification is unchanged: a Realm must import
`gno.land/p/demo/tokens/grc20`, expose `TotalSupply`, `BalanceOf`, and `Transfer`,
and contain exactly one bounded, statically literal `NewToken` identity.

## GRC721 contract

A GRC721 candidate must be a Realm with successfully persisted qfunc metadata,
an import of `gno.land/p/demo/tokens/grc721`, and public `BalanceOf`, `OwnerOf`, and
`TransferFrom` functions. Verification additionally requires exactly one qualified
`NewBasicNFT` call through the imported package name or an explicit identifier
alias. Its final two arguments must be bounded, non-empty string literals providing
the collection name and symbol. Dynamic identities, missing behavior, import-only
use, malformed or oversized source, multiple constructors, packages, and dual
GRC20/GRC721 paths are rejected.

`TokenCount` is not required for discovery and is intentionally not queried in this
stage. The API returns `token_count: null`; no count is inferred from rendering or
partial history.

`inspect_grc721_candidate` and `classify_grc721` expose `candidate`, `verified`,
or `rejected` classifications and a stable reason to support tests and read-only diagnostics. Candidate status records
the official import signal; the complete catalog admits only verified results.
