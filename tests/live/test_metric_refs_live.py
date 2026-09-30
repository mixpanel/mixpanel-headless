"""Live tests for querying a saved metric by reference.

Read-only. Each test picks a saved behavior metric that the caller can view,
queries it by reference (``MetricRef``), sends the same saved definition
inline, and checks that both give the same numbers. Nothing is created,
changed, or deleted.

Skipped by default. Enable with ``MP_LIVE_TESTS=1``.

Environment:
- ``MP_TEST_METRICS_ACCOUNT`` — account to use (default ``journey-lab-us``).
- ``MP_TEST_METRICS_PROJECT`` — project with saved metrics (default
  ``3409416``).
- ``MP_TEST_METRICS_FROM`` / ``MP_TEST_METRICS_TO`` — date range with data
  (default ``2024-09-01`` to ``2024-09-07``; the default project's clock
  reads 2024-09-15).

Usage:
    MP_LIVE_TESTS=1 uv run pytest tests/live/test_metric_refs_live.py -o addopts="" -q
"""

from __future__ import annotations

import os
from typing import Any, Literal

import pytest

import mixpanel_headless as mp
from mixpanel_headless.types import QueryResult

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MP_LIVE_TESTS") != "1",
        reason="MP_LIVE_TESTS=1 not set — live tests skipped by default",
    ),
]

_ACCOUNT = os.environ.get("MP_TEST_METRICS_ACCOUNT", "journey-lab-us")
_PROJECT = os.environ.get("MP_TEST_METRICS_PROJECT", "3409416")
_FROM = os.environ.get("MP_TEST_METRICS_FROM", "2024-09-01")
_TO = os.environ.get("MP_TEST_METRICS_TO", "2024-09-07")

_INLINE_BEHAVIOR_TYPES = ("event", "simple", "funnel", "retention")
"""Behavior types to try, in order of preference, for the inline comparison."""


@pytest.fixture(scope="module")
def ws() -> mp.Workspace:
    """One Workspace on the saved-metrics project for the whole module."""
    workspace = mp.Workspace(account=_ACCOUNT, project=_PROJECT)
    assert str(workspace.api.project_id) == _PROJECT
    return workspace


@pytest.fixture(scope="module")
def saved_metric(ws: mp.Workspace) -> dict[str, Any]:
    """A viewable saved behavior metric whose definition can be sent inline.

    Reads ``GET /projects/{pid}/metrics`` through the raw client (read-only).
    """
    raw = ws.api.app_request("GET", f"/projects/{ws.api.project_id}/metrics")
    rows: list[dict[str, Any]] = list(raw.values()) if isinstance(raw, dict) else raw
    candidates = [
        row
        for row in rows
        if row.get("type") == "metric"
        and row.get("can_view") is True
        and isinstance(row.get("definition"), dict)
        and (row["definition"].get("behavior") or {}).get("type")
        in _INLINE_BEHAVIOR_TYPES
    ]
    if not candidates:
        pytest.skip("no viewable saved behavior metric of a known type")
    return min(
        candidates,
        key=lambda row: (
            _INLINE_BEHAVIOR_TYPES.index(row["definition"]["behavior"]["type"]),
            int(row["id"]),
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
    params = ws.build_params("placeholder", from_date=_FROM, to_date=_TO)
    params["sections"]["show"] = [
        {
            "type": "metric",
            "behavior": definition["behavior"],
            "measurement": measurement,
        }
    ]
    return params


def test_reference_matches_inline_definition(
    ws: mp.Workspace, saved_metric: dict[str, Any]
) -> None:
    """A saved metric by reference gives the numbers of its inline definition."""
    definition = saved_metric["definition"]

    by_reference = ws.query(
        mp.MetricRef(int(saved_metric["id"])), from_date=_FROM, to_date=_TO
    )
    inline = ws.run_params(_inline_params(ws, definition, definition["measurement"]))

    assert by_reference.params["sections"]["show"] == [
        {"type": "metric", "id": int(saved_metric["id"])}
    ]
    assert _only_series(by_reference) == _only_series(inline)
    assert any(value for value in _only_series(by_reference).values())


def test_math_override_matches_inline_change(
    ws: mp.Workspace, saved_metric: dict[str, Any]
) -> None:
    """A math override gives the numbers of the inline definition with that math."""
    definition = saved_metric["definition"]
    new_math: Literal["total", "unique"] = (
        "total" if definition["measurement"].get("math") == "unique" else "unique"
    )

    by_reference = ws.query(
        mp.MetricRef(int(saved_metric["id"]), math=new_math),
        from_date=_FROM,
        to_date=_TO,
    )
    inline = ws.run_params(
        _inline_params(ws, definition, {**definition["measurement"], "math": new_math})
    )

    assert _only_series(by_reference) == _only_series(inline)
