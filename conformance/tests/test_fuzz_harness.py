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

    _PHASE3_NAMES = (
        "python_int",
        "python_float",
        "python_strip",
        "sorted_strings",
        "cp_length",
        "cp_slice",
        "jsonl_chunks",
    )
    """The B0 targets: B0-1 pythonCompat completion + the B0-2
    ``api_client._iter_jsonl_lines`` chunk adapter (P3-4 packets), in packet
    order."""

    _PHASE3_B2_NAMES = (
        "time_args_family",
        "group_by_args_family",
        "query_args_family",
        "funnel_args_family",
        "retention_args_family",
        "flow_args_family",
        "bookmark_family",
        "flow_bookmark_family",
        "sorting_family",
        "user_args_family",
        "user_params_family",
    )
    """The B2 validator families (b2-packets.md R10.9 harness specs,
    registered at the B2-BIND (b') task), in packet V1a/V1b/V2 order."""

    _PHASE3_B3_NAMES = (
        "bookmark_schema_family",
        "get_root_model_family",
    )
    """The B3-K1 ``bookmark_schema`` families (b3-packets.md §"R10.9
    harness spec (K1)"). Declared by the K1 module task; SERVED once the
    B3 (b′) binding task lands the name-resolving
    ``validate_with_pydantic`` adapter and retargets the registry entry."""

    _PHASE3_B3_K2_NAMES = (
        "build_filter_section_family",
        "build_group_section_family",
        "build_flow_property_filter_family",
        "build_flow_cohort_filter_family",
        "build_frequency_filter_entry_family",
        "build_time_section_family",
        "build_date_range_family",
    )
    """The B3-K2 ``bookmark_builders`` families (b3-packets.md §"R10.9
    harness spec (K2)"), in packet order. Declared by the K2 module task;
    SERVED once the B3 (b′) binding task registers the TS builders.
    ``build_filter_entry`` is absent by design — the Phase-1
    ``build_filter_entry`` target already drives it."""

    _PHASE3_B3_K3_NAMES = (
        "transform_event_family",
        "transform_profile_family",
    )
    """The B3-K3 ``transforms`` families (b3-packets.md §"R10.9 harness
    spec (K3)"), declared at the B3-BIND (b′) task per the K3-notes §7.4
    deferral. ``build_segfilter_entry`` / ``normalize_on_expression`` are
    absent by design — the Phase-1 targets already drive them (B3-BIND
    added the K3 operator-row sweep to the segfilter target's edge
    set)."""

    _PHASE3_B3_K4_NAMES = ("extract_cohort_filter_family",)
    """The B3-K4 ``user_builders`` family (b3-packets.md §"R10.9 harness
    spec (K4)"). Declared by the K4 module task; SERVED once the B3 (b′)
    binding task registers the TS side. The two selector entry points are
    absent by design — the Phase-1 ``filter_to_selector`` /
    ``filters_to_selector`` targets already drive them (K4 widened their
    drawn Filter domain with the mandatory escaping bias)."""

    _PHASE3_B5_NAMES = (
        "workspace_build_params_family",
        "workspace_build_funnel_params_family",
        "workspace_build_flow_params_family",
        "workspace_build_retention_params_family",
        "workspace_build_user_params_family",
        "replay_url_normalizer_family",
        "replay_default_label_family",
        "replay_selector_label_family",
        "rrweb_analyze_family",
    )
    """The B5 families (b5-packets.md §6.6): the five
    ``workspace.build_*params`` facade builders + the four replay
    builders. Declared at the B5-BIND (b′) task; SERVED through the
    shared TS bindings registration (``wire-workspace.ts`` /
    ``replays-bindings.ts``). The wire-kind B5 members (facade query /
    discovery / replay members, ``replays.*``) are absent by design —
    wire names have no oracle call surface (P3-2 c)."""

    def test_all_targets_extends_phase1_with_phase2(self) -> None:
        """``ALL_TARGETS`` is Phase 1 + P2-9 + B0 + the B2/B3/B5 families.

        Raises:
            AssertionError: On a missing or misordered target.
        """
        from conformance.differential.strategies import ALL_TARGETS

        names = tuple(target.name for target in ALL_TARGETS)
        assert names == (
            *_EXPECTED_TARGET_NAMES,
            *self._PHASE2_NAMES,
            *self._PHASE3_NAMES,
            *self._PHASE3_B2_NAMES,
            *self._PHASE3_B3_NAMES,
            *self._PHASE3_B3_K2_NAMES,
            *self._PHASE3_B3_K3_NAMES,
            *self._PHASE3_B3_K4_NAMES,
            *self._PHASE3_B5_NAMES,
        )

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


class TestSeededRuns:
    """The P3-7 fresh-seed mode (``seed=`` threading, added at the B0 gate).

    A batch-gate regression run must use FRESH seeds while staying
    reproducible from the RUN record (P3-2c/P3-7): ``seed=None`` keeps the
    historical ``derandomize=True`` behavior; an explicit integer seed
    switches Hypothesis to seeded generation whose probe sequence is a
    pure function of the seed.
    """

    @staticmethod
    def _recording_call(log: list[tuple[str, str]]) -> Any:
        """Wrap a fresh in-process server, logging every probe.

        Args:
            log: Destination list receiving ``(api, canonical-json-input)``
                entries in call order.

        Returns:
            An ``OracleCall`` surface backed by :class:`OracleServer`.
        """
        server = OracleServer()

        def call(api: str, encoded_input: Mapping[str, Any]) -> Mapping[str, Any]:
            """Delegate one probe to the server, recording it first.

            Args:
                api: The dotted registry api name.
                encoded_input: The codec-encoded kwargs.

            Returns:
                The call result payload.
            """
            log.append((api, json.dumps(encoded_input, sort_keys=True)))
            return server.call_api(api, encoded_input)

        return call

    def _sequence_for(
        self, tmp_path: Path, target_name: str, seed: int | None, budget: int
    ) -> list[tuple[str, str]]:
        """Run one clean seeded/derandomized pass and return the probe log.

        Args:
            tmp_path: Repro directory (must stay empty — the run is
                self-parity, so no divergence may occur).
            target_name: Key into :data:`TARGETS_BY_NAME`.
            seed: Hypothesis seed, or None for the derandomized default.
            budget: Generated-example budget.

        Returns:
            The left bridge's ``(api, canonical-json-input)`` log.

        Raises:
            AssertionError: On divergence, bridge error, or repro output.
        """
        log: list[tuple[str, str]] = []
        report = run_target(
            TARGETS_BY_NAME[target_name],
            self._recording_call(log),
            self._recording_call([]),
            max_examples=budget,
            repro_dir=tmp_path,
            seed=seed,
        )
        assert report.divergences == 0
        assert report.error is None
        assert list(tmp_path.iterdir()) == []
        return log

    def test_same_seed_reproduces_call_sequence(self, tmp_path: Path) -> None:
        """Two runs with one seed generate the identical probe sequence.

        This is the review-pair reproducibility contract: the RUN record's
        seed replays the exact generated corpus (P3-2d item 5).

        Args:
            tmp_path: Repro directory (must stay empty).

        Raises:
            AssertionError: If the sequences differ or a run is dirty.
        """
        first = self._sequence_for(tmp_path, "python_int", 1234, 25)
        second = self._sequence_for(tmp_path, "python_int", 1234, 25)
        assert first == second
        assert len(first) >= 25

    def test_distinct_seeds_vary_generation(self, tmp_path: Path) -> None:
        """Different seeds explore different generated corpora.

        Locks the 'fresh seeds' half of P3-7: a gate run with a new seed
        is not a byte-replay of a previous run (the shared prefix is only
        the deterministic R10.9 ``@example`` edge set).

        Args:
            tmp_path: Repro directory (must stay empty).

        Raises:
            AssertionError: If both seeds generate identical sequences.
        """
        alfa = self._sequence_for(tmp_path, "python_int", 0, 30)
        bravo = self._sequence_for(tmp_path, "python_int", 1, 30)
        assert alfa != bravo

    def test_default_stays_derandomized(self, tmp_path: Path) -> None:
        """``seed=None`` keeps the deterministic seedless behavior.

        Two seedless runs must stay byte-identical — the pre-gate
        contract every earlier RUN record (B0-1/B0-2, P2-9) relies on.

        Args:
            tmp_path: Repro directory (must stay empty).

        Raises:
            AssertionError: If seedless runs stop being deterministic.
        """
        first = self._sequence_for(tmp_path, "python_int", None, 10)
        second = self._sequence_for(tmp_path, "python_int", None, 10)
        assert first == second


class TestB3SchemaCallDomainIntegrity:
    """``_b3_schema_calls`` stays transport-shippable and side-effect-free.

    B3-gate regression lock (2026-08-15): ``_B3_LEAF_VALUES`` carries
    module-level MUTABLE containers (``{}``, ``{"k": 1}``, ``[{}]``).
    Pre-fix, the mutation arms of ``_b3_schema_calls`` inserted them BY
    REFERENCE and later writes (``_b3_set_path`` walking through an
    inserted leaf, or direct key writes when ``value`` IS an inserted
    leaf) mutated the shared constants, so nesting accumulated across
    examples until ``encode_input_kwargs`` hit the codec depth guard
    (``UnencodableValueError`` — a harness transport crash, not a bridge
    divergence; B3-gate full-suite replays at seeds 3343231 and
    28631260). The choice-3 graft arm already json-round-tripped its
    payloads; this suite locks the same copy-at-draw discipline for every
    arm.
    """

    def test_drawing_never_mutates_leaf_constants_and_always_ships(
        self,
    ) -> None:
        """Derandomized draws leave the constants pristine and encodable.

        Raises:
            AssertionError: If a drawn probe is not transport-shippable
                or any ``_B3_LEAF_VALUES`` entry mutated during drawing.
        """
        import copy

        from hypothesis import HealthCheck, given, settings

        from conformance.differential import strategies as strat
        from conformance.record.codecs import encode_input_kwargs

        snapshot = copy.deepcopy(strat._B3_LEAF_VALUES)
        shared_ids = {
            id(leaf) for leaf in strat._B3_LEAF_VALUES if isinstance(leaf, (dict, list))
        }

        def assert_no_shared_reference(obj: Any) -> None:
            """Recursively assert no drawn container IS a leaf constant.

            A by-reference insertion is the defect even before nesting
            accumulates: later in-place writes through it corrupt the
            module-level domain for every subsequent example.

            Args:
                obj: A drawn kwargs subtree.

            Raises:
                AssertionError: If ``obj`` aliases a mutable
                    ``_B3_LEAF_VALUES`` entry.
            """
            if isinstance(obj, (dict, list)):
                assert id(obj) not in shared_ids, (
                    "_b3_schema_calls inserted a _B3_LEAF_VALUES container "
                    "by reference — mutation arms must deep-copy at draw "
                    "time"
                )
                items = obj.values() if isinstance(obj, dict) else obj
                for item in items:
                    assert_no_shared_reference(item)

        @given(call=strat._b3_schema_calls())
        @settings(
            max_examples=300,
            derandomize=True,
            database=None,
            deadline=None,
            suppress_health_check=[
                HealthCheck.too_slow,
                HealthCheck.filter_too_much,
            ],
        )
        def run(call: tuple[str, dict[str, Any]]) -> None:
            """Encode one drawn probe (must never raise or alias).

            Args:
                call: The drawn ``(api, kwargs)`` probe.

            Raises:
                UnencodableValueError: If the probe is unshippable
                    (the pre-fix failure mode).
                AssertionError: If the probe aliases a shared leaf.
            """
            _api, kwargs = call
            assert_no_shared_reference(kwargs.get("value"))
            encode_input_kwargs(kwargs)

        run()
        assert snapshot == strat._B3_LEAF_VALUES, (
            "_b3_schema_calls mutated its shared leaf constants — "
            "mutation arms must deep-copy at draw time"
        )
