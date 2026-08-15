"""Unit tests for the corpus runner (design D7, PR-6).

Covers the replay features the committed extracted corpus does not yet
exercise (they arrive with the PR-7 authored vectors): keyed
unordered-group serving, one-shot interaction consumption, extra/missing
traffic detection, ``transport_error`` re-raising with the recorded
message, ``body_stream`` chunk-boundary rebuild, callback-stub call-log
diffing, corpus loading rules, and the CLI's ``vector_failed`` vs
``runner_crashed`` distinction (design D9.3).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from conformance.runner.execute import run_vector
from conformance.runner.loading import CorpusLoadError, LoadedVector, load_vectors
from conformance.runner.transport import VectorReplayError, VectorTransport


def _interaction(
    method: str,
    path: str,
    response: dict[str, Any],
    *,
    params: dict[str, Any] | None = None,
    group: int | None = None,
) -> dict[str, Any]:
    """Build one recorded-interaction object for transport tests.

    Args:
        method: Request method.
        path: Request path.
        response: The recorded response object.
        params: Optional recorded query params.
        group: Optional ``unordered_group`` id.

    Returns:
        The interaction object.
    """
    request: dict[str, Any] = {
        "method": method,
        "scheme_host": "https://wirestub.invalid",
        "path": path,
    }
    if params:
        request["params"] = params
    interaction: dict[str, Any] = {"request": request, "response": response}
    if group is not None:
        interaction["unordered_group"] = group
    return interaction


def test_ordered_serving_is_positional_and_one_shot() -> None:
    """Ordered interactions serve positionally, each exactly once (D7).

    Raises:
        AssertionError: If responses arrive out of order or an exhausted
            transport keeps serving.
    """
    transport = VectorTransport(
        [
            _interaction("GET", "/a", {"status": 200, "body": {"n": 1}}),
            _interaction("GET", "/b", {"status": 200, "body": {"n": 2}}),
        ]
    )
    client = httpx.Client(transport=transport, base_url="https://wirestub.invalid")
    assert client.get("/a").json() == {"n": 1}
    assert client.get("/b").json() == {"n": 2}
    with pytest.raises(VectorReplayError):
        client.get("/c")
    assert transport.unconsumed_indexes() == []
    assert len(transport.extra_requests) == 1


def test_unordered_group_serves_by_key() -> None:
    """Group members serve by canonical key, not position (design D2/D7).

    Raises:
        AssertionError: If the i-th request receives the i-th recorded
            body instead of its key match.
    """
    transport = VectorTransport(
        [
            _interaction("GET", "/f/0", {"status": 200, "body": {"file": 0}}, group=1),
            _interaction("GET", "/f/1", {"status": 200, "body": {"file": 1}}, group=1),
        ]
    )
    client = httpx.Client(transport=transport, base_url="https://wirestub.invalid")
    # Reverse order: keyed serving must still hand each URL its own body.
    assert client.get("/f/1").json() == {"file": 1}
    assert client.get("/f/0").json() == {"file": 0}
    assert transport.unconsumed_indexes() == []


def test_transport_error_reraises_with_recorded_message() -> None:
    """``transport_error`` interactions raise the recorded class+message.

    Raises:
        AssertionError: If the class or message differs.
    """
    transport = VectorTransport(
        [
            _interaction(
                "GET",
                "/a",
                {"transport_error": "ConnectError", "message": "DNS lookup failed"},
            )
        ]
    )
    client = httpx.Client(transport=transport, base_url="https://wirestub.invalid")
    with pytest.raises(httpx.ConnectError, match="DNS lookup failed"):
        client.get("/a")


def test_body_stream_chunk_boundaries_preserved() -> None:
    """``body_stream`` responses rebuild the exact recorded chunks (D2).

    Raises:
        AssertionError: If chunks are merged, split, or reordered.
    """
    transport = VectorTransport(
        [
            _interaction(
                "GET",
                "/stream",
                {
                    "status": 200,
                    "body_stream": [
                        {"encoding": "utf8", "data": '{"a": 1}\n{"b'},
                        {"encoding": "utf8", "data": '": 2}\n'},
                    ],
                },
            )
        ]
    )
    client = httpx.Client(transport=transport, base_url="https://wirestub.invalid")
    with client.stream("GET", "/stream") as response:
        chunks = [chunk.decode("utf-8") for chunk in response.iter_raw()]
    assert chunks == ['{"a": 1}\n{"b', '": 2}\n']


def _wirestub_vector(vector_id: str, body: dict[str, Any]) -> LoadedVector:
    """Wrap a raw vector body for direct ``run_vector`` execution.

    Args:
        vector_id: The vector id.
        body: The vector object.

    Returns:
        The loaded-vector wrapper.
    """
    return LoadedVector(
        id=vector_id,
        kind=str(body["kind"]),
        body=body,
        bundle=Path("synthetic.jsonl"),
    )


def _stub_wire_body(**overrides: Any) -> dict[str, Any]:
    """Build a minimal passing ``wirestub.request`` wire vector body.

    Args:
        **overrides: Top-level keys to replace in the body.

    Returns:
        The vector body.
    """
    body: dict[str, Any] = {
        "schema_version": "1.0",
        "id": "compat/wirestub.request/synthetic",
        "kind": "wire",
        "origin": "authored",
        "capability": "compat",
        "call": {
            "api": "wirestub.request",
            "input": {"method": "GET", "path": "/ping", "params": {"q": "1"}},
        },
        "expect": {
            "interactions": [
                _interaction(
                    "GET",
                    "/ping",
                    {
                        "status": 200,
                        "headers": {"content-type": "application/json"},
                        "body": {"ok": True},
                    },
                    params={"q": "1"},
                )
            ],
            "result": {"status": 200, "body": {"ok": True}},
        },
    }
    body.update(overrides)
    return body


def test_run_vector_wirestub_green_path() -> None:
    """A correct wire vector replays green end-to-end (design D13 stub).

    Raises:
        AssertionError: If the synthetic vector fails.
    """
    outcome = run_vector(
        _wirestub_vector("compat/wirestub.request/synthetic", _stub_wire_body())
    )
    assert outcome.passed, outcome.reasons


def test_run_vector_detects_request_mismatch() -> None:
    """A wrong recorded param diffs as ``vector_failed`` (design D7).

    Raises:
        AssertionError: If the mismatch is not reported.
    """
    body = _stub_wire_body()
    body["expect"]["interactions"][0]["request"]["params"] = {"q": "2"}
    outcome = run_vector(_wirestub_vector("compat/wirestub.request/bad", body))
    assert not outcome.passed
    assert any("request mismatch" in reason for reason in outcome.reasons)


def test_run_vector_detects_result_mismatch() -> None:
    """A wrong ``expect.result`` diffs as ``vector_failed`` (design D7).

    Raises:
        AssertionError: If the mismatch is not reported.
    """
    body = _stub_wire_body()
    body["expect"]["result"] = {"status": 200, "body": {"ok": False}}
    outcome = run_vector(_wirestub_vector("compat/wirestub.request/badres", body))
    assert not outcome.passed
    assert any("result mismatch" in reason for reason in outcome.reasons)


def test_run_vector_builder_compat() -> None:
    """A builder vector replays through the registry target (design D7).

    Raises:
        AssertionError: If the compat vector fails.
    """
    body = {
        "schema_version": "1.0",
        "id": "compat/compat.zfill/synthetic",
        "kind": "builder",
        "origin": "authored",
        "capability": "compat",
        "call": {"api": "compat.zfill", "input": {"value": "-1", "width": 3}},
        "expect": {"output": "-01"},
    }
    outcome = run_vector(_wirestub_vector("compat/compat.zfill/synthetic", body))
    assert outcome.passed, outcome.reasons


def _guard_error_body(
    api: str, input_kwargs: dict[str, Any], code: str
) -> dict[str, Any]:
    """Build a coded-guard ``error_only`` builder vector body (design §5).

    Args:
        api: The registered guard-entry api (``types.<Class>[.<method>]``).
        input_kwargs: The violating ``call.input`` kwargs.
        code: The expected registry code.

    Returns:
        The vector body.
    """
    return {
        "schema_version": "1.0",
        "id": f"validation/{api.lower()}/synthetic",
        "kind": "builder",
        "origin": "authored",
        "capability": "validation",
        "call": {"api": api, "input": input_kwargs},
        "expect": {"error": {"class": "ParamValidationError", "code": code}},
    }


def test_run_vector_error_only_constructor_guard() -> None:
    """A constructor-target guard vector replays by calling the class.

    ``types.TimeComparison`` registers ``TimeComparison.__init__`` under
    the bare class api name; replay must construct the class with the
    decoded kwargs and diff the coded raise (coding-pass design §5).

    Raises:
        AssertionError: If the guard vector fails to replay.
    """
    body = _guard_error_body(
        "types.TimeComparison", {"type": "bogus"}, "TC0_INVALID_TYPE"
    )
    outcome = run_vector(_wirestub_vector(str(body["id"]), body))
    assert outcome.passed, outcome.reasons


def test_run_vector_error_only_classmethod_guard() -> None:
    """A classmethod-target guard vector replays via the bound classmethod.

    Raises:
        AssertionError: If the guard vector fails to replay.
    """
    body = _guard_error_body(
        "types.Filter.in_the_last",
        {"property": "plan", "quantity": 0, "date_unit": "day"},
        "FD1_QUANTITY_NOT_POSITIVE",
    )
    outcome = run_vector(_wirestub_vector(str(body["id"]), body))
    assert outcome.passed, outcome.reasons


def test_run_vector_error_only_var_positional_guard() -> None:
    """A ``*args`` guard input replays positionally, not as a keyword.

    ``Filter.list_contains(*item_filters, **equals)`` records its
    VAR_POSITIONAL parameter under ``input.item_filters``; replay must
    splat it positionally (with preceding parameters passed positionally
    too) or the guard input lands in ``**equals`` and the LC3 mixed-args
    raise never fires.

    Raises:
        AssertionError: If the guard vector fails to replay.
    """
    inner_filter = {
        "$type": "Filter",
        "_property": "Brand",
        "_operator": "equals",
        "_value": ["nike"],
        "_property_type": "string",
        "_resource_type": "events",
        "_date_unit": None,
        "_list_item_filters": None,
        "_list_item_quantifier": None,
    }
    body = _guard_error_body(
        "types.Filter.list_contains",
        {"property": "cart", "item_filters": [inner_filter], "Category": "hats"},
        "LC3_MIXED_ARGS",
    )
    outcome = run_vector(_wirestub_vector(str(body["id"]), body))
    assert outcome.passed, outcome.reasons


def test_run_vector_error_only_wrong_code_diffs_red() -> None:
    """A guard vector with the wrong expected code fails the diff.

    Raises:
        AssertionError: If the wrong code is not detected.
    """
    body = _guard_error_body(
        "types.TimeComparison", {"type": "bogus"}, "TC1_REQUIRES_UNIT"
    )
    outcome = run_vector(_wirestub_vector(str(body["id"]), body))
    assert not outcome.passed
    assert not any("infrastructure" in reason for reason in outcome.reasons)


def test_run_vector_error_only_success_is_clean_failure() -> None:
    """A guard vector whose input no longer raises fails cleanly.

    A sabotaged library that stops raising must produce an ordinary
    "expected error" diff — never a replay-infrastructure crash (which
    the R9 smoke flag would quarantine).

    Raises:
        AssertionError: If the missing raise crashes instead of diffing.
    """
    body = _guard_error_body(
        "types.TimeComparison",
        {"type": "relative", "unit": "month"},
        "TC0_INVALID_TYPE",
    )
    outcome = run_vector(_wirestub_vector(str(body["id"]), body))
    assert not outcome.passed
    assert any("expected error" in reason for reason in outcome.reasons)
    assert not any("infrastructure" in reason for reason in outcome.reasons)


def test_run_vector_diffs_callback_calls() -> None:
    """Callback stub logs diff against ``expect.callback_calls`` (D4.4).

    Uses ``region_probe.probe_region``: the replay factory's call log must
    match the recorded ``client_factory`` log.

    Raises:
        AssertionError: If a wrong recorded log passes.
    """
    interaction = _interaction(
        "GET",
        "/api/app/me",
        {"status": 200, "body": {"results": {}}},
    )
    interaction["request"]["scheme_host"] = "https://mixpanel.com"
    body: dict[str, Any] = {
        "schema_version": "1.0",
        "id": "auth/region_probe.probe_region/synthetic",
        "kind": "wire",
        "origin": "authored",
        "capability": "auth",
        "call": {
            "api": "region_probe.probe_region",
            "input": {
                "client_factory": {"$type": "callback", "name": "client_factory"},
                "headers": {"Authorization": "Basic xxx"},
            },
        },
        "expect": {
            "interactions": [interaction],
            "result": {"attempts": [["us", 200]], "region": "us"},
            "callback_calls": {"client_factory": [["us"]]},
        },
    }
    outcome = run_vector(
        _wirestub_vector("auth/region_probe.probe_region/synthetic", body)
    )
    assert outcome.passed, outcome.reasons
    body["expect"]["callback_calls"] = {"client_factory": [["eu"]]}
    outcome = run_vector(_wirestub_vector("auth/region_probe.probe_region/bad", body))
    assert not outcome.passed
    assert any("call-log mismatch" in reason for reason in outcome.reasons)


def _write_bundle(path: Path, vectors: list[dict[str, Any]]) -> None:
    """Write a JSONL bundle with a ``$bundle`` header line.

    Args:
        path: Bundle file path (parents created).
        vectors: Vector objects, one per line.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps({"$bundle": {"count": len(vectors), "source_file": "x"}}),
    ] + [json.dumps(vector) for vector in vectors]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_vectors_skips_headers_and_filters(tmp_path: Path) -> None:
    """Loading skips ``$bundle`` lines and applies the id glob (design D7).

    Raises:
        AssertionError: If headers load as vectors or the filter leaks.
    """
    _write_bundle(
        tmp_path / "compat" / "a.jsonl",
        [
            _stub_wire_body(id="compat/wirestub.request/one"),
            _stub_wire_body(id="segmentation/wirestub.request/two"),
        ],
    )
    every = load_vectors(tmp_path)
    assert [vector.id for vector in every] == [
        "compat/wirestub.request/one",
        "segmentation/wirestub.request/two",
    ]
    filtered = load_vectors(tmp_path, "compat/*")
    assert [vector.id for vector in filtered] == ["compat/wirestub.request/one"]


def test_load_vectors_rejects_duplicate_ids(tmp_path: Path) -> None:
    """Duplicate ids across bundles are a hard load error (design D3).

    Raises:
        AssertionError: If the duplicate loads silently.
    """
    _write_bundle(
        tmp_path / "a.jsonl", [_stub_wire_body(id="compat/wirestub.request/dup")]
    )
    _write_bundle(
        tmp_path / "b.jsonl", [_stub_wire_body(id="compat/wirestub.request/dup")]
    )
    with pytest.raises(CorpusLoadError, match="duplicate vector id"):
        load_vectors(tmp_path)


def test_cli_exit_codes_and_report(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The CLI distinguishes pass / vector_failed / runner_crashed (D9.3).

    Raises:
        AssertionError: If exit codes or report statuses are wrong.
    """
    from conformance.runner.__main__ import main

    good = tmp_path / "good"
    _write_bundle(
        good / "compat" / "a.jsonl",
        [_stub_wire_body(id="compat/wirestub.request/pass")],
    )
    assert main(["--vectors", str(good), "--report", "json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "ok"
    assert (report["total"], report["passed"], report["failed"]) == (1, 1, 0)

    bad_body = _stub_wire_body(id="compat/wirestub.request/fail")
    bad_body["expect"]["result"] = {"status": 200, "body": {"ok": False}}
    bad = tmp_path / "bad"
    _write_bundle(bad / "compat" / "a.jsonl", [bad_body])
    assert main(["--vectors", str(bad), "--report", "json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "vector_failed"
    assert report["failures"][0]["id"] == "compat/wirestub.request/fail"

    assert main(["--vectors", str(tmp_path / "missing"), "--report", "json"]) == 2
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "runner_crashed"
    assert "corpus load failed" in report["error"]
