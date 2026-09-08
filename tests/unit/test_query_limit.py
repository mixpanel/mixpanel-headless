"""Unit tests for the ``limit`` query parameter and the ``run_*_params`` methods.

Covers three areas:

- ``_query_limits``: the shared validator behind every ``queryLimits.limit``.
- ``limit=`` passthrough on the insights, funnel, and retention query paths,
  at both the service layer and the ``Workspace`` layer.
- ``Workspace.run_params`` / ``run_funnel_params`` / ``run_retention_params``:
  executing params that ``build_*_params`` produced.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from mixpanel_headless import Workspace
from mixpanel_headless._internal.services.live_query import (
    DEFAULT_SEGMENTATION_LIMIT,
    MAX_SEGMENTATION_LIMIT,
    LiveQueryService,
    _query_limits,
)
from mixpanel_headless.types import FunnelQueryResult, QueryResult, RetentionQueryResult
from tests.conftest import make_session

if TYPE_CHECKING:
    from collections.abc import Callable


# =============================================================================
# Fixtures and mock responses
# =============================================================================


@pytest.fixture
def mock_api_client() -> MagicMock:
    """Create a mock API client whose ``insights_query`` is recordable.

    Returns:
        A MagicMock specced against MixpanelAPIClient.
    """
    from mixpanel_headless._internal.api_client import MixpanelAPIClient

    client = MagicMock(spec=MixpanelAPIClient)
    client.close = MagicMock()
    return client


@pytest.fixture
def workspace_factory(mock_api_client: MagicMock) -> Callable[..., Workspace]:
    """Factory for Workspace instances backed by the mock API client.

    Args:
        mock_api_client: The recordable API client.

    Returns:
        A callable that builds a Workspace, accepting constructor overrides.
    """

    def factory(**kwargs: Any) -> Workspace:
        """Build a Workspace with mocked dependencies.

        Args:
            **kwargs: Overrides for the default constructor arguments.

        Returns:
            A Workspace wired to the mock API client.
        """
        defaults: dict[str, Any] = {
            "session": make_session(),
            "_api_client": mock_api_client,
        }
        defaults.update(kwargs)
        return Workspace(**defaults)

    return factory


MOCK_INSIGHTS_RESPONSE: dict[str, Any] = {
    "computed_at": "2025-01-15T12:00:00",
    "date_range": {"from_date": "2025-01-01", "to_date": "2025-01-31"},
    "headers": ["$event"],
    "series": {"A. Login": {"2025-01-01": 10}},
    "meta": {"sampling_factor": 1.0},
}
"""Canonical mock response for an insights query."""


MOCK_FUNNEL_RESPONSE: dict[str, Any] = {
    "computed_at": "2025-01-15T12:00:00",
    "date_range": {"from_date": "2025-01-01", "to_date": "2025-01-31"},
    "headers": ["$funnel"],
    "series": {
        "steps": [
            {
                "event": "Signup",
                "count": 1000,
                "step_conv_ratio": 1.0,
                "overall_conv_ratio": 1.0,
                "avg_time": 0.0,
                "avg_time_from_start": 0.0,
            },
            {
                "event": "Purchase",
                "count": 120,
                "step_conv_ratio": 0.12,
                "overall_conv_ratio": 0.12,
                "avg_time": 86400.0,
                "avg_time_from_start": 86400.0,
            },
        ]
    },
    "meta": {"sampling_factor": 1.0},
}
"""Canonical mock response for a two-step funnel query."""


MOCK_RETENTION_RESPONSE: dict[str, Any] = {
    "computed_at": "2025-01-15T12:00:00",
    "date_range": {"from_date": "2025-01-01", "to_date": "2025-01-31"},
    "headers": ["$retention"],
    "series": {"2025-01-01": {"counts": [100, 40], "first": 100}},
    "meta": {"sampling_factor": 1.0},
}
"""Canonical mock response for a retention query."""


def sent_limit(mock_api_client: MagicMock) -> int:
    """Read the ``queryLimits.limit`` from the last recorded request body.

    Args:
        mock_api_client: The mock whose ``insights_query`` was called.

    Returns:
        The limit integer sent to the API.
    """
    body = mock_api_client.insights_query.call_args[0][0]
    limit: int = body["queryLimits"]["limit"]
    return limit


# =============================================================================
# _query_limits
# =============================================================================


class TestQueryLimitsValidator:
    """Tests for the shared ``_query_limits`` validator."""

    def test_none_yields_the_default(self) -> None:
        """Passing None keeps today's 3000 default."""
        assert _query_limits(None) == {"limit": DEFAULT_SEGMENTATION_LIMIT}

    @pytest.mark.parametrize("limit", [1, 3000, 49_999, MAX_SEGMENTATION_LIMIT])
    def test_accepts_values_in_range(self, limit: int) -> None:
        """Any value from 1 to the server maximum passes through unchanged.

        Args:
            limit: A limit inside the accepted range.
        """
        assert _query_limits(limit) == {"limit": limit}

    @pytest.mark.parametrize("limit", [0, -1, MAX_SEGMENTATION_LIMIT + 1, 500_000])
    def test_rejects_values_out_of_range(self, limit: int) -> None:
        """Values outside 1..50000 raise ValueError before any HTTP call.

        Args:
            limit: A limit outside the accepted range.
        """
        with pytest.raises(ValueError, match="limit must be between 1 and 50000"):
            _query_limits(limit)

    def test_default_and_maximum_constants(self) -> None:
        """The exported constants match the documented server behavior."""
        assert DEFAULT_SEGMENTATION_LIMIT == 3000
        assert MAX_SEGMENTATION_LIMIT == 50_000


# =============================================================================
# LiveQueryService passthrough
# =============================================================================


class TestServiceLimitPassthrough:
    """Tests that each service query method forwards ``limit`` to the body."""

    @pytest.fixture
    def service(self, mock_api_client: MagicMock) -> LiveQueryService:
        """Build a LiveQueryService over the mock API client.

        Args:
            mock_api_client: The recordable API client.

        Returns:
            A LiveQueryService instance.
        """
        return LiveQueryService(mock_api_client)

    def test_query_defaults_to_3000(
        self, service: LiveQueryService, mock_api_client: MagicMock
    ) -> None:
        """Omitting ``limit`` on an insights query keeps the 3000 default.

        Args:
            service: The service under test.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_INSIGHTS_RESPONSE
        service.query({"sections": {}}, 12345)
        assert sent_limit(mock_api_client) == 3000

    def test_query_forwards_limit(
        self, service: LiveQueryService, mock_api_client: MagicMock
    ) -> None:
        """An explicit ``limit`` reaches ``queryLimits`` on an insights query.

        Args:
            service: The service under test.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_INSIGHTS_RESPONSE
        service.query({"sections": {}}, 12345, limit=50_000)
        assert sent_limit(mock_api_client) == 50_000

    def test_query_funnel_defaults_to_3000(
        self, service: LiveQueryService, mock_api_client: MagicMock
    ) -> None:
        """Omitting ``limit`` on a funnel query keeps the 3000 default.

        Args:
            service: The service under test.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_FUNNEL_RESPONSE
        service.query_funnel({"sections": {}}, 12345)
        assert sent_limit(mock_api_client) == 3000

    def test_query_funnel_forwards_limit(
        self, service: LiveQueryService, mock_api_client: MagicMock
    ) -> None:
        """An explicit ``limit`` reaches ``queryLimits`` on a funnel query.

        Args:
            service: The service under test.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_FUNNEL_RESPONSE
        service.query_funnel({"sections": {}}, 12345, limit=25_000)
        assert sent_limit(mock_api_client) == 25_000

    def test_query_retention_defaults_to_3000(
        self, service: LiveQueryService, mock_api_client: MagicMock
    ) -> None:
        """Omitting ``limit`` on a retention query keeps the 3000 default.

        Args:
            service: The service under test.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_RETENTION_RESPONSE
        service.query_retention({"sections": {}}, 12345)
        assert sent_limit(mock_api_client) == 3000

    def test_query_retention_forwards_limit(
        self, service: LiveQueryService, mock_api_client: MagicMock
    ) -> None:
        """An explicit ``limit`` reaches ``queryLimits`` on a retention query.

        Args:
            service: The service under test.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_RETENTION_RESPONSE
        service.query_retention({"sections": {}}, 12345, limit=10)
        assert sent_limit(mock_api_client) == 10

    @pytest.mark.parametrize("method", ["query", "query_funnel", "query_retention"])
    def test_out_of_range_limit_never_reaches_the_api(
        self, service: LiveQueryService, mock_api_client: MagicMock, method: str
    ) -> None:
        """A rejected limit raises before any HTTP call is made.

        Args:
            service: The service under test.
            mock_api_client: The recordable API client.
            method: Name of the service method under test.
        """
        with pytest.raises(ValueError, match="limit must be between 1 and 50000"):
            getattr(service, method)({"sections": {}}, 12345, limit=50_001)
        mock_api_client.insights_query.assert_not_called()


# =============================================================================
# Workspace passthrough
# =============================================================================


class TestWorkspaceLimitPassthrough:
    """Tests that the Workspace query methods forward ``limit``."""

    def test_query_forwards_limit(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``Workspace.query(limit=...)`` reaches the request body.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_INSIGHTS_RESPONSE
        ws = workspace_factory()
        try:
            ws.query("Login", limit=50_000)
            assert sent_limit(mock_api_client) == 50_000
        finally:
            ws.close()

    def test_query_default_is_unchanged(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``Workspace.query`` without ``limit`` still sends 3000.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_INSIGHTS_RESPONSE
        ws = workspace_factory()
        try:
            ws.query("Login")
            assert sent_limit(mock_api_client) == 3000
        finally:
            ws.close()

    def test_query_funnel_forwards_limit(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``Workspace.query_funnel(limit=...)`` reaches the request body.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_FUNNEL_RESPONSE
        ws = workspace_factory()
        try:
            ws.query_funnel(["Signup", "Purchase"], limit=12_345)
            assert sent_limit(mock_api_client) == 12_345
        finally:
            ws.close()

    def test_query_retention_forwards_limit(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``Workspace.query_retention(limit=...)`` reaches the request body.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_RETENTION_RESPONSE
        ws = workspace_factory()
        try:
            ws.query_retention("Signup", "Login", limit=42)
            assert sent_limit(mock_api_client) == 42
        finally:
            ws.close()

    def test_out_of_range_limit_raises(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """A rejected limit raises before any HTTP call is made.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        ws = workspace_factory()
        try:
            with pytest.raises(ValueError, match="limit must be between 1 and 50000"):
                ws.query("Login", limit=0)
            mock_api_client.insights_query.assert_not_called()
        finally:
            ws.close()


# =============================================================================
# run_params / run_funnel_params / run_retention_params
# =============================================================================


class TestRunParams:
    """Tests for executing params that ``build_*_params`` produced."""

    def test_run_params_returns_a_query_result(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``run_params`` posts the params and transforms the response.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_INSIGHTS_RESPONSE
        ws = workspace_factory()
        try:
            params = ws.build_params("Login")
            result = ws.run_params(params)

            assert isinstance(result, QueryResult)
            body = mock_api_client.insights_query.call_args[0][0]
            assert body["bookmark"] == params
            assert body["project_id"] == 12345
            assert body["queryLimits"] == {"limit": 3000}
        finally:
            ws.close()

    def test_run_params_matches_query(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``build_params`` then ``run_params`` sends what ``query`` sends.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_INSIGHTS_RESPONSE
        ws = workspace_factory()
        try:
            ws.query("Login", last=7)
            direct = mock_api_client.insights_query.call_args[0][0]

            ws.run_params(ws.build_params("Login", last=7))
            round_trip = mock_api_client.insights_query.call_args[0][0]

            assert round_trip == direct
        finally:
            ws.close()

    def test_run_params_forwards_limit(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``run_params(limit=...)`` reaches the request body.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_INSIGHTS_RESPONSE
        ws = workspace_factory()
        try:
            ws.run_params({"sections": {}}, limit=50_000)
            assert sent_limit(mock_api_client) == 50_000
        finally:
            ws.close()

    def test_run_params_forwards_workspace_id(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``run_params(workspace_id=...)`` reaches the API client.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_INSIGHTS_RESPONSE
        ws = workspace_factory()
        try:
            ws.run_params({"sections": {}}, workspace_id=99)
            assert mock_api_client.insights_query.call_args.kwargs["workspace_id"] == 99
        finally:
            ws.close()

    def test_run_funnel_params_returns_a_funnel_result(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``run_funnel_params`` transforms the response into a funnel result.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_FUNNEL_RESPONSE
        ws = workspace_factory()
        try:
            params = ws.build_funnel_params(["Signup", "Purchase"])
            result = ws.run_funnel_params(params, limit=7000)

            assert isinstance(result, FunnelQueryResult)
            assert sent_limit(mock_api_client) == 7000
            assert mock_api_client.insights_query.call_args[0][0]["bookmark"] == params
        finally:
            ws.close()

    def test_run_retention_params_returns_a_retention_result(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``run_retention_params`` transforms the response into a retention result.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.insights_query.return_value = MOCK_RETENTION_RESPONSE
        ws = workspace_factory()
        try:
            params = ws.build_retention_params("Signup", "Login")
            result = ws.run_retention_params(params, limit=7000)

            assert isinstance(result, RetentionQueryResult)
            assert sent_limit(mock_api_client) == 7000
            assert mock_api_client.insights_query.call_args[0][0]["bookmark"] == params
        finally:
            ws.close()

    @pytest.mark.parametrize(
        "method", ["run_params", "run_funnel_params", "run_retention_params"]
    )
    def test_out_of_range_limit_raises(
        self,
        workspace_factory: Callable[..., Workspace],
        mock_api_client: MagicMock,
        method: str,
    ) -> None:
        """A rejected limit raises before any HTTP call is made.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
            method: Name of the Workspace method under test.
        """
        ws = workspace_factory()
        try:
            with pytest.raises(ValueError, match="limit must be between 1 and 50000"):
                getattr(ws, method)({"sections": {}}, limit=50_001)
            mock_api_client.insights_query.assert_not_called()
        finally:
            ws.close()
