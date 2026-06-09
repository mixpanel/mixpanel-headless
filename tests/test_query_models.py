"""Tests for Pydantic query models in query_models.py.

Verifies construction, JSON schema generation, model_validate round-trip,
frozen immutability, and field constraints for all query model types.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel, ValidationError

from mixpanel_headless.query_models import (
    FlowQuery,
    FunnelQuery,
    InsightsQuery,
    RetentionQuery,
)
from mixpanel_headless.types import (
    CohortBreakdown,
    Exclusion,
    Filter,
    FlowStep,
    Formula,
    FrequencyBreakdown,
    FrequencyFilter,
    FunnelStep,
    GroupBy,
    HoldingConstant,
    Metric,
    RetentionEvent,
    TimeComparison,
)

ALL_MODELS = [InsightsQuery, FunnelQuery, RetentionQuery, FlowQuery]


def _minimal_insights() -> InsightsQuery:
    """Build a minimal valid InsightsQuery."""
    return InsightsQuery(events=[Metric("Login")])


def _minimal_funnel() -> FunnelQuery:
    """Build a minimal valid FunnelQuery."""
    return FunnelQuery(steps=["Signup", "Purchase"])


def _minimal_retention() -> RetentionQuery:
    """Build a minimal valid RetentionQuery."""
    return RetentionQuery(born_event="Signup", return_event="Login")


def _minimal_flow() -> FlowQuery:
    """Build a minimal valid FlowQuery."""
    return FlowQuery(event="Login")


# =============================================================================
# Schema Generation
# =============================================================================


class TestSchemaGeneration:
    """All models produce valid JSON schemas via model_json_schema()."""

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_schema_is_dict(self, model_cls: type[BaseModel]) -> None:
        """model_json_schema() returns a non-empty dict."""
        schema = model_cls.model_json_schema()
        assert isinstance(schema, dict)
        assert "properties" in schema


# =============================================================================
# Frozen Immutability
# =============================================================================


class TestFrozenImmutability:
    """All models are frozen (immutable after construction)."""

    def test_insights_frozen(self) -> None:
        """InsightsQuery fields cannot be reassigned."""
        q = _minimal_insights()
        with pytest.raises(ValidationError):
            q.last = 7  # type: ignore[misc]

    def test_funnel_frozen(self) -> None:
        """FunnelQuery fields cannot be reassigned."""
        q = _minimal_funnel()
        with pytest.raises(ValidationError):
            q.last = 7  # type: ignore[misc]

    def test_retention_frozen(self) -> None:
        """RetentionQuery fields cannot be reassigned."""
        q = _minimal_retention()
        with pytest.raises(ValidationError):
            q.last = 7  # type: ignore[misc]

    def test_flow_frozen(self) -> None:
        """FlowQuery fields cannot be reassigned."""
        q = _minimal_flow()
        with pytest.raises(ValidationError):
            q.last = 7  # type: ignore[misc]


# =============================================================================
# InsightsQuery
# =============================================================================


class TestInsightsQuery:
    """Construction, validation, and round-trip for InsightsQuery."""

    def test_minimal_construction(self) -> None:
        """Minimal construction with one event succeeds."""
        q = _minimal_insights()
        assert len(q.events) == 1
        assert q.last == 30
        assert q.mode == "timeseries"

    def test_events_min_length(self) -> None:
        """Empty events list raises BookmarkValidationError."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError, match="events"):
            InsightsQuery(events=[])

    def test_full_construction(self) -> None:
        """Construction with all optional fields."""
        q = InsightsQuery(
            events=[Metric("Login", math="unique"), Formula("A * 100")],
            from_date="2026-01-01",
            to_date="2026-01-31",
            last=7,
            unit="week",
            math="unique",
            group_by=[GroupBy("country")],
            where=[Filter.equals("platform", "iOS")],
            formula="A * 100",
            formula_label="Rate",
            rolling=7,
            mode="total",
            time_comparison=TimeComparison.relative("month"),
            data_group_id=1,
        )
        assert q.from_date == "2026-01-01"
        assert q.unit == "week"

    def test_model_validate_dict(self) -> None:
        """Round-trip from dict via model_validate."""
        q = InsightsQuery.model_validate(
            {
                "events": [{"event": "Login", "math": "unique"}],
                "last": 7,
            }
        )
        assert len(q.events) == 1
        assert q.last == 7

    def test_frequency_filter(self) -> None:
        """FrequencyFilter accepted in where list."""
        q = InsightsQuery(
            events=[Metric("Purchase")],
            where=[FrequencyFilter("Login", value=5)],
        )
        assert len(q.where) == 1  # type: ignore[arg-type]

    def test_frequency_breakdown(self) -> None:
        """FrequencyBreakdown accepted in group_by list."""
        q = InsightsQuery(
            events=[Metric("Purchase")],
            group_by=[FrequencyBreakdown("Login")],
        )
        assert len(q.group_by) == 1  # type: ignore[arg-type]


# =============================================================================
# FunnelQuery
# =============================================================================


class TestFunnelQuery:
    """Construction, validation, and round-trip for FunnelQuery."""

    def test_minimal_construction(self) -> None:
        """Minimal construction with two string steps."""
        q = _minimal_funnel()
        assert len(q.steps) == 2
        assert q.conversion_window == 14
        assert q.mode == "steps"

    def test_steps_min_length(self) -> None:
        """Single step raises BookmarkValidationError (minimum 2)."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError, match="steps"):
            FunnelQuery(steps=["Signup"])

    def test_funnel_step_objects(self) -> None:
        """FunnelStep objects accepted in steps list."""
        q = FunnelQuery(
            steps=[FunnelStep("Signup"), FunnelStep("Purchase")],
        )
        assert len(q.steps) == 2

    def test_full_construction(self) -> None:
        """Construction with all optional fields."""
        q = FunnelQuery(
            steps=["Signup", "Purchase"],
            conversion_window=7,
            conversion_window_unit="hour",
            order="any",
            math="conversion_rate_unique",
            group_by=[GroupBy("country")],
            where=[Filter.equals("platform", "iOS")],
            exclusions=[Exclusion("Error", from_step=0, to_step=1)],
            holding_constant=[HoldingConstant("device")],
            mode="trends",
            reentry_mode="basic",
            time_comparison=TimeComparison.relative("month"),
        )
        assert q.conversion_window == 7
        assert q.order == "any"

    def test_model_validate_dict(self) -> None:
        """Round-trip from dict via model_validate."""
        q = FunnelQuery.model_validate(
            {
                "steps": ["Signup", "Purchase"],
                "conversion_window": 7,
            }
        )
        assert len(q.steps) == 2
        assert q.conversion_window == 7


# =============================================================================
# RetentionQuery
# =============================================================================


class TestRetentionQuery:
    """Construction, validation, and round-trip for RetentionQuery."""

    def test_minimal_construction(self) -> None:
        """Minimal construction with born and return events."""
        q = _minimal_retention()
        assert q.born_event == "Signup"
        assert q.retention_unit == "week"
        assert q.mode == "curve"

    def test_retention_event_objects(self) -> None:
        """RetentionEvent objects accepted."""
        q = RetentionQuery(
            born_event=RetentionEvent("Signup"),
            return_event=RetentionEvent(
                "Purchase",
                filters=[Filter.equals("category", "premium")],
            ),
        )
        assert isinstance(q.return_event, RetentionEvent)

    def test_full_construction(self) -> None:
        """Construction with all optional fields."""
        q = RetentionQuery(
            born_event="Signup",
            return_event="Login",
            retention_unit="month",
            alignment="interval_start",
            bucket_sizes=[1, 3, 7],
            from_date="2026-01-01",
            to_date="2026-03-31",
            math="unique",
            group_by=[GroupBy("country")],
            where=[Filter.equals("platform", "iOS")],
            mode="trends",
            unbounded_mode="carry_forward",
            retention_cumulative=True,
            time_comparison=TimeComparison.relative("month"),
        )
        assert q.retention_unit == "month"
        assert q.retention_cumulative is True

    def test_model_validate_dict(self) -> None:
        """Round-trip from dict via model_validate."""
        q = RetentionQuery.model_validate(
            {
                "born_event": "Signup",
                "return_event": "Login",
                "retention_unit": "day",
            }
        )
        assert q.retention_unit == "day"


# =============================================================================
# FlowQuery
# =============================================================================


class TestFlowQuery:
    """Construction, validation, and round-trip for FlowQuery."""

    def test_minimal_construction(self) -> None:
        """Minimal construction with one event string."""
        q = _minimal_flow()
        assert q.event == "Login"
        assert q.forward == 3
        assert q.mode == "sankey"

    def test_flow_step_object(self) -> None:
        """FlowStep object accepted."""
        q = FlowQuery(event=FlowStep("Login", forward=5))
        assert isinstance(q.event, FlowStep)

    def test_event_list(self) -> None:
        """List of events accepted."""
        q = FlowQuery(event=["Login", FlowStep("Purchase")])
        assert isinstance(q.event, list)
        assert len(q.event) == 2

    def test_full_construction(self) -> None:
        """Construction with all optional fields."""
        q = FlowQuery(
            event="Login",
            forward=5,
            reverse=2,
            from_date="2026-01-01",
            to_date="2026-01-31",
            conversion_window=14,
            conversion_window_unit="week",
            count_type="total",
            cardinality=5,
            collapse_repeated=True,
            hidden_events=["Error"],
            mode="paths",
            where=[Filter.equals("platform", "iOS")],
            segments=[GroupBy("country")],
            exclusions=["Logout"],
        )
        assert q.forward == 5
        assert q.collapse_repeated is True

    def test_model_validate_dict(self) -> None:
        """Round-trip from dict via model_validate."""
        q = FlowQuery.model_validate(
            {
                "event": "Login",
                "forward": 5,
                "mode": "tree",
            }
        )
        assert q.forward == 5
        assert q.mode == "tree"

    def test_segments_with_frequency_breakdown(self) -> None:
        """FrequencyBreakdown accepted in segments list."""
        q = FlowQuery(
            event="Login",
            segments=[FrequencyBreakdown("Purchase")],
        )
        assert len(q.segments) == 1  # type: ignore[arg-type]

    def test_segments_with_cohort_breakdown(self) -> None:
        """CohortBreakdown accepted in segments list."""
        q = FlowQuery(
            event="Login",
            segments=[CohortBreakdown(cohort=123)],
        )
        assert len(q.segments) == 1  # type: ignore[arg-type]


# =============================================================================
# Extra Fields Rejection (C1)
# =============================================================================


class TestExtraFieldsRejected:
    """Models must reject unknown keys (extra='forbid')."""

    def test_insights_rejects_extra_top_level(self) -> None:
        """InsightsQuery rejects unknown top-level keys."""
        with pytest.raises(ValidationError, match="extra_forbidden"):
            InsightsQuery.model_validate(
                {"events": [{"event": "Login"}], "typo_field": 1}
            )

    def test_funnel_rejects_extra_top_level(self) -> None:
        """FunnelQuery rejects unknown top-level keys."""
        with pytest.raises(ValidationError, match="extra_forbidden"):
            FunnelQuery.model_validate(
                {"steps": ["A", "B"], "typo_field": 1}
            )

    def test_retention_rejects_extra_top_level(self) -> None:
        """RetentionQuery rejects unknown top-level keys."""
        with pytest.raises(ValidationError, match="extra_forbidden"):
            RetentionQuery.model_validate(
                {"born_event": "A", "return_event": "B", "extra_key": 1}
            )

    def test_flow_rejects_extra_top_level(self) -> None:
        """FlowQuery rejects unknown top-level keys."""
        with pytest.raises(ValidationError, match="extra_forbidden"):
            FlowQuery.model_validate({"event": "A", "extra_key": 1})


# =============================================================================
# Bare String Events (C2)
# =============================================================================


class TestBareStringEvents:
    """InsightsQuery must accept bare strings in events and group_by."""

    def test_bare_string_event(self) -> None:
        """InsightsQuery accepts a bare string event name."""
        q = InsightsQuery(events=["Login"])
        assert q.events == ["Login"]

    def test_mixed_string_and_metric(self) -> None:
        """InsightsQuery accepts a mix of strings and Metric objects."""
        q = InsightsQuery(events=["Login", Metric("Purchase", math="unique")])
        assert len(q.events) == 2

    def test_bare_string_via_model_validate(self) -> None:
        """InsightsQuery.model_validate accepts bare string events."""
        q = InsightsQuery.model_validate({"events": ["Login"]})
        assert q.events == ["Login"]

    def test_bare_string_group_by(self) -> None:
        """InsightsQuery accepts bare string group_by."""
        q = InsightsQuery(events=["Login"], group_by=["country"])
        assert q.group_by == ["country"]


# =============================================================================
# Public Exports (I3)
# =============================================================================


class TestPublicExports:
    """Query models must appear in mixpanel_headless.__all__."""

    @pytest.mark.parametrize(
        "name",
        ["InsightsQuery", "FunnelQuery", "RetentionQuery", "FlowQuery"],
    )
    def test_in_all(self, name: str) -> None:
        """Query model is listed in __all__."""
        import mixpanel_headless

        assert name in mixpanel_headless.__all__


# =============================================================================
# Validation Error Contract (I1)
# =============================================================================


class TestValidationErrorContract:
    """min-length constraints must raise BookmarkValidationError, not Pydantic."""

    def test_empty_events_raises_bookmark_error(self) -> None:
        """InsightsQuery(events=[]) raises BookmarkValidationError."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            InsightsQuery(events=[])

    def test_single_step_raises_bookmark_error(self) -> None:
        """FunnelQuery(steps=['A']) raises BookmarkValidationError (needs 2)."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            FunnelQuery(steps=["A"])

    def test_bookmark_error_has_structured_fields(self) -> None:
        """BookmarkValidationError carries code and path."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery(events=[])
        err = exc_info.value
        assert err.error_count >= 1
        assert len(err.errors) >= 1
        first = err.errors[0]
        assert first.path == "events"


# =============================================================================
# Round-Trip Serialization (I4)
# =============================================================================


class TestRoundTrip:
    """model.model_dump() -> Model.model_validate(dump) preserves equality."""

    def test_insights_round_trip(self) -> None:
        """InsightsQuery survives dump/validate round-trip."""
        original = InsightsQuery(
            events=[Metric("Login", math="unique")],
            last=7,
            group_by=[GroupBy("country")],
        )
        restored = InsightsQuery.model_validate(original.model_dump())
        assert restored == original

    def test_funnel_round_trip(self) -> None:
        """FunnelQuery survives dump/validate round-trip."""
        original = FunnelQuery(
            steps=[FunnelStep("Signup"), FunnelStep("Purchase")],
            conversion_window=7,
        )
        restored = FunnelQuery.model_validate(original.model_dump())
        assert restored == original

    def test_retention_round_trip(self) -> None:
        """RetentionQuery survives dump/validate round-trip."""
        original = RetentionQuery(
            born_event="Signup",
            return_event=RetentionEvent("Login"),
        )
        restored = RetentionQuery.model_validate(original.model_dump())
        assert restored == original

    def test_flow_round_trip(self) -> None:
        """FlowQuery survives dump/validate round-trip."""
        original = FlowQuery(event="Login", forward=5, reverse=2)
        restored = FlowQuery.model_validate(original.model_dump())
        assert restored == original


# =============================================================================
# Nested Dict Validation (I4)
# =============================================================================


class TestNestedDictValidation:
    """model_validate with nested dicts for dataclass members."""

    def test_metric_from_dict(self) -> None:
        """Metric constructed from dict inside InsightsQuery."""
        q = InsightsQuery.model_validate(
            {"events": [{"event": "Login", "math": "unique"}]}
        )
        assert len(q.events) == 1

    def test_funnel_step_from_dict(self) -> None:
        """FunnelStep constructed from dict inside FunnelQuery."""
        q = FunnelQuery.model_validate(
            {"steps": [{"event": "Signup"}, {"event": "Purchase"}]}
        )
        assert len(q.steps) == 2

    def test_retention_event_from_dict(self) -> None:
        """RetentionEvent constructed from dict inside RetentionQuery."""
        q = RetentionQuery.model_validate(
            {"born_event": {"event": "Signup"}, "return_event": "Login"}
        )
        assert q.born_event is not None

    def test_flow_step_from_dict(self) -> None:
        """FlowStep constructed from dict inside FlowQuery."""
        q = FlowQuery.model_validate(
            {"event": {"event": "Login"}}
        )
        assert q.event is not None

    def test_exclusion_from_dict(self) -> None:
        """Exclusion constructed from dict inside FunnelQuery."""
        q = FunnelQuery.model_validate(
            {
                "steps": ["Signup", "Purchase"],
                "exclusions": [{"event": "Logout"}],
            }
        )
        assert q.exclusions is not None
        assert len(q.exclusions) == 1


# =============================================================================
# Member-Level Extra Forbid (I7)
# =============================================================================


class TestMemberExtraForbid:
    """Typos in nested member dicts must be rejected."""

    def test_metric_typo_rejected(self) -> None:
        """Capital-M 'Math' in Metric dict is rejected."""
        with pytest.raises(ValidationError):
            InsightsQuery.model_validate(
                {"events": [{"event": "Login", "Math": "unique"}]}
            )

    def test_funnel_step_typo_rejected(self) -> None:
        """Extra key in FunnelStep dict is rejected."""
        with pytest.raises(ValidationError):
            FunnelQuery.model_validate(
                {"steps": [{"event": "A", "typo": 1}, {"event": "B"}]}
            )

    def test_retention_event_typo_rejected(self) -> None:
        """Extra key in RetentionEvent dict is rejected."""
        with pytest.raises(ValidationError):
            RetentionQuery.model_validate(
                {
                    "born_event": {"event": "Signup", "extra": 1},
                    "return_event": "Login",
                }
            )
