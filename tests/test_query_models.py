"""Tests for Pydantic query models in query_models.py.

Verifies construction, JSON schema generation, model_validate round-trip,
frozen immutability, and field constraints for all query model types.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, ClassVar

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from mixpanel_headless._internal.bookmark_schema import _is_union_arm_label
from mixpanel_headless.exceptions import BookmarkValidationError
from mixpanel_headless.query_models import (
    FlowQuery,
    FunnelQuery,
    InsightsQuery,
    RetentionQuery,
)
from mixpanel_headless.types import (
    CohortBreakdown,
    CohortMetric,
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
        assert q.where is not None
        assert len(q.where) == 1

    def test_frequency_breakdown(self) -> None:
        """FrequencyBreakdown accepted in group_by list."""
        q = InsightsQuery(
            events=[Metric("Purchase")],
            group_by=[FrequencyBreakdown("Login")],
        )
        assert q.group_by is not None
        assert len(q.group_by) == 1


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

    def test_segments_with_frequency_breakdown_rejected(self) -> None:
        """FrequencyBreakdown is rejected — the flow segment_by wire format
        only carries plain property names, so accepting it would produce
        silently empty results."""
        with pytest.raises(BookmarkValidationError):
            FlowQuery(event="Login", segments=[FrequencyBreakdown("Purchase")])

    def test_segments_with_cohort_breakdown_rejected(self) -> None:
        """CohortBreakdown is rejected — the flow segment_by wire format
        only carries plain property names."""
        with pytest.raises(BookmarkValidationError):
            FlowQuery(event="Login", segments=[CohortBreakdown(cohort=123)])

    def test_segments_with_group_by_accepted(self) -> None:
        """GroupBy and plain strings remain valid segment specs."""
        q = FlowQuery(event="Login", segments=["country", GroupBy("city")])
        assert q.segments is not None
        assert len(q.segments) == 2


# =============================================================================
# Extra Fields Rejection (C1)
# =============================================================================


class TestExtraFieldsRejected:
    """Models must reject unknown keys (extra='forbid')."""

    def test_insights_rejects_extra_top_level(self) -> None:
        """InsightsQuery rejects unknown top-level keys."""
        with pytest.raises(BookmarkValidationError, match="Extra inputs"):
            InsightsQuery.model_validate(
                {"events": [{"event": "Login"}], "typo_field": 1}
            )

    def test_funnel_rejects_extra_top_level(self) -> None:
        """FunnelQuery rejects unknown top-level keys."""
        with pytest.raises(BookmarkValidationError, match="Extra inputs"):
            FunnelQuery.model_validate({"steps": ["A", "B"], "typo_field": 1})

    def test_retention_rejects_extra_top_level(self) -> None:
        """RetentionQuery rejects unknown top-level keys."""
        with pytest.raises(BookmarkValidationError, match="Extra inputs"):
            RetentionQuery.model_validate(
                {"born_event": "A", "return_event": "B", "extra_key": 1}
            )

    def test_flow_rejects_extra_top_level(self) -> None:
        """FlowQuery rejects unknown top-level keys."""
        with pytest.raises(BookmarkValidationError, match="Extra inputs"):
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
        q = FlowQuery.model_validate({"event": {"event": "Login"}})
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
        with pytest.raises(BookmarkValidationError):
            InsightsQuery.model_validate(
                {"events": [{"event": "Login", "Math": "unique"}]}
            )

    def test_funnel_step_typo_rejected(self) -> None:
        """Extra key in FunnelStep dict is rejected."""
        with pytest.raises(BookmarkValidationError):
            FunnelQuery.model_validate(
                {"steps": [{"event": "A", "typo": 1}, {"event": "B"}]}
            )

    def test_retention_event_typo_rejected(self) -> None:
        """Extra key in RetentionEvent dict is rejected."""
        with pytest.raises(BookmarkValidationError):
            RetentionQuery.model_validate(
                {
                    "born_event": {"event": "Signup", "extra": 1},
                    "return_event": "Login",
                }
            )


# =============================================================================
# Cross-Field Validation (S4 + S5)
# =============================================================================


class TestCrossFieldValidation:
    """Cross-field constraints must be enforced by model validators."""

    def test_flow_empty_event_list_rejected(self) -> None:
        """FlowQuery(event=[]) is rejected."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            FlowQuery(event=[])

    def test_to_date_without_from_date_rejected(self) -> None:
        """to_date without from_date is rejected."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            InsightsQuery(events=["Login"], to_date="2025-01-31")

    def test_percentile_without_value_rejected(self) -> None:
        """math='percentile' without percentile_value is rejected."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            InsightsQuery(events=["Login"], math="percentile")

    def test_last_zero_rejected(self) -> None:
        """last=0 is rejected (must be >= 1)."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            InsightsQuery(events=["Login"], last=0)

    def test_percentile_above_100_rejected(self) -> None:
        """percentile_value=101 is rejected (must be <= 100)."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            InsightsQuery(events=["Login"], math="percentile", percentile_value=101)

    def test_percentile_negative_rejected(self) -> None:
        """percentile_value=-1 is rejected (must be >= 0)."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            InsightsQuery(events=["Login"], math="percentile", percentile_value=-1)

    def test_rolling_zero_rejected(self) -> None:
        """rolling=0 is rejected (must be > 0)."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            InsightsQuery(events=["Login"], rolling=0)

    def test_funnel_conversion_window_zero_rejected(self) -> None:
        """FunnelQuery conversion_window=0 is rejected (must be >= 1)."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            FunnelQuery(steps=["A", "B"], conversion_window=0)

    def test_flow_cardinality_zero_rejected(self) -> None:
        """FlowQuery cardinality=0 is rejected (must be >= 1)."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError):
            FlowQuery(event="Login", cardinality=0)

    def test_flow_zero_steps_accepted_at_construction(self) -> None:
        """FlowQuery(forward=0, reverse=0) is accepted at construction.

        The zero-step check happens at build time (FL5) because
        per-step FlowStep overrides can provide non-zero directions.
        """
        q = FlowQuery(event="Login", forward=0, reverse=0)
        assert q.forward == 0
        assert q.reverse == 0

    def test_valid_percentile_accepted(self) -> None:
        """math='percentile' with percentile_value is accepted."""
        q = InsightsQuery(events=["Login"], math="percentile", percentile_value=95)
        assert q.percentile_value == 95

    def test_valid_date_range_accepted(self) -> None:
        """from_date + to_date is accepted."""
        q = InsightsQuery(
            events=["Login"], from_date="2025-01-01", to_date="2025-01-31"
        )
        assert q.from_date == "2025-01-01"

    def test_lone_from_date_accepted_insights(self) -> None:
        """from_date alone is valid for insights (builder fills today)."""
        q = InsightsQuery(events=["Login"], from_date="2025-01-01")
        assert q.from_date == "2025-01-01"
        assert q.to_date is None

    def test_lone_from_date_accepted_funnel(self) -> None:
        """from_date alone is valid for funnels (builder fills today)."""
        q = FunnelQuery(steps=["A", "B"], from_date="2025-01-01")
        assert q.from_date == "2025-01-01"

    def test_lone_from_date_accepted_retention(self) -> None:
        """from_date alone is valid for retention (builder fills today)."""
        q = RetentionQuery(
            born_event="Signup", return_event="Login", from_date="2025-01-01"
        )
        assert q.from_date == "2025-01-01"

    def test_lone_from_date_accepted_flow(self) -> None:
        """from_date alone is valid for flow — the builder fills today.

        Parity with the other three models and with main, whose flow
        path pre-filled today's date for the missing to_date.
        """
        q = FlowQuery(event="Login", from_date="2025-01-01")
        assert q.from_date == "2025-01-01"

    @pytest.mark.parametrize(
        "make_query",
        [
            lambda: InsightsQuery(events=["Login"], to_date="2025-01-31"),
            lambda: FunnelQuery(steps=["A", "B"], to_date="2025-01-31"),
            lambda: RetentionQuery(
                born_event="Signup", return_event="Login", to_date="2025-01-31"
            ),
            lambda: FlowQuery(event="Login", to_date="2025-01-31"),
        ],
        ids=["insights", "funnel", "retention", "flow"],
    )
    def test_to_date_without_from_rejected_all_models(
        self, make_query: Callable[[], object]
    ) -> None:
        """to_date without from_date is rejected by every model (base check)."""
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError, match="to_date requires from_date"):
            make_query()


# =============================================================================
# Hashability (S3)
# =============================================================================


class TestHashability:
    """Document frozen-but-unhashable behavior."""

    def test_metric_is_hashable(self) -> None:
        """Metric (pydantic_dataclass) is hashable."""
        h = hash(Metric("Login"))
        assert isinstance(h, int)

    def test_insights_query_is_not_hashable(self) -> None:
        """InsightsQuery (BaseModel with list) is not hashable."""
        with pytest.raises(TypeError):
            hash(InsightsQuery(events=["Login"]))


# =============================================================================
# Filter dict construction (I2)
# =============================================================================


class TestFilterDictConstruction:
    """Filter supports dict construction via validation aliases."""

    _adapter: ClassVar[TypeAdapter[Filter]]

    @classmethod
    def setup_class(cls) -> None:
        """Create a shared TypeAdapter for Filter."""
        cls._adapter = TypeAdapter(Filter)

    def test_equals_dict(self) -> None:
        """Dict with 'equals' produces a Filter with wrapped value."""
        f = self._adapter.validate_python(
            {"property": "country", "operator": "equals", "value": "US"}
        )
        assert isinstance(f, Filter)
        assert f._value == ["US"]
        assert f._property_type == "string"

    def test_numeric_operator_dict(self) -> None:
        """Dict with numeric operator infers property_type='number'."""
        f = self._adapter.validate_python(
            {"property": "amount", "operator": "is greater than", "value": 50}
        )
        assert isinstance(f, Filter)
        assert f._property_type == "number"

    def test_is_set_no_value(self) -> None:
        """Dict with 'is set' needs no value field."""
        f = self._adapter.validate_python({"property": "email", "operator": "is set"})
        assert isinstance(f, Filter)
        assert f._value is None

    def test_between_operator_dict(self) -> None:
        """Dict with 'is between' accepts a two-element list."""
        f = self._adapter.validate_python(
            {"property": "amount", "operator": "is between", "value": [10, 50]}
        )
        assert isinstance(f, Filter)
        assert f._property_type == "number"
        assert f._value == [10, 50]

    def test_equals_non_string_scalar_rejected(self) -> None:
        """equals with a bare non-string scalar is rejected.

        The classmethod contract is ``str | list[str]``; passing the
        scalar through emitted a bare ``filterValue: 5`` on the wire
        where every classmethod-built equals emits a list.
        """
        with pytest.raises(ValidationError, match="string or a list"):
            self._adapter.validate_python(
                {"property": "plan_tier", "operator": "equals", "value": 5}
            )

    def test_not_equals_bool_scalar_rejected(self) -> None:
        """does not equal with a bare bool is rejected like other scalars."""
        with pytest.raises(ValidationError, match="string or a list"):
            self._adapter.validate_python(
                {"property": "active", "operator": "does not equal", "value": True}
            )

    def test_equals_list_elements_must_be_strings(self) -> None:
        """String-typed equals rejects a homogeneous non-string list."""
        with pytest.raises(ValidationError, match="list of strings"):
            self._adapter.validate_python(
                {"property": "plan_tier", "operator": "equals", "value": [5, 6]}
            )

    def test_equals_mixed_list_rejected_by_field_typing(self) -> None:
        """Mixed-type lists match no _value union arm and are rejected."""
        with pytest.raises(ValidationError):
            self._adapter.validate_python(
                {"property": "plan_tier", "operator": "equals", "value": [5, "a"]}
            )

    def test_is_between_requires_numeric_elements(self) -> None:
        """is between requires numeric endpoints (Filter.between parity).

        String endpoints built a self-contradictory wire entry
        (filterType "number" with string operands).
        """
        with pytest.raises(ValidationError, match="numeric"):
            self._adapter.validate_python(
                {"property": "amount", "operator": "is between", "value": ["a", "b"]}
            )

    def test_is_between_mixed_float_int_accepted(self) -> None:
        """is between accepts mixed int/float endpoints like Filter.between."""
        f = self._adapter.validate_python(
            {"property": "amount", "operator": "is between", "value": [1, 2.5]}
        )
        assert f._value == [1, 2.5]
        assert f._property_type == "number"

    def test_equivalence_with_classmethod(self) -> None:
        """Dict-constructed Filter matches classmethod-constructed Filter."""
        f_dict = self._adapter.validate_python(
            {"property": "country", "operator": "equals", "value": "US"}
        )
        f_cls = Filter.equals("country", "US")
        assert f_dict._property == f_cls._property
        assert f_dict._operator == f_cls._operator
        assert f_dict._value == f_cls._value
        assert f_dict._property_type == f_cls._property_type

    def test_in_insights_query(self) -> None:
        """InsightsQuery accepts dict-constructed Filter in where list."""
        f = self._adapter.validate_python(
            {"property": "country", "operator": "equals", "value": "US"}
        )
        q = InsightsQuery(events=["Login"], where=[f])
        assert q.where is not None
        assert len(q.where) == 1

    def test_invalid_operator_rejected(self) -> None:
        """Unknown operator string is rejected by FilterOperator literal."""
        with pytest.raises(ValidationError):
            self._adapter.validate_python(
                {"property": "x", "operator": "bogus", "value": "y"}
            )

    def test_relative_date_default_unit(self) -> None:
        """Relative-date operators default date_unit to 'day'."""
        f = self._adapter.validate_python(
            {"property": "created", "operator": "was in the", "value": 7}
        )
        assert f._date_unit == "day"
        assert f._property_type == "datetime"

    def test_relative_date_explicit_unit(self) -> None:
        """Explicit date_unit overrides the default."""
        f = self._adapter.validate_python(
            {
                "property": "created",
                "operator": "was in the",
                "value": 2,
                "date_unit": "week",
            }
        )
        assert f._date_unit == "week"

    def test_boolean_type_inference(self) -> None:
        """Boolean operators infer property_type='boolean'."""
        f = self._adapter.validate_python({"property": "active", "operator": "true"})
        assert f._property_type == "boolean"


class TestFilterDictDateValidation:
    """Dict-constructed Filters validate dates exactly like the classmethods.

    ``__post_init__`` must replicate the classmethods' date validation
    (``_validate_date``, from<=to ordering, quantity > 0) so the
    dict/LLM construction path cannot produce wire payloads the
    classmethod path would reject.
    """

    _adapter: ClassVar[TypeAdapter[Filter]]

    @classmethod
    def setup_class(cls) -> None:
        """Create a shared TypeAdapter for Filter."""
        cls._adapter = TypeAdapter(Filter)

    def test_was_on_rejects_malformed_date(self) -> None:
        """'was on' with a non-date string is rejected (classmethod parity)."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            self._adapter.validate_python(
                {"property": "$time", "operator": "was on", "value": "not-a-date"}
            )

    def test_was_on_rejects_invalid_calendar_date(self) -> None:
        """'was on' with an impossible calendar date is rejected."""
        with pytest.raises(ValueError, match="not a valid calendar date"):
            self._adapter.validate_python(
                {"property": "$time", "operator": "was on", "value": "2024-02-30"}
            )

    def test_was_on_rejects_non_string_value(self) -> None:
        """'was on' with a numeric value is rejected."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            self._adapter.validate_python(
                {"property": "$time", "operator": "was on", "value": 20240101}
            )

    @pytest.mark.parametrize("operator", ["was not on", "was before", "was since"])
    def test_single_date_operators_reject_malformed_date(self, operator: str) -> None:
        """All single-date operators validate their date value."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            self._adapter.validate_python(
                {"property": "created", "operator": operator, "value": "01/01/2024"}
            )

    def test_was_on_valid_date_matches_classmethod(self) -> None:
        """'was on' with a valid date matches Filter.on()."""
        f_dict = self._adapter.validate_python(
            {"property": "created", "operator": "was on", "value": "2024-06-01"}
        )
        f_cls = Filter.on("created", "2024-06-01")
        assert f_dict._value == f_cls._value
        assert f_dict._property_type == f_cls._property_type

    def test_was_between_rejects_reversed_range(self) -> None:
        """'was between' with from > to is rejected (classmethod parity)."""
        with pytest.raises(ValueError, match="from_date must be before to_date"):
            self._adapter.validate_python(
                {
                    "property": "created",
                    "operator": "was between",
                    "value": ["2024-06-30", "2024-01-01"],
                }
            )

    def test_was_not_between_rejects_reversed_range(self) -> None:
        """'was not between' with from > to is rejected."""
        with pytest.raises(ValueError, match="from_date must be before to_date"):
            self._adapter.validate_python(
                {
                    "property": "created",
                    "operator": "was not between",
                    "value": ["2024-06-30", "2024-01-01"],
                }
            )

    def test_was_between_rejects_malformed_dates(self) -> None:
        """'was between' validates both elements as dates."""
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            self._adapter.validate_python(
                {
                    "property": "created",
                    "operator": "was between",
                    "value": ["2024-01-01", "garbage"],
                }
            )

    def test_was_between_valid_range_matches_classmethod(self) -> None:
        """'was between' with a valid range matches Filter.date_between()."""
        f_dict = self._adapter.validate_python(
            {
                "property": "created",
                "operator": "was between",
                "value": ["2024-01-01", "2024-06-30"],
            }
        )
        f_cls = Filter.date_between("created", "2024-01-01", "2024-06-30")
        assert f_dict._value == f_cls._value
        assert f_dict._property_type == f_cls._property_type

    def test_numeric_between_unaffected_by_date_checks(self) -> None:
        """Numeric 'is between' still accepts descending numbers (not dates)."""
        f = self._adapter.validate_python(
            {"property": "amount", "operator": "is between", "value": [10, 50]}
        )
        assert f._value == [10, 50]

    @pytest.mark.parametrize(
        "operator", ["was in the", "was not in the", "was in the next"]
    )
    def test_relative_date_rejects_zero_quantity(self, operator: str) -> None:
        """Relative-date operators reject quantity == 0 (classmethod parity)."""
        with pytest.raises(ValueError, match="positive integer"):
            self._adapter.validate_python(
                {"property": "created", "operator": operator, "value": 0}
            )

    def test_relative_date_rejects_negative_quantity(self) -> None:
        """Relative-date operators reject negative quantities."""
        with pytest.raises(ValueError, match="positive integer"):
            self._adapter.validate_python(
                {"property": "created", "operator": "was in the", "value": -3}
            )

    def test_relative_date_rejects_non_int_quantity(self) -> None:
        """Relative-date operators reject non-integer quantities."""
        with pytest.raises(ValueError, match="positive integer"):
            self._adapter.validate_python(
                {"property": "created", "operator": "was in the", "value": "soon"}
            )

    def test_relative_date_valid_matches_classmethod(self) -> None:
        """'was in the' with valid quantity matches Filter.in_the_last()."""
        f_dict = self._adapter.validate_python(
            {
                "property": "created",
                "operator": "was in the",
                "value": 7,
                "date_unit": "week",
            }
        )
        f_cls = Filter.in_the_last("created", 7, "week")
        assert f_dict._value == f_cls._value
        assert f_dict._date_unit == f_cls._date_unit


# =============================================================================
# Wrap-validator error grammar: package paths and stable codes
# =============================================================================


class TestWrapValidationErrorGrammar:
    """Model-construction errors use the package path grammar and codes.

    ``_BaseQuery._wrap_validation`` routes pydantic errors through the
    same translator as ``validate_with_pydantic``, so paths use
    bracketed indices (``where[0].bogus``), union member class names
    never leak into paths, and codes are the stable ``B*``/``S*``
    family rather than raw pydantic type strings.
    """

    _BAD_WHERE_INPUT: ClassVar[dict[str, object]] = {
        "events": ["Login"],
        "where": [
            {
                "property": "country",
                "operator": "equals",
                "value": ["US"],
                "bogus": 1,
            }
        ],
    }

    def test_extra_key_path_uses_bracketed_indices(self) -> None:
        """Extra-key errors render where[0].bogus, not where.0.Tag.bogus."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(self._BAD_WHERE_INPUT)
        paths = [e.path for e in exc_info.value.errors]
        assert any(p == "where[0].bogus" for p in paths)
        joined = " ".join(paths)
        assert "FrequencyFilter" not in joined
        assert "Filter." not in joined
        assert ".0." not in joined

    def test_extra_key_maps_to_stable_code(self) -> None:
        """Extra keys map to S3_UNKNOWN_FIELD, not a raw pydantic type."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(self._BAD_WHERE_INPUT)
        err = next(e for e in exc_info.value.errors if e.path == "where[0].bogus")
        assert err.code == "S3_UNKNOWN_FIELD"

    def test_min_length_maps_to_stable_code(self) -> None:
        """List min_length failures map to B0_MIN_LENGTH."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery(events=[])
        err = next(e for e in exc_info.value.errors if e.path == "events")
        assert err.code == "B0_MIN_LENGTH"

    def test_literal_error_maps_to_stable_code(self) -> None:
        """Bad Literal values map to B0_INVALID_LITERAL."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate({"events": ["Login"], "unit": "bogus"})
        err = next(e for e in exc_info.value.errors if e.path == "unit")
        assert err.code == "B0_INVALID_LITERAL"

    def test_numeric_range_maps_to_stable_code(self) -> None:
        """Field range failures (ge/le) map to B0_OUT_OF_RANGE."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            FunnelQuery(steps=["A", "B"], conversion_window=-1)
        err = next(e for e in exc_info.value.errors if e.path == "conversion_window")
        assert err.code == "B0_OUT_OF_RANGE"


class TestCrossFieldErrorCodes:
    """Model-layer cross-field rules reuse the Layer-1 V* codes.

    ``to_date``-without-``from_date`` and percentile-without-value were
    validated on main as V9_TO_REQUIRES_FROM and
    V26_PERCENTILE_REQUIRES_VALUE; the model layer surfaces the same
    stable codes (via shared predicates in ``_internal.validation``)
    instead of inventing a second vocabulary.
    """

    @pytest.mark.parametrize(
        "make_query",
        [
            pytest.param(
                lambda: InsightsQuery(events=["Login"], to_date="2025-01-31"),
                id="insights",
            ),
            pytest.param(
                lambda: FunnelQuery(steps=["A", "B"], to_date="2025-01-31"),
                id="funnel",
            ),
            pytest.param(
                lambda: RetentionQuery(
                    born_event="Signup",
                    return_event="Login",
                    to_date="2025-01-31",
                ),
                id="retention",
            ),
            pytest.param(
                lambda: FlowQuery(event="Login", to_date="2025-01-31"),
                id="flow",
            ),
        ],
    )
    def test_lone_to_date_uses_v9_code(self, make_query: Callable[[], object]) -> None:
        """to_date without from_date carries V9_TO_REQUIRES_FROM."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            make_query()
        err = next(e for e in exc_info.value.errors if e.path == "to_date")
        assert err.code == "V9_TO_REQUIRES_FROM"

    def test_percentile_without_value_uses_v26_code(self) -> None:
        """math='percentile' without percentile_value carries V26."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery(events=["Login"], math="percentile")
        err = next(e for e in exc_info.value.errors if e.path == "percentile_value")
        assert err.code == "V26_PERCENTILE_REQUIRES_VALUE"

    def test_percentile_with_metric_events_not_required(self) -> None:
        """Metric events carry their own math — no V26 for them."""
        q = InsightsQuery(events=[Metric("Login")], math="percentile")
        assert q.math == "percentile"


class TestStrictScalarCoercionRejected:
    """Bool/float/str inputs where an int is expected are rejected.

    Pydantic's lax defaults coerced ``True``/``1.0``/``"2"`` into
    integers BEFORE the Workspace Layer 0.5/1 validators ran, so an
    LLM typo (``conversion_window=True``) silently built and ran a
    different query. Strict fields restore main's behavior: the model
    raises ``BookmarkValidationError`` (translated from pydantic's
    strict-mode error, code ``B0_WRONG_TYPE``) at construction time —
    the same structured error type the ``build_*_params`` contract
    documents.

    Regression tests for finding
    ``pydantic-coercion-bypasses-strict-query-validation``.
    """

    def test_funnel_conversion_window_bool_rejected(self) -> None:
        """FunnelQuery(conversion_window=True) must not become 1."""
        with pytest.raises(BookmarkValidationError, match="conversion_window"):
            FunnelQuery(steps=["Signup", "Purchase"], conversion_window=True)

    def test_funnel_conversion_window_float_rejected(self) -> None:
        """FunnelQuery(conversion_window=1.0) must not become 1."""
        with pytest.raises(BookmarkValidationError, match="conversion_window"):
            FunnelQuery(steps=["Signup", "Purchase"], conversion_window=1.0)  # type: ignore[arg-type]

    def test_funnel_conversion_window_str_rejected(self) -> None:
        """Dict-path conversion_window='7' must not become 7."""
        with pytest.raises(BookmarkValidationError, match="conversion_window"):
            FunnelQuery.model_validate(
                {"steps": ["Signup", "Purchase"], "conversion_window": "7"}
            )

    def test_funnel_conversion_window_error_code(self) -> None:
        """Strict-mode failures carry the stable B0_WRONG_TYPE code."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            FunnelQuery(steps=["Signup", "Purchase"], conversion_window=True)
        err = next(e for e in exc_info.value.errors if e.path == "conversion_window")
        assert err.code == "B0_WRONG_TYPE"

    def test_flow_forward_bool_rejected(self) -> None:
        """FlowQuery(forward=True) must not become forward=1."""
        with pytest.raises(BookmarkValidationError, match="forward"):
            FlowQuery(event="Login", forward=True)

    def test_flow_reverse_float_rejected(self) -> None:
        """FlowQuery(reverse=1.0) must not become reverse=1."""
        with pytest.raises(BookmarkValidationError, match="reverse"):
            FlowQuery(event="Login", reverse=1.0)  # type: ignore[arg-type]

    def test_flow_forward_str_rejected(self) -> None:
        """Dict-path forward='3' must not become 3."""
        with pytest.raises(BookmarkValidationError, match="forward"):
            FlowQuery.model_validate({"event": "Login", "forward": "3"})

    @pytest.mark.parametrize(
        "make_query",
        [
            pytest.param(
                lambda: InsightsQuery(events=["Login"], data_group_id=True),
                id="insights",
            ),
            pytest.param(
                lambda: FunnelQuery(steps=["A", "B"], data_group_id=True),
                id="funnel",
            ),
            pytest.param(
                lambda: RetentionQuery(
                    born_event="Signup",
                    return_event="Login",
                    data_group_id=True,
                ),
                id="retention",
            ),
            pytest.param(
                lambda: FlowQuery(event="Login", data_group_id=True),
                id="flow",
            ),
        ],
    )
    def test_data_group_id_bool_rejected_all_models(
        self, make_query: Callable[[], object]
    ) -> None:
        """data_group_id=True must not become group ID 1 on any model."""
        with pytest.raises(BookmarkValidationError, match="data_group_id"):
            make_query()

    def test_data_group_id_str_rejected(self) -> None:
        """Dict-path data_group_id='1' must not become 1."""
        with pytest.raises(BookmarkValidationError, match="data_group_id"):
            InsightsQuery.model_validate({"events": ["Login"], "data_group_id": "1"})

    def test_retention_bucket_sizes_str_items_rejected(self) -> None:
        """bucket_sizes=['2'] must not become [2]."""
        with pytest.raises(BookmarkValidationError, match="bucket_sizes"):
            RetentionQuery(
                born_event="Signup",
                return_event="Login",
                bucket_sizes=["2"],
            )

    def test_retention_bucket_sizes_bool_items_rejected(self) -> None:
        """bucket_sizes=[True] must not become [1]."""
        with pytest.raises(BookmarkValidationError, match="bucket_sizes"):
            RetentionQuery(
                born_event="Signup",
                return_event="Login",
                bucket_sizes=[True],
            )

    def test_last_bool_rejected(self) -> None:
        """last=True must not become last=1 (shared _BaseQuery field)."""
        with pytest.raises(BookmarkValidationError, match="last"):
            InsightsQuery(events=["Login"], last=True)

    def test_cumulative_int_rejected(self) -> None:
        """cumulative=1 must not become True (strict bool)."""
        with pytest.raises(BookmarkValidationError, match="cumulative"):
            InsightsQuery(events=["Login"], cumulative=1)  # type: ignore[arg-type]

    def test_nested_flow_step_forward_bool_rejected(self) -> None:
        """Nested FlowStep dict with forward=True is rejected."""
        with pytest.raises(BookmarkValidationError, match="forward"):
            FlowQuery.model_validate({"event": {"event": "Login", "forward": True}})

    def test_nested_flow_step_reverse_float_rejected(self) -> None:
        """Nested FlowStep dict with reverse=1.0 is rejected."""
        with pytest.raises(BookmarkValidationError, match="reverse"):
            FlowQuery.model_validate({"event": {"event": "Login", "reverse": 1.0}})

    def test_flow_step_direct_construction_bool_rejected(self) -> None:
        """FlowStep(forward=True) is rejected at dataclass construction."""
        with pytest.raises(ValidationError):
            FlowStep("Login", forward=True)

    def test_flow_step_direct_construction_float_rejected(self) -> None:
        """FlowStep(reverse=2.0) is rejected at dataclass construction."""
        with pytest.raises(ValidationError):
            FlowStep("Login", reverse=2.0)  # type: ignore[arg-type]

    def test_valid_ints_still_accepted(self) -> None:
        """Genuine integers still construct on every strict field."""
        fq = FunnelQuery(steps=["A", "B"], conversion_window=7)
        assert fq.conversion_window == 7
        fl = FlowQuery(event="Login", forward=5, reverse=2, data_group_id=1)
        assert (fl.forward, fl.reverse, fl.data_group_id) == (5, 2, 1)
        rq = RetentionQuery(
            born_event="Signup", return_event="Login", bucket_sizes=[1, 3, 7]
        )
        assert rq.bucket_sizes == [1, 3, 7]
        step = FlowStep("Login", forward=4, reverse=1)
        assert (step.forward, step.reverse) == (4, 1)


class TestNestedComponentStrictCoercion:
    """Nested building blocks reject bool/float/str coercion into int fields.

    Regression tests for finding
    ``nested-component-int-bool-fields-still-lax-coerce``: commit
    10f8411 made the four query models (and ``FlowStep``) strict, but
    every OTHER component dataclass reachable from them still
    lax-coerced ``True``/``"5"`` into integers on the dict/LLM path —
    e.g. ``cohort=true`` silently queried saved cohort 1 and
    ``bucket_size=true`` silently bucketed by 1. The same strict
    treatment must cover ``Metric.percentile_value``,
    ``GroupBy.bucket_size/bucket_min/bucket_max``,
    ``Exclusion.from_step/to_step``,
    ``FrequencyFilter.value/date_range_value``,
    ``FrequencyBreakdown.bucket_size/bucket_min/bucket_max``,
    ``CohortMetric.cohort``, and
    ``CohortBreakdown.cohort/include_negated``.
    """

    def test_group_by_bucket_size_bool_rejected_dict_path(self) -> None:
        """InsightsQuery group_by bucket_size=True must not become 1."""
        with pytest.raises(BookmarkValidationError, match="bucket_size"):
            InsightsQuery.model_validate(
                {
                    "events": ["x"],
                    "group_by": [
                        {
                            "property": "p",
                            "property_type": "number",
                            "bucket_size": True,
                        }
                    ],
                }
            )

    def test_group_by_bucket_size_str_rejected(self) -> None:
        """GroupBy dict with bucket_size='5' must not become 5."""
        with pytest.raises(ValidationError, match="bucket_size"):
            TypeAdapter(GroupBy).validate_python(
                {"property": "p", "property_type": "number", "bucket_size": "5"}
            )

    def test_group_by_bucket_min_bool_rejected(self) -> None:
        """GroupBy dict with bucket_min=True must not become 1."""
        with pytest.raises(ValidationError, match="bucket_min"):
            TypeAdapter(GroupBy).validate_python(
                {"property": "p", "property_type": "number", "bucket_min": True}
            )

    def test_group_by_bucket_max_str_rejected(self) -> None:
        """GroupBy dict with bucket_max='10' must not become 10."""
        with pytest.raises(ValidationError, match="bucket_max"):
            TypeAdapter(GroupBy).validate_python(
                {"property": "p", "property_type": "number", "bucket_max": "10"}
            )

    def test_exclusion_from_step_bool_rejected_dict_path(self) -> None:
        """FunnelQuery exclusions from_step=True must not become 1."""
        with pytest.raises(BookmarkValidationError, match="from_step"):
            FunnelQuery.model_validate(
                {
                    "steps": ["a", "b"],
                    "exclusions": [{"event": "e", "from_step": True}],
                }
            )

    def test_exclusion_to_step_str_rejected(self) -> None:
        """Exclusion dict with to_step='2' must not become 2."""
        with pytest.raises(ValidationError, match="to_step"):
            TypeAdapter(Exclusion).validate_python({"event": "e", "to_step": "2"})

    def test_cohort_breakdown_cohort_bool_rejected(self) -> None:
        """CohortBreakdown cohort=True must not become cohort ID 1."""
        with pytest.raises(ValidationError):
            TypeAdapter(CohortBreakdown).validate_python({"cohort": True})

    def test_cohort_breakdown_include_negated_int_rejected(self) -> None:
        """CohortBreakdown include_negated=1 must not become True."""
        with pytest.raises(ValidationError, match="include_negated"):
            TypeAdapter(CohortBreakdown).validate_python(
                {"cohort": 123, "include_negated": 1}
            )

    def test_cohort_metric_cohort_str_rejected(self) -> None:
        """CohortMetric cohort='5' must not become cohort ID 5."""
        with pytest.raises(ValidationError):
            TypeAdapter(CohortMetric).validate_python({"cohort": "5"})

    def test_metric_percentile_value_bool_rejected(self) -> None:
        """Metric percentile_value=True must not become 1."""
        with pytest.raises(ValidationError, match="percentile_value"):
            TypeAdapter(Metric).validate_python(
                {
                    "event": "x",
                    "math": "percentile",
                    "property": "amount",
                    "percentile_value": True,
                }
            )

    def test_metric_percentile_value_str_rejected(self) -> None:
        """Metric percentile_value='95' must not become 95."""
        with pytest.raises(ValidationError, match="percentile_value"):
            TypeAdapter(Metric).validate_python(
                {
                    "event": "x",
                    "math": "percentile",
                    "property": "amount",
                    "percentile_value": "95",
                }
            )

    def test_frequency_filter_value_bool_rejected(self) -> None:
        """FrequencyFilter value=True must not become threshold 1."""
        with pytest.raises(ValidationError, match="value"):
            TypeAdapter(FrequencyFilter).validate_python({"event": "x", "value": True})

    def test_frequency_filter_value_str_rejected(self) -> None:
        """FrequencyFilter value='5' must not become threshold 5."""
        with pytest.raises(ValidationError, match="value"):
            TypeAdapter(FrequencyFilter).validate_python({"event": "x", "value": "5"})

    def test_frequency_filter_date_range_value_str_rejected(self) -> None:
        """FrequencyFilter date_range_value='30' must not become 30."""
        with pytest.raises(ValidationError, match="date_range_value"):
            TypeAdapter(FrequencyFilter).validate_python(
                {
                    "event": "x",
                    "value": 5,
                    "date_range_value": "30",
                    "date_range_unit": "day",
                }
            )

    def test_frequency_breakdown_bucket_size_bool_rejected(self) -> None:
        """FrequencyBreakdown bucket_size=True must not become 1."""
        with pytest.raises(ValidationError, match="bucket_size"):
            TypeAdapter(FrequencyBreakdown).validate_python(
                {"event": "x", "bucket_size": True}
            )

    def test_frequency_breakdown_bucket_min_str_rejected(self) -> None:
        """FrequencyBreakdown bucket_min='0' must not become 0."""
        with pytest.raises(ValidationError, match="bucket_min"):
            TypeAdapter(FrequencyBreakdown).validate_python(
                {"event": "x", "bucket_min": "0"}
            )

    def test_frequency_breakdown_bucket_max_bool_rejected(self) -> None:
        """FrequencyBreakdown bucket_max=True must not become 1."""
        with pytest.raises(ValidationError, match="bucket_max"):
            TypeAdapter(FrequencyBreakdown).validate_python(
                {"event": "x", "bucket_max": True}
            )

    def test_valid_component_values_still_accepted(self) -> None:
        """Genuine ints/floats still construct on every strict field."""
        g = GroupBy(
            "revenue",
            property_type="number",
            bucket_size=50.5,
            bucket_min=0,
            bucket_max=500,
        )
        assert (g.bucket_size, g.bucket_min, g.bucket_max) == (50.5, 0, 500)
        ex = Exclusion("e", from_step=1, to_step=2)
        assert (ex.from_step, ex.to_step) == (1, 2)
        cb = CohortBreakdown(123, include_negated=False)
        assert (cb.cohort, cb.include_negated) == (123, False)
        cm = CohortMetric(123)
        assert cm.cohort == 123
        m = Metric("x", math="percentile", property="amount", percentile_value=95.5)
        assert m.percentile_value == 95.5
        ff = FrequencyFilter("x", value=2.5, date_range_value=30, date_range_unit="day")
        assert (ff.value, ff.date_range_value) == (2.5, 30)
        fb = FrequencyBreakdown("x", bucket_size=5, bucket_min=0, bucket_max=50)
        assert (fb.bucket_size, fb.bucket_min, fb.bucket_max) == (5, 0, 50)


class TestFilterOperatorValueShape:
    """Filter enforces value shape per operator family at construction.

    Regression tests for finding
    ``filter-operator-value-shape-not-enforced``: numeric operators
    must carry numeric scalars, string operators must carry strings,
    and required values may not be omitted — otherwise the dict/LLM
    path emits self-contradictory wire entries (``filterType="number"``
    with ``filterValue="oops"``).
    """

    _adapter: ClassVar[TypeAdapter[Filter]]

    @classmethod
    def setup_class(cls) -> None:
        """Create a shared TypeAdapter for Filter."""
        cls._adapter = TypeAdapter(Filter)

    def test_greater_than_string_value_rejected(self) -> None:
        """'is greater than' with value 'oops' is rejected."""
        with pytest.raises(ValidationError, match="numeric"):
            self._adapter.validate_python(
                {"property": "amount", "operator": "is greater than", "value": "oops"}
            )

    @pytest.mark.parametrize(
        "operator", ["is greater than", "is less than", "is at least", "is at most"]
    )
    def test_numeric_operators_reject_string_values(self, operator: str) -> None:
        """Every scalar numeric operator rejects a non-numeric value."""
        with pytest.raises(ValidationError, match="numeric"):
            self._adapter.validate_python(
                {"property": "amount", "operator": operator, "value": "oops"}
            )

    def test_numeric_operator_rejects_bool_value(self) -> None:
        """'is less than' with a bool value is rejected (bool is not numeric)."""
        with pytest.raises(ValidationError, match="numeric"):
            self._adapter.validate_python(
                {"property": "amount", "operator": "is less than", "value": True}
            )

    @pytest.mark.parametrize(
        "operator", ["is greater than", "is less than", "is at least", "is at most"]
    )
    def test_numeric_operators_reject_omitted_value(self, operator: str) -> None:
        """Scalar numeric operators require a value."""
        with pytest.raises(ValidationError, match="numeric"):
            self._adapter.validate_python({"property": "amount", "operator": operator})

    @pytest.mark.parametrize(
        "operator", ["contains", "does not contain", "starts with", "ends with"]
    )
    def test_string_operators_reject_numeric_values(self, operator: str) -> None:
        """String operators reject int/float values."""
        with pytest.raises(ValidationError, match="string"):
            self._adapter.validate_python(
                {"property": "name", "operator": operator, "value": 123}
            )

    def test_starts_with_float_value_rejected(self) -> None:
        """'starts with' with a float value is rejected."""
        with pytest.raises(ValidationError, match="string"):
            self._adapter.validate_python(
                {"property": "url", "operator": "starts with", "value": 1.5}
            )

    @pytest.mark.parametrize(
        "operator", ["contains", "does not contain", "starts with", "ends with"]
    )
    def test_string_operators_reject_omitted_value(self, operator: str) -> None:
        """String operators require a value."""
        with pytest.raises(ValidationError, match="string"):
            self._adapter.validate_python({"property": "name", "operator": operator})

    def test_contains_list_value_rejected(self) -> None:
        """'contains' with a list value is rejected (contract is str)."""
        with pytest.raises(ValidationError, match="string"):
            self._adapter.validate_python(
                {"property": "name", "operator": "contains", "value": ["a", "b"]}
            )

    def test_is_between_list_position_bools_rejected(self) -> None:
        """'is between' with [True, False] must not coerce to [1, 0].

        Regression for finding ``filter-list-position-bools-still-coerce``:
        booleans INSIDE list values hit pydantic's lax ``list[int | float]``
        arm and coerced to 0/1 before ``__post_init__`` ran.
        """
        with pytest.raises(ValidationError, match="numeric"):
            self._adapter.validate_python(
                {"property": "amount", "operator": "is between", "value": [True, False]}
            )

    def test_not_between_list_position_bool_rejected(self) -> None:
        """'not between' with a boolean endpoint is rejected."""
        with pytest.raises(ValidationError, match="numeric"):
            self._adapter.validate_python(
                {"property": "amount", "operator": "not between", "value": [1, True]}
            )

    def test_between_classmethod_bool_endpoint_rejected(self) -> None:
        """Filter.between('amount', True, 100) must not become [1, 100]."""
        with pytest.raises(ValidationError, match="numeric"):
            Filter.between("amount", True, 100)

    def test_equals_number_ptype_bool_list_rejected(self) -> None:
        """equals with property_type='number' and value [True] is rejected."""
        with pytest.raises(ValidationError):
            self._adapter.validate_python(
                {
                    "property": "amount",
                    "operator": "equals",
                    "value": [True],
                    "property_type": "number",
                }
            )

    def test_equals_bool_list_error_reports_original_input(self) -> None:
        """The equals bool-list error reports [True], not the coerced [1]."""
        with pytest.raises(ValidationError, match=r"\[True\]") as exc_info:
            self._adapter.validate_python(
                {"property": "plan", "operator": "equals", "value": [True]}
            )
        assert "[1]" not in str(exc_info.value)

    def test_string_operator_valid_value_matches_classmethod(self) -> None:
        """'contains' with a string still matches Filter.contains()."""
        f_dict = self._adapter.validate_python(
            {"property": "name", "operator": "contains", "value": "john"}
        )
        f_cls = Filter.contains("name", "john")
        assert f_dict._value == f_cls._value
        assert f_dict._property_type == f_cls._property_type

    def test_numeric_operator_valid_value_matches_classmethod(self) -> None:
        """'is greater than' with a number still matches Filter.greater_than()."""
        f_dict = self._adapter.validate_python(
            {"property": "amount", "operator": "is greater than", "value": 50}
        )
        f_cls = Filter.greater_than("amount", 50)
        assert f_dict._value == f_cls._value
        assert f_dict._property_type == f_cls._property_type

    def test_insights_model_path_raises_bookmark_error(self) -> None:
        """The Insights model path surfaces BookmarkValidationError.

        On the PR head this silently emitted filterType="number" with
        filterValue="oops".
        """
        with pytest.raises(BookmarkValidationError, match="numeric"):
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "where": [
                        {
                            "property": "amount",
                            "operator": "is greater than",
                            "value": "oops",
                        }
                    ],
                }
            )

    def test_flow_model_path_raises_bookmark_error(self) -> None:
        """The Flow model path surfaces BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError, match="string"):
            FlowQuery.model_validate(
                {
                    "event": "Login",
                    "where": [{"property": "name", "operator": "contains", "value": 7}],
                }
            )


class TestFilterCohortPropertyGuard:
    """Hand-rolled '$cohorts' filters are rejected at construction.

    Regression tests for finding
    ``filter-operator-value-shape-not-enforced``: the dict repro
    ``{"property": "$cohorts", "operator": "contains", "value": "123"}``
    previously constructed fine, then the Flow build path crashed with
    a raw internal ``RuntimeError`` while the Insights path silently
    emitted an ordinary string filter. Cohort membership must go
    through ``Filter.in_cohort()`` / ``Filter.not_in_cohort()``, which
    build the internal wire structure the builders require.
    """

    _adapter: ClassVar[TypeAdapter[Filter]]

    @classmethod
    def setup_class(cls) -> None:
        """Create a shared TypeAdapter for Filter."""
        cls._adapter = TypeAdapter(Filter)

    _COHORT_REPRO: ClassVar[dict[str, object]] = {
        "property": "$cohorts",
        "operator": "contains",
        "value": "123",
    }

    def test_hand_rolled_cohorts_contains_rejected(self) -> None:
        """The exact dict repro is rejected at Filter validation."""
        with pytest.raises(ValidationError, match="in_cohort"):
            self._adapter.validate_python(self._COHORT_REPRO)

    def test_hand_rolled_cohorts_equals_rejected(self) -> None:
        """'$cohorts' with a non-cohort operator is rejected."""
        with pytest.raises(ValidationError, match="in_cohort"):
            self._adapter.validate_python(
                {"property": "$cohorts", "operator": "equals", "value": "123"}
            )

    def test_hand_rolled_cohorts_malformed_wire_shape_rejected(self) -> None:
        """A list-of-dicts value missing the 'cohort' key is rejected."""
        with pytest.raises(ValidationError, match="in_cohort"):
            self._adapter.validate_python(
                {
                    "property": "$cohorts",
                    "operator": "contains",
                    "value": [{"not_cohort": 1}],
                }
            )

    def test_in_cohort_constructor_still_works(self) -> None:
        """Filter.in_cohort() output passes the new guard."""
        f = Filter.in_cohort(123, "Power Users")
        assert f._property == "$cohorts"
        assert f._operator == "contains"

    def test_not_in_cohort_constructor_still_works(self) -> None:
        """Filter.not_in_cohort() output passes the new guard."""
        f = Filter.not_in_cohort(789, "Bots")
        assert f._operator == "does not contain"

    def test_insights_model_path_raises_bookmark_error(self) -> None:
        """Insights path: BookmarkValidationError, not a silent string filter."""
        with pytest.raises(BookmarkValidationError, match="in_cohort"):
            InsightsQuery.model_validate(
                {"events": ["Login"], "where": [dict(self._COHORT_REPRO)]}
            )

    def test_flow_model_path_raises_bookmark_error(self) -> None:
        """Flow path: BookmarkValidationError, not a raw RuntimeError."""
        with pytest.raises(BookmarkValidationError, match="in_cohort"):
            FlowQuery.model_validate(
                {"event": "Login", "where": [dict(self._COHORT_REPRO)]}
            )

    def test_is_set_on_cohorts_allowed(self) -> None:
        """Filter.is_set('$cohorts') constructs a normal is-set filter.

        Regression for finding
        ``cohorts-guard-rejects-previously-valid-is-set``: the guard
        must not reject the value-less presence operators, which built
        an ordinary filter entry before the guard existed.
        """
        f = Filter.is_set("$cohorts")
        assert f._property == "$cohorts"
        assert f._operator == "is set"
        assert f._value is None

    def test_is_not_set_on_cohorts_allowed(self) -> None:
        """Filter.is_not_set('$cohorts') constructs a normal filter."""
        f = Filter.is_not_set("$cohorts")
        assert f._operator == "is not set"
        assert f._value is None

    def test_dict_path_is_set_on_cohorts_allowed(self) -> None:
        """The dict/LLM path accepts a value-less is-set on '$cohorts'."""
        f = self._adapter.validate_python(
            {"property": "$cohorts", "operator": "is set"}
        )
        assert f._operator == "is set"
        assert f._value is None

    def test_true_operator_on_cohorts_still_rejected(self) -> None:
        """Value-less boolean operators on '$cohorts' remain rejected."""
        with pytest.raises(ValidationError, match="in_cohort"):
            self._adapter.validate_python({"property": "$cohorts", "operator": "true"})


class TestUnionArmErrorTranslation:
    """Union-typed fields surface clean errors, not sibling-arm noise.

    Regression tests for finding ``union-arm-error-noise-for-invalid-filters``:
    one invalid ``Filter`` in ``InsightsQuery.where`` (typed
    ``list[Filter | FrequencyFilter]``) surfaced FIVE errors — the real
    value error plus misleading FrequencyFilter-arm errors
    (``where[0].event: Field required``) — and a bad ``Metric`` dict in
    ``events`` produced exact duplicate (path, message) pairs from
    sibling arms. ``translate_pydantic_exception`` now prefers the arm
    that pinpointed the failure (a ``value_error``) and deduplicates
    identical errors.
    """

    def test_bad_filter_in_union_where_yields_single_error(self) -> None:
        """A bad Filter dict in a union-typed where yields ONE clean error."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "where": [
                        {
                            "property": "amount",
                            "operator": "is greater than",
                            "value": "oops",
                        }
                    ],
                }
            )
        errors = exc_info.value.errors
        assert len(errors) == 1
        assert errors[0].path == "where[0]"
        assert "numeric" in errors[0].message

    def test_bad_frequency_filter_yields_single_error(self) -> None:
        """A FrequencyFilter value_error is not buried under Filter-arm noise."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {"events": ["Login"], "where": [{"event": "Login", "value": -1}]}
            )
        errors = exc_info.value.errors
        assert len(errors) == 1
        assert "non-negative" in errors[0].message

    def test_bad_metric_dict_yields_no_duplicate_errors(self) -> None:
        """A bad Metric dict in events produces no duplicate (path, message)."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate({"events": [{"event": "Login", "bogus": 1}]})
        pairs = [(e.path, e.message) for e in exc_info.value.errors]
        assert len(pairs) == len(set(pairs)), f"duplicate errors: {pairs}"

    def test_distinct_field_errors_all_preserved(self) -> None:
        """Errors on distinct non-union fields are not collapsed."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate({"events": ["Login"], "last": 0, "rolling": 0})
        paths = {e.path for e in exc_info.value.errors}
        assert {"last", "rolling"} <= paths


class TestConstrainedArmPathTranslation:
    """Per-arm ``constrained-int``/``constrained-float`` labels never leak.

    Regression tests for finding
    ``constrained-arm-labels-leak-into-error-paths``: the per-arm bound
    annotations (``Annotated[int, Field(strict=True, ge=0, le=100)]`` on
    ``InsightsQuery.percentile_value`` and ``GroupBy.bucket_size``) make
    pydantic label those union arms ``constrained-int`` /
    ``constrained-float`` in error ``loc``. Those labels are internal
    schema artifacts — they must be stripped from the translated path
    (like discriminator tags) so out-of-range input yields ONE error at
    the field's clean JSONPath instead of two near-duplicates at
    ``percentile_value.constrained-int`` / ``...constrained-float``.
    """

    def test_percentile_above_100_yields_single_clean_path(self) -> None:
        """percentile_value=150 yields exactly one error at 'percentile_value'."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery(events=["Login"], percentile_value=150)
        errors = exc_info.value.errors
        assert [e.path for e in errors] == ["percentile_value"]

    def test_percentile_negative_yields_single_clean_path(self) -> None:
        """percentile_value=-1 yields exactly one error at 'percentile_value'."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery(events=["Login"], percentile_value=-1)
        errors = exc_info.value.errors
        assert [e.path for e in errors] == ["percentile_value"]

    def test_group_by_bucket_size_out_of_range_path_clean(self) -> None:
        """bucket_size=-5 in group_by yields one range error at a clean path."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "group_by": [{"property": "x", "bucket_size": -5}],
                }
            )
        errors = exc_info.value.errors
        range_errors = [e for e in errors if "greater than 0" in e.message]
        assert [e.path for e in range_errors] == ["group_by[0].bucket_size"]
        assert all("constrained" not in e.path for e in errors)


class TestSameArmDistinctErrorsPreserved:
    """Union-arm pruning keeps distinct errors from the winning arm.

    Regression tests for finding
    ``union-prune-drops-distinct-same-arm-errors``: ``Filter``'s
    boolean-value rejection is a ``mode="before"`` validator that raises
    ``value_error`` even when OTHER fields of the SAME ``Filter`` arm
    carry real, independent errors. The prune must drop only errors
    reported under a DIFFERENT union arm (sibling shape noise), never a
    same-arm error on another field — otherwise a self-correcting agent
    fixes the boolean, resubmits, and only then learns the operator was
    also invalid.
    """

    def test_invalid_operator_and_bool_value_both_surface(self) -> None:
        """A bad operator AND a boolean value on one Filter both surface."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "where": [{"property": "x", "operator": "bogus_op", "value": True}],
                }
            )
        paths = {e.path for e in exc_info.value.errors}
        assert "where[0].operator" in paths
        assert "where[0].value" in paths
        # Sibling FrequencyFilter-arm shape noise stays pruned.
        assert "where[0].event" not in paths

    def test_nested_list_item_filter_errors_both_surface(self) -> None:
        """Distinct errors in two list_contains sub-filters both surface."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "where": [
                        {
                            "property": "items",
                            "operator": "list_contains",
                            "list_item_quantifier": "any",
                            "list_item_filters": [
                                {
                                    "property": "sku",
                                    "operator": "bogus_op",
                                    "value": "X",
                                },
                                {
                                    "property": "active",
                                    "operator": "equals",
                                    "value": True,
                                },
                            ],
                        }
                    ],
                }
            )
        paths = {e.path for e in exc_info.value.errors}
        assert "where[0].list_item_filters[0].operator" in paths
        assert "where[0].list_item_filters[1].value" in paths
        # Sibling FrequencyFilter-arm shape noise stays pruned.
        assert "where[0].event" not in paths


class TestFilterNoValueOperatorValueRejected:
    """No-value operators reject a supplied value instead of discarding it.

    Regression tests for finding
    ``filter-no-value-operators-silently-discard-value``: ``is set`` /
    ``is not set`` / ``true`` / ``false`` silently nulled a
    caller-supplied value, running a bare existence check instead of the
    comparison the caller almost certainly meant (``operator "equals"``)
    — a semantically different query. The other operator families all
    reject mismatched values with a targeted ``ValueError``; the
    no-value family must do the same.
    """

    _adapter: ClassVar[TypeAdapter[Filter]]

    @classmethod
    def setup_class(cls) -> None:
        """Create a shared TypeAdapter for Filter."""
        cls._adapter = TypeAdapter(Filter)

    @pytest.mark.parametrize("operator", ["is set", "is not set", "true", "false"])
    def test_no_value_operator_with_value_rejected(self, operator: str) -> None:
        """Each no-value operator rejects a caller-supplied value."""
        with pytest.raises(ValidationError, match="does not take a value"):
            self._adapter.validate_python(
                {"property": "country", "operator": operator, "value": "US"}
            )

    def test_is_set_error_suggests_equals(self) -> None:
        """The is-set rejection points the caller at operator 'equals'."""
        with pytest.raises(ValidationError, match="did you mean operator 'equals'"):
            self._adapter.validate_python(
                {"property": "country", "operator": "is set", "value": "US"}
            )

    def test_error_reports_original_value(self) -> None:
        """The rejection message echoes the discarded value."""
        with pytest.raises(ValidationError, match="'US'"):
            self._adapter.validate_python(
                {"property": "country", "operator": "is set", "value": "US"}
            )

    @pytest.mark.parametrize("operator", ["is set", "is not set", "true", "false"])
    def test_no_value_operator_without_value_still_accepted(
        self, operator: str
    ) -> None:
        """Omitting the value keeps every no-value operator constructible."""
        f = self._adapter.validate_python({"property": "country", "operator": operator})
        assert f._value is None

    def test_classmethods_unaffected(self) -> None:
        """The value-less classmethod constructors keep working."""
        assert Filter.is_set("email")._value is None
        assert Filter.is_not_set("email")._value is None
        assert Filter.is_true("active")._value is None
        assert Filter.is_false("active")._value is None

    def test_insights_model_path_raises_bookmark_error(self) -> None:
        """The Insights model path surfaces BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError, match="does not take a value"):
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "where": [
                        {"property": "country", "operator": "is set", "value": "US"}
                    ],
                }
            )


class TestMetricPercentileValueBounds:
    """Metric.percentile_value enforces the 0-100 range at construction.

    Regression tests for finding
    ``metric-percentile-value-unbounded-everywhere``: the top-level
    ``InsightsQuery.percentile_value`` enforced 0 <= x <= 100 per arm,
    but the per-metric field had no bound anywhere — ``Metric("E",
    math="percentile", property="p", percentile_value=150)`` was
    accepted and shipped ``custom_percentile`` 150 to the server.
    """

    def test_percentile_above_100_rejected_direct(self) -> None:
        """Metric(percentile_value=150) is rejected at construction."""
        with pytest.raises(ValidationError, match="percentile_value"):
            Metric("E", math="percentile", property="p", percentile_value=150)

    def test_percentile_negative_rejected_direct(self) -> None:
        """Metric(percentile_value=-1) is rejected at construction."""
        with pytest.raises(ValidationError, match="percentile_value"):
            Metric("E", math="percentile", property="p", percentile_value=-1)

    def test_percentile_above_100_rejected_model_path(self) -> None:
        """The dict/LLM path rejects 150 with a stable range code."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": [
                        {
                            "event": "E",
                            "math": "percentile",
                            "property": "p",
                            "percentile_value": 150,
                        }
                    ]
                }
            )
        err = next(
            e for e in exc_info.value.errors if e.path == "events[0].percentile_value"
        )
        assert err.code == "B0_OUT_OF_RANGE"

    def test_float_arm_bounded_too(self) -> None:
        """The float arm carries the same 0-100 bound."""
        with pytest.raises(ValidationError, match="percentile_value"):
            Metric("E", math="percentile", property="p", percentile_value=100.5)

    def test_boundary_values_still_accepted(self) -> None:
        """0, 100, and interior floats keep constructing."""
        assert (
            Metric("E", math="percentile", property="p", percentile_value=0)
        ).percentile_value == 0
        assert (
            Metric("E", math="percentile", property="p", percentile_value=100)
        ).percentile_value == 100
        assert (
            Metric("E", math="percentile", property="p", percentile_value=99.9)
        ).percentile_value == 99.9


class TestSiblingArmNoisePrunedWithoutValueError:
    """Sibling-arm shape noise is pruned when a field-level error wins.

    Regression tests for finding
    ``sibling-arm-shape-noise-survives-without-value-error``: the prune
    only fired when the winning arm produced a ``value_error``. When the
    distinguishing failure was a field-level pydantic error (literal,
    bound violation) the full cross-arm blast survived — including
    errors that contradict the schema, like ``events[0].event:
    S3_UNKNOWN_FIELD`` (the CohortMetric arm complaining about the
    *required* Metric field). An arm now also wins when it produced a
    nested error strictly below its root or when every one of its
    errors is a domain/constraint failure rather than shape noise.
    """

    def test_nested_filter_literal_error_prunes_sibling_arms(self) -> None:
        """A deep literal error in the Metric arm suppresses other arms."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": [
                        {
                            "event": "L",
                            "filters": [
                                {"property": "c", "operator": "bogus", "value": 1}
                            ],
                        }
                    ]
                }
            )
        errors = exc_info.value.errors
        assert [e.path for e in errors] == ["events[0].filters[0].operator"]
        assert errors[0].code == "B0_INVALID_LITERAL"

    def test_bound_violation_prunes_sibling_arms(self) -> None:
        """A bucket_size range error is not also called an unknown field."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "group_by": [{"event": "P", "bucket_size": 0}],
                }
            )
        errors = exc_info.value.errors
        assert [e.path for e in errors] == ["group_by[0].bucket_size"]
        assert errors[0].code == "B0_OUT_OF_RANGE"

    def test_ambiguous_shape_mismatch_keeps_all_arm_errors(self) -> None:
        """Inputs matching no arm's shape keep the full error set."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {"events": ["Login"], "where": [{"event": "L"}]}
            )
        paths = {e.path for e in exc_info.value.errors}
        # Both arms' missing-field errors survive: the caller's intent
        # is genuinely ambiguous (FrequencyFilter lacks value, Filter
        # lacks property/operator).
        assert "where[0].value" in paths
        assert "where[0].property" in paths


class TestDataclassArmTypeErrorCode:
    """Dataclass-arm wrong-type errors carry the stable B0_WRONG_TYPE code.

    Regression tests for finding
    ``dataclass-type-error-unmapped-to-generic-code``: pydantic emits
    ``dataclass_type`` for the pydantic-dataclass union arms (Metric,
    CohortMetric, Formula, ...) where a ``BaseModel`` arm emits
    ``model_type`` — the same conceptual wrong-type failure got
    ``B0_WRONG_TYPE`` on one arm kind and the generic
    ``VALIDATION_ERROR`` fallback on the other.
    """

    def test_scalar_event_type_errors_all_carry_wrong_type(self) -> None:
        """events=[3.14] yields B0_WRONG_TYPE for every arm's type error."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate({"events": [3.14]})
        errors = exc_info.value.errors
        assert errors, "expected at least one error"
        assert all(e.code == "B0_WRONG_TYPE" for e in errors), [
            (e.code, e.message) for e in errors
        ]

    def test_dataclass_arm_message_present_with_stable_code(self) -> None:
        """The dataclass-arm message survives with the mapped code."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate({"events": [3.14]})
        dataclass_errors = [
            e for e in exc_info.value.errors if "instance of Metric" in e.message
        ]
        assert dataclass_errors
        assert dataclass_errors[0].code == "B0_WRONG_TYPE"


class TestPropertySpecArmPathTranslation:
    """``PropertySpec`` union-arm class names never leak into error paths.

    Regression tests for finding
    ``property-spec-union-arm-labels-leak-into-error-paths``: the
    ``PropertySpec`` union members ``CustomPropertyRef`` and
    ``InlineCustomProperty`` (``property: str | CustomPropertyRef |
    InlineCustomProperty`` on ``Filter``, ``GroupBy``, and ``Metric``)
    were missing from ``_DISCRIMINATOR_TAGS``, so a malformed property
    dict surfaced raw class-name path segments like
    ``where[0].property.CustomPropertyRef.id`` on all four query paths.
    The labels must be stripped so paths collapse to the clean
    ``where[0].property``-rooted JSONPath grammar.
    """

    def test_bad_property_dict_in_where_yields_clean_paths(self) -> None:
        """A bad property dict in a Filter yields property-rooted paths."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "where": [
                        {
                            "property": {"custom_property_id": True},
                            "operator": "is set",
                        }
                    ],
                }
            )
        paths = [e.path for e in exc_info.value.errors]
        joined = " ".join(paths)
        assert "CustomPropertyRef" not in joined
        assert "InlineCustomProperty" not in joined
        # The arm errors collapse onto the clean property-rooted paths.
        assert "where[0].property.id" in paths
        assert "where[0].property.formula" in paths

    def test_bad_property_dict_in_group_by_yields_clean_paths(self) -> None:
        """A bad property dict in a GroupBy yields property-rooted paths."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "group_by": [{"property": {"custom_property_id": True}}],
                }
            )
        joined = " ".join(e.path for e in exc_info.value.errors)
        assert "CustomPropertyRef" not in joined
        assert "InlineCustomProperty" not in joined


def _iter_schema_nodes(node: Any) -> Iterator[dict[str, Any]]:
    """Yield every dict node in a pydantic core-schema tree.

    Walks the raw ``__pydantic_core_schema__`` structure (nested dicts,
    lists, and tuples) without following ``definition-ref`` links, so
    recursive schemas cannot loop.

    Args:
        node: Any core-schema fragment (dict, list, tuple, or scalar).

    Yields:
        Each ``dict`` encountered in the tree, including ``node`` itself.
    """
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _iter_schema_nodes(value)
    elif isinstance(node, (list, tuple)):
        for item in node:
            yield from _iter_schema_nodes(item)


def _union_arm_model_names(model_cls: type[BaseModel]) -> set[str]:
    """Collect every union-arm label pydantic can insert into error ``loc``.

    Walks ``model_cls.__pydantic_core_schema__`` and, for every ``union``
    and ``tagged-union`` node, records two kinds of labels:

    - For every arm, the arm's class name when the arm is a ``BaseModel``
      (``model`` schema) or pydantic dataclass (``dataclass`` schema),
      resolving ``definition-ref`` indirection. Smart unions insert these
      bare class names into error ``loc`` tuples.
    - For ``tagged-union`` nodes, the choice *keys*: pydantic inserts the
      matched tag into ``loc`` for errors inside the chosen arm. With a
      callable ``Discriminator(...)`` these keys are ``Tag(...)`` names
      (class names); with a declarative ``Field(discriminator=...)`` they
      are the raw tag values (e.g. ``"property"``), which are NOT
      strippable — registering them would destroy real field paths.

    Every collected label must be registered in ``_DISCRIMINATOR_TAGS``
    (or otherwise strippable) or it leaks into caller-facing error paths.

    Args:
        model_cls: The pydantic model whose core schema to walk.

    Returns:
        The set of union-arm labels reachable from ``model_cls``.
    """
    schema: Any = model_cls.__pydantic_core_schema__
    refs: dict[str, dict[str, Any]] = {
        node["ref"]: node
        for node in _iter_schema_nodes(schema)
        if isinstance(node.get("ref"), str)
    }
    names: set[str] = set()
    for node in _iter_schema_nodes(schema):
        if node.get("type") not in ("union", "tagged-union"):
            continue
        choices = node.get("choices")
        if node.get("type") == "tagged-union" and isinstance(choices, dict):
            names.update(str(key) for key in choices)
        arms: list[Any] = (
            list(choices.values()) if isinstance(choices, dict) else list(choices or ())
        )
        for arm in arms:
            if isinstance(arm, tuple):
                arm = arm[0]
            seen_refs: set[str] = set()
            while isinstance(arm, dict) and arm.get("type") == "definition-ref":
                ref = str(arm.get("schema_ref"))
                if ref in seen_refs:
                    break
                seen_refs.add(ref)
                arm = refs.get(ref, {})
            if isinstance(arm, dict) and arm.get("type") in ("model", "dataclass"):
                names.add(arm["cls"].__name__)
    return names


class TestUnionArmLabelRegistry:
    """Every reachable union-arm class name is a strippable arm label.

    Structural guard for finding
    ``property-spec-union-arm-labels-leak-into-error-paths``:
    ``_DISCRIMINATOR_TAGS`` is hand-maintained, and each newly added
    union member that is not registered leaks its raw class name into
    caller-facing error paths (Metric/Filter/FlowStep in earlier rounds,
    CustomPropertyRef/InlineCustomProperty in round 5). This test walks
    the pydantic core schema of all four query models, collects every
    ``BaseModel`` / pydantic-dataclass union arm, and asserts each class
    name is caught by ``_is_union_arm_label`` — so adding a union member
    without registering it fails CI instead of shipping a path leak.
    """

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_every_union_arm_class_name_is_strippable(
        self, model_cls: type[BaseModel]
    ) -> None:
        """All model/dataclass union arms reachable from the model are registered."""
        unregistered = {
            name
            for name in _union_arm_model_names(model_cls)
            if not _is_union_arm_label(name)
        }
        assert unregistered == set(), (
            f"Union arm class names not registered in _DISCRIMINATOR_TAGS "
            f"(their raw class names will leak into error paths): "
            f"{sorted(unregistered)}"
        )

    def test_walker_finds_known_union_arms(self) -> None:
        """The schema walk is not vacuous — known arms are discovered.

        Guards the guard: if the core-schema walker silently broke (e.g.
        a pydantic upgrade renames schema keys), the registry test above
        would pass on an empty set. Pin a few arms that must be found.
        """
        names = _union_arm_model_names(InsightsQuery)
        assert {
            "Filter",
            "FrequencyFilter",
            "Metric",
            "CustomPropertyRef",
            "InlineCustomProperty",
        } <= names

    def test_walker_covers_cohort_criteria_tagged_union(self) -> None:
        """The declarative cohort-node union is covered by the walk.

        Regression guard for finding
        ``cohort-criteria-kind-tag-leaks-into-error-paths``: the
        ``InlineCohort.criteria`` tagged union must surface its ``loc``
        labels (the tagged-union choice keys) to the registry test.
        With the callable ``Discriminator`` + ``Tag`` pattern those keys
        are the criterion class names; a regression to the declarative
        ``Field(discriminator="kind")`` form would surface the raw kind
        values (``"property"`` — unregistrable, it is a real field name
        everywhere) and fail ``test_every_union_arm_class_name_is_strippable``.
        """
        names = _union_arm_model_names(InsightsQuery)
        assert {
            "PropertyCriterion",
            "BehavioralCriterion",
            "CohortReferenceCriterion",
            "InlineCohort",
        } <= names


class TestCohortCriteriaKindTagPathTranslation:
    """Cohort-criteria ``kind`` tags never leak into error paths.

    Regression tests for finding
    ``cohort-criteria-kind-tag-leaks-into-error-paths``: the declarative
    ``Field(discriminator="kind")`` on the cohort-node union made
    pydantic insert the *kind tag value* into error ``loc`` tuples,
    producing phantom path segments like
    ``group_by[0].cohort.criteria[0].property.value`` — where
    ``property`` is the union tag, not a field, and collides with
    ``PropertyCriterion``'s real ``property`` field. The union now uses
    the callable ``Discriminator(...)`` + ``Tag(<ClassName>)`` pattern
    (like the sorting models) so the inserted labels are registered
    class names that ``_loc_to_jsonpath`` strips.
    """

    def test_property_criterion_missing_value_path_clean(self) -> None:
        """Missing PropertyCriterion.value reports criteria[0].value."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["L"],
                    "group_by": [
                        {
                            "cohort": {
                                "criteria": [{"kind": "property", "property": "plan"}]
                            }
                        }
                    ],
                }
            )
        paths = [e.path for e in exc_info.value.errors]
        assert "group_by[0].cohort.criteria[0].value" in paths
        assert all(".property.value" not in p for p in paths), paths

    def test_behavioral_criterion_field_error_path_clean(self) -> None:
        """A BehavioralCriterion field error carries no 'behavioral' segment."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["L"],
                    "group_by": [
                        {
                            "cohort": {
                                "criteria": [
                                    {
                                        "kind": "behavioral",
                                        "event": "Purchase",
                                        "at_least": -1,
                                        "within_days": 30,
                                    }
                                ]
                            }
                        }
                    ],
                }
            )
        paths = [e.path for e in exc_info.value.errors]
        assert "group_by[0].cohort.criteria[0].at_least" in paths
        assert all(".behavioral." not in p for p in paths), paths

    def test_retention_group_by_cohort_criteria_path_clean(self) -> None:
        """The retention query path strips the kind tag identically."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            RetentionQuery.model_validate(
                {
                    "born_event": "Signup",
                    "return_event": "Login",
                    "group_by": [
                        {
                            "cohort": {
                                "criteria": [{"kind": "property", "property": "plan"}]
                            }
                        }
                    ],
                }
            )
        paths = [e.path for e in exc_info.value.errors]
        assert "group_by[0].cohort.criteria[0].value" in paths
        assert all(".property.value" not in p for p in paths), paths

    def test_valid_declarative_cohort_still_coerces(self) -> None:
        """The Tag switch keeps valid declarative payloads validating."""
        q = InsightsQuery.model_validate(
            {
                "events": ["L"],
                "group_by": [
                    {
                        "cohort": {
                            "operator": "or",
                            "criteria": [
                                {
                                    "kind": "property",
                                    "property": "plan",
                                    "value": "pro",
                                },
                                {"kind": "cohort_reference", "cohort_id": 7},
                                {
                                    "kind": "group",
                                    "criteria": [
                                        {
                                            "kind": "behavioral",
                                            "event": "Buy",
                                            "at_least": 1,
                                            "within_days": 7,
                                        }
                                    ],
                                },
                            ],
                        }
                    }
                ],
            }
        )
        assert q.group_by is not None
        assert isinstance(q.group_by[0], CohortBreakdown)


class TestInstanceCheckArmNoise:
    """Builder-instance arm messages never shadow actionable field errors.

    Regression tests for finding
    ``is-instance-of-error-unmapped-leaks-python-only-arm-message``: the
    ``CohortDefinition`` arm of ``cohort: StrictInt | CohortDefinition``
    validates with an ``isinstance`` check that is deliberately excluded
    from the JSON schema (it exists for Python callers holding builder
    objects). A malformed inline-cohort dict made pydantic surface
    ``"Input should be an instance of CohortDefinition"`` to dict/LLM
    callers alongside the actionable ``InlineCohort``-arm field errors.
    The instance-check arm error is dropped whenever a sibling arm
    produced field-level errors for the same union value.
    """

    def test_malformed_inline_cohort_drops_instance_check_message(self) -> None:
        """The Python-only 'instance of CohortDefinition' message is dropped."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {"events": [{"cohort": {"operator": "bogus", "criteria": "nope"}}]}
            )
        errors = exc_info.value.errors
        assert not any("instance of CohortDefinition" in e.message for e in errors), [
            e.message for e in errors
        ]
        # The actionable InlineCohort-arm field errors survive.
        paths = {e.path for e in errors}
        assert "events[0].cohort.operator" in paths
        assert "events[0].cohort.criteria" in paths

    def test_cohort_breakdown_inline_cohort_drops_instance_check_message(self) -> None:
        """Same suppression on the CohortBreakdown.cohort path."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "group_by": [{"cohort": {"operator": "bogus", "criteria": "nope"}}],
                }
            )
        errors = exc_info.value.errors
        assert not any("instance of CohortDefinition" in e.message for e in errors)
        paths = {e.path for e in errors}
        assert "group_by[0].cohort.operator" in paths
        assert "group_by[0].cohort.criteria" in paths


class TestSharedFieldSchema:
    """Shared fields survive the _BaseQuery hoist in every model's schema."""

    @pytest.mark.parametrize(
        "model", [InsightsQuery, FunnelQuery, RetentionQuery, FlowQuery]
    )
    def test_data_group_id_in_schema(self, model: type[BaseModel]) -> None:
        """data_group_id appears with its description in each schema."""
        props = model.model_json_schema()["properties"]
        assert "data_group_id" in props
        assert (
            props["data_group_id"]["description"]
            == "Data group ID for group-level analytics."
        )

    @pytest.mark.parametrize("model", [InsightsQuery, FunnelQuery, RetentionQuery])
    def test_time_comparison_in_schema(self, model: type[BaseModel]) -> None:
        """time_comparison appears in the three models that support it."""
        props = model.model_json_schema()["properties"]
        assert "time_comparison" in props

    def test_flow_has_no_time_comparison(self) -> None:
        """FlowQuery does not advertise time_comparison (flows reject it)."""
        assert "time_comparison" not in FlowQuery.model_json_schema()["properties"]
