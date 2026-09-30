# ruff: noqa: ARG001
"""Property-based tests for the saved metric write path.

Properties tested:
- ``create_metric`` saves the same ``behavior`` and ``measurement`` that
  ``build_params`` writes into ``sections.show`` for the same inline metric
  (event, several events, cohort, funnel, and retention metrics), apart from
  the legacy keys that a create rejects and the server reads past, so a
  saved metric queries the same way as its inline twin
- ``create_metric`` saves the same ``referencedMetrics`` that
  ``build_params`` writes for the same formula with its own operands
- ``goal_to_wire`` always writes a string id and string checkpoint times,
  and never writes the deprecated ``unit`` and ``direction`` keys
- ``check_formula_operands`` accepts every operand whose segment method and
  attribution are absent or null

Usage:
    pytest tests/unit/test_saved_definitions_pbt.py
    HYPOTHESIS_PROFILE=dev pytest tests/unit/test_saved_definitions_pbt.py
    HYPOTHESIS_PROFILE=ci pytest tests/unit/test_saved_definitions_pbt.py
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

import httpx
from hypothesis import assume, given
from hypothesis import strategies as st
from pydantic import SecretStr

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless._internal.saved_definitions import (
    check_formula_operands,
    find_server_skipped_keys,
    goal_to_wire,
    strip_server_skipped_keys,
)
from mixpanel_headless.types import (
    CohortMetric,
    CreateMetricParams,
    CustomEventRef,
    Formula,
    FunnelBehavior,
    FunnelMetric,
    FunnelStep,
    MathType,
    Metric,
    MetricGoal,
    RetentionBehavior,
    RetentionMetric,
)
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session
from tests.unit._saved_metric_fixtures import behavior_metric_json, envelope

_SESSION = Session(
    account=ServiceAccount(
        name="test_account",
        region="us",
        username="test_user",
        secret=SecretStr("test_secret"),
        default_project="12345",
    ),
    project=Project(id="12345"),
)

# =============================================================================
# Strategies
# =============================================================================

_event_names = st.text(
    alphabet=st.characters(categories=("L", "N"), include_characters=" _-$."),
    min_size=1,
    max_size=30,
).filter(lambda s: s.strip())

_PLAIN_MATHS: list[MathType] = ["total", "unique", "dau", "wau", "mau", "sessions"]
_PROPERTY_MATHS: list[MathType] = ["average", "median", "min", "max", "p90"]
_plain_maths = st.sampled_from(_PLAIN_MATHS)
_property_maths = st.sampled_from(_PROPERTY_MATHS)


InlineMetric = Metric | CohortMetric | FunnelMetric | RetentionMetric
"""The inline metric values that a saved behavior metric can hold."""


@st.composite
def inline_metrics(draw: st.DrawFn) -> InlineMetric:
    """Generate an inline metric that a saved behavior metric can hold.

    Args:
        draw: Hypothesis draw function.

    Returns:
        A ``Metric`` (one or two events, plain or property math, optional
        segment method), a ``CohortMetric`` over a saved cohort id, a
        ``FunnelMetric`` over two or three steps, or a ``RetentionMetric``.
    """
    choice = draw(st.integers(min_value=0, max_value=5))
    if choice == 0:
        return Metric(
            draw(_event_names),
            math=draw(_plain_maths),
            segment_method=draw(st.sampled_from([None, "all", "first"])),
        )
    if choice == 1:
        return Metric(
            draw(_event_names),
            math=draw(_property_maths),
            property=draw(_event_names),
        )
    if choice == 2:
        events: list[str | CustomEventRef] = list(
            draw(st.lists(_event_names, min_size=2, max_size=3, unique=True))
        )
        return Metric(events, math=draw(_plain_maths))
    if choice == 3:
        steps: list[str | FunnelStep] = list(
            draw(st.lists(_event_names, min_size=2, max_size=3))
        )
        return FunnelMetric(
            FunnelBehavior(steps, conversion_window=draw(st.integers(1, 30)))
        )
    if choice == 4:
        return RetentionMetric(
            RetentionBehavior(draw(_event_names), draw(_event_names))
        )
    return CohortMetric(draw(st.integers(min_value=1, max_value=10**9)), "Cohort")


def _workspace(captured: list[httpx.Request]) -> Workspace:
    """Build a Workspace whose transport records requests and answers a create.

    Args:
        captured: List the handler appends each request to.

    Returns:
        A Workspace wired to the recording transport.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request and return one saved metric."""
        captured.append(request)
        return httpx.Response(200, json=envelope(behavior_metric_json()))

    creds = make_session(project_id="12345", region="us", oauth_token="t")
    client = MixpanelAPIClient(session=creds, _transport=httpx.MockTransport(handler))
    return Workspace(session=_SESSION, _api_client=client)


# =============================================================================
# Properties
# =============================================================================


@given(metric=inline_metrics())
def test_saved_definition_equals_query_show_clause(metric: InlineMetric) -> None:
    """The saved behavior and measurement equal those of the query show clause.

    Args:
        metric: A generated inline metric.
    """
    captured: list[httpx.Request] = []
    ws = _workspace(captured)
    ws.create_metric(CreateMetricParams(name="m", definition=metric))
    sent = json.loads(captured[0].content)["definition"]
    show = ws.build_params(metric)["sections"]["show"][0]
    expected = {"behavior": show["behavior"], "measurement": show["measurement"]}
    strip_server_skipped_keys("metric", expected)
    assert sent == expected
    assert find_server_skipped_keys("metric", sent) == []


@given(operands=st.lists(inline_metrics(), min_size=1, max_size=3))
def test_saved_formula_operands_equal_query_operands(
    operands: list[InlineMetric],
) -> None:
    """A saved formula holds the operands that the query formula clause holds.

    Operands with a segment method are left out: a saved formula refuses
    them (``FM6_OPERAND_ATTRIBUTION``), while a query accepts them.

    Args:
        operands: Generated inline operands.
    """
    assume(all(getattr(op, "segment_method", None) is None for op in operands))
    expression = " + ".join("ABC"[i] for i in range(len(operands)))
    formula = Formula(expression, metrics=list(operands))
    captured: list[httpx.Request] = []
    ws = _workspace(captured)
    ws.create_metric(CreateMetricParams(name="f", definition=formula))
    sent = json.loads(captured[0].content)
    assert sent["type"] == "formula"
    clause = ws.build_params(formula)["sections"]["show"][-1]
    expected = {
        "formula": {
            "definition": clause["definition"],
            "referencedMetrics": clause["referencedMetrics"],
        }
    }
    strip_server_skipped_keys("formula", expected)
    assert sent["definition"] == expected
    assert find_server_skipped_keys("formula", sent["definition"]) == []


_checkpoint_times = st.one_of(
    st.dates(min_value=date(2000, 1, 1), max_value=date(2100, 1, 1)),
    st.datetimes(min_value=datetime(2000, 1, 1), max_value=datetime(2100, 1, 1)),
    st.text(min_size=1, max_size=25),
)


@given(
    goal_id=st.one_of(st.none(), st.text(min_size=1, max_size=36)),
    label=st.text(max_size=30),
    checkpoints=st.lists(
        st.tuples(_checkpoint_times, st.floats(allow_nan=False, allow_infinity=False)),
        max_size=5,
    ),
    extras=st.dictionaries(
        st.sampled_from(["unit", "direction", "note"]), st.text(max_size=5), max_size=3
    ),
)
def test_goal_wire_shape(
    goal_id: str | None,
    label: str,
    checkpoints: list[tuple[Any, float]],
    extras: dict[str, str],
) -> None:
    """A written goal has a string id, string times, and no deprecated keys.

    Args:
        goal_id: The goal id, or None for a new goal.
        label: The goal label.
        checkpoints: Checkpoint pairs with mixed time types.
        extras: Unknown keys, including the deprecated ones.
    """
    goal = MetricGoal.model_validate(
        {"id": goal_id, "label": label, "checkpoints": checkpoints, **extras}
    )
    wire = goal_to_wire(goal)
    assert isinstance(wire["id"], str) and wire["id"]
    if goal_id is not None:
        assert wire["id"] == goal_id
    assert "unit" not in wire
    assert "direction" not in wire
    assert all(
        isinstance(t, str) and isinstance(v, float) for t, v in wire["checkpoints"]
    )
    assert len(wire["checkpoints"]) == len(checkpoints)


@st.composite
def null_attribution_operands(draw: st.DrawFn) -> dict[str, Any]:
    """Generate a formula operand whose segment method and attribution are unset.

    Args:
        draw: Hypothesis draw function.

    Returns:
        An operand dict with an optional id, measurement, and overrides; any
        ``segmentMethod`` or ``multiAttribution`` key it has is ``None``.
    """
    operand: dict[str, Any] = {}
    if draw(st.booleans()):
        operand["id"] = draw(st.integers(min_value=1))
        operand["type"] = "metric"
    if draw(st.booleans()):
        measurement: dict[str, Any] = {
            "math": draw(st.sampled_from(["total", "unique"]))
        }
        for key in ("segmentMethod", "multiAttribution"):
            if draw(st.booleans()):
                measurement[key] = None
        operand["measurement"] = measurement
    if draw(st.booleans()):
        inner: dict[str, Any] = {}
        if draw(st.booleans()):
            inner["segmentMethod"] = None
        operand["overrides"] = {"measurement": inner}
    return operand


@given(operands=st.lists(null_attribution_operands(), max_size=6))
def test_operands_without_attribution_pass(operands: list[dict[str, Any]]) -> None:
    """Operands with absent or null segment method and attribution always pass.

    Args:
        operands: Generated formula operands.
    """
    check_formula_operands(
        {"formula": {"definition": "A", "referencedMetrics": operands}}
    )
