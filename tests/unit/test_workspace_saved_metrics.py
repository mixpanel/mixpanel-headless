# ruff: noqa: ARG001, ARG005
"""Unit tests for the Workspace saved metric and saved behavior methods.

Tests for:
- ``list_metrics`` with its filters (kind, verified, name, viewable)
- ``get_metric``, ``delete_metric`` (pre-read, then the bulk route),
  ``delete_metrics``
- ``list_behaviors`` with its filters, ``get_behavior``, ``delete_behavior``
  (pre-read, then the bulk route), ``delete_behaviors``

Verifies:
- Correct return types
- Local filters over the one list response
- The requests each delete method sends, in order
- The ``SM5_NOT_FOUND_FOR_DELETE`` refusal when the pre-read finds no metric
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless.exceptions import (
    CODED_GUARD_REGISTRY,
    ParamValidationError,
    QueryError,
    ResponseValidationError,
    ServerError,
)
from mixpanel_headless.types import SavedBehavior, SavedMetric
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session
from tests.unit._saved_metric_fixtures import (
    behavior_metric_json,
    envelope,
    formula_metric_json,
    saved_behavior_json,
    warehouse_metric_json,
)

# ---- canonical fake Session for Workspace(session=…) ----
_TEST_SESSION = Session(
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
# Helpers
# =============================================================================


def _make_workspace(temp_dir: Path, handler: Any) -> Workspace:
    """Create a Workspace with a mock HTTP transport.

    Args:
        temp_dir: Temporary directory for config and storage.
        handler: Handler function for httpx.MockTransport.

    Returns:
        A Workspace instance wired to the mock transport.
    """
    creds = make_session(project_id="12345", region="us", oauth_token="test-token")
    transport = httpx.MockTransport(handler)
    client = MixpanelAPIClient(session=creds, _transport=transport)
    return Workspace(session=_TEST_SESSION, _api_client=client)


def _metric_list_handler(captured: list[httpx.Request]) -> Any:
    """Build a handler that answers every request with four saved metrics.

    The rows: an unverified behavior metric, a verified behavior metric, a
    formula, and a warehouse metric the caller cannot view.

    Args:
        captured: List the handler appends each request to.

    Returns:
        A MockTransport handler.
    """
    body = envelope(
        behavior_metric_json(1, "Weekly signups"),
        behavior_metric_json(2, "Verified revenue", verified=True),
        formula_metric_json(3, "Signup conversion"),
        warehouse_metric_json(4, "Warehouse revenue"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request and return the metric list."""
        captured.append(request)
        return httpx.Response(200, json=body)

    return handler


# =============================================================================
# Saved metrics — list
# =============================================================================


class TestListMetrics:
    """Tests for Workspace.list_metrics()."""

    def test_returns_every_kind_by_default(self, temp_dir: Path) -> None:
        """With no filters the full server list comes back, all kinds, in order."""
        captured: list[httpx.Request] = []
        ws = _make_workspace(temp_dir, _metric_list_handler(captured))
        metrics = ws.list_metrics()
        assert all(isinstance(m, SavedMetric) for m in metrics)
        assert [m.id for m in metrics] == [1, 2, 3, 4]
        assert [m.type for m in metrics] == ["metric", "metric", "formula", "warehouse"]
        assert len(captured) == 1
        assert captured[0].url.path == "/api/app/projects/12345/metrics"

    def test_includes_rows_the_caller_cannot_view(self, temp_dir: Path) -> None:
        """The default keeps rows with can_view false."""
        ws = _make_workspace(temp_dir, _metric_list_handler([]))
        metrics = ws.list_metrics()
        assert [m.can_view for m in metrics] == [True, True, True, False]

    def test_viewable_only(self, temp_dir: Path) -> None:
        """viewable_only=True drops the rows the server marks can_view false."""
        ws = _make_workspace(temp_dir, _metric_list_handler([]))
        assert [m.id for m in ws.list_metrics(viewable_only=True)] == [1, 2, 3]

    def test_viewable_only_keeps_rows_without_the_flag(self, temp_dir: Path) -> None:
        """A row with no can_view key is not dropped by viewable_only."""
        row = behavior_metric_json(9)
        del row["can_view"]

        def handler(request: httpx.Request) -> httpx.Response:
            """Return one row without a can_view key."""
            return httpx.Response(200, json=envelope(row))

        ws = _make_workspace(temp_dir, handler)
        assert [m.id for m in ws.list_metrics(viewable_only=True)] == [9]

    @pytest.mark.parametrize(
        ("metric_type", "expected"),
        [("metric", [1, 2]), ("formula", [3]), ("warehouse", [4]), ("behavior", [])],
    )
    def test_metric_type(
        self, temp_dir: Path, metric_type: str, expected: list[int]
    ) -> None:
        """metric_type keeps the rows of one kind.

        Args:
            temp_dir: Temporary directory fixture.
            metric_type: The kind to keep.
            expected: The ids that remain.
        """
        ws = _make_workspace(temp_dir, _metric_list_handler([]))
        assert [m.id for m in ws.list_metrics(metric_type=metric_type)] == expected

    def test_verified_true_and_false(self, temp_dir: Path) -> None:
        """verified=True keeps verified rows; verified=False keeps the others."""
        ws = _make_workspace(temp_dir, _metric_list_handler([]))
        assert [m.id for m in ws.list_metrics(verified=True)] == [2]
        assert [m.id for m in ws.list_metrics(verified=False)] == [1, 3, 4]

    def test_name_contains_is_case_insensitive(self, temp_dir: Path) -> None:
        """name_contains matches a substring of the name, ignoring case."""
        ws = _make_workspace(temp_dir, _metric_list_handler([]))
        assert [m.id for m in ws.list_metrics(name_contains="REVENUE")] == [2, 4]
        assert [m.id for m in ws.list_metrics(name_contains="signup")] == [1, 3]

    def test_filters_combine(self, temp_dir: Path) -> None:
        """All filters apply together over the one list response."""
        captured: list[httpx.Request] = []
        ws = _make_workspace(temp_dir, _metric_list_handler(captured))
        metrics = ws.list_metrics(
            metric_type="metric", verified=True, name_contains="rev", viewable_only=True
        )
        assert [m.id for m in metrics] == [2]
        assert len(captured) == 1
        assert captured[0].url.params == httpx.QueryParams()

    def test_malformed_row_raises_response_validation_error(
        self, temp_dir: Path
    ) -> None:
        """A row without a required key raises ResponseValidationError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a row with no name."""
            return httpx.Response(
                200,
                json={"results": {"1": {"id": 1, "type": "metric", "definition": {}}}},
            )

        ws = _make_workspace(temp_dir, handler)
        with pytest.raises(ResponseValidationError):
            ws.list_metrics()


# =============================================================================
# Saved metrics — get and delete
# =============================================================================


class TestGetMetric:
    """Tests for Workspace.get_metric()."""

    def test_returns_saved_metric(self, temp_dir: Path) -> None:
        """get_metric() returns a typed SavedMetric with working accessors."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return one formula row."""
            return httpx.Response(200, json=envelope(formula_metric_json()))

        ws = _make_workspace(temp_dir, handler)
        metric = ws.get_metric(118228)
        assert isinstance(metric, SavedMetric)
        assert metric.formula_expression == "A / B * 100"
        assert metric.referenced_metric_ids == [104700, 104701]

    def test_404_raises_query_error(self, temp_dir: Path) -> None:
        """An absent metric raises QueryError with status 404."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return the server's not-found body."""
            return httpx.Response(404, json={"error": "Metric not found for id 5"})

        ws = _make_workspace(temp_dir, handler)
        with pytest.raises(QueryError) as exc_info:
            ws.get_metric(5)
        assert exc_info.value.status_code == 404


class TestDeleteMetric:
    """Tests for Workspace.delete_metric()."""

    def test_pre_read_then_bulk_delete(self, temp_dir: Path) -> None:
        """delete_metric() GETs the metric, then sends the bulk DELETE with one id."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer the pre-read with the row and the DELETE with an empty map."""
            captured.append(request)
            if request.method == "GET":
                return httpx.Response(200, json=envelope(behavior_metric_json()))
            return httpx.Response(200, json={"status": "ok", "results": {}})

        ws = _make_workspace(temp_dir, handler)
        ws.delete_metric(104700)
        assert [(r.method, r.url.path) for r in captured] == [
            ("GET", "/api/app/projects/12345/metrics/104700"),
            ("DELETE", "/api/app/projects/12345/metrics"),
        ]
        assert json.loads(captured[1].content) == {"metrics": [{"id": 104700}]}

    def test_not_found_refusal_sends_no_delete(self, temp_dir: Path) -> None:
        """A 404 on the pre-read raises SM5_NOT_FOUND_FOR_DELETE and deletes nothing."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer every request with a 404."""
            captured.append(request)
            return httpx.Response(404, json={"error": "Metric not found for id 5"})

        ws = _make_workspace(temp_dir, handler)
        with pytest.raises(ParamValidationError) as exc_info:
            ws.delete_metric(5)
        exc = exc_info.value
        assert exc.code == "SM5_NOT_FOUND_FOR_DELETE"
        assert exc.code in CODED_GUARD_REGISTRY
        assert exc.details == {
            "metric_id": 5,
            "project_id": "12345",
            "status_code": 404,
        }
        assert "5" in str(exc)
        assert isinstance(exc.__cause__, QueryError)
        assert [r.method for r in captured] == ["GET"]

    def test_other_pre_read_errors_propagate(self, temp_dir: Path) -> None:
        """A 403 on the pre-read propagates as QueryError and deletes nothing."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer every request with a 403."""
            captured.append(request)
            return httpx.Response(403, json={"error": "Forbidden"})

        ws = _make_workspace(temp_dir, handler)
        with pytest.raises(QueryError) as exc_info:
            ws.delete_metric(5)
        assert exc_info.value.status_code == 403
        assert [r.method for r in captured] == ["GET"]

    def test_delete_permission_error_propagates(self, temp_dir: Path) -> None:
        """A 403 on the bulk DELETE propagates as QueryError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer the pre-read with the row and the DELETE with a 403."""
            if request.method == "GET":
                return httpx.Response(200, json=envelope(behavior_metric_json()))
            return httpx.Response(403, json={"error": ""})

        ws = _make_workspace(temp_dir, handler)
        with pytest.raises(QueryError) as exc_info:
            ws.delete_metric(104700)
        assert exc_info.value.status_code == 403


class TestDeleteMetrics:
    """Tests for Workspace.delete_metrics()."""

    def test_one_bulk_delete(self, temp_dir: Path) -> None:
        """delete_metrics() sends one DELETE with every id and no pre-read."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the request and return an empty map."""
            captured.append(request)
            return httpx.Response(200, json={"status": "ok", "results": {}})

        ws = _make_workspace(temp_dir, handler)
        ws.delete_metrics((1, 2, 3))
        assert [r.method for r in captured] == ["DELETE"]
        assert json.loads(captured[0].content) == {
            "metrics": [{"id": 1}, {"id": 2}, {"id": 3}]
        }

    def test_empty_sequence_sends_nothing(self, temp_dir: Path) -> None:
        """An empty id sequence sends no request."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the request."""
            captured.append(request)
            return httpx.Response(200, json={})

        ws = _make_workspace(temp_dir, handler)
        ws.delete_metrics([])
        assert captured == []


# =============================================================================
# Saved behaviors
# =============================================================================


def _behavior_list_handler() -> Any:
    """Build a handler that answers every request with three saved behaviors.

    Returns:
        A MockTransport handler.
    """
    body = envelope(
        saved_behavior_json(1, "Checkout", behavior_type="funnel"),
        saved_behavior_json(2, "Any purchase", behavior_type="simple"),
        saved_behavior_json(3, "Checkout return", behavior_type="retention"),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the behavior list."""
        return httpx.Response(200, json=body)

    return handler


class TestListBehaviors:
    """Tests for Workspace.list_behaviors()."""

    def test_returns_all_by_default(self, temp_dir: Path) -> None:
        """With no filters every behavior comes back, typed, in order."""
        ws = _make_workspace(temp_dir, _behavior_list_handler())
        behaviors = ws.list_behaviors()
        assert all(isinstance(b, SavedBehavior) for b in behaviors)
        assert [b.id for b in behaviors] == [1, 2, 3]

    def test_behavior_type(self, temp_dir: Path) -> None:
        """behavior_type keeps the rows of one type."""
        ws = _make_workspace(temp_dir, _behavior_list_handler())
        assert [b.id for b in ws.list_behaviors(behavior_type="funnel")] == [1]
        assert [b.id for b in ws.list_behaviors(behavior_type="retention")] == [3]

    def test_name_contains(self, temp_dir: Path) -> None:
        """name_contains matches a substring of the name, ignoring case."""
        ws = _make_workspace(temp_dir, _behavior_list_handler())
        assert [b.id for b in ws.list_behaviors(name_contains="CHECKOUT")] == [1, 3]
        assert [
            b.id
            for b in ws.list_behaviors(behavior_type="simple", name_contains="checkout")
        ] == []


class TestGetBehavior:
    """Tests for Workspace.get_behavior()."""

    def test_returns_saved_behavior(self, temp_dir: Path) -> None:
        """get_behavior() returns a typed SavedBehavior."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return one behavior row."""
            return httpx.Response(200, json=envelope(saved_behavior_json(3001)))

        ws = _make_workspace(temp_dir, handler)
        behavior = ws.get_behavior(3001)
        assert isinstance(behavior, SavedBehavior)
        assert behavior.behavior_type == "funnel"


class TestDeleteBehavior:
    """Tests for Workspace.delete_behavior()."""

    def test_pre_read_then_bulk_delete(self, temp_dir: Path) -> None:
        """delete_behavior() GETs the behavior, then sends the bulk DELETE."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer the pre-read with the row and the DELETE with an empty map."""
            captured.append(request)
            if request.method == "GET":
                return httpx.Response(200, json=envelope(saved_behavior_json(3001)))
            return httpx.Response(200, json={"status": "ok", "results": {}})

        ws = _make_workspace(temp_dir, handler)
        ws.delete_behavior(3001)
        assert [(r.method, r.url.path) for r in captured] == [
            ("GET", "/api/app/projects/12345/behaviors/3001"),
            ("DELETE", "/api/app/projects/12345/behaviors"),
        ]
        assert json.loads(captured[1].content) == {"behaviors": [{"id": 3001}]}

    def test_unknown_id_fails_on_pre_read(self, temp_dir: Path) -> None:
        """The server's 500 for an unknown id stops the delete before the DELETE."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer every request with a 500."""
            captured.append(request)
            return httpx.Response(500, text="Internal Server Error")

        ws = _make_workspace(temp_dir, handler)
        with pytest.raises(ServerError):
            ws.delete_behavior(999)
        assert [r.method for r in captured] == ["GET"]


class TestDeleteBehaviors:
    """Tests for Workspace.delete_behaviors()."""

    def test_one_bulk_delete(self, temp_dir: Path) -> None:
        """delete_behaviors() sends one DELETE with every id and no pre-read."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the request and return an empty map."""
            captured.append(request)
            return httpx.Response(200, json={"status": "ok", "results": {}})

        ws = _make_workspace(temp_dir, handler)
        ws.delete_behaviors([7, 8])
        assert [r.method for r in captured] == ["DELETE"]
        assert json.loads(captured[0].content) == {"behaviors": [{"id": 7}, {"id": 8}]}

    def test_empty_sequence_sends_nothing(self, temp_dir: Path) -> None:
        """An empty id sequence sends no request."""
        captured: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the request."""
            captured.append(request)
            return httpx.Response(200, json={})

        ws = _make_workspace(temp_dir, handler)
        ws.delete_behaviors(())
        assert captured == []
