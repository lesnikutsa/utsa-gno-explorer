import io
import json
from contextlib import redirect_stdout
from dataclasses import asdict

import pytest

import scripts.probe_realm_rpc_metadata as probe
from indexer.rpc import RpcProbeResult
from scripts.inspect_rpc import RpcError

RAW_SOURCE_SECRET = "RAW_SOURCE_SECRET"
RAW_DOC_SECRET = "RAW_DOC_SECRET"
RAW_QPKG_SECRET = "RAW_QPKG_SECRET"
RAW_RENDER_SECRET = "RAW_RENDER_SECRET"
URL_CREDENTIAL_SECRET = "URL_CREDENTIAL_SECRET"
SECRET_URL = f"https://user:{URL_CREDENTIAL_SECRET}@example.test/rpc?token=TOP_SECRET"
RAW_MARKERS = ["user", URL_CREDENTIAL_SECRET, "TOP_SECRET", "example.test", "token"]


class FakeClient:
    def __init__(self, responses):
        self.responses = responses
        self.calls = []
        self.closed = False

    def abci_query(self, path, data, height=None):
        self.calls.append((path, data, height))
        value = self.responses.get((path, data))
        if isinstance(value, Exception):
            raise value
        if value is None:
            raise RpcError("missing")
        return value

    def close(self):
        self.closed = True


def rpc_probe(url, client, latest=11):
    return RpcProbeResult(
        url=url,
        healthy=True,
        selected=False,
        chain_id="dev",
        latest_height=latest,
        observed_lag=0,
        catching_up=False,
        client=client,
        status_payload={},
        response_seconds=0.1,
    )


def responses(path="gno.land/r/demo/users"):
    return {
        ("vm/qfile", path): "main.gno\nmain_test.gno\ngnomod.toml",
        ("vm/qfile", path + "/main.gno"): f'package users\nconst secret = "{RAW_SOURCE_SECRET}"\nimport "gno.land/p/demo/avl"\n',
        ("vm/qfuncs", path): '[{"FuncName":"Render","Params":[],"Results":[]}]',
        ("vm/qdoc", path): json.dumps({"package_path": path, "package_doc": RAW_DOC_SECRET, "funcs": [{"name": "Render", "doc": "safe"}], "values": [], "types": []}),
        ("vm/qpkg_json", path): json.dumps({"Name": "users", "Doc": RAW_QPKG_SECRET}),
        ("vm/qrender", path + ":"): f"<p>{RAW_RENDER_SECRET}</p>",
        ("vm/qstorage", path): "storage: 1, deposit: 2",
    }


def report_text(result):
    return json.dumps(asdict(result), sort_keys=True)


def test_realm_invokes_queries_and_sanitizes_summary_terminal_and_report(capsys):
    client = FakeClient(responses())
    result = probe.probe_path(client, "rpc.example", 10, "gno.land/r/demo/users", "realm")
    assert [query.query_name for query in result.queries] == ["qfile_listing", "qfile_source_sample", "qfuncs", "qdoc", "qpkg_json", "qrender", "qstorage"]
    assert ("vm/qrender", "gno.land/r/demo/users:", 10) in client.calls
    probe.print_results([result])
    terminal = capsys.readouterr().out
    serialized = report_text(result)
    for marker in [RAW_SOURCE_SECRET, RAW_DOC_SECRET, RAW_QPKG_SECRET, RAW_RENDER_SECRET]:
        assert marker not in terminal
        assert marker not in serialized
        for query in result.queries:
            assert marker not in json.dumps(query.summary, sort_keys=True)


def test_package_never_invokes_realm_queries():
    path = "gno.land/p/demo/avl"
    data = responses(path)
    data.pop(("vm/qrender", path + ":"))
    data.pop(("vm/qstorage", path))
    client = FakeClient(data)
    result = probe.probe_path(client, "rpc.example", 10, path, "package")
    assert ("vm/qrender", path + ":", 10) not in client.calls
    assert result.queries[-2].status == "not_applicable" and result.queries[-1].status == "not_applicable"


def test_one_query_failure_does_not_stop_others_and_overall_partial():
    data = responses()
    data[("vm/qfuncs", "gno.land/r/demo/users")] = RpcError("ABCI query returned an application error")
    client = FakeClient(data)
    result = probe.probe_path(client, "rpc.example", 10, "gno.land/r/demo/users", "realm")
    assert result.overall_status == "partial"
    assert any(query.query_name == "qfuncs" and query.status == "application_error" for query in result.queries)
    assert any(query.query_name == "qdoc" and query.status == "ok" for query in result.queries)


def test_overall_status_all_states():
    ok = probe.QueryProbeResult("qfile_listing", "ok", 1, 0.0, {})
    rpc = probe.QueryProbeResult("qfuncs", "rpc_error", 0, 0.0, {}, "rpc_error")
    malformed = probe.QueryProbeResult("qdoc", "malformed", 17, 0.0, {}, "malformed_json")
    skipped = probe.QueryProbeResult("qfile_source_sample", "skipped", 0, 0.0, {})
    assert probe.overall_status([ok, skipped]) == "ok"
    assert probe.overall_status([ok, rpc]) == "partial"
    assert probe.overall_status([rpc, skipped]) == "unavailable"
    assert probe.overall_status([ok, malformed]) == "malformed"


def test_safe_host_removes_credentials():
    assert probe.safe_host("https://user:pass@example.com/rpc?token=x") == "example.com"


@pytest.mark.parametrize(
    "message,code",
    [
        ("RPC request timed out for status", "rpc_timeout"),
        (f"RPC request failed for abci_query: {SECRET_URL}", "rpc_request_failed"),
        ("RPC response for status was not valid JSON", "rpc_invalid_json"),
        (f"RPC returned an error for status: {SECRET_URL}", "rpc_payload_error"),
        ("ABCI query returned an application error", "application_error"),
        ("Malformed ABCI response", "malformed_abci_response"),
        ("Malformed or oversized ABCI response data", "malformed_abci_data"),
        ("Malformed ABCI response data", "malformed_abci_data"),
        ("ABCI response exceeds size limit", "oversized"),
        ("ABCI response data is not UTF-8", "invalid_utf8"),
        (f"unknown {SECRET_URL}", "rpc_error"),
    ],
)
def test_rpc_error_static_classification_never_leaks_raw_text(message, code):
    safe = probe.rpc_error_code(RpcError(message))
    assert safe == code
    for marker in RAW_MARKERS:
        assert marker not in safe


def test_rpc_secret_absent_from_terminal_json_and_safe_code(capsys):
    data = responses()
    path = "gno.land/r/demo/accounts"
    data = responses(path)
    data[("vm/qfuncs", path)] = RpcError(f"RPC request failed for abci_query: {SECRET_URL}")
    client = FakeClient(data)
    result = probe.probe_path(client, "rpc.example", 10, path, "realm")
    probe.print_results([result])
    terminal = capsys.readouterr().out
    serialized = report_text(result)
    qfuncs = next(query for query in result.queries if query.query_name == "qfuncs")
    assert qfuncs.safe_error_code == "rpc_request_failed"
    for marker in RAW_MARKERS:
        assert marker not in terminal
        assert marker not in serialized
        assert marker not in qfuncs.safe_error_code


def test_parser_unknown_code_collapses_to_static_error():
    assert probe.parser_error_code(probe.MetadataParseError(f"{SECRET_URL}")) == "metadata_parse_error"


def test_response_byte_count_preserved_on_parser_failure_and_json_report(tmp_path):
    malformed = '{"bad": "123456"}'
    assert len(malformed.encode()) == 17
    data = responses()
    data[("vm/qfuncs", "gno.land/r/demo/users")] = malformed
    client = FakeClient(data)
    result = probe.probe_path(client, "rpc.example", 10, "gno.land/r/demo/users", "realm")
    qfuncs = next(query for query in result.queries if query.query_name == "qfuncs")
    assert qfuncs.status == "malformed"
    assert qfuncs.response_bytes == 17
    assert result.overall_status == "malformed"
    report = {"schema_version": 1, "generated_at": "now", "chain_id": "dev", "endpoints": [asdict(result)]}
    out = tmp_path / "report.json"
    probe.write_json_report(out, report)
    serialized = out.read_text()
    assert '"response_bytes": 17' in serialized
    assert malformed not in serialized


def test_main_default_first_rpc_all_rpc_latest_minus_one_and_closes(monkeypatch, capsys):
    c1 = FakeClient(responses())
    c2 = FakeClient(responses())
    probes = [rpc_probe("https://a.example", c1, latest=20), rpc_probe("https://b.example", c2, latest=30)]
    monkeypatch.setattr(probe, "load_config", lambda: type("C", (), {"rpc_urls": ["a", "b"], "chain_id": "dev", "max_height_lag": 10})())
    monkeypatch.setattr(probe, "probe_rpc_endpoints", lambda *args, **kwargs: probes)
    assert probe.main(["--realm-path", "gno.land/r/demo/users"]) == 0
    assert all(call[2] == 19 for call in c1.calls) and c2.calls == []
    assert c1.closed and c2.closed
    assert "https://" not in capsys.readouterr().out
    c1 = FakeClient(responses())
    c2 = FakeClient(responses())
    probes = [rpc_probe("https://a.example", c1, 20), rpc_probe("https://b.example", c2, 30)]
    monkeypatch.setattr(probe, "probe_rpc_endpoints", lambda *args, **kwargs: probes)
    assert probe.main(["--realm-path", "gno.land/r/demo/users", "--all-suitable-rpcs"]) == 0
    assert {call[2] for call in c1.calls} == {19} and {call[2] for call in c2.calls} == {29}


def test_json_report_atomic_and_no_raw(tmp_path):
    out = tmp_path / "report.json"
    report = {"schema_version": 1, "generated_at": "now", "chain_id": "dev", "endpoints": [{"summary": "safe"}]}
    probe.write_json_report(out, report)
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    assert json.loads(out.read_text()) == report
    link = tmp_path / "link.json"
    link.symlink_to(out)
    with pytest.raises(OSError):
        probe.write_json_report(link, report)


def configured_main(monkeypatch, path_status):
    data = responses()
    for query_name, value in path_status.items():
        rpc_path = {"qfile_listing": "vm/qfile", "qfuncs": "vm/qfuncs", "qdoc": "vm/qdoc"}[query_name]
        data[(rpc_path, "gno.land/r/demo/users")] = value
    client = FakeClient(data)
    probes = [rpc_probe("https://a.example", client, 20)]
    monkeypatch.setattr(probe, "load_config", lambda: type("C", (), {"rpc_urls": ["a"], "chain_id": "dev", "max_height_lag": 10})())
    monkeypatch.setattr(probe, "probe_rpc_endpoints", lambda *args, **kwargs: probes)


def test_exit_code_2_precedes_meaningful_success(monkeypatch):
    configured_main(monkeypatch, {"qfuncs": '{"bad": "12345"}'})
    assert probe.main(["--realm-path", "gno.land/r/demo/users"]) == 2


def test_exit_code_1_when_no_core_ok(monkeypatch):
    configured_main(monkeypatch, {
        "qfile_listing": RpcError("ABCI query returned an application error"),
        "qfuncs": RpcError("ABCI query returned an application error"),
        "qdoc": RpcError("ABCI query returned an application error"),
    })
    assert probe.main(["--realm-path", "gno.land/r/demo/users"]) == 1


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["--realm-path", "bad"],
        ["--realm-path", "gno.land/p/demo/avl"],
        ["--package-path", "gno.land/r/demo/users"],
        ["--timeout", "0", "--realm-path", "gno.land/r/demo/users"],
        ["--timeout", "61", "--realm-path", "gno.land/r/demo/users"],
        ["--timeout", "bad", "--realm-path", "gno.land/r/demo/users"],
        ["--unknown", "x", "--realm-path", "gno.land/r/demo/users"],
        ["--realm-path", "gno.land/r/demo/users", "--realm-path", "gno.land/r/demo/users"],
        sum((["--realm-path", f"gno.land/r/demo/path{i}"] for i in range(21)), []),
    ],
)
def test_invalid_cli_exits_one(args):
    with pytest.raises(SystemExit) as exc:
        probe.main(args)
    assert exc.value.code == 1


def test_help_retains_zero_exit():
    with pytest.raises(SystemExit) as exc:
        probe.main(["--help"])
    assert exc.value.code == 0


@pytest.mark.parametrize(
    "constructor,args",
    [
        (probe.QueryProbeResult, ("bad-name", "ok", 0, 0.0, {}, None)),
        (probe.QueryProbeResult, ("q", "unknown", 0, 0.0, {}, None)),
        (probe.QueryProbeResult, ("q", "ok", True, 0.0, {}, None)),
        (probe.QueryProbeResult, ("q", "ok", 0, float("inf"), {}, None)),
        (probe.QueryProbeResult, ("q", "ok", 0, 0.0, [], None)),
        (probe.QueryProbeResult, ("q", "ok", 0, 0.0, {}, "rpc_error")),
        (probe.QueryProbeResult, ("q", "rpc_error", 0, 0.0, {}, None)),
    ],
)
def test_query_result_model_rejects_invalid(constructor, args):
    with pytest.raises(ValueError):
        constructor(*args)


def test_path_result_model_rejects_invalid():
    query = probe.QueryProbeResult("q", "ok", 0, 0.0, {})
    with pytest.raises(ValueError):
        probe.PathProbeResult("gno.land/p/demo/avl", "realm", "rpc.example", 1, [query], "ok")
    with pytest.raises(ValueError):
        probe.PathProbeResult("gno.land/r/demo/users", "realm", "user:pass@example", 1, [query], "ok")
    with pytest.raises(ValueError):
        probe.PathProbeResult("gno.land/r/demo/users", "realm", "rpc.example", 0, [query], "ok")
    with pytest.raises(ValueError):
        probe.PathProbeResult("gno.land/r/demo/users", "realm", "rpc.example", 1, [], "ok")
    with pytest.raises(ValueError):
        probe.PathProbeResult("gno.land/r/demo/users", "realm", "rpc.example", 1, [query, query], "ok")
    with pytest.raises(ValueError):
        probe.PathProbeResult("gno.land/r/demo/users", "realm", "rpc.example", 1, [query], "bad")
