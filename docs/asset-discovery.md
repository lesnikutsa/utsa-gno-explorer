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

This stage verifies only constructor-backed GRC721 collection Realms. A candidate
import path must have the normalized final path component `grc721` or `grc721v2`.
Substring matches, dot imports, Packages, self-contained implementations, and
imports without an owned collection constructor are not accepted.

Verification requires exactly one `NewBasicNFT` or `NewNFTWithMetadata` call
qualified by an implementation alias imported in the same source file. The final
arguments resolve to the collection name and symbol. They may be direct string
literals or identifiers with exactly one simple package-scope `const` or `var`
string-literal binding across the Realm source set. Expressions, missing bindings,
local or conflicting declarations, and ambiguous constructors fail closed.

Source must additionally declare `OwnerOf` and at least one of `TokenURI`,
`TokenMetadata`, `BalanceOf`, `GetApproved`, `Exists`, `TransferFrom`,
`SafeTransferFrom`, `Approve`, `Mint`, `Burn`, or `SetApprovalForAll`. Qfunc
metadata is not used as the GRC721 compliance gate because custom GRC721 types are
not represented reliably there.

Self-contained GRC721 implementations without a recognized imported constructor
remain deliberately unclassified. Marketplaces, adapters, accessors, and consumers
remain unclassified unless the same constructor and collection-behavior rule proves
that the Realm owns one distinct collection.

`TokenCount` is not queried in this stage. The API returns `token_count: null`; no
count is inferred from rendering, mint history, events, arrays, or partial history.

`inspect_grc721_candidate` and `classify_grc721` expose stable candidate, verified,
and rejected reasons for tests and read-only diagnostics. Public catalog results
contain verified collections only.
