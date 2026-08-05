import hashlib
import json

import pytest

from indexer.realm_metadata import *

RAW_SOURCE_SECRET = "RAW_SOURCE_SECRET"
RAW_DOC_SECRET = "RAW_DOC_SECRET"
RAW_QPKG_SECRET = "RAW_QPKG_SECRET"
RAW_RENDER_SECRET = "RAW_RENDER_SECRET"


def test_qfile_listing_valid_gnomod_tests_unknown_nested_and_trailing_newline():
    summary = parse_qfile_listing("gnomod.toml\nmain.gno\nmain_test.gno\nnested/dir/source.gno\nREADME.md\n")
    assert summary == {
        "file_count": 5,
        "gno_file_count": 3,
        "test_file_count": 1,
        "has_gnomod": True,
        "filenames": ["gnomod.toml", "main.gno", "main_test.gno", "nested/dir/source.gno", "README.md"],
    }


@pytest.mark.parametrize(
    "payload",
    [
        "",
        "a.gno\n\nb.gno",
        "a.gno\na.gno",
        "../x.gno",
        "./source.gno",
        "dir/./source.gno",
        "dir/../source.gno",
        "/x.gno",
        "C:/source.gno",
        "dir\\source.gno",
        "bad\x01.gno",
    ],
)
def test_qfile_listing_rejects_unsafe(payload):
    with pytest.raises(MetadataParseError):
        parse_qfile_listing(payload)


def test_qfile_listing_rejects_too_many_oversized_invalid_utf8():
    with pytest.raises(MetadataParseError):
        parse_qfile_listing("\n".join(f"{i}.gno" for i in range(257)))
    with pytest.raises(MetadataParseError):
        parse_qfile_listing(b"x" * (MAX_ABCI_RESPONSE_BYTES + 1))
    with pytest.raises(MetadataParseError):
        parse_qfile_listing(b"\xff")


def test_source_summary_counts_hash_import_forms_and_no_raw_source():
    src = f'''package demo // package comment
import "gno.land/p/demo/a"
import alias "gno.land/p/demo/b"
import _ "gno.land/p/demo/c"
import . "gno.land/p/demo/d"
import (
  alias2 "gno.land/p/demo/e"
  _ "gno.land/p/demo/f"
  "fmt"
)
const ordinary = "gno.land/p/not/an/import"
// import "gno.land/p/commented/out"
const secret = "{RAW_SOURCE_SECRET}"
'''
    summary = summarize_source_file("main.gno", src)
    assert summary["byte_count"] == len(src.encode())
    assert summary["line_count"] == 13
    assert summary["sha256"] == hashlib.sha256(src.encode()).hexdigest()
    assert summary["package_declared"] is True
    assert summary["import_candidate_count"] == 7
    assert summary["gno_land_imports"] == [
        "gno.land/p/demo/a",
        "gno.land/p/demo/b",
        "gno.land/p/demo/c",
        "gno.land/p/demo/d",
        "gno.land/p/demo/e",
        "gno.land/p/demo/f",
    ]
    assert RAW_SOURCE_SECRET not in json.dumps(summary)
    assert "gno.land/p/not/an/import" not in json.dumps(summary)
    assert "gno.land/p/commented/out" not in json.dumps(summary)


def test_source_summary_fails_closed():
    with pytest.raises(MetadataParseError):
        summarize_source_file("../main.gno", "package x")
    with pytest.raises(MetadataParseError):
        summarize_source_file("main.gno", b"\xff")


def test_qfuncs_valid_nulls_duplicates_no_raw():
    payload = json.dumps([
        {"FuncName": "A", "Params": None, "Results": None},
        {"FuncName": "A", "Params": [{}], "Results": [{}]},
    ])
    summary = parse_qfuncs(payload)
    assert summary["function_count"] == 2 and summary["duplicate_names"] is True
    assert summary["functions_with_params"] == 1 and summary["functions_with_results"] == 1
    assert payload not in json.dumps(summary)


@pytest.mark.parametrize("payload", ["{", "{}", json.dumps([{"FuncName": ""}]), json.dumps([{"FuncName": "A", "Params": {}}])])
def test_qfuncs_rejects_malformed(payload):
    with pytest.raises(MetadataParseError):
        parse_qfuncs(payload)


def test_qfuncs_rejects_too_many_and_bad_params():
    with pytest.raises(MetadataParseError):
        parse_qfuncs(json.dumps([{"FuncName": str(i)} for i in range(1001)]))
    with pytest.raises(MetadataParseError):
        parse_qfuncs(json.dumps([{"FuncName": "A", "Params": ["x"]}]))


def test_qdoc_official_shape_lower_case_and_no_doc_text():
    payload = json.dumps({
        "package_path": "gno.land/r/demo/users",
        "package_line": "package users",
        "package_doc": f"Package users {RAW_DOC_SECRET}",
        "values": [{"name": "users", "doc": "value docs", "type": "*avl.Tree"}],
        "funcs": [{"name": "GetUser", "doc": "GetUser returns ..."}, {}],
        "types": [],
    })
    summary = parse_qdoc(payload, "gno.land/r/demo/users")
    assert summary["package_doc_present"] is True
    assert summary["documented_function_count"] == 1
    assert summary["value_count"] == 1
    assert summary["type_count"] == 0
    assert RAW_DOC_SECRET not in json.dumps(summary)
    assert "GetUser returns" not in json.dumps(summary)


def test_qdoc_legacy_aliases_and_empty_collections_are_explicit():
    payload = json.dumps({"PackagePath": "gno.land/r/demo/users", "Doc": "legacy", "Funcs": [], "Values": [], "Types": []})
    summary = parse_qdoc(payload, "gno.land/r/demo/users")
    assert summary["package_doc_present"] is True
    assert summary["documented_function_count"] == 0


def test_qdoc_rejects_mismatch_and_bounds_and_invalid_doc_semantics():
    with pytest.raises(MetadataParseError):
        parse_qdoc(json.dumps({"package_path": "gno.land/r/x"}), "gno.land/r/y")
    with pytest.raises(MetadataParseError):
        parse_qdoc("{")
    value = {}
    cur = value
    for _ in range(MAX_JSON_DEPTH + 2):
        cur["x"] = {}
        cur = cur["x"]
    with pytest.raises(MetadataParseError):
        parse_qdoc(json.dumps(value))
    with pytest.raises(MetadataParseError):
        parse_qdoc(json.dumps({"funcs": [{}] * (MAX_QDOC_ITEMS + 1)}))
    with pytest.raises(MetadataParseError):
        parse_qdoc(json.dumps({"package_doc": 1}))
    with pytest.raises(MetadataParseError):
        parse_qdoc(json.dumps({"funcs": ["not-object"]}))


def test_qpkg_json_object_and_list_unknown_fields_no_raw():
    summary = parse_qpkg_json(json.dumps({"unknown": RAW_QPKG_SECRET}))
    assert summary["top_level_keys"] == ["unknown"]
    assert RAW_QPKG_SECRET not in json.dumps(summary)
    assert parse_qpkg_json('[{"x":1}]')["top_level_type"] == "list"


@pytest.mark.parametrize("payload", ["{", "1"])
def test_qpkg_json_rejects_invalid(payload):
    with pytest.raises(MetadataParseError):
        parse_qpkg_json(payload)


def test_qpkg_json_rejects_depth_and_nodes():
    value = {}
    cur = value
    for _ in range(MAX_JSON_DEPTH + 2):
        cur["x"] = {}
        cur = cur["x"]
    with pytest.raises(MetadataParseError):
        parse_qpkg_json(json.dumps(value))
    with pytest.raises(MetadataParseError):
        parse_qpkg_json(json.dumps([0] * (MAX_JSON_NODES + 1)))


def huge_json_integer_payload(wrapper):
    digits = getattr(__import__("sys"), "get_int_max_str_digits", lambda: 4300)() + 1
    return wrapper("1" * digits)


@pytest.mark.parametrize(
    "parser,payload",
    [
        (parse_qfuncs, huge_json_integer_payload(lambda value: f"[{{\"FuncName\":\"A\",\"n\":{value}}}]")),
        (parse_qdoc, huge_json_integer_payload(lambda value: f"{{\"package_path\":\"gno.land/r/demo/users\",\"n\":{value}}}")),
        (parse_qpkg_json, huge_json_integer_payload(lambda value: f"{{\"n\":{value}}}")),
    ],
)
def test_json_value_errors_normalize_to_malformed_json(parser, payload):
    with pytest.raises(MetadataParseError) as exc:
        parser(payload)
    assert exc.value.args == ("malformed_json",)


def test_json_parse_constant_error_is_preserved():
    with pytest.raises(MetadataParseError) as exc:
        parse_qpkg_json("NaN")
    assert exc.value.args == ("invalid_json_constant",)


def test_qrender_summary_empty_non_empty_no_body():
    assert summarize_qrender("")["non_empty"] is False
    summary = summarize_qrender(f"hello\n{RAW_RENDER_SECRET}")
    assert summary["byte_count"] == len(f"hello\n{RAW_RENDER_SECRET}".encode())
    assert summary["line_count"] == 2 and summary["non_empty"] is True
    assert summary["sha256"] == hashlib.sha256(f"hello\n{RAW_RENDER_SECRET}".encode()).hexdigest()
    assert RAW_RENDER_SECRET not in json.dumps(summary)


@pytest.mark.parametrize("payload,expected", [("storage: 1, deposit: 2", {"storage_bytes": 1, "deposit_ugnot": 2}), ("storage: 0, deposit: 0", {"storage_bytes": 0, "deposit_ugnot": 0})])
def test_qstorage_valid(payload, expected):
    assert parse_qstorage(payload) == expected


@pytest.mark.parametrize("payload", ["storage: -1, deposit: 2", "storage: 1.0, deposit: 2", "storage: 1, deposit: 2 trailing", "storage: x, deposit: 2", "storage: " + ("1" * 41) + ", deposit: 0"])
def test_qstorage_rejects(payload):
    with pytest.raises(MetadataParseError):
        parse_qstorage(payload)
