"""Live QA tests for saved metric and saved behavior writes.

Creates saved metrics and saved behaviors, changes them, and deletes them.
The project can be shared with other users. Safety rules, enforced in code:

- The tests run only when ``MP_LIVE_ACCOUNT`` is set, and they write only
  when the account's project id equals ``MP_LIVE_WRITE_PROJECT``; otherwise
  they skip before any write.
- Every created entity has a ``zz-`` name prefix.
- A test changes or deletes only ids that its own creates returned in the
  same run. Each update and delete first asserts that its target id is in
  the created set.
- The module teardown deletes only the created ids.

Usage:
    MP_LIVE_ACCOUNT=<account> MP_LIVE_WRITE_PROJECT=<project id> \
        uv run pytest tests/live/test_saved_metrics_write_live.py -v -m live

Environment:
    - ``MP_LIVE_ACCOUNT`` — the configured account; the suite skips when it
      is unset.
    - ``MP_LIVE_WRITE_PROJECT`` — the only project id the tests write to; the
      suite skips when it is unset or differs from the account's project.
    - ``MP_LIVE_EVENTS`` — two event names for the metric definitions, comma
      separated. Optional: a create does not need the events to exist, so
      the default names are placeholders.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field

import pytest

import mixpanel_headless as mp
from mixpanel_headless.exceptions import ParamValidationError, QueryError

# All tests require the `live` marker — skipped by default
pytestmark = pytest.mark.live

_EVENTS = os.environ.get(
    "MP_LIVE_EVENTS", "zz-headless-live event a,zz-headless-live event b"
).split(",")
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


@pytest.fixture(scope="module")
def created(ws: mp.Workspace) -> Iterator[_Created]:
    """Track created ids and delete exactly those at module teardown.

    Args:
        ws: The write Workspace.

    Yields:
        The tracker that each create adds its id to.
    """
    tracker = _Created()
    yield tracker
    assert str(ws.api.project_id) == _write_project()
    if tracker.metrics:
        ws.delete_metrics(sorted(tracker.metrics))
    if tracker.behaviors:
        ws.delete_behaviors(sorted(tracker.behaviors))
    remaining = {m.id for m in ws.list_metrics()} & tracker.metrics
    remaining |= {b.id for b in ws.list_behaviors()} & tracker.behaviors
    assert remaining == set()


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
