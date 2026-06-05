"""Property-based tests for the session-replay series flattener (044).

`_flatten_series` walks a nested Insights ``series`` dict in group-by order,
skipping the ``$overall`` rollup key at every level, and emits one flat row per
surviving leaf. Invariants verified across randomly generated nestings:

- Every emitted row has exactly the group-by keys plus ``count``.
- ``$overall`` never leaks into a group-key column (rollups are skipped at
  every level).
- The flattener recovers exactly the non-rollup leaves that were planted —
  no more, no fewer — regardless of how many ``$overall`` siblings are injected.
- The walk is deterministic across repeated calls.
"""

from __future__ import annotations

from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from mixpanel_headless._internal.services.replays import _flatten_series

# Group-key values: short tokens that are never the rollup sentinel.
_safe_keys = st.text(
    alphabet="abcdefghijkmnpqrstuvwxyz0123456789-", min_size=1, max_size=8
).filter(lambda s: s != "$overall")


@st.composite
def _series_node(
    draw: st.DrawFn, group_names: list[str]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build ``(node, expected_rows)`` nesting ``len(group_names)`` levels.

    Plants 1–3 real (non-rollup) keys at each level and optionally injects an
    ``$overall`` rollup sibling that the flattener must ignore.

    Args:
        draw: Hypothesis draw callable.
        group_names: Remaining group-key names to nest, outermost first.

    Returns:
        A ``(node, expected_rows)`` pair: the nested dict and the exact list of
        flattened rows ``_flatten_series`` should produce for it.
    """
    prop = group_names[0]
    rest = group_names[1:]
    keys = draw(st.lists(_safe_keys, min_size=1, max_size=3, unique=True))

    node: dict[str, Any] = {}
    rows: list[dict[str, Any]] = []
    for key in keys:
        if rest:
            child, child_rows = draw(_series_node(rest))
            node[key] = child
            rows.extend({prop: key, **row} for row in child_rows)
        else:
            value = draw(st.integers(min_value=1, max_value=10**13))
            node[key] = {"all": value}
            rows.append({prop: key, "count": value})

    # Inject a rollup sibling that MUST be skipped (any shape — never descended).
    if draw(st.booleans()):
        node["$overall"] = {"all": draw(st.integers(min_value=0, max_value=10**13))}
    return node, rows


@st.composite
def _series_and_expected(
    draw: st.DrawFn,
) -> tuple[dict[str, Any], list[str], list[dict[str, Any]]]:
    """Build a full ``(series, group_by, expected_rows)`` example.

    Args:
        draw: Hypothesis draw callable.

    Returns:
        ``(series, group_by, expected_rows)`` — a one-metric series, the
        group-by names matching its nesting depth, and the exact rows the
        flattener should emit.
    """
    depth = draw(st.integers(min_value=1, max_value=4))
    group_names = [f"g{i}" for i in range(depth)]
    node, rows = draw(_series_node(group_names))
    metric = draw(_safe_keys)
    return {metric: node}, group_names, rows


def _normalize(rows: list[dict[str, Any]]) -> list[tuple[tuple[str, Any], ...]]:
    """Order-independent canonical form for a row list."""
    return sorted(tuple(sorted(row.items())) for row in rows)


@given(_series_and_expected())
@settings(max_examples=200)
def test_flatten_recovers_leaves_and_skips_overall(
    data: tuple[dict[str, Any], list[str], list[dict[str, Any]]],
) -> None:
    """Flattener recovers exactly the planted leaves; no $overall leaks."""
    series, group_by, expected = data
    rows = _flatten_series(series, group_by)

    for row in rows:
        assert set(row) == set(group_by) | {"count"}
        for key in group_by:
            assert row[key] != "$overall"

    assert _normalize(rows) == _normalize(expected)


@given(_series_and_expected())
@settings(max_examples=100)
def test_flatten_is_deterministic(
    data: tuple[dict[str, Any], list[str], list[dict[str, Any]]],
) -> None:
    """Repeated calls on the same series yield identical rows."""
    series, group_by, _expected = data
    assert _flatten_series(series, group_by) == _flatten_series(series, group_by)
