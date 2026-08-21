"""Cursor-based pagination helper for Mixpanel App API.

Provides a generic paginator that follows cursor-based pagination
through App API responses. Used by domain-specific methods to iterate
through all pages of results.

This is a private implementation detail. Users should use the Workspace
class methods instead of accessing this module directly.
"""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import httpx

from mixpanel_headless.exceptions import (
    AuthenticationError,
    MixpanelHeadlessError,
    RateLimitError,
    ServerError,
)

if TYPE_CHECKING:
    from mixpanel_headless._internal.api_client import MixpanelAPIClient

logger = logging.getLogger(__name__)

#: Maximum number of pages to fetch before raising an error.
#: Prevents infinite loops when the server returns a non-null cursor indefinitely.
MAX_PAGES: int = 10000

#: Maximum number of retries for rate-limited (429) responses per page request.
MAX_RATE_LIMIT_RETRIES: int = 3

#: Base delay in seconds for exponential backoff on 429 retries.
_BACKOFF_BASE: float = 1.0

#: Maximum backoff delay in seconds.
_BACKOFF_MAX: float = 60.0


def _parse_retry_after(raw: str | None) -> float | None:
    """Parse a ``Retry-After`` header value into a safe number of seconds.

    The header is attacker- or bug-controlled input that would otherwise flow
    straight into ``time.sleep()``, which raises ``ValueError`` on negative and
    NaN values and ``OverflowError`` on infinity. Anything that is not a
    finite, non-negative number is rejected so callers can fall back to the
    exponential-backoff schedule.

    HTTP-date form (RFC 9110) is not supported and is treated as unparseable,
    matching the delta-seconds-only behaviour this module has always had.

    Args:
        raw: Raw header value, or ``None`` when the header is absent.

    Returns:
        The advertised delay in seconds, or ``None`` when the header is
        absent, empty, unparseable, negative, NaN, or infinite. The value is
        not capped — apply ``_BACKOFF_MAX`` at the point of sleeping.

    Example:
        ```python
        _parse_retry_after("30")    # 30.0
        _parse_retry_after("-1")    # None
        _parse_retry_after("inf")   # None
        ```
    """
    if not raw:
        return None
    try:
        seconds = float(raw)
    except ValueError:
        return None
    if not math.isfinite(seconds) or seconds < 0:
        return None
    return seconds


def paginate_all(
    client: MixpanelAPIClient,
    path: str,
    *,
    params: dict[str, str] | None = None,
    page_size: int = 100,
) -> Iterator[Any]:
    """Iterate through all pages of a paginated App API response.

    Makes repeated calls to ``client.app_request("GET", path, ...)`` following
    the ``next_cursor`` field in pagination metadata until all pages are
    exhausted.

    The App API returns paginated responses in this shape::

        {
            "status": "ok",
            "results": [...],
            "pagination": {
                "page_size": 100,
                "next_cursor": "abc123" | null
            }
        }

    Since ``app_request()`` unwraps the ``results`` field, this function
    makes a raw request to get the full response including pagination metadata.

    Args:
        client: MixpanelAPIClient instance to use for requests.
        path: App API path (e.g., ``/projects/12345/dashboards``).
        params: Optional additional query parameters to include in each request.
        page_size: Number of items per page (default 100).

    Yields:
        Individual items from across all pages of results.

    Raises:
        AuthenticationError: Invalid credentials (401).
        RateLimitError: Rate limit exceeded after max retries (429).
        ServerError: Server-side errors (5xx).
        MixpanelHeadlessError: Client errors (400, 404, 422), network/connection
            errors, pagination limit exceeded, or a malformed body (non-JSON,
            or a ``results`` field that is neither a list nor null).

    Example:
        ```python
        with MixpanelAPIClient(credentials) as client:
            all_dashboards = list(paginate_all(
                client,
                "/projects/12345/dashboards",
                page_size=50,
            ))
        ```
    """
    next_cursor: str | None = None
    page_count = 0

    while True:
        page_count += 1

        if page_count > MAX_PAGES:
            raise MixpanelHeadlessError(
                "Pagination exceeded maximum page limit",
                code="PAGINATION_LIMIT",
                details={"max_pages": MAX_PAGES, "path": path},
            )

        request_params: dict[str, str] = {"page_size": str(page_size)}
        if params:
            request_params.update(params)
        if next_cursor is not None:
            request_params["cursor"] = next_cursor
        # query_origin is canonical telemetry — set last so caller params can't override it
        request_params["query_origin"] = "mixpanel-headless"

        # Make the raw request to get full response with pagination
        url = client._build_url("app", path)
        auth_header = client._get_auth_header()
        headers = {"Authorization": auth_header}

        http_client = client._ensure_client()
        response: httpx.Response | None = None

        for attempt in range(MAX_RATE_LIMIT_RETRIES + 1):
            try:
                response = http_client.request(
                    "GET",
                    url,
                    params=request_params,
                    headers=headers,
                    timeout=client._default_timeout(url),
                )
            except httpx.HTTPError as exc:
                raise MixpanelHeadlessError(
                    f"Network error during pagination: {exc}",
                    code="NETWORK_ERROR",
                    details={"path": path, "error": str(exc)},
                ) from exc

            # Handle 429 with retry/backoff
            if response.status_code == 429:
                advertised = _parse_retry_after(response.headers.get("Retry-After"))
                if attempt >= MAX_RATE_LIMIT_RETRIES:
                    retry_after = None if advertised is None else int(advertised)
                    raise RateLimitError(
                        "Rate limit exceeded after max retries during pagination",
                        retry_after=retry_after,
                        status_code=429,
                        response_body=response.text,
                        request_method="GET",
                        request_url=url,
                    )
                # Honor a sane Retry-After, but never sleep longer than the
                # backoff cap — a server-advertised hour would hang the walk.
                if advertised is None:
                    wait_time = min(_BACKOFF_BASE * (2**attempt), _BACKOFF_MAX)
                else:
                    wait_time = min(advertised, _BACKOFF_MAX)
                logger.warning(
                    "Rate limited during pagination, retrying in %.1f seconds "
                    "(attempt %d/%d)",
                    wait_time,
                    attempt + 1,
                    MAX_RATE_LIMIT_RETRIES,
                )
                time.sleep(wait_time)
                continue

            # Not a 429 — break out of retry loop
            break

        # At this point response is guaranteed non-None
        assert response is not None  # noqa: S101

        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            body = exc.response.text
            if status == 401:
                raise AuthenticationError(
                    f"Authentication failed during pagination: {body}",
                    status_code=status,
                    response_body=body,
                    request_method="GET",
                    request_url=url,
                ) from exc
            if status >= 500:
                raise ServerError(
                    f"Server error during pagination: {body}",
                    status_code=status,
                    response_body=body,
                    request_method="GET",
                    request_url=url,
                ) from exc
            raise MixpanelHeadlessError(
                f"HTTP {status} during pagination: {body}",
                code="API_ERROR",
                details={"status_code": status, "response_body": body},
            ) from exc

        try:
            data = response.json()
        except Exception as exc:
            raise MixpanelHeadlessError(
                f"Non-JSON response during pagination (content-type: "
                f"{response.headers.get('content-type', 'unknown')})",
                code="INVALID_RESPONSE",
                details={"content_type": response.headers.get("content-type")},
            ) from exc

        # Extract results
        results: list[Any] = []
        if isinstance(data, dict):
            raw_results = data.get("results")
            if raw_results is None:
                # Absent key and explicit JSON null both mean "no items here";
                # the cursor, not this field, decides when iteration stops.
                results = []
            elif isinstance(raw_results, list):
                results = raw_results
            else:
                # Iterating a str would yield characters and a dict would yield
                # keys — corrupt output dressed up as success.
                raise MixpanelHeadlessError(
                    "Malformed paginated response: 'results' must be a list, got "
                    f"{type(raw_results).__name__}",
                    code="INVALID_RESPONSE",
                    details={"path": path, "results_type": type(raw_results).__name__},
                )
        elif isinstance(data, list):
            results = data

        yield from results

        # Check for next page
        pagination = data.get("pagination") if isinstance(data, dict) else None
        if pagination and isinstance(pagination, dict):
            next_cursor = pagination.get("next_cursor")
        else:
            next_cursor = None

        if next_cursor is None:
            break
