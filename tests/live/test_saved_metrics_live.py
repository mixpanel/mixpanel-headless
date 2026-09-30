"""Live QA tests for saved metrics and saved behaviors (read only).

Lists and gets saved metrics and saved behaviors against the real
``/metrics`` and ``/behaviors`` App API endpoints, on the account
``journey-lab-us`` (project 3409416, a shared project), and checks that
every row parses into the open read models. The tests create, change, and
delete nothing.

Usage:
    uv run pytest tests/live/test_saved_metrics_live.py -v -m live
    MP_SAVED_METRICS_ACCOUNT=other uv run pytest tests/live/test_saved_metrics_live.py -v -m live

Constraints:
    - Reads only; safe on a shared project.
    - ``MP_SAVED_METRICS_ACCOUNT`` overrides the account (default
      ``journey-lab-us``).
"""

from __future__ import annotations

import os

import pytest

import mixpanel_headless as mp

# All tests require the `live` marker — skipped by default
pytestmark = pytest.mark.live

_ACCOUNT = os.environ.get("MP_SAVED_METRICS_ACCOUNT", "journey-lab-us")


@pytest.fixture(scope="module")
def ws() -> mp.Workspace:
    """One Workspace on the saved-metrics test account for the whole module."""
    return mp.Workspace(account=_ACCOUNT)


class TestSavedMetricsLive:
    """list_metrics and get_metric against the real endpoint."""

    def test_list_then_get_first(self, ws: mp.Workspace) -> None:
        """The list parses; when it is non-empty, get_metric returns the first row."""
        metrics = ws.list_metrics()
        assert all(isinstance(m, mp.SavedMetric) for m in metrics)
        for metric in metrics:
            _ = (metric.behavior_type, metric.math, metric.formula_expression)
            _ = (metric.referenced_metric_ids, metric.display, metric.goals)
        if not metrics:
            pytest.skip("The project has no saved metrics to get.")
        first = ws.get_metric(metrics[0].id)
        assert first.id == metrics[0].id
        assert first.name == metrics[0].name
        assert first.type == metrics[0].type

    def test_filters_are_subsets(self, ws: mp.Workspace) -> None:
        """Each filtered list is a subset of the full list."""
        all_ids = {m.id for m in ws.list_metrics()}
        for kind in ("metric", "formula", "warehouse"):
            subset = ws.list_metrics(metric_type=kind)
            assert {m.id for m in subset} <= all_ids
            assert all(m.type == kind for m in subset)
        viewable = ws.list_metrics(viewable_only=True)
        assert all(m.can_view is not False for m in viewable)


class TestSavedBehaviorsLive:
    """list_behaviors and get_behavior against the real endpoint."""

    def test_list_then_get_first(self, ws: mp.Workspace) -> None:
        """The list parses; when it is non-empty, get_behavior returns the first row."""
        behaviors = ws.list_behaviors()
        assert all(isinstance(b, mp.SavedBehavior) for b in behaviors)
        if not behaviors:
            pytest.skip("The project has no saved behaviors to get.")
        first = ws.get_behavior(behaviors[0].id)
        assert first.id == behaviors[0].id
        assert first.type == behaviors[0].type
