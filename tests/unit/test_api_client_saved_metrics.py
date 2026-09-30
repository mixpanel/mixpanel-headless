# ruff: noqa: ARG001, ARG005
"""Unit tests for the saved metric and saved behavior API client methods.

Tests for:
- ``list_metrics`` / ``get_metric`` / ``delete_metrics``
- ``list_behaviors`` / ``get_behavior`` / ``delete_behaviors``
- The per-call ``timeout`` of ``app_request`` and the long read timeout of
  the two unpaginated list calls

Verifies paths (project-scoped even with a pinned workspace), verbs, bulk
DELETE bodies, the unwrap of the id-keyed ``results`` map, and error mapping.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from mixpanel_headless._internal.api_client import (
    DEFAULT_APP_TIMEOUT_S,
    MixpanelAPIClient,
)
from mixpanel_headless._internal.auth.session import Session
from mixpanel_headless.exceptions import (
    MixpanelHeadlessError,
    QueryError,
    ServerError,
)
from tests.conftest import make_session
from tests.unit._saved_metric_fixtures import (
    behavior_metric_json,
    envelope,
    formula_metric_json,
    saved_behavior_json,
)

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def oauth_credentials() -> Session:
    """Create OAuth credentials for App API testing."""
    return make_session(project_id="12345", region="us", oauth_token="test-oauth-token")


def create_mock_client(
    credentials: Session,
    handler: Callable[[httpx.Request], httpx.Response],
    **kwargs: Any,
) -> MixpanelAPIClient:
    """Create a client with a mock transport (no workspace ID set).

    Args:
        credentials: Authentication credentials.
        handler: Mock HTTP handler function.
        **kwargs: Extra MixpanelAPIClient constructor arguments.

    Returns:
        MixpanelAPIClient configured with the mock transport.
    """
    transport = httpx.MockTransport(handler)
    return MixpanelAPIClient(session=credentials, _transport=transport, **kwargs)


def _capture(
    captured: list[httpx.Request], body: dict[str, Any]
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a handler that records each request and answers with ``body``.

    Args:
        captured: List the handler appends each request to.
        body: JSON body of every response.

    Returns:
        A MockTransport handler.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request and return the canned body."""
        captured.append(request)
        return httpx.Response(200, json=body)

    return handler


# =============================================================================
# app_request per-call timeout
# =============================================================================


class TestAppRequestTimeout:
    """``app_request(timeout=...)`` replaces the route-aware default."""

    def test_per_call_timeout_wins(self, oauth_credentials: Session) -> None:
        """A per-call timeout overrides the constructor timeout."""
        captured: list[httpx.Request] = []
        client = create_mock_client(
            oauth_credentials, _capture(captured, {"results": []}), timeout=42.0
        )
        with client:
            client.app_request("GET", "/projects/12345/dashboards", timeout=7.0)
        assert captured[0].extensions["timeout"]["read"] == 7.0

    def test_default_when_absent(self, oauth_credentials: Session) -> None:
        """Without a per-call timeout the app-route default applies."""
        captured: list[httpx.Request] = []
        client = create_mock_client(oauth_credentials, _capture(captured, {}))
        with client:
            client.app_request("GET", "/projects/12345/dashboards")
        assert captured[0].extensions["timeout"]["read"] == DEFAULT_APP_TIMEOUT_S

    def test_per_call_timeout_on_form_body(self, oauth_credentials: Session) -> None:
        """The per-call timeout also applies to form-encoded requests."""
        captured: list[httpx.Request] = []
        client = create_mock_client(oauth_credentials, _capture(captured, {}))
        with client:
            client.app_request(
                "POST",
                "/projects/12345/custom_events/",
                form_body={"a": "b"},
                timeout=9.0,
            )
        assert captured[0].extensions["timeout"]["read"] == 9.0


# =============================================================================
# Saved metrics
# =============================================================================


class TestListMetrics:
    """Tests for list_metrics() API client method."""

    def test_unwraps_id_map_in_server_order(self, oauth_credentials: Session) -> None:
        """list_metrics() turns the id-keyed results map into a list of rows."""
        captured: list[httpx.Request] = []
        body = envelope(formula_metric_json(), behavior_metric_json())
        client = create_mock_client(oauth_credentials, _capture(captured, body))
        with client:
            rows = client.list_metrics()
        assert [r["id"] for r in rows] == [118228, 104700]
        assert rows[1]["name"] == "Weekly signups"

    def test_get_on_project_path(self, oauth_credentials: Session) -> None:
        """list_metrics() sends GET to the project-scoped metrics path."""
        captured: list[httpx.Request] = []
        client = create_mock_client(oauth_credentials, _capture(captured, envelope()))
        with client:
            client.list_metrics()
        assert captured[0].method == "GET"
        assert captured[0].url.path == "/api/app/projects/12345/metrics"

    def test_project_scoped_with_workspace_pinned(
        self, oauth_credentials: Session
    ) -> None:
        """A pinned workspace does not move the call under /workspaces/."""
        captured: list[httpx.Request] = []
        client = create_mock_client(oauth_credentials, _capture(captured, envelope()))
        client.set_workspace_id(77)
        with client:
            client.list_metrics()
        assert captured[0].url.path == "/api/app/projects/12345/metrics"

    def test_empty_map(self, oauth_credentials: Session) -> None:
        """An empty results map gives an empty list."""
        client = create_mock_client(
            oauth_credentials, _capture([], {"status": "ok", "results": {}})
        )
        with client:
            assert client.list_metrics() == []

    def test_long_timeout_by_default(self, oauth_credentials: Session) -> None:
        """The list uses a read timeout of at least 120 seconds."""
        captured: list[httpx.Request] = []
        client = create_mock_client(oauth_credentials, _capture(captured, envelope()))
        with client:
            client.list_metrics()
        assert captured[0].extensions["timeout"]["read"] == DEFAULT_APP_TIMEOUT_S
        assert DEFAULT_APP_TIMEOUT_S >= 120.0

    def test_short_constructor_timeout_is_raised(
        self, oauth_credentials: Session
    ) -> None:
        """A constructor timeout below the floor does not cut the list short."""
        captured: list[httpx.Request] = []
        client = create_mock_client(
            oauth_credentials, _capture(captured, envelope()), timeout=10.0
        )
        with client:
            client.list_metrics()
        assert captured[0].extensions["timeout"]["read"] == DEFAULT_APP_TIMEOUT_S

    def test_longer_constructor_timeout_is_kept(
        self, oauth_credentials: Session
    ) -> None:
        """A constructor timeout above the floor applies unchanged."""
        captured: list[httpx.Request] = []
        client = create_mock_client(
            oauth_credentials, _capture(captured, envelope()), timeout=600.0
        )
        with client:
            client.list_metrics()
        assert captured[0].extensions["timeout"]["read"] == 600.0

    def test_list_shaped_results_rejected(self, oauth_credentials: Session) -> None:
        """A results value that is not an id-keyed map raises."""
        client = create_mock_client(
            oauth_credentials, _capture([], {"status": "ok", "results": [1, 2]})
        )
        with client, pytest.raises(MixpanelHeadlessError, match="list_metrics"):
            client.list_metrics()

    def test_non_dict_row_rejected(self, oauth_credentials: Session) -> None:
        """A map value that is not an entity dict raises."""
        client = create_mock_client(
            oauth_credentials, _capture([], {"status": "ok", "results": {"1": "x"}})
        )
        with client, pytest.raises(MixpanelHeadlessError, match="list_metrics"):
            client.list_metrics()

    def test_403_raises_query_error(self, oauth_credentials: Session) -> None:
        """A 403 (missing permission or plan gate) raises QueryError with the status."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 403 in the bare error shape."""
            return httpx.Response(403, json={"error": ""})

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(QueryError) as exc_info:
            client.list_metrics()
        assert exc_info.value.status_code == 403

    def test_500_raises_server_error_without_retry(
        self, oauth_credentials: Session
    ) -> None:
        """A 5xx raises ServerError after one attempt."""
        attempts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Count attempts and return a 500."""
            attempts.append(1)
            return httpx.Response(500, json={"error": "boom"})

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(ServerError):
            client.list_metrics()
        assert len(attempts) == 1

    def test_retries_on_429(self, oauth_credentials: Session) -> None:
        """list_metrics() retries a 429, then returns the rows."""
        attempts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Return 429 once, then the list."""
            attempts.append(1)
            if len(attempts) == 1:
                return httpx.Response(429, headers={"Retry-After": "0"}, json={})
            return httpx.Response(200, json=envelope(behavior_metric_json()))

        client = create_mock_client(oauth_credentials, handler)
        with client:
            rows = client.list_metrics()
        assert len(attempts) == 2
        assert rows[0]["id"] == 104700


class TestGetMetric:
    """Tests for get_metric() API client method."""

    def test_unwraps_one_entry_map(self, oauth_credentials: Session) -> None:
        """get_metric() returns the single row of the id-keyed map."""
        captured: list[httpx.Request] = []
        client = create_mock_client(
            oauth_credentials, _capture(captured, envelope(behavior_metric_json()))
        )
        with client:
            row = client.get_metric(104700)
        assert row["id"] == 104700
        assert captured[0].method == "GET"
        assert captured[0].url.path == "/api/app/projects/12345/metrics/104700"

    def test_project_scoped_with_workspace_pinned(
        self, oauth_credentials: Session
    ) -> None:
        """A pinned workspace does not move the call under /workspaces/."""
        captured: list[httpx.Request] = []
        client = create_mock_client(
            oauth_credentials, _capture(captured, envelope(behavior_metric_json()))
        )
        client.set_workspace_id(77)
        with client:
            client.get_metric(104700)
        assert captured[0].url.path == "/api/app/projects/12345/metrics/104700"

    def test_404_raises_query_error(self, oauth_credentials: Session) -> None:
        """An absent or inactive metric raises QueryError with status 404."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return the server's not-found body."""
            return httpx.Response(
                404, json={"status": "error", "error": "Metric not found for id 9"}
            )

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(QueryError) as exc_info:
            client.get_metric(9)
        assert exc_info.value.status_code == 404

    @pytest.mark.parametrize(
        "results",
        [{}, envelope(behavior_metric_json(1), behavior_metric_json(2))["results"]],
    )
    def test_not_exactly_one_row_raises(
        self, oauth_credentials: Session, results: dict[str, Any]
    ) -> None:
        """A map with zero or two rows is an unexpected response.

        Args:
            oauth_credentials: Session fixture.
            results: The results map to return.
        """
        client = create_mock_client(
            oauth_credentials, _capture([], {"status": "ok", "results": results})
        )
        with client, pytest.raises(MixpanelHeadlessError, match="get_metric"):
            client.get_metric(1)


class TestDeleteMetrics:
    """Tests for delete_metrics() API client method."""

    def test_bulk_delete_body(self, oauth_credentials: Session) -> None:
        """delete_metrics() sends one DELETE with the id objects in the body."""
        captured: list[httpx.Request] = []
        client = create_mock_client(
            oauth_credentials, _capture(captured, {"status": "ok", "results": {}})
        )
        with client:
            client.delete_metrics([104700, 118228])
        assert len(captured) == 1
        assert captured[0].method == "DELETE"
        assert captured[0].url.path == "/api/app/projects/12345/metrics"
        assert json.loads(captured[0].content) == {
            "metrics": [{"id": 104700}, {"id": 118228}]
        }

    def test_project_scoped_with_workspace_pinned(
        self, oauth_credentials: Session
    ) -> None:
        """A pinned workspace does not move the call under /workspaces/."""
        captured: list[httpx.Request] = []
        client = create_mock_client(oauth_credentials, _capture(captured, {}))
        client.set_workspace_id(77)
        with client:
            client.delete_metrics([1])
        assert captured[0].url.path == "/api/app/projects/12345/metrics"

    def test_403_raises_query_error(self, oauth_credentials: Session) -> None:
        """A 403 raises QueryError with the status."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 403."""
            return httpx.Response(403, json={"status": "error", "error": "Forbidden"})

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(QueryError) as exc_info:
            client.delete_metrics([1])
        assert exc_info.value.status_code == 403


# =============================================================================
# Saved behaviors
# =============================================================================


class TestListBehaviors:
    """Tests for list_behaviors() API client method."""

    def test_unwraps_id_map(self, oauth_credentials: Session) -> None:
        """list_behaviors() GETs the project path and unwraps the id map."""
        captured: list[httpx.Request] = []
        body = envelope(saved_behavior_json(1), saved_behavior_json(2, "Other"))
        client = create_mock_client(oauth_credentials, _capture(captured, body))
        client.set_workspace_id(77)
        with client:
            rows = client.list_behaviors()
        assert [r["id"] for r in rows] == [1, 2]
        assert captured[0].method == "GET"
        assert captured[0].url.path == "/api/app/projects/12345/behaviors"

    def test_short_constructor_timeout_is_raised(
        self, oauth_credentials: Session
    ) -> None:
        """The behavior list also gets the long read timeout."""
        captured: list[httpx.Request] = []
        client = create_mock_client(
            oauth_credentials, _capture(captured, envelope()), timeout=5.0
        )
        with client:
            client.list_behaviors()
        assert captured[0].extensions["timeout"]["read"] == DEFAULT_APP_TIMEOUT_S

    def test_non_map_rejected(self, oauth_credentials: Session) -> None:
        """A results value that is not a map raises."""
        client = create_mock_client(
            oauth_credentials, _capture([], {"status": "ok", "results": "nope"})
        )
        with client, pytest.raises(MixpanelHeadlessError, match="list_behaviors"):
            client.list_behaviors()


class TestGetBehavior:
    """Tests for get_behavior() API client method."""

    def test_unwraps_one_entry_map(self, oauth_credentials: Session) -> None:
        """get_behavior() GETs the project path and returns the single row."""
        captured: list[httpx.Request] = []
        client = create_mock_client(
            oauth_credentials, _capture(captured, envelope(saved_behavior_json(3001)))
        )
        client.set_workspace_id(77)
        with client:
            row = client.get_behavior(3001)
        assert row["id"] == 3001
        assert captured[0].method == "GET"
        assert captured[0].url.path == "/api/app/projects/12345/behaviors/3001"

    def test_500_raises_server_error(self, oauth_credentials: Session) -> None:
        """The server's failure on an unknown behavior id surfaces as ServerError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 500."""
            return httpx.Response(500, text="Internal Server Error")

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(ServerError):
            client.get_behavior(999)

    def test_not_exactly_one_row_raises(self, oauth_credentials: Session) -> None:
        """An empty map is an unexpected response."""
        client = create_mock_client(
            oauth_credentials, _capture([], {"status": "ok", "results": {}})
        )
        with client, pytest.raises(MixpanelHeadlessError, match="get_behavior"):
            client.get_behavior(1)


class TestDeleteBehaviors:
    """Tests for delete_behaviors() API client method."""

    def test_bulk_delete_body(self, oauth_credentials: Session) -> None:
        """delete_behaviors() sends one DELETE with the id objects in the body."""
        captured: list[httpx.Request] = []
        client = create_mock_client(
            oauth_credentials, _capture(captured, {"status": "ok", "results": {}})
        )
        client.set_workspace_id(77)
        with client:
            client.delete_behaviors([3001, 3002])
        assert captured[0].method == "DELETE"
        assert captured[0].url.path == "/api/app/projects/12345/behaviors"
        assert json.loads(captured[0].content) == {
            "behaviors": [{"id": 3001}, {"id": 3002}]
        }

    def test_403_raises_query_error(self, oauth_credentials: Session) -> None:
        """A 403 raises QueryError with the status."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 403."""
            return httpx.Response(403, json={"error": "Forbidden"})

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(QueryError) as exc_info:
            client.delete_behaviors([1])
        assert exc_info.value.status_code == 403
