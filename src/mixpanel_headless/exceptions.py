"""Exception hierarchy for mixpanel_headless.

All library exceptions inherit from MixpanelHeadlessError, enabling callers to
catch all library errors with a single except clause while still allowing
fine-grained exception handling when needed.

The exception hierarchy is designed to help AI agents autonomously recover
from errors by providing structured access to:
- HTTP status codes and response bodies
- Original request context (method, URL, params, body)
- Parsed error details for common error patterns
- Structured validation errors with paths, suggestions, and fixes
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final, Literal
from urllib.parse import urlencode

if TYPE_CHECKING:
    from mixpanel_headless._internal.auth.account import Region


class MixpanelHeadlessError(Exception):
    """Base exception for all mixpanel_headless errors.

    All library exceptions inherit from this class, allowing callers to:
    - Catch all library errors: except MixpanelHeadlessError
    - Handle specific errors: except AccountNotFoundError
    - Serialize errors: error.to_dict()
    """

    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize exception.

        Args:
            message: Human-readable error message.
            code: Machine-readable error code for programmatic handling.
            details: Additional structured data about the error.
        """
        super().__init__(message)
        self._message = message
        self._code = code
        self._details = details or {}

    @property
    def code(self) -> str:
        """Machine-readable error code."""
        return self._code

    @property
    def message(self) -> str:
        """Human-readable error message."""
        return self._message

    @property
    def details(self) -> dict[str, Any]:
        """Additional structured error data."""
        return self._details

    def to_dict(self) -> dict[str, Any]:
        """Serialize exception for logging/JSON output.

        Returns:
            Dictionary with keys: code, message, details.
            All values are JSON-serializable.
        """
        return {
            "code": self._code,
            "message": self._message,
            "details": self._details,
        }

    def __str__(self) -> str:
        """Return human-readable error message."""
        return self._message

    def __repr__(self) -> str:
        """Return detailed string representation."""
        return (
            f"{self.__class__.__name__}(message={self._message!r}, code={self._code!r})"
        )


# Coded guard errors (E2 coding pass) - dual-inheritance domain errors that
# replace raw ``raise ValueError`` / ``raise TypeError`` argument guards while
# staying catchable as the original builtin (R5.5 registry-coded guards).


class ParamValidationError(MixpanelHeadlessError, ValueError):
    """A builder/facade argument guard rejected a value (registry-coded).

    Dual-inherits from :class:`MixpanelHeadlessError` and :class:`ValueError`
    so converted guard sites keep byte-identical messages and remain
    catchable by existing ``except ValueError`` handlers, while carrying a
    machine-readable registry ``.code`` for the conformance contract (R5.3).

    Example:
        ```python
        try:
            Filter.on("plan").in_the_last(0, "days")
        except ParamValidationError as exc:
            exc.code  # "FD1_QUANTITY_NOT_POSITIVE"
        ```
    """

    def __init__(
        self,
        message: str,
        code: str = "VALIDATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the coded guard error.

        Args:
            message: Human-readable error message (byte-identical to the
                pre-conversion builtin message at each converted site).
            code: Machine-readable registry code for the violated rule.
                Defaults to the generic ``VALIDATION_ERROR`` (R5.5
                construction-path fallback).
            details: Optional structured, deterministic, codec-encodable
                data about the error.
        """
        super().__init__(message, code=code, details=details)


class ParamTypeError(MixpanelHeadlessError, TypeError):
    """A builder/facade argument guard rejected a value's type (registry-coded).

    Dual-inherits from :class:`MixpanelHeadlessError` and :class:`TypeError`
    so converted guard sites keep byte-identical messages and remain
    catchable by existing ``except TypeError`` handlers, while carrying a
    machine-readable registry ``.code`` for the conformance contract (R5.3).
    """

    def __init__(
        self,
        message: str,
        code: str = "VALIDATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the coded guard error.

        Args:
            message: Human-readable error message (byte-identical to the
                pre-conversion builtin message at each converted site).
            code: Machine-readable registry code for the violated rule.
                Defaults to the generic ``VALIDATION_ERROR`` (R5.5
                construction-path fallback).
            details: Optional structured, deterministic, codec-encodable
                data about the error.
        """
        super().__init__(message, code=code, details=details)


class ResponseValidationError(MixpanelHeadlessError):
    """An API response failed Pydantic model validation.

    Raised at response-parsing seams when a Mixpanel API payload does not
    match the expected response model. Deliberately does NOT subclass
    ``ValueError`` (unlike ``pydantic.ValidationError``) — the wrap is a
    real, sanctioned behavior change recorded by ruling E2. The original
    pydantic error is chained via ``raise ... from exc``.
    """

    def __init__(
        self,
        message: str,
        code: str = "RESPONSE_VALIDATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the response validation error.

        Args:
            message: Human-readable error message.
            code: Machine-readable error code. Defaults to the generic
                ``RESPONSE_VALIDATION_ERROR`` (R5.5).
            details: Optional structured data — typically the response
                model name and ``pydantic`` error list.
        """
        super().__init__(message, code=code, details=details)


# API Exceptions - Base class for HTTP errors


class APIError(MixpanelHeadlessError):
    """Base class for Mixpanel API HTTP errors.

    Provides structured access to HTTP request/response context for debugging
    and automated recovery by AI agents. All API-related exceptions inherit
    from this class, enabling agents to:

    - Understand what went wrong (status code, error message)
    - See exactly what was sent (request method, URL, params, body)
    - See exactly what came back (response body, headers)
    - Modify their approach and retry autonomously

    Example:
        ```python
        try:
            result = client.segmentation(event="signup", ...)
        except APIError as e:
            print(f"Status: {e.status_code}")
            print(f"Response: {e.response_body}")
            print(f"Request URL: {e.request_url}")
            print(f"Request params: {e.request_params}")
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        response_body: str | dict[str, Any] | None = None,
        request_method: str | None = None,
        request_url: str | None = None,
        request_params: dict[str, Any] | None = None,
        request_body: dict[str, Any] | None = None,
        code: str = "API_ERROR",
    ) -> None:
        """Initialize APIError.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code from response.
            response_body: Raw response body (string or parsed dict).
            request_method: HTTP method used (GET, POST).
            request_url: Full request URL.
            request_params: Query parameters sent.
            request_body: Request body sent (for POST requests).
            code: Machine-readable error code.
        """
        self._status_code = status_code
        self._response_body = response_body
        self._request_method = request_method
        self._request_url = request_url
        self._request_params = request_params
        self._request_body = request_body

        details: dict[str, Any] = {
            "status_code": status_code,
        }
        if response_body is not None:
            details["response_body"] = response_body
        if request_method is not None:
            details["request_method"] = request_method
        if request_url is not None:
            details["request_url"] = request_url
        if request_params is not None:
            details["request_params"] = request_params
        if request_body is not None:
            details["request_body"] = request_body

        super().__init__(message, code=code, details=details)

    @property
    def status_code(self) -> int:
        """HTTP status code from response."""
        return self._status_code

    @property
    def response_body(self) -> str | dict[str, Any] | None:
        """Raw response body (string or parsed dict)."""
        return self._response_body

    @property
    def request_method(self) -> str | None:
        """HTTP method used (GET, POST)."""
        return self._request_method

    @property
    def request_url(self) -> str | None:
        """Full request URL."""
        return self._request_url

    @property
    def request_params(self) -> dict[str, Any] | None:
        """Query parameters sent."""
        return self._request_params

    @property
    def request_body(self) -> dict[str, Any] | None:
        """Request body sent (for POST requests)."""
        return self._request_body


# Configuration Exceptions


class ConfigError(MixpanelHeadlessError):
    """Base for configuration-related errors.

    Raised when there's a problem with configuration files, environment
    variables, or credential resolution.
    """

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize ConfigError.

        Args:
            message: Human-readable error message.
            details: Additional structured data.
        """
        super().__init__(message, code="CONFIG_ERROR", details=details)


class AccountNotFoundError(ConfigError):
    """Named account does not exist in configuration.

    Raised when attempting to access an account that hasn't been configured.
    The available_accounts property lists valid account names to help users.
    """

    def __init__(
        self,
        account_name: str,
        available_accounts: list[str] | None = None,
    ) -> None:
        """Initialize AccountNotFoundError.

        Args:
            account_name: The requested account name that wasn't found.
            available_accounts: List of valid account names for suggestions.
        """
        available = available_accounts or []
        if available:
            available_str = ", ".join(f"'{a}'" for a in available)
            message = (
                f"Account '{account_name}' not found. "
                f"Available accounts: {available_str}"
            )
        else:
            message = f"Account '{account_name}' not found. No accounts configured."

        details = {
            "account_name": account_name,
            "available_accounts": available,
        }
        super().__init__(message, details=details)
        self._code = "ACCOUNT_NOT_FOUND"

    @property
    def account_name(self) -> str:
        """The requested account name that wasn't found."""
        return str(self._details.get("account_name", ""))

    @property
    def available_accounts(self) -> list[str]:
        """List of valid account names."""
        accounts = self._details.get("available_accounts")
        return accounts if isinstance(accounts, list) else []


class ProjectNotFoundError(ConfigError):
    """Raised when a specified project is not accessible.

    Includes the requested project ID and optionally a list of
    accessible project IDs to help the user correct their selection.

    Example:
        ```python
        try:
            projects = ws.projects()
            match = [p for p in projects if p.id == target_id]
            if not match:
                raise ProjectNotFoundError(
                    target_id,
                    available_projects=[p.id for p in projects],
                )
        except ProjectNotFoundError as e:
            print(f"Project '{e.project_id}' not found.")
            if e.available_projects:
                print(f"Available: {', '.join(e.available_projects)}")
        ```
    """

    def __init__(
        self,
        project_id: str,
        available_projects: list[str] | None = None,
    ) -> None:
        """Initialize ProjectNotFoundError.

        Args:
            project_id: The requested project ID that wasn't found.
            available_projects: List of accessible project IDs for suggestions.
        """
        available = available_projects or []
        if available:
            available_str = ", ".join(f"'{p}'" for p in available)
            message = (
                f"Project '{project_id}' not found. Available projects: {available_str}"
            )
        else:
            message = (
                f"Project '{project_id}' not found. No accessible projects discovered."
            )

        details: dict[str, Any] = {
            "project_id": project_id,
            "available_projects": available,
        }
        super().__init__(message, details=details)
        self._code = "PROJECT_NOT_FOUND"

    @property
    def project_id(self) -> str:
        """The requested project ID that wasn't found."""
        return str(self._details.get("project_id", ""))

    @property
    def available_projects(self) -> list[str]:
        """List of accessible project IDs."""
        projects = self._details.get("available_projects")
        return projects if isinstance(projects, list) else []


class AccountExistsError(ConfigError):
    """Account name already exists in configuration.

    Raised when attempting to add an account with a name that's already in use.
    """

    def __init__(self, account_name: str) -> None:
        """Initialize AccountExistsError.

        Args:
            account_name: The conflicting account name.
        """
        message = f"Account '{account_name}' already exists."
        details = {"account_name": account_name}
        super().__init__(message, details=details)
        self._code = "ACCOUNT_EXISTS"

    @property
    def account_name(self) -> str:
        """The conflicting account name."""
        return str(self._details.get("account_name", ""))


class InvalidArgumentError(ConfigError):
    """Raised when a public API call combines mutually incompatible arguments.

    Carries a ``violation`` discriminator and the resolved
    ``detected_auth_type`` so non-CLI callers (Cowork's ``auth_manager.py``,
    JSON consumers) can dispatch programmatically without parsing the
    human message. The CLI ``handle_errors`` decorator maps this subclass
    to ``ExitCode.INVALID_ARGS`` (3) instead of the generic
    ``GENERAL_ERROR`` (1) that ``ConfigError`` would otherwise produce.

    Used by ``accounts.login_unified`` for the three documented
    flag-combination rejections (043 contract, ``cli-commands.md`` §5):
    ``--service-account`` + ``--token-env``, ``--no-browser`` against a
    non-browser auth type, and ``--secret-stdin`` against a non-SA
    auth type.

    Example:
        ```python
        try:
            accounts.login_unified(service_account=True, token_env="X")
        except InvalidArgumentError as exc:
            assert exc.violation == "mutually_exclusive"
            assert exc.detected_auth_type == "service_account"
        ```
    """

    _VALID_VIOLATIONS = (
        "mutually_exclusive",
        "no_browser_misuse",
        "secret_stdin_misuse",
    )

    def __init__(
        self,
        message: str,
        *,
        violation: Literal[
            "mutually_exclusive", "no_browser_misuse", "secret_stdin_misuse"
        ],
        detected_auth_type: str | None = None,
    ) -> None:
        """Initialize InvalidArgumentError.

        Args:
            message: Human-readable error message.
            violation: Discriminator for the kind of misuse. One of
                ``"mutually_exclusive"``, ``"no_browser_misuse"``,
                ``"secret_stdin_misuse"``.
            detected_auth_type: The auth type the orchestrator resolved
                from the supplied flags / env. ``None`` only when the
                violation was caught BEFORE detection ran (currently
                no such case, but kept optional for future-proofing).
        """
        if violation not in self._VALID_VIOLATIONS:
            raise ValueError(
                f"Invalid violation {violation!r}; must be one of "
                f"{self._VALID_VIOLATIONS}."
            )
        details: dict[str, Any] = {"violation": violation}
        if detected_auth_type is not None:
            details["detected_auth_type"] = detected_auth_type
        super().__init__(message, details=details)
        self._code = "INVALID_ARGUMENT"

    @property
    def violation(self) -> str:
        """The kind of misuse — see ``_VALID_VIOLATIONS``."""
        return str(self._details.get("violation", ""))

    @property
    def detected_auth_type(self) -> str | None:
        """The auth type the orchestrator resolved (or ``None`` if pre-detection)."""
        value = self._details.get("detected_auth_type")
        return str(value) if value is not None else None


class AccountInUseError(ConfigError):
    """Account is referenced by one or more targets and cannot be removed.

    Raised by ``mp.accounts.remove(name)`` when the account is referenced by
    one or more ``[targets.NAME]`` blocks and the caller did not pass
    ``force=True``. The list of dependent target names is available in
    ``referenced_by`` so callers can show a helpful error message or pass
    ``force=True`` to delete the account and orphan the targets.
    """

    def __init__(
        self, account_name: str, referenced_by: list[str] | None = None
    ) -> None:
        """Initialize AccountInUseError.

        Args:
            account_name: The account that callers tried to remove.
            referenced_by: Names of targets that reference the account.
        """
        targets = referenced_by or []
        if targets:
            target_str = ", ".join(f"'{t}'" for t in targets)
            message = (
                f"Account '{account_name}' is referenced by target(s): {target_str}. "
                f"Pass `force=True` to remove anyway."
            )
        else:
            message = (
                f"Account '{account_name}' is in use. Pass `force=True` to remove."
            )

        details: dict[str, Any] = {
            "account_name": account_name,
            "referenced_by": list(targets),
        }
        super().__init__(message, details=details)
        self._code = "ACCOUNT_IN_USE"

    @property
    def account_name(self) -> str:
        """The account name that callers tried to remove."""
        return str(self._details.get("account_name", ""))

    @property
    def referenced_by(self) -> list[str]:
        """Target names that reference the account."""
        targets = self._details.get("referenced_by")
        return targets if isinstance(targets, list) else []


# Authentication Exceptions


class AuthenticationError(APIError):
    """Authentication with Mixpanel API failed (HTTP 401).

    Raised when credentials are invalid, expired, or lack required permissions.
    Inherits from APIError to provide full request/response context.

    Example:
        ```python
        try:
            client.segmentation(...)
        except AuthenticationError as e:
            print(f"Auth failed: {e.message}")
            print(f"Request URL: {e.request_url}")
            # Check if project_id is correct, credentials are valid, etc.
        ```
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        *,
        status_code: int = 401,
        response_body: str | dict[str, Any] | None = None,
        request_method: str | None = None,
        request_url: str | None = None,
        request_params: dict[str, Any] | None = None,
        request_body: dict[str, Any] | None = None,
    ) -> None:
        """Initialize AuthenticationError.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code (default 401).
            response_body: Raw response body.
            request_method: HTTP method used.
            request_url: Full request URL.
            request_params: Query parameters sent.
            request_body: Request body sent (for POST/PATCH requests), so a
                401 carries the same context as the other error branches.
        """
        super().__init__(
            message,
            status_code=status_code,
            response_body=response_body,
            request_method=request_method,
            request_url=request_url,
            request_params=request_params,
            request_body=request_body,
            code="AUTH_FAILED",
        )


# Rate Limit Exceptions

# Rate-limit lead-collection form. Short forms.gle links can't carry prefill
# query params, so the long-form URL is used whenever the project_id is known.
_RATE_LIMIT_FORM_SHORT_URL = "https://forms.gle/7Y9UcUHe69bh8EgC7"
_RATE_LIMIT_FORM_PREFILL_BASE = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLSe8h0ZpB-V3zoK9qeUnUeh7vCs2lvP1IJ6IYMAiayHJ4g5LQA/viewform"
)
_RATE_LIMIT_FORM_PROJECT_FIELD = "entry.1636741534"


def _build_rate_limit_form_url(project_id: str | None) -> str:
    """Build the URL to the rate-limit-increase request form.

    When ``project_id`` is known, returns the long-form Google Form URL with
    the project id prefilled, so inbound leads arrive attributed to a project.
    Short ``forms.gle`` links cannot carry prefill query params, so the short
    link is used only as the no-project fallback.

    Args:
        project_id: Active Mixpanel project id, or ``None``/empty when unknown.

    Returns:
        The project-prefilled long-form URL when ``project_id`` is truthy,
        otherwise the short form link.

    Example:
        ```python
        _build_rate_limit_form_url("3018488")
        # ".../viewform?usp=pp_url&entry.1636741534=3018488"
        _build_rate_limit_form_url(None)
        # "https://forms.gle/7Y9UcUHe69bh8EgC7"
        ```
    """
    if not project_id:
        return _RATE_LIMIT_FORM_SHORT_URL
    query = urlencode({"usp": "pp_url", _RATE_LIMIT_FORM_PROJECT_FIELD: project_id})
    return f"{_RATE_LIMIT_FORM_PREFILL_BASE}?{query}"


class RateLimitError(APIError):
    """Mixpanel API rate limit exceeded (HTTP 429).

    Raised when the API returns a 429 status. The retry_after property
    indicates when the request can be retried. Inherits from APIError
    to provide full request context for debugging.

    Example:
        ```python
        try:
            for _ in range(1000):
                client.segmentation(...)
        except RateLimitError as e:
            print(f"Rate limited! Retry after {e.retry_after}s")
            print(f"Request: {e.request_method} {e.request_url}")
            print(f"Request a higher limit: {e.rate_limit_form_url}")
            time.sleep(e.retry_after or 60)
        ```
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        *,
        retry_after: int | None = None,
        status_code: int = 429,
        response_body: str | dict[str, Any] | None = None,
        request_method: str | None = None,
        request_url: str | None = None,
        request_params: dict[str, Any] | None = None,
        project_id: str | None = None,
    ) -> None:
        """Initialize RateLimitError.

        Args:
            message: Human-readable error message.
            retry_after: Seconds until retry is allowed (from Retry-After header).
            status_code: HTTP status code (default 429).
            response_body: Raw response body.
            request_method: HTTP method used.
            request_url: Full request URL.
            request_params: Query parameters sent.
            project_id: Mixpanel project id active when the limit was hit, used
                to prefill the rate-limit-increase request form. ``None`` when
                unknown.
        """
        self._retry_after = retry_after
        self._project_id = project_id
        if retry_after is not None:
            message = f"{message}. Retry after {retry_after} seconds."

        super().__init__(
            message,
            status_code=status_code,
            response_body=response_body,
            request_method=request_method,
            request_url=request_url,
            request_params=request_params,
            code="RATE_LIMITED",
        )
        # Add retry_after to details
        if retry_after is not None:
            self._details["retry_after"] = retry_after
        # Add project_id to details so JSON consumers (to_dict) can attribute it.
        if project_id is not None:
            self._details["project_id"] = project_id

    @property
    def retry_after(self) -> int | None:
        """Seconds until retry is allowed, or None if unknown."""
        return self._retry_after

    @property
    def project_id(self) -> str | None:
        """Mixpanel project id active when the rate limit was hit, if known."""
        return self._project_id

    @property
    def rate_limit_form_url(self) -> str:
        """URL to request a rate-limit increase.

        Returns the project-prefilled Google Form URL when the project id is
        known (so the lead is attributed to a project), otherwise the short
        form link. Handy for surfacing in scripts or notebooks that catch this
        error.

        Returns:
            The rate-limit-increase request form URL.
        """
        return _build_rate_limit_form_url(self._project_id)


# Query Exceptions


class EventNotFoundError(MixpanelHeadlessError):
    """Event name not found in Mixpanel project.

    Raised when an event name is not found. Includes suggestions for
    similar event names based on case-insensitive and substring matching
    to help users correct typos or case mismatches.

    Example:
        ```python
        try:
            properties = discovery.list_properties("sign up")
        except EventNotFoundError as e:
            print(f"Event '{e.event_name}' not found.")
            if e.similar_events:
                print(f"Did you mean: {', '.join(e.similar_events)}")
        ```
    """

    def __init__(
        self,
        event_name: str,
        similar_events: list[str] | None = None,
    ) -> None:
        """Initialize EventNotFoundError.

        Args:
            event_name: The event name that was not found.
            similar_events: List of similar event names to suggest.
        """
        self._event_name = event_name
        self._similar_events = similar_events or []

        message = f"Event '{event_name}' not found."
        if self._similar_events:
            suggestions = ", ".join(f"'{e}'" for e in self._similar_events[:5])
            message += f" Did you mean: {suggestions}?"

        details: dict[str, Any] = {
            "event_name": event_name,
            "similar_events": self._similar_events,
        }

        super().__init__(message, code="EVENT_NOT_FOUND", details=details)

    @property
    def event_name(self) -> str:
        """The event name that was not found."""
        return self._event_name

    @property
    def similar_events(self) -> list[str]:
        """List of similar event names."""
        return self._similar_events


class QueryError(APIError):
    """Query execution failed (HTTP 400 or query-specific error).

    Raised when an API query fails due to invalid parameters, syntax errors,
    or other query-specific issues. Inherits from APIError to provide full
    request/response context for debugging.

    Example:
        ```python
        try:
            client.segmentation(event="nonexistent", ...)
        except QueryError as e:
            print(f"Query failed: {e.message}")
            print(f"Response: {e.response_body}")
            print(f"Request params: {e.request_params}")
        ```
    """

    def __init__(
        self,
        message: str = "Query execution failed",
        *,
        status_code: int = 400,
        response_body: str | dict[str, Any] | None = None,
        request_method: str | None = None,
        request_url: str | None = None,
        request_params: dict[str, Any] | None = None,
        request_body: dict[str, Any] | None = None,
    ) -> None:
        """Initialize QueryError.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code (default 400).
            response_body: Raw response body with error details.
            request_method: HTTP method used.
            request_url: Full request URL.
            request_params: Query parameters sent.
            request_body: Request body sent (for POST).
        """
        super().__init__(
            message,
            status_code=status_code,
            response_body=response_body,
            request_method=request_method,
            request_url=request_url,
            request_params=request_params,
            request_body=request_body,
            code="QUERY_FAILED",
        )


class ServerError(APIError):
    """Mixpanel server error (HTTP 5xx).

    Raised when the Mixpanel API returns a server error. These are typically
    transient issues that may succeed on retry. The response_body property
    contains the full error details from Mixpanel, which often include
    actionable information (e.g., "unit and interval both specified").

    Example:
        ```python
        try:
            client.retention(born_event="signup", ...)
        except ServerError as e:
            print(f"Server error {e.status_code}: {e.message}")
            print(f"Response: {e.response_body}")
            print(f"Request params: {e.request_params}")
            # AI agent can analyze response_body to fix the request
        ```
    """

    def __init__(
        self,
        message: str = "Server error",
        *,
        status_code: int = 500,
        response_body: str | dict[str, Any] | None = None,
        request_method: str | None = None,
        request_url: str | None = None,
        request_params: dict[str, Any] | None = None,
        request_body: dict[str, Any] | None = None,
    ) -> None:
        """Initialize ServerError.

        Args:
            message: Human-readable error message.
            status_code: HTTP status code (5xx).
            response_body: Raw response body with error details.
            request_method: HTTP method used.
            request_url: Full request URL.
            request_params: Query parameters sent.
            request_body: Request body sent (for POST).
        """
        super().__init__(
            message,
            status_code=status_code,
            response_body=response_body,
            request_method=request_method,
            request_url=request_url,
            request_params=request_params,
            request_body=request_body,
            code="SERVER_ERROR",
        )


# Validation Exceptions


class DateRangeTooLargeError(MixpanelHeadlessError):
    """Date range exceeds maximum allowed by Mixpanel API.

    The Mixpanel Export API limits requests to 100 days maximum.
    Split large date ranges into smaller chunks.

    Example:
        ```python
        try:
            events = ws.stream_events(from_date="2024-01-01", to_date="2024-06-30")
        except DateRangeTooLargeError as e:
            print(f"Range is {e.days_requested} days, max is {e.max_days}")
        ```
    """

    def __init__(
        self,
        from_date: str,
        to_date: str,
        days_requested: int,
        max_days: int = 100,
    ) -> None:
        """Initialize DateRangeTooLargeError.

        Args:
            from_date: Start date that was requested.
            to_date: End date that was requested.
            days_requested: Number of days in the requested range.
            max_days: Maximum allowed days (default: 100).
        """
        self._from_date = from_date
        self._to_date = to_date
        self._days_requested = days_requested
        self._max_days = max_days

        message = (
            f"Date range from {from_date} to {to_date} spans {days_requested} days, "
            f"but maximum is {max_days} days. Split your request into smaller chunks."
        )

        details: dict[str, Any] = {
            "from_date": from_date,
            "to_date": to_date,
            "days_requested": days_requested,
            "max_days": max_days,
        }

        super().__init__(message, code="DATE_RANGE_TOO_LARGE", details=details)

    @property
    def from_date(self) -> str:
        """Start date that was requested."""
        return self._from_date

    @property
    def to_date(self) -> str:
        """End date that was requested."""
        return self._to_date

    @property
    def days_requested(self) -> int:
        """Number of days in the requested range."""
        return self._days_requested

    @property
    def max_days(self) -> int:
        """Maximum allowed days."""
        return self._max_days


# OAuth Exceptions


class OAuthError(MixpanelHeadlessError):
    """OAuth authentication flow error.

    Raised for failures during the OAuth 2.0 PKCE flow, including token
    exchange, token refresh, client registration, callback timeout,
    port unavailability, and browser launch failures.

    Error codes:
    - OAUTH_TOKEN_ERROR: Token exchange or validation failed
    - OAUTH_REFRESH_ERROR: Token refresh failed
    - OAUTH_REGISTRATION_ERROR: Dynamic Client Registration failed
    - OAUTH_TIMEOUT: Callback server timed out waiting for authorization
    - OAUTH_PORT_ERROR: All callback ports are occupied
    - OAUTH_BROWSER_ERROR: Could not open browser for authorization

    Example:
        ```python
        try:
            flow = OAuthFlow(region="us")
            tokens = flow.login()
        except OAuthError as e:
            print(f"OAuth failed: {e.message} (code: {e.code})")
        ```
    """

    def __init__(
        self,
        message: str,
        code: str = "OAUTH_TOKEN_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize OAuthError.

        Args:
            message: Human-readable error message.
            code: Machine-readable error code. One of: OAUTH_TOKEN_ERROR,
                OAUTH_REFRESH_ERROR, OAUTH_REGISTRATION_ERROR, OAUTH_TIMEOUT,
                OAUTH_PORT_ERROR, OAUTH_BROWSER_ERROR.
            details: Additional structured data about the error.
        """
        super().__init__(message, code=code, details=details)


class RegionProbeError(OAuthError):
    """Raised when no region accepts the credential during region probing.

    The region probe walks a configured order (default ``us`` → ``eu`` →
    ``in``) against ``/api/app/me``, returning the first 200. When every
    probe attempt fails, this exception is raised carrying the full
    attempt list for diagnostic and telemetry use.

    A status code of ``0`` indicates the request never reached the server
    (network error); the third tuple element carries the failure detail
    (HTTP response text or the network error reason).

    See :class:`RegionProbeNetworkError` for the all-network-error
    subclass — the probe distinguishes "credential rejected" from
    "could not reach any region" so the CLI can render different
    remediation hints.

    Example:
        ```python
        try:
            result = probe_region(client_factory, headers)
        except RegionProbeError as exc:
            for region, status, body in exc.attempts:
                print(f"{region}: {status} {body}")
        ```
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: list[tuple[Region, int, str]],
        code: str = "OAUTH_REGION_PROBE_FAILED",
    ) -> None:
        """Initialize RegionProbeError.

        Args:
            message: Human-readable error message.
            attempts: Ordered list of ``(region, status_code, error_body)``
                tuples for every probed region. ``status_code`` is ``0``
                for network errors; ``error_body`` carries the failure
                detail.
            code: Machine-readable error code. Defaults to
                ``OAUTH_REGION_PROBE_FAILED`` for the generic case;
                :class:`RegionProbeNetworkError` overrides to
                ``OAUTH_NETWORK_UNREACHABLE``.
        """
        self._attempts: list[tuple[Region, int, str]] = list(attempts)
        super().__init__(
            message,
            code=code,
            details={"attempts": [list(a) for a in self._attempts]},
        )

    @property
    def attempts(self) -> list[tuple[Region, int, str]]:
        """Ordered list of ``(region, status_code, error_body)`` tuples."""
        return list(self._attempts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the exception to a JSON-friendly dict.

        Includes ``attempts`` at the top level so consumers can inspect
        the per-region probe outcomes without unpacking ``details``.

        Returns:
            Dictionary with keys ``code``, ``message``, ``details``, and
            ``attempts``. Each ``attempts`` entry is a 3-element list
            ``[region, status_code, error_body]``.
        """
        base = super().to_dict()
        base["attempts"] = [list(a) for a in self._attempts]
        return base


class RegionProbeNetworkError(RegionProbeError):
    """Raised when every region probe attempt failed at the network layer.

    Subclass of :class:`RegionProbeError` used when ALL recorded
    attempts have ``status_code == 0`` — i.e. the credential was never
    actually evaluated because no region was reachable (DNS failure,
    TLS rejection, captive portal, no internet). The CLI catches this
    before the generic ``RegionProbeError`` so it can render "could
    not reach any Mixpanel region" instead of "credential not valid",
    which would mislead a user who is actually offline.

    Carries the same ``attempts`` shape as the parent so existing
    consumers can render the per-region detail without changes.
    """

    def __init__(
        self,
        message: str,
        *,
        attempts: list[tuple[Region, int, str]],
    ) -> None:
        """Initialize RegionProbeNetworkError.

        Args:
            message: Human-readable error message.
            attempts: Ordered list of ``(region, 0, error_body)``
                tuples — every entry must have status 0 by construction
                (the probe loop only raises this subclass when that
                invariant holds).
        """
        super().__init__(
            message,
            attempts=attempts,
            code="OAUTH_NETWORK_UNREACHABLE",
        )


class WorkspaceScopeError(MixpanelHeadlessError):
    """Scope resolution error (workspace or organization).

    Raised when an auth-axis identifier cannot be resolved during App
    API requests. Originally introduced for workspace resolution; also
    raised when the organization ID for an org-scoped business-context
    call cannot be auto-derived from the cached ``/me`` response.

    Error codes:
    - NO_WORKSPACES: Project has no accessible workspaces
    - AMBIGUOUS_WORKSPACE: Multiple workspaces, none default; must specify --workspace-id
    - WORKSPACE_NOT_FOUND: Explicit workspace ID doesn't match any workspace
    - ORGANIZATION_AMBIGUOUS: Cannot auto-resolve the organization for an
      org-scoped call (active project absent from /me AND >1 accessible
      organization). The ``details`` dict carries ``project_id`` and
      ``available_organizations``. Pass ``organization_id=N`` explicitly
      to bypass auto-resolution.

    Example:
        ```python
        try:
            workspace_id = ws.resolve_workspace_id()
        except WorkspaceScopeError as e:
            print(f"Scope issue: {e.message} (code: {e.code})")
        ```
    """

    def __init__(
        self,
        message: str,
        code: str = "NO_WORKSPACES",
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize WorkspaceScopeError.

        Args:
            message: Human-readable error message.
            code: Machine-readable error code. One of: NO_WORKSPACES,
                AMBIGUOUS_WORKSPACE, WORKSPACE_NOT_FOUND,
                ORGANIZATION_AMBIGUOUS.
            details: Additional structured data about the error.
        """
        super().__init__(message, code=code, details=details)


# Business Context Validation


class BusinessContextValidationError(MixpanelHeadlessError):
    """Business context content failed client-side validation.

    Raised by ``Workspace.set_business_context()`` when the supplied
    content exceeds ``BUSINESS_CONTEXT_MAX_CHARS`` (50,000 characters).
    The check runs before the HTTP call so callers can fail fast and
    avoid a wasted round-trip — the server enforces the same limit
    server-side and would otherwise return ``QueryError`` (HTTP 400).

    The ``details`` dict carries ``length`` (the actual content length)
    and ``max`` (the configured limit) for programmatic recovery.

    Example:
        ```python
        try:
            ws.set_business_context("x" * 60_000, level="project")
        except BusinessContextValidationError as e:
            print(f"Too long: {e.details['length']} > {e.details['max']}")
        ```
    """

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize BusinessContextValidationError.

        Args:
            message: Human-readable error message.
            details: Additional structured data — typically ``length``
                and ``max``.
        """
        super().__init__(
            message,
            code="BUSINESS_CONTEXT_TOO_LONG",
            details=details,
        )


# Bookmark Validation


@dataclass(frozen=True)
class ValidationError:
    """A single validation issue found in query arguments or bookmark params.

    Used by the bookmark validation engine to report all issues found in a
    single pass, enabling agents to fix multiple problems at once rather
    than discovering them one at a time.

    Attributes:
        path: JSONPath-like location of the error (e.g.
            ``"sections.show[0].measurement.math"``).
        message: Human-readable description of the issue.
        code: Machine-readable error code for programmatic handling
            (e.g. ``"INVALID_MATH_TYPE"``).
        severity: ``"error"`` blocks execution; ``"warning"`` is informational.
        suggestion: Fuzzy-matched valid alternatives, if applicable.
        fix: JSON structure template to correct the error, if applicable.

    Example:
        ```python
        error = ValidationError(
            path="sections.show[0].measurement.math",
            message="Invalid math type 'totl'",
            code="INVALID_MATH_TYPE",
            suggestion=("total",),
        )
        print(error)  # [ERROR] sections.show[0]...: Invalid math type 'totl'
        ```
    """

    path: str
    """JSONPath-like location of the error."""

    message: str
    """Human-readable description of the issue."""

    code: str = "VALIDATION_ERROR"
    """Machine-readable error code for programmatic handling."""

    severity: Literal["error", "warning"] = "error"
    """``"error"`` blocks execution; ``"warning"`` is informational."""

    suggestion: tuple[str, ...] | None = None
    """Fuzzy-matched valid alternatives, if applicable."""

    fix: dict[str, Any] | None = None
    """JSON structure template to correct the error, if applicable."""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for JSON output.

        Returns:
            Dictionary with all ValidationError fields. Keys with ``None``
            values are omitted for cleaner output.
        """
        result: dict[str, Any] = {
            "path": self.path,
            "message": self.message,
            "code": self.code,
            "severity": self.severity,
        }
        if self.suggestion is not None:
            result["suggestion"] = list(self.suggestion)
        if self.fix is not None:
            result["fix"] = self.fix
        return result

    def __str__(self) -> str:
        """Return formatted error string.

        Returns:
            Formatted string with severity prefix, path, and message.
        """
        prefix = "WARNING" if self.severity == "warning" else "ERROR"
        s = f"[{prefix}] {self.path}: {self.message}"
        if self.suggestion:
            s += f" Did you mean '{self.suggestion[0]}'?"
        return s


class BookmarkValidationError(MixpanelHeadlessError):
    """Bookmark params failed validation.

    Contains all validation errors found, enabling agents to fix
    multiple issues in a single pass rather than one at a time.
    Integrates into the ``MixpanelHeadlessError`` hierarchy so callers
    using ``except MixpanelHeadlessError`` will catch these.

    Attributes:
        errors: All validation errors found (both errors and warnings).
        error_count: Number of severity="error" items.
        warning_count: Number of severity="warning" items.

    Example:
        ```python
        try:
            result = ws.query("Login", math="totl")
        except BookmarkValidationError as e:
            print(f"{e.error_count} errors, {e.warning_count} warnings")
            for err in e.errors:
                print(f"  {err.path}: {err.message}")
                if err.suggestion:
                    print(f"    Did you mean: {err.suggestion[0]}?")
        ```
    """

    def __init__(self, errors: Sequence[ValidationError]) -> None:
        """Initialize BookmarkValidationError.

        Args:
            errors: Sequence of validation errors found. Must contain at
                least one error with severity="error".
        """
        self._errors = tuple(errors)
        self._error_count = sum(1 for e in self._errors if e.severity == "error")
        self._warning_count = sum(1 for e in self._errors if e.severity == "warning")

        # Build summary message
        parts: list[str] = []
        for err in self._errors:
            if err.severity == "error":
                parts.append(f"  {err}")
        summary = "\n".join(parts)
        message = (
            f"Bookmark validation failed with {self._error_count} error(s)"
            f" and {self._warning_count} warning(s):\n{summary}"
        )

        details: dict[str, Any] = {
            "error_count": self._error_count,
            "warning_count": self._warning_count,
            "errors": [e.to_dict() for e in self._errors],
        }
        super().__init__(message, code="BOOKMARK_VALIDATION_ERROR", details=details)

    @property
    def errors(self) -> tuple[ValidationError, ...]:
        """All validation errors found (both errors and warnings)."""
        return self._errors

    @property
    def error_count(self) -> int:
        """Number of severity="error" items."""
        return self._error_count

    @property
    def warning_count(self) -> int:
        """Number of severity="warning" items."""
        return self._warning_count


# =============================================================================
# Session-Replay Exceptions (044-session-replay)
# =============================================================================


class SessionReplayError(APIError):
    """Base class for session-replay-specific failures.

    Subclasses cover the three replay-specific failure modes:
    :class:`SessionReplayAccessError` (sensitive-data permission denied),
    :class:`SignedURLExpiredError` (5-minute signed-URL TTL elapsed), and
    :class:`ReplayNotFoundError` (CDN walker found no bytes for the
    replay). All carry the standard :class:`APIError` HTTP context
    (``status_code``, ``response_body``, ``request_url``, etc.) plus a
    replay-specific ``details`` dict that the subclass merges in on top
    (``replay_id``, ``project_id``, ``flag``, ``retention_days``, …).

    Catch this base class to handle any replay failure uniformly:

    Example:
        ```python
        try:
            replay = ws.fetch_replay("r-19221")
        except SessionReplayError as exc:
            log.warning("replay fetch failed: %s", exc.to_dict())
        ```

    Because :class:`SessionReplayError` is an :class:`APIError`, existing
    ``except APIError:`` handlers — including the CLI ``handle_errors``
    decorator that maps HTTP failures to exit codes — continue to catch
    these without modification.
    """

    _DEFAULT_CODE = "SESSION_REPLAY_ERROR"
    _DEFAULT_STATUS: int = 500

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        status_code: int | None = None,
        response_body: str | dict[str, Any] | None = None,
        request_method: str | None = None,
        request_url: str | None = None,
        request_params: dict[str, Any] | None = None,
        request_body: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        """Initialize SessionReplayError.

        Args:
            message: Human-readable error message; see error-messages.md for
                the catalog of stable wording per subclass.
            details: Replay-specific structured context (``replay_id``,
                ``project_id``, ``flag``, ``retention_days``,
                ``cdn_url_prefix``, ``signed_at``, ``expired_at`` —
                whichever keys the subclass documents). Merged into the
                base :class:`APIError` ``details`` dict so consumers see
                both HTTP context and replay context in one place.
            status_code: HTTP status that triggered the error. Defaults
                to the subclass's ``_DEFAULT_STATUS`` (403 for access /
                expiry, 404 for not-found, 500 for the base class).
            response_body: Raw response body for debugging.
            request_method: HTTP method (GET, POST, …).
            request_url: Full request URL.
            request_params: Query parameters sent on the failing request.
            request_body: Request body sent on the failing request.
            code: Machine-readable error code. Defaults to the subclass's
                ``_DEFAULT_CODE``.
        """
        super().__init__(
            message,
            status_code=status_code
            if status_code is not None
            else self._DEFAULT_STATUS,
            response_body=response_body,
            request_method=request_method,
            request_url=request_url,
            request_params=request_params,
            request_body=request_body,
            code=code if code is not None else self._DEFAULT_CODE,
        )
        if details:
            self._details.update(details)


class SessionReplayAccessError(SessionReplayError):
    """Project has SESSION_RECORDING_SENSITIVE_DATA enabled and caller lacks access.

    Raised when the bulk-sign endpoint returns 403 with a body that
    mentions the ``SESSION_RECORDING_SENSITIVE_DATA`` project flag. The
    project owner can grant the ``sensitive_data_replay`` permission to
    unblock the caller; a service account with that permission works too.

    Details:
        project_id (int): The project that gated the call.
        flag (str): Always ``"SESSION_RECORDING_SENSITIVE_DATA"``.
        permission_required (str): Always ``"sensitive_data_replay"``.

    See error-messages.md §1 for the canonical message wording.
    """

    _DEFAULT_CODE = "SESSION_REPLAY_ACCESS_ERROR"
    _DEFAULT_STATUS = 403


class SignedURLExpiredError(SessionReplayError):
    """Signed CDN URL passed to a fetch has expired (5-minute TTL).

    Raised when a CDN fetch returns 403 with an expiration body AND the
    caller opted out of automatic re-signing (``stream_replay`` with
    ``re_sign_on_expiry=False``). Re-sign via :meth:`Workspace.sign_replay`
    and retry, or pass ``re_sign_on_expiry=True`` (the default) to let the
    library re-sign transparently.

    Details:
        replay_id (str): The replay whose URL expired.
        signed_at (float): Unix seconds when the original URL was signed.
        expired_at (float): Unix seconds when the URL expired
            (typically ``signed_at + 300``).

    See error-messages.md §2 for the canonical message wording.
    """

    _DEFAULT_CODE = "SIGNED_URL_EXPIRED"
    _DEFAULT_STATUS = 403


class ReplayNotFoundError(SessionReplayError):
    """No CDN bytes found for a requested replay.

    Raised when the CDN walker hits a 404 on the very first file
    (``0000-N.json``). The replay either aged out of its retention
    window, was never recorded, or has been deleted. Mid-walk 404s are
    treated as the end-of-replay sentinel and do NOT raise.

    Details:
        replay_id (str): The replay that returned no bytes.
        retention_days (int): The retention window that was assumed
            (1, 7, 30, or 90).
        cdn_url_prefix (str): The CDN prefix that was walked.

    See error-messages.md §3 for the canonical message wording.
    """

    _DEFAULT_CODE = "REPLAY_NOT_FOUND"
    _DEFAULT_STATUS = 404


class UnsupportedReplayFormatError(SessionReplayError):
    """Replay bytes are not in rrweb format (mobile or other non-web recording).

    Raised by the CDN walker when the first event of a recording lacks the
    standard rrweb keys (``type`` / ``data`` / ``timestamp``). Mobile session
    replays (iOS / Android) use a different on-disk format that the rrweb
    analyzer cannot interpret. Discovery still works because
    ``$mp_session_record`` / ``$mp_replay_id`` are platform-agnostic, but the
    bytes and analyzer layers are web-only.

    This is a typed :class:`SessionReplayError` (not the builtin
    ``NotImplementedError`` used in earlier cuts) so callers can branch on it
    and the CLI ``handle_errors`` decorator maps it to a clean message and exit
    code instead of surfacing an uncaught traceback.

    Details:
        replay_id (str): The replay whose bytes were not rrweb-shaped.
        format (str): The detected shape — always ``"non-rrweb"``.

    The default ``status_code`` is 501 (Not Implemented): no HTTP request
    failed, the format simply isn't supported yet.

    See error-messages.md §9 for the canonical message wording.
    """

    _DEFAULT_CODE = "UNSUPPORTED_REPLAY_FORMAT"
    _DEFAULT_STATUS = 501


# =============================================================================
# Report-link exceptions (045-report-links)
# =============================================================================


class ReportLinkError(MixpanelHeadlessError):
    """Base class for report-link failures (045-report-links).

    Report links are Mixpanel web URLs that open a report in the browser.
    Most failures in this family are local — a link that does not parse, a
    link that points at another project or region, or a link kind that
    headless cannot resolve — so the base is :class:`MixpanelHeadlessError`
    rather than :class:`APIError`. The HTTP-shaped failures,
    :class:`ReportLinkNotFoundError` and :class:`ShortLinkResolutionError`,
    carry the parsed link fields in ``details`` instead of HTTP context.

    Subclasses: :class:`ReportLinkParseError`,
    :class:`UnsupportedReportLinkError`, :class:`ReportLinkNotFoundError`,
    :class:`ReportLinkScopeMismatchError`, :class:`ShortLinkResolutionError`.

    Not in this family: the pure URL builders and ``create_report_link``
    input guards raise :class:`ParamValidationError` with the codes
    ``RL1_UNKNOWN_REPORT_TYPE``, ``RL2_INVALID_SLUG``, ``RL3_UNKNOWN_REGION``,
    ``RL4_REPORT_TYPE_CONFLICT``, and ``RL5_RESOLVED_REPORT_INCONSISTENT``. A
    ``try/except ReportLinkError`` does not catch them. Every failure in this
    family carries a ``hint`` in ``details``.

    Example:
        ```python
        try:
            resolved = ws.resolve_report_link(link)
        except ReportLinkError as exc:
            print(exc.code, exc.details.get("hint"))
        ```
    """

    _DEFAULT_CODE = "REPORT_LINK_ERROR"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Initialize a report-link error.

        Args:
            message: Human-readable error message; see
                ``specs/045-report-links/contracts/error-messages.md`` for the
                stable wording per code.
            code: Machine-readable error code. Defaults to the subclass's
                ``_DEFAULT_CODE``.
            details: Parsed link fields that are available (``kind``,
                ``region``, ``project_id``, ``workspace_id``, ``slug``,
                ``bookmark_id``, ``short_code``) plus ``hint`` when one exists.
        """
        super().__init__(
            message,
            code=code if code is not None else self._DEFAULT_CODE,
            details=details,
        )


class ReportLinkParseError(ReportLinkError):
    """The input string is not a recognizable Mixpanel report link.

    Codes: ``REPORT_LINK_UNPARSEABLE`` (default),
    ``REPORT_LINK_NOT_MIXPANEL_HOST``, ``REPORT_LINK_UNRECOGNIZED_PATH``,
    ``REPORT_LINK_UNRECOGNIZED_HASH``, ``REPORT_LINK_EMPTY_HASH``. The parser
    is total: this is the only exception it raises for any input string.
    """

    _DEFAULT_CODE = "REPORT_LINK_UNPARSEABLE"


class UnsupportedReportLinkError(ReportLinkError):
    """The link was recognized but headless cannot resolve or run it.

    Codes: ``UNSUPPORTED_REPORT_LINK`` (default), ``UNSUPPORTED_LEGACY_HASH``
    (a ``~(...)`` JSURL hash), ``UNSUPPORTED_DASHBOARD_LINK`` (a board, not a
    single report), ``UNSUPPORTED_REPORT_TYPE`` (for example
    ``launch-analysis`` passed to ``query_report_link``).
    """

    _DEFAULT_CODE = "UNSUPPORTED_REPORT_LINK"


class ReportLinkNotFoundError(ReportLinkError):
    """The slug, saved report, or shortlink does not exist in scope.

    Codes: ``REPORT_LINK_NOT_FOUND`` (default), ``REPORT_LINK_SLUG_NOT_FOUND``,
    ``REPORT_LINK_BOOKMARK_NOT_FOUND``, ``SHORT_LINK_NOT_FOUND``. A slug is
    readable only in the project and region that created it, so a 404 on a
    slug often means the caller is on the wrong project.
    """

    _DEFAULT_CODE = "REPORT_LINK_NOT_FOUND"


class ReportLinkScopeMismatchError(ReportLinkError):
    """The link names a project or region other than the active session.

    Codes: ``REPORT_LINK_SCOPE_MISMATCH`` (default),
    ``REPORT_LINK_PROJECT_MISMATCH``, ``REPORT_LINK_REGION_MISMATCH``,
    ``REPORT_LINK_WORKSPACE_MISMATCH`` (only when the session pins a
    workspace and the link names a different one). The region check runs
    before any HTTP call. The project and workspace checks run before the
    record fetch; for a shortlink that is after the one redirect GET, because
    the target is not known before it. The message names both values, and
    ``details["hint"]`` names the ``ws.use(...)`` call and the ``mp --account``,
    ``mp --project``, or ``mp --workspace`` flag that fixes it.
    """

    _DEFAULT_CODE = "REPORT_LINK_SCOPE_MISMATCH"


class ShortLinkResolutionError(ReportLinkError):
    """A ``/s/{code}`` shortlink could not be expanded to a full report URL.

    Codes: ``SHORT_LINK_RESOLUTION_ERROR`` (default), ``SHORT_LINK_NO_LOCATION``
    (3xx without ``Location``), ``SHORT_LINK_UNEXPECTED_RESPONSE`` (200 body
    without the ``window.location.href`` script), ``SHORT_LINK_CHAIN`` (the
    target is another shortlink; headless follows one redirect only).
    """

    _DEFAULT_CODE = "SHORT_LINK_RESOLUTION_ERROR"


# =============================================================================
# Coded-guard registry (E2 coding pass)
# =============================================================================

CODED_GUARD_REGISTRY: Final[frozenset[str]] = frozenset(
    {
        # -- B1: types.py cohort/metric families (design §1.1) --------------
        "CF1_COHORT_ID_NOT_POSITIVE",
        "CB1_COHORT_ID_NOT_POSITIVE",
        "CM1_COHORT_ID_NOT_POSITIVE",
        "CF2_COHORT_NAME_EMPTY",
        "CB2_COHORT_NAME_EMPTY",
        "CM2_COHORT_NAME_EMPTY",
        "CD9_EMPTY_CRITERIA",
        # -- B1: types.py CohortCriteria / cohort helpers (design §1.2) -----
        "CD4_EMPTY_EVENT",
        "CA1_AGGREGATION_PAIR",
        "CA2_EMPTY_AGGREGATION_PROPERTY",
        "CD1_FREQUENCY_PARAM_REQUIRED",
        "CD2_FREQUENCY_NEGATIVE",
        "CD3_TIME_CONSTRAINT_REQUIRED",
        "CD3_WINDOW_NOT_POSITIVE",
        "CD5_FROM_REQUIRES_TO",
        "CD5_TO_REQUIRES_FROM",
        "CD6_DATE_FORMAT",
        "CD6_DATE_ORDER",
        "CD6_DATE_INVALID",
        "CD7_EMPTY_PROPERTY",
        "CD8_COHORT_ID_NOT_POSITIVE",
        "CD10_UNSUPPORTED_FILTER_OPERATOR",
        # -- B1: types.py query-builder dataclass guards (design §1.3) ------
        "TC0_INVALID_TYPE",
        "TC1_REQUIRES_UNIT",
        "TC1B_INVALID_UNIT",
        "TC1_REJECTS_DATE",
        "TC2_REQUIRES_DATE",
        "TC2_REJECTS_UNIT",
        "TC3_DATE_FORMAT",
        "TC3B_DATE_INVALID",
        "MT2_INVALID_SEGMENT_METHOD",
        "FM1_EMPTY_EXPRESSION",
        "LC1_MISSING_ITEM_FILTERS",
        "LC2_MISSING_QUANTIFIER",
        "FD1_QUANTITY_NOT_POSITIVE",
        "FD2_DATE_ORDER",
        "LC3_MIXED_ARGS",
        "LC4_INVALID_QUANTIFIER",
        "LC5_EMPTY_KWARG_KEY",
        "LC6_KWARG_VALUE_TYPE",
        "LC7_NO_CONDITIONS",
        "LC8_NESTED_LIST_CONTAINS",
        "LG1_EMPTY_SUB",
        "LG2_INVALID_SUB_TYPE",
        "GB1_EMPTY_PROPERTY",
        "GB4_LIST_ITEM_BUCKETING",
        "GB5_LIST_ITEM_PROPERTY_TYPE",
        "EV1_EMPTY_EVENT",
        "EV2_CONTROL_CHAR_EVENT",
        "FB1_EMPTY_EVENT",
        "FB2_BUCKET_SIZE_NOT_POSITIVE",
        "FB3_BUCKET_ORDER",
        "FB4_BUCKET_MIN_NEGATIVE",
        "FF1_EMPTY_EVENT",
        "FF2_INVALID_OPERATOR",
        "FF3_VALUE_NEGATIVE",
        "FF4_DATE_RANGE_PAIR",
        "FF5_DATE_RANGE_VALUE_NOT_POSITIVE",
        "EX1_FROM_STEP_NEGATIVE",
        "EX2_STEP_ORDER",
        "HC1_EMPTY_PROPERTY",
        "FS1_SESSION_EVENT_MISMATCH",
        # -- B1: types.py result/replay-model invariants (design §1.4) ------
        # NOTE: the design's AT1/AT2/AT3 codes (AccountTestResult) are NOT
        # minted: `AccountTestResult._ok_iff_no_error` is a pydantic
        # `@model_validator`, so those three raise sites fall under the
        # design's own P3 policy (a ValueError subclass raised inside a
        # pydantic validator is wrapped into pydantic.ValidationError and
        # the code is lost — verified empirically). They keep the builtin
        # raise; their contract is the generic VALIDATION_ERROR boundary.
        "RS1_EMPTY_REPLAY_ID",
        "RS2_PROJECT_ID_NOT_POSITIVE",
        "RS3_START_TIME_NOT_POSITIVE",
        "RS4_INVALID_RETENTION_DAYS",
        "SR1_URL_NO_TRAILING_SLASH",
        "SR2_EMPTY_QUERY_STRING",
        "SR3_INVALID_ENV",
        "SR4_SIGNED_AT_NEGATIVE",
        "UA1_TIMESTAMP_NOT_POSITIVE",
        "UA2_EMPTY_TARGET_DESC",
        "RE1_EMPTY_REPLAY_ID",
        "RE2_EMPTY_EVENT_NAME",
        "RE3_EVENT_TIME_NOT_POSITIVE",
        "RP1_EMPTY_REPLAY_ID",
        "RP2_PROJECT_ID_NOT_POSITIVE",
        "RP3_START_TIME_NOT_POSITIVE",
        "RP4_TIME_ORDER",
        "RP5_INVALID_RETENTION_DAYS",
        "RB1_PROJECT_ID_MISMATCH",
        # -- B2: bookmark_builders.py + segfilter.py (design §1.5) ----------
        "BB1_GROUP_BY_ELEMENT_TYPE",
        "BB2_FLOW_PROPERTY_FILTER_EMPTY",
        "BB3_FLOW_PROPERTY_FILTER_TYPE",
        "BB4_FLOW_COHORT_FILTER_TYPE",
        "BB5_FLOW_MULTIPLE_COHORT_FILTERS",
        "BB6_COHORT_VALUE_NOT_LIST",
        "BB7_COHORT_VALUE_NOT_DICT",
        "BB8_COHORT_KEY_MISSING",
        "SG1_UNKNOWN_STRING_OPERATOR",
        "SG2_UNKNOWN_NUMBER_OPERATOR",
        "SG3_UNKNOWN_DATETIME_OPERATOR",
        "SG4_UNSUPPORTED_PROPERTY_TYPE",
        # -- B3: user_builders.py + workspace.py + api_client.py (§1.6/§1.7) -
        "ES1_PROPERTY_NOT_STRING",
        "ES2_EQUALS_EXPECTS_LIST",
        "ES3_EQUALS_NO_TERMS",
        "ES4_NOT_EQUALS_EXPECTS_LIST",
        "ES5_NOT_EQUALS_NO_TERMS",
        "ES6_CONTAINS_EXPECTS_STR",
        "ES7_NOT_CONTAINS_EXPECTS_STR",
        "ES8_GT_EXPECTS_NUMBER",
        "ES9_LT_EXPECTS_NUMBER",
        "ES10_BETWEEN_EXPECTS_PAIR",
        "ES11_BETWEEN_LOWER_NOT_NUMBER",
        "ES12_BETWEEN_UPPER_NOT_NUMBER",
        "ES13_UNSUPPORTED_OPERATOR",
        "WR1_TOO_MANY_EVENT_PROPERTIES",
        "WR2_LIMIT_TOO_SMALL",
        "WR3_LIMIT_TOO_LARGE",
        "WR4_REPLAY_SELECTOR_REQUIRED",
        "WR5_DATE_RANGE_REQUIRED",
        "WS1_TARGET_MUTUALLY_EXCLUSIVE",
        "WS2_INVALID_LEVEL",
        "AC1_BODY_MUTUALLY_EXCLUSIVE",
        "AC2_DISTINCT_ID_CONFLICT",
        "AC3_BEHAVIORS_COHORT_CONFLICT",
        "AC4_INCLUDE_ALL_USERS_REQUIRES_COHORT",
        "AC5_BEHAVIORS_NOT_LIST",
        "AC6_AS_OF_TIMESTAMP_FUTURE",
        "RESPONSE_VALIDATION_ERROR",
        # -- 045-report-links: pure URL builder + create_report_link guards --
        "RL1_UNKNOWN_REPORT_TYPE",
        "RL2_INVALID_SLUG",
        "RL3_UNKNOWN_REGION",
        "RL4_REPORT_TYPE_CONFLICT",
        "RL5_RESOLVED_REPORT_INCONSISTENT",
    }
)
"""Every full error code minted by the E2 uncoded-raise coding pass.

Single source of truth for the codes newly introduced by the coding pass
(design ``context/phase1/addendum/coding-pass-design.md`` §1), importable by
tests (code-uniqueness guard) and the conformance recorder. Reused twin
codes are listed separately in :data:`CODED_GUARD_TWIN_CODES` — they
pre-exist in the registry and are deliberately NOT minted here.
"""

CODED_GUARD_TWIN_CODES: Final[frozenset[str]] = frozenset(
    {
        "CM5_INLINE_COHORT_METRIC",
        "V13_METRIC_MATH_PROPERTY",
        "V26_PERCENTILE_REQUIRES_VALUE",
        "V8_DATE_FORMAT",
        "V8_DATE_INVALID",
        "V12_BUCKET_SIZE_POSITIVE",
        "V18_BUCKET_ORDER",
        "FL3_FORWARD_RANGE",
        "FL4_REVERSE_RANGE",
    }
)
"""Pre-existing registry codes reused by dual-enforcement guard twins.

Each converted fail-fast guard that duplicates an already-coded validator
rule (the documented CM5 dual-enforcement pattern) carries the same full
code as its validator twin; rule-identity was verified per site (design §1
"Twin reuse"). These codes already exist in the code universe and are NOT
part of :data:`CODED_GUARD_REGISTRY`.
"""
