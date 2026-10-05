"""Live tests for querying a saved metric by reference.

Read-only. Each test picks a saved behavior metric that the caller can view
(``list_metrics``), queries it by reference, sends the same saved definition
inline, and checks that both give the same numbers. Nothing is created,
changed, or deleted.

Usage:
    MP_LIVE_ACCOUNT=<account> uv run pytest tests/live/test_metric_refs_live.py -m live -v

Environment:
    - ``MP_LIVE_ACCOUNT`` — the configured account to read with. The suite
      skips when it is unset. The Workspace uses the account's default
      project, which needs at least one viewable saved behavior metric.
    - ``MP_LIVE_FROM`` and ``MP_LIVE_TO`` — optional date range
      (YYYY-MM-DD) with data for that metric. Without them the queries use
      the last 30 days, which is empty when the project's clock is behind.
"""

from __future__ import annotations

import os
from typing import Any, Literal

import pytest

import mixpanel_headless as mp
from mixpanel_headless.types import QueryResult

pytestmark = pytest.mark.live

_INLINE_BEHAVIOR_TYPES = ("event", "simple", "funnel", "retention")
"""Behavior types to try, in order of preference, for the inline comparison."""


def _window() -> dict[str, Any]:
    """Return the date arguments of every query in this module.

    Returns:
        ``from_date`` and ``to_date`` from ``MP_LIVE_FROM`` and
        ``MP_LIVE_TO`` when both are set, otherwise ``last=30``.
    """
    from_date = os.environ.get("MP_LIVE_FROM")
    to_date = os.environ.get("MP_LIVE_TO")
    if from_date and to_date:
        return {"from_date": from_date, "to_date": to_date}
    return {"last": 30}


@pytest.fixture(scope="module")
def ws() -> mp.Workspace:
    """One Workspace on the ``MP_LIVE_ACCOUNT`` account, or a skip when unset."""
    account = os.environ.get("MP_LIVE_ACCOUNT")
    if not account:
        pytest.skip("MP_LIVE_ACCOUNT is not set")
    return mp.Workspace(account=account)


@pytest.fixture(scope="module")
def saved_metric(ws: mp.Workspace) -> mp.SavedMetric:
    """A viewable saved behavior metric whose definition can be sent inline.

    Reads the saved metrics with ``list_metrics(viewable_only=True)``.
    """
    candidates = [
        metric
        for metric in ws.list_metrics(metric_type="metric", viewable_only=True)
        if metric.behavior_type in _INLINE_BEHAVIOR_TYPES
        and isinstance(metric.definition.get("measurement"), dict)
    ]
    if not candidates:
        pytest.skip("no viewable saved behavior metric of a known type")
    return min(
        candidates,
        key=lambda metric: (
            _INLINE_BEHAVIOR_TYPES.index(str(metric.behavior_type)),
            metric.id,
        ),
    )


def _only_series(result: QueryResult) -> dict[str, Any]:
    """Return the value map of the single series of a result.

    Args:
        result: A query result with one series.

    Returns:
        The ``{date: value}`` map of that series.
    """
    assert len(result.series) == 1, result.series
    values: dict[str, Any] = next(iter(result.series.values()))
    return values


def _inline_params(
    ws: mp.Workspace, definition: dict[str, Any], measurement: dict[str, Any]
) -> dict[str, Any]:
    """Build params that send a saved definition inline.

    Args:
        ws: The workspace.
        definition: The saved metric definition.
        measurement: The measurement block to send.

    Returns:
        Insights params whose only show clause is the inline definition.
    """
    params = ws.build_params("placeholder", **_window())
    params["sections"]["show"] = [
        {
            "type": "metric",
            "behavior": definition["behavior"],
            "measurement": measurement,
        }
    ]
    return params


def test_reference_matches_inline_definition(
    ws: mp.Workspace, saved_metric: mp.SavedMetric
) -> None:
    """A saved metric by reference gives the numbers of its inline definition."""
    definition = saved_metric.definition

    by_reference = ws.query(saved_metric, **_window())
    inline = ws.run_params(_inline_params(ws, definition, definition["measurement"]))

    assert by_reference.params["sections"]["show"] == [
        {"type": "metric", "id": saved_metric.id}
    ]
    assert _only_series(by_reference) == _only_series(inline)
    if not any(value for value in _only_series(by_reference).values()):
        pytest.skip("no data in the window; set MP_LIVE_FROM and MP_LIVE_TO")


def test_math_override_matches_inline_change(
    ws: mp.Workspace, saved_metric: mp.SavedMetric
) -> None:
    """A math override gives the numbers of the inline definition with that math."""
    definition = saved_metric.definition
    new_math: Literal["total", "unique"] = (
        "total" if saved_metric.math == "unique" else "unique"
    )

    by_reference = ws.query(saved_metric.to_ref(math=new_math), **_window())
    inline = ws.run_params(
        _inline_params(ws, definition, {**definition["measurement"], "math": new_math})
    )

    assert _only_series(by_reference) == _only_series(inline)
