"""Tests for Pydantic query models in query_models.py.

Verifies construction, JSON schema generation, model_validate round-trip,
frozen immutability, and field constraints for all query model types.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import ClassVar

import pytest
from pydantic import BaseModel, TypeAdapter, ValidationError

from mixpanel_headless.exceptions import BookmarkValidationError
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
