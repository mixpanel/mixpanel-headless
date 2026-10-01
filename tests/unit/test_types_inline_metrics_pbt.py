"""Property-based tests for the inline behavior and metric values.

Covers the step counts of behaviors (``BH1_STEP_COUNT``), blank step names
(``BH2_EMPTY_EVENT``), and the property-math rules of ``FunnelMetric`` and
``RetentionMetric`` over every math value. Hypothesis profiles come from
``tests/conftest.py`` (``default``, ``dev``, ``ci``).

Usage:
    # Run with default profile (100 examples)
    pytest tests/unit/test_types_inline_metrics_pbt.py

    # Run with dev profile (10 examples, verbose)
    HYPOTHESIS_PROFILE=dev pytest tests/unit/test_types_inline_metrics_pbt.py
"""

from __future__ import annotations

from typing import get_args

import pytest
from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.bookmark_enums import (
    MATH_PROPERTY_OPTIONAL,
    MATH_REQUIRING_PROPERTY,
)
from mixpanel_headless._literal_types import FunnelMathType, RetentionMathType
from mixpanel_headless.exceptions import ParamValidationError
from mixpanel_headless.types import (
    FunnelBehavior,
    FunnelMetric,
    RetentionBehavior,
    RetentionMetric,
    SimpleBehavior,
)

event_names = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")), min_size=1, max_size=20
).filter(lambda name: name.strip() != "")
"""Event names with a visible character and no control characters."""

blank_names = st.text(alphabet=" \t", max_size=3)
"""Empty or whitespace-only event names."""

properties = st.one_of(st.none(), event_names)
"""An optional property name."""


class TestStepCountProperties:
    """``BH1_STEP_COUNT`` fires exactly below the minimum step count."""

    @given(st.lists(event_names, max_size=6))
    def test_simple_behavior_needs_one_event(self, events: list[str]) -> None:
        """A simple behavior builds iff it has at least one event."""
        if events:
            assert SimpleBehavior(list(events)).events == events
        else:
            with pytest.raises(ParamValidationError) as excinfo:
                SimpleBehavior(list(events))
            assert excinfo.value.code == "BH1_STEP_COUNT"

    @given(st.lists(event_names, max_size=6))
    def test_funnel_behavior_needs_two_steps(self, steps: list[str]) -> None:
        """A funnel behavior builds iff it has at least two steps."""
        if len(steps) >= 2:
            assert FunnelBehavior(list(steps)).steps == steps
        else:
            with pytest.raises(ParamValidationError) as excinfo:
                FunnelBehavior(list(steps))
            assert excinfo.value.code == "BH1_STEP_COUNT"

    @given(event_names, event_names)
    def test_retention_behavior_holds_two_events(self, born: str, back: str) -> None:
        """A retention behavior always holds exactly a born and a return event."""
        behavior = RetentionBehavior(born, back)
        assert (behavior.born_event, behavior.return_event) == (born, back)


class TestBlankStepProperties:
    """``BH2_EMPTY_EVENT`` fires for a blank name at any position."""

    @given(st.lists(event_names, min_size=2, max_size=6), blank_names, st.data())
    def test_blank_step_anywhere_raises_bh2(
        self, steps: list[str], blank: str, data: st.DataObject
    ) -> None:
        """A blank step at any position of a valid funnel raises BH2."""
        position = data.draw(st.integers(min_value=0, max_value=len(steps)))
        with_blank = [*steps[:position], blank, *steps[position:]]
        with pytest.raises(ParamValidationError) as simple:
            SimpleBehavior([*with_blank])
        with pytest.raises(ParamValidationError) as funnel:
            FunnelBehavior([*with_blank])
        for excinfo in (simple, funnel):
            assert excinfo.value.code == "BH2_EMPTY_EVENT"
            assert f"[{position}]" in excinfo.value.message


class TestPropertyMathProperties:
    """The property rules follow the shared property-math sets."""

    @given(st.sampled_from(get_args(FunnelMathType)), properties)
    def test_funnel_metric_property_rule(self, math: str, prop: str | None) -> None:
        """A funnel metric builds iff its property matches its math."""
        if math in MATH_REQUIRING_PROPERTY and prop is None:
            code: str | None = "F10_MATH_MISSING_PROPERTY"
        elif (
            math not in MATH_REQUIRING_PROPERTY
            and math not in MATH_PROPERTY_OPTIONAL
            and prop is not None
        ):
            code = "F11_MATH_REJECTS_PROPERTY"
        else:
            code = None
        behavior = FunnelBehavior(["Signup", "Purchase"])
        if code is None:
            metric = FunnelMetric(behavior, math=math, property=prop)  # type: ignore[arg-type]
            assert metric.property == prop
        else:
            with pytest.raises(ParamValidationError) as excinfo:
                FunnelMetric(behavior, math=math, property=prop)  # type: ignore[arg-type]
            assert excinfo.value.code == code

    @given(st.sampled_from(get_args(RetentionMathType)), properties)
    def test_retention_metric_property_rule(self, math: str, prop: str | None) -> None:
        """A retention metric builds iff its property matches its math."""
        needs = math in MATH_REQUIRING_PROPERTY
        takes = needs or math in MATH_PROPERTY_OPTIONAL
        behavior = RetentionBehavior("Signup", "Login")
        if (needs and prop is None) or (not takes and prop is not None):
            with pytest.raises(ParamValidationError) as excinfo:
                RetentionMetric(behavior, math=math, property=prop)  # type: ignore[arg-type]
            assert excinfo.value.code == "BH3_PROPERTY_MATH"
        else:
            metric = RetentionMetric(behavior, math=math, property=prop)  # type: ignore[arg-type]
            assert metric.property == prop

    @given(
        st.sampled_from(
            sorted(set(get_args(FunnelMathType)) & MATH_REQUIRING_PROPERTY)
        ),
        blank_names,
    )
    def test_funnel_metric_blank_property_is_missing(
        self, math: str, prop: str
    ) -> None:
        """A blank property name on a funnel property math raises F10."""
        behavior = FunnelBehavior(["Signup", "Purchase"])
        with pytest.raises(ParamValidationError) as excinfo:
            FunnelMetric(behavior, math=math, property=prop)  # type: ignore[arg-type]
        assert excinfo.value.code == "F10_MATH_MISSING_PROPERTY"

    @given(
        st.sampled_from(
            sorted(set(get_args(RetentionMathType)) & MATH_REQUIRING_PROPERTY)
        ),
        blank_names,
    )
    def test_retention_metric_blank_property_is_missing(
        self, math: str, prop: str
    ) -> None:
        """A blank property name on a retention property math raises BH3."""
        behavior = RetentionBehavior("Signup", "Login")
        with pytest.raises(ParamValidationError) as excinfo:
            RetentionMetric(behavior, math=math, property=prop)  # type: ignore[arg-type]
        assert excinfo.value.code == "BH3_PROPERTY_MATH"
        assert "requires a property" in excinfo.value.message
