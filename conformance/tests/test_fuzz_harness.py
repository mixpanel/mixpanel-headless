"""Unit tests for the differential fuzz harness (design D14, PR-10).

Covers the comparison core (match / skip / divergence over canonical
forms), the per-target Hypothesis runner including the R10.9 edge-set
attachment and repro writing, and the strategy table's structural
invariants (all seven Phase-1 priority targets present, every edge call
registry-resolvable). Bridge processes are replaced by in-process
:class:`conformance.oracle_py.server.OracleServer` doubles — the real
subprocess path is exercised by the protocol suite and the self-parity
run.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from conformance.differential.fuzz_harness import (
    Divergence,
    OracleBridgeError,
    OracleProcess,
    compare_call,
    run_target,
)
from conformance.differential.strategies import (
    PHASE1_TARGETS,
    TARGETS_BY_NAME,
    FuzzTarget,
)
from conformance.oracle_py.server import OracleServer
from conformance.record.registry import (
    KIND_BUILDER,
    KIND_VALIDATOR,
    REGISTRY_BY_API,
)

_EXPECTED_TARGET_NAMES = (
    "filter_to_selector",
    "filters_to_selector",
    "build_segfilter_entry",
    "build_filter_entry",
    "validators_by_code",
    "normalize_on_expression",
    "pythoncompat",
)
"""The design D14 Phase-1 priority-target vocabulary, in design order."""


def _server_call(server: OracleServer) -> Any:
    """Wrap an in-process server as an ``OracleCall`` surface.

    Args:
        server: The server double.

    Returns:
        A ``(api, encoded_input) -> payload`` callable.
    """

    def call(api: str, encoded_input: Mapping[str, Any]) -> Mapping[str, Any]:
        """Delegate one probe to the in-process server.

        Args:
            api: The dotted registry api name.
            encoded_input: The codec-encoded kwargs.

        Returns:
            The call result payload.
        """
        return server.call_api(api, encoded_input)

    return call


def _rigged_call(mutate_api: str) -> Any:
    """Build a bridge double that corrupts one api's output.

    Args:
        mutate_api: The api whose ``ok: true`` output gets corrupted.

    Returns:
        An ``OracleCall`` surface backed by a real server, with the one
        api's output replaced by a sentinel.
    """
    server = OracleServer()

    def call(api: str, encoded_input: Mapping[str, Any]) -> Mapping[str, Any]:
        """Delegate, corrupting the targeted api's successful output.

        Args:
            api: The dotted registry api name.
            encoded_input: The codec-encoded kwargs.

        Returns:
            The (possibly corrupted) call result payload.
        """
        result = dict(server.call_api(api, encoded_input))
        if api == mutate_api and result.get("ok"):
            result["output"] = "CORRUPTED"
        return result

    return call


class TestCompareCall:
    """The canonical-comparison core."""

    def test_identical_servers_match(self) -> None:
        """Two fresh servers agree on a builder probe.

        Raises:
            AssertionError: If a self-comparison diverges.
        """
        outcome = compare_call(
            _server_call(OracleServer()),
            _server_call(OracleServer()),
            "compat.zfill",
            {"value": "-1", "width": 3},
        )
        assert outcome is None

    def test_error_outcomes_compare_structurally(self) -> None:
        """Both sides raising the same coded error is a match (R5.4).

        Raises:
            AssertionError: If equal error DATA is reported as divergence.
        """
        outcome = compare_call(
            _server_call(OracleServer()),
            _server_call(OracleServer()),
            "workspace.build_params",
            {"events": ["Login"], "from_date": "bad", "to_date": "2025-01-31"},
        )
        assert outcome is None

    def test_corrupted_output_diverges(self) -> None:
        """A mutated right-side output is detected as a divergence.

        Raises:
            AssertionError: If the corruption goes unnoticed.
        """
        outcome = compare_call(
            _server_call(OracleServer()),
            _rigged_call("compat.zfill"),
            "compat.zfill",
            {"value": "5", "width": 3},
        )
        assert isinstance(outcome, Divergence)
        assert outcome.api == "compat.zfill"
        assert outcome.right["output"] == "CORRUPTED"

    def test_ok_vs_error_diverges(self) -> None:
        """A return on one side and an error on the other diverges.

        Raises:
            AssertionError: If the ok/error axis is not compared.
        """
        server = OracleServer()

        def erroring(_api: str, _encoded: Mapping[str, Any]) -> Mapping[str, Any]:
            """Always answer a library-error payload.

            Args:
                _api: Ignored.
                _encoded: Ignored.

            Returns:
                A fixed ``ok: false`` payload.
            """
            return {"ok": False, "error": {"class": "ValueError"}}

        outcome = compare_call(
            _server_call(server), erroring, "compat.zfill", {"value": "5", "width": 3}
        )
        assert isinstance(outcome, Divergence)

    def test_skip_codes_never_diverge(self) -> None:
        """UNPORTED / WIRE_OUT_OF_SCOPE from either side counts as skip.

        This is how compat-only oracle-ts coexists with the full oracle-py
        surface (oracle-protocol.md §4.2).

        Raises:
            AssertionError: If a skip payload is treated as divergence.
        """

        def unported(_api: str, _encoded: Mapping[str, Any]) -> Mapping[str, Any]:
            """Answer the oracle-ts UNPORTED payload for every api.

            Args:
                _api: Ignored.
                _encoded: Ignored.

            Returns:
                The UNPORTED skip payload.
            """
            return {"ok": False, "error": {"class": "Unported", "code": "UNPORTED"}}

        outcome = compare_call(
            _server_call(OracleServer()),
            unported,
            "compat.zfill",
            {"value": "5", "width": 3},
        )
        assert outcome == "skip"

    def test_malformed_payload_is_bridge_error(self) -> None:
        """A payload without ``output``/``error`` shape crashes the harness.

        Crashes are never divergences (D9.3 discipline carried over).

        Raises:
            AssertionError: If no ``OracleBridgeError`` is raised.
        """

        def malformed(_api: str, _encoded: Mapping[str, Any]) -> Mapping[str, Any]:
            """Answer a shape the protocol forbids.

            Args:
                _api: Ignored.
                _encoded: Ignored.

            Returns:
                A malformed payload.
            """
            return {"ok": False, "error": "not-an-object"}

        with pytest.raises(OracleBridgeError):
            compare_call(
                _server_call(OracleServer()),
                malformed,
                "compat.zfill",
                {"value": "5", "width": 3},
            )


class TestRunTarget:
    """The per-target Hypothesis runner."""

    def test_self_parity_target_runs_clean(self, tmp_path: Path) -> None:
        """A small self-parity run passes with edge + generated counts.

        Args:
            tmp_path: Repro directory (must stay empty).

        Raises:
            AssertionError: On any divergence or missing examples.
        """
        target = TARGETS_BY_NAME["pythoncompat"]
        report = run_target(
            target,
            _server_call(OracleServer()),
            _server_call(OracleServer()),
            max_examples=5,
            repro_dir=tmp_path,
        )
        assert report.divergences == 0
        assert report.error is None
        # Every R10.9 edge call runs plus the generated budget.
        assert report.examples >= len(target.edge_calls) + 5
        assert list(tmp_path.iterdir()) == []

    def test_divergence_is_shrunk_and_reproduced(self, tmp_path: Path) -> None:
        """A rigged bridge yields divergences=1 and a repro file.

        Raises:
            AssertionError: If the divergence or repro is missing.

        Args:
            tmp_path: Repro directory.
        """
        target = TARGETS_BY_NAME["pythoncompat"]
        report = run_target(
            target,
            _server_call(OracleServer()),
            _rigged_call("compat.zfill"),
            max_examples=5,
            repro_dir=tmp_path,
        )
        assert report.divergences == 1
        assert report.repro_path is not None
        payload = json.loads(Path(report.repro_path).read_text(encoding="utf-8"))
        assert payload["target"] == "pythoncompat"
        assert payload["api"] == "compat.zfill"
        assert payload["right"]["output"] == "CORRUPTED"

    def test_bridge_failure_is_error_not_divergence(self, tmp_path: Path) -> None:
        """A dead bridge lands in ``report.error`` (crash is never a catch).

        Args:
            tmp_path: Repro directory (must stay empty).

        Raises:
            AssertionError: If the failure is misclassified.
        """

        def dead(_api: str, _encoded: Mapping[str, Any]) -> Mapping[str, Any]:
            """Simulate a dead bridge pipe.

            Args:
                _api: Ignored.
                _encoded: Ignored.

            Returns:
                Never returns.

            Raises:
                OracleBridgeError: Always.
            """
            raise OracleBridgeError("oracle closed the pipe")

        report = run_target(
            TARGETS_BY_NAME["pythoncompat"],
            _server_call(OracleServer()),
            dead,
            max_examples=5,
            repro_dir=tmp_path,
        )
        assert report.divergences == 0
        assert report.error is not None
        assert list(tmp_path.iterdir()) == []


class TestStrategyTable:
    """Structural invariants of the Phase-1 target table."""

    def test_all_phase1_priority_targets_present(self) -> None:
        """The table carries exactly the design D14 priority vocabulary.

        Raises:
            AssertionError: On a missing or extra target.
        """
        assert tuple(target.name for target in PHASE1_TARGETS) == _EXPECTED_TARGET_NAMES

    @pytest.mark.parametrize(
        "target", PHASE1_TARGETS, ids=[t.name for t in PHASE1_TARGETS]
    )
    def test_edge_calls_resolve_through_registry(self, target: FuzzTarget) -> None:
        """Every edge call names a builder/validator registry entry (D14).

        Args:
            target: The target under inspection.

        Raises:
            AssertionError: On an unknown api or out-of-scope kind.
        """
        assert target.edge_calls, "R10.9 mandatory edge set must be non-empty"
        for api, kwargs in target.edge_calls:
            entry = REGISTRY_BY_API.get(api)
            assert entry is not None, f"edge api {api!r} is not a registry entry"
            assert entry.kind in (KIND_BUILDER, KIND_VALIDATOR)
            assert isinstance(kwargs, dict)

    @pytest.mark.parametrize(
        "target", PHASE1_TARGETS, ids=[t.name for t in PHASE1_TARGETS]
    )
    def test_edge_calls_execute_on_oracle_py(self, target: FuzzTarget) -> None:
        """Every edge call executes as call DATA (never a protocol error).

        Args:
            target: The target under inspection.

        Raises:
            AssertionError: If an edge call fails at the protocol level.
        """
        from conformance.record.codecs import encode_input_kwargs

        server = OracleServer()
        for api, kwargs in target.edge_calls:
            payload = server.call_api(api, encode_input_kwargs(kwargs))
            assert "ok" in payload, (api, payload)


class TestPhase2StrategyTable:
    """Structural invariants of the Phase-2 target table (P2-9, C9)."""

    _PHASE2_NAMES = (
        "filter_family",
        "metric_group_family",
        "cohort_family",
        "funnel_family",
        "retention_flow_family",
        "frequency_family",
        "replay_family",
        "codec_roundtrip",
    )

    def test_all_targets_extends_phase1_with_phase2(self) -> None:
        """``ALL_TARGETS`` is the Phase-1 table plus the 8 P2-9 targets.

        Raises:
            AssertionError: On a missing or misordered target.
        """
        from conformance.differential.strategies import ALL_TARGETS

        names = tuple(target.name for target in ALL_TARGETS)
        assert names == (*_EXPECTED_TARGET_NAMES, *self._PHASE2_NAMES)

    def test_harvest_covers_every_phase2_guard_code_and_api(self) -> None:
        """The corpus harvest closes the R10.9 "every error branch" item.

        One probe per Phase-2 guard code (all 81 per the generated
        registry artifact) and one per `types.*` api (all 44 per the
        api-index) — the completeness the checked-in coverage artifact
        records.

        Raises:
            AssertionError: On any uncovered code or api.
        """
        from conformance.differential.strategies import (
            edge_coverage_report,
            phase2_guard_codes,
        )

        report = edge_coverage_report()
        assert set(report["guard_codes"]) == set(phase2_guard_codes())
        types_apis = sorted(api for api in REGISTRY_BY_API if api.startswith("types."))
        assert sorted(report["apis"]) == types_apis
        assert len(types_apis) == 44

    def test_checked_in_coverage_artifact_is_in_sync(self) -> None:
        """`phase2-edge-coverage.json` matches a fresh report build.

        Raises:
            AssertionError: On drift (re-generate and re-commit).
        """
        import json as _json
        from pathlib import Path as _Path

        from conformance.differential.strategies import edge_coverage_report

        artifact = _Path(__file__).resolve().parents[1] / "differential"
        committed = _json.loads(
            (artifact / "phase2-edge-coverage.json").read_text(encoding="utf-8")
        )
        assert committed == _json.loads(
            _json.dumps(edge_coverage_report(), ensure_ascii=True)
        )

    def test_phase2_edge_calls_resolve(self) -> None:
        """Every Phase-2 edge call names a registry entry or the sentinel.

        Raises:
            AssertionError: On an unknown api or empty edge set.
        """
        from conformance.differential.strategies import (
            CODEC_ROUNDTRIP_API,
            PHASE2_TARGETS,
        )

        for target in PHASE2_TARGETS:
            assert target.edge_calls, target.name
            for api, kwargs in target.edge_calls:
                assert isinstance(kwargs, dict)
                if api == CODEC_ROUNDTRIP_API:
                    assert target.name == "codec_roundtrip"
                    assert "value" in kwargs
                    continue
                entry = REGISTRY_BY_API.get(api)
                assert entry is not None, f"edge api {api!r} not registered"
                assert entry.kind in (KIND_BUILDER, KIND_VALIDATOR)

    def test_phase2_edge_calls_execute_on_oracle_py(self) -> None:
        """Every Phase-2 edge call is call DATA (never a protocol error).

        Roundtrip edges go through ``codec_roundtrip``; api edges through
        ``call_api`` — both must produce ``ok`` payloads on oracle-py.

        Raises:
            AssertionError: If an edge call fails at the protocol level.
        """
        from conformance.differential.strategies import (
            CODEC_ROUNDTRIP_API,
            PHASE2_TARGETS,
        )
        from conformance.record.codecs import encode_input_kwargs

        server = OracleServer()
        for target in PHASE2_TARGETS:
            for api, kwargs in target.edge_calls:
                encoded = encode_input_kwargs(kwargs)
                if api == CODEC_ROUNDTRIP_API:
                    payload = server.codec_roundtrip({"value": encoded["value"]})
                else:
                    payload = server.call_api(api, encoded)
                assert "ok" in payload, (target.name, api, payload)

    def test_roundtrip_probe_routes_to_the_protocol_method(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`OracleProcess.call` routes the sentinel api to §8's method.

        Args:
            monkeypatch: Pytest monkeypatch fixture.

        Raises:
            AssertionError: If the request method/params are wrong.
        """
        from conformance.differential.strategies import CODEC_ROUNDTRIP_API

        seen: list[tuple[str, Any]] = []

        def fake_request(
            _self: OracleProcess, method: str, params: Any
        ) -> dict[str, Any]:
            """Record the outgoing request instead of using a pipe.

            Args:
                _self: The process wrapper (unused by the double).
                method: The JSON-RPC method.
                params: The params object.

            Returns:
                A canned ok payload.
            """
            seen.append((method, params))
            return {"ok": True, "output": None}

        monkeypatch.setattr(OracleProcess, "_request", fake_request)
        process = OracleProcess(["unused"])
        process.call(
            CODEC_ROUNDTRIP_API, {"value": {"$type": "float", "value": "18.0"}}
        )
        process.call("types.Filter.on", {"property": "p", "date": "d"})
        assert seen[0] == (
            "codec.roundtrip",
            {"value": {"$type": "float", "value": "18.0"}},
        )
        assert seen[1][0] == "oracle.call"
