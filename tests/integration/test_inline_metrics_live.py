"""Live integration tests for inline metrics over several events, funnel metrics, and formulas.

Skipped by default — set ``MP_LIVE_TESTS=1`` and point auth at a project
with two events that share users. The queries are read-only. One test may
create a custom event, only when no custom event already unions the two
events and only on the project named by ``MP_TEST_WRITE_PROJECT``; it
deletes that custom event, by the id its own create returned, in teardown.

Environment:
- ``MP_LIVE_TESTS=1`` — enable.
- ``MP_TEST_ACCOUNT`` — account name (default: the active account).
- ``MP_TEST_EVENT_A`` / ``MP_TEST_EVENT_B`` — two event names (defaults
  ``login`` and ``sign up``).
- ``MP_TEST_EVENT_C`` — a funnel second step (default ``document opened``).
- ``MP_TEST_FROM`` / ``MP_TEST_TO`` — the date range (defaults
  ``2024-09-01`` and ``2024-09-07``).
- ``MP_TEST_FILTER_PROPERTY`` / ``MP_TEST_FILTER_VALUE`` — a string event
  property and a value that some events have (defaults ``$city`` and
  ``San Francisco``).
- ``MP_TEST_WRITE_PROJECT`` — the only project id where the test may create
  a custom event (unset: the test skips when none exists).

Markers:
- ``@pytest.mark.live`` lets the rest of the suite skip them via
  ``-m "not live"``.
- ``@pytest.mark.skipif`` short-circuits when ``MP_LIVE_TESTS`` is absent.
"""

from __future__ import annotations

import copy
import os
from collections.abc import Iterator

import pytest

import mixpanel_headless as mp
from mixpanel_headless.exceptions import QueryError

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("MP_LIVE_TESTS") != "1",
        reason="MP_LIVE_TESTS=1 not set — live tests skipped by default",
    ),
]

_ACCOUNT = os.environ.get("MP_TEST_ACCOUNT")
_A = os.environ.get("MP_TEST_EVENT_A", "login")
_B = os.environ.get("MP_TEST_EVENT_B", "sign up")
_C = os.environ.get("MP_TEST_EVENT_C", "document opened")
_FROM = os.environ.get("MP_TEST_FROM", "2024-09-01")
_TO = os.environ.get("MP_TEST_TO", "2024-09-07")
_PROPERTY = os.environ.get("MP_TEST_FILTER_PROPERTY", "$city")
_VALUE = os.environ.get("MP_TEST_FILTER_VALUE", "San Francisco")
_WRITE_PROJECT = os.environ.get("MP_TEST_WRITE_PROJECT")


@pytest.fixture(scope="module")
def ws() -> mp.Workspace:
    """One Workspace on the chosen account for the whole module."""
    return mp.Workspace(account=_ACCOUNT) if _ACCOUNT else mp.Workspace()


def _total(ws: mp.Workspace, events: object) -> float:
    """Run a total-mode query and return the single count.

    Args:
        ws: The workspace.
        events: The ``events`` argument of ``Workspace.query``.

    Returns:
        The count of the only series.
    """
    result = ws.query(events, from_date=_FROM, to_date=_TO, mode="total")  # type: ignore[arg-type]
    rows = result.df.to_dict("records")
    assert len(rows) == 1, rows
    return float(rows[0]["count"])


def _find_union_custom_event(ws: mp.Workspace) -> int | None:
    """Return the id of a custom event that unions exactly events A and B.

    Args:
        ws: The workspace.

    Returns:
        The custom event id, or ``None`` when no such custom event exists.
    """
    for definition in ws.list_custom_events():
        extra = definition.model_dump()
        alternatives = extra.get("alternatives") or []
        events = {a.get("event") for a in alternatives}
        unfiltered = all(
            not (a.get("valid_segfilter") or {}).get("filters") for a in alternatives
        )
        if events == {_A, _B} and len(alternatives) == 2 and unfiltered:
            return int(extra["custom_event_id"])
    return None


@pytest.fixture(scope="module")
def union_custom_event(ws: mp.Workspace) -> Iterator[int]:
    """Yield a custom event id that unions A and B; create one only if allowed.

    Yields:
        The custom event id.
    """
    found = _find_union_custom_event(ws)
    if found is not None:
        yield found
        return
    project = str(ws._session.project.id)
    if _WRITE_PROJECT is None or project != _WRITE_PROJECT:
        pytest.skip(
            "no custom event unions the two events, and MP_TEST_WRITE_PROJECT "
            "does not name this project"
        )
    created = ws.create_custom_event(
        mp.CreateCustomEventParams(
            name=f"zz-inline-metrics-live-{os.getpid()}", alternatives=[_A, _B]
        )
    )
    try:
        yield created.id
    finally:
        ws.delete_custom_event(created.id)


class TestMetricOverTwoEvents:
    """A metric over two events counts like the custom event of the same union."""

    def test_unique_matches_custom_event(
        self, ws: mp.Workspace, union_custom_event: int
    ) -> None:
        """Unique users over two events equal those of the union custom event."""
        several = _total(ws, mp.Metric([_A, _B], math="unique"))
        by_ref = _total(
            ws, mp.Metric(mp.CustomEventRef(union_custom_event), math="unique")
        )
        by_name = _total(
            ws, mp.Metric(f"$custom_event:{union_custom_event}", math="unique")
        )
        assert several == by_ref == by_name
        assert several > 0

    def test_display_name_of_a_custom_event_returns_no_rows(
        self, ws: mp.Workspace, union_custom_event: int
    ) -> None:
        """The display name of a custom event is not an event name."""
        names = {
            d.model_dump().get("custom_event_id"): d.name
            for d in ws.list_custom_events()
        }
        result = ws.query(
            names[union_custom_event], from_date=_FROM, to_date=_TO, mode="total"
        )
        assert result.df.empty


class TestSimpleBehaviorFilters:
    """Filters on a multi-event behavior work per event, not on the behavior."""

    def test_behavior_level_filters_are_ignored_and_event_filters_apply(
        self, ws: mp.Workspace
    ) -> None:
        """A behavior-level filter changes nothing; the same filter per event does."""
        city = mp.Filter.equals(_PROPERTY, _VALUE)
        unfiltered = _total(ws, mp.Metric([_A, _B], math="unique"))
        per_event = _total(ws, mp.Metric([_A, _B], math="unique", filters=[city]))

        params = ws.build_params(
            mp.Metric([_A, _B], math="unique"),
            from_date=_FROM,
            to_date=_TO,
            mode="total",
        )
        behavior = params["sections"]["show"][0]["behavior"]
        behavior["filters"] = copy.deepcopy(
            ws.build_params(
                mp.Metric(_A, filters=[city]), from_date=_FROM, to_date=_TO
            )["sections"]["show"][0]["behavior"]["filters"]
        )
        rows = ws.run_params(params).df.to_dict("records")
        behavior_level = float(rows[0]["count"])

        assert behavior_level == unfiltered
        assert per_event < unfiltered


class TestFunnelMetric:
    """A funnel metric gives the number of ``query_funnel`` for the same funnel."""

    def test_conversion_rate_matches_query_funnel(self, ws: mp.Workspace) -> None:
        """The funnel metric's rate equals the overall rate of query_funnel."""
        behavior = mp.FunnelBehavior([_A, _C])
        rate = _total(ws, mp.FunnelMetric(behavior))
        engine = ws.query_funnel([_A, _C], from_date=_FROM, to_date=_TO)
        assert rate == pytest.approx(engine.overall_conversion_rate)

    def test_time_math_without_property_is_refused_by_the_server(
        self, ws: mp.Workspace
    ) -> None:
        """A funnel clause with ``average`` and no property fails on the server."""
        params = ws.build_params(
            mp.FunnelMetric(mp.FunnelBehavior([_A, _C])),
            from_date=_FROM,
            to_date=_TO,
            mode="total",
        )
        params["sections"]["show"][0]["measurement"]["math"] = "average"
        with pytest.raises(QueryError):
            ws.run_params(params)


class TestFormulaWithOperands:
    """A formula with its own operands computes over them, not the query's metrics."""

    def test_ratio_of_operands(self, ws: mp.Workspace) -> None:
        """``A / B`` over two operands equals the ratio of their counts."""
        a = _total(ws, mp.Metric(_B, math="unique"))
        b = _total(ws, mp.Metric(_A, math="unique"))
        formula = mp.Formula(
            "A / B",
            label="ratio",
            metrics=[mp.Metric(_B, math="unique"), mp.Metric(_A, math="unique")],
        )
        assert _total(ws, formula) == pytest.approx(a / b)
