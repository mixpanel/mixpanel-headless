"""Unit tests for cursor-based pagination helper.

Tests for paginate_all() function that iterates through paginated App API responses.
"""
# ruff: noqa: ARG001, ARG005

from __future__ import annotations

import itertools
from collections.abc import Callable
from unittest.mock import patch

import httpx
import pytest

from mixpanel_headless._internal.api_client import (
    DEFAULT_APP_TIMEOUT_S,
    MixpanelAPIClient,
)
from mixpanel_headless._internal.auth.session import Session
from mixpanel_headless._internal.pagination import (
    _BACKOFF_MAX,
    MAX_RATE_LIMIT_RETRIES,
    paginate_all,
)
from mixpanel_headless.exceptions import (
    AuthenticationError,
    MixpanelHeadlessError,
    RateLimitError,
    ServerError,
)
from tests.conftest import make_session

# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def oauth_credentials() -> Session:
    """Create OAuth credentials for pagination testing."""
    return make_session(project_id="12345", region="us", oauth_token="test-oauth-token")


def create_mock_client(
    credentials: Session,
    handler: Callable[[httpx.Request], httpx.Response],
) -> MixpanelAPIClient:
    """Create a client with mock transport.

    Args:
        credentials: Authentication credentials.
        handler: Mock HTTP handler function.

    Returns:
        MixpanelAPIClient configured with mock transport.
    """
    transport = httpx.MockTransport(handler)
    return MixpanelAPIClient(session=credentials, _transport=transport)


# =============================================================================
# T028: Cursor pagination tests
# =============================================================================


class TestPaginateAll:
    """Test paginate_all() cursor pagination helper."""

    def test_yields_all_results_across_pages(self, oauth_credentials: Session) -> None:
        """paginate_all() should yield all results from multiple pages."""
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            cursor = request.url.params.get("cursor")

            if cursor is None:
                # First page
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": [{"id": 1}, {"id": 2}],
                        "pagination": {
                            "page_size": 2,
                            "next_cursor": "cursor_page2",
                        },
                    },
                )
            elif cursor == "cursor_page2":
                # Second page
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": [{"id": 3}],
                        "pagination": {
                            "page_size": 2,
                            "next_cursor": None,
                        },
                    },
                )
            else:
                return httpx.Response(404, json={"error": "Unknown cursor"})

        client = create_mock_client(oauth_credentials, handler)
        with client:
            items = list(paginate_all(client, "/projects/12345/dashboards"))

        assert items == [{"id": 1}, {"id": 2}, {"id": 3}]
        assert call_count == 2

    def test_follows_next_cursor_until_none(self, oauth_credentials: Session) -> None:
        """paginate_all() should stop when next_cursor is None."""
        cursors_seen: list[str | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            cursor = request.url.params.get("cursor")
            cursors_seen.append(cursor)

            if cursor is None:
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": [{"id": 1}],
                        "pagination": {
                            "page_size": 1,
                            "next_cursor": "c2",
                        },
                    },
                )
            elif cursor == "c2":
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": [{"id": 2}],
                        "pagination": {
                            "page_size": 1,
                            "next_cursor": "c3",
                        },
                    },
                )
            else:
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": [{"id": 3}],
                        "pagination": {
                            "page_size": 1,
                            "next_cursor": None,
                        },
                    },
                )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            items = list(paginate_all(client, "/projects/12345/items"))

        assert len(items) == 3
        assert cursors_seen == [None, "c2", "c3"]

    def test_handles_empty_results(self, oauth_credentials: Session) -> None:
        """paginate_all() should handle empty results gracefully."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [],
                    "pagination": {
                        "page_size": 100,
                        "next_cursor": None,
                    },
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            items = list(paginate_all(client, "/projects/12345/dashboards"))

        assert items == []

    def test_handles_missing_pagination_field(self, oauth_credentials: Session) -> None:
        """paginate_all() should treat missing pagination as single page."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [{"id": 1}, {"id": 2}],
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            items = list(paginate_all(client, "/projects/12345/dashboards"))

        assert items == [{"id": 1}, {"id": 2}]

    def test_respects_page_size_parameter(self, oauth_credentials: Session) -> None:
        """paginate_all() should pass page_size as query parameter."""
        captured_params: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [{"id": 1}],
                    "pagination": {"page_size": 25, "next_cursor": None},
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            list(paginate_all(client, "/projects/12345/dashboards", page_size=25))

        assert captured_params[0]["page_size"] == "25"

    def test_passes_additional_params(self, oauth_credentials: Session) -> None:
        """paginate_all() should merge extra params with pagination params."""
        captured_params: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [],
                    "pagination": {"page_size": 100, "next_cursor": None},
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            list(
                paginate_all(
                    client,
                    "/projects/12345/dashboards",
                    params={"include_archived": "true"},
                )
            )

        assert captured_params[0]["include_archived"] == "true"

    def test_injects_query_origin_telemetry(self, oauth_credentials: Session) -> None:
        """paginate_all() should auto-inject the query_origin telemetry param.

        Locks the literal value so a future typo or accidental rename of the
        telemetry tag is caught at PR time rather than silently corrupting
        Mixpanel-internal analytics dashboards.
        """
        captured_params: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [{"id": 1}],
                    "pagination": {"page_size": 100, "next_cursor": None},
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            list(paginate_all(client, "/projects/12345/dashboards"))

        assert captured_params[0]["query_origin"] == "mixpanel-headless"

    def test_canonical_query_origin_wins_over_caller(
        self, oauth_credentials: Session
    ) -> None:
        """Caller-supplied ``query_origin`` cannot override the canonical value.

        The telemetry tag is non-negotiable: even if a caller passes a spoofed
        ``query_origin`` in ``params``, the canonical ``mixpanel-headless``
        value must win.
        """
        captured_params: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_params.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [{"id": 1}],
                    "pagination": {"page_size": 100, "next_cursor": None},
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            list(
                paginate_all(
                    client,
                    "/projects/12345/dashboards",
                    params={"query_origin": "spoofed-by-caller"},
                )
            )

        assert captured_params[0]["query_origin"] == "mixpanel-headless"

    def test_default_timeout_outlasts_app_deadline(
        self, oauth_credentials: Session
    ) -> None:
        """Pagination requests carry the route-aware App API timeout.

        With no explicit client timeout, the request timeout must be the
        app-route default (sized to outlast the server's ~120s deadline),
        never ``None`` (which httpx reads as "no timeout at all").
        """
        captured_timeouts: list[dict[str, float | None] | None] = []

        def handler(request: httpx.Request) -> httpx.Response:
            captured_timeouts.append(request.extensions.get("timeout"))
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [{"id": 1}],
                    "pagination": {"page_size": 100, "next_cursor": None},
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            list(paginate_all(client, "/projects/12345/dashboards"))

        assert captured_timeouts[0] is not None
        assert captured_timeouts[0]["read"] == DEFAULT_APP_TIMEOUT_S

    def test_handles_response_without_results_key(
        self, oauth_credentials: Session
    ) -> None:
        """paginate_all() should handle responses where app_request returns a list."""

        def handler(request: httpx.Request) -> httpx.Response:
            # app_request unwraps results, so if the API returns results as
            # a list directly, paginate_all gets a list
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [{"id": 1}],
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            items = list(paginate_all(client, "/projects/12345/items"))

        assert items == [{"id": 1}]


class TestPaginateAllRobustness:
    """Test paginate_all() robustness against infinite loops and bad responses."""

    def test_infinite_loop_same_cursor(self, oauth_credentials: Session) -> None:
        """Verify pagination terminates when the server returns the same cursor forever.

        A server that always returns the same next_cursor would cause an
        infinite loop without the MAX_PAGES guard.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Return the same cursor on every page.

            Args:
                request: The incoming request.

            Returns:
                Response with a constant cursor.
            """
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [{"id": 1}],
                    "pagination": {
                        "page_size": 1,
                        "next_cursor": "same",
                    },
                },
            )

        # Use a small MAX_PAGES for the test to avoid long runtime
        with patch("mixpanel_headless._internal.pagination.MAX_PAGES", 50):
            client = create_mock_client(oauth_credentials, handler)
            with (
                client,
                pytest.raises(MixpanelHeadlessError, match="maximum page limit"),
            ):
                # Consume all items — should raise before 15000
                list(
                    itertools.islice(
                        paginate_all(client, "/projects/12345/items"), 15000
                    )
                )

    def test_non_json_response(self, oauth_credentials: Session) -> None:
        """Verify pagination raises a clear error for non-JSON responses.

        If the server returns HTML or other non-JSON content, the function
        should raise MixpanelHeadlessError rather than a raw JSONDecodeError.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Return HTML instead of JSON.

            Args:
                request: The incoming request.

            Returns:
                HTML response.
            """
            return httpx.Response(
                200,
                content=b"<html><body>Error</body></html>",
                headers={"content-type": "text/html"},
            )

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(MixpanelHeadlessError, match="Non-JSON response"):
            list(paginate_all(client, "/projects/12345/items"))

    def test_http_429_mid_pagination(self, oauth_credentials: Session) -> None:
        """Verify that a 429 on the second page raises RateLimitError.

        Rate limits can occur mid-pagination; the error should propagate
        as a proper RateLimitError. ``time.sleep`` is patched out so the retry
        budget (3 x the advertised 30s) does not cost the suite 90 seconds of
        real wall time.
        """
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Return OK on first page, 429 on second.

            Args:
                request: The incoming request.

            Returns:
                Success or rate-limit response.
            """
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": [{"id": 1}],
                        "pagination": {"page_size": 1, "next_cursor": "c2"},
                    },
                )
            return httpx.Response(
                429,
                json={"error": "rate_limited"},
                headers={"Retry-After": "30"},
            )

        client = create_mock_client(oauth_credentials, handler)
        with (
            patch("time.sleep") as mock_sleep,
            client,
            pytest.raises(RateLimitError),
        ):
            list(paginate_all(client, "/projects/12345/items"))

        assert [call.args[0] for call in mock_sleep.call_args_list] == [30.0] * 3

    def test_http_500_mid_pagination(self, oauth_credentials: Session) -> None:
        """Verify that a 500 on the second page raises ServerError.

        Server errors during pagination should be mapped to ServerError.
        """
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Return OK on first page, 500 on second.

            Args:
                request: The incoming request.

            Returns:
                Success or server-error response.
            """
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": [{"id": 1}],
                        "pagination": {"page_size": 1, "next_cursor": "c2"},
                    },
                )
            return httpx.Response(500, json={"error": "internal_error"})

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(ServerError):
            list(paginate_all(client, "/projects/12345/items"))

    def test_http_401_mid_pagination(self, oauth_credentials: Session) -> None:
        """Verify that a 401 on the second page raises AuthenticationError.

        Token expiry during pagination should be mapped to AuthenticationError.
        """
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Return OK on first page, 401 on second.

            Args:
                request: The incoming request.

            Returns:
                Success or auth-error response.
            """
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": [{"id": 1}],
                        "pagination": {"page_size": 1, "next_cursor": "c2"},
                    },
                )
            return httpx.Response(401, json={"error": "unauthorized"})

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(AuthenticationError):
            list(paginate_all(client, "/projects/12345/items"))


class TestPaginateAllMalformedResults:
    """Test paginate_all() handling of a malformed ``results`` field."""

    def test_null_results_treated_as_empty_page(
        self, oauth_credentials: Session
    ) -> None:
        """A JSON ``null`` ``results`` field must behave like an absent one.

        A server that serializes an empty page as ``"results": null`` rather
        than omitting the key must not crash the paginator with an unhandled
        ``TypeError`` from ``yield from None``.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a page whose results field is JSON null.

            Args:
                request: The incoming request.

            Returns:
                Response with ``results`` set to null and no next cursor.
            """
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": None,
                    "pagination": {"page_size": 100, "next_cursor": None},
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            items = list(paginate_all(client, "/projects/12345/items"))

        assert items == []

    def test_null_results_still_follows_next_cursor(
        self, oauth_credentials: Session
    ) -> None:
        """A null ``results`` page must not abort an otherwise healthy walk.

        The cursor, not the results field, decides when iteration stops, so a
        null page in the middle of a chain must be skipped and the next page
        fetched.
        """
        call_count = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a null-results first page, then a normal second page.

            Args:
                request: The incoming request.

            Returns:
                Null-results page or the final page of items.
            """
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return httpx.Response(
                    200,
                    json={
                        "status": "ok",
                        "results": None,
                        "pagination": {"page_size": 100, "next_cursor": "c2"},
                    },
                )
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": [{"id": 1}],
                    "pagination": {"page_size": 100, "next_cursor": None},
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client:
            items = list(paginate_all(client, "/projects/12345/items"))

        assert items == [{"id": 1}]
        assert call_count == 2

    @pytest.mark.parametrize(
        "results_value",
        ["abc", 42, {"id": 1}, True],
        ids=["string", "int", "dict", "bool"],
    )
    def test_non_list_results_raises_invalid_response(
        self, oauth_credentials: Session, results_value: object
    ) -> None:
        """A non-list, non-null ``results`` field must raise a typed error.

        Iterating a string would silently yield individual characters and
        iterating a dict would yield keys; both are corrupt output dressed up
        as success. The paginator must reject the response instead.

        Args:
            oauth_credentials: Session fixture.
            results_value: Malformed value to place in the ``results`` field.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a page whose results field is not a list.

            Args:
                request: The incoming request.

            Returns:
                Response with a malformed ``results`` field.
            """
            return httpx.Response(
                200,
                json={
                    "status": "ok",
                    "results": results_value,
                    "pagination": {"page_size": 100, "next_cursor": None},
                },
            )

        client = create_mock_client(oauth_credentials, handler)
        with client, pytest.raises(MixpanelHeadlessError, match="must be a list") as ei:
            list(paginate_all(client, "/projects/12345/items"))

        assert ei.value.code == "INVALID_RESPONSE"


def run_rate_limited_pagination(
    credentials: Session,
    retry_after: str | None,
    *,
    always_429: bool = False,
) -> tuple[list[float], list[BaseException]]:
    """Drive a rate-limited pagination run and capture the sleep durations.

    Args:
        credentials: Session used to build the mock-transport client.
        retry_after: Value for the ``Retry-After`` header, or ``None`` to omit
            the header entirely.
        always_429: When True every response is a 429 so the retry budget is
            exhausted; when False only the first response is a 429.

    Returns:
        Tuple of (sleep durations passed to ``time.sleep``, exceptions raised
        by the pagination run).
    """
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a 429 (with optional Retry-After) then a terminal page.

        Args:
            request: The incoming request.

        Returns:
            Rate-limit response or the final page of results.
        """
        nonlocal call_count
        call_count += 1
        if always_429 or call_count == 1:
            headers = {} if retry_after is None else {"Retry-After": retry_after}
            return httpx.Response(429, json={"error": "rate_limited"}, headers=headers)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "results": [{"id": 1}],
                "pagination": {"page_size": 100, "next_cursor": None},
            },
        )

    raised: list[BaseException] = []
    client = create_mock_client(credentials, handler)
    with patch("time.sleep") as mock_sleep, client:
        try:
            list(paginate_all(client, "/projects/12345/items"))
        except BaseException as exc:  # noqa: BLE001 - recorded for assertions
            raised.append(exc)
    durations = [float(call.args[0]) for call in mock_sleep.call_args_list]
    return durations, raised


class TestPaginateAllRetryAfter:
    """Test defensive parsing of the ``Retry-After`` header before sleeping."""

    def test_valid_retry_after_is_honored(self, oauth_credentials: Session) -> None:
        """A sane numeric Retry-After must be used verbatim as the wait."""
        durations, raised = run_rate_limited_pagination(oauth_credentials, "30")

        assert durations == [30.0]
        assert raised == []

    @pytest.mark.parametrize(
        "retry_after",
        ["-1", "-0.5", "nan", "NaN", "inf", "-inf", "abc", "", "1,000"],
        ids=[
            "negative-int",
            "negative-float",
            "nan",
            "nan-mixed-case",
            "infinity",
            "negative-infinity",
            "garbage",
            "empty",
            "thousands-separator",
        ],
    )
    def test_hostile_retry_after_falls_back_to_backoff(
        self, oauth_credentials: Session, retry_after: str
    ) -> None:
        """Invalid Retry-After values must never reach ``time.sleep``.

        ``time.sleep`` raises ValueError on negatives and NaN and OverflowError
        on infinity, so an unvalidated header value turns a retryable 429 into
        an unhandled crash out of a public iterator. Each of these must instead
        fall back to the exponential-backoff schedule.

        Args:
            oauth_credentials: Session fixture.
            retry_after: Hostile header value under test.
        """
        durations, raised = run_rate_limited_pagination(oauth_credentials, retry_after)

        assert durations == [1.0]
        assert raised == []

    @pytest.mark.parametrize(
        "retry_after",
        ["999999", "1e9", "86400"],
        ids=["huge-int", "exponent", "one-day"],
    )
    def test_oversized_retry_after_is_clamped(
        self, oauth_credentials: Session, retry_after: str
    ) -> None:
        """A Retry-After beyond the backoff cap must be clamped, not obeyed.

        Sleeping for a server-chosen day inside a paginator is a hang, so the
        wait is bounded by the same cap the computed backoff uses.

        Args:
            oauth_credentials: Session fixture.
            retry_after: Oversized header value under test.
        """
        durations, raised = run_rate_limited_pagination(oauth_credentials, retry_after)

        assert durations == [_BACKOFF_MAX]
        assert raised == []

    def test_missing_retry_after_uses_exponential_backoff(
        self, oauth_credentials: Session
    ) -> None:
        """With no Retry-After header the backoff schedule is unchanged."""
        durations, raised = run_rate_limited_pagination(oauth_credentials, None)

        assert durations == [1.0]
        assert raised == []

    def test_exhausted_retries_backoff_schedule_is_bounded(
        self, oauth_credentials: Session
    ) -> None:
        """Every sleep in an exhausted retry run stays within the cap."""
        durations, raised = run_rate_limited_pagination(
            oauth_credentials, "inf", always_429=True
        )

        assert durations == [1.0, 2.0, 4.0]
        assert len(durations) == MAX_RATE_LIMIT_RETRIES
        assert all(0.0 <= d <= _BACKOFF_MAX for d in durations)
        assert isinstance(raised[0], RateLimitError)

    @pytest.mark.parametrize(
        "retry_after",
        ["-5", "nan", "inf", "abc"],
        ids=["negative", "nan", "infinity", "garbage"],
    )
    def test_hostile_retry_after_not_reported_on_error(
        self, oauth_credentials: Session, retry_after: str
    ) -> None:
        """A hostile header must not be echoed back as ``RateLimitError.retry_after``.

        The documented caller pattern is ``time.sleep(e.retry_after or 60)``,
        so surfacing a negative or non-finite value would just relocate the
        crash into user code.

        Args:
            oauth_credentials: Session fixture.
            retry_after: Hostile header value under test.
        """
        _, raised = run_rate_limited_pagination(
            oauth_credentials, retry_after, always_429=True
        )

        assert isinstance(raised[0], RateLimitError)
        assert raised[0].retry_after is None

    def test_valid_retry_after_reported_on_error(
        self, oauth_credentials: Session
    ) -> None:
        """A sane header value is still reported on the raised RateLimitError."""
        _, raised = run_rate_limited_pagination(
            oauth_credentials, "45", always_429=True
        )

        assert isinstance(raised[0], RateLimitError)
        assert raised[0].retry_after == 45
