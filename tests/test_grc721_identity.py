from api.grc721_identity import (GRC721Identity, classify_grc721,
                                 extract_grc721_identity, inspect_grc721_candidate)
from api.token_identity import MAX_TOKEN_SOURCE_BYTES, MAX_TOKEN_SOURCE_FILES


def source(body, *, filename="main.gno"):
    return [{"filename": filename, "file_kind": "gno_source", "content": body}]


def collection(import_path="gno.land/p/demo/tokens/grc721", constructor=None, alias="grc721"):
    constructor = constructor or f'{alias}.NewBasicNFT(0, cur, "FooNFT", "FNFT")'
    import_alias = "" if alias == import_path.rsplit("/", 1)[-1] else f"{alias} "
    return f'''import {import_alias}"{import_path}"
var collection = {constructor}
func OwnerOf(id int) {{}}
func TokenURI(id int) {{}}
'''


CANONICAL = collection()


def test_demo_and_arbitrary_implementation_paths_verify():
    assert inspect_grc721_candidate(source(CANONICAL)).status == "candidate"
    assert classify_grc721(source(CANONICAL)).identity == GRC721Identity("FooNFT", "FNFT")
    vendored = collection("gno.land/p/gnoswap/deps/tokens/grc721")
    assert classify_grc721(source(vendored)).status == "verified"
    v2 = collection("gno.land/p/publisher/grc721v2", alias="nft")
    assert classify_grc721(source(v2)).status == "verified"


def test_path_component_matching_rejects_substrings_and_dot_imports():
    for path in ("gno.land/p/x/my_grc721_helper", "gno.land/p/x/grc721market", "gno.land/p/x/fakegrc721adapter"):
        assert classify_grc721(source(collection(path))).reason == "implementation_import_missing"
    dotted = CANONICAL.replace('import "', 'import . "')
    assert classify_grc721(source(dotted)).reason == "implementation_import_missing"


def test_alias_and_real_four_argument_constructor_are_supported():
    aliased = collection("gno.land/p/vendor/grc721", alias="nft")
    assert extract_grc721_identity(source(aliased)) == GRC721Identity("FooNFT", "FNFT")


def test_import_aliases_are_file_scoped_and_cross_file_confusion_fails_closed():
    files = source('import nft "gno.land/p/vendor/grc721"', filename="imports.gno")
    files += source('var nft = someOtherObject\nvar x = nft.NewBasicNFT(0, cur, "Fake", "FAKE")\nfunc OwnerOf(){}\nfunc Mint(){}', filename="fake.gno")
    assert classify_grc721(files).reason == "constructor_missing"


def test_metadata_constructor_resolves_unique_cross_file_static_bindings():
    main = '''import nft "gno.land/p/vendor/grc721v2"
var nftCollection = nft.NewNFTWithMetadata(0, cur, CollectionName, CollectionSymbol)
func OwnerOf(id int) {}
func TokenMetadata(id int) {}
func Mint() {}
'''
    bindings = 'const CollectionName = "Metadata Art"\nconst CollectionSymbol = "MART"\n'
    result = classify_grc721(source(main) + source(bindings, filename="identity.gno"))
    assert result.status == "verified" and result.identity == GRC721Identity("Metadata Art", "MART")
    literal = collection(constructor='grc721.NewNFTWithMetadata(0, cur, "Literal Art", "LART")')
    assert classify_grc721(source(literal)).identity == GRC721Identity("Literal Art", "LART")


def test_grouped_const_identity_and_alias_import_verify():
    fixture = '''import nft "gno.land/p/vendor/grc721v2"
const (
    CollectionName = "Gems"
    CollectionSymbol = "GEMS"
)
var collection = nft.NewNFTWithMetadata(0, cur, CollectionName, CollectionSymbol)
func OwnerOf() {}
func TokenURI() {}
'''
    assert classify_grc721(source(fixture)).identity == GRC721Identity("Gems", "GEMS")


def test_dynamic_and_conflicting_static_bindings_fail_closed():
    main = collection(constructor="grc721.NewNFTWithMetadata(0, cur, CollectionName, CollectionSymbol)")
    dynamic = 'const CollectionName = getName()\nconst CollectionSymbol = "DYN"'
    assert classify_grc721(source(main) + source(dynamic, filename="identity.gno")).reason == "dynamic_or_malformed_identity"
    conflicting = 'const CollectionName = "A"\nconst CollectionName = "B"\nconst CollectionSymbol = "AB"'
    assert classify_grc721(source(main) + source(conflicting, filename="identity.gno")).reason == "dynamic_or_malformed_identity"
    grouped_conflict = '''const (
CollectionName = "A"
CollectionName = "B"
CollectionSymbol = getSymbol()
)'''
    assert classify_grc721(source(main) + source(grouped_conflict, filename="grouped.gno")).reason == "dynamic_or_malformed_identity"


def test_mutable_var_identity_is_never_statically_verified():
    mutable = 'var CollectionName = "Mutable"\nvar CollectionSymbol = "MUT"'
    main = collection(constructor="grc721.NewNFTWithMetadata(0, cur, CollectionName, CollectionSymbol)")
    assert classify_grc721(source(main) + source(mutable, filename="mutable.gno")).reason == "dynamic_or_malformed_identity"
    self_contained = mutable + '''
func Name() string { return CollectionName }
func Symbol() string { return CollectionSymbol }
func OwnerOf() {}
func TokenURI() {}
func TransferFrom() {}
func BalanceOf() {}
func Mint() {}
'''
    assert classify_grc721(source(self_contained)).status == "rejected"


def test_self_contained_collection_resolves_grouped_constants():
    fixture = '''const (
    CollectionName = "GnoBuilders Badges"
    CollectionSymbol = "GNOBADGE"
)
func Name() string { return CollectionName }
func Symbol() string { return CollectionSymbol }
func OwnerOf() {}
func TokenURI() {}
func TransferFrom() {}
func TotalSupply() {}
func BalanceOf() {}
func Approve() {}
'''
    result = classify_grc721(source(fixture))
    assert result.status == "verified" and result.reason == "self_contained_collection"
    assert result.identity == GRC721Identity("GnoBuilders Badges", "GNOBADGE")


def test_self_contained_direct_literal_identity_verifies():
    fixture = '''func Name() string { return "Demo NFT" }
func Symbol() string { return "DEMO" }
func OwnerOf() {}
func TokenURI() {}
func TransferFrom() {}
func BalanceOf() {}
func Mint() {}
'''
    assert classify_grc721(source(fixture)).identity == GRC721Identity("Demo NFT", "DEMO")


def test_self_contained_forwarder_and_incomplete_collection_fail_closed():
    adapter = '''func Name() string { return target.Name() }
func Symbol() string { return target.Symbol() }
func OwnerOf() { target.OwnerOf() }
func TokenURI() { target.TokenURI() }
func TransferFrom() { target.TransferFrom() }
func BalanceOf() { target.BalanceOf() }
func Approve() { target.Approve() }
'''
    assert classify_grc721(source(adapter)).status == "rejected"
    incomplete = '''const collectionName = "Broken"
func Name() string { return collectionName }
func Symbol() string { return "ERR" }
func OwnerOf() {}
func TokenURI() {}
func BalanceOf() {}
'''
    assert classify_grc721(source(incomplete)).status == "rejected"


def test_gnoswap_real_world_source_shape_verifies():
    fixture = '''import "gno.land/p/gnoswap/deps/tokens/grc721"
nft = grc721.NewBasicNFT(
    0,
    cur,
    "GNOSWAP NFT",
    "GNFT",
)
func TokenURI(id int) {}
func OwnerOf(id int) {}
func SafeTransferFrom() {}
func TransferFrom() {}
func Approve() {}
func GetApproved() {}
func Mint() {}
func Burn() {}
func Exists() {}
'''
    result = classify_grc721(source(fixture))
    assert result.status == "verified" and result.identity == GRC721Identity("GNOSWAP NFT", "GNFT")


def test_constructor_requires_ownership_and_an_additional_collection_signal():
    no_owner = CANONICAL.replace("func OwnerOf(id int) {}", "func Helper() {}")
    assert classify_grc721(source(no_owner)).reason == "collection_behavior_missing"
    owner_only = CANONICAL.replace("func TokenURI(id int) {}", "func Helper() {}")
    assert classify_grc721(source(owner_only)).reason == "collection_behavior_missing"


def test_marketplace_adapter_consumer_import_only_and_package_are_rejected():
    marketplace = 'func RegisterCollection(path string) {}\nfunc Trade() {} // grc721 marketplace'
    assert classify_grc721(source(marketplace)).reason == "implementation_import_missing"
    adapter = '''import "gno.land/p/vendor/grc721"
func OwnerOf() { target.OwnerOf() }
func TransferFrom() { target.TransferFrom() }
'''
    assert classify_grc721(source(adapter)).reason == "constructor_missing"
    consumer = '''import "gno.land/p/vendor/grc721v2"
var id grc721v2.TokenID
func OwnerOf() {}
func TokenURI() {}
'''
    assert classify_grc721(source(consumer)).reason == "constructor_missing"
    assert classify_grc721(source('import "gno.land/p/vendor/grc721"')).reason == "collection_behavior_missing"
    assert classify_grc721(source(CANONICAL), path_kind="package").reason == "not_realm"


def test_unqualified_ambiguous_malformed_and_bounds_fail_closed():
    unqualified = CANONICAL.replace("grc721.NewBasicNFT", "NewBasicNFT")
    assert classify_grc721(source(unqualified)).reason == "constructor_missing"
    duplicate = CANONICAL + '\nvar other = grc721.NewBasicNFT(0, cur, "Bar", "BAR")'
    assert classify_grc721(source(duplicate)).reason == "ambiguous_identity"
    assert classify_grc721(source(CANONICAL + "\n/* unterminated")).status == "rejected"
    assert classify_grc721(source(CANONICAL) * (MAX_TOKEN_SOURCE_FILES + 1)).reason == "file_limit"
    assert classify_grc721(source(CANONICAL + (" " * MAX_TOKEN_SOURCE_BYTES))).reason == "source_limit"
