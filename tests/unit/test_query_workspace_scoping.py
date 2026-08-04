"""Failing-first tests for issue #198 — queries must honor the workspace pin.

An explicitly pinned workspace (``Session.workspace`` /
``set_workspace_id()`` / ``Workspace.use(workspace=...)``) must be
injected as a ``workspace_id`` query parameter on every Query-host
request (GET and POST) so Mixpanel data view filters apply. The
injection is EXPLICIT-ONLY: an unpinned session injects nothing and
triggers no workspace auto-resolution. Non-query hosts are unaffected:
the App API keeps its ``/workspaces/{id}/`` path scoping, and the
export host stays project-scoped by design.

Tests use ``httpx.MockTransport`` for deterministic HTTP mocking,
mirroring ``tests/unit/test_api_client.py`` and
``tests/unit/test_api_client_session.py``.
"""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.session import Session
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session

_PINNED_WORKSPACE_ID = 777


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Isolate ``$HOME`` and ``MP_CONFIG_PATH`` for hermetic tests.

    ``Workspace.use(...)`` constructs a :class:`ConfigManager` even for
    workspace-only swaps, so every test in this module must be walled
    off from the developer's real ``~/.mp/config.toml``.

    Args:
        tmp_path: pytest-provided temporary directory.
        monkeypatch: pytest monkeypatch fixture.
    """
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("MP_CONFIG_PATH", str(tmp_path / ".mp" / "config.toml"))


@pytest.fixture
def pinned_session() -> Session:
    """Return a Session with an explicitly pinned workspace.

    Returns:
        A ``Session`` whose ``workspace`` axis carries
        ``_PINNED_WORKSPACE_ID``, so ``MixpanelAPIClient`` treats the
        workspace as an explicit pin (``_workspace_id`` is set).
    """
    return make_session(
        username="test_user",
        secret="test_secret",
        project_id="12345",
        region="us",
        workspace_id=_PINNED_WORKSPACE_ID,
    )


@pytest.fixture
def unpinned_session() -> Session:
    """Return a Session with NO workspace pinned.

    Returns:
        A ``Session`` whose ``workspace`` axis is ``None`` (lazy).
    """
    return make_session(
        username="test_user",
        secret="test_secret",
        project_id="12345",
        region="us",
    )


def make_capture_client(
    session: Session,
    captured: list[httpx.Request],
    *,
    response_json: object = None,
    response_content: bytes | None = None,
) -> MixpanelAPIClient:
    """Create a client whose transport records every outgoing request.

    Args:
        session: The Session to bind the client to.
        captured: List that each outgoing ``httpx.Request`` is appended to.
        response_json: JSON body every response carries (used when
            ``response_content`` is None; defaults to an empty list).
        response_content: Raw byte body (e.g. JSONL for export streams).
            Mutually exclusive with ``response_json`` by construction.

    Returns:
        A ``MixpanelAPIClient`` wired to an ``httpx.MockTransport`` that
        captures requests and returns a canned 200 response.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request and return the canned 200 response.

        Args:
            request: The outgoing request under test.

        Returns:
            A 200 ``httpx.Response`` with the configured body.
        """
        captured.append(request)
        if response_content is not None:
            return httpx.Response(200, content=response_content)
        body = response_json if response_json is not None else []
        return httpx.Response(200, json=body)

    transport = httpx.MockTransport(handler)
    return MixpanelAPIClient(session=session, _transport=transport)


# =============================================================================
# Query host — workspace_id MUST be injected when a workspace is pinned
# (these tests FAIL against current main behavior; the fix makes them pass)
# =============================================================================


class TestQueryHostInjectionWhenPinned:
    """A pinned workspace scopes Query-host requests via ``workspace_id``."""

    def test_pinned_workspace_get_includes_workspace_id(
        self, pinned_session: Session
    ) -> None:
        """Query-host GET (``/events/names``) carries ``workspace_id``.

        Args:
            pinned_session: Session with workspace 777 pinned.
        """
        captured: list[httpx.Request] = []
        with make_capture_client(pinned_session, captured) as client:
            client.get_events()

        assert len(captured) == 1
        request = captured[0]
        assert "/api/query/events/names" in str(request.url)
        assert request.url.params.get("workspace_id") == str(_PINNED_WORKSPACE_ID)

    def test_pinned_workspace_post_includes_workspace_id(
        self, pinned_session: Session
    ) -> None:
        """Query-host POST (``insights_query``) carries ``workspace_id``.

        The pin rides in the query string; the server merges it with the
        JSON body (verified live against POST /insights).

        Args:
            pinned_session: Session with workspace 777 pinned.
        """
        captured: list[httpx.Request] = []
        client = make_capture_client(
            pinned_session,
            captured,
            response_json={"headers": [], "series": {}},
        )
        with client:
            client.insights_query({"bookmark": {}, "project_id": 12345})

        assert len(captured) == 1
        request = captured[0]
        assert request.method == "POST"
        assert "/api/query/insights" in str(request.url)
        assert request.url.params.get("workspace_id") == str(_PINNED_WORKSPACE_ID)

    def test_set_workspace_id_pin_scopes_subsequent_queries(
        self, unpinned_session: Session
    ) -> None:
        """``set_workspace_id(N)`` after construction scopes later queries.

        Args:
            unpinned_session: Session with no workspace pinned initially.
        """
        captured: list[httpx.Request] = []
        with make_capture_client(unpinned_session, captured) as client:
            client.set_workspace_id(_PINNED_WORKSPACE_ID)
            client.get_events()

        assert len(captured) == 1
        assert captured[0].url.params.get("workspace_id") == str(_PINNED_WORKSPACE_ID)


class TestInjectionOptOut:
    """``inject_workspace_id=False`` suppresses the pin per-request."""

    def test_inject_workspace_id_false_omits_param_even_when_pinned(
        self, pinned_session: Session
    ) -> None:
        """``_request(..., inject_workspace_id=False)`` sends no workspace_id.

        Currently fails with ``TypeError`` because the parameter does not
        exist yet — the fix adds it to ``_request``.

        Args:
            pinned_session: Session with workspace 777 pinned.
        """
        captured: list[httpx.Request] = []
        with make_capture_client(pinned_session, captured) as client:
            url = client._build_url("query", "/events/names")  # noqa: SLF001
            client._request(  # noqa: SLF001
                "GET",
                url,
                params={"type": "general"},
                inject_workspace_id=False,
            )

        assert len(captured) == 1
        assert "workspace_id" not in captured[0].url.params


# =============================================================================
# Guardrails — these tests PASS today and must KEEP passing after the fix
# =============================================================================


class TestNoWorkspacePinned:
    """Unpinned sessions inject nothing and never auto-resolve (passes today)."""

    def test_unpinned_query_has_no_workspace_id_and_no_discovery(
        self, unpinned_session: Session
    ) -> None:
        """No pin → no ``workspace_id`` param AND no auto-resolution call.

        EXPLICIT-ONLY gating: ``_request`` must never consult
        ``resolve_workspace_id()``, so exactly one request goes out and
        none touches a ``/workspaces`` discovery endpoint.

        Args:
            unpinned_session: Session with no workspace pinned.
        """
        captured: list[httpx.Request] = []
        with make_capture_client(unpinned_session, captured) as client:
            client.get_events()

        assert len(captured) == 1
        request = captured[0]
        assert "workspace_id" not in request.url.params
        assert "/workspaces" not in str(request.url)

    def test_caller_supplied_workspace_id_is_preserved(
        self, pinned_session: Session
    ) -> None:
        """A caller-supplied ``workspace_id`` param survives untouched.

        The fix uses ``params.setdefault(...)``, so an explicit value in
        ``params`` must win over the session pin — before AND after the
        fix this request carries exactly the caller's value.

        Args:
            pinned_session: Session with workspace 777 pinned.
        """
        captured: list[httpx.Request] = []
        with make_capture_client(pinned_session, captured) as client:
            url = client._build_url("query", "/events/names")  # noqa: SLF001
            client._request(  # noqa: SLF001
                "GET",
                url,
                params={"type": "general", "workspace_id": 111},
            )

        assert len(captured) == 1
        assert captured[0].url.params.get("workspace_id") == "111"


class TestNonQueryHostsUnaffected:
    """App API and export host never receive a ``workspace_id`` param."""

    def test_app_request_carries_no_workspace_id_param(
        self, pinned_session: Session
    ) -> None:
        """App API calls keep path scoping only — no query param (passes today).

        Args:
            pinned_session: Session with workspace 777 pinned.
        """
        captured: list[httpx.Request] = []
        client = make_capture_client(
            pinned_session, captured, response_json={"results": []}
        )
        with client:
            path = client.maybe_scoped_path("dashboards")
            assert path == f"/workspaces/{_PINNED_WORKSPACE_ID}/dashboards"
            client.app_request("GET", path)

        assert len(captured) == 1
        request = captured[0]
        assert f"/api/app/workspaces/{_PINNED_WORKSPACE_ID}/dashboards" in str(
            request.url
        )
        assert "workspace_id" not in request.url.params

    def test_export_stream_carries_no_workspace_id_param(
        self, pinned_session: Session
    ) -> None:
        """Export-host streaming stays project-scoped by design (passes today).

        Args:
            pinned_session: Session with workspace 777 pinned.
        """
        captured: list[httpx.Request] = []
        client = make_capture_client(
            pinned_session,
            captured,
            response_content=b'{"event":"A","properties":{"time":1}}\n',
        )
        with client:
            events = list(client.export_events("2024-01-01", "2024-01-31"))

        assert len(events) == 1
        assert len(captured) == 1
        request = captured[0]
        assert "data.mixpanel.com" in str(request.url)
        assert "workspace_id" not in request.url.params


class TestPinLifecycle:
    """Axis swaps that clear the pin must clear it at the request level."""

    def test_use_project_clears_pin_from_query_params(
        self, pinned_session: Session
    ) -> None:
        """``use(project=...)`` drops the pin → no ``workspace_id`` sent.

        Passes today (nothing is ever injected); after the fix it locks
        the request-level consequence of the pin-clearing behavior
        already covered by ``TestUseClearsStaleWorkspaceId``.

        Args:
            pinned_session: Session with workspace 777 pinned.
        """
        captured: list[httpx.Request] = []
        with make_capture_client(pinned_session, captured) as client:
            assert client._workspace_id == _PINNED_WORKSPACE_ID  # noqa: SLF001
            client.use(project="99999")
            client.get_events()

        assert len(captured) == 1
        assert "workspace_id" not in captured[0].url.params

    def test_zero_axis_use_clears_pin_from_query_params(
        self, pinned_session: Session
    ) -> None:
        """Zero-axis ``use()`` keeps the pin in lockstep with the session.

        ``use()`` with no axes clears ``session.workspace`` (the
        ``workspace=None`` argument reaches ``Session.replace``, which
        treats ``None`` as "clear"), so the int-id pin must be cleared
        too — otherwise subsequent Query-host requests silently carry a
        ``workspace_id`` that the session no longer holds.

        Args:
            pinned_session: Session with workspace 777 pinned.
        """
        captured: list[httpx.Request] = []
        with make_capture_client(pinned_session, captured) as client:
            assert client._workspace_id == _PINNED_WORKSPACE_ID  # noqa: SLF001
            client.use()
            assert client.session.workspace is None
            assert client._workspace_id is None  # noqa: SLF001
            client.get_events()

        assert len(captured) == 1
        assert "workspace_id" not in captured[0].url.params


# =============================================================================
# Workspace facade — ws.use(workspace=N) must scope subsequent discovery
# =============================================================================


class TestWorkspaceFacadeScoping:
    """``ws.use(workspace=N)`` scopes discovery/query calls (fails today)."""

    def test_use_workspace_then_discovery_call_sends_workspace_id(
        self, unpinned_session: Session
    ) -> None:
        """``ws.use(workspace=N)`` then ``ws.events()`` sends the pin.

        Args:
            unpinned_session: Session with no workspace pinned initially.
        """
        captured: list[httpx.Request] = []
        client = make_capture_client(unpinned_session, captured)
        ws = Workspace(session=unpinned_session, _api_client=client)
        with ws:
            ws.use(workspace=4242)
            ws.events()

        assert len(captured) == 1
        assert captured[0].url.params.get("workspace_id") == "4242"


class TestDiscoveryCacheAcrossUse:
    """Lock: ``Workspace.use(...)`` discards the discovery cache.

    Investigated for spec item 5: the staleness hazard is NOT real —
    ``Workspace.use()`` unconditionally sets ``self._discovery = None``,
    and ``DiscoveryService`` keeps its cache on the instance, so a
    workspace swap always rebuilds the service with an empty cache.
    This test locks that invariant (passes today, must keep passing).
    """

    def test_use_workspace_discards_cached_discovery_results(
        self, unpinned_session: Session
    ) -> None:
        """``ws.events()`` → ``use(workspace=N)`` → ``ws.events()`` refetches.

        Without the cache discard, the second ``events()`` would serve
        stale unscoped results from before the workspace swap.

        Args:
            unpinned_session: Session with no workspace pinned initially.
        """
        captured: list[httpx.Request] = []
        client = make_capture_client(unpinned_session, captured)
        ws = Workspace(session=unpinned_session, _api_client=client)
        with ws:
            ws.events()
            ws.events()
            # Cache hit: the repeat call must NOT issue a second request.
            assert len(captured) == 1

            ws.use(workspace=4242)
            ws.events()

        # The swap discarded the cache, so a fresh request went out.
        assert len(captured) == 2
