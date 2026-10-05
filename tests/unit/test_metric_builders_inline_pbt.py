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

from typing import Any, get_args

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
    BehaviorRef,
    CohortMetric,
    CustomEventRef,
    Formula,
    FormulaOperand,
    FunnelBehavior,
    FunnelMetric,
    Metric,
    MetricRef,
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

ids = st.integers(min_value=1, max_value=10**9)
"""Saved-entity ids."""

simple_refs = ids.map(lambda i: BehaviorRef(i, "simple"))
"""References to saved simple behaviors."""

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
        simple_refs,
    ),
    math=st.sampled_from(["total", "unique", "dau"]),
    segment_method=st.one_of(st.none(), st.sampled_from(get_args(SegmentMethod))),
)
"""Metrics over one event, a custom event, a list, or a simple behavior (inline or saved)."""

funnel_behaviors = st.builds(
    FunnelBehavior,
    steps=st.lists(names, min_size=2, max_size=5),
    conversion_window=st.integers(min_value=1, max_value=30),
    conversion_window_unit=st.sampled_from(
        [u for u in get_args(ConversionWindowUnit) if u != "session"]
    ),
    order=st.sampled_from(get_args(FunnelOrder)),
)
"""Inline funnel behaviors."""

funnel_metrics = st.builds(
    FunnelMetric,
    behavior=st.one_of(funnel_behaviors, ids.map(lambda i: BehaviorRef(i, "funnel"))),
    math=st.sampled_from(["conversion_rate_unique", "unique", "total"]),
    step_index=st.one_of(st.none(), st.integers(min_value=0, max_value=4)),
)
"""Funnel metrics over generated funnels, inline or saved."""

retention_behaviors = st.builds(
    RetentionBehavior,
    born_event=names,
    return_event=names,
    alignment=st.sampled_from(get_args(RetentionAlignment)),
)
"""Inline retention behaviors."""

retention_metrics = st.builds(
    RetentionMetric,
    behavior=st.one_of(
        retention_behaviors, ids.map(lambda i: BehaviorRef(i, "retention"))
    ),
    bucket_index=st.one_of(st.none(), st.integers(min_value=0, max_value=30)),
    retention_cumulative=st.booleans(),
)
"""Retention metrics over generated retention behaviors, inline or saved."""

cohort_metrics = st.builds(
    CohortMetric,
    cohort=st.integers(min_value=1, max_value=10**6),
    name=st.one_of(st.none(), names),
)
"""Cohort size metrics over saved cohorts."""

inline_metrics: st.SearchStrategy[
    Metric | CohortMetric | FunnelMetric | RetentionMetric
] = st.one_of(metrics, funnel_metrics, retention_metrics, cohort_metrics)
"""Any inline metric."""

operand_refs = st.builds(MetricRef, ids)
"""Saved-metric references that can be formula operands."""

operands: st.SearchStrategy[FormulaOperand] = st.one_of(inline_metrics, operand_refs)
"""Any formula operand: an inline metric or a saved-metric reference."""


def _without_filter(block: dict[str, Any]) -> dict[str, Any]:
    """Return a behavior block without the legacy ``filter`` key.

    Args:
        block: A behavior block from a show clause.

    Returns:
        A copy without ``filter``.
    """
    return {key: value for key, value in block.items() if key != "filter"}


class TestDefinitionCompilerProperties:
    """The saved definition and the show clause come from one builder."""

    @given(inline_metrics, st.booleans())
    def test_definition_equals_clause_blocks(
        self,
        metric: Metric | CohortMetric | FunnelMetric | RetentionMetric,
        hidden: bool,
    ) -> None:
        """The definition is the clause's behavior and measurement, less ``filter``.

        ``filter`` is the one behavior key that the save schema leaves out.
        """
        clause = build_inline_metric_clause(metric, hidden=hidden)
        assert build_metric_definition(metric) == {
            "behavior": _without_filter(clause["behavior"]),
            "measurement": clause["measurement"],
        }

    @given(st.one_of(funnel_behaviors, retention_behaviors))
    def test_behavior_definition_equals_metric_behavior(
        self, behavior: FunnelBehavior | RetentionBehavior
    ) -> None:
        """A saved behavior stores its metric's behavior block, less ``filter``."""
        metric = (
            FunnelMetric(behavior)
            if isinstance(behavior, FunnelBehavior)
            else RetentionMetric(behavior)
        )
        clause = build_inline_metric_clause(metric)
        assert build_behavior_definition(behavior) == {
            "behavior": _without_filter(clause["behavior"])
        }

    @given(
        st.one_of(
            simple_refs.map(Metric),
            ids.map(lambda i: FunnelMetric(BehaviorRef(i, "funnel"))),
            ids.map(lambda i: RetentionMetric(BehaviorRef(i, "retention"))),
        )
    )
    def test_saved_behavior_stays_a_reference(
        self, metric: Metric | FunnelMetric | RetentionMetric
    ) -> None:
        """A saved behavior is written as ``{type, id}`` and nothing else."""
        ref = metric.event if isinstance(metric, Metric) else metric.behavior
        assert isinstance(ref, BehaviorRef)
        assert build_metric_definition(metric)["behavior"] == {
            "type": ref.type,
            "id": ref.id,
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

    @given(st.lists(operands, min_size=1, max_size=4), st.data())
    def test_formula_operands_are_operand_definitions(
        self, several: list[FormulaOperand], data: st.DataObject
    ) -> None:
        """Query operands are clause blocks; saved operands are definitions.

        A reference operand is ``{type, id}`` in both. An inline operand in
        the query clause keeps the clause's behavior block; in the saved
        definition it drops the legacy ``filter`` key.
        """
        index = data.draw(st.integers(min_value=0, max_value=len(several) - 1))
        formula = Formula(f"{letters_for_index(index)} * 2", metrics=several)
        query_entries = build_formula_clause(formula)["referencedMetrics"]
        saved_entries = build_formula_definition(formula)["formula"][
            "referencedMetrics"
        ]
        for op, query_entry, saved_entry in zip(
            several, query_entries, saved_entries, strict=True
        ):
            if isinstance(op, MetricRef):
                assert query_entry == saved_entry == {"type": op.type, "id": op.id}
                continue
            clause = build_inline_metric_clause(op)
            assert query_entry == {
                "type": "metric",
                "behavior": clause["behavior"],
                "measurement": clause["measurement"],
            }
            assert saved_entry == {"type": "metric", **build_metric_definition(op)}


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
