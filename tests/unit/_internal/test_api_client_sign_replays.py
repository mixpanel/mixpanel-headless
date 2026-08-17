"""Unit tests for MixpanelAPIClient.sign_replays (044-session-replay).

Covers:
- POST body shape: `{"replays": [{"replay_id": ..., "replay_env": ...}, ...]}`
- URL: `/app/projects/<project_id>/replays/sign/bulk`
- 403 + SESSION_RECORDING_SENSITIVE_DATA → SessionReplayAccessError with details
- Other 4xx/5xx pass through to the existing APIError / ServerError mapping
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from tests.conftest import make_session

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.session import Session
from mixpanel_headless.exceptions import (
    APIError,
    QueryError,
    ServerError,
    SessionReplayAccessError,
)


@pytest.fixture
def us_credentials() -> Session:
    """US-region service-account session for sign-endpoint tests."""
    return make_session(
        username="test_user",
        secret="test_secret",
        project_id="12345",
        region="us",
    )


def _client(credentials: Session, handler: Any) -> MixpanelAPIClient:
    """Build an API client with an httpx.MockTransport-backed handler."""
    transport = httpx.MockTransport(handler)
    return MixpanelAPIClient(session=credentials, _transport=transport)


# =============================================================================
# Happy path: request shape + response passthrough
# =============================================================================


class TestSignReplaysRequest:
    """Request URL and JSON body shape."""

    def test_posts_to_bulk_endpoint(self, us_credentials: Session) -> None:
        """Hits POST /api/app/projects/<id>/replays/sign/bulk on the US host."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            captured["method"] = request.method
            captured["url"] = str(request.url)
            return httpx.Response(200, json={"results": []})

        with _client(us_credentials, handler) as client:
            client.sign_replays(["r-1"], env="prod")

        assert captured["method"] == "POST"
        assert (
            "https://mixpanel.com/api/app/projects/12345/replays/sign/bulk"
            in captured["url"]
        )

    def test_request_body_shape(self, us_credentials: Session) -> None:
        """Body is `{"replays": [{"replay_id": ..., "replay_env": "prod"}, ...]}`."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"results": []})

        with _client(us_credentials, handler) as client:
            client.sign_replays(["r-1", "r-2"], env="prod")

        assert captured["body"] == {
            "replays": [
                {"replay_id": "r-1", "replay_env": "prod"},
                {"replay_id": "r-2", "replay_env": "prod"},
            ]
        }

    def test_request_body_propagates_env_dev(self, us_credentials: Session) -> None:
        """env='dev' propagates to every replay entry."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"results": []})

        with _client(us_credentials, handler) as client:
            client.sign_replays(["r-1"], env="dev")

        assert captured["body"]["replays"][0]["replay_env"] == "dev"

    def test_returns_raw_results_list(self, us_credentials: Session) -> None:
        """Returns the `results` array contents (raw decoded dicts), in input order."""
        response_results = [
            {
                "replay_id": "r-1",
                "url": "https://cdn.mxpnl.com/srr-us/sha-12345/",
                "query_string": "URLPrefix=A&Expires=1&KeyName=K&Signature=S",
            },
            {
                "replay_id": "r-2",
                "url": "https://cdn.mxpnl.com/srr-us/sha2-12345/",
                "query_string": "URLPrefix=B&Expires=2&KeyName=K&Signature=S",
            },
        ]

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(200, json={"results": response_results})

        with _client(us_credentials, handler) as client:
            result = client.sign_replays(["r-1", "r-2"], env="prod")

        assert result == response_results

    def test_default_env_is_prod(self, us_credentials: Session) -> None:
        """env defaults to 'prod' when omitted."""
        captured: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            captured["body"] = json.loads(request.content)
            return httpx.Response(200, json={"results": []})

        with _client(us_credentials, handler) as client:
            client.sign_replays(["r-1"])

        assert captured["body"]["replays"][0]["replay_env"] == "prod"


# =============================================================================
# 403 → SessionReplayAccessError mapping
# =============================================================================


class TestSensitiveDataMapping:
    """SESSION_RECORDING_SENSITIVE_DATA 403 → SessionReplayAccessError."""

    def test_403_with_flag_raises_session_replay_access_error(
        self, us_credentials: Session
    ) -> None:
        """403 body containing SESSION_RECORDING_SENSITIVE_DATA → SessionReplayAccessError."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(
                403,
                json={
                    "error": (
                        "Your project has sensitive replay data. Set "
                        "SESSION_RECORDING_SENSITIVE_DATA to access."
                    )
                },
            )

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(SessionReplayAccessError) as exc_info,
        ):
            client.sign_replays(["r-1"], env="prod")

        exc = exc_info.value
        assert exc.status_code == 403
        assert exc.details["project_id"] == 12345
        assert exc.details["flag"] == "SESSION_RECORDING_SENSITIVE_DATA"
        assert exc.details["permission_required"] == "sensitive_data_replay"

    def test_403_without_flag_passes_through_to_query_error(
        self, us_credentials: Session
    ) -> None:
        """A 403 without the SESSION_RECORDING_SENSITIVE_DATA marker falls through."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(403, json={"error": "Permission denied"})

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(QueryError) as exc_info,
        ):
            client.sign_replays(["r-1"], env="prod")

        assert not isinstance(exc_info.value, SessionReplayAccessError)
        assert exc_info.value.status_code == 403


# =============================================================================
# 403 body-shape robustness (bug (c): TypeError on truthy non-dict/non-str JSON)
# =============================================================================


class TestSensitiveData403BodyShapes:
    """403 sniff handles every JSON body shape without crashing.

    Fix-of-record: context/phase3/bug-reports/python-handle-response-403-typeerror.md.
    The sniff must apply uniform substring semantics across dict, list, string,
    and scalar bodies — never raising an uncoded ``TypeError``.
    """

    @pytest.mark.parametrize("body", [42, 1.5, True])
    def test_403_truthy_scalar_body_raises_query_error(
        self, us_credentials: Session, body: object
    ) -> None:
        """A truthy non-dict/non-str JSON body (42/1.5/true) → QueryError, not TypeError."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(403, json=body)

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(QueryError) as exc_info,
        ):
            client.sign_replays(["r-1"], env="prod")

        assert not isinstance(exc_info.value, SessionReplayAccessError)
        assert exc_info.value.status_code == 403

    @pytest.mark.parametrize("content", [b"0", b"false", b"null"])
    def test_403_falsy_scalar_body_raises_query_error(
        self, us_credentials: Session, content: bytes
    ) -> None:
        """Falsy scalar bodies (0/false/null) keep the plain QueryError path."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(
                403,
                content=content,
                headers={"content-type": "application/json"},
            )

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(QueryError) as exc_info,
        ):
            client.sign_replays(["r-1"], env="prod")

        assert not isinstance(exc_info.value, SessionReplayAccessError)
        assert exc_info.value.status_code == 403

    def test_403_list_exact_element_flag_raises_replay_access_error(
        self, us_credentials: Session
    ) -> None:
        """List body with the flag as an exact element → SessionReplayAccessError."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(403, json=["SESSION_RECORDING_SENSITIVE_DATA"])

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(SessionReplayAccessError) as exc_info,
        ):
            client.sign_replays(["r-1"], env="prod")

        assert exc_info.value.details["flag"] == "SESSION_RECORDING_SENSITIVE_DATA"

    def test_403_list_substring_flag_raises_replay_access_error(
        self, us_credentials: Session
    ) -> None:
        """List body with the flag as a SUBSTRING of an element also matches.

        Uniform substring semantics: serialized-list sniffing must behave the
        same as dict and string bodies (the pre-fix code used Python list
        element-membership here and missed substring occurrences).
        """

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(
                403, json=["error: SESSION_RECORDING_SENSITIVE_DATA is set"]
            )

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(SessionReplayAccessError) as exc_info,
        ):
            client.sign_replays(["r-1"], env="prod")

        assert exc_info.value.details["flag"] == "SESSION_RECORDING_SENSITIVE_DATA"

    def test_403_string_body_with_flag_raises_replay_access_error(
        self, us_credentials: Session
    ) -> None:
        """JSON string body containing the flag → SessionReplayAccessError."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(403, json="SESSION_RECORDING_SENSITIVE_DATA denied")

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(SessionReplayAccessError) as exc_info,
        ):
            client.sign_replays(["r-1"], env="prod")

        assert exc_info.value.status_code == 403


# =============================================================================
# Pass-through for other HTTP errors
# =============================================================================


class TestOtherHttpErrors:
    """4xx and 5xx not matching the sensitive-data 403 pattern use the existing mapping."""

    def test_400_raises_query_error(self, us_credentials: Session) -> None:
        """400 → QueryError (existing behavior)."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(400, json={"error": "Bad request"})

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(QueryError),
        ):
            client.sign_replays(["r-1"], env="prod")

    def test_500_raises_server_error(self, us_credentials: Session) -> None:
        """5xx → ServerError (existing behavior)."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(500, json={"error": "Internal server error"})

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(ServerError),
        ):
            client.sign_replays(["r-1"], env="prod")

    def test_non_replay_403_is_not_session_replay_access_error(
        self, us_credentials: Session
    ) -> None:
        """Plain 403 (no sensitive-data marker) is still an APIError but not the replay subclass."""

        def handler(_request: httpx.Request) -> httpx.Response:
            """Mock HTTP handler returning a canned httpx.Response for this test."""
            return httpx.Response(403, json={"error": "Generic permission denied"})

        with (
            _client(us_credentials, handler) as client,
            pytest.raises(APIError) as exc_info,
        ):
            client.sign_replays(["r-1"], env="prod")

        assert not isinstance(exc_info.value, SessionReplayAccessError)
