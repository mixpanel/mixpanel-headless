"""Unit tests for Workspace business context methods.

Covers all four facade methods plus the ``_resolve_organization_id``
and ``_cached_organization_id`` helpers. Each method delegates to
MixpanelAPIClient via httpx.MockTransport and returns typed
BusinessContext / BusinessContextChain instances.

Verifies:

- Project- and org-level GET / SET / CLEAR
- Org ID auto-resolution from /me cache (project lookup, sole-org fallback)
- Org ID explicit override (no /me fetch)
- Ambiguous-org raises WorkspaceScopeError
- Invalid ``level`` raises ValueError before any HTTP call
- 50,000-character boundary on set (client-side validation)
- Clear issues DELETE and returns an empty context
- Chain is built from one project GET (nested organization context), no /me fetch
- Chain populates org_id from cached /me on a best-effort basis
- Cold-cache chain leaves organization_id=None
- Per-region platform hosts and ``updated_at`` parsing
- RFC 9457 problem responses map onto the exception hierarchy
- Missing ``content`` / ``organization_business_context`` raises
  MixpanelHeadlessError instead of being silently treated as empty
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless._internal.auth.session import Session
from mixpanel_headless._internal.me import MeOrgInfo, MeProjectInfo, MeResponse
from mixpanel_headless.exceptions import (
    AuthenticationError,
    BusinessContextValidationError,
    MixpanelHeadlessError,
    QueryError,
    RateLimitError,
    WorkspaceScopeError,
)
from mixpanel_headless.types import (
    BUSINESS_CONTEXT_MAX_CHARS,
    BusinessContext,
    BusinessContextChain,
)
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session

# =============================================================================
# Helpers
# =============================================================================


def _session() -> Session:
    """Return a Session bound to test project 12345.

    Returns:
        A Session usable for ``MixpanelAPIClient(session=...)``.
    """
    return make_session(project_id="12345", region="us", oauth_token="test-token")


def _make_workspace(handler: Any) -> Workspace:
    """Build a Workspace whose API client routes through ``handler``.

    Args:
        handler: ``httpx.MockTransport`` handler accepting ``Request``.

    Returns:
        A Workspace wired to the mock transport.
    """
    sess = _session()
    transport = httpx.MockTransport(handler)
    client = MixpanelAPIClient(session=sess, _transport=transport)
    return Workspace(session=sess, _api_client=client)


def _stub_me(
    ws: Workspace,
    *,
    project_org: int | None = 100,
    extra_orgs: dict[str, int] | None = None,
    no_active_project: bool = False,
) -> None:
    """Pre-populate ``ws._me_service`` with a canned MeResponse.

    The stub implements both ``fetch()`` and ``peek()`` — ``fetch()``
    is what ``_resolve_organization_id`` calls, ``peek()`` is what
    ``_cached_organization_id`` (used by the chain endpoint) calls.

    Args:
        ws: Workspace whose MeService should be replaced.
        project_org: Owning organization ID for the active project
            (12345). Set to ``None`` to omit the project from the
            ``/me`` payload (forces fallback paths).
        extra_orgs: Additional ``{org_id: int_id}`` entries to add to
            ``MeResponse.organizations``. The active project's org is
            always present (when ``project_org`` is set) plus these.
        no_active_project: When True, omit the active project entirely
            (combine with empty ``extra_orgs`` to test ambiguous-org
            failure, or with one ``extra_orgs`` to test sole-org
            fallback).
    """

    class _StubMeSvc:
        """Minimal MeService stand-in returning a canned MeResponse."""

        def __init__(self, response: MeResponse) -> None:
            """Store the canned response."""
            self._response = response

        def fetch(self, *, force_refresh: bool = False) -> MeResponse:
            """Return the canned response (cache parameters ignored)."""
            del force_refresh
            return self._response

        def peek(self) -> MeResponse:
            """Return the canned response without triggering a fetch."""
            return self._response

    orgs: dict[str, MeOrgInfo] = {}
    projects: dict[str, MeProjectInfo] = {}

    if project_org is not None and not no_active_project:
        orgs[str(project_org)] = MeOrgInfo(id=project_org, name=f"Org {project_org}")
        projects["12345"] = MeProjectInfo(name="Active", organization_id=project_org)

    if extra_orgs:
        for key, oid in extra_orgs.items():
            orgs[key] = MeOrgInfo(id=oid, name=f"Org {oid}")

    response = MeResponse(organizations=orgs, projects=projects)
    ws._me_service = _StubMeSvc(response)  # type: ignore[assignment]


def _ok(body: dict[str, Any]) -> httpx.Response:
    """Build a 200 OK v1 Platform API response with a bare JSON ``body``."""
    return httpx.Response(200, json=body)


def _problem(status: int, title: str, **extra: Any) -> httpx.Response:
    """Build an RFC 9457 problem-details error response.

    Args:
        status: HTTP status code.
        title: Short problem title.
        **extra: Additional problem fields (``detail``, ``errors``, ...).

    Returns:
        An ``httpx.Response`` with the problem JSON body.
    """
    body: dict[str, Any] = {
        "type": None,
        "title": title,
        "status": status,
        "detail": None,
        "instance": None,
        "error_id": "err-1",
    }
    body.update(extra)
    return httpx.Response(status, json=body)


# =============================================================================
# Project-scoped GET
# =============================================================================


class TestGetBusinessContextProject:
    """get_business_context(level='project') behavior."""

    def test_returns_populated_context(self) -> None:
        """GET returns BusinessContext with project_id and content."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture URL + method, return canned content."""
            seen.append(f"{request.method} {request.url.path}")
            return _ok({"content": "# Project context\n\nHello."})

        ws = _make_workspace(handler)
        ctx = ws.get_business_context(level="project")

        assert isinstance(ctx, BusinessContext)
        assert ctx.level == "project"
        assert ctx.project_id == "12345"
        assert ctx.organization_id is None
        assert ctx.content == "# Project context\n\nHello."
        assert ctx.is_empty is False
        assert ctx.character_count == len("# Project context\n\nHello.")
        assert seen == ["GET /v1/projects/12345/business-context"]

    def test_default_level_is_project(self) -> None:
        """Calling without ``level`` defaults to 'project'."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return empty content."""
            del request
            return _ok({"content": ""})

        ws = _make_workspace(handler)
        ctx = ws.get_business_context()
        assert ctx.level == "project"
        assert ctx.is_empty is True

    def test_empty_content_yields_is_empty(self) -> None:
        """Empty string from API → BusinessContext.is_empty is True."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return the unset state."""
            del request
            return _ok({"content": ""})

        ws = _make_workspace(handler)
        ctx = ws.get_business_context(level="project")
        assert ctx.content == ""
        assert ctx.is_empty is True
        assert ctx.character_count == 0

    def test_invalid_level_raises_value_error(self) -> None:
        """``level="org"`` (or any other non-literal) raises ValueError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Should never run when validation rejects input."""
            del request
            raise AssertionError("HTTP must not be called for invalid level")

        ws = _make_workspace(handler)
        with pytest.raises(
            ValueError, match=r"level must be 'organization' or 'project'"
        ):
            ws.get_business_context(level="org")  # type: ignore[arg-type]

    def test_missing_content_raises_mixpanel_headless_error(self) -> None:
        """API response without ``content`` field → MixpanelHeadlessError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a malformed response (no ``content`` field)."""
            del request
            return _ok({"unexpected": "shape"})

        ws = _make_workspace(handler)
        with pytest.raises(MixpanelHeadlessError) as exc_info:
            ws.get_business_context(level="project")
        assert "missing required field 'content'" in str(exc_info.value)


# =============================================================================
# Project-scoped SET / CLEAR
# =============================================================================


class TestSetBusinessContextProject:
    """set_business_context(level='project') behavior."""

    def test_sends_put_with_correct_body(self) -> None:
        """SET issues PUT with ``{"content": ...}`` body."""
        seen: list[tuple[str, str, dict[str, Any]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture method, path, body and echo content back."""
            body: dict[str, Any] = json.loads(request.content)
            seen.append((request.method, request.url.path, body))
            return _ok({"content": body["content"]})

        ws = _make_workspace(handler)
        ctx = ws.set_business_context("# New content", level="project")

        assert ctx.level == "project"
        assert ctx.project_id == "12345"
        assert ctx.content == "# New content"
        assert seen == [
            (
                "PUT",
                "/v1/projects/12345/business-context",
                {"content": "# New content"},
            ),
        ]

    def test_validation_blocks_oversize_before_http(self) -> None:
        """50_001 chars → BusinessContextValidationError, no HTTP call."""
        called = False

        def handler(request: httpx.Request) -> httpx.Response:
            """Should never be called when validation rejects input."""
            del request
            nonlocal called
            called = True
            return _ok({"content": ""})

        ws = _make_workspace(handler)
        with pytest.raises(BusinessContextValidationError) as exc_info:
            ws.set_business_context("x" * (BUSINESS_CONTEXT_MAX_CHARS + 1))

        assert called is False
        details = exc_info.value.details
        assert details["length"] == BUSINESS_CONTEXT_MAX_CHARS + 1
        assert details["max"] == BUSINESS_CONTEXT_MAX_CHARS
        assert exc_info.value.code == "BUSINESS_CONTEXT_TOO_LONG"

    def test_exact_max_length_is_accepted(self) -> None:
        """Exactly 50,000 chars passes client-side validation."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Echo content back to caller."""
            body: dict[str, Any] = json.loads(request.content)
            return _ok({"content": body["content"]})

        ws = _make_workspace(handler)
        payload = "x" * BUSINESS_CONTEXT_MAX_CHARS
        ctx = ws.set_business_context(payload, level="project")
        assert ctx.character_count == BUSINESS_CONTEXT_MAX_CHARS

    def test_server_400_surfaces_as_query_error(self) -> None:
        """A 400 from the API is mapped to QueryError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return the server-side rejection shape."""
            del request
            return _problem(
                400,
                "Bad Request",
                detail="content exceeds maximum length of 50000 characters",
            )

        ws = _make_workspace(handler)
        with pytest.raises(QueryError):
            ws.set_business_context("# legal here", level="project")

    def test_invalid_level_raises_value_error_before_http(self) -> None:
        """``set`` with bogus ``level`` raises ValueError, no HTTP."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Should never run when validation rejects input."""
            del request
            raise AssertionError("HTTP must not be called for invalid level")

        ws = _make_workspace(handler)
        with pytest.raises(
            ValueError, match=r"level must be 'organization' or 'project'"
        ):
            ws.set_business_context("x", level="oops")  # type: ignore[arg-type]


class TestClearBusinessContextProject:
    """clear_business_context issues DELETE."""

    def test_clear_sends_delete_and_returns_empty(self) -> None:
        """CLEAR issues DELETE (204) and returns an empty project context."""
        seen: list[tuple[str, str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture method, host and path; return 204."""
            seen.append((request.method, request.url.host, request.url.path))
            return httpx.Response(204)

        ws = _make_workspace(handler)
        ctx = ws.clear_business_context(level="project")

        assert ctx.level == "project"
        assert ctx.project_id == "12345"
        assert ctx.is_empty is True
        assert ctx.updated_at is None
        assert seen == [
            (
                "DELETE",
                "platform-us.mixpanel.com",
                "/v1/projects/12345/business-context",
            )
        ]

    def test_clear_org_sends_delete(self) -> None:
        """Org CLEAR issues DELETE on the organization path."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture method and path; return 204."""
            seen.append(f"{request.method} {request.url.path}")
            return httpx.Response(204)

        ws = _make_workspace(handler)
        ctx = ws.clear_business_context(level="organization", organization_id=100)

        assert ctx.level == "organization"
        assert ctx.organization_id == 100
        assert ctx.is_empty is True
        assert seen == ["DELETE /v1/organizations/100/business-context"]


# =============================================================================
# Org-scoped GET / SET (with org-id resolution)
# =============================================================================


class TestGetBusinessContextOrganization:
    """get_business_context(level='organization') behavior."""

    def test_explicit_org_id_skips_me_fetch(self) -> None:
        """Passing organization_id avoids any /me lookup."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture URL and return canned org content."""
            seen.append(f"{request.method} {request.url.path}")
            return _ok({"content": "# Org content"})

        ws = _make_workspace(handler)

        class _ExplodingMeSvc:
            """Stand-in that raises if fetch() is called."""

            def fetch(self, *, force_refresh: bool = False) -> MeResponse:
                """Should never be invoked when organization_id is explicit."""
                del force_refresh
                raise AssertionError("MeService.fetch should not be called")

            def peek(self) -> MeResponse | None:
                """Should never be invoked for an explicit-org-id call."""
                raise AssertionError("MeService.peek should not be called")

        ws._me_service = _ExplodingMeSvc()  # type: ignore[assignment]

        ctx = ws.get_business_context(level="organization", organization_id=42)
        assert ctx.level == "organization"
        assert ctx.organization_id == 42
        assert ctx.project_id is None
        assert ctx.content == "# Org content"
        assert seen == ["GET /v1/organizations/42/business-context"]

    def test_auto_resolve_from_active_project(self) -> None:
        """Without explicit org_id, derives it from /me.projects[pid]."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture URL and return canned org content."""
            seen.append(request.url.path)
            return _ok({"content": "# Auto-resolved"})

        ws = _make_workspace(handler)
        _stub_me(ws, project_org=100)

        ctx = ws.get_business_context(level="organization")
        assert ctx.organization_id == 100
        assert seen == ["/v1/organizations/100/business-context"]

    def test_auto_resolve_falls_through_to_sole_org(self) -> None:
        """When project missing from /me but only one org exists, use it."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Return canned content."""
            seen.append(request.url.path)
            return _ok({"content": ""})

        ws = _make_workspace(handler)
        _stub_me(
            ws,
            project_org=None,
            extra_orgs={"77": 77},
            no_active_project=True,
        )

        ctx = ws.get_business_context(level="organization")
        assert ctx.organization_id == 77
        assert seen == ["/v1/organizations/77/business-context"]

    def test_ambiguous_org_raises_workspace_scope_error(self) -> None:
        """Multiple orgs + project not in /me → WorkspaceScopeError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Should never be called when resolution fails first."""
            del request
            raise AssertionError("HTTP call should not happen on resolution failure")

        ws = _make_workspace(handler)
        _stub_me(
            ws,
            project_org=None,
            extra_orgs={"1": 1, "2": 2},
            no_active_project=True,
        )

        with pytest.raises(WorkspaceScopeError) as exc_info:
            ws.get_business_context(level="organization")

        assert exc_info.value.code == "ORGANIZATION_AMBIGUOUS"
        assert exc_info.value.details["project_id"] == "12345"
        assert exc_info.value.details["available_organizations"] == ["1", "2"]


class TestSetBusinessContextOrganization:
    """set_business_context(level='organization') behavior."""

    def test_set_org_uses_org_path(self) -> None:
        """Org SET hits /organizations/{id}/business-context."""
        seen: list[tuple[str, str, dict[str, Any]]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture method, path, body."""
            body: dict[str, Any] = json.loads(request.content)
            seen.append((request.method, request.url.path, body))
            return _ok({"content": body["content"]})

        ws = _make_workspace(handler)
        ctx = ws.set_business_context(
            "# Org-wide",
            level="organization",
            organization_id=100,
        )

        assert ctx.level == "organization"
        assert ctx.organization_id == 100
        assert ctx.content == "# Org-wide"
        assert seen == [
            (
                "PUT",
                "/v1/organizations/100/business-context",
                {"content": "# Org-wide"},
            ),
        ]


# =============================================================================
# Chain endpoint
# =============================================================================


class TestGetBusinessContextChain:
    """get_business_context_chain() behavior."""

    @staticmethod
    def _project_body(
        project: str = "# Project info", org: str = "# Org info"
    ) -> dict[str, Any]:
        """Build a project GET body with a nested organization context.

        Args:
            project: Project-level content.
            org: Organization-level content.

        Returns:
            The bare v1 project GET response.
        """
        return {
            "content": project,
            "updated_at": "2026-01-02T03:04:05Z",
            "organization_business_context": {
                "content": org,
                "updated_at": None,
            },
        }

    def test_chain_parses_both_scopes(self) -> None:
        """Chain is built from one project GET with nested org context."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture URL, return both scopes."""
            seen.append(f"{request.method} {request.url.path}")
            return _ok(self._project_body())

        ws = _make_workspace(handler)
        _stub_me(ws, project_org=100)

        chain = ws.get_business_context_chain()

        assert isinstance(chain, BusinessContextChain)
        assert chain.organization.level == "organization"
        assert chain.organization.organization_id == 100
        assert chain.organization.content == "# Org info"
        assert chain.organization.updated_at is None
        assert chain.project.level == "project"
        assert chain.project.project_id == "12345"
        assert chain.project.content == "# Project info"
        assert chain.project.updated_at == datetime(
            2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc
        )
        assert seen == ["GET /v1/projects/12345/business-context"]

    def test_chain_with_empty_scopes(self) -> None:
        """Empty strings yield is_empty BusinessContexts."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return the unset state for both scopes."""
            del request
            return _ok(self._project_body("", ""))

        ws = _make_workspace(handler)
        _stub_me(ws, project_org=100)

        chain = ws.get_business_context_chain()
        assert chain.organization.is_empty is True
        assert chain.project.is_empty is True

    def test_chain_does_not_fetch_me_when_cache_cold(self) -> None:
        """Chain leaves organization_id=None when the /me cache is cold."""
        seen: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture method+path; fail if /me is reached."""
            seen.append(f"{request.method} {request.url.path}")
            if request.url.path.endswith("/me"):
                raise AssertionError("Chain must not trigger /me fetch")
            return _ok(self._project_body("# Project", "# Org"))

        ws = _make_workspace(handler)

        chain = ws.get_business_context_chain()
        assert chain.organization.organization_id is None
        assert chain.organization.content == "# Org"
        assert chain.project.content == "# Project"
        assert seen == ["GET /v1/projects/12345/business-context"]

    def test_chain_missing_nested_org_raises(self) -> None:
        """Response without ``organization_business_context`` raises."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a malformed response."""
            del request
            return _ok({"content": "# Project"})

        ws = _make_workspace(handler)
        with pytest.raises(MixpanelHeadlessError) as exc_info:
            ws.get_business_context_chain()
        assert "organization_business_context" in str(exc_info.value)

    def test_chain_missing_project_content_raises(self) -> None:
        """Response without ``content`` raises."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a malformed response."""
            del request
            return _ok({"organization_business_context": {"content": "# Org"}})

        ws = _make_workspace(handler)
        with pytest.raises(MixpanelHeadlessError) as exc_info:
            ws.get_business_context_chain()
        assert "missing required field 'content'" in str(exc_info.value)

    def test_chain_missing_nested_org_content_raises(self) -> None:
        """Nested org context without ``content`` raises."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a malformed nested org object."""
            del request
            return _ok({"content": "# P", "organization_business_context": {}})

        ws = _make_workspace(handler)
        with pytest.raises(MixpanelHeadlessError) as exc_info:
            ws.get_business_context_chain()
        assert "missing required field 'content'" in str(exc_info.value)


# =============================================================================
# Platform host, updated_at, and RFC 9457 errors
# =============================================================================


class TestPlatformHostAndErrors:
    """The v1 Platform API host per region, ``updated_at``, and problem errors."""

    @pytest.mark.parametrize(
        ("region", "host"),
        [
            ("us", "platform-us.mixpanel.com"),
            ("eu", "platform-eu.mixpanel.com"),
            ("in", "platform-in.mixpanel.com"),
        ],
    )
    def test_region_host(self, region: str, host: str) -> None:
        """Each region routes to its own platform host.

        Args:
            region: Account region.
            host: Expected request host.
        """
        seen: list[tuple[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Capture scheme and host."""
            seen.append((request.url.scheme, request.url.host))
            return _ok({"content": "", "updated_at": None})

        sess = make_session(project_id="12345", region=region, oauth_token="t")
        client = MixpanelAPIClient(
            session=sess, _transport=httpx.MockTransport(handler)
        )
        ws = Workspace(session=sess, _api_client=client)
        ws.get_business_context()
        assert seen == [("https", host)]

    def test_updated_at_parsed(self) -> None:
        """An ISO-8601 ``updated_at`` becomes a timezone-aware datetime."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return content with a timestamp."""
            del request
            return _ok({"content": "x", "updated_at": "2026-03-04T05:06:07+00:00"})

        ws = _make_workspace(handler)
        ctx = ws.get_business_context(level="organization", organization_id=1)
        assert ctx.updated_at == datetime(2026, 3, 4, 5, 6, 7, tzinfo=timezone.utc)

    def test_bad_updated_at_raises(self) -> None:
        """An unparseable ``updated_at`` raises MixpanelHeadlessError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a malformed timestamp."""
            del request
            return _ok({"content": "x", "updated_at": "not-a-date"})

        ws = _make_workspace(handler)
        with pytest.raises(MixpanelHeadlessError, match="updated_at"):
            ws.get_business_context()

    def test_bad_updated_at_chains_value_error(self) -> None:
        """A malformed ``updated_at`` string keeps the parse error as its cause."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a malformed timestamp."""
            del request
            return _ok({"content": "x", "updated_at": "not-a-date"})

        ws = _make_workspace(handler)
        with pytest.raises(MixpanelHeadlessError) as exc_info:
            ws.get_business_context()
        assert isinstance(exc_info.value.__cause__, ValueError)

    def test_422_surfaces_detail_and_errors(self) -> None:
        """A 422 problem maps to QueryError with detail, errors and error_id."""
        errors = [{"type": "string_too_long", "loc": ["body", "content"], "msg": "x"}]

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 422 problem."""
            del request
            return _problem(
                422, "Unprocessable Entity", detail="content too long", errors=errors
            )

        ws = _make_workspace(handler)
        with pytest.raises(QueryError) as exc_info:
            ws.set_business_context("ok")
        assert "content too long" in str(exc_info.value)
        assert exc_info.value.status_code == 422
        body = exc_info.value.response_body
        assert isinstance(body, dict)
        assert body["errors"] == errors
        assert body["error_id"] == "err-1"

    def test_400_falls_back_to_title(self) -> None:
        """A 400 problem without ``detail`` uses ``title`` as the message."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 400 problem with no detail."""
            del request
            return _problem(400, "Bad Request")

        ws = _make_workspace(handler)
        with pytest.raises(QueryError, match="Bad Request"):
            ws.get_business_context()

    def test_404_maps_to_query_error(self) -> None:
        """A 404 problem maps to QueryError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 404 problem."""
            del request
            return _problem(404, "Not Found", detail="no such project")

        ws = _make_workspace(handler)
        with pytest.raises(QueryError, match="no such project") as exc_info:
            ws.get_business_context()
        assert exc_info.value.status_code == 404

    def test_401_maps_to_authentication_error(self) -> None:
        """A 401 problem maps to AuthenticationError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 401 problem."""
            del request
            return _problem(401, "Unauthorized")

        ws = _make_workspace(handler)
        with pytest.raises(AuthenticationError):
            ws.get_business_context()

    def test_429_maps_to_rate_limit_error(self) -> None:
        """A 429 with a long Retry-After raises RateLimitError without sleeping."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 429 problem."""
            del request
            resp = _problem(429, "Too Many Requests")
            resp.headers["Retry-After"] = "3600"
            return resp

        ws = _make_workspace(handler)
        with pytest.raises(RateLimitError):
            ws.get_business_context()

    def test_delete_error_maps_to_query_error(self) -> None:
        """A 403 problem on DELETE maps to QueryError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 403 problem."""
            del request
            return _problem(403, "Forbidden", detail="needs edit permission")

        ws = _make_workspace(handler)
        with pytest.raises(QueryError, match="needs edit permission"):
            ws.clear_business_context()

    def test_non_object_get_body_raises(self) -> None:
        """A GET body that is not a JSON object raises MixpanelHeadlessError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a JSON array."""
            del request
            return httpx.Response(200, json=["unexpected"])

        ws = _make_workspace(handler)
        with pytest.raises(MixpanelHeadlessError, match="expected dict"):
            ws.get_business_context()

    def test_non_object_put_body_raises(self) -> None:
        """A PUT body that is not a JSON object raises MixpanelHeadlessError."""

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a JSON array."""
            del request
            return httpx.Response(200, json=["unexpected"])

        ws = _make_workspace(handler)
        with pytest.raises(MixpanelHeadlessError, match="expected dict"):
            ws.set_business_context("x")
