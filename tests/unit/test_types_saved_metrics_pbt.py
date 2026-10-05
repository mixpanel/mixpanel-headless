"""Property-based tests for the saved metric and saved behavior result types.

These tests verify invariants that should hold for every App API row, known
shape or not, because the read models are open.

Properties tested:
- SavedMetric parses any JSON object with the required keys
- SavedMetric keeps every unknown key, in ``model_extra`` and in dumps
- SavedMetric accessors never raise and return the documented types
- referenced_metric_ids returns each operand id once, in first-use order,
  and skips a ``metric_id`` string that ``int()`` rejects
- SavedBehavior parses any JSON object with the required keys, keeps
  unknown keys, and its accessor never raises

Usage:
    pytest tests/unit/test_types_saved_metrics_pbt.py
    HYPOTHESIS_PROFILE=dev pytest tests/unit/test_types_saved_metrics_pbt.py
    HYPOTHESIS_PROFILE=ci pytest tests/unit/test_types_saved_metrics_pbt.py
"""

from __future__ import annotations

from typing import Any

from hypothesis import given
from hypothesis import strategies as st

from mixpanel_headless.types import (
    MetricDisplay,
    MetricGoal,
    SavedBehavior,
    SavedMetric,
)

# =============================================================================
# Custom Strategies
# =============================================================================

# Strategy for JSON-serializable primitive values
json_primitives = st.one_of(
    st.none(),
    st.booleans(),
    st.integers(),
    st.floats(allow_nan=False, allow_infinity=False),
    st.text(max_size=20),
)

# Strategy for JSON-serializable values (recursive: primitives, lists, dicts)
json_values: st.SearchStrategy[Any] = st.recursive(
    json_primitives,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.text(max_size=10), children, max_size=4),
    ),
    max_leaves=12,
)

# Definition keys that the typed accessors read, plus the nested keys under them
_ACCESSOR_KEYS = ("behavior", "measurement", "formula", "display", "goals")
_NESTED_KEYS = (
    "type",
    "math",
    "definition",
    "referencedMetrics",
    "id",
    "metric_id",
    "label",
    "checkpoints",
    "precision",
    "prefix",
)

# Nested values biased toward the shapes the accessors look for
_nested_values: st.SearchStrategy[Any] = st.recursive(
    json_primitives,
    lambda children: st.one_of(
        st.lists(children, max_size=4),
        st.dictionaries(st.sampled_from(_NESTED_KEYS), children, max_size=4),
    ),
    max_leaves=12,
)

# Definitions: either fully random or keyed by the accessor keys
definitions: st.SearchStrategy[dict[str, Any]] = st.one_of(
    st.dictionaries(st.text(max_size=10), json_values, max_size=5),
    st.dictionaries(st.sampled_from(_ACCESSOR_KEYS), _nested_values, max_size=5),
)

# Digit strings that pass str.isdigit() but that int() rejects (superscripts)
_INT_REJECTED_DIGITS = ("²", "1²", "³⁴")

# Unknown top-level keys: identifier-like names that are not model fields
_extra_keys = st.from_regex(r"[a-z][a-z_]{0,15}", fullmatch=True)


def _extras(model_fields: set[str]) -> st.SearchStrategy[dict[str, Any]]:
    """Build a strategy for unknown top-level keys of an entity row.

    Args:
        model_fields: Field names of the model, which the keys must avoid.

    Returns:
        A strategy of dicts whose keys are not model fields.
    """
    return st.dictionaries(
        _extra_keys.filter(lambda k: k not in model_fields), json_values, max_size=4
    )


@st.composite
def metric_rows(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a saved metric row: the required keys plus unknown keys.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A dict with ``id``, ``name``, ``type``, ``definition``, and extras.
    """
    row = draw(_extras(set(SavedMetric.model_fields)))
    row.update(
        {
            "id": draw(st.integers()),
            "name": draw(st.text(max_size=30)),
            "type": draw(
                st.one_of(
                    st.sampled_from(["metric", "formula", "warehouse", "behavior"]),
                    st.text(max_size=15),
                )
            ),
            "definition": draw(definitions),
        }
    )
    return row


@st.composite
def behavior_rows(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a saved behavior row: the required keys plus unknown keys.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A dict with ``id``, ``name``, ``type``, ``definition``, and extras.
    """
    row = draw(_extras(set(SavedBehavior.model_fields)))
    row.update(
        {
            "id": draw(st.integers()),
            "name": draw(st.text(max_size=30)),
            "type": draw(
                st.one_of(
                    st.sampled_from(["simple", "funnel", "retention"]),
                    st.text(max_size=15),
                )
            ),
            "definition": draw(definitions),
        }
    )
    return row


# =============================================================================
# SavedMetric properties
# =============================================================================


class TestSavedMetricProperties:
    """Open-read invariants of SavedMetric."""

    @given(row=metric_rows())
    def test_parses_and_keeps_unknown_keys(self, row: dict[str, Any]) -> None:
        """Any row with the required keys parses, and unknown keys survive.

        Args:
            row: A generated saved metric row.
        """
        metric = SavedMetric.model_validate(row)
        assert metric.id == row["id"]
        assert metric.type == row["type"]
        assert metric.definition == row["definition"]
        unknown = {k: v for k, v in row.items() if k not in SavedMetric.model_fields}
        assert metric.model_extra == unknown
        dumped = metric.model_dump()
        for key, value in unknown.items():
            assert dumped[key] == value

    @given(row=metric_rows())
    def test_accessors_never_raise(self, row: dict[str, Any]) -> None:
        """Every accessor returns its documented type for any definition.

        Args:
            row: A generated saved metric row.
        """
        metric = SavedMetric.model_validate(row)
        assert metric.behavior_type is None or isinstance(metric.behavior_type, str)
        assert metric.math is None or isinstance(metric.math, str)
        assert metric.formula_expression is None or isinstance(
            metric.formula_expression, str
        )
        ids = metric.referenced_metric_ids
        assert all(isinstance(i, int) and not isinstance(i, bool) for i in ids)
        assert metric.display is None or isinstance(metric.display, MetricDisplay)
        assert all(isinstance(g, MetricGoal) for g in metric.goals)

    @given(
        operands=st.lists(
            st.one_of(
                st.fixed_dictionaries({"id": st.integers(min_value=0)}),
                st.fixed_dictionaries({"metric_id": st.integers(min_value=0).map(str)}),
                st.fixed_dictionaries(
                    {"metric_id": st.sampled_from(_INT_REJECTED_DIGITS)}
                ),
                st.fixed_dictionaries({"behavior": json_values}),
            ),
            max_size=8,
        )
    )
    def test_referenced_ids_unique_in_first_use_order(
        self, operands: list[dict[str, Any]]
    ) -> None:
        """Operand ids come back once each, in the order they first appear.

        A ``metric_id`` string that ``int()`` rejects is skipped.

        Args:
            operands: Generated formula operands, with or without an id.
        """
        metric = SavedMetric.model_validate(
            {
                "id": 1,
                "name": "f",
                "type": "formula",
                "definition": {
                    "formula": {"definition": "A", "referencedMetrics": operands}
                },
            }
        )
        expected: list[int] = []
        for operand in operands:
            raw = operand.get("id", operand.get("metric_id"))
            if raw in _INT_REJECTED_DIGITS:
                continue
            if raw is not None and int(raw) not in expected:
                expected.append(int(raw))
        assert metric.referenced_metric_ids == expected


# =============================================================================
# SavedBehavior properties
# =============================================================================


class TestSavedBehaviorProperties:
    """Open-read invariants of SavedBehavior."""

    @given(row=behavior_rows())
    def test_parses_keeps_unknown_keys_and_accessor_never_raises(
        self, row: dict[str, Any]
    ) -> None:
        """Any row with the required keys parses, keeps extras, and reads safely.

        Args:
            row: A generated saved behavior row.
        """
        behavior = SavedBehavior.model_validate(row)
        assert behavior.type == row["type"]
        unknown = {k: v for k, v in row.items() if k not in SavedBehavior.model_fields}
        assert behavior.model_extra == unknown
        assert behavior.behavior_type is None or isinstance(behavior.behavior_type, str)
