"""Tests for the bookmark_parser referee routing + handoff producer (D15b).

Covers the pure routing knowledge in
:mod:`conformance.referee_bookmark_parser.harness` — payload wrapping per
builder API, dialect detection (modern nested vs legacy flat show
clauses), and draft-04 schema routing — plus an integration pass of
:func:`conformance.referee_bookmark_parser.handoff.produce_handoff` over
the real committed corpus (the producer re-executes every
bookmark-capability builder vector live, so this doubles as the
"Python-built payloads" integrity check without needing the read-only
analytics checkout).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conformance.referee_bookmark_parser.handoff import (
    HandoffError,
    produce_handoff,
)
from conformance.referee_bookmark_parser.harness import (
    BOOKMARK_TYPES,
    COMMON_SCHEMA,
    FUNNELS_SCHEMA,
    HANDOFF_ROUTES,
    detect_dialect,
    structural_schema_for,
    wrap_payload,
)

VECTORS_ROOT = Path(__file__).resolve().parents[1] / "vectors"
"""The committed corpus root (conformance/vectors)."""

MODERN_SHOW = {
    "behavior": {"name": "Login", "resourceType": "events", "type": "event"},
    "measurement": {"math": "total"},
    "type": "metric",
}
"""A modern nested show clause (workspace.build_params dialect)."""

LEGACY_SHOW = {
    "math": "total",
    "resourceType": "events",
    "value": {"name": "Login", "resourceType": "events"},
}
"""A legacy flat show clause (the dialect insights/validate.py documents)."""


class TestWrapPayload:
    """Wrapping rules mapping builder outputs to handoff params (D15b)."""

    def test_build_params_passthrough(self) -> None:
        """workspace.build_params output is already a full insights payload."""
        output = {"sections": {"show": [MODERN_SHOW]}}
        bookmark_type, params = wrap_payload("workspace.build_params", output)
        assert bookmark_type == "insights"
        assert params == output

    def test_time_section_fragment_is_wrapped(self) -> None:
        """build_time_section emits a sections.time list; wrap it in context."""
        output = [{"dateRangeType": "between", "unit": "day", "value": ["a", "b"]}]
        bookmark_type, params = wrap_payload(
            "bookmark_builders.build_time_section", output
        )
        assert bookmark_type == "insights"
        assert params == {"sections": {"time": output}}

    def test_date_range_fragment_is_wrapped(self) -> None:
        """build_date_range emits a date_range object; wrap it in context."""
        output = {"from_date": "2025-01-01", "to_date": "2025-01-31", "type": "between"}
        bookmark_type, params = wrap_payload(
            "bookmark_builders.build_date_range", output
        )
        assert bookmark_type == "common"
        assert params == {"date_range": output}

    def test_funnel_flow_retention_passthrough(self) -> None:
        """The three non-insights facade builders pass through unwrapped."""
        for api, expected_type in (
            ("workspace.build_funnel_params", "funnels"),
            ("workspace.build_retention_params", "common"),
            ("workspace.build_flow_params", "common"),
        ):
            bookmark_type, params = wrap_payload(api, {"k": 1})
            assert bookmark_type == expected_type
            assert params == {"k": 1}

    def test_unknown_api_raises(self) -> None:
        """APIs outside the handoff route table are a hard error."""
        with pytest.raises(ValueError, match="not a bookmark-payload builder"):
            wrap_payload("expressions.normalize_on_expression", {})

    def test_non_object_payload_raises(self) -> None:
        """A wrapped payload must end up a JSON object (schema root type)."""
        with pytest.raises(ValueError, match="JSON object"):
            wrap_payload("workspace.build_params", [1, 2])

    def test_route_table_covers_documented_apis(self) -> None:
        """The route table matches the D15b feed (six builder APIs)."""
        assert set(HANDOFF_ROUTES) == {
            "workspace.build_params",
            "bookmark_builders.build_time_section",
            "bookmark_builders.build_date_range",
            "workspace.build_funnel_params",
            "workspace.build_retention_params",
            "workspace.build_flow_params",
        }
        assert set(HANDOFF_ROUTES.values()) <= BOOKMARK_TYPES


class TestDetectDialect:
    """Dialect detection over handoff params (D15b dialect rule)."""

    def test_modern_nested_show_clause(self) -> None:
        """behavior/measurement show clauses are the modern nested dialect."""
        params = {"sections": {"show": [MODERN_SHOW]}}
        assert detect_dialect(params) == "modern-nested"

    def test_legacy_flat_show_clause(self) -> None:
        """Flat math/value show clauses are the legacy dialect."""
        params = {"sections": {"show": [LEGACY_SHOW]}}
        assert detect_dialect(params) == "legacy-flat"

    def test_top_level_steps_is_legacy_flat(self) -> None:
        """Flat params with top-level steps (flows, legacy funnels) are legacy."""
        params = {"steps": [{"event": "Login"}], "date_range": {"type": "in the last"}}
        assert detect_dialect(params) == "legacy-flat"

    def test_time_only_payload_is_neutral(self) -> None:
        """Payloads with no show clauses and no steps carry no dialect."""
        params = {"sections": {"time": [{"dateRangeType": "between"}]}}
        assert detect_dialect(params) == "neutral"
        assert detect_dialect({"date_range": {"type": "between"}}) == "neutral"

    def test_mixed_votes_are_reported_mixed(self) -> None:
        """A payload mixing both clause shapes is flagged, never guessed."""
        params = {"sections": {"show": [MODERN_SHOW, LEGACY_SHOW]}}
        assert detect_dialect(params) == "mixed"

    def test_malformed_sections_are_neutral(self) -> None:
        """Non-object sections / non-list show never crash detection."""
        assert detect_dialect({"sections": "nope"}) == "neutral"
        assert detect_dialect({"sections": {"show": "nope"}}) == "neutral"
        assert detect_dialect({"sections": {"show": ["nope"]}}) == "neutral"


class TestStructuralSchemaRouting:
    """Draft-04 schema selection per bookmark_type + dialect (D15b)."""

    def test_funnels_legacy_flat_uses_funnels_schema(self) -> None:
        """Legacy flat funnel params (top-level steps) hit the funnels schema."""
        params = {"steps": [{"event": "Signup"}]}
        assert structural_schema_for("funnels", params) == FUNNELS_SCHEMA

    def test_funnels_modern_dialect_falls_back_to_common(self) -> None:
        """Modern sections-dialect funnel payloads route to the common schema.

        The draft-04 funnels schema REQUIRES legacy flat ``steps``; feeding
        it the modern nested dialect would reject correct library output
        (the same trap D15a documents for ajv), so only its allOf-common
        layer applies.
        """
        params = {"sections": {"show": [MODERN_SHOW]}}
        assert structural_schema_for("funnels", params) == COMMON_SCHEMA

    def test_insights_and_common_use_common_schema(self) -> None:
        """insights/common payloads always validate against the common schema."""
        assert structural_schema_for("insights", {"sections": {}}) == COMMON_SCHEMA
        assert structural_schema_for("common", {"date_range": {}}) == COMMON_SCHEMA

    def test_unknown_bookmark_type_raises(self) -> None:
        """bookmark_type outside the D15b vocabulary is a hard error."""
        with pytest.raises(ValueError, match="bookmark_type"):
            structural_schema_for("retention", {})


class TestProduceHandoff:
    """Integration: live re-execution of the committed corpus (D15b feed)."""

    def test_handoff_covers_all_bookmark_builder_vectors(self) -> None:
        """Every bookmark-capability builder vector yields one handoff entry.

        Re-executes each builder live under the replay clock and
        cross-checks the output against the recorded expectation, so a
        pass here proves the handoff carries genuine Python-built
        payloads, not stale recordings.
        """
        entries = produce_handoff(VECTORS_ROOT)
        assert len(entries) >= 300  # 314 at authoring time; corpus may grow
        ids = [str(entry["id"]) for entry in entries]
        assert len(set(ids)) == len(ids)
        assert ids == sorted(ids)
        for entry in entries:
            assert set(entry) == {"id", "bookmark_type", "params"}
            assert entry["bookmark_type"] in BOOKMARK_TYPES
            assert isinstance(entry["params"], dict)

    def test_handoff_skips_error_expectation_vectors(self, tmp_path: Path) -> None:
        """Coded-guard error vectors carry no payload and are never handed off.

        The E2 coding pass added builder-kind vectors with ``expect.error``
        on handoff-routed apis (e.g. ``workspace.build_flow_params`` BB5
        guards); re-executing them raises by design, so the handoff must
        exclude them from selection instead of aborting.

        Args:
            tmp_path: Temporary corpus root.
        """
        import json

        bundle = tmp_path / "bookmarks" / "test_guard.jsonl"
        bundle.parent.mkdir(parents=True)
        vector = {
            "schema_version": "1.0",
            "id": "bookmarks/workspace.build_flow_params/guard-error",
            "kind": "builder",
            "origin": "extracted",
            "capability": "bookmarks",
            "call": {"api": "workspace.build_flow_params", "input": {}},
            "expect": {
                "error": {
                    "class": "ParamValidationError",
                    "code": "BB5_FLOW_MULTIPLE_COHORT_FILTERS",
                }
            },
        }
        bundle.write_text(json.dumps(vector) + "\n", encoding="utf-8")
        with pytest.raises(HandoffError, match="no bookmark-capability"):
            produce_handoff(tmp_path)

    def test_missing_corpus_root_raises(self) -> None:
        """A bad vectors root fails loudly, never an empty handoff."""
        with pytest.raises(HandoffError, match="corpus load failed"):
            produce_handoff(VECTORS_ROOT / "does-not-exist")

    def test_empty_selection_raises(self, tmp_path: Path) -> None:
        """A corpus with no bookmark builder vectors fails loudly."""
        with pytest.raises(HandoffError, match="no bookmark-capability"):
            produce_handoff(tmp_path)
