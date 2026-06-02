"""Unit tests for LiveQueryService.

Tests use httpx.MockTransport for deterministic HTTP mocking.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

import httpx
import pytest

from mixpanel_headless._internal.services.live_query import LiveQueryService
from mixpanel_headless.exceptions import AuthenticationError, QueryError

if TYPE_CHECKING:
    from mixpanel_headless._internal.api_client import MixpanelAPIClient


@pytest.fixture
def live_query_factory(
    request: pytest.FixtureRequest,
    mock_client_factory: Callable[
        [Callable[[httpx.Request], httpx.Response]], MixpanelAPIClient
    ],
) -> Callable[[Callable[[httpx.Request], httpx.Response]], LiveQueryService]:
    """Factory for creating LiveQueryService with mock API client.

    Usage:
        def test_something(live_query_factory):
            def handler(request):
                return httpx.Response(200, json={"data": {...}})

            live_query = live_query_factory(handler)
            result = live_query.segmentation(...)
    """
    clients: list[MixpanelAPIClient] = []

    def factory(
        handler: Callable[[httpx.Request], httpx.Response],
    ) -> LiveQueryService:
        client = mock_client_factory(handler)
        # Enter context to ensure client is initialized
        client.__enter__()
        clients.append(client)
        return LiveQueryService(client)

    def cleanup() -> None:
        for client in clients:
            client.__exit__(None, None, None)

    request.addfinalizer(cleanup)
    return factory


class TestLiveQueryService:
    """Tests for LiveQueryService initialization."""

    def test_init_with_api_client(
        self,
        mock_client_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], MixpanelAPIClient
        ],
        success_handler: Callable[[httpx.Request], httpx.Response],
    ) -> None:
        """LiveQueryService should accept an API client."""
        client = mock_client_factory(success_handler)
        live_query = LiveQueryService(client)
        assert live_query._api_client is client


# =============================================================================
# User Story 1: Segmentation Tests
# =============================================================================


class TestSegmentation:
    """Tests for LiveQueryService.segmentation()."""

    def test_segmentation_basic_query(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """segmentation() should return SegmentationResult with correct data."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01", "2024-01-02", "2024-01-03"],
                        "values": {
                            "Sign Up": {
                                "2024-01-01": 147,
                                "2024-01-02": 146,
                                "2024-01-03": 776,
                            }
                        },
                    },
                    "legend_size": 1,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.segmentation(
            event="Sign Up",
            from_date="2024-01-01",
            to_date="2024-01-03",
        )

        assert result.event == "Sign Up"
        assert result.from_date == "2024-01-01"
        assert result.to_date == "2024-01-03"
        assert result.unit == "day"
        assert result.segment_property is None
        assert result.series == {
            "Sign Up": {
                "2024-01-01": 147,
                "2024-01-02": 146,
                "2024-01-03": 776,
            }
        }

    def test_segmentation_with_property_segmentation(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """segmentation() with on parameter should return segmented data."""

        def handler(request: httpx.Request) -> httpx.Response:
            # Verify on parameter is passed
            assert "on=" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01", "2024-01-02"],
                        "values": {
                            "US": {"2024-01-01": 100, "2024-01-02": 120},
                            "CA": {"2024-01-01": 50, "2024-01-02": 60},
                        },
                    },
                    "legend_size": 2,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.segmentation(
            event="Sign Up",
            from_date="2024-01-01",
            to_date="2024-01-02",
            on='properties["country"]',
        )

        assert result.segment_property == 'properties["country"]'
        assert "US" in result.series
        assert "CA" in result.series
        assert result.series["US"]["2024-01-01"] == 100

    def test_segmentation_with_where_filter(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """segmentation() with where parameter should pass filter to API."""

        def handler(request: httpx.Request) -> httpx.Response:
            # Verify where parameter is passed
            assert "where=" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01"],
                        "values": {"Sign Up": {"2024-01-01": 50}},
                    },
                    "legend_size": 1,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.segmentation(
            event="Sign Up",
            from_date="2024-01-01",
            to_date="2024-01-01",
            where='properties["platform"] == "mobile"',
        )

        assert result.total == 50

    def test_segmentation_calculates_total(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """segmentation() should calculate total from all values."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01", "2024-01-02"],
                        "values": {
                            "US": {"2024-01-01": 100, "2024-01-02": 200},
                            "CA": {"2024-01-01": 50, "2024-01-02": 150},
                        },
                    },
                    "legend_size": 2,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.segmentation(
            event="Sign Up",
            from_date="2024-01-01",
            to_date="2024-01-02",
            on='properties["country"]',
        )

        # Total should be 100 + 200 + 50 + 150 = 500
        assert result.total == 500

    def test_segmentation_empty_result(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """segmentation() should handle empty results."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": [],
                        "values": {},
                    },
                    "legend_size": 0,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.segmentation(
            event="Sign Up",
            from_date="2024-01-01",
            to_date="2024-01-01",
        )

        assert result.total == 0
        assert result.series == {}

    def test_segmentation_propagates_auth_error(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """segmentation() should propagate AuthenticationError from API."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "Invalid credentials"})

        live_query = live_query_factory(handler)

        with pytest.raises(AuthenticationError):
            live_query.segmentation(
                event="Sign Up",
                from_date="2024-01-01",
                to_date="2024-01-01",
            )


# =============================================================================
# User Story 2: Funnel Tests
# =============================================================================


class TestFunnel:
    """Tests for LiveQueryService.funnel()."""

    def test_funnel_basic_query(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """funnel() should return FunnelResult with correct step data."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "meta": {"dates": ["2024-01-01"]},
                    "data": {
                        "2024-01-01": {
                            "steps": [
                                {
                                    "count": 1000,
                                    "step_conv_ratio": 1.0,
                                    "overall_conv_ratio": 1.0,
                                    "event": "App Open",
                                    "goal": "App Open",
                                },
                                {
                                    "count": 600,
                                    "step_conv_ratio": 0.6,
                                    "overall_conv_ratio": 0.6,
                                    "event": "Sign Up",
                                    "goal": "Sign Up",
                                },
                                {
                                    "count": 300,
                                    "step_conv_ratio": 0.5,
                                    "overall_conv_ratio": 0.3,
                                    "event": "Purchase",
                                    "goal": "Purchase",
                                },
                            ],
                            "analysis": {
                                "completion": 300,
                                "starting_amount": 1000,
                                "steps": 3,
                                "worst": 1,
                            },
                        }
                    },
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.funnel(
            funnel_id=12345,
            from_date="2024-01-01",
            to_date="2024-01-01",
        )

        assert result.funnel_id == 12345
        assert result.from_date == "2024-01-01"
        assert result.to_date == "2024-01-01"
        assert len(result.steps) == 3
        assert result.steps[0].event == "App Open"
        assert result.steps[0].count == 1000
        assert result.steps[1].event == "Sign Up"
        assert result.steps[1].count == 600
        assert result.steps[2].event == "Purchase"
        assert result.steps[2].count == 300

    def test_funnel_aggregates_across_dates(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """funnel() should aggregate counts across multiple dates."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "meta": {"dates": ["2024-01-01", "2024-01-02"]},
                    "data": {
                        "2024-01-01": {
                            "steps": [
                                {"count": 500, "event": "App Open"},
                                {"count": 300, "event": "Sign Up"},
                            ],
                            "analysis": {},
                        },
                        "2024-01-02": {
                            "steps": [
                                {"count": 500, "event": "App Open"},
                                {"count": 300, "event": "Sign Up"},
                            ],
                            "analysis": {},
                        },
                    },
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.funnel(
            funnel_id=12345,
            from_date="2024-01-01",
            to_date="2024-01-02",
        )

        # Should be aggregated: 500 + 500 = 1000, 300 + 300 = 600
        assert result.steps[0].count == 1000
        assert result.steps[1].count == 600

    def test_funnel_calculates_conversion_rates(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """funnel() should calculate step conversion rates from aggregated counts."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "meta": {"dates": ["2024-01-01"]},
                    "data": {
                        "2024-01-01": {
                            "steps": [
                                {"count": 1000, "event": "Step 1"},
                                {"count": 500, "event": "Step 2"},
                                {"count": 250, "event": "Step 3"},
                            ],
                            "analysis": {},
                        }
                    },
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.funnel(
            funnel_id=12345,
            from_date="2024-01-01",
            to_date="2024-01-01",
        )

        # Step 1 is always 1.0 (100% of itself)
        assert result.steps[0].conversion_rate == 1.0
        # Step 2 is 500/1000 = 0.5
        assert result.steps[1].conversion_rate == 0.5
        # Step 3 is 250/500 = 0.5
        assert result.steps[2].conversion_rate == 0.5

    def test_funnel_overall_conversion_rate(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """funnel() should calculate overall conversion rate."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "meta": {"dates": ["2024-01-01"]},
                    "data": {
                        "2024-01-01": {
                            "steps": [
                                {"count": 1000, "event": "Step 1"},
                                {"count": 250, "event": "Step 2"},
                            ],
                            "analysis": {},
                        }
                    },
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.funnel(
            funnel_id=12345,
            from_date="2024-01-01",
            to_date="2024-01-01",
        )

        # Overall conversion: 250/1000 = 0.25
        assert result.conversion_rate == 0.25

    def test_funnel_empty_result(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """funnel() should handle empty results."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "meta": {"dates": []},
                    "data": {},
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.funnel(
            funnel_id=12345,
            from_date="2024-01-01",
            to_date="2024-01-01",
        )

        assert result.steps == []
        assert result.conversion_rate == 0.0

    def test_funnel_propagates_query_error(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """funnel() should propagate QueryError for invalid funnel ID."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "Invalid funnel ID"})

        live_query = live_query_factory(handler)

        with pytest.raises(QueryError):
            live_query.funnel(
                funnel_id=99999,
                from_date="2024-01-01",
                to_date="2024-01-01",
            )


# =============================================================================
# Funnel Helper Tests
# =============================================================================


class TestExtractStepsFromDateData:
    """Tests for _extract_steps_from_date_data helper function.

    This function handles both regular and segmented funnel response formats.
    """

    def test_non_segmented_format_returns_steps(self) -> None:
        """Non-segmented format with 'steps' key returns step list."""
        from mixpanel_headless._internal.services.live_query import (
            _extract_steps_from_date_data,
        )

        date_data = {
            "steps": [
                {"count": 100, "step_label": "Step 1"},
                {"count": 80, "step_label": "Step 2"},
            ]
        }
        result = _extract_steps_from_date_data(date_data)
        assert result == [
            {"count": 100, "step_label": "Step 1"},
            {"count": 80, "step_label": "Step 2"},
        ]

    def test_segmented_format_returns_overall(self) -> None:
        """Segmented format with '$overall' key returns aggregate data."""
        from mixpanel_headless._internal.services.live_query import (
            _extract_steps_from_date_data,
        )

        date_data = {
            "$overall": [
                {"count": 200, "step_label": "Step 1"},
                {"count": 150, "step_label": "Step 2"},
            ],
            "Chrome": [
                {"count": 100, "step_label": "Step 1"},
                {"count": 70, "step_label": "Step 2"},
            ],
            "Firefox": [
                {"count": 100, "step_label": "Step 1"},
                {"count": 80, "step_label": "Step 2"},
            ],
        }
        result = _extract_steps_from_date_data(date_data)
        # Should return $overall, not individual segments
        assert result == [
            {"count": 200, "step_label": "Step 1"},
            {"count": 150, "step_label": "Step 2"},
        ]

    def test_empty_steps_list_returns_empty(self) -> None:
        """Empty steps list returns empty list."""
        from mixpanel_headless._internal.services.live_query import (
            _extract_steps_from_date_data,
        )

        date_data: dict[str, list[dict[str, str]]] = {"steps": []}
        result = _extract_steps_from_date_data(date_data)
        assert result == []

    def test_empty_overall_returns_empty(self) -> None:
        """Empty $overall list returns empty list."""
        from mixpanel_headless._internal.services.live_query import (
            _extract_steps_from_date_data,
        )

        date_data: dict[str, list[dict[str, str]]] = {"$overall": []}
        result = _extract_steps_from_date_data(date_data)
        assert result == []

    def test_steps_non_list_type_returns_empty(self) -> None:
        """Non-list type for steps returns empty list."""
        from mixpanel_headless._internal.services.live_query import (
            _extract_steps_from_date_data,
        )

        date_data = {"steps": "not a list"}
        result = _extract_steps_from_date_data(date_data)
        assert result == []

    def test_overall_non_list_type_returns_empty(self) -> None:
        """Non-list type for $overall returns empty list."""
        from mixpanel_headless._internal.services.live_query import (
            _extract_steps_from_date_data,
        )

        date_data = {"$overall": {"not": "a list"}}
        result = _extract_steps_from_date_data(date_data)
        assert result == []

    def test_unrecognized_format_returns_empty(self) -> None:
        """Unrecognized format without steps or $overall returns empty list."""
        from mixpanel_headless._internal.services.live_query import (
            _extract_steps_from_date_data,
        )

        date_data = {"some_other_key": [1, 2, 3]}
        result = _extract_steps_from_date_data(date_data)
        assert result == []

    def test_empty_dict_returns_empty(self) -> None:
        """Empty dict returns empty list."""
        from mixpanel_headless._internal.services.live_query import (
            _extract_steps_from_date_data,
        )

        result = _extract_steps_from_date_data({})
        assert result == []

    def test_steps_takes_precedence_over_overall(self) -> None:
        """When both 'steps' and '$overall' exist, 'steps' takes precedence."""
        from mixpanel_headless._internal.services.live_query import (
            _extract_steps_from_date_data,
        )

        date_data = {
            "steps": [{"count": 50, "step_label": "From steps"}],
            "$overall": [{"count": 100, "step_label": "From overall"}],
        }
        result = _extract_steps_from_date_data(date_data)
        # steps key is checked first, so it takes precedence
        assert result == [{"count": 50, "step_label": "From steps"}]


# =============================================================================
# User Story 3: Retention Tests
# =============================================================================


class TestRetention:
    """Tests for LiveQueryService.retention()."""

    def test_retention_basic_query(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """retention() should return RetentionResult with cohort data."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "2024-01-01": {"counts": [9, 7, 6], "first": 10},
                    "2024-01-02": {"counts": [8, 5, 4], "first": 9},
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.retention(
            born_event="Sign Up",
            return_event="Purchase",
            from_date="2024-01-01",
            to_date="2024-01-02",
        )

        assert result.born_event == "Sign Up"
        assert result.return_event == "Purchase"
        assert result.from_date == "2024-01-01"
        assert result.to_date == "2024-01-02"
        assert result.unit == "day"
        assert len(result.cohorts) == 2

    def test_retention_calculates_percentages(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """retention() should calculate retention percentages from counts."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "2024-01-01": {"counts": [100, 50, 25], "first": 100},
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.retention(
            born_event="Sign Up",
            return_event="Purchase",
            from_date="2024-01-01",
            to_date="2024-01-01",
        )

        cohort = result.cohorts[0]
        assert cohort.size == 100
        # retention[0] = 100/100 = 1.0
        assert cohort.retention[0] == 1.0
        # retention[1] = 50/100 = 0.5
        assert cohort.retention[1] == 0.5
        # retention[2] = 25/100 = 0.25
        assert cohort.retention[2] == 0.25

    def test_retention_with_filters(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """retention() should pass filter parameters to API."""

        def handler(request: httpx.Request) -> httpx.Response:
            # Verify filter parameters are passed
            url_str = str(request.url)
            assert "born_where=" in url_str or "where=" in url_str
            return httpx.Response(
                200,
                json={
                    "2024-01-01": {"counts": [50, 25], "first": 50},
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.retention(
            born_event="Sign Up",
            return_event="Purchase",
            from_date="2024-01-01",
            to_date="2024-01-01",
            born_where='properties["platform"] == "mobile"',
        )

        assert len(result.cohorts) == 1

    def test_retention_custom_intervals(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """retention() should pass interval parameters to API."""

        def handler(request: httpx.Request) -> httpx.Response:
            # Verify interval parameters are passed
            # Note: interval is only included when != 1 (Mixpanel API constraint)
            url_str = str(request.url)
            assert "interval=7" in url_str  # Custom interval
            assert "interval_count=" in url_str
            # When interval != 1, unit should NOT be included
            assert "unit=" not in url_str
            return httpx.Response(
                200,
                json={
                    "2024-01-01": {"counts": [100, 80, 60, 40, 20], "first": 100},
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.retention(
            born_event="Sign Up",
            return_event="Any Event",
            from_date="2024-01-01",
            to_date="2024-01-01",
            interval=7,  # 7-day intervals (custom, not default)
            interval_count=5,
        )

        assert len(result.cohorts[0].retention) == 5

    def test_retention_empty_result(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """retention() should handle empty results."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={})

        live_query = live_query_factory(handler)
        result = live_query.retention(
            born_event="Sign Up",
            return_event="Purchase",
            from_date="2024-01-01",
            to_date="2024-01-01",
        )

        assert result.cohorts == []

    def test_retention_sorts_cohorts_by_date(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """retention() should return cohorts sorted by date."""

        def handler(_request: httpx.Request) -> httpx.Response:
            # Return dates in non-sorted order
            return httpx.Response(
                200,
                json={
                    "2024-01-03": {"counts": [30], "first": 30},
                    "2024-01-01": {"counts": [10], "first": 10},
                    "2024-01-02": {"counts": [20], "first": 20},
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.retention(
            born_event="Sign Up",
            return_event="Purchase",
            from_date="2024-01-01",
            to_date="2024-01-03",
        )

        # Should be sorted by date
        assert result.cohorts[0].date == "2024-01-01"
        assert result.cohorts[1].date == "2024-01-02"
        assert result.cohorts[2].date == "2024-01-03"


class TestEventCounts:
    """Tests for LiveQueryService.event_counts()."""

    def test_event_counts_basic_query(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """event_counts() should return EventCountsResult with correct data."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01", "2024-01-02"],
                        "values": {
                            "Sign Up": {"2024-01-01": 100, "2024-01-02": 150},
                            "Purchase": {"2024-01-01": 50, "2024-01-02": 75},
                        },
                    },
                    "legend_size": 2,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.event_counts(
            events=["Sign Up", "Purchase"],
            from_date="2024-01-01",
            to_date="2024-01-02",
        )

        assert result.events == ["Sign Up", "Purchase"]
        assert result.from_date == "2024-01-01"
        assert result.to_date == "2024-01-02"
        assert result.unit == "day"
        assert result.type == "general"
        assert result.series["Sign Up"]["2024-01-01"] == 100
        assert result.series["Purchase"]["2024-01-02"] == 75

    def test_event_counts_with_type_and_unit(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """event_counts() should pass type and unit parameters."""

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            assert "type=unique" in url_str
            assert "unit=week" in url_str
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01"],
                        "values": {"Test": {"2024-01-01": 100}},
                    },
                    "legend_size": 1,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.event_counts(
            events=["Test"],
            from_date="2024-01-01",
            to_date="2024-01-31",
            type="unique",
            unit="week",
        )

        assert result.type == "unique"
        assert result.unit == "week"

    def test_event_counts_df_conversion(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """event_counts() result should have working df property."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01", "2024-01-02"],
                        "values": {
                            "Event A": {"2024-01-01": 100, "2024-01-02": 150},
                            "Event B": {"2024-01-01": 50, "2024-01-02": 75},
                        },
                    },
                    "legend_size": 2,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.event_counts(
            events=["Event A", "Event B"],
            from_date="2024-01-01",
            to_date="2024-01-02",
        )

        df = result.df
        assert "date" in df.columns
        assert "event" in df.columns
        assert "count" in df.columns
        assert len(df) == 4  # 2 events × 2 dates

    def test_event_counts_empty_result(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """event_counts() should handle empty results."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": [],
                        "values": {},
                    },
                    "legend_size": 0,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.event_counts(
            events=[],
            from_date="2024-01-01",
            to_date="2024-01-01",
        )

        assert result.series == {}
        assert len(result.df) == 0

    def test_event_counts_propagates_auth_error(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """event_counts() should propagate AuthenticationError from API."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "Invalid credentials"})

        live_query = live_query_factory(handler)

        with pytest.raises(AuthenticationError):
            live_query.event_counts(
                events=["Test"],
                from_date="2024-01-01",
                to_date="2024-01-01",
            )


# =============================================================================
# User Story 6: Property Counts Tests
# =============================================================================


class TestPropertyCounts:
    """Tests for LiveQueryService.property_counts()."""

    def test_property_counts_basic_query(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """property_counts() should return PropertyCountsResult with correct data."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01", "2024-01-02"],
                        "values": {
                            "US": {"2024-01-01": 100, "2024-01-02": 150},
                            "CA": {"2024-01-01": 50, "2024-01-02": 75},
                        },
                    },
                    "legend_size": 2,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.property_counts(
            event="Purchase",
            property_name="country",
            from_date="2024-01-01",
            to_date="2024-01-02",
        )

        assert result.event == "Purchase"
        assert result.property_name == "country"
        assert result.from_date == "2024-01-01"
        assert result.to_date == "2024-01-02"
        assert result.unit == "day"
        assert result.type == "general"
        assert result.series["US"]["2024-01-01"] == 100
        assert result.series["CA"]["2024-01-02"] == 75

    def test_property_counts_with_type_and_unit(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """property_counts() should pass type and unit parameters."""

        def handler(request: httpx.Request) -> httpx.Response:
            url_str = str(request.url)
            assert "type=unique" in url_str
            assert "unit=month" in url_str
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01"],
                        "values": {"US": {"2024-01-01": 100}},
                    },
                    "legend_size": 1,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.property_counts(
            event="Purchase",
            property_name="country",
            from_date="2024-01-01",
            to_date="2024-01-31",
            type="unique",
            unit="month",
        )

        assert result.type == "unique"
        assert result.unit == "month"

    def test_property_counts_with_values_filter(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """property_counts() should pass values filter to API."""

        def handler(request: httpx.Request) -> httpx.Response:
            # Verify values parameter is JSON-encoded
            assert "values=" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01"],
                        "values": {"US": {"2024-01-01": 100}},
                    },
                    "legend_size": 1,
                },
            )

        live_query = live_query_factory(handler)
        live_query.property_counts(
            event="Purchase",
            property_name="country",
            from_date="2024-01-01",
            to_date="2024-01-01",
            values=["US", "CA"],
        )

    def test_property_counts_with_limit(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """property_counts() should pass limit parameter to API."""

        def handler(request: httpx.Request) -> httpx.Response:
            assert "limit=10" in str(request.url)
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01"],
                        "values": {"US": {"2024-01-01": 100}},
                    },
                    "legend_size": 1,
                },
            )

        live_query = live_query_factory(handler)
        live_query.property_counts(
            event="Purchase",
            property_name="country",
            from_date="2024-01-01",
            to_date="2024-01-01",
            limit=10,
        )

    def test_property_counts_df_conversion(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """property_counts() result should have working df property."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": ["2024-01-01", "2024-01-02"],
                        "values": {
                            "US": {"2024-01-01": 100, "2024-01-02": 150},
                            "CA": {"2024-01-01": 50, "2024-01-02": 75},
                        },
                    },
                    "legend_size": 2,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.property_counts(
            event="Purchase",
            property_name="country",
            from_date="2024-01-01",
            to_date="2024-01-02",
        )

        df = result.df
        assert "date" in df.columns
        assert "value" in df.columns
        assert "count" in df.columns
        assert len(df) == 4  # 2 values × 2 dates

    def test_property_counts_empty_result(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """property_counts() should handle empty results."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "data": {
                        "series": [],
                        "values": {},
                    },
                    "legend_size": 0,
                },
            )

        live_query = live_query_factory(handler)
        result = live_query.property_counts(
            event="Purchase",
            property_name="country",
            from_date="2024-01-01",
            to_date="2024-01-01",
        )

        assert result.series == {}
        assert len(result.df) == 0

    def test_property_counts_propagates_query_error(
        self,
        live_query_factory: Callable[
            [Callable[[httpx.Request], httpx.Response]], LiveQueryService
        ],
    ) -> None:
        """property_counts() should propagate QueryError for invalid params."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": "Invalid property"})

        live_query = live_query_factory(handler)

        with pytest.raises(QueryError):
            live_query.property_counts(
                event="Purchase",
                property_name="invalid_property",
                from_date="2024-01-01",
                to_date="2024-01-01",
            )
