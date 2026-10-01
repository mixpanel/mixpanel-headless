"""Live QA tests for saved metric and saved behavior writes.

Creates saved metrics and saved behaviors, changes them, and deletes them.
The project can be shared with other users. Safety rules, enforced in code:

- The tests run only when ``MP_LIVE_ACCOUNT`` is set, and they write only
  when the account's project id equals ``MP_LIVE_WRITE_PROJECT``; otherwise
  they skip before any write.
- Every created entity has a name prefix unique to the run:
  ``zz-headless-live-`` plus eight random hex characters.
- A test changes or deletes only ids that its own creates returned in the
  same run. Each update and delete first asserts that its target id is in
  the created set.
- Before the first test, the module records the ids of the active metrics
  and behaviors (the start snapshot).
- The module teardown deletes the created ids. A create can commit on the
  server and still fail on the client (a timeout, or a ``create_metric``
  whose follow-up update fails), so its id never reaches the created set.
  The teardown then also deletes every active metric and behavior whose
  name starts with the run prefix and whose id is not in the start
  snapshot.
- The teardown writes an audit record (the run prefix, the created ids,
  the swept ids, and any id still active) to
  ``saved_metrics_write_live.json`` in the temp directory.

Usage:
    MP_LIVE_ACCOUNT=<account> MP_LIVE_WRITE_PROJECT=<project id> \
        uv run pytest tests/live/test_saved_metrics_write_live.py -v -m live

Environment:
    - ``MP_LIVE_ACCOUNT`` — the configured account; the suite skips when it
      is unset.
    - ``MP_LIVE_WRITE_PROJECT`` — the only project id the tests write to; the
      suite skips when it is unset or differs from the account's project.
    - ``MP_LIVE_EVENT_A`` and ``MP_LIVE_EVENT_B`` — two event names for the
      metric definitions. Optional: a create does not need the events to
      exist, so the default names are placeholders. The reference-query
      step compares numbers, so it needs real events to mean something.
    - ``MP_LIVE_FROM`` and ``MP_LIVE_TO`` — optional date range
      (YYYY-MM-DD) with data for the events. Without them the queries use
      the last 30 days, which is empty when the project's clock is behind.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

import pytest

import mixpanel_headless as mp
from mixpanel_headless.exceptions import ParamValidationError, QueryError

# All tests require the `live` marker — skipped by default
pytestmark = pytest.mark.live

_EVENTS = [
    os.environ.get("MP_LIVE_EVENT_A", "zz-headless-live event a"),
    os.environ.get("MP_LIVE_EVENT_B", "zz-headless-live event b"),
]


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


_PREFIX = f"zz-headless-live-{uuid.uuid4().hex[:8]}-"


@dataclass
class _Created:
    """The ids that this run created, the only ids it may change or delete."""

    metrics: set[int] = field(default_factory=set)
    """Saved metric ids returned by this run's creates."""

    behaviors: set[int] = field(default_factory=set)
    """Saved behavior ids returned by this run's creates."""

    def own_metric(self, metric_id: int) -> int:
        """Assert that this run created a metric, before a change or delete.

        Args:
            metric_id: The target metric id.

        Returns:
            The same id.
        """
        assert metric_id in self.metrics, f"refusing to touch metric {metric_id}"
        return metric_id

    def own_behavior(self, behavior_id: int) -> int:
        """Assert that this run created a behavior, before a change or delete.

        Args:
            behavior_id: The target behavior id.

        Returns:
            The same id.
        """
        assert behavior_id in self.behaviors, (
            f"refusing to touch behavior {behavior_id}"
        )
        return behavior_id


def _write_project() -> str:
    """Return the write project id from ``MP_LIVE_WRITE_PROJECT``, or skip.

    Returns:
        The project id that write steps may change.
    """
    project = os.environ.get("MP_LIVE_WRITE_PROJECT")
    if not project:
        pytest.skip("MP_LIVE_WRITE_PROJECT is not set; write steps are off")
    return project


@pytest.fixture(scope="module")
def ws() -> mp.Workspace:
    """A Workspace on ``MP_LIVE_ACCOUNT`` whose project is the write project, or a skip."""
    account = os.environ.get("MP_LIVE_ACCOUNT")
    if not account:
        pytest.skip("MP_LIVE_ACCOUNT is not set")
    write_project = _write_project()
    workspace = mp.Workspace(account=account)
    if str(workspace.api.project_id) != write_project:
        pytest.skip(
            f"the account resolves to project {workspace.api.project_id}, not the "
            f"write project {write_project}"
        )
    return workspace


def _run_ids(
    rows: Iterable[mp.SavedMetric | mp.SavedBehavior], before: set[int]
) -> set[int]:
    """Return the ids of the rows that this run created, tracked or not.

    Args:
        rows: Active saved metrics or saved behaviors.
        before: The ids of the start snapshot.

    Returns:
        The ids whose name starts with the run prefix and that the start
        snapshot does not hold.
    """
    return {
        row.id for row in rows if row.name.startswith(_PREFIX) and row.id not in before
    }


@pytest.fixture(scope="module")
def created(ws: mp.Workspace) -> Iterator[_Created]:
    """Track created ids; at module teardown, delete them and sweep untracked ones.

    Args:
        ws: The write Workspace.

    Yields:
        The tracker that each create adds its id to.
    """
    before_metrics = {m.id for m in ws.list_metrics()}
    before_behaviors = {b.id for b in ws.list_behaviors()}
    tracker = _Created()
    yield tracker
    assert str(ws.api.project_id) == _write_project()
    if tracker.metrics:
        ws.delete_metrics(sorted(tracker.metrics))
    if tracker.behaviors:
        ws.delete_behaviors(sorted(tracker.behaviors))
    swept_metrics = _run_ids(ws.list_metrics(), before_metrics) - tracker.metrics
    swept_behaviors = (
        _run_ids(ws.list_behaviors(), before_behaviors) - tracker.behaviors
    )
    assert str(ws.api.project_id) == _write_project()
    if swept_metrics:
        ws.delete_metrics(sorted(swept_metrics))
    if swept_behaviors:
        ws.delete_behaviors(sorted(swept_behaviors))
    active_metrics = ws.list_metrics()
    active_behaviors = ws.list_behaviors()
    remaining_metrics = {
        m.id for m in active_metrics if m.id in tracker.metrics
    } | _run_ids(active_metrics, before_metrics)
    remaining_behaviors = {
        b.id for b in active_behaviors if b.id in tracker.behaviors
    } | _run_ids(active_behaviors, before_behaviors)
    audit = {
        "prefix": _PREFIX,
        "project_id": str(ws.api.project_id),
        "created_metrics": sorted(tracker.metrics),
        "created_behaviors": sorted(tracker.behaviors),
        "swept_metrics": sorted(swept_metrics),
        "swept_behaviors": sorted(swept_behaviors),
        "active_after_teardown": sorted(remaining_metrics | remaining_behaviors),
    }
    audit_path = os.path.join(tempfile.gettempdir(), "saved_metrics_write_live.json")
    with open(audit_path, "w", encoding="utf-8") as handle:
        json.dump(audit, handle, indent=2)
    assert remaining_metrics == set()
    assert remaining_behaviors == set()


class TestSavedMetricWriteCycle:
    """Create, read, update, and bulk update one saved metric."""

    def test_cycle(self, ws: mp.Workspace, created: _Created) -> None:
        """A typed metric round-trips through every write method."""
        name = f"{_PREFIX}event-total"
        metric = ws.create_metric(
            mp.CreateMetricParams(
                name=name,
                definition=mp.Metric(_EVENTS[0], math="total"),
                description="Scratch metric of an automated library test.",
                display=mp.MetricDisplay(suffix=" docs", precision=0),
                goals=[mp.MetricGoal(label="Target", checkpoints=[("2024-09-30", 10)])],
                verified=True,
            )
        )
        created.metrics.add(metric.id)
        assert metric.name == name
        assert metric.type == "metric"
        assert metric.verified is True
        assert metric.math == "total"
        assert metric.display is not None
        assert metric.display.suffix == " docs"
        (goal,) = metric.goals
        assert goal.id

        fetched = ws.get_metric(metric.id)
        assert fetched.definition == metric.definition

        updated = ws.update_metric(
            created.own_metric(metric.id),
            mp.UpdateMetricParams(display=mp.MetricDisplay(precision=2)),
        )
        assert updated.definition["behavior"] == metric.definition["behavior"]
        assert updated.definition["display"] == {"precision": 2}
        assert updated.definition["goals"] == metric.definition["goals"]

        redefined = ws.update_metric(
            created.own_metric(metric.id),
            mp.UpdateMetricParams(definition=mp.Metric(_EVENTS[0], math="unique")),
        )
        assert redefined.math == "unique"
        assert redefined.definition["display"] == {"precision": 2}

        with pytest.raises(ParamValidationError) as exc_info:
            ws.update_metric(
                created.own_metric(metric.id),
                mp.UpdateMetricParams(
                    definition=mp.RawMetricDefinition(
                        "formula",
                        {"formula": {"definition": "A", "referencedMetrics": []}},
                    )
                ),
            )
        assert exc_info.value.code == "SM3_KIND_CHANGE"

        (unverified,) = ws.bulk_update_metrics(
            [mp.BulkUpdateMetricEntry(id=created.own_metric(metric.id), verified=False)]
        )
        assert unverified.verified is False

    def test_duplicate_name_is_refused(
        self, ws: mp.Workspace, created: _Created
    ) -> None:
        """A second active metric with the same name gets a 409."""
        name = f"{_PREFIX}duplicate"
        first = ws.create_metric(
            mp.CreateMetricParams(name=name, definition=mp.Metric(_EVENTS[0]))
        )
        created.metrics.add(first.id)
        with pytest.raises(QueryError) as exc_info:
            ws.create_metric(
                mp.CreateMetricParams(name=name, definition=mp.Metric(_EVENTS[1]))
            )
        assert exc_info.value.status_code == 409


class TestTypedDefinitionsLive:
    """Typed values save through the definition compiler and query by reference."""

    def test_formula_and_funnel_metric(
        self, ws: mp.Workspace, created: _Created
    ) -> None:
        """A formula with operands and a funnel metric save with their kinds."""
        formula = ws.create_metric(
            mp.CreateMetricParams(
                name=f"{_PREFIX}formula",
                definition=mp.Formula(
                    "A / B",
                    metrics=[mp.Metric(_EVENTS[0]), mp.Metric(_EVENTS[1])],
                ),
            )
        )
        created.metrics.add(formula.id)
        assert formula.type == "formula"
        assert formula.formula_expression == "A / B"

        funnel = ws.create_metric(
            mp.CreateMetricParams(
                name=f"{_PREFIX}funnel",
                definition=mp.FunnelMetric(mp.FunnelBehavior(list(_EVENTS))),
            )
        )
        created.metrics.add(funnel.id)
        assert funnel.type == "metric"
        assert funnel.behavior_type == "funnel"

    def test_reference_query_matches_inline(
        self, ws: mp.Workspace, created: _Created
    ) -> None:
        """A created metric queried by reference gives the numbers of its inline twin."""
        inline_metric = mp.Metric(_EVENTS[0], math="total")
        saved = ws.create_metric(
            mp.CreateMetricParams(
                name=f"{_PREFIX}by-reference", definition=inline_metric
            )
        )
        created.metrics.add(saved.id)

        by_reference = ws.query(saved, **_window())
        inline = ws.query(inline_metric, **_window())

        assert by_reference.params["sections"]["show"][0]["id"] == saved.id
        (reference_series,) = by_reference.series.values()
        (inline_series,) = inline.series.values()
        assert reference_series == inline_series


class TestSavedBehaviorWriteCycle:
    """Create and update one saved behavior."""

    def test_cycle(self, ws: mp.Workspace, created: _Created) -> None:
        """A raw funnel behavior round-trips through create and update."""
        definition = {
            "behavior": {
                "type": "funnel",
                "resourceType": "events",
                "behaviors": [
                    {"type": "event", "name": event, "filters": []} for event in _EVENTS
                ],
                "conversionWindowDuration": 7,
                "conversionWindowUnit": "day",
                "funnelOrder": "loose",
                "exclusions": [],
                "aggregateBy": [],
            }
        }
        behavior = ws.create_behavior(
            mp.CreateBehaviorParams(
                name=f"{_PREFIX}funnel",
                behavior=mp.RawBehaviorDefinition(definition),
            )
        )
        created.behaviors.add(behavior.id)
        assert behavior.type == "funnel"
        assert behavior.description is None

        updated = ws.update_behavior(
            created.own_behavior(behavior.id),
            mp.UpdateBehaviorParams(description="Scratch behavior.", verified=True),
        )
        assert updated.verified is True
        assert updated.description == "Scratch behavior."

        with pytest.raises(ParamValidationError) as exc_info:
            ws.update_behavior(
                created.own_behavior(behavior.id),
                mp.UpdateBehaviorParams(
                    behavior=mp.RawBehaviorDefinition(
                        {"behavior": {"type": "simple", "behaviors": []}}
                    )
                ),
            )
        assert exc_info.value.code == "SM3_KIND_CHANGE"
