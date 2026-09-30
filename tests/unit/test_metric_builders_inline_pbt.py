"""Property-based tests for the inline-metric builders and the definition compiler.

Covers the invariants that the create layer and the query layer share: the
saved definition of an inline metric is the behavior and measurement of its
show clause, a metric over more than one event always writes a named simple
behavior with one entry per event, and operand formulas write one entry per
operand. Hypothesis profiles come from ``tests/conftest.py``.

Usage:
    # Run with default profile (100 examples)
    pytest tests/unit/test_metric_builders_inline_pbt.py

    # Run with dev profile (10 examples, verbose)
    HYPOTHESIS_PROFILE=dev pytest tests/unit/test_metric_builders_inline_pbt.py
"""

from __future__ import annotations

from typing import get_args

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless._internal.query.formula import letters_for_index
from mixpanel_headless._internal.query.metric_builders import (
    build_behavior_definition,
    build_formula_clause,
    build_formula_definition,
    build_inline_metric_clause,
    build_metric_clause,
    build_metric_definition,
)
from mixpanel_headless._literal_types import (
    ConversionWindowUnit,
    FunnelOrder,
    RetentionAlignment,
    SegmentMethod,
)
from mixpanel_headless.types import (
    CohortMetric,
    CustomEventRef,
    Formula,
    FormulaOperand,
    FunnelBehavior,
    FunnelMetric,
    Metric,
    RetentionBehavior,
    RetentionMetric,
    SimpleBehavior,
)

names = st.text(
    alphabet=st.characters(blacklist_categories=("Cc", "Cs")), min_size=1, max_size=12
).filter(lambda name: name.strip() != "")
"""Event names with a visible character and no control characters."""

refs = st.integers(min_value=1, max_value=10**9).map(CustomEventRef)
"""Custom event references."""

events = st.one_of(names, refs)
"""One event: a name or a custom event reference."""

metrics = st.builds(
    Metric,
    event=st.one_of(
        names,
        refs,
        st.lists(events, min_size=1, max_size=5),
        st.builds(
            SimpleBehavior,
            events=st.lists(events, min_size=1, max_size=4),
            name=st.one_of(st.none(), names),
        ),
    ),
    math=st.sampled_from(["total", "unique", "dau"]),
    segment_method=st.one_of(st.none(), st.sampled_from(get_args(SegmentMethod))),
)
"""Metrics over one event, a custom event, a list, or a simple behavior."""

funnel_metrics = st.builds(
    FunnelMetric,
    behavior=st.builds(
        FunnelBehavior,
        steps=st.lists(names, min_size=2, max_size=5),
        conversion_window=st.integers(min_value=1, max_value=30),
        conversion_window_unit=st.sampled_from(
            [u for u in get_args(ConversionWindowUnit) if u != "session"]
        ),
        order=st.sampled_from(get_args(FunnelOrder)),
    ),
    math=st.sampled_from(["conversion_rate_unique", "unique", "total"]),
    step_index=st.one_of(st.none(), st.integers(min_value=0, max_value=4)),
)
"""Funnel metrics over generated funnels."""

retention_metrics = st.builds(
    RetentionMetric,
    behavior=st.builds(
        RetentionBehavior,
        born_event=names,
        return_event=names,
        alignment=st.sampled_from(get_args(RetentionAlignment)),
    ),
    bucket_index=st.one_of(st.none(), st.integers(min_value=0, max_value=30)),
    retention_cumulative=st.booleans(),
)
"""Retention metrics over generated retention behaviors."""

cohort_metrics = st.builds(
    CohortMetric,
    cohort=st.integers(min_value=1, max_value=10**6),
    name=st.one_of(st.none(), names),
)
"""Cohort size metrics over saved cohorts."""

inline_metrics: st.SearchStrategy[FormulaOperand] = st.one_of(
    metrics, funnel_metrics, retention_metrics, cohort_metrics
)
"""Any inline metric that can be a formula operand."""


class TestDefinitionCompilerProperties:
    """The saved definition and the show clause come from one builder."""

    @given(inline_metrics, st.booleans())
    def test_definition_equals_clause_blocks(
        self, metric: FormulaOperand, hidden: bool
    ) -> None:
        """The definition is the behavior and measurement of the show clause."""
        clause = build_inline_metric_clause(metric, hidden=hidden)
        assert build_metric_definition(metric) == {
            "behavior": clause["behavior"],
            "measurement": clause["measurement"],
        }

    @given(st.one_of(funnel_metrics, retention_metrics))
    def test_behavior_definition_equals_metric_behavior(
        self, metric: FunnelMetric | RetentionMetric
    ) -> None:
        """A saved behavior stores the behavior block of its metric clause."""
        clause = build_inline_metric_clause(metric)
        assert build_behavior_definition(metric.behavior) == {
            "behavior": clause["behavior"]
        }

    @given(st.lists(events, min_size=1, max_size=5), st.one_of(st.none(), names))
    def test_simple_behavior_definition_has_no_name(
        self, several: list[str | CustomEventRef], name: str | None
    ) -> None:
        """A saved simple behavior is the query block without its name."""
        behavior = SimpleBehavior(list(several), name=name)
        query_block = build_metric_clause(Metric(behavior))["behavior"]
        saved = build_behavior_definition(behavior)["behavior"]
        assert "name" not in saved
        assert saved == {k: v for k, v in query_block.items() if k != "name"}

    @given(st.lists(inline_metrics, min_size=1, max_size=4), st.data())
    def test_formula_operands_are_operand_definitions(
        self, operands: list[FormulaOperand], data: st.DataObject
    ) -> None:
        """Each ``referencedMetrics`` entry is its operand's definition."""
        index = data.draw(st.integers(min_value=0, max_value=len(operands) - 1))
        formula = Formula(f"{letters_for_index(index)} * 2", metrics=operands)
        entries = build_formula_clause(formula)["referencedMetrics"]
        assert entries == [
            {"type": "metric", **build_metric_definition(op)} for op in operands
        ]
        assert build_formula_definition(formula)["formula"]["referencedMetrics"] == (
            entries
        )


class TestSeveralEventsProperties:
    """A metric over more than one event writes one named simple behavior."""

    @given(st.lists(events, min_size=2, max_size=6))
    def test_list_writes_named_simple_behavior(
        self, several: list[str | CustomEventRef]
    ) -> None:
        """The behavior is simple, named, with one entry per event in order."""
        behavior = build_metric_clause(Metric(several))["behavior"]
        assert behavior["type"] == "simple"
        assert behavior["name"].strip() != ""
        assert behavior["filters"] == []
        assert len(behavior["behaviors"]) == len(several)
        for entry, event in zip(behavior["behaviors"], several, strict=True):
            if isinstance(event, CustomEventRef):
                assert entry["type"] == "custom-event"
                assert entry["id"] == event.id
            else:
                assert entry["type"] == "event"
                assert entry["name"] == event

    @given(events)
    def test_list_of_one_equals_the_event(self, event: str | CustomEventRef) -> None:
        """A one-element list writes the clause of the element alone."""
        assert build_metric_clause(Metric([event])) == build_metric_clause(
            Metric(event)
        )
