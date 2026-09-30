"""Unit tests for the inline behavior and metric values.

Covers ``CustomEventRef``, ``SimpleBehavior``, ``FunnelBehavior``,
``RetentionBehavior``, ``FunnelMetric``, and ``RetentionMetric``: defaults,
immutability, parameter names shared with the engine methods, and the
construction-time guards (``BH1_STEP_COUNT``, ``BH2_EMPTY_EVENT``,
``BH3_PROPERTY_MATH``, and the reused funnel property-math codes).
"""

from __future__ import annotations

import dataclasses
import inspect

import pytest

from mixpanel_headless.exceptions import (
    CODED_GUARD_REGISTRY,
    CODED_GUARD_TWIN_CODES,
    ParamValidationError,
)
from mixpanel_headless.types import (
    CustomEventRef,
    CustomPropertyRef,
    Exclusion,
    Filter,
    FunnelBehavior,
    FunnelMetric,
    FunnelStep,
    HoldingConstant,
    RetentionBehavior,
    RetentionEvent,
    RetentionMetric,
    SimpleBehavior,
)
from mixpanel_headless.workspace import Workspace


def _funnel() -> FunnelBehavior:
    """Return a minimal valid two-step funnel behavior."""
    return FunnelBehavior(["Signup", "Purchase"])


def _retention() -> RetentionBehavior:
    """Return a minimal valid retention behavior."""
    return RetentionBehavior("Signup", "Login")


# =============================================================================
# CustomEventRef
# =============================================================================


class TestCustomEventRef:
    """``CustomEventRef`` holds the id of a saved custom event."""

    def test_holds_id(self) -> None:
        """The id is stored unchanged."""
        assert CustomEventRef(42).id == 42

    def test_immutable(self) -> None:
        """A reference cannot be changed after construction."""
        ref = CustomEventRef(42)
        with pytest.raises(dataclasses.FrozenInstanceError):
            ref.id = 7  # type: ignore[misc]

    def test_equality_by_id(self) -> None:
        """Two references with the same id are equal and hash the same."""
        assert CustomEventRef(42) == CustomEventRef(42)
        assert hash(CustomEventRef(42)) == hash(CustomEventRef(42))
        assert CustomEventRef(42) != CustomEventRef(43)


# =============================================================================
# SimpleBehavior
# =============================================================================


class TestSimpleBehavior:
    """``SimpleBehavior`` is one or more events counted as one behavior."""

    def test_defaults(self) -> None:
        """Filters default to none, combined with AND."""
        behavior = SimpleBehavior(["Login"])
        assert behavior.events == ["Login"]
        assert behavior.filters is None
        assert behavior.filters_combinator == "all"

    def test_accepts_names_custom_events_and_steps(self) -> None:
        """Events can be names, custom event references, or steps with filters."""
        step = FunnelStep("Purchase", filters=[Filter.greater_than("amount", 5)])
        behavior = SimpleBehavior(
            ["Login", CustomEventRef(7), step],
            filters=[Filter.equals("platform", "ios")],
            filters_combinator="any",
        )
        assert behavior.events == ["Login", CustomEventRef(7), step]
        assert behavior.filters_combinator == "any"

    def test_immutable(self) -> None:
        """A behavior cannot be changed after construction."""
        behavior = SimpleBehavior(["Login"])
        with pytest.raises(dataclasses.FrozenInstanceError):
            behavior.events = ["Signup"]  # type: ignore[misc]

    def test_no_events_raises_bh1(self) -> None:
        """A simple behavior with no events raises BH1_STEP_COUNT."""
        with pytest.raises(ParamValidationError) as excinfo:
            SimpleBehavior([])
        assert excinfo.value.code == "BH1_STEP_COUNT"
        assert "at least 1 event" in excinfo.value.message

    @pytest.mark.parametrize("event", ["", "   ", "\t"])
    def test_blank_event_name_raises_bh2(self, event: str) -> None:
        """A blank event name raises BH2_EMPTY_EVENT and names its position."""
        with pytest.raises(ParamValidationError) as excinfo:
            SimpleBehavior(["Login", event])
        assert excinfo.value.code == "BH2_EMPTY_EVENT"
        assert "SimpleBehavior.events[1]" in excinfo.value.message

    def test_control_character_raises_ev2(self) -> None:
        """An event name with a control character raises EV2_CONTROL_CHAR_EVENT."""
        with pytest.raises(ParamValidationError) as excinfo:
            SimpleBehavior(["Log\x00in"])
        assert excinfo.value.code == "EV2_CONTROL_CHAR_EVENT"
        assert "SimpleBehavior.events[0]" in excinfo.value.message


# =============================================================================
# FunnelBehavior
# =============================================================================


class TestFunnelBehavior:
    """``FunnelBehavior`` is an ordered list of two or more steps."""

    def test_defaults_match_query_funnel(self) -> None:
        """Defaults: a 14-day window, loose order, no exclusions or constants."""
        behavior = _funnel()
        assert behavior.steps == ["Signup", "Purchase"]
        assert behavior.conversion_window == 14
        assert behavior.conversion_window_unit == "day"
        assert behavior.order == "loose"
        assert behavior.exclusions is None
        assert behavior.holding_constant is None
        assert behavior.reentry_mode is None

    def test_all_fields_set(self) -> None:
        """Every field accepts the values that ``query_funnel`` accepts."""
        behavior = FunnelBehavior(
            [FunnelStep("Signup"), "Purchase"],
            conversion_window=2,
            conversion_window_unit="week",
            order="any",
            exclusions=["Logout", Exclusion("Refund", from_step=1)],
            holding_constant=["platform", HoldingConstant("plan", "people")],
            reentry_mode="basic",
        )
        assert behavior.conversion_window == 2
        assert behavior.conversion_window_unit == "week"
        assert behavior.order == "any"
        assert behavior.exclusions == ["Logout", Exclusion("Refund", from_step=1)]
        assert behavior.reentry_mode == "basic"

    def test_holding_constant_accepts_one_value(self) -> None:
        """``holding_constant`` takes one name or object, as in ``query_funnel``."""
        assert FunnelBehavior(["A", "B"], holding_constant="platform")
        assert FunnelBehavior(["A", "B"], holding_constant=HoldingConstant("plan"))

    def test_immutable(self) -> None:
        """A behavior cannot be changed after construction."""
        behavior = _funnel()
        with pytest.raises(dataclasses.FrozenInstanceError):
            behavior.order = "any"  # type: ignore[misc]

    @pytest.mark.parametrize("steps", [[], ["Signup"], [FunnelStep("Signup")]])
    def test_fewer_than_two_steps_raises_bh1(
        self, steps: list[str | FunnelStep]
    ) -> None:
        """A funnel behavior with fewer than two steps raises BH1_STEP_COUNT."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelBehavior(steps)
        assert excinfo.value.code == "BH1_STEP_COUNT"
        assert "at least 2 steps" in excinfo.value.message

    @pytest.mark.parametrize("event", ["", "  "])
    def test_blank_step_raises_bh2(self, event: str) -> None:
        """A blank step name raises BH2_EMPTY_EVENT and names its position."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelBehavior(["Signup", event])
        assert excinfo.value.code == "BH2_EMPTY_EVENT"
        assert "FunnelBehavior.steps[1]" in excinfo.value.message

    def test_control_character_step_raises_ev2(self) -> None:
        """A step name with a control character raises EV2_CONTROL_CHAR_EVENT."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelBehavior(["Sign\x07up", "Purchase"])
        assert excinfo.value.code == "EV2_CONTROL_CHAR_EVENT"

    def test_step_count_is_checked_before_step_names(self) -> None:
        """With one blank step the count rule is reported first."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelBehavior([""])
        assert excinfo.value.code == "BH1_STEP_COUNT"

    def test_blank_exclusion_name_raises_ev1(self) -> None:
        """A blank exclusion name raises the ``Exclusion`` code EV1_EMPTY_EVENT."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelBehavior(["A", "B"], exclusions=[" "])
        assert excinfo.value.code == "EV1_EMPTY_EVENT"

    @pytest.mark.parametrize("value", ["", ["platform", " "]])
    def test_blank_holding_constant_raises_hc1(
        self, value: str | list[str | HoldingConstant]
    ) -> None:
        """A blank property to hold constant raises HC1_EMPTY_PROPERTY."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelBehavior(["A", "B"], holding_constant=value)
        assert excinfo.value.code == "HC1_EMPTY_PROPERTY"


# =============================================================================
# RetentionBehavior
# =============================================================================


class TestRetentionBehavior:
    """``RetentionBehavior`` is a born event and a return event."""

    def test_defaults_match_query_retention(self) -> None:
        """Defaults: weekly buckets aligned to birth, server default for the rest."""
        behavior = _retention()
        assert behavior.born_event == "Signup"
        assert behavior.return_event == "Login"
        assert behavior.retention_unit == "week"
        assert behavior.alignment == "birth"
        assert behavior.bucket_sizes is None
        assert behavior.unbounded_mode is None

    def test_all_fields_set(self) -> None:
        """Every field accepts the values that ``query_retention`` accepts."""
        born = RetentionEvent("Signup", filters=[Filter.equals("source", "ads")])
        behavior = RetentionBehavior(
            born,
            RetentionEvent("Login"),
            retention_unit="week",
            alignment="interval_start",
            bucket_sizes=[1, 7, 30],
            unbounded_mode="carry_forward",
        )
        assert behavior.born_event == born
        assert behavior.retention_unit == "week"
        assert behavior.alignment == "interval_start"
        assert behavior.bucket_sizes == [1, 7, 30]
        assert behavior.unbounded_mode == "carry_forward"

    def test_immutable(self) -> None:
        """A behavior cannot be changed after construction."""
        behavior = _retention()
        with pytest.raises(dataclasses.FrozenInstanceError):
            behavior.alignment = "interval_start"  # type: ignore[misc]

    @pytest.mark.parametrize(
        ("born", "returning", "field"),
        [("", "Login", "born_event"), ("Signup", "  ", "return_event")],
    )
    def test_blank_event_raises_bh2(
        self, born: str, returning: str, field: str
    ) -> None:
        """A blank born or return event raises BH2_EMPTY_EVENT and names the field."""
        with pytest.raises(ParamValidationError) as excinfo:
            RetentionBehavior(born, returning)
        assert excinfo.value.code == "BH2_EMPTY_EVENT"
        assert f"RetentionBehavior.{field}" in excinfo.value.message

    def test_control_character_raises_ev2(self) -> None:
        """An event name with a control character raises EV2_CONTROL_CHAR_EVENT."""
        with pytest.raises(ParamValidationError) as excinfo:
            RetentionBehavior("Signup", "Log\x1fin")
        assert excinfo.value.code == "EV2_CONTROL_CHAR_EVENT"


# =============================================================================
# FunnelMetric
# =============================================================================


class TestFunnelMetric:
    """``FunnelMetric`` measures a funnel behavior as one metric."""

    def test_defaults(self) -> None:
        """Defaults: unique conversion rate over the whole funnel."""
        metric = FunnelMetric(_funnel())
        assert metric.behavior == _funnel()
        assert metric.math == "conversion_rate_unique"
        assert metric.property is None
        assert metric.step_index is None
        assert metric.label is None

    def test_all_fields_set(self) -> None:
        """A property math with a property, a step, and a label."""
        metric = FunnelMetric(
            _funnel(),
            math="average",
            property=CustomPropertyRef(9),
            step_index=1,
            label="Average cart",
        )
        assert metric.math == "average"
        assert metric.property == CustomPropertyRef(9)
        assert metric.step_index == 1
        assert metric.label == "Average cart"

    def test_immutable(self) -> None:
        """A metric cannot be changed after construction."""
        metric = FunnelMetric(_funnel())
        with pytest.raises(dataclasses.FrozenInstanceError):
            metric.math = "unique"  # type: ignore[misc]

    @pytest.mark.parametrize("math", ["average", "median", "p90", "histogram"])
    def test_property_math_without_property_raises_f10(self, math: str) -> None:
        """A property math without a property raises F10_MATH_MISSING_PROPERTY."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelMetric(_funnel(), math=math)  # type: ignore[arg-type]
        assert excinfo.value.code == "F10_MATH_MISSING_PROPERTY"
        assert f"FunnelMetric math={math!r} requires a property" in (
            excinfo.value.message
        )

    @pytest.mark.parametrize(
        "math", ["conversion_rate_unique", "conversion_rate_session", "unique"]
    )
    def test_rate_or_count_math_with_property_raises_f11(self, math: str) -> None:
        """A math that takes no property raises F11_MATH_REJECTS_PROPERTY."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelMetric(_funnel(), math=math, property="amount")  # type: ignore[arg-type]
        assert excinfo.value.code == "F11_MATH_REJECTS_PROPERTY"
        assert "does not take a property" in excinfo.value.message
        assert "'average'" in excinfo.value.message

    @pytest.mark.parametrize("prop", [None, "amount"])
    def test_total_takes_an_optional_property(self, prop: str | None) -> None:
        """``total`` counts events without a property and sums one with it."""
        assert FunnelMetric(_funnel(), math="total", property=prop).property == prop


# =============================================================================
# RetentionMetric
# =============================================================================


class TestRetentionMetric:
    """``RetentionMetric`` measures a retention behavior as one metric."""

    def test_defaults(self) -> None:
        """Defaults: retention rate, report default bucket, not cumulative."""
        metric = RetentionMetric(_retention())
        assert metric.behavior == _retention()
        assert metric.math == "retention_rate"
        assert metric.bucket_index is None
        assert metric.retention_cumulative is False
        assert metric.property is None
        assert metric.label is None

    def test_all_fields_set(self) -> None:
        """A property math with a property, a bucket, and a label."""
        metric = RetentionMetric(
            _retention(),
            math="average",
            bucket_index=7,
            retention_cumulative=True,
            property="amount",
            label="Day 7 spend",
        )
        assert metric.bucket_index == 7
        assert metric.retention_cumulative is True
        assert metric.property == "amount"
        assert metric.label == "Day 7 spend"

    def test_immutable(self) -> None:
        """A metric cannot be changed after construction."""
        metric = RetentionMetric(_retention())
        with pytest.raises(dataclasses.FrozenInstanceError):
            metric.bucket_index = 1  # type: ignore[misc]

    def test_property_math_without_property_raises_bh3(self) -> None:
        """``average`` without a property raises BH3_PROPERTY_MATH."""
        with pytest.raises(ParamValidationError) as excinfo:
            RetentionMetric(_retention(), math="average")
        assert excinfo.value.code == "BH3_PROPERTY_MATH"
        assert "RetentionMetric math='average' requires a property" in (
            excinfo.value.message
        )

    @pytest.mark.parametrize("math", ["retention_rate", "unique"])
    def test_rate_or_count_math_with_property_raises_bh3(self, math: str) -> None:
        """A math that takes no property raises BH3_PROPERTY_MATH."""
        with pytest.raises(ParamValidationError) as excinfo:
            RetentionMetric(_retention(), math=math, property="amount")  # type: ignore[arg-type]
        assert excinfo.value.code == "BH3_PROPERTY_MATH"
        assert "does not take a property" in excinfo.value.message
        assert "['average', 'total']" in excinfo.value.message

    @pytest.mark.parametrize("prop", [None, "amount"])
    def test_total_takes_an_optional_property(self, prop: str | None) -> None:
        """``total`` counts events without a property and sums one with it."""
        metric = RetentionMetric(_retention(), math="total", property=prop)
        assert metric.property == prop


# =============================================================================
# Names shared with the engine methods
# =============================================================================


class TestEngineParameterNames:
    """Behavior fields use the parameter names of the engine methods."""

    def test_funnel_behavior_fields_are_query_funnel_parameters(self) -> None:
        """Every ``FunnelBehavior`` field is a ``query_funnel`` parameter."""
        engine = set(inspect.signature(Workspace.query_funnel).parameters)
        names = {f.name for f in dataclasses.fields(FunnelBehavior)}
        assert names <= engine

    def test_retention_behavior_fields_are_query_retention_parameters(self) -> None:
        """Every ``RetentionBehavior`` field is a ``query_retention`` parameter."""
        engine = set(inspect.signature(Workspace.query_retention).parameters)
        names = {f.name for f in dataclasses.fields(RetentionBehavior)}
        assert names <= engine

    @pytest.mark.parametrize(
        ("value_type", "method"),
        [
            (FunnelBehavior, Workspace.query_funnel),
            (FunnelMetric, Workspace.query_funnel),
            (RetentionBehavior, Workspace.query_retention),
            (RetentionMetric, Workspace.query_retention),
        ],
    )
    def test_defaults_match_the_engine_method(
        self, value_type: type, method: object
    ) -> None:
        """A field that shares a name with an engine parameter shares its default."""
        engine = inspect.signature(method).parameters  # type: ignore[arg-type]
        checked = 0
        for field in dataclasses.fields(value_type):
            parameter = engine.get(field.name)
            if parameter is None or parameter.default is inspect.Parameter.empty:
                continue
            assert field.default == parameter.default, field.name
            checked += 1
        assert checked >= 1

    def test_retention_metric_measurement_names(self) -> None:
        """``math`` and ``retention_cumulative`` match ``query_retention``."""
        engine = set(inspect.signature(Workspace.query_retention).parameters)
        assert {"math", "retention_cumulative"} <= engine
        names = {f.name for f in dataclasses.fields(RetentionMetric)}
        assert {"math", "retention_cumulative"} <= names


# =============================================================================
# Registry
# =============================================================================


class TestBehaviorGuardCodes:
    """The behavior codes are minted; the funnel property codes are twins."""

    @pytest.mark.parametrize(
        "code", ["BH1_STEP_COUNT", "BH2_EMPTY_EVENT", "BH3_PROPERTY_MATH"]
    )
    def test_minted(self, code: str) -> None:
        """Each behavior code is present in CODED_GUARD_REGISTRY."""
        assert code in CODED_GUARD_REGISTRY

    @pytest.mark.parametrize(
        "code", ["F10_MATH_MISSING_PROPERTY", "F11_MATH_REJECTS_PROPERTY"]
    )
    def test_funnel_property_codes_are_twins(self, code: str) -> None:
        """``FunnelMetric`` reuses the ``query_funnel`` validator codes."""
        assert code in CODED_GUARD_TWIN_CODES
        assert code not in CODED_GUARD_REGISTRY
