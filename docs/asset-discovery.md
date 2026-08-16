# Contract asset discovery

The unified `/api/assets` directory is derived only from persisted Realm catalog,
metadata, imports, and bounded source files. It never executes Realm code. Native
GNOT is excluded and remains available from `/api/tokens/native`. The compatibility
`/api/tokens` endpoint retains its existing GRC20 contract.

## GRC20 contract

GRC20 verification is unchanged: a Realm must import
`gno.land/p/demo/tokens/grc20`, expose `TotalSupply`, `BalanceOf`, and `Transfer`,
and contain exactly one bounded, statically literal `NewToken` identity.

## GRC721 contract

This stage supports two source-verified GRC721 collection routes: constructor-backed
collections and self-contained standard-shape collections. Packages are never
collections.

### Constructor-backed route

A candidate import path must have the normalized final path component `grc721` or
`grc721v2`. Substring matches and dot imports are not accepted. Verification
requires exactly one `NewBasicNFT` or `NewNFTWithMetadata` call qualified by an
implementation alias imported in the same source file.

The final constructor arguments resolve to the collection name and symbol. They may be direct string
literals or identifiers with exactly one simple package-scope `const` or `var`
string-literal binding across the Realm source set. Ordinary package-scope grouped
`const (...)` string declarations are supported. Expressions, missing bindings,
local or conflicting declarations, and ambiguous constructors fail closed.

Source must additionally declare `OwnerOf` and at least one of `TokenURI`,
`TokenMetadata`, `BalanceOf`, `GetApproved`, `Exists`, `TransferFrom`,
`SafeTransferFrom`, `Approve`, `Mint`, `Burn`, or `SetApprovalForAll`. Qfunc
metadata is not used as the GRC721 compliance gate because custom GRC721 types are
not represented reliably there.

### Self-contained route

A self-contained collection must declare package functions `Name`, `Symbol`,
`OwnerOf`, `TokenURI`, and `TransferFrom`, plus at least two independent state or
collection signals from `TokenCount`, `TotalSupply`, `BalanceOf`, `Mint`, `Burn`,
`Approve`, `GetApproved`, `SafeTransferFrom`, and `SetApprovalForAll`. `Name` and
`Symbol` must each contain one simple return of either a direct string literal or a
uniquely resolved static binding. Forwarded calls and expressions are not evaluated.

Candidate SQL admits bounded Realms through either a recognized implementation
import or the persisted qfunc form of the self-contained core API. Final acceptance
always uses bounded persisted source. Marketplaces, adapters, stakers, positions,
accessors, consumers, incomplete APIs, dynamic identities, and mixed independently
verified GRC20/GRC721 paths fail closed.

`TokenCount` is not queried in this stage. The API returns `token_count: null`; no
count is inferred from rendering, mint history, events, arrays, or partial history.

`inspect_grc721_candidate` and `classify_grc721` expose stable candidate, verified,
and rejected reasons for tests and read-only diagnostics. Public catalog results
contain verified collections only.
