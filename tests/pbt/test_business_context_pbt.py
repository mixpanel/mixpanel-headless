"""Property-based tests for business context.

Locks down these invariants that must hold for arbitrary inputs:

1. ``Workspace.set_business_context(content)`` sends exactly
   ``{"content": content}`` to the project endpoint for any text
   payload up to ``BUSINESS_CONTEXT_MAX_CHARS`` chars.
2. Round-trip GET-after-SET (mocked echo) preserves the content
   verbatim across arbitrary unicode strings.
3. ``set_business_context`` rejects any content with
   ``len(content) > BUSINESS_CONTEXT_MAX_CHARS`` BEFORE making any
   HTTP call (the mock transport's request count stays at zero).
4. ``clear_business_context`` issues exactly one DELETE and returns an
   empty context, for either level and any organization ID.
"""

# ruff: noqa: ARG001, ARG005

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from mixpanel_headless._internal.api_client import MixpanelAPIClient
from mixpanel_headless.exceptions import BusinessContextValidationError
from mixpanel_headless.types import BUSINESS_CONTEXT_MAX_CHARS, BusinessContext
from mixpanel_headless.workspace import Workspace
from tests.conftest import make_session


def _build_workspace(handler: Any) -> Workspace:
    """Build a Workspace whose API client routes through ``handler``.

    Args:
        handler: ``httpx.MockTransport`` handler.

    Returns:
        Workspace bound to the mock transport with project 12345.
    """
    sess = make_session(project_id="12345", region="us", oauth_token="token")
    transport = httpx.MockTransport(handler)
    client = MixpanelAPIClient(session=sess, _transport=transport)
    return Workspace(session=sess, _api_client=client)


# Valid-content strategy: any unicode text up to the cap.
_valid_content = st.text(min_size=0, max_size=BUSINESS_CONTEXT_MAX_CHARS)


@given(content=_valid_content)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_set_sends_exact_content_body(content: str) -> None:
    """For any valid content, set sends ``{"content": <content>}``."""
    captured: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Capture body, echo content back."""
        body: dict[str, Any] = json.loads(request.content)
        captured.append(body)
        return httpx.Response(
            200, json={"content": body["content"], "updated_at": None}
        )

    ws = _build_workspace(handler)
    ws.set_business_context(content, level="project")
    assert captured == [{"content": content}]


@given(content=_valid_content)
@settings(
    max_examples=50,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_round_trip_preserves_content(content: str) -> None:
    """Echo handler: SET then GET returns the same content."""

    storage: dict[str, str] = {"content": ""}

    def handler(request: httpx.Request) -> httpx.Response:
        """Mock storage: PUT updates, GET returns current state."""
        if request.method == "PUT":
            body: dict[str, Any] = json.loads(request.content)
            storage["content"] = body["content"]
        return httpx.Response(
            200, json={"content": storage["content"], "updated_at": None}
        )

    ws = _build_workspace(handler)
    ws.set_business_context(content, level="project")
    fetched = ws.get_business_context(level="project")

    assert isinstance(fetched, BusinessContext)
    assert fetched.content == content
    assert fetched.character_count == len(content)


@given(
    overflow=st.integers(min_value=1, max_value=128),
)
@settings(
    max_examples=20,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
)
def test_oversize_content_blocks_http_call(overflow: int) -> None:
    """``len(content) > MAX`` raises BEFORE any HTTP request is made."""

    request_count = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        """Bump counter; should never run when validation rejects."""
        request_count["n"] += 1
        return httpx.Response(200, json={"content": "", "updated_at": None})

    ws = _build_workspace(handler)
    payload = "x" * (BUSINESS_CONTEXT_MAX_CHARS + overflow)

    with pytest.raises(BusinessContextValidationError) as exc_info:
        ws.set_business_context(payload, level="project")

    assert request_count["n"] == 0
    assert exc_info.value.details["length"] == len(payload)
    assert exc_info.value.details["max"] == BUSINESS_CONTEXT_MAX_CHARS


@given(
    level=st.sampled_from(["project", "organization"]),
    org_id=st.integers(min_value=1, max_value=10**9),
)
@settings(max_examples=20, deadline=None)
def test_clear_issues_single_delete_and_returns_empty(level: str, org_id: int) -> None:
    """Clear sends one DELETE to the level's path and returns an empty context."""
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record method and path; answer 204."""
        seen.append((request.method, request.url.path))
        return httpx.Response(204)

    ws = _build_workspace(handler)
    ctx = ws.clear_business_context(
        level=level,  # type: ignore[arg-type]
        organization_id=org_id,
    )

    expected = (
        f"/v1/organizations/{org_id}/business-context"
        if level == "organization"
        else "/v1/projects/12345/business-context"
    )
    assert seen == [("DELETE", expected)]
    assert ctx.is_empty
    assert ctx.updated_at is None
