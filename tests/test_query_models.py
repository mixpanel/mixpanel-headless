"""Tests for Pydantic query models in query_models.py.

Verifies construction, JSON schema generation, model_validate round-trip,
frozen immutability, and field constraints for all query model types.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any, ClassVar

import pytest
from jsonschema import Draft202012Validator
from pydantic import BaseModel, TypeAdapter, ValidationError

from mixpanel_headless._internal.pydantic_utils import is_meta_key
from mixpanel_headless.exceptions import BookmarkValidationError
from mixpanel_headless.query_models import (
    FlowQuery,
    FunnelQuery,
    InsightsQuery,
    RetentionQuery,
)
from mixpanel_headless.types import (
    BehavioralCriterion,
    CohortBreakdown,
    CohortMetric,
    CohortReferenceCriterion,
    CustomPropertyRef,
    Exclusion,
    Filter,
    FlowStep,
    Formula,
    FrequencyBreakdown,
    FrequencyFilter,
    FunnelStep,
    GroupBy,
    HoldingConstant,
    InlineCohort,
    Metric,
    PropertyCriterion,
    RetentionEvent,
    TimeComparison,
)

ALL_MODELS: list[type[BaseModel]] = [
    InsightsQuery,
    FunnelQuery,
    RetentionQuery,
    FlowQuery,
]


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
        """FlowQuery(event=[]) is rejected.

        The rule lives on the list union alternative as ``min_length=1``
        (so the schema advertises ``minItems``), and ``_BaseQuery``'s wrap
        validator keeps the caller-facing exception type unchanged.
        """
        from mixpanel_headless.exceptions import BookmarkValidationError

        with pytest.raises(BookmarkValidationError) as exc_info:
            FlowQuery(event=[])
        err = next(e for e in exc_info.value.errors if e.path == "event")
        assert err.code == "B0_MIN_LENGTH"

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
        """Mixed-type lists match no _value union alternative and are rejected."""
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


class TestFilterEqualityPropertyTypeCompatibility:
    """Equality operands must match an explicitly declared property_type.

    A scalar string was wrapped into a list before ``_property_type`` was
    consulted, so a filter declared ``number`` kept a string operand and
    reached the wire as ``filterType: "number"`` with
    ``filterValue: ["oops"]`` — a self-contradictory query the API cannot
    answer meaningfully.
    """

    _adapter: ClassVar[TypeAdapter[Filter]]

    @classmethod
    def setup_class(cls) -> None:
        """Create a shared TypeAdapter for Filter."""
        cls._adapter = TypeAdapter(Filter)

    @pytest.mark.parametrize("operator", ["equals", "does not equal"])
    def test_number_type_rejects_scalar_string(self, operator: str) -> None:
        """A number-typed equality rejects a scalar string operand.

        Args:
            operator: The equality operator under test.
        """
        with pytest.raises(ValidationError, match="numeric"):
            self._adapter.validate_python(
                {
                    "property": "amount",
                    "operator": operator,
                    "value": "oops",
                    "property_type": "number",
                }
            )

    def test_number_type_rejects_string_list(self) -> None:
        """A number-typed equality rejects a list of string operands."""
        with pytest.raises(ValidationError, match="numeric"):
            self._adapter.validate_python(
                {
                    "property": "amount",
                    "operator": "equals",
                    "value": ["10", "20"],
                    "property_type": "number",
                }
            )

    @pytest.mark.parametrize("operator", ["equals", "does not equal"])
    def test_number_type_keeps_scalar_numeric_value(self, operator: str) -> None:
        """A number-typed equality keeps a numeric scalar unwrapped.

        Pinned by ``filter_to_selector``: the scalar numeric form is the
        schema-driven equality path through ``query_user``.

        Args:
            operator: The equality operator under test.
        """
        f = self._adapter.validate_python(
            {
                "property": "count",
                "operator": operator,
                "value": 42,
                "property_type": "number",
            }
        )
        assert f._value == 42
        assert f._property_type == "number"

    def test_number_type_accepts_numeric_list(self) -> None:
        """A number-typed equality accepts a list of numeric operands."""
        f = self._adapter.validate_python(
            {
                "property": "count",
                "operator": "equals",
                "value": [1, 2.5],
                "property_type": "number",
            }
        )
        assert f._value == [1, 2.5]

    @pytest.mark.parametrize("operator", ["equals", "does not equal"])
    def test_boolean_type_rejects_equality(self, operator: str) -> None:
        """A boolean-typed property cannot be tested with equality.

        Boolean properties are tested with the value-less ``true`` /
        ``false`` operators, so no operand is compatible here.

        Args:
            operator: The equality operator under test.
        """
        with pytest.raises(ValidationError, match="is_true"):
            self._adapter.validate_python(
                {
                    "property": "active",
                    "operator": operator,
                    "value": "oops",
                    "property_type": "boolean",
                }
            )

    def test_string_type_still_wraps_scalar(self) -> None:
        """The default string-typed equality keeps wrapping a scalar."""
        f = self._adapter.validate_python(
            {"property": "country", "operator": "equals", "value": "US"}
        )
        assert f._value == ["US"]

    def test_explicit_string_type_still_wraps_scalar(self) -> None:
        """An explicitly string-typed equality keeps wrapping a scalar."""
        f = self._adapter.validate_python(
            {
                "property": "country",
                "operator": "equals",
                "value": "US",
                "property_type": "string",
            }
        )
        assert f._value == ["US"]

    def test_datetime_type_still_wraps_scalar(self) -> None:
        """A datetime-typed equality is unaffected by the number rule."""
        f = self._adapter.validate_python(
            {
                "property": "$time",
                "operator": "equals",
                "value": "2024-01-01",
                "property_type": "datetime",
            }
        )
        assert f._value == ["2024-01-01"]

    def test_classmethod_number_equality_still_builds(self) -> None:
        """Direct construction with a numeric operand is unaffected."""
        f = Filter(
            _property="count",
            _operator="equals",
            _value=42,
            _property_type="number",
            _resource_type="events",
        )
        assert f._value == 42


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


class TestDeclarativeCriterionStrictCoercion:
    """Declarative cohort criteria reject bool/str coercion into int/bool fields.

    Regression tests for finding
    ``declarative-cohort-criterion-models-lax-coerce-int-bool``: the
    declarative criterion models used plain lax ``int``/``bool`` fields
    while every other nested building block was strict, so on the
    dict/LLM path ``cohort_id: "456"`` silently referenced saved cohort
    456 (the exact ``cohort: "5"`` typo scenario the query_models.py
    module docstring cites), ``at_least: True`` silently became count 1
    (a caller who meant boolean "did the event" got a materially
    different query), and ``negated: 1`` silently became ``True``.
    ``CohortReferenceCriterion.cohort_id/negated`` and every
    ``BehavioralCriterion`` count/window field must reject coercion
    like their strict siblings (``CohortMetric.cohort``,
    ``FrequencyFilter.date_range_value``, ...).
    """

    def test_cohort_reference_cohort_id_str_rejected(self) -> None:
        """CohortReferenceCriterion cohort_id='456' must not become 456."""
        with pytest.raises(ValidationError, match="cohort_id"):
            CohortReferenceCriterion.model_validate(
                {"kind": "cohort_reference", "cohort_id": "456"}
            )

    def test_cohort_reference_cohort_id_bool_rejected(self) -> None:
        """CohortReferenceCriterion cohort_id=True must not become 1."""
        with pytest.raises(ValidationError, match="cohort_id"):
            CohortReferenceCriterion.model_validate(
                {"kind": "cohort_reference", "cohort_id": True}
            )

    def test_cohort_reference_negated_int_rejected(self) -> None:
        """CohortReferenceCriterion negated=1 must not become True."""
        with pytest.raises(ValidationError, match="negated"):
            CohortReferenceCriterion.model_validate(
                {"kind": "cohort_reference", "cohort_id": 456, "negated": 1}
            )

    def test_behavioral_at_least_bool_rejected(self) -> None:
        """BehavioralCriterion at_least=True must not become count 1."""
        with pytest.raises(ValidationError, match="at_least"):
            BehavioralCriterion.model_validate(
                {
                    "kind": "behavioral",
                    "event": "Purchase",
                    "at_least": True,
                    "within_days": 30,
                }
            )

    def test_behavioral_at_least_str_rejected(self) -> None:
        """BehavioralCriterion at_least='3' must not become count 3."""
        with pytest.raises(ValidationError, match="at_least"):
            BehavioralCriterion.model_validate(
                {
                    "kind": "behavioral",
                    "event": "Purchase",
                    "at_least": "3",
                    "within_days": 30,
                }
            )

    def test_behavioral_at_most_str_rejected(self) -> None:
        """BehavioralCriterion at_most='5' must not become count 5."""
        with pytest.raises(ValidationError, match="at_most"):
            BehavioralCriterion.model_validate(
                {
                    "kind": "behavioral",
                    "event": "Purchase",
                    "at_most": "5",
                    "within_days": 30,
                }
            )

    def test_behavioral_exactly_bool_rejected(self) -> None:
        """BehavioralCriterion exactly=False must not become count 0."""
        with pytest.raises(ValidationError, match="exactly"):
            BehavioralCriterion.model_validate(
                {
                    "kind": "behavioral",
                    "event": "Purchase",
                    "exactly": False,
                    "within_days": 30,
                }
            )

    def test_behavioral_within_days_str_rejected(self) -> None:
        """BehavioralCriterion within_days='30' must not become 30."""
        with pytest.raises(ValidationError, match="within_days"):
            BehavioralCriterion.model_validate(
                {
                    "kind": "behavioral",
                    "event": "Purchase",
                    "at_least": 3,
                    "within_days": "30",
                }
            )

    def test_behavioral_within_weeks_bool_rejected(self) -> None:
        """BehavioralCriterion within_weeks=True must not become 1."""
        with pytest.raises(ValidationError, match="within_weeks"):
            BehavioralCriterion.model_validate(
                {
                    "kind": "behavioral",
                    "event": "Purchase",
                    "at_least": 3,
                    "within_weeks": True,
                }
            )

    def test_behavioral_within_months_str_rejected(self) -> None:
        """BehavioralCriterion within_months='6' must not become 6."""
        with pytest.raises(ValidationError, match="within_months"):
            BehavioralCriterion.model_validate(
                {
                    "kind": "behavioral",
                    "event": "Purchase",
                    "at_least": 3,
                    "within_months": "6",
                }
            )

    def test_cohort_reference_str_id_rejected_via_query_dict_path(self) -> None:
        """InsightsQuery group_by inline-cohort cohort_id='456' is rejected."""
        with pytest.raises(BookmarkValidationError, match="cohort_id"):
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "group_by": [
                        {
                            "cohort": {
                                "kind": "group",
                                "criteria": [
                                    {"kind": "cohort_reference", "cohort_id": "456"}
                                ],
                            }
                        }
                    ],
                }
            )

    def test_behavioral_bool_count_rejected_via_query_dict_path(self) -> None:
        """InsightsQuery group_by inline-cohort at_least=True is rejected."""
        with pytest.raises(BookmarkValidationError, match="at_least"):
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "group_by": [
                        {
                            "cohort": {
                                "kind": "group",
                                "criteria": [
                                    {
                                        "kind": "behavioral",
                                        "event": "Purchase",
                                        "at_least": True,
                                        "within_days": 30,
                                    }
                                ],
                            }
                        }
                    ],
                }
            )

    def test_valid_criterion_values_still_accepted(self) -> None:
        """Genuine ints/bools still construct on every strict field."""
        ref = CohortReferenceCriterion.model_validate(
            {"kind": "cohort_reference", "cohort_id": 456, "negated": True}
        )
        assert (ref.cohort_id, ref.negated) == (456, True)
        ref_default = CohortReferenceCriterion.model_validate(
            {"kind": "cohort_reference", "cohort_id": 7}
        )
        assert ref_default.negated is False
        b = BehavioralCriterion.model_validate(
            {
                "kind": "behavioral",
                "event": "Purchase",
                "at_least": 3,
                "within_days": 30,
            }
        )
        assert (b.at_least, b.within_days) == (3, 30)
        b_full = BehavioralCriterion(
            kind="behavioral",
            event="Purchase",
            at_most=5,
            within_weeks=2,
        )
        assert (b_full.at_most, b_full.within_weeks) == (5, 2)
        b_exact = BehavioralCriterion(
            kind="behavioral", event="Purchase", exactly=0, within_months=6
        )
        assert (b_exact.exactly, b_exact.within_months) == (0, 6)


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
        alternative and coerced to 0/1 before ``__post_init__`` ran.
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


class TestUnionAlternativeErrorTranslation:
    """Union-typed fields surface clean errors, not sibling-alternative noise.

    Regression tests for finding ``union-alternative-error-noise-for-invalid-filters``:
    one invalid ``Filter`` in ``InsightsQuery.where`` (typed
    ``list[Filter | FrequencyFilter]``) surfaced FIVE errors — the real
    value error plus misleading FrequencyFilter-alternative errors
    (``where[0].event: Field required``) — and a bad ``Metric`` dict in
    ``events`` produced exact duplicate (path, message) pairs from
    sibling alternatives. ``translate_pydantic_exception`` now prefers the alternative
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
        """A FrequencyFilter value_error is not buried under Filter-alternative noise."""
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


class TestConstrainedAlternativePathTranslation:
    """Per-alternative ``constrained-int``/``constrained-float`` labels never leak.

    Regression tests for finding
    ``constrained-alternative-labels-leak-into-error-paths``: the per-alternative bound
    annotations (``Annotated[int, Field(strict=True, ge=0, le=100)]`` on
    ``InsightsQuery.percentile_value`` and ``GroupBy.bucket_size``) make
    pydantic label those union alternatives ``constrained-int`` /
    ``constrained-float`` in ``error_location``. Those labels are internal
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
    ``InsightsQuery.percentile_value`` enforced 0 <= x <= 100 per alternative,
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

    def test_float_alternative_bounded_too(self) -> None:
        """The float alternative carries the same 0-100 bound."""
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


class TestDataclassAlternativeTypeErrorCode:
    """Dataclass-alternative wrong-type errors carry the stable B0_WRONG_TYPE code.

    Regression tests for finding
    ``dataclass-type-error-unmapped-to-generic-code``: pydantic emits
    ``dataclass_type`` for the pydantic-dataclass union alternatives (Metric,
    CohortMetric, Formula, ...) where a ``BaseModel`` alternative emits
    ``model_type`` — the same conceptual wrong-type failure got
    ``B0_WRONG_TYPE`` on one alternative kind and the generic
    ``VALIDATION_ERROR`` fallback on the other.
    """

    def test_dataclass_alternative_type_error_carries_wrong_type(self) -> None:
        """A non-str routed to a dataclass alternative yields B0_WRONG_TYPE.

        In a ``str | FunnelStep`` union, a scalar like ``3.14`` routes to
        the ``FunnelStep`` alternative (see ``_str_or``); pydantic emits
        ``dataclass_type``, which must map to the stable wrong-type code
        rather than the generic ``VALIDATION_ERROR`` fallback.
        """
        with pytest.raises(BookmarkValidationError) as exc_info:
            FunnelQuery.model_validate({"steps": ["Signup", 3.14]})
        errors = exc_info.value.errors
        assert errors, "expected at least one error"
        assert all(e.code == "B0_WRONG_TYPE" for e in errors), [
            (e.code, e.message) for e in errors
        ]

    def test_dataclass_alternative_message_present_with_stable_code(self) -> None:
        """The dataclass-alternative message survives with the mapped code."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            FunnelQuery.model_validate({"steps": ["Signup", 3.14]})
        dataclass_errors = [
            e for e in exc_info.value.errors if "instance of FunnelStep" in e.message
        ]
        assert dataclass_errors
        assert dataclass_errors[0].code == "B0_WRONG_TYPE"


class TestPropertySpecAlternativePathTranslation:
    """``PropertySpec`` union-alternative class names never leak into error paths.

    Regression tests for finding
    ``property-spec-union-alternative-labels-leak-into-error-paths``: the
    ``PropertySpec`` union members ``CustomPropertyRef`` and
    ``InlineCustomProperty`` (``property: str | CustomPropertyRef |
    InlineCustomProperty`` on ``Filter``, ``GroupBy``, and ``Metric``)
    once surfaced raw class-name path segments like
    ``where[0].property.CustomPropertyRef.id``. Their tags are now marked, so a
    malformed dict routes to a single alternative (clean
    ``where[0].property.id`` path) and an unroutable one gets the located
    ``custom_error_message`` — no class name leaks into the path or message
    either way.
    """

    def test_routed_property_dict_in_where_yields_clean_path(self) -> None:
        """A malformed custom-property ref in a Filter reports a clean path.

        ``{"id": "x"}`` routes to the ``CustomPropertyRef`` alternative; the strict
        int rejection must surface at ``where[0].property.id`` with no
        ``CustomPropertyRef`` class name in the path.
        """
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "where": [{"property": {"id": "x"}, "operator": "is set"}],
                }
            )
        paths = [e.path for e in exc_info.value.errors]
        joined = " ".join(paths)
        assert "CustomPropertyRef" not in joined
        assert "InlineCustomProperty" not in joined
        assert "where[0].property.id" in paths

    def test_unroutable_property_dict_yields_custom_error_at_property(self) -> None:
        """A property dict matching no alternative gets the custom message at the field.

        ``{"custom_property_id": True}`` has neither ``id`` nor ``formula``,
        so the discriminator cannot place it: one located error at
        ``where[0].property`` with the caller-facing message and no leaked
        class names.
        """
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
        (err,) = [e for e in exc_info.value.errors if e.path == "where[0].property"]
        assert "'id'" in err.message and "'formula'" in err.message, err.message
        assert "CustomPropertyRef" not in err.message
        assert "InlineCustomProperty" not in err.message

    def test_bad_property_dict_in_group_by_yields_clean_paths(self) -> None:
        """A bad property dict in a GroupBy yields property-rooted paths."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "group_by": [{"property": {"id": "x"}}],
                }
            )
        joined = " ".join(e.path for e in exc_info.value.errors)
        assert "CustomPropertyRef" not in joined
        assert "InlineCustomProperty" not in joined
        assert "group_by[0].property.id" in [e.path for e in exc_info.value.errors]


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


def _union_alternative_labels(model_cls: type[BaseModel]) -> set[str]:
    """Collect every union label pydantic can insert into ``error_location``.

    Walks ``model_cls.__pydantic_core_schema__`` and records what pydantic
    actually puts in the loc for each union kind:

    - ``tagged-union`` — the choice *keys*. Pydantic inserts the matched tag
      for errors inside the chosen alternative. Built by
      ``discriminated_union``, these are :class:`MarkedTag` names (``#Metric``).
    - plain ``union`` — each alternative's class name, for ``BaseModel`` and
      pydantic-dataclass alternatives, resolving ``definition-ref``
      indirection. Smart unions insert bare class names, which nothing strips.

    Args:
        model_cls: The pydantic model whose core schema to walk.

    Returns:
        The set of union labels reachable from ``model_cls``.
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
            continue
        for alternative in list(choices or ()):
            if isinstance(alternative, tuple):
                alternative = alternative[0]
            seen_refs: set[str] = set()
            while (
                isinstance(alternative, dict)
                and alternative.get("type") == "definition-ref"
            ):
                ref = str(alternative.get("schema_ref"))
                if ref in seen_refs:
                    break
                seen_refs.add(ref)
                alternative = refs.get(ref, {})
            if isinstance(alternative, dict) and alternative.get("type") in (
                "model",
                "dataclass",
            ):
                names.add(alternative["cls"].__name__)
    return names


class TestUnionAlternativeLabelRegistry:
    """Every reachable union label is strippable from caller-facing paths.

    Structural guard for finding
    ``property-spec-union-alternative-labels-leak-into-error-paths``. It used
    to check membership of a hand-maintained ``_DISCRIMINATOR_TAGS`` frozenset;
    since every union is built by ``discriminated_union``, the check is now
    structural — each label must satisfy ``is_meta_key``, which is true of a
    :class:`MarkedTag` by construction.

    A failure means a union was declared without ``discriminated_union`` (a
    plain union contributes bare class names, an undiscriminated one
    contributes type labels), and its label would leak into an error path.
    """

    @pytest.mark.parametrize("model_cls", ALL_MODELS, ids=lambda m: m.__name__)
    def test_every_union_label_is_strippable(self, model_cls: type[BaseModel]) -> None:
        """All union labels reachable from the model are marked or otherwise meta."""
        leaking = {
            name
            for name in _union_alternative_labels(model_cls)
            if not is_meta_key(name)
        }
        assert leaking == set(), (
            f"Union labels that are not strippable — declare the union with "
            f"discriminated_union() so its tags are marked: {sorted(leaking)}"
        )

    def test_walker_finds_known_union_alternatives(self) -> None:
        """The schema walk is not vacuous — known alternatives are discovered.

        Guards the guard: if the core-schema walker silently broke (e.g. a
        pydantic upgrade renames schema keys), the test above would pass on an
        empty set. Pin a few tags that must be found.
        """
        names = _union_alternative_labels(InsightsQuery)
        assert {
            "#Filter",
            "#FrequencyFilter",
            "#Metric",
            "#CustomPropertyRef",
            "#InlineCustomProperty",
        } <= names

    def test_walker_covers_cohort_criteria_tagged_union(self) -> None:
        """The cohort-node union surfaces marked tags, not raw ``kind`` values.

        Regression guard for finding
        ``cohort-criteria-kind-tag-leaks-into-error-paths``: routing
        ``InlineCohort.criteria`` with a declarative ``Field(discriminator="kind")``
        would put the raw values (``"property"`` — a real field name
        everywhere) into ``error_location``, where nothing can safely strip
        them. Marked tags carry a prefix no field name can have.
        """
        names = _union_alternative_labels(InsightsQuery)
        assert {
            "#property",
            "#behavioral",
            "#cohort_reference",
            "#group",
        } <= names


class TestCohortCriteriaKindTagPathTranslation:
    """Cohort-criteria ``kind`` tags never leak into error paths.

    Regression tests for finding
    ``cohort-criteria-kind-tag-leaks-into-error-paths``: the declarative
    ``Field(discriminator="kind")`` on the cohort-node union made
    pydantic insert the *kind tag value* into ``error_location`` tuples,
    producing phantom path segments like
    ``group_by[0].cohort.criteria[0].property.value`` — where
    ``property`` is the union tag, not a field, and collides with
    ``PropertyCriterion``'s real ``property`` field. The union now uses
    the callable ``Discriminator(...)`` + ``Tag(<ClassName>)`` pattern
    (like the sorting models) so the inserted labels are registered
    class names that ``_error_location_to_json_path`` strips.
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
                                "kind": "group",
                                "criteria": [{"kind": "property", "property": "plan"}],
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
                                "kind": "group",
                                "criteria": [
                                    {
                                        "kind": "behavioral",
                                        "event": "Purchase",
                                        "at_least": -1,
                                        "within_days": 30,
                                    }
                                ],
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
                                "kind": "group",
                                "criteria": [{"kind": "property", "property": "plan"}],
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
                            "kind": "group",
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


def _cohort_criteria_payload(criterion: dict[str, Any] | str) -> dict[str, Any]:
    """Build an InsightsQuery payload with one inline-cohort criterion.

    Args:
        criterion: The raw ``criteria[0]`` entry (dict or scalar) to embed
            in a ``group_by`` inline cohort.

    Returns:
        A dict payload for ``InsightsQuery.model_validate``.
    """
    return {
        "events": ["L"],
        "group_by": [{"cohort": {"kind": "group", "criteria": [criterion]}}],
    }


class TestCohortNodeTagErrorMessages:
    """Cohort-node union tag failures surface kind values, not internals.

    Regression tests for finding
    ``cohort-node-union-tag-errors-leak-class-names-and-private-fn``: marking
    the tags fixed the ``error_location`` leak, but pydantic's default
    ``union_tag_invalid`` / ``union_tag_not_found`` MESSAGES would still leak
    all four criterion class names plus the routing callable's name, pointing
    self-correcting agents at ``kind="BehavioralCriterion"`` (which then fails
    the ``Literal``). The union's ``custom_error_message`` replaces them with
    the caller-facing ``kind`` values.
    """

    def test_bogus_kind_message_names_kind_values(self) -> None:
        """An unknown kind lists the four valid kind values, not class names.

        The message is the ``Discriminator``'s ``custom_error_message`` —
        a fixed "kind must be one of ..." string, so it names the valid
        kinds (guiding a self-correcting agent) without echoing the bogus
        input or leaking any internal name.
        """
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                _cohort_criteria_payload(
                    {"kind": "bogus", "property": "p", "value": "x"}
                )
            )
        (err,) = [
            e
            for e in exc_info.value.errors
            if e.path == "group_by[0].cohort.criteria[0]"
        ]
        assert "kind must be one of" in err.message, err.message
        for kind in ("'property'", "'behavioral'", "'cohort_reference'", "'group'"):
            assert kind in err.message, err.message

    @pytest.mark.parametrize(
        "criterion",
        [
            {"kind": "bogus", "property": "p", "value": "x"},
            {"negated": True},
            "not-a-dict",
            {"kind": 7},
        ],
        ids=[
            "bogus-kind",
            "missing-kind-unroutable",
            "non-dict-entry",
            "non-string-kind",
        ],
    )
    def test_no_internal_names_in_any_tag_failure_message(
        self, criterion: dict[str, Any] | str
    ) -> None:
        """No tag-failure message leaks class names or the private function."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(_cohort_criteria_payload(criterion))
        for e in exc_info.value.errors:
            assert "by_field_kind" not in e.message, e.message
            for cls_name in (
                "PropertyCriterion",
                "BehavioralCriterion",
                "CohortReferenceCriterion",
                "InlineCohort",
            ):
                assert cls_name not in e.message, e.message

    def test_missing_kind_message_names_kind_field(self) -> None:
        """A kind-less criterion is told which kind values are valid.

        Routing is by ``kind`` only, so any dict without a valid string
        ``kind`` (here a bare ``negated`` flag) is unroutable and gets
        the ``custom_error_message`` naming the ``kind`` field and its
        four valid values.
        """
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(_cohort_criteria_payload({"negated": True}))
        (err,) = [
            e
            for e in exc_info.value.errors
            if e.path == "group_by[0].cohort.criteria[0]"
        ]
        assert "kind must be one of" in err.message, err.message
        for kind in ("'property'", "'behavioral'", "'cohort_reference'", "'group'"):
            assert kind in err.message, err.message

    def test_callable_discriminators_that_return_none_set_custom_error(self) -> None:
        """Structural guard: routing discriminators carry a ``custom_error_message``.

        Replaces the deleted rewrite-registry guard on the MESSAGE side.
        Any tagged union reachable from the four query models that routes
        through a callable ``Discriminator`` which can return ``None``
        (unroutable input) must set ``custom_error_message`` on that
        ``Discriminator`` — otherwise pydantic's default
        ``union_tag_not_found`` message leaks the callable's private name
        and the ``Tag`` class names. Discriminators annotated to return a
        bare ``str`` (the total ``_str_or`` / ``_flow_event`` family)
        never emit those errors and are exempt.
        """
        import inspect

        offenders: set[str] = set()
        for model_cls in ALL_MODELS:
            for node in _iter_schema_nodes(model_cls.__pydantic_core_schema__):
                if node.get("type") != "tagged-union":
                    continue
                discriminator = node.get("discriminator")
                if not callable(discriminator):
                    continue
                returns_none = "None" in str(
                    inspect.signature(discriminator).return_annotation
                )
                custom = node.get("custom_error_message") or node.get(
                    "custom_error_type"
                )
                if returns_none and not custom:
                    offenders.add(discriminator.__name__)
        assert offenders == set(), (
            f"Callable discriminators that can return None without a "
            f"custom_error_message (their private names will leak into "
            f"caller-facing messages): {sorted(offenders)}"
        )

    def test_walker_finds_cohort_node_discriminator(self) -> None:
        """The structural guard above is not vacuous.

        Guards the guard: the cohort-node union's callable discriminator
        must be discovered by the tagged-union walk. It routes by reading the
        ``kind`` field, so its name is ``by_field_kind``.
        """
        names = {
            node["discriminator"].__name__
            for model_cls in ALL_MODELS
            for node in _iter_schema_nodes(model_cls.__pydantic_core_schema__)
            if node.get("type") == "tagged-union"
            and callable(node.get("discriminator"))
        }
        assert "by_field_kind" in names


class TestCustomPropertyExtraKeySchemaRuntimeParity:
    """Extra keys on custom-property dicts are rejected by BOTH layers.

    Regression tests for finding
    ``custom-property-dataclasses-missing-additionalProperties-false``:
    ``PropertyInput``, ``InlineCustomProperty``, and ``CustomPropertyRef``
    were plain stdlib dataclasses, so their ``$defs`` OMITTED
    ``additionalProperties: false`` — advertising "extra keys allowed" —
    while ``model_validate`` rejected extras with ``Unexpected keyword
    argument``. A schema-valid LLM payload therefore failed at runtime.
    The three are now pydantic dataclasses with ``extra="forbid"``, so
    the generated schema and the runtime agree: extras fail both, and
    the clean payloads pass both.
    """

    EXTRA_KEY_PAYLOADS: ClassVar[dict[str, dict[str, Any]]] = {
        "CustomPropertyRef": {
            "events": ["Login"],
            "group_by": [{"property": {"id": 42, "bogus": 1}}],
        },
        "InlineCustomProperty": {
            "events": ["Login"],
            "group_by": [
                {
                    "property": {
                        "formula": "A",
                        "inputs": {"A": {"name": "p"}},
                        "bogus": 1,
                    }
                }
            ],
        },
        "PropertyInput": {
            "events": ["Login"],
            "group_by": [
                {
                    "property": {
                        "formula": "A",
                        "inputs": {"A": {"name": "p", "bogus": 1}},
                    }
                }
            ],
        },
    }
    """One extra-key payload per formerly-open custom-property type."""

    CLEAN_PAYLOADS: ClassVar[dict[str, dict[str, Any]]] = {
        "CustomPropertyRef": {
            "events": ["Login"],
            "group_by": [{"property": {"id": 42}}],
        },
        "InlineCustomProperty": {
            "events": ["Login"],
            "group_by": [
                {"property": {"formula": "A", "inputs": {"A": {"name": "p"}}}}
            ],
        },
    }
    """The same payloads without the extra key (positive controls)."""

    @pytest.mark.parametrize("type_name", sorted(EXTRA_KEY_PAYLOADS), ids=str)
    def test_extra_key_rejected_by_schema_and_runtime(self, type_name: str) -> None:
        """A bogus extra key fails schema validation AND model_validate."""
        payload = self.EXTRA_KEY_PAYLOADS[type_name]
        schema_errors = list(
            Draft202012Validator(InsightsQuery.model_json_schema()).iter_errors(payload)
        )
        assert schema_errors != [], (
            f"{type_name}: schema accepted an extra key the runtime rejects"
        )
        with pytest.raises(BookmarkValidationError):
            InsightsQuery.model_validate(payload)

    @pytest.mark.parametrize("type_name", sorted(CLEAN_PAYLOADS), ids=str)
    def test_clean_payload_accepted_by_schema_and_runtime(self, type_name: str) -> None:
        """The extra-free payload passes schema validation AND model_validate."""
        payload = self.CLEAN_PAYLOADS[type_name]
        schema_errors = list(
            Draft202012Validator(InsightsQuery.model_json_schema()).iter_errors(payload)
        )
        assert schema_errors == [], [e.message for e in schema_errors]
        query = InsightsQuery.model_validate(payload)
        assert isinstance(query, InsightsQuery)

    @pytest.mark.parametrize(
        "def_name", ["PropertyInput", "InlineCustomProperty", "CustomPropertyRef"]
    )
    def test_defs_advertise_additional_properties_false(self, def_name: str) -> None:
        """Each of the three ``$defs`` renders ``additionalProperties: false``."""
        definition = InsightsQuery.model_json_schema()["$defs"][def_name]
        assert definition.get("additionalProperties") is False, definition


class TestCustomPropertyRefIdSchemaRuntimeParity:
    """A coercible ``CustomPropertyRef.id`` is rejected by BOTH layers.

    Regression tests for finding ``reject-coerced-custom-property-ids``:
    ``id`` was a plain ``int``, so pydantic coerced before the positive-ID
    rule ever ran. ``id=True`` became custom property ``1`` and ``id="42"``
    became ``42`` — both real, unrelated properties — while the generated
    schema rejected the same inputs as not-an-integer. That is the silent
    kind of divergence: the query succeeds and answers the wrong question.
    CP1 cannot catch it either, because by the time it sees the value the
    coercion has already produced a legitimate positive ID.

    ``id`` is now ``_PositiveStrictIntSchema``, whose ``StrictInt`` refuses
    the coercion outright.
    """

    COERCIBLE_IDS: ClassVar[dict[str, Any]] = {
        "bool": True,
        "numeric string": "42",
    }
    """Inputs the schema calls non-integers and pydantic used to convert.

    ``42.0`` is deliberately absent: JSON Schema counts a whole float as an
    integer, so it is not a both-layers-reject case. It has its own test.
    """

    @staticmethod
    def _payload(id_value: Any) -> dict[str, Any]:
        """Build an insights payload whose group_by references a custom property.

        Args:
            id_value: The value to place at ``group_by[0].property.id``.

        Returns:
            A payload valid apart from the ``id`` under test.
        """
        return {
            "events": ["Login"],
            "group_by": [{"property": {"id": id_value}, "property_type": "number"}],
        }

    @staticmethod
    def _stored_id(query: InsightsQuery) -> int:
        """Read back the custom-property ID a validated query kept.

        Args:
            query: A query built from :meth:`_payload`.

        Returns:
            The ``id`` stored at ``group_by[0].property``.
        """
        assert query.group_by is not None
        breakdown = query.group_by[0]
        assert isinstance(breakdown, GroupBy)
        prop = breakdown.property
        assert isinstance(prop, CustomPropertyRef)
        return prop.id

    @pytest.mark.parametrize("kind", sorted(COERCIBLE_IDS), ids=str)
    def test_coercible_id_rejected_by_schema_and_runtime(self, kind: str) -> None:
        """A non-integer id fails schema validation AND model_validate."""
        payload = self._payload(self.COERCIBLE_IDS[kind])

        schema_errors = list(
            Draft202012Validator(InsightsQuery.model_json_schema()).iter_errors(payload)
        )
        assert schema_errors != [], f"{kind}: schema accepted a non-integer id"

        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(payload)
        assert any(
            e.path == "group_by[0].property.id" for e in exc_info.value.errors
        ), [e.path for e in exc_info.value.errors]

    def test_positive_id_accepted_by_schema_and_runtime(self) -> None:
        """A genuine positive integer still passes both layers (positive control)."""
        payload = self._payload(42)

        schema_errors = list(
            Draft202012Validator(InsightsQuery.model_json_schema()).iter_errors(payload)
        )
        assert schema_errors == [], [e.message for e in schema_errors]
        query = InsightsQuery.model_validate(payload)
        assert self._stored_id(query) == 42

    @pytest.mark.parametrize("id_value", [0, -5], ids=["zero", "negative"])
    def test_non_positive_id_is_the_known_remaining_gap(self, id_value: int) -> None:
        """A non-positive id still passes ``model_validate``; CP1 catches it later.

        Pins the gap the ``TODO`` on ``CustomPropertyRef.id`` describes, so
        closing it is a deliberate edit here rather than a silent change.
        ``StrictInt`` fixes the *type*; ``exclusiveMinimum`` on the shared
        alias is still schema-only, so the *range* is enforced by CP1 at
        ``build_params`` instead of by the model.

        Unlike the coercion cases this is not silent — the caller does get a
        ``CP1_INVALID_ID`` error, just from a later layer.
        """
        payload = self._payload(id_value)

        schema_errors = list(
            Draft202012Validator(InsightsQuery.model_json_schema()).iter_errors(payload)
        )
        assert schema_errors != [], "schema should reject a non-positive id"

        query = InsightsQuery.model_validate(payload)
        assert self._stored_id(query) == id_value

    def test_whole_float_id_diverges_the_other_way(self) -> None:
        """``42.0`` is schema-valid but ``StrictInt`` rejects it.

        JSON Schema treats a float with no fractional part as an integer, so
        the schema accepts ``42.0`` while strict mode does not. This is the
        divergence pointing the opposite way, and it is not new: every field
        already using ``_PositiveStrictIntSchema`` behaves the same — see
        ``CohortBreakdown.cohort``. Pinned so the shared contract is visible
        rather than folklore.
        """
        payload = self._payload(42.0)

        schema_errors = list(
            Draft202012Validator(InsightsQuery.model_json_schema()).iter_errors(payload)
        )
        assert schema_errors == [], "JSON Schema counts a whole float as an integer"

        with pytest.raises(BookmarkValidationError):
            InsightsQuery.model_validate(payload)


class TestCohortMetricHiddenAlternativeErrorConsistency:
    """CohortMetric.cohort errors never contradict its integer-only schema.

    Regression tests for finding
    ``cohort-metric-hidden-alternative-error-contradicts-integer-only-schema``:
    the ``SkipJsonSchema[CohortDefinition]`` alternative correctly hides the
    inline shape from the JSON schema, but its ``model_type`` error
    (``"Input should be a valid dictionary or instance of InlineCohort"``)
    still reached dict/JSON callers — telling a schema-driven agent to
    send a shape the schema says doesn't exist, and leaking the
    ``InlineCohort`` class name into a caller-facing message. The cohort
    field now routes through a discriminated union so a non-dict input
    only ever gets the schema-consistent integer diagnosis.
    """

    def test_string_cohort_yields_integer_only_diagnosis(self) -> None:
        """cohort='5' surfaces only the integer diagnosis for the field."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate({"events": [{"cohort": "5", "name": "PU"}]})
        errors = exc_info.value.errors
        cohort_errors = [e for e in errors if e.path == "events[0].cohort"]
        assert any("valid integer" in e.message for e in cohort_errors)
        for e in errors:
            assert "InlineCohort" not in e.message, e.message
            assert "dictionary or instance" not in e.message, e.message

    def test_valid_inline_cohort_keeps_targeted_500_rejection(self) -> None:
        """A well-formed inline definition still gets the curated message."""
        with pytest.raises(BookmarkValidationError, match="server returns 500"):
            InsightsQuery.model_validate(
                {
                    "events": [
                        {
                            "cohort": {
                                "kind": "group",
                                "criteria": [
                                    {
                                        "kind": "property",
                                        "property": "plan",
                                        "value": "premium",
                                    }
                                ],
                            }
                        }
                    ]
                }
            )

    def test_cohort_breakdown_inline_alternative_is_reachable(self) -> None:
        """CohortBreakdown.cohort routes a structured dict to the inline alternative.

        The breakdown schema advertises the ``InlineCohort`` ``$ref``, and
        the shared discriminator routes a dict to that alternative — so a malformed
        inline cohort reports field-level errors under the cohort path
        (proving the alternative is reachable) with no ``InlineCohort`` class name
        leaked into any message.
        """
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {
                    "events": ["Login"],
                    "group_by": [
                        {
                            "cohort": {
                                "kind": "group",
                                "operator": "bogus",
                                "criteria": [
                                    {"kind": "cohort_reference", "cohort_id": 7}
                                ],
                            }
                        }
                    ],
                }
            )
        paths = {e.path for e in exc_info.value.errors}
        assert "group_by[0].cohort.operator" in paths, paths
        for e in exc_info.value.errors:
            assert "InlineCohort" not in e.message, e.message

    def test_cohort_breakdown_scalar_gets_integer_diagnosis(self) -> None:
        """A non-structured value routes only to the integer alternative (like CohortMetric)."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {"events": ["Login"], "group_by": [{"cohort": "5"}]}
            )
        cohort_errors = [
            e for e in exc_info.value.errors if e.path == "group_by[0].cohort"
        ]
        assert any("valid integer" in e.message for e in cohort_errors), cohort_errors


class TestPropertyCriterionNoValueOperatorValueRejected:
    """Presence operators reject a supplied value instead of discarding it.

    Regression tests for finding
    ``property-criterion-silently-ignores-value-on-is-set-operators``:
    mirrors ``TestFilterNoValueOperatorValueRejected`` — ``Filter`` now
    rejects a supplied value on ``is set`` / ``is not set``, but
    ``PropertyCriterion(kind="property", property="country", value="US", operator="is_set")``
    was accepted, ran a bare existence check, and shipped the ignored
    operand into the wire selector. Because ``value`` is a required field
    (the schema keeps it required for the comparison operators), the
    presence operators accept only the documented ``""`` sentinel.
    """

    @pytest.mark.parametrize("operator", ["is_set", "is_not_set"])
    def test_presence_operator_with_value_rejected(self, operator: str) -> None:
        """Each presence operator rejects a caller-supplied value."""
        with pytest.raises(ValidationError, match="does not take a value"):
            PropertyCriterion(
                kind="property", property="country", value="US", operator=operator
            )

    def test_is_set_error_suggests_equals(self) -> None:
        """The is_set rejection points the caller at operator 'equals'."""
        with pytest.raises(ValidationError, match="did you mean operator 'equals'"):
            PropertyCriterion(
                kind="property", property="country", value="US", operator="is_set"
            )

    def test_error_reports_original_value(self) -> None:
        """The rejection message echoes the discarded value."""
        with pytest.raises(ValidationError, match="'US'"):
            PropertyCriterion(
                kind="property", property="country", value="US", operator="is_set"
            )

    @pytest.mark.parametrize("operator", ["is_set", "is_not_set"])
    def test_empty_string_sentinel_still_accepted(self, operator: str) -> None:
        """The documented '' sentinel keeps presence criteria constructible."""
        c = PropertyCriterion(
            kind="property", property="country", value="", operator=operator
        )
        assert c.value == ""
        assert c.to_criteria() is not None

    def test_non_string_value_also_rejected(self) -> None:
        """Non-string junk values (e.g. 0) are rejected too."""
        with pytest.raises(ValidationError, match="does not take a value"):
            PropertyCriterion(
                kind="property", property="country", value=0, operator="is_set"
            )

    def test_comparison_operators_unaffected(self) -> None:
        """Comparison operators keep requiring and accepting real values."""
        c = PropertyCriterion(kind="property", property="plan", value="premium")
        assert c.value == "premium"

    def test_insights_model_path_raises_bookmark_error(self) -> None:
        """The Insights model path surfaces BookmarkValidationError."""
        with pytest.raises(BookmarkValidationError, match="does not take a value"):
            InsightsQuery.model_validate(
                _cohort_criteria_payload(
                    {
                        "kind": "property",
                        "property": "country",
                        "value": "US",
                        "operator": "is_set",
                    }
                )
            )


class TestDiscriminatedUnionRouting:
    """Callable-``Discriminator`` unions route to one alternative across every field.

    Locks the discriminated-union behavior that replaced the hand-rolled
    prune pipeline: a malformed entry yields ONE located error (only the
    matched alternative validates), an unroutable entry gets the union's
    ``custom_error_message`` located at the item, string shorthands still
    validate, and the discriminators route model instances on the
    serialization path (``model_dump`` round-trips).
    """

    def test_malformed_event_dict_yields_single_located_error(self) -> None:
        """A bad math on a Metric dict is one error at events[0].math."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(
                {"events": [{"event": "Login", "math": "totl"}]}
            )
        errors = exc_info.value.errors
        assert [e.path for e in errors] == ["events[0].math"], errors

    @pytest.mark.parametrize(
        ("payload", "path", "needle"),
        [
            ({"events": [123]}, "events[0]", "each event must be"),
            (
                {"events": ["L"], "where": [123]},
                "where[0]",
                "each where entry must be",
            ),
            (
                {"events": ["L"], "group_by": [123]},
                "group_by[0]",
                "each group_by must be",
            ),
        ],
        ids=["events", "where", "group_by"],
    )
    def test_unroutable_entry_gets_custom_message_at_item(
        self, payload: dict[str, Any], path: str, needle: str
    ) -> None:
        """An unroutable list entry yields the custom message located at the item."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(payload)
        (err,) = [e for e in exc_info.value.errors if e.path == path]
        assert needle in err.message, err.message

    @pytest.mark.parametrize(
        "build",
        [
            lambda: InsightsQuery(events=["Login"], group_by=["plan"], where=None),
            lambda: FunnelQuery(steps=["Signup", "Purchase"], group_by=["plan"]),
            lambda: RetentionQuery(born_event="Signup", return_event="Login"),
            lambda: FlowQuery(event=["Login", "Logout"], segments=["plan"]),
        ],
        ids=["insights", "funnel", "retention", "flow"],
    )
    def test_string_shorthands_still_validate(
        self, build: Callable[[], BaseModel]
    ) -> None:
        """Bare-string shorthands construct on every model."""
        assert isinstance(build(), BaseModel)

    def test_flow_event_list_of_strings_validates(self) -> None:
        """The flow ``event`` list-of-strings alternative routes and validates."""
        q = FlowQuery(event=["Login", "Purchase"])
        assert q.event == ["Login", "Purchase"]

    def test_serialization_routes_every_model_instance_alternative(self) -> None:
        """model_dump() routes a model instance through every discriminator alternative.

        The discriminators run on the serialization path too — pydantic
        passes the model instance, not a dict. If any discriminator's
        ``isinstance`` branch were missing, ``model_dump`` would raise a
        serialization error. Includes ``Filter`` (whose dump uses private
        field names, so it is excluded from the re-validate round-trip
        below).
        """
        q = InsightsQuery(
            events=[
                Metric("Login", math="unique"),
                CohortMetric(7, "Power"),
                Formula("A / B", label="ratio"),
            ],
            group_by=[
                GroupBy("plan"),
                CohortBreakdown(7),
                FrequencyBreakdown("Purchase"),
            ],
            where=[Filter.equals("country", "US"), FrequencyFilter("Login", value=3)],
        )
        dumped = q.model_dump()
        assert len(dumped["events"]) == 3
        assert len(dumped["group_by"]) == 3
        assert len(dumped["where"]) == 2

    @pytest.mark.parametrize(
        "query",
        [
            InsightsQuery(
                events=[
                    Metric("Login", math="unique"),
                    CohortMetric(7, "Power"),
                    Formula("A / B", label="ratio"),
                ],
                group_by=[
                    GroupBy("plan"),
                    CohortBreakdown(7),
                    FrequencyBreakdown("Purchase"),
                ],
                where=[FrequencyFilter("Login", value=3)],
            ),
            FunnelQuery(
                steps=[FunnelStep("Signup"), FunnelStep("Purchase")],
                group_by=[GroupBy("plan"), CohortBreakdown(7)],
                exclusions=[Exclusion("Refund")],
                holding_constant=[HoldingConstant("country")],
            ),
            RetentionQuery(
                born_event=RetentionEvent("Signup"),
                return_event=RetentionEvent("Login"),
                group_by=[GroupBy("plan")],
            ),
            FlowQuery(
                event=[FlowStep("Login"), "Purchase"], segments=[GroupBy("plan")]
            ),
        ],
        ids=["insights", "funnel", "retention", "flow"],
    )
    def test_model_instance_dump_revalidate_round_trip(self, query: BaseModel) -> None:
        """A model built from instances dumps and re-validates to an equal model.

        Covers every discriminated alternative whose serialized form re-routes on
        validation (``where`` uses ``FrequencyFilter`` — ``Filter`` dumps
        private field names and is covered by the dump-only test above,
        matching ``TestRoundTrip``'s handling).
        """
        dumped = query.model_dump()
        reparsed = type(query).model_validate(dumped)
        assert reparsed == query


class TestCohortNodeKindSchemaRuntimeParity:
    """``kind`` is required by BOTH the generated schema and the runtime.

    Regression tests for finding
    ``cohort-kind-optional-in-schema-required-at-runtime``: every
    criterion arm rendered ``kind`` as a *defaulted* (non-required)
    property, so a schema-driven consumer that omitted it produced a
    payload with zero JSON Schema errors that ``model_validate`` then
    rejected — the discriminator routes by ``kind`` alone and returns
    ``None`` for a kind-less dict. ``kind`` is now required everywhere,
    so the advertised contract and the validator agree in both
    directions.
    """

    ARM_DEFS: ClassVar[tuple[str, ...]] = (
        "PropertyCriterion",
        "BehavioralCriterion",
        "CohortReferenceCriterion",
        "InlineCohort",
    )
    """Every ``$def`` participating in the cohort-node union."""

    KINDLESS_CRITERIA: ClassVar[dict[str, dict[str, Any]]] = {
        "PropertyCriterion": {"property": "plan", "value": "premium"},
        "BehavioralCriterion": {"event": "Purchase", "at_least": 3, "within_days": 30},
        "CohortReferenceCriterion": {"cohort_id": 456},
        "InlineCohort": {
            "criteria": [{"kind": "property", "property": "p", "value": 1}]
        },
    }
    """One otherwise-valid, ``kind``-less criterion per arm."""

    @pytest.mark.parametrize("def_name", ARM_DEFS, ids=str)
    def test_def_requires_kind(self, def_name: str) -> None:
        """Each criterion ``$def`` lists ``kind`` in ``required``."""
        definition = InsightsQuery.model_json_schema()["$defs"][def_name]
        assert "kind" in definition["required"], (
            f"{def_name}: schema advertises kind as optional, "
            f"but the discriminator requires it"
        )

    @pytest.mark.parametrize("arm", sorted(KINDLESS_CRITERIA), ids=str)
    def test_kindless_criterion_rejected_by_schema_and_runtime(self, arm: str) -> None:
        """A ``kind``-less criterion fails schema validation AND model_validate."""
        payload = _cohort_criteria_payload(self.KINDLESS_CRITERIA[arm])
        schema_errors = list(
            Draft202012Validator(InsightsQuery.model_json_schema()).iter_errors(payload)
        )
        assert schema_errors != [], (
            f"{arm}: schema accepted a kind-less criterion the runtime rejects"
        )
        with pytest.raises(BookmarkValidationError):
            InsightsQuery.model_validate(payload)

    @pytest.mark.parametrize("arm", sorted(KINDLESS_CRITERIA), ids=str)
    def test_kinded_criterion_accepted_by_schema_and_runtime(self, arm: str) -> None:
        """The same criterion WITH its ``kind`` passes both layers."""
        kind = InsightsQuery.model_json_schema()["$defs"][arm]["properties"]["kind"][
            "const"
        ]
        payload = _cohort_criteria_payload(
            {**self.KINDLESS_CRITERIA[arm], "kind": kind}
        )
        schema_errors = list(
            Draft202012Validator(InsightsQuery.model_json_schema()).iter_errors(payload)
        )
        assert schema_errors == [], [e.message for e in schema_errors]
        assert isinstance(InsightsQuery.model_validate(payload), InsightsQuery)


class TestCohortNodeMissingOrBogusKind:
    """Cohort criteria with a missing or bogus ``kind`` fail cleanly.

    Routing is by ``kind`` only, so a criterion without a valid string
    ``kind`` is unroutable and gets the ``custom_error_message`` — with no
    discriminator function name or criterion class name leaked.
    """

    @pytest.mark.parametrize(
        "criterion",
        [{"property": "plan", "value": "pro"}, {"kind": "bogus", "cohort_id": 7}],
        ids=["missing-kind", "bogus-kind"],
    )
    def test_missing_or_bogus_kind_yields_clean_error(
        self, criterion: dict[str, Any]
    ) -> None:
        """A kind-less or bogus-kind criterion fails with the kind message."""
        with pytest.raises(BookmarkValidationError) as exc_info:
            InsightsQuery.model_validate(_cohort_criteria_payload(criterion))
        (err,) = [
            e
            for e in exc_info.value.errors
            if e.path == "group_by[0].cohort.criteria[0]"
        ]
        assert "kind must be one of" in err.message, err.message
        assert "by_field_kind" not in err.message
        for cls_name in (
            "PropertyCriterion",
            "BehavioralCriterion",
            "CohortReferenceCriterion",
            "InlineCohort",
        ):
            assert cls_name not in err.message, err.message

    def test_direct_construction_takes_kind_explicitly(self) -> None:
        """PropertyCriterion / InlineCohort take kind explicitly on the Python path."""
        crit = PropertyCriterion(kind="property", property="plan", value="pro")
        assert crit.kind == "property"
        cohort = InlineCohort(kind="group", criteria=[crit])
        assert cohort.kind == "group"
        assert cohort.criteria[0] is crit
