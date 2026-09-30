"""Live integration tests for inline metrics over several events, funnel metrics, and formulas.

Skipped by default (the ``live`` marker). The queries are read-only. One
step may create a custom event, only when no custom event already unions
the two events and only when the resolved project id equals
``MP_LIVE_WRITE_PROJECT``; it deletes that custom event, by the id its own
create returned, in teardown.

Usage:
    MP_LIVE_ACCOUNT=<account> MP_LIVE_WRITE_PROJECT=<project id> \\
        uv run pytest tests/live/test_inline_metrics_live.py -m live -v

Environment:
- ``MP_LIVE_ACCOUNT`` — the account the suite uses (unset: the suite skips).
- ``MP_LIVE_WRITE_PROJECT`` — write steps run only when the resolved
  project id equals it (unset or different: the write step skips).
- ``MP_LIVE_EVENT_A`` / ``MP_LIVE_EVENT_B`` — two event names that share
  users (defaults ``login`` and ``sign up``).
- ``MP_LIVE_EVENT_C`` — a funnel second step (default ``document opened``).
- ``MP_LIVE_FROM`` / ``MP_LIVE_TO`` — the date range (defaults
  ``2024-09-01`` and ``2024-09-07``).
- ``MP_LIVE_FILTER_PROPERTY`` / ``MP_LIVE_FILTER_VALUE`` — a string event
  property and a value that some events have (defaults ``$city`` and
  ``San Francisco``).

Rate limits: the client does not retry a 429 here. A test that gets one is
skipped, and the skip reason records the error, so a shared project is not
queried again while its limit runs.

Markers:
- ``@pytest.mark.live`` lets the rest of the suite skip them via
  ``-m "not live"``.
- ``@pytest.mark.skipif`` short-circuits when ``MP_LIVE_ACCOUNT`` is absent.
"""

from __future__ import annotations

import copy
import functools
import os
from collections.abc import Callable, Iterator
from typing import ParamSpec

import pytest

import mixpanel_headless as mp
from mixpanel_headless.exceptions import QueryError, RateLimitError

_P = ParamSpec("_P")

_ACCOUNT = os.environ.get("MP_LIVE_ACCOUNT")
_WRITE_PROJECT = os.environ.get("MP_LIVE_WRITE_PROJECT")
_A = os.environ.get("MP_LIVE_EVENT_A", "login")
_B = os.environ.get("MP_LIVE_EVENT_B", "sign up")
_C = os.environ.get("MP_LIVE_EVENT_C", "document opened")
_FROM = os.environ.get("MP_LIVE_FROM", "2024-09-01")
_TO = os.environ.get("MP_LIVE_TO", "2024-09-07")
_PROPERTY = os.environ.get("MP_LIVE_FILTER_PROPERTY", "$city")
_VALUE = os.environ.get("MP_LIVE_FILTER_VALUE", "San Francisco")

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        not _ACCOUNT,
        reason="MP_LIVE_ACCOUNT not set — the suite needs a named account",
    ),
]


def _skip_on_429(test: Callable[_P, None]) -> Callable[_P, None]:
    """Turn a rate-limit error in a test into a skip that records it.

    Args:
        test: The test function.

    Returns:
        The wrapped test.
    """

    @functools.wraps(test)
    def wrapper(*args: _P.args, **kwargs: _P.kwargs) -> None:
        """Run the test; skip with the error text on a 429."""
        try:
            test(*args, **kwargs)
        except RateLimitError as exc:
            pytest.skip(f"429 from the project, not retried: {exc}")

    return wrapper


@pytest.fixture(scope="module")
def ws() -> mp.Workspace:
    """One Workspace on ``MP_LIVE_ACCOUNT``, with no retry on a 429."""
    workspace = mp.Workspace(account=_ACCOUNT)
    workspace._require_api_client()._max_retries = 0
    return workspace


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
    try:
        found = _find_union_custom_event(ws)
    except RateLimitError as exc:
        pytest.skip(f"429 from the project, not retried: {exc}")
    if found is not None:
        yield found
        return
    project = str(ws._session.project.id)
    if _WRITE_PROJECT is None or project != _WRITE_PROJECT:
        pytest.skip(
            "no custom event unions the two events, and the resolved project "
            "id does not equal MP_LIVE_WRITE_PROJECT"
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

    @_skip_on_429
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

    @_skip_on_429
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

    @_skip_on_429
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

    @_skip_on_429
    def test_conversion_rate_matches_query_funnel(self, ws: mp.Workspace) -> None:
        """The funnel metric's rate equals the overall rate of query_funnel."""
        behavior = mp.FunnelBehavior([_A, _C])
        rate = _total(ws, mp.FunnelMetric(behavior))
        engine = ws.query_funnel([_A, _C], from_date=_FROM, to_date=_TO)
        assert rate == pytest.approx(engine.overall_conversion_rate)

    @_skip_on_429
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

    @_skip_on_429
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


@pytest.fixture(scope="module")
def two_saved_metrics(ws: mp.Workspace) -> tuple[int, int]:
    """Return the ids of two viewable saved behavior metrics.

    Reads ``list_metrics(viewable_only=True)`` and keeps the saved behavior
    metrics over events, funnels, and retention, which give one total each.

    Returns:
        Two saved metric ids, lowest first.
    """
    try:
        saved = ws.list_metrics(metric_type="metric", viewable_only=True)
    except RateLimitError as exc:
        pytest.skip(f"429 from the project, not retried: {exc}")
    kinds = ("event", "simple", "funnel", "retention")
    ids = sorted(m.id for m in saved if m.behavior_type in kinds)
    if len(ids) < 2:
        pytest.skip("fewer than two viewable saved behavior metrics")
    return ids[0], ids[1]


class TestFormulaWithSavedMetricOperands:
    """An inline formula over saved metrics computes over their saved definitions."""

    @_skip_on_429
    def test_ratio_of_saved_metrics(
        self, ws: mp.Workspace, two_saved_metrics: tuple[int, int]
    ) -> None:
        """``A / B`` over two ``MetricRef`` operands equals the ratio of the refs."""
        first, second = two_saved_metrics
        a = _total(ws, mp.MetricRef(first))
        b = _total(ws, mp.MetricRef(second))
        if b == 0:
            pytest.skip(f"saved metric {second} has no data in the date range")
        formula = mp.Formula(
            "A / B",
            label="ratio of saved metrics",
            metrics=[mp.MetricRef(first), mp.MetricRef(second)],
        )
        assert _total(ws, formula) == pytest.approx(a / b)
