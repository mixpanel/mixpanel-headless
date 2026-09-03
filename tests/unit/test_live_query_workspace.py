"""``LiveQueryService`` inline query methods pass ``workspace_id`` to the client.

045-report-links (PR #223 review): ``query_report_link`` runs a resolved
report under the workspace the report records, so the four inline query
methods forward an optional ``workspace_id`` to ``insights_query`` /
``arb_funnels_query``. Fixtures copy ``tests/unit/test_live_query_flow.py``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.services.live_query import LiveQueryService

_INSIGHTS_RAW: dict[str, Any] = {
    "computed_at": "2025-01-15T10:00:00",
    "date_range": {"from_date": "2025-01-01", "to_date": "2025-01-07"},
    "headers": ["$event"],
    "series": {"Login": {"2025-01-01": 1}},
}
_FLOW_RAW: dict[str, Any] = {"computed_at": "2025-01-15T10:00:00", "steps": []}


@pytest.fixture
def mock_api_client() -> MagicMock:
    """Create a spec'd mock API client."""
    client = MagicMock(spec=MixpanelAPIClient)
    client.insights_query.return_value = _INSIGHTS_RAW
    client.arb_funnels_query.return_value = _FLOW_RAW
    return client


@pytest.fixture
def service(mock_api_client: MagicMock) -> LiveQueryService:
    """Create a LiveQueryService with the mocked client."""
    return LiveQueryService(mock_api_client)


class TestWorkspacePassthrough:
    """Each inline method forwards ``workspace_id`` as a keyword."""

    @pytest.mark.parametrize("method", ["query", "query_funnel", "query_retention"])
    def test_insights_methods_forward_workspace(
        self, service: LiveQueryService, mock_api_client: MagicMock, method: str
    ) -> None:
        """``query`` / ``query_funnel`` / ``query_retention`` pass it through."""
        getattr(service, method)({"sections": {}}, 12345, workspace_id=75)

        assert mock_api_client.insights_query.call_args.kwargs["workspace_id"] == 75

    @pytest.mark.parametrize("method", ["query", "query_funnel", "query_retention"])
    def test_insights_methods_default_to_none(
        self, service: LiveQueryService, mock_api_client: MagicMock, method: str
    ) -> None:
        """Without the argument the client receives ``workspace_id=None``."""
        getattr(service, method)({"sections": {}}, 12345)

        assert mock_api_client.insights_query.call_args.kwargs["workspace_id"] is None

    def test_query_flow_forwards_workspace(
        self, service: LiveQueryService, mock_api_client: MagicMock
    ) -> None:
        """``query_flow`` passes it through to ``arb_funnels_query``."""
        service.query_flow({"steps": []}, 12345, mode="sankey", workspace_id=75)

        assert mock_api_client.arb_funnels_query.call_args.kwargs["workspace_id"] == 75

    @pytest.mark.parametrize("method", ["query", "query_funnel", "query_retention"])
    def test_insights_methods_forward_pin_opt_out(
        self, service: LiveQueryService, mock_api_client: MagicMock, method: str
    ) -> None:
        """``inject_workspace_id=False`` reaches ``insights_query``."""
        getattr(service, method)({"sections": {}}, 12345, inject_workspace_id=False)

        kwargs = mock_api_client.insights_query.call_args.kwargs
        assert kwargs["inject_workspace_id"] is False
        assert kwargs["workspace_id"] is None

    @pytest.mark.parametrize("method", ["query", "query_funnel", "query_retention"])
    def test_insights_methods_default_to_pin_injection(
        self, service: LiveQueryService, mock_api_client: MagicMock, method: str
    ) -> None:
        """Without the argument the pin still applies (``True``)."""
        getattr(service, method)({"sections": {}}, 12345)

        assert mock_api_client.insights_query.call_args.kwargs["inject_workspace_id"]

    def test_query_flow_forwards_pin_opt_out(
        self, service: LiveQueryService, mock_api_client: MagicMock
    ) -> None:
        """``query_flow`` forwards the opt-out to ``arb_funnels_query``."""
        service.query_flow({"steps": []}, 12345, inject_workspace_id=False)

        kwargs = mock_api_client.arb_funnels_query.call_args.kwargs
        assert kwargs["inject_workspace_id"] is False

    def test_query_flow_defaults_to_none(
        self, service: LiveQueryService, mock_api_client: MagicMock
    ) -> None:
        """Without the argument ``arb_funnels_query`` receives ``None``."""
        service.query_flow({"steps": []}, 12345)

        assert (
            mock_api_client.arb_funnels_query.call_args.kwargs["workspace_id"] is None
        )
