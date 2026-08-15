"""Protocol unit tests for oracle-py (design D14, PR-10).

Exercises the newline-delimited JSON-RPC 2.0 surface of
``conformance/oracle_py/server.py`` against the normative spec at
``conformance/schema/oracle-protocol.md``: framing (ASCII-safe single
lines), the three methods, R5.4 error-mapping (library errors are
``ok: false`` DATA with messages stripped; harness bugs are JSON-RPC
``error`` objects), the Phase-1 scope rules, and the subprocess entry
point end-to-end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import IO, Any

import pytest

from conformance.oracle_py.server import (
    JSONRPC_INTERNAL_ERROR,
    JSONRPC_INVALID_PARAMS,
    JSONRPC_INVALID_REQUEST,
    JSONRPC_METHOD_NOT_FOUND,
    JSONRPC_PARSE_ERROR,
    PROTOCOL_VERSION,
    WIRE_OUT_OF_SCOPE_CODE,
    OracleServer,
)

_REPO_ROOT = Path(__file__).resolve().parents[2]
"""Repo root — cwd for the subprocess round-trip test."""


def _serve(server: OracleServer, method: str, params: Any = None) -> dict[str, Any]:
    """Round-trip one request line through the server.

    Args:
        server: The server under test.
        method: The JSON-RPC method name.
        params: Optional params object.

    Returns:
        The parsed response object.

    Raises:
        AssertionError: If the server returned no response line.
    """
    request: dict[str, Any] = {"jsonrpc": "2.0", "id": 1, "method": method}
    if params is not None:
        request["params"] = params
    line = server.handle_line(json.dumps(request, ensure_ascii=True))
    assert line is not None
    parsed = json.loads(line)
    assert isinstance(parsed, dict)
    return parsed


def _call(server: OracleServer, api: str, encoded_input: dict[str, Any]) -> Any:
    """Serve one successful ``oracle.call`` and return its result payload.

    Args:
        server: The server under test.
        api: The dotted registry api name.
        encoded_input: The codec-encoded kwargs.

    Returns:
        The ``result`` member.

    Raises:
        AssertionError: If the response is a JSON-RPC error.
    """
    response = _serve(server, "oracle.call", {"api": api, "input": encoded_input})
    assert "error" not in response, response
    return response["result"]


class TestInfoAndLifecycle:
    """``oracle.info`` / ``oracle.shutdown`` and request-shape handling."""

    def test_info_reports_identity_block(self) -> None:
        """``oracle.info`` returns the four §3 members with sane values.

        Raises:
            AssertionError: On a missing or malformed member.
        """
        import json
        from pathlib import Path

        result = _serve(OracleServer(), "oracle.info")["result"]
        assert result["language"] == "python"
        assert result["protocol_version"] == PROTOCOL_VERSION
        assert isinstance(result["library_version"], str)
        # The committed corpus manifest pins the extraction commit; info
        # must surface EXACTLY the manifest stamp (never `git rev-parse`,
        # design D3 stamp rule) — asserted against the manifest itself so
        # sanctioned re-extractions do not stale-pin this test.
        manifest_path = (
            Path(__file__).resolve().parents[1] / "vectors" / "manifest.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        assert result["source_commit"] == manifest["source_commit"]
        assert len(str(result["source_commit"])) == 40

    def test_shutdown_acknowledges_then_flags_exit(self) -> None:
        """``oracle.shutdown`` returns ``{ok: true}`` and sets the flag.

        Raises:
            AssertionError: If the flag or payload is wrong.
        """
        server = OracleServer()
        assert not server.shutdown_requested
        assert _serve(server, "oracle.shutdown")["result"] == {"ok": True}
        assert server.shutdown_requested

    def test_blank_lines_are_ignored(self) -> None:
        """Blank input lines produce no response (protocol §1).

        Raises:
            AssertionError: If a response was produced.
        """
        server = OracleServer()
        assert server.handle_line("") is None
        assert server.handle_line("   ") is None

    def test_parse_error_answers_id_null(self) -> None:
        """A non-JSON line yields ``-32700`` with ``id: null`` (§2).

        Raises:
            AssertionError: On the wrong code or id.
        """
        response = json.loads(OracleServer().handle_line("not json") or "")
        assert response["id"] is None
        assert response["error"]["code"] == JSONRPC_PARSE_ERROR

    @pytest.mark.parametrize(
        "line",
        [
            json.dumps({"jsonrpc": "1.0", "id": 1, "method": "oracle.info"}),
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": 7}),
            json.dumps([1, 2, 3]),
        ],
    )
    def test_malformed_requests_answer_invalid_request(self, line: str) -> None:
        """Bad ``jsonrpc``/``method``/shape yields ``-32600``.

        Args:
            line: The malformed request line.

        Raises:
            AssertionError: On the wrong error code.
        """
        response = json.loads(OracleServer().handle_line(line) or "")
        assert response["error"]["code"] == JSONRPC_INVALID_REQUEST

    def test_unknown_method_answers_method_not_found(self) -> None:
        """A method outside the three oracle methods yields ``-32601``.

        Raises:
            AssertionError: On the wrong error code.
        """
        response = _serve(OracleServer(), "oracle.nope")
        assert response["error"]["code"] == JSONRPC_METHOD_NOT_FOUND

    def test_responses_are_single_ascii_lines(self) -> None:
        """Framing is ASCII-safe and newline-free (D14 ``ensure_ascii``).

        A non-BMP output value must arrive ``\\uXXXX``-escaped so no fuzz
        strategy can kill the bridge via a stdout encode error.

        Raises:
            AssertionError: If the line contains non-ASCII or newlines.
        """
        server = OracleServer()
        request = {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "oracle.call",
            "params": {"api": "compat.python_str", "input": {"value": "\U0001f40d"}},
        }
        line = server.handle_line(json.dumps(request, ensure_ascii=True))
        assert line is not None
        assert "\n" not in line
        assert all(ord(char) < 128 for char in line)
        assert json.loads(line)["result"]["output"] == "\U0001f40d"


class TestOracleCall:
    """``oracle.call`` dispatch, scope, and R5.4 error-as-data mapping."""

    def test_builder_call_returns_output(self) -> None:
        """A compat builder call returns ``ok: true`` with the raw output.

        Raises:
            AssertionError: On the wrong payload.
        """
        result = _call(OracleServer(), "compat.zfill", {"value": "-1", "width": 3})
        assert result == {"ok": True, "output": "-01"}

    def test_validator_call_returns_structural_errors(self) -> None:
        """Validator output is ``[{path, code, severity}]`` — no messages.

        Raises:
            AssertionError: If messages leak or codes are wrong.
        """
        result = _call(
            OracleServer(),
            "validation.validate_time_args",
            {"from_date": "nope", "to_date": None, "last": 30},
        )
        assert result["ok"] is True
        assert result["output"] == [
            {"path": "from_date", "code": "V8_DATE_FORMAT", "severity": "error"}
        ]

    def test_facade_validation_error_is_data_with_messages_stripped(self) -> None:
        """A raised ``BookmarkValidationError`` becomes ``ok: false`` DATA.

        Per R5.4 the payload carries class + code + structural errors and
        NEVER ``message``/``suggestion``/``fix``.

        Raises:
            AssertionError: On a leaked advisory key or wrong structure.
        """
        result = _call(
            OracleServer(),
            "workspace.build_params",
            {"events": ["Login"], "from_date": "not-a-date", "to_date": "2025-01-31"},
        )
        assert result["ok"] is False
        error = result["error"]
        assert error["class"] == "BookmarkValidationError"
        assert error["code"] == "BOOKMARK_VALIDATION_ERROR"
        assert error["errors"] == [
            {"path": "from_date", "code": "V8_DATE_FORMAT", "severity": "error"}
        ]
        for stripped in ("message", "suggestion", "fix"):
            assert stripped not in error
            assert all(stripped not in item for item in error["errors"])

    def test_uncoded_raise_is_bare_class_data(self) -> None:
        """Uncoded builtin raises encode as ``{class}`` only (§4.1).

        The E2 coding pass (AD-B3) converted ``filter_to_selector``'s own
        ``ValueError`` guards to coded ``ParamValidationError``s, so this
        test now exercises the bare-class fallback with a raise that stays
        outside the coded hierarchy: a wrong-typed input triggers a plain
        ``AttributeError`` — comparable across bridges as the bare class
        name.

        Raises:
            AssertionError: On the wrong payload shape.
        """
        from conformance.record.codecs import encode_input_kwargs

        encoded = encode_input_kwargs({"f": "not-a-filter"})
        result = _call(OracleServer(), "user_builders.filter_to_selector", encoded)
        assert result == {"ok": False, "error": {"class": "AttributeError"}}

    def test_converted_guard_raise_is_coded_error_data(self) -> None:
        """Converted guard raises encode as class + code DATA (E2 / AD-B3).

        ``filter_to_selector`` on a cohort filter now raises the coded
        ``ParamValidationError`` (``ES6_CONTAINS_EXPECTS_STR`` — the cohort
        filter's list-of-dicts value fails the ``contains`` shape guard),
        which the oracle serializes through the recorder's structural
        encoder as class name + code.

        Raises:
            AssertionError: On the wrong payload shape.
        """
        from conformance.record.codecs import encode_input_kwargs
        from mixpanel_headless.types import Filter

        encoded = encode_input_kwargs({"f": Filter.in_cohort(7)})
        result = _call(OracleServer(), "user_builders.filter_to_selector", encoded)
        assert result == {
            "ok": False,
            "error": {
                "class": "ParamValidationError",
                "code": "ES6_CONTAINS_EXPECTS_STR",
            },
        }

    def test_wire_api_is_out_of_scope_skip_payload(self) -> None:
        """``wire_api`` registry entries answer the §4.2 skip payload.

        Raises:
            AssertionError: On the wrong payload.
        """
        result = _call(OracleServer(), "api_client.get_events", {})
        assert result == {
            "ok": False,
            "error": {"class": "Unsupported", "code": WIRE_OUT_OF_SCOPE_CODE},
        }

    def test_unknown_api_is_protocol_error(self) -> None:
        """An api in no registry entry fails fast with ``-32602``.

        Raises:
            AssertionError: On the wrong error code.
        """
        response = _serve(
            OracleServer(), "oracle.call", {"api": "nope.nope", "input": {}}
        )
        assert response["error"]["code"] == JSONRPC_INVALID_PARAMS

    def test_undecodable_input_is_protocol_error(self) -> None:
        """A ``$type`` tag outside the codec table yields ``-32602``.

        Raises:
            AssertionError: On the wrong error code.
        """
        response = _serve(
            OracleServer(),
            "oracle.call",
            {"api": "compat.python_str", "input": {"value": {"$type": "Nope"}}},
        )
        assert response["error"]["code"] == JSONRPC_INVALID_PARAMS

    def test_missing_api_is_protocol_error(self) -> None:
        """``params.api`` absent/empty yields ``-32602``.

        Raises:
            AssertionError: On the wrong error code.
        """
        response = _serve(OracleServer(), "oracle.call", {"input": {}})
        assert response["error"]["code"] == JSONRPC_INVALID_PARAMS

    def test_session_is_accepted_and_ignored(self) -> None:
        """The optional ``session`` member is protocol-legal in Phase 1.

        Raises:
            AssertionError: If a session makes a pure builder call fail.
        """
        response = _serve(
            OracleServer(),
            "oracle.call",
            {
                "api": "compat.zfill",
                "input": {"value": "5", "width": 3},
                "session": {"kind": "service_account", "username": "u"},
            },
        )
        assert response["result"] == {"ok": True, "output": "005"}

    def test_lone_surrogate_output_is_internal_error(self) -> None:
        """An output the D6 encoder rejects yields ``-32000``, not a crash.

        ``python_str`` over a ``$type: bytes`` value returns a Python
        ``bytes`` repr — legal; to force a canonicalization rejection we
        call ``python_str`` with a surrogate-bearing input, whose OUTPUT
        string carries the lone surrogate (the input itself arrives via a
        JSON escape, which Python decodes to the surrogate code point).

        Raises:
            AssertionError: On the wrong error code.
        """
        line = (
            '{"jsonrpc": "2.0", "id": 1, "method": "oracle.call", "params": '
            '{"api": "compat.python_str", "input": {"value": "\\ud800"}}}'
        )
        response = json.loads(OracleServer().handle_line(line) or "")
        assert response["error"]["code"] == JSONRPC_INTERNAL_ERROR

    def test_wirestub_call_replays_against_interactions(self) -> None:
        """``wirestub.*`` runs against a transport built from §4.3 params.

        Raises:
            AssertionError: On the wrong replayed payload.
        """
        interactions = [
            {
                "seq": 0,
                "request": {
                    "method": "GET",
                    "scheme_host": "https://wirestub.invalid",
                    "path": "/ping",
                },
                "response": {
                    "status": 200,
                    "headers": {"content-type": "application/json"},
                    "body": {"okay": True},
                },
            }
        ]
        response = _serve(
            OracleServer(),
            "oracle.call",
            {
                "api": "wirestub.request",
                "input": {"method": "GET", "path": "/ping"},
                "interactions": interactions,
            },
        )
        assert response["result"] == {
            "ok": True,
            "output": {"status": 200, "body": {"okay": True}},
        }


class TestSubprocessRoundTrip:
    """End-to-end: ``python -m conformance.oracle_py`` over real pipes."""

    def test_info_call_shutdown_session(self) -> None:
        """A full session round-trips and exits 0 (design D14 / §1).

        Raises:
            AssertionError: On any response mismatch or nonzero exit.
        """
        process = subprocess.Popen(  # noqa: S603 - test-owned argv
            [sys.executable, "-m", "conformance.oracle_py"],
            cwd=_REPO_ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            bufsize=1,
        )
        try:
            stdin: IO[str] = process.stdin  # type: ignore[assignment]
            stdout: IO[str] = process.stdout  # type: ignore[assignment]

            def request(payload: dict[str, Any]) -> dict[str, Any]:
                """Send one request line and parse the response line.

                Args:
                    payload: The request object.

                Returns:
                    The parsed response object.
                """
                stdin.write(json.dumps(payload, ensure_ascii=True) + "\n")
                stdin.flush()
                parsed = json.loads(stdout.readline())
                assert isinstance(parsed, dict)
                return parsed

            info = request({"jsonrpc": "2.0", "id": 1, "method": "oracle.info"})
            assert info["result"]["language"] == "python"
            call = request(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "oracle.call",
                    "params": {
                        "api": "compat.zfill",
                        "input": {"value": "-1", "width": 3},
                    },
                }
            )
            assert call["result"] == {"ok": True, "output": "-01"}
            done = request({"jsonrpc": "2.0", "id": 3, "method": "oracle.shutdown"})
            assert done["result"] == {"ok": True}
            assert process.wait(timeout=30) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)


class TestPhase2TypesSurface:
    """The Phase-2 ``types.*`` call surface (oracle-protocol.md §8 note)."""

    def test_variadic_target_binds_recorder_parameter_names(self) -> None:
        """`types.CohortDefinition.all_of` replays the `criteria` binding.

        The oracle must split VAR_POSITIONAL kwargs exactly like the
        corpus runner (`_bind_variadic`) — a plain ``target(**decoded)``
        call would land ``criteria`` in the wrong slot.

        Raises:
            AssertionError: On a protocol error or non-ok payload.
        """
        from conformance.record.codecs import encode_input_kwargs
        from mixpanel_headless.types import CohortCriteria

        criterion = CohortCriteria.did_event("login", at_least=1, within_days=30)
        payload = OracleServer().call_api(
            "types.CohortDefinition.all_of",
            encode_input_kwargs({"criteria": [criterion]}),
        )
        assert payload["ok"] is True, payload
        assert payload["output"]["_operator"] == "and"
        assert len(payload["output"]["_criteria"]) == 1

    def test_guard_failures_are_coded_error_data(self) -> None:
        """Constructor guards return ``{class, code}`` DATA (R5.4).

        Raises:
            AssertionError: On a missing class/code member.
        """
        payload = OracleServer().call_api(
            "types.Filter.in_the_last",
            {"property": "p", "quantity": 0, "date_unit": "day"},
        )
        assert payload == {
            "ok": False,
            "error": {
                "class": "ParamValidationError",
                "code": "FD1_QUANTITY_NOT_POSITIVE",
            },
        }


class TestCodecRoundtrip:
    """The protocol-1.1 ``codec.roundtrip`` method (oracle-protocol.md §8)."""

    def test_tagged_payload_round_trips_to_itself(self) -> None:
        """A valid rich payload encodes back to the identical value.

        Raises:
            AssertionError: On any member drift.
        """
        from conformance.record.codecs import encode_input_value
        from mixpanel_headless.types import Filter

        payload = encode_input_value(Filter.equals("plan", "pro"))
        result = _serve(OracleServer(), "codec.roundtrip", {"value": payload})["result"]
        assert result == {"ok": True, "output": payload}

    def test_plain_values_round_trip_through_identity(self) -> None:
        """Untagged scalars/containers pass through unchanged (§8).

        Raises:
            AssertionError: On value or float-kind drift.
        """
        result = _serve(
            OracleServer(),
            "codec.roundtrip",
            {"value": [18.0, 1.5, 18, True, None, "", "\U0001d4b3"]},
        )["result"]
        assert result["ok"] is True
        output = result["output"]
        assert output == [18.0, 1.5, 18, True, None, "", "\U0001d4b3"]
        assert isinstance(output[0], float)  # 18.0 stays a float
        assert isinstance(output[2], int)  # 18 stays an int

    def test_missing_value_is_invalid_params(self) -> None:
        """A params object without ``value`` is a ``-32602`` (§8).

        Raises:
            AssertionError: On the wrong error code.
        """
        response = _serve(OracleServer(), "codec.roundtrip", {})
        assert response["error"]["code"] == JSONRPC_INVALID_PARAMS

    def test_unknown_tag_is_invalid_params(self) -> None:
        """An undecodable tag is a ``-32602`` protocol error (§8).

        Raises:
            AssertionError: On the wrong error code.
        """
        response = _serve(
            OracleServer(),
            "codec.roundtrip",
            {"value": {"$type": "NoSuchTag", "x": 1}},
        )
        assert response["error"]["code"] == JSONRPC_INVALID_PARAMS

    def test_guard_failure_during_reconstruction_is_invalid_params(self) -> None:
        """A payload whose constructor guard fires is a ``-32602`` (§8).

        The harness only ships payloads it encoded from live instances,
        so a decode-time guard failure is a strategy/codec bug — never
        comparison data.

        Raises:
            AssertionError: On the wrong error code.
        """
        response = _serve(
            OracleServer(),
            "codec.roundtrip",
            {
                "value": {
                    "$type": "ReplaySummary",
                    "replay_id": "",
                    "distinct_id": None,
                    "project_id": 1,
                    "start_time": 1,
                    "retention_days": 7,
                    "_df_cache": None,
                }
            },
        )
        assert response["error"]["code"] == JSONRPC_INVALID_PARAMS
