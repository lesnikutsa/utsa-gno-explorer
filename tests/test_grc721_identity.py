from api.grc721_identity import (GRC721Identity, classify_grc721,
                                 extract_grc721_identity, inspect_grc721_candidate)
from api.token_identity import MAX_TOKEN_SOURCE_BYTES, MAX_TOKEN_SOURCE_FILES


def source(body, *, filename="main.gno"):
    return [{"filename": filename, "file_kind": "gno_source", "content": body}]


CANONICAL = '''
import "gno.land/p/demo/tokens/grc721"
var collection = grc721.NewBasicNFT(0, cur, "FooNFT", "FNFT")
'''


def test_official_import_and_canonical_identity_are_verified_without_token_count():
    assert inspect_grc721_candidate(source(CANONICAL)).status == "candidate"
    result = classify_grc721(source(CANONICAL), qfunc_names={"BalanceOf", "OwnerOf", "TransferFrom"})
    assert result.status == "verified" and result.identity == GRC721Identity("FooNFT", "FNFT")


def test_alias_is_supported_but_unrelated_import_and_import_only_fail_closed():
    aliased = CANONICAL.replace('import "', 'import nft "').replace("grc721.New", "nft.New")
    assert extract_grc721_identity(source(aliased)).verified
    assert classify_grc721(source('import "gno.land/p/demo/other"')).reason == "official_import_missing"
    assert classify_grc721(source('import "gno.land/p/demo/tokens/grc721"')).reason == "constructor_missing"


def test_import_aliases_are_file_scoped_and_cross_file_confusion_fails_closed():
    files = source('import nft "gno.land/p/demo/tokens/grc721"', filename="imports.gno")
    files += source('var nft = someOtherObject\nvar x = nft.NewBasicNFT(0, cur, "Fake", "FAKE")',
                    filename="fake.gno")
    result = classify_grc721(files)
    assert result.status == "rejected" and result.reason == "constructor_missing"


def test_behavior_is_required_and_packages_are_never_collections():
    assert classify_grc721(source(CANONICAL), qfunc_names={"BalanceOf"}).reason == "canonical_functions_missing"
    assert classify_grc721(source(CANONICAL), path_kind="package").reason == "not_realm"


def test_ambiguous_dynamic_and_malformed_identities_fail_closed():
    duplicate = CANONICAL + '\nvar other = grc721.NewBasicNFT(owner, "Bar", "BAR")'
    assert classify_grc721(source(duplicate)).reason == "ambiguous_identity"
    assert classify_grc721(source(CANONICAL.replace('"FooNFT"', "collectionName"))).reason == "dynamic_or_malformed_identity"
    assert classify_grc721(source(CANONICAL + "\n/* unterminated")).status == "rejected"


def test_source_and_file_bounds_fail_closed():
    assert classify_grc721(source(CANONICAL) * (MAX_TOKEN_SOURCE_FILES + 1)).reason == "file_limit"
    oversized = CANONICAL + (" " * MAX_TOKEN_SOURCE_BYTES)
    assert classify_grc721(source(oversized)).reason == "source_limit"
