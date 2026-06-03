"""Tests for auto-workspace resolution (PR1).

Three layers:

- ``MeService.resolve_workspace`` / ``select_workspace_id`` — pick the best
  workspace id from cached ``/me`` data (prefer the global "All Project Data"
  view). Peek-only: a cold cache resolves to ``None``.
- ``MixpanelAPIClient.resolve_workspace_id`` — consults the injected ``/me``
  resolver first (so a redundant, uncached ``/workspaces/public`` call is
  avoided), then ``/workspaces/public``, then the ``/projects/metadata/index``
  service-account fallback, then raises.
- end to end through the ``Workspace`` facade (the resolver it installs, and its
  behavior across ``use()`` swaps).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import SecretStr

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session
from mixpanel_headless._internal.me import (
    MeCache,
    MeService,
    WorkspaceView,
    select_workspace_id,
)
from mixpanel_headless.exceptions import (
    AuthenticationError,
    RateLimitError,
    WorkspaceScopeError,
)
from mixpanel_headless.workspace import Workspace


def _me_dict(workspaces: dict[str, Any], projects: dict[str, Any]) -> dict[str, Any]:
    """Build a minimal raw /me response dict for mocking ``api_client.me()``.

    Args:
        workspaces: ``workspaces`` block, keyed by workspace ID.
        projects: ``projects`` block, keyed by project ID.

    Returns:
        A raw /me dict accepted by :meth:`MeResponse.model_validate`.
    """
    return {
        "user_id": 1,
        "user_email": "ak@example.com",
        "projects": projects,
        "workspaces": workspaces,
    }


def _ws(
    wid: int,
    *,
    project_id: int = 4025120,
    name: str = "view",
    is_default: bool | None = None,
    is_global: bool | None = None,
    is_visible: bool | None = None,
) -> dict[str, Any]:
    """Build a single ``/me`` workspace entry.

    Args:
        wid: Workspace ID.
        project_id: Parent project ID.
        name: Workspace name.
        is_default: Default-view flag.
        is_global: Global-view flag.
        is_visible: Visibility flag.

    Returns:
        A workspace dict for the ``workspaces`` block.
    """
    return {
        "id": wid,
        "name": name,
        "project_id": project_id,
        "is_default": is_default,
        "is_global": is_global,
        "is_visible": is_visible,
    }


class TestSelectWorkspaceId:
    """The shared selection ladder used by every resolution path."""

    def _v(self, **kw: Any) -> WorkspaceView:
        """Build a WorkspaceView with sensible defaults."""
        kw.setdefault("name", "v")
        kw.setdefault("is_global", None)
        kw.setdefault("is_default", None)
        kw.setdefault("is_visible", None)
        return WorkspaceView(**kw)

    def test_empty_is_none(self) -> None:
        """No views resolves to None."""
        assert select_workspace_id([]) is None

    def test_global_wins(self) -> None:
        """is_global beats default and name."""
        views = [
            self._v(id=1, is_default=True, name="All Project Data"),
            self._v(id=2, is_global=True),
        ]
        assert select_workspace_id(views) == 2

    def test_all_project_data_name_when_no_global(self) -> None:
        """The 'All Project Data' name wins when no global flag is set."""
        views = [self._v(id=1), self._v(id=2, name="All Project Data")]
        assert select_workspace_id(views) == 2

    def test_default_then_first_visible_then_first(self) -> None:
        """Falls through default -> first visible -> first."""
        assert select_workspace_id([self._v(id=1), self._v(id=2, is_default=True)]) == 2
        # no flags: is_visible None counts as visible, so the first is chosen
        assert select_workspace_id([self._v(id=5), self._v(id=6)]) == 5
        # an explicitly invisible first view is skipped for the next visible one
        assert (
            select_workspace_id(
                [self._v(id=7, is_visible=False), self._v(id=8, is_visible=True)]
            )
            == 8
        )
        # everything invisible: falls back to the first
        assert (
            select_workspace_id(
                [self._v(id=9, is_visible=False), self._v(id=10, is_visible=False)]
            )
            == 9
        )


class TestMeServiceResolveWorkspace:
    """``MeService.resolve_workspace`` reads the warm cache and selects."""

    @pytest.fixture
    def cache(self, tmp_path: Path) -> MeCache:
        """Return a MeCache pointed at a temp dir."""
        return MeCache(account_name="demo", storage_dir=tmp_path / "demo")

    def _service(self, cache: MeCache, raw: dict[str, Any]) -> MeService:
        """Build a MeService with a warm /me cache returning ``raw``.

        ``resolve_workspace`` is peek-only, so the cache is warmed via
        ``fetch()`` to mirror a session that has already loaded ``/me``.
        """
        api = MagicMock()
        api.me.return_value = raw
        svc = MeService(api, cache, "us")
        svc.fetch()
        return svc

    def test_resolves_global_view(self, cache: MeCache) -> None:
        """Picks the global view for the requested project."""
        raw = _me_dict(
            workspaces={
                "1": _ws(1, name="Console", is_default=True),
                "2": _ws(2, name="All Project Data", is_global=True),
            },
            projects={"4025120": {"name": "demo", "organization_id": 1}},
        )
        assert self._service(cache, raw).resolve_workspace("4025120") == 2

    def test_filters_by_project(self, cache: MeCache) -> None:
        """Only workspaces belonging to the requested project are considered."""
        raw = _me_dict(
            workspaces={
                "1": _ws(1, project_id=999, name="All Project Data", is_global=True),
                "2": _ws(2, project_id=4025120, name="mine", is_default=True),
            },
            projects={"4025120": {"name": "demo", "organization_id": 1}},
        )
        assert self._service(cache, raw).resolve_workspace("4025120") == 2

    def test_no_workspaces_for_project_is_none(self, cache: MeCache) -> None:
        """A project with no workspaces in /me resolves to None."""
        raw = _me_dict(
            workspaces={"9": _ws(9, project_id=999)},
            projects={"4025120": {"name": "demo", "organization_id": 1}},
        )
        assert self._service(cache, raw).resolve_workspace("4025120") is None

    def test_non_numeric_project_is_none(self, cache: MeCache) -> None:
        """A non-numeric project id resolves to None rather than raising."""
        raw = _me_dict(workspaces={}, projects={})
        assert self._service(cache, raw).resolve_workspace("not-a-number") is None

    def test_cold_cache_is_none_without_network(self, cache: MeCache) -> None:
        """A cold /me cache resolves to None and never calls the API."""
        api = MagicMock()
        svc = MeService(api, cache, "us")
        assert svc.resolve_workspace("4025120") is None
        api.me.assert_not_called()


def _session_no_ws(project_id: str = "4025120") -> Session:
    """Return a service-account Session with workspace unset (lazy)."""
    return Session(
        account=ServiceAccount(
            name="demo", region="us", username="u", secret=SecretStr("s")
        ),
        project=Project(id=project_id),
        workspace=None,
    )


class TestResolveWorkspaceIdWithResolver:
    """``MixpanelAPIClient.resolve_workspace_id`` resolution chain."""

    def test_resolver_hit_skips_public_endpoint(self) -> None:
        """When the /me resolver yields an id, /workspaces/public is never called."""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            return httpx.Response(200, json={"results": []})

        client = MixpanelAPIClient(
            session=_session_no_ws(), _transport=httpx.MockTransport(handler)
        )
        client.set_workspace_resolver(lambda _pid: 4521297)
        assert client.resolve_workspace_id() == 4521297
        assert not any("workspaces/public" in p for p in calls)

    def test_explicit_workspace_skips_resolver(self) -> None:
        """An explicit workspace id short-circuits before the resolver."""
        resolver = MagicMock()
        client = MixpanelAPIClient(session=_session_no_ws())
        client.set_workspace_id(4521297)
        client.set_workspace_resolver(resolver)
        assert client.resolve_workspace_id() == 4521297
        resolver.assert_not_called()

    def test_falls_back_to_public_when_resolver_returns_none(self) -> None:
        """A None resolution falls through to /workspaces/public (global view).

        The default and global flags are on different workspaces, so a result of
        11 proves the public path applies the global-first preference rather than
        the older default-first logic (which would have returned 10).
        """

        def handler(request: httpx.Request) -> httpx.Response:
            if "workspaces/public" in request.url.path:
                return httpx.Response(
                    200,
                    json=[
                        {
                            "id": 10,
                            "name": "Console",
                            "project_id": 4025120,
                            "is_default": True,
                        },
                        {
                            "id": 11,
                            "name": "All Project Data",
                            "project_id": 4025120,
                            "is_default": False,
                            "is_global": True,
                        },
                    ],
                )
            return httpx.Response(200, json={"results": []})

        client = MixpanelAPIClient(
            session=_session_no_ws(), _transport=httpx.MockTransport(handler)
        )
        client.set_workspace_resolver(lambda _pid: None)
        assert client.resolve_workspace_id() == 11

    def test_metadata_fallback_when_public_empty(self) -> None:
        """Empty /workspaces/public triggers the metadata-index fallback."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "workspaces/public" in request.url.path:
                return httpx.Response(200, json=[])
            if "metadata/index" in request.url.path:
                return httpx.Response(
                    200,
                    json={
                        "results": {
                            "4025120": {
                                "workspaces": {
                                    "4521297": {
                                        "id": 4521297,
                                        "name": "All Project Data",
                                        "is_default": True,
                                        "is_global": True,
                                    }
                                }
                            }
                        }
                    },
                )
            return httpx.Response(200, json={"results": []})

        client = MixpanelAPIClient(
            session=_session_no_ws(), _transport=httpx.MockTransport(handler)
        )
        assert client.resolve_workspace_id() == 4521297

    def test_raises_when_nothing_resolves(self) -> None:
        """No /me, empty public, empty metadata -> WorkspaceScopeError."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "metadata/index" in request.url.path:
                return httpx.Response(200, json={"results": {}})
            return httpx.Response(200, json=[])

        client = MixpanelAPIClient(
            session=_session_no_ws(), _transport=httpx.MockTransport(handler)
        )
        with pytest.raises(WorkspaceScopeError):
            client.resolve_workspace_id()

    def test_no_resolver_preserves_public_path(self) -> None:
        """Without a resolver installed, behavior matches the legacy public path."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json=[
                    {
                        "id": 55,
                        "name": "Default",
                        "project_id": 4025120,
                        "is_default": True,
                    }
                ],
            )

        client = MixpanelAPIClient(
            session=_session_no_ws(), _transport=httpx.MockTransport(handler)
        )
        assert client.resolve_workspace_id() == 55

    def test_maybe_scoped_path_stays_project_scoped_without_workspace(self) -> None:
        """Lexicon-style endpoints stay project-scoped when no workspace is set."""
        client = MixpanelAPIClient(session=_session_no_ws())
        assert client.maybe_scoped_path("data-definitions/events/") == (
            "/projects/4025120/data-definitions/events/"
        )


class TestProjectsMetadataIndex:
    """``projects_metadata_index`` + metadata-index resolution edge cases."""

    def _client(self, handler: Any) -> MixpanelAPIClient:
        """Build a client wired to a MockTransport ``handler``."""
        return MixpanelAPIClient(
            session=_session_no_ws(), _transport=httpx.MockTransport(handler)
        )

    def test_returns_project_keyed_mapping(self) -> None:
        """app_request unwraps the results envelope to the project-keyed map."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"results": {"4025120": {"name": "demo"}}})

        assert self._client(handler).projects_metadata_index() == {
            "4025120": {"name": "demo"}
        }

    def test_resolver_prefers_default_when_no_global(self) -> None:
        """The metadata fallback uses the shared ladder (default beats first)."""

        def handler(request: httpx.Request) -> httpx.Response:
            if "workspaces/public" in request.url.path:
                return httpx.Response(200, json=[])
            return httpx.Response(
                200,
                json={
                    "4025120": {
                        "workspaces": {
                            "1": {"id": 1, "name": "Console", "is_default": False},
                            "2": {"id": 2, "name": "Main", "is_default": True},
                        }
                    }
                },
            )

        assert self._client(handler).resolve_workspace_id() == 2

    def test_resolver_none_when_project_absent(self) -> None:
        """A metadata index lacking the project yields no fallback id."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"9999": {"workspaces": {}}})

        assert self._client(handler)._resolve_workspace_from_metadata() is None

    def test_resolver_none_when_workspaces_missing(self) -> None:
        """A project entry without a ``workspaces`` block yields no fallback id."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"4025120": {"name": "demo"}})

        assert self._client(handler)._resolve_workspace_from_metadata() is None

    def test_resolver_skips_non_numeric_ids(self) -> None:
        """A non-numeric workspace id is skipped, not crashed on."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "4025120": {
                        "workspaces": {
                            "bad": {"id": "not-an-int", "name": "x"},
                            "good": {"id": 42, "name": "y", "is_default": True},
                        }
                    }
                },
            )

        assert self._client(handler)._resolve_workspace_from_metadata() == 42

    def test_resolver_swallows_shape_errors(self) -> None:
        """A server error on the metadata index resolves to None (best-effort)."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(500, json={"error": "boom"})

        assert self._client(handler)._resolve_workspace_from_metadata() is None

    def test_resolver_none_when_all_ids_invalid(self) -> None:
        """A workspaces block where every entry is unusable yields no fallback id."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "4025120": {
                        "workspaces": {
                            "a": "not-a-dict",
                            "b": {"id": "nope", "name": "x"},
                        }
                    }
                },
            )

        assert self._client(handler)._resolve_workspace_from_metadata() is None

    def test_resolver_propagates_auth_error(self) -> None:
        """A 401 on the metadata index is surfaced, not masked as no-workspaces."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"error": "unauthorized"})

        with pytest.raises(AuthenticationError):
            self._client(handler)._resolve_workspace_from_metadata()

    def test_resolver_propagates_rate_limit_error(self) -> None:
        """A 429 on the metadata index is surfaced, not masked as no-workspaces."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(429, json={"error": "slow down"})

        client = MixpanelAPIClient(
            session=_session_no_ws(),
            _transport=httpx.MockTransport(handler),
            max_retries=0,
        )
        with pytest.raises(RateLimitError):
            client._resolve_workspace_from_metadata()


class TestFacadeResolverWiring:
    """End to end: the resolver the Workspace facade installs."""

    def _ws_session(self, project_id: str = "4025120") -> Session:
        """Service-account session for facade construction."""
        return Session(
            account=ServiceAccount(
                name="facade", region="us", username="u", secret=SecretStr("s")
            ),
            project=Project(id=project_id),
            workspace=None,
        )

    def _workspace(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path, handler: Any
    ) -> Workspace:
        """Build a Workspace with a MockTransport, isolating MeCache to tmp."""
        # MeCache writes under Path.home(); keep it off the real home dir.
        monkeypatch.setenv("HOME", str(tmp_path))
        session = self._ws_session()
        client = MixpanelAPIClient(
            session=session, _transport=httpx.MockTransport(handler)
        )
        return Workspace(session=session, _api_client=client)

    def test_resolves_from_me_cache_without_public_call(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A warm /me lets the facade resolve without hitting /workspaces/public."""
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path.endswith("/me"):
                return httpx.Response(
                    200,
                    json=_me_dict(
                        workspaces={
                            "2": _ws(
                                2,
                                project_id=4025120,
                                name="All Project Data",
                                is_global=True,
                            )
                        },
                        projects={"4025120": {"name": "demo", "organization_id": 1}},
                    ),
                )
            return httpx.Response(200, json={"results": []})

        ws = self._workspace(monkeypatch, tmp_path, handler)
        ws.me()  # warm the per-account /me cache (as `mp login` would)
        assert ws.api.resolve_workspace_id() == 2
        assert not any("workspaces/public" in p for p in calls)
        ws.close()

    def test_resolver_follows_project_swap(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """After use(project=...), the resolver selects the new project's view."""

        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("/me"):
                return httpx.Response(
                    200,
                    json=_me_dict(
                        workspaces={
                            "2": _ws(2, project_id=4025120, is_global=True),
                            "3": _ws(3, project_id=777, is_global=True),
                        },
                        projects={
                            "4025120": {"name": "a", "organization_id": 1},
                            "777": {"name": "b", "organization_id": 1},
                        },
                    ),
                )
            return httpx.Response(200, json={"results": []})

        ws = self._workspace(monkeypatch, tmp_path, handler)
        ws.me()
        assert ws.api.resolve_workspace_id() == 2
        ws.use(project="777")
        assert ws.api.resolve_workspace_id() == 3
        ws.close()

    def test_injected_client_resolver_not_overwritten(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """A resolver wired onto an injected client survives facade construction."""
        monkeypatch.setenv("HOME", str(tmp_path))
        session = self._ws_session()
        client = MixpanelAPIClient(
            session=session,
            _transport=httpx.MockTransport(lambda _r: httpx.Response(200, json=[])),
        )
        custom = MagicMock(return_value=99)
        client.set_workspace_resolver(custom)

        Workspace(session=session, _api_client=client)

        # Facade left the caller's resolver in place rather than clobbering it.
        assert client.resolve_workspace_id() == 99
        custom.assert_called_once()
