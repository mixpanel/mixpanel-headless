"""Tests for the MixpanelAPIClient ``bookmark-urls`` and shortlink methods.

045-report-links: ``create_bookmark_url``, ``get_bookmark_url``, and
``resolve_short_link``. Fixtures copy ``tests/unit/test_api_client_bookmarks.py``.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.session import Session
from mixpanel_headless.exceptions import (
    AuthenticationError,
    MixpanelHeadlessError,
    QueryError,
    RateLimitError,
    ReportLinkNotFoundError,
    ServerError,
    ShortLinkResolutionError,
)
from tests.conftest import make_session

_SLUG = "EBrV5bW2u9Mw"
_PARAMS = {"sections": {"show": []}, "displayOptions": {"chartType": "line"}}


@pytest.fixture
def test_credentials() -> Session:
    """Provide a US service-account session bound to project 12345."""
    return make_session(
        username="test_user",
        secret="test_secret",
        project_id="12345",
        region="us",
    )


@pytest.fixture
def eu_credentials() -> Session:
    """Provide an EU service-account session bound to project 12345."""
    return make_session(
        username="test_user",
        secret="test_secret",
        project_id="12345",
        region="eu",
    )


def create_mock_client(
    credentials: Session,
    handler: Callable[[httpx.Request], httpx.Response] | None = None,
) -> MixpanelAPIClient:
    """Create a MixpanelAPIClient with a mock transport.

    Args:
        credentials: The session to bind.
        handler: Optional request handler; defaults to an empty 200 JSON body.

    Returns:
        A client whose HTTP layer is ``httpx.MockTransport``.
    """
    if handler is None:
        transport = httpx.MockTransport(lambda _: httpx.Response(200, json={}))
    else:
        transport = httpx.MockTransport(handler)
    return MixpanelAPIClient(session=credentials, _transport=transport)


def _record(slug: str = _SLUG, **extra: object) -> dict[str, object]:
    """Build a server slug record.

    Args:
        slug: The slug to embed.
        **extra: Extra keys merged into the record.

    Returns:
        A dict shaped like a ``bookmark-urls`` result.
    """
    return {
        "slug": slug,
        "type": "insights",
        "params": _PARAMS,
        "project_id": 12345,
        "created_at": "2026-09-02T10:00:00",
        **extra,
    }


class TestCreateBookmarkUrl:
    """``create_bookmark_url`` POSTs the slug record to the project endpoint."""

    def test_posts_to_project_scoped_endpoint(self, test_credentials: Session) -> None:
        """The request is a POST to ``/api/app/projects/{pid}/bookmark-urls/``."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"results": _record()})

        with create_mock_client(test_credentials, handler) as client:
            client.create_bookmark_url(
                {"slug": _SLUG, "type": "insights", "params": _PARAMS}
            )

        assert len(seen) == 1
        assert seen[0].method == "POST"
        assert seen[0].url.path == "/api/app/projects/12345/bookmark-urls/"

    def test_body_carries_required_and_optional_keys(
        self, test_credentials: Session
    ) -> None:
        """slug, type, params plus name, description, bookmark_id are sent."""
        bodies: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"results": _record()})

        with create_mock_client(test_credentials, handler) as client:
            client.create_bookmark_url(
                {
                    "slug": _SLUG,
                    "type": "funnels",
                    "params": _PARAMS,
                    "name": "Logins",
                    "description": "last 7 days",
                    "bookmark_id": 9,
                }
            )

        assert bodies == [
            {
                "slug": _SLUG,
                "type": "funnels",
                "params": _PARAMS,
                "name": "Logins",
                "description": "last 7 days",
                "bookmark_id": 9,
            }
        ]

    def test_body_never_contains_workspace_id(self, test_credentials: Session) -> None:
        """A stray ``workspace_id`` key is dropped; the server ignores it anyway."""
        bodies: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            bodies.append(json.loads(request.content))
            return httpx.Response(200, json={"results": _record()})

        with create_mock_client(test_credentials, handler) as client:
            client.create_bookmark_url(
                {"slug": _SLUG, "type": "insights", "params": {}, "workspace_id": 75}
            )

        assert "workspace_id" not in bodies[0]
        assert bodies[0]["slug"] == _SLUG

    def test_stays_project_scoped_with_pinned_workspace(
        self, test_credentials: Session
    ) -> None:
        """``set_workspace_id`` does not route the call under ``/workspaces/``."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json={"results": _record()})

        with create_mock_client(test_credentials, handler) as client:
            client.set_workspace_id(789)
            client.create_bookmark_url(
                {"slug": _SLUG, "type": "insights", "params": {}}
            )

        assert seen == ["/api/app/projects/12345/bookmark-urls/"]

    def test_unwraps_results_envelope(self, test_credentials: Session) -> None:
        """The ``results`` dict is returned, not the envelope."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"status": "ok", "results": _record()})

        with create_mock_client(test_credentials, handler) as client:
            result = client.create_bookmark_url(
                {"slug": _SLUG, "type": "insights", "params": {}}
            )

        assert result["slug"] == _SLUG
        assert result["created_at"] == "2026-09-02T10:00:00"
        assert "results" not in result

    def test_non_dict_result_raises(self, test_credentials: Session) -> None:
        """A list result is a malformed response."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": [1, 2]})

        with (
            create_mock_client(test_credentials, handler) as client,
            pytest.raises(MixpanelHeadlessError, match="create_bookmark_url"),
        ):
            client.create_bookmark_url(
                {"slug": _SLUG, "type": "insights", "params": {}}
            )


class TestGetBookmarkUrl:
    """``get_bookmark_url`` GETs the slug record from the project endpoint."""

    def test_gets_project_scoped_endpoint(self, test_credentials: Session) -> None:
        """The request is a GET to ``/api/app/projects/{pid}/bookmark-urls/{slug}/``."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(200, json={"results": _record()})

        with create_mock_client(test_credentials, handler) as client:
            result = client.get_bookmark_url(_SLUG)

        assert len(seen) == 1
        assert seen[0].method == "GET"
        assert seen[0].url.path == f"/api/app/projects/12345/bookmark-urls/{_SLUG}/"
        assert result["slug"] == _SLUG
        assert result["params"] == _PARAMS

    def test_stays_project_scoped_with_pinned_workspace(
        self, test_credentials: Session
    ) -> None:
        """``set_workspace_id`` does not route the call under ``/workspaces/``."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request.url.path)
            return httpx.Response(200, json={"results": _record()})

        with create_mock_client(test_credentials, handler) as client:
            client.set_workspace_id(789)
            client.get_bookmark_url(_SLUG)

        assert seen == [f"/api/app/projects/12345/bookmark-urls/{_SLUG}/"]

    def test_404_maps_to_report_link_not_found(self, test_credentials: Session) -> None:
        """A 404 becomes ReportLinkNotFoundError with the slug in details."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, json={"error": "Not found"})

        with (
            create_mock_client(test_credentials, handler) as client,
            pytest.raises(ReportLinkNotFoundError) as exc_info,
        ):
            client.get_bookmark_url(_SLUG)

        exc = exc_info.value
        assert exc.code == "REPORT_LINK_SLUG_NOT_FOUND"
        assert exc.details["slug"] == _SLUG
        assert exc.details["project_id"] == 12345
        assert exc.details["region"] == "us"
        assert str(exc) == (
            f"No unsaved report found for slug {_SLUG} in project 12345 (us). "
            "A slug is only readable in the project and region that created it."
        )
        assert isinstance(exc.__cause__, QueryError)

    def test_500_passes_through_as_server_error(
        self, test_credentials: Session
    ) -> None:
        """A 5xx is not remapped."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        client = MixpanelAPIClient(
            session=test_credentials,
            max_retries=0,
            _transport=httpx.MockTransport(handler),
        )
        with client, pytest.raises(ServerError):
            client.get_bookmark_url(_SLUG)

    def test_403_passes_through_as_query_error(self, test_credentials: Session) -> None:
        """A 403 is not remapped to not-found."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(403, json={"error": "Permission denied"})

        with (
            create_mock_client(test_credentials, handler) as client,
            pytest.raises(QueryError) as exc_info,
        ):
            client.get_bookmark_url(_SLUG)

        assert exc_info.value.status_code == 403

    def test_non_dict_result_raises(self, test_credentials: Session) -> None:
        """A list result is a malformed response."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": []})

        with (
            create_mock_client(test_credentials, handler) as client,
            pytest.raises(MixpanelHeadlessError, match="get_bookmark_url"),
        ):
            client.get_bookmark_url(_SLUG)


_CODE = "AbC123"
_TARGET = f"https://mixpanel.com/project/12345/view/75/app/insights#{_SLUG}"


def _short_link_client(
    credentials: Session,
    handler: Callable[[httpx.Request], httpx.Response],
) -> MixpanelAPIClient:
    """Create a client for shortlink tests with retries disabled.

    Args:
        credentials: The session to bind.
        handler: The mock transport handler.

    Returns:
        A client whose HTTP layer is ``httpx.MockTransport``.
    """
    return MixpanelAPIClient(
        session=credentials, max_retries=0, _transport=httpx.MockTransport(handler)
    )


class TestResolveShortLink:
    """``resolve_short_link`` follows exactly one redirect with headless creds."""

    def test_single_request_redirects_not_followed(
        self, test_credentials: Session
    ) -> None:
        """One GET to ``https://mixpanel.com/s/{code}``; the 302 is not followed."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(302, headers={"Location": _TARGET})

        with _short_link_client(test_credentials, handler) as client:
            target = client.resolve_short_link(_CODE)

        assert target == _TARGET
        assert len(seen) == 1
        assert seen[0].method == "GET"
        assert str(seen[0].url) == f"https://mixpanel.com/s/{_CODE}"

    def test_request_carries_authorization(self, test_credentials: Session) -> None:
        """The request has the Authorization header and the library User-Agent."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(302, headers={"Location": _TARGET})

        with _short_link_client(test_credentials, handler) as client:
            client.resolve_short_link(_CODE)

        assert seen[0].headers["Authorization"].startswith("Basic ")
        assert "User-Agent" in seen[0].headers

    def test_relative_location_is_joined(self, test_credentials: Session) -> None:
        """A relative Location is joined against the request URL."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                302, headers={"Location": f"/project/12345/app/insights#{_SLUG}"}
            )

        with _short_link_client(test_credentials, handler) as client:
            target = client.resolve_short_link(_CODE)

        assert target == f"https://mixpanel.com/project/12345/app/insights#{_SLUG}"

    @pytest.mark.parametrize("status", [301, 303, 307, 308])
    def test_other_redirect_statuses(
        self, test_credentials: Session, status: int
    ) -> None:
        """Every redirect status with a Location returns the Location."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(status, headers={"Location": _TARGET})

        with _short_link_client(test_credentials, handler) as client:
            assert client.resolve_short_link(_CODE) == _TARGET

    def test_login_redirect_is_authentication_error(
        self, test_credentials: Session
    ) -> None:
        """A 302 to ``/login?next=...`` is an auth failure, not the target."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302, headers={"Location": f"/login?next=/s/{_CODE}"})

        with (
            _short_link_client(test_credentials, handler) as client,
            pytest.raises(AuthenticationError) as exc_info,
        ):
            client.resolve_short_link(_CODE)

        assert str(exc_info.value) == (
            f"Shortlink /s/{_CODE} requires authentication; the server redirected "
            "to the login page."
        )

    def test_200_html_with_location_script(self, test_credentials: Session) -> None:
        """A 200 page with ``window.location.href="..."`` yields the decoded URL."""
        escaped = _TARGET.replace("/", "\\/")
        body = (
            "<html><head><script>\n"
            f'  window.location.href = "{escaped}";\n'
            "</script></head></html>"
        )

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text=body, headers={"Content-Type": "text/html"})

        with _short_link_client(test_credentials, handler) as client:
            assert client.resolve_short_link(_CODE) == _TARGET

    def test_200_without_script_is_unexpected_response(
        self, test_credentials: Session
    ) -> None:
        """A 200 without the redirect script is SHORT_LINK_UNEXPECTED_RESPONSE."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, text="<html>hello</html>")

        with (
            _short_link_client(test_credentials, handler) as client,
            pytest.raises(ShortLinkResolutionError) as exc_info,
        ):
            client.resolve_short_link(_CODE)

        exc = exc_info.value
        assert exc.code == "SHORT_LINK_UNEXPECTED_RESPONSE"
        assert str(exc) == (
            f"Shortlink /s/{_CODE} returned HTTP 200 with a body mixpanel-headless "
            "does not recognize."
        )
        assert exc.details["hint"] == (
            "Open the shortlink in a browser and copy the full URL."
        )
        assert exc.details["short_code"] == _CODE

    def test_3xx_without_location(self, test_credentials: Session) -> None:
        """A redirect status without Location is SHORT_LINK_NO_LOCATION."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(302)

        with (
            _short_link_client(test_credentials, handler) as client,
            pytest.raises(ShortLinkResolutionError) as exc_info,
        ):
            client.resolve_short_link(_CODE)

        exc = exc_info.value
        assert exc.code == "SHORT_LINK_NO_LOCATION"
        assert str(exc) == (
            f"Shortlink /s/{_CODE} returned HTTP 302 without a Location header."
        )
        assert exc.details["status"] == 302

    def test_401(self, test_credentials: Session) -> None:
        """A 401 is AuthenticationError."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "nope"})

        with (
            _short_link_client(test_credentials, handler) as client,
            pytest.raises(AuthenticationError),
        ):
            client.resolve_short_link(_CODE)

    def test_404(self, test_credentials: Session) -> None:
        """A 404 is ReportLinkNotFoundError(SHORT_LINK_NOT_FOUND)."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(404, text="Not found")

        with (
            _short_link_client(test_credentials, handler) as client,
            pytest.raises(ReportLinkNotFoundError) as exc_info,
        ):
            client.resolve_short_link(_CODE)

        exc = exc_info.value
        assert exc.code == "SHORT_LINK_NOT_FOUND"
        assert str(exc) == f"Shortlink /s/{_CODE} does not exist on mixpanel.com."
        assert exc.details["short_code"] == _CODE
        assert exc.details["host"] == "mixpanel.com"

    def test_429(self, test_credentials: Session) -> None:
        """A 429 is RateLimitError with Retry-After honored."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "7"})

        with (
            _short_link_client(test_credentials, handler) as client,
            pytest.raises(RateLimitError) as exc_info,
        ):
            client.resolve_short_link(_CODE)

        assert exc_info.value.retry_after == 7

    def test_503(self, test_credentials: Session) -> None:
        """A 5xx is ServerError."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="down")

        with (
            _short_link_client(test_credentials, handler) as client,
            pytest.raises(ServerError) as exc_info,
        ):
            client.resolve_short_link(_CODE)

        assert exc_info.value.status_code == 503

    def test_other_4xx_is_unexpected_response(self, test_credentials: Session) -> None:
        """A 4xx outside the table is SHORT_LINK_UNEXPECTED_RESPONSE."""

        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(418, text="teapot")

        with (
            _short_link_client(test_credentials, handler) as client,
            pytest.raises(ShortLinkResolutionError) as exc_info,
        ):
            client.resolve_short_link(_CODE)

        assert exc_info.value.code == "SHORT_LINK_UNEXPECTED_RESPONSE"
        assert "HTTP 418" in str(exc_info.value)

    def test_connect_error(self, test_credentials: Session) -> None:
        """A transport failure is MixpanelHeadlessError(HTTP_ERROR)."""

        def handler(_request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("boom")

        with (
            _short_link_client(test_credentials, handler) as client,
            pytest.raises(MixpanelHeadlessError) as exc_info,
        ):
            client.resolve_short_link(_CODE)

        assert exc_info.value.code == "HTTP_ERROR"

    def test_eu_session_hits_eu_host(self, eu_credentials: Session) -> None:
        """An EU session requests ``https://eu.mixpanel.com/s/{code}``."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(str(request.url))
            return httpx.Response(302, headers={"Location": _TARGET})

        with _short_link_client(eu_credentials, handler) as client:
            client.resolve_short_link(_CODE)

        assert seen == [f"https://eu.mixpanel.com/s/{_CODE}"]

    def test_no_log_record_contains_authorization(
        self, test_credentials: Session, caplog: pytest.LogCaptureFixture
    ) -> None:
        """No log line at any level carries the Authorization value."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return httpx.Response(302, headers={"Location": _TARGET})

        with (
            caplog.at_level("DEBUG"),
            _short_link_client(test_credentials, handler) as client,
        ):
            client.resolve_short_link(_CODE)

        auth_value = seen[0].headers["Authorization"]
        secret = auth_value.split(" ", 1)[1]
        for record in caplog.records:
            text = record.getMessage()
            assert auth_value not in text
            assert secret not in text
            assert "Authorization" not in text
