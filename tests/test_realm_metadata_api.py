from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch
import unittest

from fastapi import HTTPException

import api.app as module


NOW = datetime(2026, 8, 11, tzinfo=timezone.utc)
SHA = "a" * 64


def metadata_row(path="gno.land/r/demo/app", kind="realm", status="complete"):
    return {"chain_id":"topaz-1", "path":path, "path_kind":kind, "observed_height":580214,
        "collected_at":NOW, "collection_status":status, "file_count":2, "gno_file_count":2,
        "test_file_count":1, "has_gnomod":False, "total_file_bytes":20, "total_file_lines":4,
        "dependency_count":2, "qdoc_status":"ok", "qdoc_summary":{"available":True,
        "package_doc_present":True, "documented_function_count":1, "value_count":0, "type_count":0,
        "byte_count":10}, "qpkg_json_status":"ok", "qpkg_json_summary":{"available":True,
        "top_level_type":"dict", "top_level_keys":[], "byte_count":2, "maximum_depth":1, "node_count":1},
        "qfuncs_status":"ok", "qfuncs_summary":{"function_count":1, "function_names":["Render"],
        "functions_with_params":0, "functions_with_results":1, "duplicate_names":False},
        "qrender_status":"ok", "qrender_byte_count":2, "qrender_line_count":1,
        "qrender_non_empty":True, "qstorage_status":"ok", "qstorage_bytes":"9007199254740993",
        "qstorage_deposit_ugnot":"9999999999999999999"}


class RealmMetadataApiTests(unittest.TestCase):
    def setUp(self):
        module.app.state.api_config = SimpleNamespace(chain_id="topaz-1")

    def test_bounded_metadata_response_and_numeric_strings(self):
        files = [{"filename":"a.gno", "file_kind":"gno_source", "byte_count":10, "line_count":2,
            "sha256":SHA, "package_declared":True, "import_candidate_count":2}]
        deps = [{"imported_path":f"gno.land/p/demo/{index:03}", "imported_kind":"package"} for index in range(201)]
        with patch.object(module.database, "fetch_realm_metadata", return_value={"metadata":metadata_row(), "files":files, "dependencies":deps}):
            response = module.get_realm_metadata(path="gno.land/r/demo/app")
        body = response.model_dump()
        self.assertEqual(body["summary"]["qstorage_bytes"], "9007199254740993")
        self.assertEqual(len(body["dependencies"]), 200)
        self.assertTrue(body["dependencies_truncated"])
        self.assertNotIn("content", body["files"][0])
        self.assertNotIn("qdoc_payload", body["summary"])
        self.assertNotIn("qrender_body", body["summary"])

    def test_partial_package_does_not_invent_functions(self):
        row = metadata_row("gno.land/p/demo/pkg", "package", "partial")
        row.update(qfuncs_status="application_error", qfuncs_summary=None, qrender_status="not_applicable",
                   qrender_byte_count=None, qrender_line_count=None, qrender_non_empty=None,
                   qstorage_status="not_applicable", qstorage_bytes=None, qstorage_deposit_ugnot=None)
        with patch.object(module.database, "fetch_realm_metadata", return_value={"metadata":row, "files":[], "dependencies":[]}):
            response = module.get_realm_metadata(path="gno.land/p/demo/pkg")
        self.assertEqual(response.collection_status, "partial")
        self.assertEqual(response.summary.qfuncs_status, "application_error")
        self.assertIsNone(response.summary.qfuncs_summary)

    def test_validation_and_absence_are_static(self):
        with self.assertRaises(HTTPException) as invalid:
            module.get_realm_metadata(path="not-a-path")
        self.assertEqual(invalid.exception.status_code, 422)
        with patch.object(module.database, "fetch_realm_metadata", return_value={"metadata":None}):
            with self.assertRaises(HTTPException) as missing:
                module.get_realm_metadata(path="gno.land/r/demo/missing")
        self.assertEqual((missing.exception.status_code, missing.exception.detail), (404, "Realm metadata not found"))

    def test_exact_file_and_missing_file(self):
        row = {"chain_id":"topaz-1", "path":"gno.land/r/demo/app", "filename":"main.gno",
            "file_kind":"gno_source", "byte_count":12, "line_count":1, "sha256":SHA, "content":"package demo"}
        with patch.object(module.database, "fetch_realm_metadata_file", return_value=row) as fetch:
            response = module.get_realm_metadata_file(path=row["path"], filename=row["filename"])
        self.assertEqual(response.content, "package demo")
        self.assertEqual(fetch.call_args.kwargs, {"chain_id":"topaz-1", "path":row["path"], "filename":"main.gno"})
        with patch.object(module.database, "fetch_realm_metadata_file", return_value=None):
            with self.assertRaises(HTTPException) as missing:
                module.get_realm_metadata_file(path=row["path"], filename="missing.gno")
        self.assertEqual(missing.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
