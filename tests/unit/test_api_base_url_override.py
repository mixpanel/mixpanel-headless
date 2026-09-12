"""Unit tests for the ``MP_API_BASE_URL`` / ``MP_APP_BASE_URL`` host override.

When ``MP_API_BASE_URL`` is set, the per-region ``ENDPOINTS`` lookup is
bypassed and every API family resolves to a fixed path prefix on that one
base (``/api/query``, ``/api/2.0``, ``/api/query/engage``, ``/api/app``).
``MP_APP_BASE_URL`` optionally re-homes just the App API family. Both are
read at request time, so ``use(account=...)`` swaps and env monkeypatching
keep working. With both unset the live table is returned untouched.

Tests use ``httpx.MockTransport`` and assert the full request URL per
family, mirroring ``tests/unit/test_api_client.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from typer.testing import CliRunner

from mixpanel_headless._internal.api_client import (
    DEFAULT_APP_TIMEOUT_S,
    DEFAULT_QUERY_TIMEOUT_S,
    ENDPOINTS,
    MixpanelAPIClient,
    _api_family_for,
    _endpoints_for,
)
from mixpanel_headless._internal.auth.session import Session
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session

_BASE = "http://127.0.0.1:8080"
"""Override base used throughout; a plain-``http`` loopback host."""

_EXPECTED: dict[str, str] = {
    "query": f"{_BASE}/api/query",
    "export": f"{_BASE}/api/2.0",
    "engage": f"{_BASE}/api/query/engage",
    "app": f"{_BASE}/api/app",
}
"""The prefix table from the work order, anchored at ``_BASE``."""

_INSIGHTS_BODY: dict[str, Any] = {
    "computed_at": "2025-01-15T12:00:00",
    "date_range": {"from_date": "2025-01-01", "to_date": "2025-01-31"},
    "headers": ["$event"],
    "series": {"A. Login": {"2025-01-01": 10}},
    "meta": {"sampling_factor": 1.0},
}
"""Minimal insights response (copied from ``test_query_limit.py``)."""

_FUNNEL_BODY: dict[str, Any] = {
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
"""Minimal ``arb_funnels`` response (copied from ``test_query_limit.py``)."""

_RETENTION_BODY: dict[str, Any] = {
    "computed_at": "2025-01-15T12:00:00",
    "date_range": {"from_date": "2025-01-01", "to_date": "2025-01-31"},
    "headers": ["$retention"],
    "series": {"2025-01-01": {"counts": [100, 40], "first": 100}},
    "meta": {"sampling_factor": 1.0},
}
"""Minimal insights-mode retention response (copied from ``test_query_limit.py``)."""

_LEGACY_FUNNEL_BODY: dict[str, Any] = {
    "meta": {"dates": ["2024-01-01"]},
    "data": {
        "2024-01-01": {
            "steps": [
                {
                    "count": 10,
                    "step_label": "Login",
                    "event": "Login",
                    "goal": "Login",
                    "overall_conv_ratio": 1.0,
                    "step_conv_ratio": 1.0,
                    "avg_time": None,
                }
            ],
            "analysis": {
                "completion": 10,
                "starting_amount": 10,
                "steps": 1,
                "worst": 1,
            },
        }
    },
}
"""Minimal legacy ``GET /funnels`` response."""

_LEGACY_RETENTION_BODY: dict[str, Any] = {
    "2024-01-01": {"counts": [10, 4], "first": 10},
}
"""Minimal legacy ``GET /retention`` response."""

_STATS_BODY: dict[str, Any] = {
    "results": 42,
    "status": "ok",
    "computed_at": "2025-01-15T10:00:00",
}
"""Minimal Engage ``stats`` response."""

_ENGAGE_BODY: dict[str, Any] = {
    "results": [{"$distinct_id": "u1", "$properties": {"$last_seen": "2025-01-15"}}],
    "page": 0,
    "page_size": 1000,
    "session_id": "sess",
    "total": 1,
    "status": "ok",
}
"""Minimal Engage profile page."""

_EXPORT_LINE = (
    b'{"event":"Login","properties":{"distinct_id":"u1","time":1705328400}}\n'
)
"""One JSONL export line."""


def _insights_body_for(request: httpx.Request) -> dict[str, Any]:
    """Pick the canned ``/insights`` body from the posted report definition.

    ``query``, ``query_funnel`` and ``query_retention`` all POST to
    ``/insights`` with ``{"bookmark": <params>, "project_id": ...,
    "queryLimits": ...}``; the params' ``sections.show[0].behavior.type``
    says which report it is.

    Args:
        request: The captured ``POST /insights`` request.

    Returns:
        ``_FUNNEL_BODY``, ``_RETENTION_BODY`` or ``_INSIGHTS_BODY``.
    """
    if not request.content:
        return _INSIGHTS_BODY
    payload = json.loads(request.content)
    params = payload.get("bookmark", payload)
    show = params.get("sections", {}).get("show", [])
    behavior_type = show[0].get("behavior", {}).get("type") if show else None
    if behavior_type == "funnel":
        return _FUNNEL_BODY
    if behavior_type == "retention":
        return _RETENTION_BODY
    return _INSIGHTS_BODY


class _Recorder:
    """Mock-transport handler that logs every request and answers per route.

    The response body is chosen from the request path and method so the
    full ``Workspace`` facade can run end to end against the recorder.

    Attributes:
        requests: Every ``httpx.Request`` seen, in order.
    """

    def __init__(self) -> None:
        """Start with an empty request log."""
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        """Record ``request`` and return a canned 200 for its route.

        Args:
            request: The outgoing request under test.

        Returns:
            A 200 ``httpx.Response`` whose body matches the route family.
        """
        self.requests.append(request)
        path = request.url.path
        if path.endswith("/export"):
            return httpx.Response(200, content=_EXPORT_LINE)
        if path.endswith("/insights"):
            return httpx.Response(200, json=_insights_body_for(request))
        if path.endswith("/arb_funnels"):
            return httpx.Response(200, json=_FUNNEL_BODY)
        if path.endswith("/retention"):
            if request.method == "POST":
                return httpx.Response(200, json=_RETENTION_BODY)
            return httpx.Response(200, json=_LEGACY_RETENTION_BODY)
        if path.endswith("/funnels"):
            return httpx.Response(200, json=_LEGACY_FUNNEL_BODY)
        if path.endswith("/engage/stats"):
            return httpx.Response(200, json=_STATS_BODY)
        if path.endswith("/engage"):
            return httpx.Response(200, json=_ENGAGE_BODY)
        if path.endswith("/events/names"):
            return httpx.Response(200, json=["Login"])
        return httpx.Response(200, json={"results": []})

    def urls(self) -> list[str]:
        """Return every recorded URL with its query string stripped.

        Returns:
            Ordered list of ``scheme://host[:port]/path`` strings.
        """
        return [str(r.url.copy_with(query=None)) for r in self.requests]


def _no_mixpanel_hosts(recorder: _Recorder) -> None:
    """Assert every recorded request went to the loopback override host.

    Args:
        recorder: The recorder whose requests are checked.

    Raises:
        AssertionError: A request left for any host other than
            ``127.0.0.1:8080``.
    """
    assert recorder.requests, "expected at least one request"
    for request in recorder.requests:
        assert request.url.host == "127.0.0.1", str(request.url)
        assert request.url.port == 8080, str(request.url)
        assert "mixpanel.com" not in str(request.url)


def _install_transport(monkeypatch: pytest.MonkeyPatch, recorder: _Recorder) -> None:
    """Force every ``MixpanelAPIClient`` built during the test onto ``recorder``.

    ``Workspace()`` and the ``mp`` CLI build their client internally with no
    transport hook, so this wraps the constructor to inject one. The wrapper
    only fills ``_transport`` when the caller left it unset.

    Args:
        monkeypatch: pytest monkeypatch fixture (restores the constructor).
        recorder: The handler backing the injected ``httpx.MockTransport``.
    """
    original_init = MixpanelAPIClient.__init__
    transport = httpx.MockTransport(recorder)

    def _init(self: MixpanelAPIClient, **kwargs: Any) -> None:
        """Delegate to the real constructor with the mock transport injected.

        Args:
            self: The client under construction.
            **kwargs: Constructor keyword arguments (``Any`` because the
                wrapper forwards whatever the caller passed).
        """
        kwargs.setdefault("_transport", transport)
        original_init(self, **kwargs)

    monkeypatch.setattr(MixpanelAPIClient, "__init__", _init)


@pytest.fixture
def us_session() -> Session:
    """Return a US service-account Session with no workspace pinned.

    Returns:
        A ``Session`` for project ``12345`` in region ``us``.
    """
    return make_session(project_id="12345", region="us")


@pytest.fixture
def pinned_session() -> Session:
    """Return a US Session with workspace ``777`` pinned.

    Returns:
        A ``Session`` whose ``workspace`` axis carries id ``777``.
    """
    return make_session(project_id="12345", region="us", workspace_id=777)


@pytest.fixture
def override_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set ``MP_API_BASE_URL`` to the loopback base for the test.

    Args:
        monkeypatch: pytest monkeypatch fixture.
    """
    monkeypatch.setenv("MP_API_BASE_URL", _BASE)


@pytest.fixture
def env_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, override_env: None
) -> _Recorder:
    """Wire env-var auth plus the override so a bare ``Workspace()`` resolves.

    Pins ``$HOME`` / ``MP_CONFIG_PATH`` to ``tmp_path``, exports the
    service-account quad, and routes every client onto a fresh recorder.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        tmp_path: pytest temporary directory.
        override_env: Ensures ``MP_API_BASE_URL`` is exported.

    Returns:
        The recorder capturing every request the workspace issues.
    """
    del override_env
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MP_CONFIG_PATH", str(tmp_path / ".mp" / "config.toml"))
    monkeypatch.setenv("MP_USERNAME", "svc")
    monkeypatch.setenv("MP_SECRET", "s3cret")
    monkeypatch.setenv("MP_PROJECT_ID", "12345")
    monkeypatch.setenv("MP_REGION", "us")
    recorder = _Recorder()
    _install_transport(monkeypatch, recorder)
    return recorder


# =============================================================================
# _endpoints_for resolver
# =============================================================================


class TestEndpointsForResolver:
    """``_endpoints_for`` picks the override table or the live region table."""

    @pytest.mark.parametrize("region", ["us", "eu", "in"])
    def test_unset_returns_live_table_object(self, region: str) -> None:
        """With both vars unset the live ``ENDPOINTS[region]`` object is returned.

        Args:
            region: Region under test.
        """
        assert _endpoints_for(region) is ENDPOINTS[region]

    @pytest.mark.parametrize("region", ["us", "eu", "in"])
    def test_override_ignores_region(self, region: str, override_env: None) -> None:
        """Every region resolves to the same prefix table under the override.

        Args:
            region: Region under test.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        assert _endpoints_for(region) == _EXPECTED

    @pytest.mark.parametrize("suffix", ["/", "//", "///"])
    def test_trailing_slashes_are_stripped(
        self, suffix: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Trailing slashes on the base never produce ``//api`` URLs.

        Args:
            suffix: Slash run appended to the base.
            monkeypatch: pytest monkeypatch fixture.
        """
        monkeypatch.setenv("MP_API_BASE_URL", f"{_BASE}{suffix}")
        assert _endpoints_for("us") == _EXPECTED

    @pytest.mark.parametrize("value", ["", "/", "//"])
    def test_empty_or_slash_only_value_means_unset(
        self, value: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An empty (or slash-only) value is treated as unset, not as base ``""``.

        Args:
            value: The degenerate env value.
            monkeypatch: pytest monkeypatch fixture.
        """
        monkeypatch.setenv("MP_API_BASE_URL", value)
        assert _endpoints_for("eu") is ENDPOINTS["eu"]

    def test_path_prefixed_base_is_preserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A base with its own path segment keeps that segment ahead of the prefix.

        Args:
            monkeypatch: pytest monkeypatch fixture.
        """
        monkeypatch.setenv("MP_API_BASE_URL", "https://proxy.example/mp/")
        table = _endpoints_for("us")
        assert table["query"] == "https://proxy.example/mp/api/query"
        assert table["export"] == "https://proxy.example/mp/api/2.0"
        assert table["engage"] == "https://proxy.example/mp/api/query/engage"
        assert table["app"] == "https://proxy.example/mp/api/app"

    def test_live_table_is_never_mutated(self, override_env: None) -> None:
        """Resolving the override must not write into ``ENDPOINTS``.

        Args:
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        before = {r: dict(t) for r, t in ENDPOINTS.items()}
        _endpoints_for("us")
        _endpoints_for("eu")
        assert before == ENDPOINTS
        assert ENDPOINTS["us"]["query"] == "https://mixpanel.com/api/query"

    def test_app_base_alone_overrides_only_app_family(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``MP_APP_BASE_URL`` on its own re-homes the App API and nothing else.

        Args:
            monkeypatch: pytest monkeypatch fixture.
        """
        monkeypatch.setenv("MP_APP_BASE_URL", "http://app.internal:9000/")
        table = _endpoints_for("eu")
        assert table["app"] == "http://app.internal:9000/api/app"
        for family in ("query", "export", "engage"):
            assert table[family] == ENDPOINTS["eu"][family]
        # The live table itself is untouched.
        assert ENDPOINTS["eu"]["app"] == "https://eu.mixpanel.com/api/app"

    def test_app_base_wins_over_api_base_for_app_family(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With both set, ``MP_APP_BASE_URL`` decides the App API host.

        Args:
            monkeypatch: pytest monkeypatch fixture.
        """
        monkeypatch.setenv("MP_API_BASE_URL", _BASE)
        monkeypatch.setenv("MP_APP_BASE_URL", "http://app.internal:9000")
        table = _endpoints_for("us")
        assert table["app"] == "http://app.internal:9000/api/app"
        assert table["query"] == _EXPECTED["query"]
        assert table["export"] == _EXPECTED["export"]
        assert table["engage"] == _EXPECTED["engage"]


# =============================================================================
# _build_url — read at request time
# =============================================================================


class TestBuildUrlUnderOverride:
    """``_build_url`` honours the override for every family, lazily."""

    @pytest.mark.parametrize("api_type", ["query", "export", "engage", "app"])
    def test_each_family_uses_prefix(
        self, api_type: str, us_session: Session, override_env: None
    ) -> None:
        """``_build_url(api_type, "/x")`` is ``{base}{prefix}/x``.

        Args:
            api_type: API family under test.
            us_session: US session fixture.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        client = MixpanelAPIClient(session=us_session)
        try:
            assert client._build_url(api_type, "/x") == f"{_EXPECTED[api_type]}/x"
        finally:
            client.close()

    def test_env_is_read_per_call_not_at_construction(
        self, us_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Setting the var after the client exists still redirects the next URL.

        Args:
            us_session: US session fixture.
            monkeypatch: pytest monkeypatch fixture.
        """
        client = MixpanelAPIClient(session=us_session)
        try:
            live = client._build_url("query", "/segmentation")
            assert live == "https://mixpanel.com/api/query/segmentation"
            monkeypatch.setenv("MP_API_BASE_URL", _BASE)
            assert (
                client._build_url("query", "/segmentation")
                == f"{_BASE}/api/query/segmentation"
            )
            monkeypatch.delenv("MP_API_BASE_URL")
            assert client._build_url("query", "/segmentation") == live
        finally:
            client.close()

    def test_eu_session_is_redirected_too(self, override_env: None) -> None:
        """A non-US session is routed at the same base (region is URL-irrelevant).

        Args:
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        client = MixpanelAPIClient(session=make_session(region="eu"))
        try:
            assert client._build_url("export", "/export") == f"{_BASE}/api/2.0/export"
        finally:
            client.close()


# =============================================================================
# Full request URL per family through the client
# =============================================================================


class TestClientRequestsHitOverride:
    """Each client family method sends its request to the override host."""

    def test_get_events_hits_query_prefix(
        self, us_session: Session, override_env: None
    ) -> None:
        """``get_events`` → ``{base}/api/query/events/names``.

        Args:
            us_session: US session fixture.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=us_session, _transport=httpx.MockTransport(recorder)
        ) as client:
            client.get_events()
        assert recorder.urls() == [f"{_BASE}/api/query/events/names"]
        _no_mixpanel_hosts(recorder)

    def test_export_events_hits_export_prefix(
        self, us_session: Session, override_env: None
    ) -> None:
        """``export_events`` → ``{base}/api/2.0/export``.

        Args:
            us_session: US session fixture.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=us_session, _transport=httpx.MockTransport(recorder)
        ) as client:
            rows = list(
                client.export_events(from_date="2024-01-01", to_date="2024-01-01")
            )
        assert len(rows) == 1
        assert recorder.urls() == [f"{_BASE}/api/2.0/export"]
        _no_mixpanel_hosts(recorder)

    def test_engage_stats_hits_engage_prefix(
        self, us_session: Session, override_env: None
    ) -> None:
        """``engage_stats`` → ``{base}/api/query/engage/stats``.

        Args:
            us_session: US session fixture.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=us_session, _transport=httpx.MockTransport(recorder)
        ) as client:
            client.engage_stats()
        assert recorder.urls() == [f"{_BASE}/api/query/engage/stats"]
        _no_mixpanel_hosts(recorder)

    def test_app_request_hits_app_prefix(
        self, us_session: Session, override_env: None
    ) -> None:
        """``app_request`` → ``{base}/api/app/...``.

        Args:
            us_session: US session fixture.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=us_session, _transport=httpx.MockTransport(recorder)
        ) as client:
            client.app_request("GET", "/projects/12345/dashboards")
        assert recorder.urls() == [f"{_BASE}/api/app/projects/12345/dashboards"]
        _no_mixpanel_hosts(recorder)

    def test_trailing_slash_base_yields_clean_urls(
        self, us_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``MP_API_BASE_URL=http://127.0.0.1:8080/`` produces no double slash.

        Args:
            us_session: US session fixture.
            monkeypatch: pytest monkeypatch fixture.
        """
        monkeypatch.setenv("MP_API_BASE_URL", f"{_BASE}/")
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=us_session, _transport=httpx.MockTransport(recorder)
        ) as client:
            client.get_events()
            client.app_request("GET", "/projects/12345/dashboards")
        assert recorder.urls() == [
            f"{_BASE}/api/query/events/names",
            f"{_BASE}/api/app/projects/12345/dashboards",
        ]
        for url in recorder.urls():
            assert "//api" not in url


# =============================================================================
# Timeout selection and workspace_id injection
# =============================================================================


class TestTimeoutSelectionUnderOverride:
    """Route-aware timeouts still key off the App-vs-Query family."""

    @staticmethod
    def _capture_client(session: Session, seen: dict[str, Any]) -> MixpanelAPIClient:
        """Build a client whose transport records the per-request timeout.

        Args:
            session: Session for the client.
            seen: Dict the handler writes the request timeout into.

        Returns:
            A client wired to the capturing MockTransport.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the timeout extension and answer 200.

            Args:
                request: The outgoing request.

            Returns:
                An empty-results 200 response.
            """
            seen["timeout"] = request.extensions.get("timeout")
            return httpx.Response(200, json={"results": []})

        return MixpanelAPIClient(
            session=session, _transport=httpx.MockTransport(handler)
        )

    def test_app_request_keeps_app_timeout(
        self, us_session: Session, override_env: None
    ) -> None:
        """App API requests at the override still get the App read timeout.

        Args:
            us_session: US session fixture.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        seen: dict[str, Any] = {}
        with self._capture_client(us_session, seen) as client:
            client.app_request("GET", "/projects/12345/dashboards")
        assert seen["timeout"]["read"] == DEFAULT_APP_TIMEOUT_S

    def test_query_request_keeps_query_timeout(
        self, us_session: Session, override_env: None
    ) -> None:
        """Query-family requests at the override get the Query read timeout.

        Args:
            us_session: US session fixture.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        seen: dict[str, Any] = {}
        with self._capture_client(us_session, seen) as client:
            client.get_events()
        assert seen["timeout"]["read"] == DEFAULT_QUERY_TIMEOUT_S
        with self._capture_client(us_session, seen) as client:
            client.request("GET", f"{_BASE}/api/query/segmentation")
        assert seen["timeout"]["read"] == DEFAULT_QUERY_TIMEOUT_S

    def test_split_app_host_still_selects_app_timeout(
        self, us_session: Session, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With ``MP_APP_BASE_URL`` set, App routes on the second host keep 135s.

        Args:
            us_session: US session fixture.
            monkeypatch: pytest monkeypatch fixture.
        """
        monkeypatch.setenv("MP_API_BASE_URL", _BASE)
        monkeypatch.setenv("MP_APP_BASE_URL", "http://app.internal:9000")
        seen: dict[str, Any] = {}
        with self._capture_client(us_session, seen) as client:
            client.app_request("GET", "/projects/12345/dashboards")
        assert seen["timeout"]["read"] == DEFAULT_APP_TIMEOUT_S


class TestWorkspaceIdInjectionUnderOverride:
    """``workspace_id`` injection keys off the Query family, not the host."""

    def test_pinned_query_request_carries_workspace_id(
        self, pinned_session: Session, override_env: None
    ) -> None:
        """A pinned workspace is injected on Query-family requests at the override.

        Args:
            pinned_session: Session with workspace 777 pinned.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=pinned_session, _transport=httpx.MockTransport(recorder)
        ) as client:
            client.get_events()
        params = recorder.requests[0].url.params
        assert params.get("workspace_id") == "777"
        assert params.get("project_id") == "12345"

    def test_pinned_app_request_does_not_carry_workspace_id(
        self, pinned_session: Session, override_env: None
    ) -> None:
        """App API requests are never given ``workspace_id`` (same as live).

        Args:
            pinned_session: Session with workspace 777 pinned.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=pinned_session, _transport=httpx.MockTransport(recorder)
        ) as client:
            client.app_request("GET", "/projects/12345/dashboards")
        assert "workspace_id" not in recorder.requests[0].url.params

    def test_unpinned_query_request_has_no_workspace_id(
        self, us_session: Session, override_env: None
    ) -> None:
        """No pin → no ``workspace_id`` param, exactly as live.

        Args:
            us_session: US session fixture.
            override_env: Exports ``MP_API_BASE_URL``.
        """
        del override_env
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=us_session, _transport=httpx.MockTransport(recorder)
        ) as client:
            client.get_events()
        assert "workspace_id" not in recorder.requests[0].url.params


# =============================================================================
# _api_family_for — longest-prefix family classification
# =============================================================================


class TestApiFamilyFor:
    """``_api_family_for`` picks the family whose base is the longest URL prefix."""

    @pytest.mark.parametrize(
        ("url", "family"),
        [
            ("https://mixpanel.com/api/query/insights", "query"),
            ("https://mixpanel.com/api/query/engage/", "engage"),
            ("https://mixpanel.com/api/query/engage/stats", "engage"),
            ("https://data.mixpanel.com/api/2.0/export", "export"),
            ("https://mixpanel.com/api/app/projects/1/dashboards", "app"),
            ("https://example.com/api/query/insights", None),
        ],
    )
    def test_live_table_classification(self, url: str, family: str | None) -> None:
        """Live URLs classify by their own family; engage beats query as a prefix.

        Args:
            url: The request URL.
            family: The expected family, or ``None`` for a foreign host.
        """
        assert _api_family_for(url, ENDPOINTS["us"]) == family

    def test_longest_prefix_wins_under_collision(self) -> None:
        """When one base is a prefix of another family's URL, the longer base wins."""
        table = {
            "query": "https://proxy/api/query",
            "export": "https://proxy/api/2.0",
            "engage": "https://proxy/api/query/engage",
            "app": "https://proxy/api/query/api/app",
        }
        assert _api_family_for("https://proxy/api/query/api/app/x", table) == "app"
        assert _api_family_for("https://proxy/api/query/insights", table) == "query"
        assert _api_family_for("https://proxy/api/query/engage/", table) == "engage"


class TestPrefixCollisionConfigs:
    """Split configs where one base is a prefix of another family stay correct."""

    @staticmethod
    def _seen_for(
        session: Session,
        call: str,
        monkeypatch: pytest.MonkeyPatch,
        env: dict[str, str],
    ) -> httpx.Request:
        """Issue one request under ``env`` and return it for inspection.

        Args:
            session: Session for the client (pinned to workspace 777).
            call: ``"app"`` to issue an App API GET, ``"query"`` for ``get_events``.
            monkeypatch: pytest monkeypatch fixture.
            env: Override variables to export for the call.

        Returns:
            The single captured ``httpx.Request``.
        """
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=session, _transport=httpx.MockTransport(recorder)
        ) as client:
            if call == "app":
                client.app_request("GET", "/projects/12345/dashboards")
            else:
                client.get_events()
        assert len(recorder.requests) == 1
        return recorder.requests[0]

    _APP_UNDER_QUERY = {
        "MP_API_BASE_URL": "https://proxy",
        "MP_APP_BASE_URL": "https://proxy/api/query",
    }
    """App base nested under the query prefix (reviewer config 1)."""

    _QUERY_UNDER_APP = {
        "MP_API_BASE_URL": "https://proxy/api/app",
        "MP_APP_BASE_URL": "https://proxy",
    }
    """Query prefix nested under the app base (the colliding reverse)."""

    _REVERSE_LITERAL = {
        "MP_API_BASE_URL": "https://proxy/api/query",
        "MP_APP_BASE_URL": "https://proxy",
    }
    """The literal reverse of config 1 (no textual overlap; must still be right)."""

    @pytest.mark.parametrize(
        "env", [_APP_UNDER_QUERY, _QUERY_UNDER_APP, _REVERSE_LITERAL]
    )
    def test_app_request_is_app_family(
        self,
        env: dict[str, str],
        pinned_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """App requests get the App timeout and no ``workspace_id`` in every config.

        Args:
            env: Override variables for the config under test.
            pinned_session: Session with workspace 777 pinned.
            monkeypatch: pytest monkeypatch fixture.
        """
        request = self._seen_for(pinned_session, "app", monkeypatch, env)
        assert request.url.path.endswith("/api/app/projects/12345/dashboards")
        assert request.extensions["timeout"]["read"] == DEFAULT_APP_TIMEOUT_S
        assert "workspace_id" not in request.url.params

    @pytest.mark.parametrize(
        "env", [_APP_UNDER_QUERY, _QUERY_UNDER_APP, _REVERSE_LITERAL]
    )
    def test_query_request_is_query_family(
        self,
        env: dict[str, str],
        pinned_session: Session,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Query requests get the Query timeout and carry ``workspace_id`` in every config.

        Args:
            env: Override variables for the config under test.
            pinned_session: Session with workspace 777 pinned.
            monkeypatch: pytest monkeypatch fixture.
        """
        request = self._seen_for(pinned_session, "query", monkeypatch, env)
        assert request.url.path.endswith("/api/query/events/names")
        assert request.extensions["timeout"]["read"] == DEFAULT_QUERY_TIMEOUT_S
        assert request.url.params.get("workspace_id") == "777"

    def test_live_engage_request_still_carries_workspace_id(
        self, pinned_session: Session
    ) -> None:
        """Unchanged live rule: Engage URLs are workspace-scoped like Query URLs.

        Args:
            pinned_session: Session with workspace 777 pinned.
        """
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=pinned_session, _transport=httpx.MockTransport(recorder)
        ) as client:
            client.engage_stats()
        request = recorder.requests[0]
        assert str(request.url).startswith(
            "https://mixpanel.com/api/query/engage/stats"
        )
        assert request.url.params.get("workspace_id") == "777"
        assert request.extensions["timeout"]["read"] == DEFAULT_QUERY_TIMEOUT_S


# =============================================================================
# Workspace() from env — the acceptance list
# =============================================================================


class TestWorkspaceFacadeHitsOverride:
    """``Workspace()`` built from env vars routes every facade call at the base."""

    def test_events(self, env_workspace: _Recorder) -> None:
        """``Workspace().events()`` → ``{base}/api/query/events/names``.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        with Workspace() as ws:
            assert ws.events() == ["Login"]
        assert env_workspace.urls() == [f"{_BASE}/api/query/events/names"]
        _no_mixpanel_hosts(env_workspace)

    def test_query(self, env_workspace: _Recorder) -> None:
        """``Workspace().query(...)`` → ``{base}/api/query/insights``.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        with Workspace() as ws:
            ws.query("Login", from_date="2025-01-01", to_date="2025-01-31")
        assert f"{_BASE}/api/query/insights" in env_workspace.urls()
        _no_mixpanel_hosts(env_workspace)

    def test_query_funnel(self, env_workspace: _Recorder) -> None:
        """``Workspace().query_funnel(...)`` → ``POST {base}/api/query/insights``.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        with Workspace() as ws:
            ws.query_funnel(
                ["Signup", "Purchase"], from_date="2025-01-01", to_date="2025-01-31"
            )
        assert env_workspace.urls() == [f"{_BASE}/api/query/insights"]
        assert env_workspace.requests[0].method == "POST"
        _no_mixpanel_hosts(env_workspace)

    def test_query_retention(self, env_workspace: _Recorder) -> None:
        """``Workspace().query_retention(...)`` → ``POST {base}/api/query/insights``.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        with Workspace() as ws:
            ws.query_retention(
                "Signup", "Login", from_date="2025-01-01", to_date="2025-01-31"
            )
        assert env_workspace.urls() == [f"{_BASE}/api/query/insights"]
        assert env_workspace.requests[0].method == "POST"
        _no_mixpanel_hosts(env_workspace)

    def test_legacy_funnel(self, env_workspace: _Recorder) -> None:
        """``Workspace().funnel(...)`` → ``{base}/api/query/funnels``.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        with Workspace() as ws:
            ws.funnel(1, from_date="2024-01-01", to_date="2024-01-01")
        assert f"{_BASE}/api/query/funnels" in env_workspace.urls()
        _no_mixpanel_hosts(env_workspace)

    def test_legacy_retention(self, env_workspace: _Recorder) -> None:
        """``Workspace().retention(...)`` → ``{base}/api/query/retention``.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        with Workspace() as ws:
            ws.retention(
                born_event="Signup",
                return_event="Login",
                from_date="2024-01-01",
                to_date="2024-01-01",
            )
        assert f"{_BASE}/api/query/retention" in env_workspace.urls()
        _no_mixpanel_hosts(env_workspace)

    def test_query_user_aggregate(self, env_workspace: _Recorder) -> None:
        """``Workspace().query_user(mode="aggregate")`` → engage ``stats``.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        with Workspace() as ws:
            ws.query_user(mode="aggregate", aggregate="count")
        assert f"{_BASE}/api/query/engage/stats" in env_workspace.urls()
        _no_mixpanel_hosts(env_workspace)

    def test_query_user_profiles(self, env_workspace: _Recorder) -> None:
        """``Workspace().query_user(mode="profiles")`` → ``{base}/api/query/engage/``.

        The trailing slash is the live shape too: the Engage root is built
        with ``_build_url("engage", "")``.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        with Workspace() as ws:
            ws.query_user(mode="profiles", limit=1)
        assert env_workspace.urls() == [f"{_BASE}/api/query/engage/"]
        _no_mixpanel_hosts(env_workspace)

    def test_stream_events(self, env_workspace: _Recorder) -> None:
        """``Workspace().stream_events(...)`` → ``{base}/api/2.0/export``.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        with Workspace() as ws:
            rows = list(ws.stream_events(from_date="2024-01-15", to_date="2024-01-15"))
        assert len(rows) == 1
        assert env_workspace.urls() == [f"{_BASE}/api/2.0/export"]
        _no_mixpanel_hosts(env_workspace)


# =============================================================================
# CLI inherits the override with no flag
# =============================================================================


class TestCliInheritsOverride:
    """The ``mp`` CLI shares the client, so the env var alone redirects it."""

    def test_mp_inspect_events_hits_override(self, env_workspace: _Recorder) -> None:
        """``mp inspect events`` with the var set queries the loopback base.

        Args:
            env_workspace: Recorder behind the env-resolved workspace.
        """
        from mixpanel_headless.cli.main import app

        result = CliRunner().invoke(app, ["inspect", "events"])
        assert result.exit_code == 0, result.output
        assert "Login" in result.output
        assert env_workspace.urls() == [f"{_BASE}/api/query/events/names"]
        _no_mixpanel_hosts(env_workspace)


# =============================================================================
# Unset → byte-identical live behaviour
# =============================================================================


class TestUnsetIsLive:
    """Without the var, URLs are exactly the live per-region hosts."""

    @pytest.mark.parametrize(
        ("region", "expected"),
        [
            ("us", "https://mixpanel.com/api/query/events/names"),
            ("eu", "https://eu.mixpanel.com/api/query/events/names"),
            ("in", "https://in.mixpanel.com/api/query/events/names"),
        ],
    )
    def test_query_url_matches_live_region(self, region: str, expected: str) -> None:
        """``get_events`` targets the region's live Query host when unset.

        Args:
            region: Region under test.
            expected: The live URL for that region.
        """
        recorder = _Recorder()
        with MixpanelAPIClient(
            session=make_session(region=region),
            _transport=httpx.MockTransport(recorder),
        ) as client:
            client.get_events()
        assert recorder.urls() == [expected]
