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
