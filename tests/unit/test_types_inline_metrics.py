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
    BehaviorRef,
    CohortMetric,
    CustomEventRef,
    CustomPropertyRef,
    Exclusion,
    Filter,
    Formula,
    FormulaOperand,
    FunnelBehavior,
    FunnelMetric,
    FunnelStep,
    HoldingConstant,
    Metric,
    MetricRef,
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


class TestIdAndIndexGuards:
    """Ids are positive ints and indexes are ints >= 0; ``bool`` is never one."""

    @pytest.mark.parametrize("bad", [0, -1, True, False, 1.5, "7"])
    def test_custom_event_id_must_be_a_positive_int(self, bad: object) -> None:
        """A non-positive, bool, or non-int id raises CE1_INVALID_ID."""
        with pytest.raises(ParamValidationError) as excinfo:
            CustomEventRef(bad)  # type: ignore[arg-type]
        assert excinfo.value.code == "CE1_INVALID_ID"

    @pytest.mark.parametrize("bad", [-1, True, False, 1.0, "1"])
    def test_funnel_step_index_must_be_an_index(self, bad: object) -> None:
        """A negative, bool, or non-int step_index raises MT4_INVALID_INDEX."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelMetric(_funnel(), step_index=bad)  # type: ignore[arg-type]
        assert excinfo.value.code == "MT4_INVALID_INDEX"
        assert "FunnelMetric.step_index" in excinfo.value.message

    @pytest.mark.parametrize("bad", [-1, True, False, 1.0, "1"])
    def test_retention_bucket_index_must_be_an_index(self, bad: object) -> None:
        """A negative, bool, or non-int bucket_index raises MT4_INVALID_INDEX."""
        with pytest.raises(ParamValidationError) as excinfo:
            RetentionMetric(_retention(), bucket_index=bad)  # type: ignore[arg-type]
        assert excinfo.value.code == "MT4_INVALID_INDEX"
        assert "RetentionMetric.bucket_index" in excinfo.value.message

    def test_zero_indexes_pass(self) -> None:
        """Step and bucket index zero are valid."""
        assert FunnelMetric(_funnel(), step_index=0).step_index == 0
        assert RetentionMetric(_retention(), bucket_index=0).bucket_index == 0

    @pytest.mark.parametrize("bad", [True, False, 0])
    def test_saved_entity_refs_refuse_bool_ids(self, bad: object) -> None:
        """BehaviorRef and MetricRef refuse a bool or non-positive id too."""
        with pytest.raises(ParamValidationError) as behavior_exc:
            BehaviorRef(bad, "funnel")  # type: ignore[arg-type]
        assert behavior_exc.value.code == "BR1_INVALID_ID"
        with pytest.raises(ParamValidationError) as metric_exc:
            MetricRef(bad)  # type: ignore[arg-type]
        assert metric_exc.value.code == "MR4_INVALID_ID"

    @pytest.mark.parametrize("code", ["CE1_INVALID_ID", "MT4_INVALID_INDEX"])
    def test_codes_are_registered(self, code: str) -> None:
        """The two guard codes are minted in the registry."""
        assert code in CODED_GUARD_REGISTRY


# =============================================================================
# SimpleBehavior
# =============================================================================


class TestSimpleBehavior:
    """``SimpleBehavior`` is one or more events counted as one behavior."""

    def test_defaults(self) -> None:
        """The name defaults to none (the builder derives one)."""
        behavior = SimpleBehavior(["Login"])
        assert behavior.events == ["Login"]
        assert behavior.name is None

    def test_has_no_behavior_level_filters(self) -> None:
        """The server ignores behavior-level filters, so the type has none."""
        names = {f.name for f in dataclasses.fields(SimpleBehavior)}
        assert names == {"events", "name"}

    def test_accepts_names_custom_events_and_steps(self) -> None:
        """Events can be names, custom event references, or steps with filters."""
        step = FunnelStep("Purchase", filters=[Filter.greater_than("amount", 5)])
        behavior = SimpleBehavior(["Login", CustomEventRef(7), step], name="Engaged")
        assert behavior.events == ["Login", CustomEventRef(7), step]
        assert behavior.name == "Engaged"

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

    @pytest.mark.parametrize("prop", ["", "   ", "\t"])
    def test_blank_property_with_property_math_raises_f10(self, prop: str) -> None:
        """A blank property name counts as no property for a property math."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelMetric(_funnel(), math="average", property=prop)
        assert excinfo.value.code == "F10_MATH_MISSING_PROPERTY"
        assert "FunnelMetric math='average' requires a property" in (
            excinfo.value.message
        )

    def test_property_name_with_property_math_passes(self) -> None:
        """A property math with a property name builds."""
        metric = FunnelMetric(_funnel(), math="average", property="amount")
        assert metric.property == "amount"

    @pytest.mark.parametrize("prop", ["", "   "])
    def test_blank_property_with_rate_math_raises_f11(self, prop: str) -> None:
        """A math that takes no property still refuses a blank property name."""
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelMetric(_funnel(), property=prop)
        assert excinfo.value.code == "F11_MATH_REJECTS_PROPERTY"

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

    @pytest.mark.parametrize("prop", ["", "   ", "\t"])
    def test_blank_property_with_property_math_raises_bh3(self, prop: str) -> None:
        """A blank property name counts as no property for ``average``."""
        with pytest.raises(ParamValidationError) as excinfo:
            RetentionMetric(_retention(), math="average", property=prop)
        assert excinfo.value.code == "BH3_PROPERTY_MATH"
        assert "RetentionMetric math='average' requires a property" in (
            excinfo.value.message
        )

    def test_property_name_with_property_math_passes(self) -> None:
        """``average`` with a property name builds."""
        metric = RetentionMetric(_retention(), math="average", property="amount")
        assert metric.property == "amount"

    @pytest.mark.parametrize("prop", ["", "   "])
    def test_blank_property_with_rate_math_raises_bh3(self, prop: str) -> None:
        """A math that takes no property still refuses a blank property name."""
        with pytest.raises(ParamValidationError) as excinfo:
            RetentionMetric(_retention(), property=prop)
        assert excinfo.value.code == "BH3_PROPERTY_MATH"
        assert "does not take a property" in excinfo.value.message

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
# Metric over a custom event or more than one event
# =============================================================================


class TestMetricEvents:
    """``Metric.event`` takes one event, a custom event, or several events."""

    def test_custom_event_ref(self) -> None:
        """A custom event reference is stored unchanged."""
        assert Metric(CustomEventRef(5), math="unique").event == CustomEventRef(5)

    def test_list_of_names_and_refs(self) -> None:
        """A list of names and custom event references is stored unchanged."""
        metric = Metric(["Login", CustomEventRef(5)], math="unique")
        assert metric.event == ["Login", CustomEventRef(5)]

    def test_simple_behavior(self) -> None:
        """A simple behavior is stored unchanged."""
        behavior = SimpleBehavior(["Login", "SSO Login"], name="Signed in")
        assert Metric(behavior).event == behavior

    def test_empty_list_raises_bh1(self) -> None:
        """A metric over an empty list of events raises BH1_STEP_COUNT."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric([])
        assert excinfo.value.code == "BH1_STEP_COUNT"
        assert "Metric needs at least 1 event" in excinfo.value.message

    def test_blank_name_in_list_raises_bh2(self) -> None:
        """A blank name in the list raises BH2_EMPTY_EVENT with its position."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric(["Login", " "])
        assert excinfo.value.code == "BH2_EMPTY_EVENT"
        assert "Metric.event[1]" in excinfo.value.message

    def test_control_character_in_list_raises_ev2(self) -> None:
        """A name with a control character in the list raises EV2."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric(["Log\x00in", "Signup"])
        assert excinfo.value.code == "EV2_CONTROL_CHAR_EVENT"

    def test_filters_with_simple_behavior_raise_mt3(self) -> None:
        """Metric filters cannot be combined with a simple behavior."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric(
                SimpleBehavior(["Login", "Signup"]),
                filters=[Filter.equals("platform", "ios")],
            )
        assert excinfo.value.code == "MT3_FILTERS_WITH_BEHAVIOR"
        assert "FunnelStep" in excinfo.value.message

    def test_empty_filters_with_simple_behavior_pass(self) -> None:
        """An empty filter list is no filter."""
        assert Metric(SimpleBehavior(["Login", "Signup"]), filters=[]).filters == []

    def test_filters_with_a_list_of_events_pass(self) -> None:
        """Filters on a metric over a list apply to every event."""
        metric = Metric(["Login", "Signup"], filters=[Filter.equals("plan", "pro")])
        assert metric.filters == [Filter.equals("plan", "pro")]

    def test_property_rule_still_applies(self) -> None:
        """A property math without a property keeps V13_METRIC_MATH_PROPERTY."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric(["Login", "Signup"], math="average")
        assert excinfo.value.code == "V13_METRIC_MATH_PROPERTY"

    def test_mt3_is_registered(self) -> None:
        """MT3_FILTERS_WITH_BEHAVIOR is a minted registry code."""
        assert "MT3_FILTERS_WITH_BEHAVIOR" in CODED_GUARD_REGISTRY

    @pytest.mark.parametrize(
        "item",
        [FunnelStep("Buy"), 123, 1.5, True, None, {"event": "Buy"}, ["Buy"]],
        ids=["funnel-step", "int", "float", "bool", "none", "dict", "nested-list"],
    )
    @pytest.mark.parametrize(
        "filters", [None, [Filter.equals("country", "US")]], ids=["bare", "filtered"]
    )
    def test_list_item_of_another_type_raises_mt5(
        self, item: object, filters: list[Filter] | None
    ) -> None:
        """A list item that is not a name or a CustomEventRef raises MT5."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric(["Login", item], filters=filters)  # type: ignore[list-item]
        assert excinfo.value.code == "MT5_INVALID_EVENT_TYPE"
        assert "Metric.event[1]" in excinfo.value.message
        assert f"got {type(item).__name__}" in excinfo.value.message

    def test_funnel_steps_with_metric_filters_raise_mt5(self) -> None:
        """Steps with Metric filters are refused, and the message names SimpleBehavior."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric(
                [FunnelStep("a"), FunnelStep("b")],  # type: ignore[list-item]
                filters=[Filter.equals("country", "US")],
            )
        assert excinfo.value.code == "MT5_INVALID_EVENT_TYPE"
        message = excinfo.value.message
        assert "Metric.event[0]" in message
        assert "Metric filters apply to every event" in message
        assert "Metric(SimpleBehavior([FunnelStep(" in message

    def test_single_funnel_step_in_a_list_raises_mt5(self) -> None:
        """A list of one step is refused, not written as the step's repr."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric([FunnelStep("X")])  # type: ignore[list-item]
        assert excinfo.value.code == "MT5_INVALID_EVENT_TYPE"
        assert "Metric.event[0]" in excinfo.value.message

    def test_number_before_a_name_raises_mt5(self) -> None:
        """A number first in the list raises MT5, not a raw TypeError."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric([123, "A"])  # type: ignore[list-item]
        assert excinfo.value.code == "MT5_INVALID_EVENT_TYPE"
        assert "Metric.event[0]" in excinfo.value.message

    @pytest.mark.parametrize(
        "event",
        [FunnelStep("X"), 123, None, {"Login": 1}],
        ids=["funnel-step", "int", "none", "dict"],
    )
    def test_event_of_another_type_raises_mt5(self, event: object) -> None:
        """An event that is no name, custom event, list, or behavior raises MT5."""
        with pytest.raises(ParamValidationError) as excinfo:
            Metric(event)  # type: ignore[arg-type]
        assert excinfo.value.code == "MT5_INVALID_EVENT_TYPE"
        assert "Metric.event must be" in excinfo.value.message
        assert f"got {type(event).__name__}" in excinfo.value.message
        assert "SimpleBehavior" in excinfo.value.message

    def test_simple_behavior_of_filtered_steps_passes(self) -> None:
        """Steps with their own filters go in a SimpleBehavior."""
        us = Filter.equals("country", "US")
        behavior = SimpleBehavior([FunnelStep("a", filters=[us]), FunnelStep("b")])
        assert Metric(behavior, math="unique").event == behavior

    def test_mt5_is_registered(self) -> None:
        """MT5_INVALID_EVENT_TYPE is a minted registry code."""
        assert "MT5_INVALID_EVENT_TYPE" in CODED_GUARD_REGISTRY


# =============================================================================
# Formula with operands
# =============================================================================


class TestFormulaOperands:
    """``Formula(metrics=...)`` names its own operands by letter."""

    def test_default_has_no_operands(self) -> None:
        """Without operands the letters name the other metrics of the query."""
        formula = Formula("B / A")
        assert formula.metrics is None

    def test_operands_are_stored(self) -> None:
        """Operands of every metric kind are stored in order."""
        operands: list[Metric | CohortMetric | FunnelMetric | RetentionMetric] = [
            Metric("Signup", math="unique"),
            FunnelMetric(_funnel()),
            RetentionMetric(_retention()),
            CohortMetric(12),
        ]
        formula = Formula("(A + B) * C / D", label="Mix", metrics=[*operands])
        assert formula.metrics == tuple(operands)
        assert formula.label == "Mix"

    def test_letters_after_z_name_later_operands(self) -> None:
        """With 27 operands the 27th is ``BA``."""
        operands: list[Metric | CohortMetric | FunnelMetric | RetentionMetric] = [
            Metric(f"E{i}") for i in range(27)
        ]
        assert Formula("BA / A", metrics=[*operands]).metrics == tuple(operands)

    def test_operands_are_a_tuple_copy(self) -> None:
        """The operands are stored as a tuple, not the caller's list."""
        operands: list[FormulaOperand] = [Metric("Signup"), Metric("Purchase")]
        formula = Formula("B / A", metrics=operands)
        # A list never equals a tuple, so this also proves the stored type.
        assert formula.metrics == (Metric("Signup"), Metric("Purchase"))

    def test_caller_list_changes_do_not_reach_the_formula(self) -> None:
        """A later pop or append on the caller's list skips no guard."""
        operands: list[FormulaOperand] = [Metric("Signup"), Metric("Purchase")]
        formula = Formula("B / A", metrics=operands)
        operands.pop()
        operands.append(MetricRef(11, type="warehouse"))
        operands.append(Metric("Login"))
        assert formula.metrics == (Metric("Signup"), Metric("Purchase"))

    def test_operands_cannot_be_appended(self) -> None:
        """The stored operands have no ``append``."""
        formula = Formula("A", metrics=[Metric("Signup")])
        with pytest.raises(AttributeError):
            formula.metrics.append(Metric("Login"))  # type: ignore[union-attr]

    def test_list_and_tuple_operands_are_equal(self) -> None:
        """A list and a tuple of the same operands make equal formulas."""
        from_list = Formula("A", label="L", metrics=[Metric("Signup")])
        from_tuple = Formula("A", label="L", metrics=(Metric("Signup"),))
        assert from_list == from_tuple
        assert repr(from_list) == repr(from_tuple)
        assert "metrics=(Metric(" in repr(from_list)

    def test_empty_expression_keeps_fm1(self) -> None:
        """An empty expression raises FM1 before any operand rule."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula(" ", metrics=[Metric("A")])
        assert excinfo.value.code == "FM1_EMPTY_EXPRESSION"

    def test_formula_operand_raises_fm3(self) -> None:
        """A formula cannot be an operand of another formula."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula(
                "A + B",
                metrics=[Metric("Login"), Formula("A")],  # type: ignore[list-item]
            )
        assert excinfo.value.code == "FM3_NESTED_FORMULA"
        assert "Formula.metrics[1]" in excinfo.value.message

    def test_syntax_error_raises_fm4(self) -> None:
        """An expression outside the server grammar raises FM4_SYNTAX."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("A ^ -B", metrics=[Metric("A"), Metric("B")])
        assert excinfo.value.code == "FM4_SYNTAX"

    def test_uppercase_exponent_raises_fm5(self) -> None:
        """A literal with an uppercase E raises FM5_UPPER_E with operands."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("A * 1E3", metrics=[Metric("A")])
        assert excinfo.value.code == "FM5_UPPER_E"

    def test_uppercase_exponent_passes_without_operands(self) -> None:
        """Without operands the server does not rename letters, so 1E3 passes."""
        assert Formula("A * 1E3").expression == "A * 1E3"

    def test_unknown_letter_raises_fm2(self) -> None:
        """A letter past the last operand raises FM2_UNKNOWN_LETTER."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("A + C", metrics=[Metric("A"), Metric("B")])
        assert excinfo.value.code == "FM2_UNKNOWN_LETTER"

    def test_no_operands_listed_raises_fm2(self) -> None:
        """An empty operand list leaves every letter unknown."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("A", metrics=[])
        assert excinfo.value.code == "FM2_UNKNOWN_LETTER"

    def test_no_letters_raises_v16_twin(self) -> None:
        """An operand formula with no letters raises V16_FORMULA_SYNTAX."""
        with pytest.raises(ParamValidationError) as excinfo:
            Formula("1 + 2", metrics=[Metric("A")])
        assert excinfo.value.code == "V16_FORMULA_SYNTAX"
        assert "at least one operand" in excinfo.value.message

    def test_v16_is_a_registered_twin(self) -> None:
        """The operand form reuses the V16 validator code as a twin."""
        assert "V16_FORMULA_SYNTAX" in CODED_GUARD_TWIN_CODES
        assert "FM3_NESTED_FORMULA" in CODED_GUARD_REGISTRY


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
        """A field with a default shares the default of its engine parameter.

        A required field (a retention return event) has no default to share.
        """
        engine = inspect.signature(method).parameters  # type: ignore[arg-type]
        checked = 0
        for field in dataclasses.fields(value_type):
            parameter = engine.get(field.name)
            if (
                parameter is None
                or parameter.default is inspect.Parameter.empty
                or field.default is dataclasses.MISSING
            ):
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
