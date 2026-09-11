"""Unit tests for ``Workspace.run_flow_params`` and ``Workspace.run_user_params``.

These two methods are the execution half of ``build_flow_params`` and
``build_user_params``. They complete the ``run_*_params`` family started by
``run_params`` / ``run_funnel_params`` / ``run_retention_params``.

Covers:

- ``run_flow_params``: posts the params as the request ``bookmark``, derives
  the flows ``query_type`` from ``params["flows_merge_type"]`` (falling back
  to ``chartType``), accepts an explicit ``mode=`` override, forwards
  ``workspace_id``, and
  sends the same body as ``query_flow`` for the same arguments.
- ``run_user_params``: routes to the Engage ``stats`` endpoint when the
  params carry an aggregate ``action``, otherwise to profile export; forwards
  ``limit`` and honours ``parallel`` / ``workers``; sends the same request as
  ``query_user`` for the same arguments.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from unittest.mock import MagicMock

import pytest

from mixpanel_headless import Workspace
from mixpanel_headless.types import (
    FlowQueryResult,
    ProfilePageResult,
    UserQueryResult,
)
from tests.conftest import make_session

if TYPE_CHECKING:
    from collections.abc import Callable


# =============================================================================
# Fixtures and mock responses
# =============================================================================


@pytest.fixture
def mock_api_client() -> MagicMock:
    """Create a mock API client with recordable flow and engage endpoints.

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


MOCK_SANKEY_RESPONSE: dict[str, Any] = {
    "computed_at": "2025-01-15T10:00:00",
    "steps": [
        {"event": "Login", "count": 100},
        {"event": "Purchase", "count": 30},
    ],
    "breakdowns": [],
    "overallConversionRate": 0.3,
    "metadata": {"sampling_factor": 1.0},
}
"""Canonical mock response for a sankey flow query."""


MOCK_TOP_PATHS_RESPONSE: dict[str, Any] = {
    "computed_at": "2025-01-15T10:00:00",
    "flows": [{"path": ["Login", "Purchase"], "count": 30}],
    "steps": [],
    "breakdowns": [],
    "overallConversionRate": 0.5,
    "metadata": {},
}
"""Canonical mock response for a top-paths flow query."""


MOCK_TREE_RESPONSE: dict[str, Any] = {
    "computed_at": "2025-01-15T10:00:00",
    "trees": [],
    "metadata": {},
}
"""Minimal mock response for a tree flow query."""


MOCK_STATS_RESPONSE: dict[str, Any] = {
    "results": 42,
    "status": "ok",
    "computed_at": "2025-01-15T10:00:00",
}
"""Canonical mock response for an Engage ``stats`` count."""


def _page(profiles: list[dict[str, Any]]) -> ProfilePageResult:
    """Build a single-page profile export result.

    Args:
        profiles: Raw profile dicts to return on page zero.

    Returns:
        A ProfilePageResult with no further pages.
    """
    return ProfilePageResult(
        profiles=profiles,
        page=0,
        total=len(profiles),
        page_size=1000,
        session_id="sess",
        has_more=False,
    )


RAW_PROFILES: list[dict[str, Any]] = [
    {"$distinct_id": f"user_{i:03d}", "$properties": {"$last_seen": "2025-01-15"}}
    for i in range(3)
]
"""Three raw Engage profiles."""


def flow_body(mock_api_client: MagicMock) -> dict[str, Any]:
    """Read the last body posted to the flows endpoint.

    Args:
        mock_api_client: The mock whose ``arb_funnels_query`` was called.

    Returns:
        The request body dict.
    """
    body: dict[str, Any] = mock_api_client.arb_funnels_query.call_args[0][0]
    return body


# =============================================================================
# run_flow_params
# =============================================================================


class TestRunFlowParams:
    """Tests for executing params that ``build_flow_params`` produced."""

    def test_returns_a_flow_result_and_posts_params_as_bookmark(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``run_flow_params`` posts the params and transforms the response.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.arb_funnels_query.return_value = MOCK_SANKEY_RESPONSE
        ws = workspace_factory()
        try:
            params = ws.build_flow_params("Login")
            result = ws.run_flow_params(params)

            assert isinstance(result, FlowQueryResult)
            body = flow_body(mock_api_client)
            assert body["bookmark"] == params
            assert body["project_id"] == 12345
            assert body["query_type"] == "flows_sankey"
        finally:
            ws.close()

    def test_matches_query_flow(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``build_flow_params`` then ``run_flow_params`` sends what ``query_flow`` sends.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.arb_funnels_query.return_value = MOCK_SANKEY_RESPONSE
        ws = workspace_factory()
        try:
            ws.query_flow("Login", forward=2, last=7)
            direct = flow_body(mock_api_client)

            ws.run_flow_params(ws.build_flow_params("Login", forward=2, last=7))
            round_trip = flow_body(mock_api_client)

            assert round_trip == direct
        finally:
            ws.close()

    def test_derives_paths_mode_from_chart_type(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """Params built with ``mode="paths"`` run as a top-paths query.

        The builder stores ``chartType: "top-paths"``; the runner must read it
        back so the caller does not repeat the mode.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.arb_funnels_query.return_value = MOCK_TOP_PATHS_RESPONSE
        ws = workspace_factory()
        try:
            params = ws.build_flow_params("Login", mode="paths")
            assert params["chartType"] == "top-paths"

            result = ws.run_flow_params(params)

            assert flow_body(mock_api_client)["query_type"] == "flows_top_paths"
            assert result.mode == "paths"
        finally:
            ws.close()

    def test_derives_tree_mode_from_flows_merge_type(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """Params built with ``mode="tree"`` run as a tree query without help.

        The builder writes ``chartType: "sankey"`` for tree mode and records
        the real mode in ``flows_merge_type: "tree"``. The runner must read
        the merge type, or tree params would silently run as sankey.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.arb_funnels_query.return_value = MOCK_TREE_RESPONSE
        ws = workspace_factory()
        try:
            params = ws.build_flow_params("Login", mode="tree")
            assert params["chartType"] == "sankey"
            assert params["flows_merge_type"] == "tree"

            result = ws.run_flow_params(params)

            assert flow_body(mock_api_client)["query_type"] == "flows"
            assert result.mode == "tree"
        finally:
            ws.close()

    @pytest.mark.parametrize("built_mode", ["sankey", "paths", "tree"])
    def test_every_built_mode_round_trips(
        self,
        workspace_factory: Callable[..., Workspace],
        mock_api_client: MagicMock,
        built_mode: str,
    ) -> None:
        """``run_flow_params`` sends the same body as ``query_flow`` for each mode.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
            built_mode: The flow mode passed to the builder.
        """
        mock_api_client.arb_funnels_query.return_value = {
            **MOCK_SANKEY_RESPONSE,
            "trees": [],
            "flows": [],
        }
        ws = workspace_factory()
        try:
            ws.query_flow("Login", mode=built_mode)  # type: ignore[arg-type]
            direct = flow_body(mock_api_client)

            ws.run_flow_params(ws.build_flow_params("Login", mode=built_mode))  # type: ignore[arg-type]
            round_trip = flow_body(mock_api_client)

            assert round_trip == direct
        finally:
            ws.close()

    def test_explicit_mode_overrides_params(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``mode=`` wins over whatever the params record.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.arb_funnels_query.return_value = MOCK_TOP_PATHS_RESPONSE
        ws = workspace_factory()
        try:
            params = ws.build_flow_params("Login", mode="tree")

            result = ws.run_flow_params(params, mode="paths")

            assert flow_body(mock_api_client)["query_type"] == "flows_top_paths"
            assert result.mode == "paths"
        finally:
            ws.close()

    @pytest.mark.parametrize(
        ("params", "expected"),
        [
            ({"steps": []}, "flows_sankey"),
            ({"steps": [], "chartType": "sankey"}, "flows_sankey"),
            ({"steps": [], "chartType": "top-paths"}, "flows_top_paths"),
            ({"steps": [], "chartType": "paths"}, "flows_top_paths"),
            ({"steps": [], "chartType": "tree"}, "flows"),
            ({"steps": [], "chartType": "something-else"}, "flows_sankey"),
            ({"steps": [], "flows_merge_type": "tree"}, "flows"),
            ({"steps": [], "flows_merge_type": "list"}, "flows_top_paths"),
            ({"steps": [], "flows_merge_type": "graph"}, "flows_sankey"),
            (
                {"steps": [], "chartType": "sankey", "flows_merge_type": "tree"},
                "flows",
            ),
            (
                {"steps": [], "chartType": "top-paths", "flows_merge_type": "list"},
                "flows_top_paths",
            ),
            ({"steps": [], "flows_merge_type": "unknown"}, "flows_sankey"),
        ],
    )
    def test_chart_type_to_query_type(
        self,
        workspace_factory: Callable[..., Workspace],
        mock_api_client: MagicMock,
        params: dict[str, Any],
        expected: str,
    ) -> None:
        """Hand-written params map to the right ``query_type``.

        ``flows_merge_type`` is authoritative when present. ``chartType``
        is the fallback. Missing or unknown values fall back to sankey.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
            params: Hand-written flow params.
            expected: The ``query_type`` the request body must carry.
        """
        mock_api_client.arb_funnels_query.return_value = {
            **MOCK_SANKEY_RESPONSE,
            "trees": [],
            "flows": [],
        }
        ws = workspace_factory()
        try:
            ws.run_flow_params(params)
            assert flow_body(mock_api_client)["query_type"] == expected
        finally:
            ws.close()

    def test_forwards_workspace_id(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``run_flow_params(workspace_id=...)`` reaches the API client.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.arb_funnels_query.return_value = MOCK_SANKEY_RESPONSE
        ws = workspace_factory()
        try:
            ws.run_flow_params({"steps": []}, workspace_id=99)
            kwargs = mock_api_client.arb_funnels_query.call_args.kwargs
            assert kwargs["workspace_id"] == 99
        finally:
            ws.close()


# =============================================================================
# run_user_params
# =============================================================================


class TestRunUserParams:
    """Tests for executing params that ``build_user_params`` produced."""

    def test_aggregate_params_route_to_engage_stats(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """Params that carry an ``action`` run as an aggregate query.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.engage_stats.return_value = MOCK_STATS_RESPONSE
        ws = workspace_factory()
        try:
            params = ws.build_user_params(mode="aggregate")
            assert "action" in params

            result = ws.run_user_params(params)

            assert isinstance(result, UserQueryResult)
            assert result.mode == "aggregate"
            assert result.total == 42
            assert result.params == params
            mock_api_client.engage_stats.assert_called_once()
            mock_api_client.export_profiles_page.assert_not_called()
        finally:
            ws.close()

    def test_aggregate_matches_query_user(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``build_user_params`` then ``run_user_params`` calls stats like ``query_user``.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.engage_stats.return_value = MOCK_STATS_RESPONSE
        ws = workspace_factory()
        try:
            ws.query_user(mode="aggregate", aggregate="count")
            direct = mock_api_client.engage_stats.call_args

            ws.run_user_params(
                ws.build_user_params(mode="aggregate", aggregate="count")
            )
            round_trip = mock_api_client.engage_stats.call_args

            assert round_trip == direct
        finally:
            ws.close()

    def test_profile_params_route_to_export(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """Params without an ``action`` run as a profiles query.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.export_profiles_page.return_value = _page(RAW_PROFILES)
        ws = workspace_factory()
        try:
            params = ws.build_user_params(mode="profiles")
            assert "action" not in params

            result = ws.run_user_params(params)

            assert result.mode == "profiles"
            assert len(result.profiles) == 1
            assert result.params == params
            mock_api_client.engage_stats.assert_not_called()
        finally:
            ws.close()

    def test_profile_limit_is_forwarded(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``limit`` reaches the export call and caps the profiles returned.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.export_profiles_page.return_value = _page(RAW_PROFILES)
        ws = workspace_factory()
        try:
            result = ws.run_user_params({}, limit=2)

            assert len(result.profiles) == 2
            kwargs = mock_api_client.export_profiles_page.call_args.kwargs
            assert kwargs["limit"] == 2
        finally:
            ws.close()

    def test_profiles_match_query_user(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``build_user_params`` then ``run_user_params`` exports like ``query_user``.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.export_profiles_page.return_value = _page(RAW_PROFILES)
        ws = workspace_factory()
        try:
            ws.query_user(mode="profiles", properties=["$email"], limit=2)
            direct = mock_api_client.export_profiles_page.call_args

            ws.run_user_params(
                ws.build_user_params(mode="profiles", properties=["$email"]),
                limit=2,
            )
            round_trip = mock_api_client.export_profiles_page.call_args

            assert round_trip == direct
        finally:
            ws.close()

    def test_parallel_path_is_used_when_requested(
        self, workspace_factory: Callable[..., Workspace], mock_api_client: MagicMock
    ) -> None:
        """``parallel=True`` with ``limit != 1`` takes the parallel fetch path.

        Args:
            workspace_factory: Factory for a mocked Workspace.
            mock_api_client: The recordable API client.
        """
        mock_api_client.export_profiles_page.return_value = _page(RAW_PROFILES)
        ws = workspace_factory()
        try:
            with_parallel = MagicMock(wraps=ws._execute_user_query_parallel)
            ws._execute_user_query_parallel = with_parallel  # type: ignore[method-assign]

            result = ws.run_user_params({}, limit=3, parallel=True, workers=2)

            with_parallel.assert_called_once()
            assert with_parallel.call_args.args[1:] == (3, 2)
            assert len(result.profiles) == 3
        finally:
            ws.close()
