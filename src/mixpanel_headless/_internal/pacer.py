"""Client-side request pacing: the shared query ledger.

The server limits counted Query API requests per project in a rolling
hour. This module mirrors that limit on the client, in one JSON ledger file
per host and project under the storage root. All
processes and threads on the machine share the ledger. A short wait for
the next slot is absorbed with a sleep. A long wait raises
:class:`~mixpanel_headless.exceptions.RateLimitError` at once, and nothing
is sent. The pacer fails open: an I/O error or a bug never blocks a
request. With ``MP_PACER=off`` it does no file-system access.

This module must not import ``api_client`` (that would be circular).

Example:
    ```python
    pacer = Pacer(load_pacer_settings())
    key = classify(request.url, family, base, content=request_content(request))
    pacer.before_send(request, key)  # may sleep, or raise RateLimitError
    # ... send, then:
    pacer.after_response(response)
    ```
"""

from __future__ import annotations

import bisect
import functools
import json
import logging
import math
import os
import re
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Final, Literal, NoReturn, TypeVar, cast, get_args
from urllib.parse import parse_qs

import httpx

from mixpanel_headless._internal import client_metadata
from mixpanel_headless._internal.auth.storage import _storage_root
from mixpanel_headless._internal.io_utils import atomic_write_bytes
from mixpanel_headless.exceptions import ConfigError, RateLimitError

if sys.platform == "win32":  # pragma: no cover - Windows only
    import msvcrt

    def _try_lock_fd(fd: int) -> bool:
        """Try once to take an exclusive lock on an open lock file.

        Args:
            fd: The open file descriptor of the lock file.

        Returns:
            True when the lock is taken, False when another holder has it.
        """
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        except PermissionError:
            return False
        return True

    def _unlock_fd(fd: int) -> None:
        """Release the lock taken by :func:`_try_lock_fd`.

        Args:
            fd: The open file descriptor of the lock file.
        """
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _try_lock_fd(fd: int) -> bool:
        """Try once to take an exclusive lock on an open lock file.

        Args:
            fd: The open file descriptor of the lock file.

        Returns:
            True when the lock is taken, False when another holder has it.
        """
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        return True

    def _unlock_fd(fd: int) -> None:
        """Release the lock taken by :func:`_try_lock_fd`.

        Args:
            fd: The open file descriptor of the lock file.
        """
        fcntl.flock(fd, fcntl.LOCK_UN)


logger = logging.getLogger(__name__)

Bucket = Literal["query"]
"""A server rate-limit pool that the ledger mirrors (the Query API only)."""

LimitSource = Literal["default", "configured", "server"]
"""Where the current limit of a ledger comes from."""

Tripped = Literal["window", "concurrency"]
"""Which server limit a 429 names: the hourly window or concurrency."""

_T = TypeVar("_T")


# =============================================================================
# Budgets and constants
# =============================================================================


@dataclass(frozen=True)
class Budget:
    """A server rate-limit bucket that the ledger mirrors.

    Attributes:
        limit: Default requests per window, used until configuration or the
            server sets the real limit.
        window_s: The server's window length in seconds.
    """

    limit: int
    window_s: float


BUDGETS: Final[Mapping[Bucket, Budget]] = MappingProxyType(
    {
        "query": Budget(limit=60, window_s=3600.0),
    }
)
"""The budget of each bucket."""

# A copy of the server's API_RATE_LIMITED_ENDPOINTS. Update both together.
COUNTED_QUERY_ENDPOINTS: Final[frozenset[str]] = frozenset(
    {
        "arb_funnels",
        "cohorts",
        "correlate",
        "custom-query",
        "data_definitions",
        "engage",
        "events",
        "experiments",
        "flows",
        "formulas",
        "funnels",
        "impact",
        "insights",
        "metrics",
        "query",
        "integrations",
        "jql",
        "retention",
        "segmentation",
        "stream",
        "trends",
    }
)
"""The first path segment after ``/api/query/`` of every counted endpoint."""

MARGIN_S: Final = 10.0
"""Seconds added to the window to cover the spread of request latencies."""

LEARNED_LIMIT_TTL_S: Final = 7 * 86400
"""How long a limit learned from the server stays valid, in seconds."""

LONG_WAIT_LOG_S: Final = 5.0
"""Waits of this many seconds or more log at WARNING; shorter ones at DEBUG."""

DEFAULT_MAX_WAIT_S: Final = 30.0
"""The longest wait that the pacer absorbs by default, in seconds."""

_LOCK_TIMEOUT_S = 1.0
"""How long to retry a busy ledger lock before sending unpaced."""

_LOCK_RETRY_S = 0.02
"""The pause between tries of a busy ledger lock."""

_HORIZON_S: Final = 86400.0
"""Ledger entries further ahead than this are dropped as corrupt, in every process.

The cutoff does not depend on a process's own max_wait, so a process with a
short wait keeps the valid reservations of a process that waits without
limit. A legitimate reservation more than a day ahead needs more than
24 x limit queued callers.
"""

_LEDGER_VERSION: Final = 1
_PROJECT_ID_RE: Final = re.compile(r"[A-Za-z0-9_-]{1,64}")
_UNSAFE_HOST_CHARS: Final = re.compile(r"[^A-Za-z0-9._-]")
_CONCURRENT_UNIT: Final = "concurrent-requests"
_ITEM_RE: Final = re.compile(r'"([^"]*)"\s*((?:;[^,;]*)*)')
_PARAM_RE: Final = re.compile(r'([a-z]+)=("?)([^;,"]*)\2')
_INT_RE: Final = re.compile(r"\s*-?[0-9]{1,15}\s*")
_SWITCH_ON: Final = frozenset({"on", "true", "1", "yes"})
_SWITCH_OFF: Final = frozenset({"off", "false", "0", "no"})

_IO_WARNING: Final = (
    "Request pacing is off for this process: cannot use the ledger under %s "
    "(%s). Requests go out unpaced."
)
_LOCK_WARNING: Final = (
    "Request pacing uses a thread lock only: processes on this machine are "
    "not paced together."
)
_INTERNAL_WARNING: Final = (
    "Request pacer internal error; requests go out unpaced; please report."
)
_CLOCK_WARNING: Final = (
    "Request pacer: ignoring ledger entries in the future; the system clock "
    "stepped back."
)


# =============================================================================
# Keys and settings
# =============================================================================


@dataclass(frozen=True)
class LedgerKey:
    """Identifies one ledger. The account is not part of it, like on the server.

    Attributes:
        host: The request host, with the port when it is not the default.
        project_id: The Mixpanel project ID.
        bucket: The server rate-limit pool.
    """

    host: str
    project_id: str
    bucket: Bucket = "query"


@dataclass(frozen=True)
class PacerSettings:
    """Pacer configuration, resolved from env vars and the config file.

    Attributes:
        enabled: False turns the pacer off completely (no file access).
        max_wait_s: The longest wait the pacer absorbs with a sleep. A
            longer wait raises ``RateLimitError``. ``math.inf`` never raises.
        query_limit: A known Query API limit per hour for every project
            (from ``MP_PACER_QUERY_LIMIT``).
        query_limits: Known Query API limits per hour, keyed by project ID
            (from ``[settings.pacer_query_limits]`` in the config file).
    """

    enabled: bool = True
    max_wait_s: float = DEFAULT_MAX_WAIT_S
    query_limit: int | None = None
    query_limits: Mapping[str, int] = field(default_factory=dict)

    def configured_query_limit(self, project_id: str) -> int | None:
        """Return the configured Query API limit for a project.

        The process-wide ``query_limit`` wins over the per-project value.

        Args:
            project_id: The Mixpanel project ID.

        Returns:
            The configured limit, or None when no limit is configured.
        """
        if self.query_limit is not None:
            return self.query_limit
        return self.query_limits.get(project_id)


_warned: set[str] = set()
_warned_guard = threading.Lock()
_thread_locks: dict[str, threading.Lock] = {}
_thread_locks_guard = threading.Lock()
_waited_s = 0.0
_waited_guard = threading.Lock()


def _warn_once(message: str, *args: object, key: str | None = None) -> None:
    """Log a WARNING the first time a message (or its key) occurs in this process.

    Args:
        message: A ``%``-style format string.
        *args: Values for the format string.
        key: Identifies the warning for once-only logging. None uses the
            formatted text, so each distinct text logs once.
    """
    text = message % args if args else message
    with _warned_guard:
        if (key or text) in _warned:
            return
        _warned.add(key or text)
    logger.warning("%s", text)


def _reset_warn_once() -> None:
    """Forget which warnings were logged, so tests start clean."""
    with _warned_guard:
        _warned.clear()


def reset_wait_budget() -> None:
    """Give the process its full pacer wait budget again.

    In the ``mp`` CLI, ``max_wait_s`` is a budget for all the pacer sleeps of
    one command. Call this at the start of each command (and in tests).

    Example:
        ```python
        reset_wait_budget()  # the next command may wait max_wait_s in total
        ```
    """
    global _waited_s
    with _waited_guard:
        _waited_s = 0.0


_reset_wait_budget = reset_wait_budget  # the earlier private name, kept for callers


def _add_waited(seconds: float) -> None:
    """Add a pacer sleep to this process's total.

    Args:
        seconds: The seconds slept.
    """
    global _waited_s
    with _waited_guard:
        _waited_s += seconds


def _reset_after_fork() -> None:
    """Replace the lock registry, warn-once memory, and wait total in a child.

    A lock that another thread held at fork time stays locked forever in
    the child, so the child gets new objects.
    """
    global _warned, _warned_guard, _thread_locks, _thread_locks_guard
    global _waited_s, _waited_guard
    _warned = set()
    _warned_guard = threading.Lock()
    _thread_locks = {}
    _thread_locks_guard = threading.Lock()
    _waited_s = 0.0
    _waited_guard = threading.Lock()


if hasattr(os, "register_at_fork"):  # pragma: no branch - absent on Windows only
    os.register_at_fork(after_in_child=_reset_after_fork)


def report_internal_error() -> None:
    """Report that pacing stopped because of an unexpected error.

    Logs the current exception (if any) at DEBUG, and the fixed
    internal-error WARNING once per process. Callers outside this module
    (for example a request hook that fails to classify a request) use it,
    so users hear once that requests go out unpaced.

    Example:
        ```python
        try:
            key = classify(request.url, family, base)
        except Exception:
            report_internal_error()
        ```
    """
    logger.debug("Pacer internal error", exc_info=True)
    _warn_once(_INTERNAL_WARNING)


def parse_pacer_switch(value: object) -> bool | None:
    """Parse the pacer on/off switch (``MP_PACER`` or ``[settings] pacer``).

    Args:
        value: The raw value: a string, or a TOML boolean.

    Returns:
        True for ``on``, ``true``, ``1``, ``yes`` or TOML ``true``; False
        for ``off``, ``false``, ``0``, ``no`` or TOML ``false`` (strings
        are case-insensitive and trimmed); None for anything else.

    Example:
        ```python
        parse_pacer_switch(" No ")
        # False
        ```
    """
    if isinstance(value, bool):
        return value
    if not isinstance(value, str):
        return None
    word = value.strip().lower()
    if word in _SWITCH_ON:
        return True
    return False if word in _SWITCH_OFF else None


def _parse_max_wait(value: object) -> float | None:
    """Parse a max-wait value: a number of seconds, or ``inf``.

    Args:
        value: The raw value (a string from the env, or a TOML value).

    Returns:
        The seconds as a float, or None when the value is not a
        non-negative number.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        seconds = float(value.strip() if isinstance(value, str) else value)
    except ValueError:
        return None
    return None if math.isnan(seconds) or seconds < 0 else seconds


def _parse_positive_int(value: object) -> int | None:
    """Parse a positive integer from a string.

    Args:
        value: The raw value.

    Returns:
        The integer, or None when the value is not a positive integer string.
    """
    try:
        number = int(str(value).strip())
    except ValueError:
        return None
    return number if number > 0 else None


def _read_config_settings(config_path: Path | None) -> dict[str, Any]:
    """Read the raw ``[settings]`` table, which holds the pacer keys.

    Args:
        config_path: The config file path, or None for the default location.

    Returns:
        The raw table. An empty dict when the file is absent or cannot be
        read; a read failure logs one WARNING.
    """
    from mixpanel_headless._internal.config import ConfigManager

    try:
        return ConfigManager(config_path=config_path).get_settings()
    except (ConfigError, OSError, ValueError) as exc:
        _warn_once("Ignoring pacer settings in the config file: %s", exc)
        return {}


def _setting(
    env: str,
    key: str | None,
    parse: Callable[[object], _T | None],
    expected: str,
    config: Callable[[], Mapping[str, Any]],
) -> _T | None:
    """Resolve one setting: the env var, then the config key.

    An invalid value logs one WARNING and the next source applies. The
    config is read only when the env var does not decide the value.

    Args:
        env: The env var name.
        key: The ``[settings]`` key, or None when there is no config key.
        parse: Converts a raw value, returning None when it is invalid.
        expected: A description of a valid value, for the warning.
        config: Returns the raw ``[settings]`` table.

    Returns:
        The parsed value, or None when no source gives a valid value.
    """
    if env in os.environ:
        value = parse(os.environ[env])
        if value is not None:
            return value
        _warn_once("Ignoring %s=%r: expected %s", env, os.environ[env], expected)
    if key is not None and key in config():
        value = parse(config()[key])
        if value is not None:
            return value
        _warn_once(
            "Ignoring [settings] %s = %r: expected %s", key, config()[key], expected
        )
    return None


def _config_query_limits(raw: object) -> dict[str, int]:
    """Validate the per-project Query API limits from the config file.

    Args:
        raw: The raw ``pacer_query_limits`` value.

    Returns:
        The valid entries. Each invalid entry logs one WARNING.
    """
    if raw is None:
        return {}
    if not isinstance(raw, dict):
        _warn_once(
            "Ignoring [settings] pacer_query_limits: expected a table of "
            "project ID to a positive integer, got %r",
            raw,
        )
        return {}
    limits: dict[str, int] = {}
    for project_id, limit in raw.items():
        valid_id = isinstance(project_id, str) and _PROJECT_ID_RE.fullmatch(project_id)
        if valid_id and type(limit) is int and limit > 0:
            limits[project_id] = limit
        else:
            _warn_once(
                "Ignoring [settings.pacer_query_limits] entry %r = %r: "
                "the limit must be a positive integer",
                project_id,
                limit,
            )
    return limits


def load_pacer_settings(config_path: Path | None = None) -> PacerSettings:
    """Resolve pacer settings: env var, then ``[settings]`` in config, then default.

    - ``MP_PACER``, config ``pacer``: see :func:`parse_pacer_switch`.
    - ``MP_PACER_MAX_WAIT=<seconds>|inf``, config ``pacer_max_wait``.
    - ``MP_PACER_QUERY_LIMIT=<int>`` for all projects, config
      ``[settings.pacer_query_limits]`` ``"<project id>" = <int>``.

    An invalid value logs one WARNING and is ignored; this function never
    raises. When ``MP_PACER`` turns the pacer off, the config file is not read.

    Args:
        config_path: The config file path. None uses the default location
            (``MP_CONFIG_PATH``, else ``~/.mp/config.toml``).

    Returns:
        The resolved settings.
    """
    config = functools.cache(lambda: _read_config_settings(config_path))
    enabled = _setting(
        "MP_PACER",
        "pacer",
        parse_pacer_switch,
        "on/off, true/false, 1/0, or yes/no; request pacing stays on",
        config,
    )
    if enabled is False:
        return PacerSettings(enabled=False)
    max_wait = _setting(
        "MP_PACER_MAX_WAIT",
        "pacer_max_wait",
        _parse_max_wait,
        "seconds (>= 0) or 'inf'",
        config,
    )
    query_limit = _setting(
        "MP_PACER_QUERY_LIMIT", None, _parse_positive_int, "a positive integer", config
    )
    return PacerSettings(
        enabled=True,
        max_wait_s=DEFAULT_MAX_WAIT_S if max_wait is None else max_wait,
        query_limit=query_limit,
        query_limits=_config_query_limits(config().get("pacer_query_limits")),
    )


# =============================================================================
# Classification
# =============================================================================


def _host_key(url: httpx.URL) -> str:
    """Return the host part of a ledger key.

    Args:
        url: The request URL.

    Returns:
        The host, plus ``:port`` when the URL has a non-default port.
    """
    return f"{url.host}:{url.port}" if url.port is not None else url.host


def _body_params(content: bytes | None) -> dict[str, object]:
    """Return the parameters that a request body adds, like the server reads them.

    The server tries JSON first, then form-encoded. A body that cannot be
    decoded, or JSON that is not an object, adds nothing.

    Args:
        content: The request body, or None.

    Returns:
        The body parameters.
    """
    if not content:
        return {}
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return {}
    try:
        data = json.loads(text)
    except RecursionError:
        return {}
    except ValueError:
        return {name: values[0] for name, values in parse_qs(text).items()}
    return data if isinstance(data, dict) else {}


def request_content(request: httpx.Request) -> bytes | None:
    """Return the body of a request when it is already in memory.

    Pass the result to :func:`classify` as ``content``.

    Args:
        request: The request about to be sent.

    Returns:
        The body bytes (empty for no body), or None for a streamed body that
        is not read yet (it stays unread).
    """
    try:
        return request.content
    except httpx.RequestNotRead:
        return None


def classify(
    url: httpx.URL,
    family: str | None,
    family_base: str | None,
    *,
    content: bytes | None = None,
) -> LedgerKey | None:
    """Return the ledger key of a request that the server counts, else None.

    The rules mirror the server, which merges the body parameters over the
    URL parameters. A usable ``project_id`` is required. Query and engage
    requests count when the first path segment after the family base is in
    :data:`COUNTED_QUERY_ENDPOINTS`, except engage pages with a
    ``session_id`` and ``engage/aliases``. Export, the App API, and other
    families are not paced.

    Args:
        url: The request URL.
        family: The API family of the URL, or None.
        family_base: The base URL of that family.
        content: The request body, from :func:`request_content`.

    Returns:
        The ledger key, or None when the server does not count the request.
    """
    if family not in ("query", "engage"):
        return None
    params: dict[str, object] = dict(url.params.items())
    params.update(_body_params(content))
    raw_project_id = params.get("project_id")
    if isinstance(raw_project_id, bool) or not isinstance(raw_project_id, (str, int)):
        return None
    project_id = str(raw_project_id)
    if not _PROJECT_ID_RE.fullmatch(project_id):
        return None
    host = _host_key(url)
    if not family_base:
        return None
    base_path = httpx.URL(family_base).path.rstrip("/")
    path = url.path
    if path != base_path and not path.startswith(base_path + "/"):
        return None
    segments = [part for part in path[len(base_path) :].split("/") if part]
    if family == "engage":
        segments = ["engage", *segments]
    if not segments or segments[0] not in COUNTED_QUERY_ENDPOINTS:
        return None
    if segments[0] == "engage" and (
        segments[1:2] == ["aliases"] or params.get("session_id")
    ):
        return None
    return LedgerKey(host=host, project_id=project_id, bucket="query")


# =============================================================================
# Rate-limit header parser
# =============================================================================


@dataclass(frozen=True)
class RateLimitInfo:
    """What a 429 response says about the server's limits.

    Attributes:
        window_quota: The quota of the window policy that applies (the
            ``project`` policy when present), or None.
        window_seconds: The window length of that policy, or None.
        tripped: The limit that the request tripped, or None when the
            headers do not name one.
    """

    window_quota: int | None
    window_seconds: int | None
    tripped: Tripped | None


def _parse_items(value: str) -> list[tuple[str, dict[str, str | int]]]:
    """Parse a header such as ``"a";q=1;w=60, "b";r=0`` into items.

    Item names must be quoted. A quoted value that contains ``,`` or ``;``
    may be lost.

    Args:
        value: The header value.

    Returns:
        A list of (item name, parameters). Integer values become ints.
    """
    items: list[tuple[str, dict[str, str | int]]] = []
    for item in _ITEM_RE.finditer(value):
        params: dict[str, str | int] = {}
        for param in _PARAM_RE.finditer(item.group(2)):
            raw = param.group(3)
            is_int = not param.group(2) and _INT_RE.fullmatch(raw)
            params[param.group(1)] = int(raw) if is_int else raw
        items.append((item.group(1), params))
    return items


def _int_param(params: Mapping[str, str | int], *names: str) -> int | None:
    """Return the first parameter among ``names`` that is an integer.

    Args:
        params: The item parameters.
        *names: Parameter names in order of preference.

    Returns:
        The integer value, or None.
    """
    for name in names:
        value = params.get(name)
        if type(value) is int:
            return value
    return None


def _is_concurrency(name: str, params: Mapping[str, str | int] | None) -> bool:
    """Tell whether a policy or limit item is about concurrency.

    Args:
        name: The item name.
        params: The policy parameters, when known.

    Returns:
        True for a concurrency item.
    """
    if name.endswith("-concurrency"):
        return True
    return params is not None and params.get("qu") == _CONCURRENT_UNIT


def _parse_headers(headers: httpx.Headers) -> RateLimitInfo | None:
    """Parse the rate-limit headers; see :func:`parse_rate_limit_headers`.

    Args:
        headers: The response headers.

    Returns:
        The parsed information, or None.
    """
    policies = _parse_items(headers.get("RateLimit-Policy", ""))
    policy_params = dict(policies)
    quota: int | None = None
    seconds: int | None = None
    candidates = [
        (name, params)
        for name, params in policies
        if not _is_concurrency(name, params) and (_int_param(params, "q") or 0) > 0
    ]
    candidates.sort(key=lambda item: item[0] != "project")
    if candidates:
        params = candidates[0][1]
        quota = _int_param(params, "q")
        window = _int_param(params, "w")
        seconds = window if window is not None and window > 0 else None

    tripped: Tripped | None = None
    for name, params in _parse_items(headers.get("RateLimit", "")):
        if _int_param(params, "r", "a") != 0:
            continue
        if _is_concurrency(name, policy_params.get(name)):
            tripped = tripped or "concurrency"
        else:
            tripped = "window"

    if quota is None and tripped is None:
        return None
    return RateLimitInfo(window_quota=quota, window_seconds=seconds, tripped=tripped)


def parse_rate_limit_headers(headers: httpx.Headers) -> RateLimitInfo | None:
    """Read the server's limits from the headers of a 429 response. Never raises.

    Reads ``RateLimit-Policy`` (``q``, ``w``, ``qu``) and ``RateLimit``
    (``r`` or ``a``). The item with no remaining quota names the limit that
    tripped. The body is never read.

    Args:
        headers: The response headers.

    Returns:
        The parsed information, or None when nothing is recognizable.
    """
    try:
        return _parse_headers(headers)
    except Exception:  # noqa: BLE001 - a parser bug must never fail a request
        logger.debug("Could not parse rate-limit headers", exc_info=True)
        return None


# =============================================================================
# Ledger storage and locks
# =============================================================================


@dataclass(frozen=True)
class LedgerSnapshot:
    """A read-only view of one ledger.

    Attributes:
        limit: The current limit per window.
        limit_source: Where the limit comes from.
        used: Reservations in the current window (including future ones).
        next_slot_at: The epoch time at which a new request would go out.
        blocked_until: The floor on the next slot set by an unexplained 429.
        window_seconds: The server's window length.
    """

    limit: int
    limit_source: LimitSource
    used: int
    next_slot_at: float
    blocked_until: float
    window_seconds: float


@dataclass
class _Ledger:
    """The mutable in-memory state of one ledger file.

    Attributes:
        limit: The effective limit per window.
        limit_source: Where the effective limit comes from.
        server_limit: The limit the server confirmed (within its TTL), or None.
        learned_at: When the server confirmed it (0 when it did not).
        blocked_until: A floor on the next slot.
        blocked_at: When an unexplained window trip last set the block (0
            when none). A success clears the block only if its request was
            reserved at or after this time.
        blocked_streak: Unexplained window trips since the last success.
        sent: Sorted reservation times inside the window plus margin.
    """

    limit: int
    limit_source: LimitSource
    server_limit: int | None
    learned_at: float
    blocked_until: float
    blocked_at: float
    blocked_streak: int
    sent: list[float]


def _thread_lock_for(path: Path) -> threading.Lock:
    """Return the process-global thread lock for one ledger path.

    Args:
        path: The ledger file path.

    Returns:
        The lock, created on first use.
    """
    with _thread_locks_guard:
        return _thread_locks.setdefault(str(path), threading.Lock())


@contextmanager
def _ledger_lock(path: Path) -> Iterator[None]:
    """Hold the thread lock and the OS file lock of one ledger.

    The OS lock is on a sidecar ``.lock`` file, because the data file is
    replaced by rename. A busy lock is retried for ``_LOCK_TIMEOUT_S``. When
    the platform cannot lock files, the thread lock alone applies. Never
    sleep for a slot while this lock is held.

    Args:
        path: The ledger data file path.

    Yields:
        None, while the locks are held.

    Raises:
        TimeoutError: Another holder kept the lock past the timeout.
        OSError: The ledger directory or lock file cannot be created.
    """
    with _thread_lock_for(path):
        host_dir = path.parent
        host_dir.parent.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        host_dir.parent.mkdir(mode=0o700, exist_ok=True)
        host_dir.mkdir(mode=0o700, exist_ok=True)
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(str(path.with_name(path.name + ".lock")), flags, 0o600)
        try:
            locked = True
            deadline = time.monotonic() + _LOCK_TIMEOUT_S
            try:
                while not _try_lock_fd(fd):
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"ledger lock busy at {path}")
                    time.sleep(_LOCK_RETRY_S)
            except TimeoutError:
                raise
            except OSError as exc:
                locked = False
                logger.debug("Pacer file lock unavailable: %s", exc)
                _warn_once(_LOCK_WARNING)
            try:
                yield
            finally:
                if locked:
                    with suppress(OSError):
                        _unlock_fd(fd)
        finally:
            os.close(fd)


def _number(value: object) -> float | None:
    """Return a JSON number as a finite float.

    Args:
        value: The raw JSON value.

    Returns:
        The float, or None for booleans, non-numbers, and non-finite values.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _reject_constant(name: str) -> NoReturn:
    """Reject the non-standard JSON constants NaN, Infinity, and -Infinity.

    Args:
        name: The constant name.

    Raises:
        ValueError: Always.
    """
    raise ValueError(f"non-standard JSON constant {name}")


def _stored_ledger(data: object) -> _Ledger | None:
    """Validate the JSON content of a ledger file.

    Args:
        data: The parsed JSON value.

    Returns:
        The stored ledger, or None when the content is not a valid ledger.
    """
    if not isinstance(data, dict) or data.get("v") != _LEDGER_VERSION:
        return None
    limit = data.get("limit")
    source = data.get("limit_source")
    learned_at = _number(data.get("learned_at"))
    blocked_until = _number(data.get("blocked_until"))
    blocked_at = _number(data.get("blocked_at", 0))
    streak = data.get("blocked_streak", 0)
    raw_sent = data.get("sent")
    if (
        type(limit) is not int
        or limit <= 0
        or source not in get_args(LimitSource)
        or learned_at is None
        or blocked_until is None
        or blocked_at is None
        or type(streak) is not int
        or streak < 0
        or not isinstance(raw_sent, list)
    ):
        return None
    sent = [_number(entry) for entry in raw_sent]
    if any(entry is None for entry in sent):
        return None
    return _Ledger(
        limit=limit,
        limit_source=cast("LimitSource", source),  # checked against get_args above
        server_limit=limit if source == "server" else None,
        learned_at=learned_at,
        blocked_until=blocked_until,
        blocked_at=blocked_at,
        blocked_streak=streak,
        sent=[entry for entry in sent if entry is not None],
    )


def _ledger_slot(led: _Ledger, budget: Budget, now: float) -> float:
    """Return the earliest time at which the ledger itself admits a request.

    ``blocked_until`` is not applied here. A full ledger with the
    ``default`` limit does not block: the next request is a probe.

    Args:
        led: The loaded ledger (with ``sent`` pruned and sorted).
        budget: The budget of the ledger's bucket.
        now: The current time.

    Returns:
        The slot time.
    """
    if led.limit_source != "default" and len(led.sent) >= led.limit:
        # The oldest entry that must age out before a new one fits.
        oldest = led.sent[len(led.sent) - led.limit]
        return max(now, oldest + budget.window_s + MARGIN_S)
    return now


def _in_window(led: _Ledger, budget: Budget, now: float) -> int:
    """Count the reservations that the server can already have counted.

    Args:
        led: The ledger.
        budget: The budget of the ledger's bucket.
        now: The current time.

    Returns:
        The number of entries in ``(now - window - margin, now]``.
    """
    start = now - budget.window_s - MARGIN_S
    return sum(1 for entry in led.sent if start < entry <= now)


def _format_wait(seconds: int) -> str:
    """Format a whole number of seconds as ``Xm Ys`` or ``Ys``.

    Args:
        seconds: The wait in whole seconds.

    Returns:
        The formatted wait.
    """
    minutes, rest = divmod(seconds, 60)
    return f"{minutes}m {rest}s" if minutes else f"{rest}s"


# =============================================================================
# Pacer
# =============================================================================


class Pacer:
    """Paces counted requests against a shared on-disk ledger.

    Pacers in other threads and processes that use the same storage root
    share the same ledgers.
    """

    def __init__(
        self,
        settings: PacerSettings,
        *,
        storage_root: Path | None = None,
        clock: Callable[[], float] | None = None,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        """Create a pacer.

        Args:
            settings: The pacer settings.
            storage_root: The root directory for ledger files. None uses the
                library storage root (``MP_STORAGE_DIR``, else ``~/.mp``),
                resolved at each use.
            clock: A function that returns epoch seconds. None uses
                ``time.time``, looked up at each call.
            sleep: A function that sleeps for a number of seconds. None uses
                ``time.sleep``, looked up at each call.
        """
        self._settings = settings
        self._storage_root = storage_root
        self._clock = clock
        self._sleep_fn = sleep
        # Keys whose ledger showed a backoff streak, so a success resets it
        # without a ledger read on every successful request.
        self._streak_keys: set[LedgerKey] = set()
        self._streak_guard = threading.Lock()

    @property
    def settings(self) -> PacerSettings:
        """Return the settings of this pacer."""
        return self._settings

    def _now(self) -> float:
        """Return the current epoch time from the injected or default clock.

        Returns:
            Epoch seconds.
        """
        return self._clock() if self._clock is not None else time.time()

    def _sleep(self, seconds: float) -> None:
        """Sleep with the injected or default sleep function.

        Args:
            seconds: Seconds to sleep.
        """
        if self._sleep_fn is not None:
            self._sleep_fn(seconds)
        else:
            time.sleep(seconds)

    def _max_wait(self) -> float:
        """Return the longest wait allowed for the next reservation.

        In the ``mp`` CLI, ``max_wait_s`` is a budget for the whole process:
        the seconds already slept in the pacer are taken off. Elsewhere it
        applies to each request.

        Returns:
            The allowed wait in seconds, never below 0.
        """
        if client_metadata.get_entry_point() != "cli":
            return self._settings.max_wait_s
        with _waited_guard:
            return max(0.0, self._settings.max_wait_s - _waited_s)

    def _track_streak(self, key: LedgerKey, led: _Ledger) -> None:
        """Remember whether a ledger has a block or streak to clear on success.

        Args:
            key: The ledger key.
            led: The ledger just loaded or updated.
        """
        with self._streak_guard:
            if led.blocked_streak > 0 or led.blocked_until > 0:
                self._streak_keys.add(key)
            else:
                self._streak_keys.discard(key)

    def _root(self) -> Path:
        """Return the storage root, resolved now.

        Returns:
            The injected root, else the library storage root.
        """
        return self._storage_root if self._storage_root is not None else _storage_root()

    def _ledger_path(self, key: LedgerKey) -> Path:
        """Return the ledger file path for a key.

        Args:
            key: The ledger key.

        Returns:
            ``{storage_root}/pacer/{host}/{project_id}-{bucket}.json``, with
            unsafe host characters replaced by ``_``.

        Raises:
            ValueError: The project ID or bucket is not safe in a file name.
        """
        if not _PROJECT_ID_RE.fullmatch(key.project_id) or key.bucket not in BUDGETS:
            raise ValueError(f"unsafe ledger key: {key!r}")
        host = _UNSAFE_HOST_CHARS.sub("_", key.host)
        if host in ("", ".", ".."):
            host = "_"
        return self._root() / "pacer" / host / f"{key.project_id}-{key.bucket}.json"

    def _io_failed(self, key: LedgerKey, exc: Exception) -> None:
        """Log a ledger I/O failure: DEBUG per request, one WARNING per process.

        Args:
            key: The ledger key.
            exc: The failure.
        """
        logger.debug("Pacer ledger unavailable for %s", key, exc_info=True)
        _warn_once(_IO_WARNING, self._root(), type(exc).__name__, key="io")

    @staticmethod
    def _internal_error() -> None:
        """Log an unexpected pacer error: DEBUG per request, one WARNING per process."""
        report_internal_error()

    def _set_limit(self, led: _Ledger, key: LedgerKey) -> None:
        """Set the effective limit from the server limit and the configured one.

        A configured limit is a ceiling the user chose: with both, the lower
        one applies. With neither, the budget default applies.

        Args:
            led: The ledger to update.
            key: The ledger key.
        """
        configured = self._settings.configured_query_limit(key.project_id)
        server = led.server_limit
        if server is not None and (configured is None or server <= configured):
            led.limit, led.limit_source = server, "server"
        elif configured is not None:
            led.limit, led.limit_source = configured, "configured"
        else:
            led.limit, led.limit_source = BUDGETS[key.bucket].limit, "default"

    def _load(self, path: Path | None, key: LedgerKey, now: float) -> _Ledger:
        """Load the working ledger. A missing or corrupt file gives an empty one.

        Keeps a server limit only within its TTL (``learned_at`` is clamped
        to now), sets the effective limit, prunes old entries, drops entries
        beyond the wait horizon (a clock that stepped back), and caps
        ``blocked_until`` at one window from now.

        Args:
            path: The ledger file path, or None to read nothing.
            key: The ledger key.
            now: The current time.

        Returns:
            The working ledger.

        Raises:
            OSError: The file exists but cannot be read.
        """
        stored: _Ledger | None = None
        if path is not None:
            with suppress(FileNotFoundError):
                raw = path.read_bytes()
                try:
                    data = json.loads(raw, parse_constant=_reject_constant)
                except (ValueError, RecursionError):
                    data = None
                stored = _stored_ledger(data)
                if stored is None:
                    logger.debug("Ignoring a corrupt pacer ledger at %s", path)
        led = _Ledger(0, "default", None, 0.0, 0.0, 0.0, 0, [])
        if stored is not None:
            window = BUDGETS[key.bucket].window_s + MARGIN_S
            learned_at = min(stored.learned_at, now)
            if (
                stored.server_limit is not None
                and now - learned_at < LEARNED_LIMIT_TTL_S
            ):
                led.server_limit, led.learned_at = stored.server_limit, learned_at
            horizon = now + max(window, _HORIZON_S)
            kept = [entry for entry in stored.sent if now - window < entry <= horizon]
            if any(entry > horizon for entry in stored.sent):
                _warn_once(_CLOCK_WARNING)
            led.sent = sorted(kept)
            led.blocked_until = min(stored.blocked_until, now + window)
            led.blocked_at = stored.blocked_at
            led.blocked_streak = stored.blocked_streak
        self._set_limit(led, key)
        return led

    @staticmethod
    def _save(path: Path, led: _Ledger) -> None:
        """Write a ledger file atomically.

        A known server limit is stored as such, so each process can apply
        its own configured ceiling on top of it.

        Args:
            path: The ledger file path.
            led: The ledger to write.

        Raises:
            OSError: The file cannot be written.
        """
        if led.server_limit is not None:
            limit, source, learned_at = led.server_limit, "server", led.learned_at
        else:
            limit, source, learned_at = led.limit, led.limit_source, 0.0
        data = {
            "v": _LEDGER_VERSION,
            "limit": limit,
            "limit_source": source,
            "learned_at": learned_at,
            "blocked_until": led.blocked_until,
            "blocked_at": led.blocked_at,
            "blocked_streak": led.blocked_streak,
            "sent": led.sent,
        }
        atomic_write_bytes(path, json.dumps(data).encode("utf-8"))

    def _exhausted(
        self,
        key: LedgerKey,
        led: _Ledger,
        slot: float,
        now: float,
        from_server: bool,
        request: httpx.Request | None,
    ) -> RateLimitError:
        """Build the error for a slot that is too far away.

        Args:
            key: The ledger key.
            led: The ledger.
            slot: The next slot.
            now: The current time.
            from_server: True when the slot comes from ``blocked_until``,
                which the ledger's own count does not explain.
            request: The request that was not sent, when known.

        Returns:
            The error to raise.
        """
        wait = math.ceil(slot - now)
        opens = datetime.fromtimestamp(math.ceil(slot), tz=timezone.utc)
        used = len(led.sent)
        head = f"Mixpanel {key.bucket} budget exhausted for project {key.project_id}: "
        if from_server:
            known = f" ({led.limit})" if led.limit_source != "default" else ""
            state = (
                f"the server reported the hourly limit{known} reached, likely "
                "from other clients sharing this project. The next attempt opens"
            )
        else:
            state = (
                f"{used} of {led.limit} queries used in the last hour "
                "(Query API limit). "
                "The next slot opens"
            )
        message = (
            f"{head}{state} at {opens:%H:%M:%S} UTC (in {_format_wait(wait)}). "
            "No request was sent. To wait instead of failing, set "
            "MP_PACER_MAX_WAIT (seconds)"
        )
        return RateLimitError(
            message,
            retry_after=wait,
            request_method=request.method if request is not None else None,
            request_url=str(request.url) if request is not None else None,
            project_id=key.project_id,
            details={
                "limit": led.limit,
                "used": used,
                "window_seconds": int(BUDGETS[key.bucket].window_s),
                "next_slot_at": f"{opens:%Y-%m-%dT%H:%M:%SZ}",
                "limit_source": led.limit_source,
                "sent": False,
                "bucket": key.bucket,
                "reason": "server" if from_server else "ledger",
                **({"blocked_streak": led.blocked_streak} if from_server else {}),
            },
        )

    def _reserve(self, key: LedgerKey, request: httpx.Request | None) -> float | None:
        """Reserve the next slot and log any wait; see :meth:`reserve`.

        Args:
            key: The ledger key.
            request: The request to be sent, when known (for the error).

        Returns:
            The slot, or None when ledger I/O failed (fail open).

        Raises:
            RateLimitError: The next slot is more than ``max_wait_s`` away.
        """
        budget = BUDGETS[key.bucket]
        try:
            path = self._ledger_path(key)
            with _ledger_lock(path):
                now = self._now()
                led = self._load(path, key, now)
                ledger_slot = _ledger_slot(led, budget, now)
                slot = max(ledger_slot, led.blocked_until)
                self._track_streak(key, led)
                if slot - now > self._max_wait():
                    from_server = led.blocked_until > ledger_slot
                    raise self._exhausted(key, led, slot, now, from_server, request)
                used = len(led.sent)
                bisect.insort(led.sent, slot)  # commit before the sleep
                self._save(path, led)
        except (OSError, ValueError) as exc:
            self._io_failed(key, exc)
            return None
        wait = slot - now
        if wait > 0:
            logger.log(
                logging.WARNING if wait >= LONG_WAIT_LOG_S else logging.DEBUG,
                "Mixpanel %s budget for project %s: %d of %d used in the last hour; "
                "waiting %ds for the next slot.",
                key.bucket,
                key.project_id,
                used,
                led.limit,
                math.ceil(wait),
            )
        return slot

    def reserve(self, key: LedgerKey) -> float:
        """Reserve the next slot for a counted request and return its time.

        The caller must sleep until the slot, with no lock held, and then
        send. When the ledger cannot be read or written, the request goes
        out unpaced and the current time is returned.

        Args:
            key: The ledger key.

        Returns:
            The epoch time at which the request may be sent.

        Raises:
            RateLimitError: The next slot is more than ``max_wait_s`` away.
                Nothing is reserved and nothing is sent.
        """
        if not self._settings.enabled:
            return self._now()
        slot = self._reserve(key, None)
        return slot if slot is not None else self._now()

    def _learn(self, key: LedgerKey, led: _Ledger, quota: int, now: float) -> None:
        """Store a limit that the server reported, then reset the effective limit.

        Args:
            key: The ledger key.
            led: The ledger to update.
            quota: The server's quota.
            now: The current time.
        """
        configured = self._settings.configured_query_limit(key.project_id)
        if configured is not None and configured != quota:
            _warn_once(
                "configured query limit %d for project %s, but the server reports %d",
                configured,
                key.project_id,
                quota,
            )
        led.server_limit = quota
        led.learned_at = now
        self._set_limit(led, key)

    def _observe(
        self, key: LedgerKey, slot: float, response: httpx.Response
    ) -> Tripped | None:
        """Update the ledger from a response; see :meth:`observe`.

        Args:
            key: The ledger key.
            slot: The reserved slot of the request.
            response: The response.

        Returns:
            For a 429 whose headers name a trip and whose ledger update
            succeeded, the limit that tripped. Else None.
        """
        status = response.status_code
        if 200 <= status < 300:
            self._reset_streak(key, slot)
            return None
        if status not in (401, 402, 429):
            return None
        budget = BUDGETS[key.bucket]
        info = parse_rate_limit_headers(response.headers) if status == 429 else None
        tripped = info.tripped if info is not None else None
        try:
            path = self._ledger_path(key)
            with _ledger_lock(path):
                now = self._now()
                led = self._load(path, key, now)
                with suppress(ValueError):
                    led.sent.remove(slot)  # the server did not count it
                if info is not None and tripped is not None:
                    if info.window_quota is not None:
                        self._learn(key, led, info.window_quota, now)
                    explained = (
                        led.limit_source != "default"
                        and _in_window(led, budget, now) >= led.limit
                    )
                    if tripped == "window" and not explained:
                        # Something the ledger cannot see used the quota,
                        # for example another machine on the same project.
                        led.blocked_until = max(
                            led.blocked_until,
                            now + self._backoff(key, led),
                        )
                        led.blocked_at = now
                        led.blocked_streak += 1
                        self._track_streak(key, led)
                self._save(path, led)
        except (OSError, ValueError) as exc:
            self._io_failed(key, exc)
            return None
        return tripped

    @staticmethod
    def _backoff(key: LedgerKey, led: _Ledger) -> float:
        """Return the block length after an unexplained window trip.

        The base is window / limit, doubled for each earlier trip in the
        streak, and capped at the window.

        Args:
            key: The ledger key.
            led: The ledger, before its streak is incremented.

        Returns:
            The seconds to block.
        """
        budget = BUDGETS[key.bucket]
        base = budget.window_s / led.limit
        return min(base * float(1 << min(led.blocked_streak, 32)), budget.window_s)

    def _reset_streak(self, key: LedgerKey, slot: float) -> None:
        """Clear the block and the backoff streak after a success.

        The server accepted a counted request, so the block no longer holds,
        unless the request was reserved before the trip that set the block
        (a concurrent query admitted earlier). This runs only for keys whose
        ledger showed a block or streak, so a normal success reads and
        writes nothing.

        Args:
            key: The ledger key.
            slot: The reserved slot of the successful request.
        """
        with self._streak_guard:
            if key not in self._streak_keys:
                return
        try:
            path = self._ledger_path(key)
            with _ledger_lock(path):
                led = self._load(path, key, self._now())
                blocked = led.blocked_streak > 0 or led.blocked_until > 0
                if blocked and slot >= led.blocked_at:
                    led.blocked_streak = 0
                    led.blocked_until = 0.0
                    led.blocked_at = 0.0
                    self._save(path, led)
                self._track_streak(key, led)
        except (OSError, ValueError) as exc:
            self._io_failed(key, exc)

    def observe(self, key: LedgerKey, slot: float, response: httpx.Response) -> None:
        """Update the ledger from the response to a counted request.

        401, 402, and 429 refund: the server does not count them. A 429 whose
        headers name a trip also teaches the limit, and sets
        ``blocked_until`` (with exponential backoff) when the ledger cannot
        explain a window trip. A 2xx clears the block and the backoff when
        its request was reserved at or after the trip that set the block.
        Any other response keeps the reservation.

        Args:
            key: The ledger key.
            slot: The reserved slot of the request.
            response: The response.
        """
        if not self._settings.enabled:
            return
        try:
            self._observe(key, slot, response)
        except Exception:  # noqa: BLE001 - the pacer must never fail a request
            self._internal_error()

    def before_send(self, request: httpx.Request, key: LedgerKey | None) -> float:
        """Pace one request: reserve a slot, then sleep until it with no lock held.

        Does nothing when the pacer is off or ``key`` is None. Stores
        ``(key, slot)`` in ``request.extensions["mp_pacer"]``. It never
        sends before the slot: it sleeps in chunks of at most one window
        plus the margin and re-reads the clock after each. Only the deliberate
        ``RateLimitError`` escapes; any other failure lets the request go
        out unpaced.

        Args:
            request: The request about to be sent.
            key: The ledger key from :func:`classify`, or None.

        Returns:
            The seconds slept. 0.0 when there was no wait, the pacer is off,
            ``key`` is None, or the request goes out unpaced. After a sleep,
            time-bound request headers (such as an OAuth token) can be stale.

        Raises:
            RateLimitError: The next slot is more than the allowed wait away.
                The request must not be sent.
        """
        if not self._settings.enabled or key is None:
            return 0.0
        try:
            slot = self._reserve(key, request)
        except RateLimitError:
            raise
        except Exception:  # noqa: BLE001 - the pacer must never fail a request
            self._internal_error()
            return 0.0
        if slot is None:
            return 0.0
        request.extensions["mp_pacer"] = (key, slot)
        chunk = BUDGETS[key.bucket].window_s + MARGIN_S
        slept = 0.0
        now = self._now()
        while now < slot:
            step = min(slot - now, chunk)
            self._sleep(step)
            slept += step
            # Re-read the clock: a forward jump ends the wait early. The
            # step really elapsed, so a clock that stalls or steps back
            # never makes the pacer sleep past the slot or send early.
            now = max(self._now(), now + step)
        _add_waited(slept)
        return slept

    def after_response(self, response: httpx.Response) -> None:
        """Observe the response to a paced request. Never raises.

        On a 429 whose headers name a trip and whose ledger update
        succeeded, sets ``response.extensions["mp_pacer_tripped"]`` to
        ``"window"`` or ``"concurrency"``.

        Args:
            response: The response.
        """
        if not self._settings.enabled:
            return
        try:
            marker = response.request.extensions.get("mp_pacer")
            if marker is None:
                return
            key, slot = marker
            tripped = self._observe(key, slot, response)
        except Exception:  # noqa: BLE001 - the pacer must never fail a request
            self._internal_error()
            return
        if tripped is not None:
            response.extensions["mp_pacer_tripped"] = tripped

    def _refund(self, key: LedgerKey, slot: float) -> None:
        """Remove one reservation from the ledger; see :meth:`refund`.

        Args:
            key: The ledger key.
            slot: The reserved slot to remove.
        """
        try:
            path = self._ledger_path(key)
            with _ledger_lock(path):
                led = self._load(path, key, self._now())
                with suppress(ValueError):
                    led.sent.remove(slot)
                self._save(path, led)
        except (OSError, ValueError) as exc:
            self._io_failed(key, exc)

    def refund(self, request: httpx.Request) -> None:
        """Remove the reservation of a request that the server never received.

        Use it when the connection failed before the request was sent. It
        pops the marker (so a second call does nothing) and never raises. A
        request with no marker is ignored.

        Args:
            request: The request that ``before_send`` paced.
        """
        if not self._settings.enabled:
            return
        try:
            marker = request.extensions.pop("mp_pacer", None)
            if marker is None:
                return
            key, slot = marker
            self._refund(key, slot)
        except Exception:  # noqa: BLE001 - the pacer must never fail a request
            self._internal_error()

    def snapshot(self, key: LedgerKey) -> LedgerSnapshot:
        """Return a read-only view of one ledger. Writes nothing.

        With the pacer off it does no file access; when the ledger cannot be
        read it reports an empty ledger.

        Args:
            key: The ledger key.

        Returns:
            The limit, its source, the used count, and the next slot.
        """
        budget = BUDGETS[key.bucket]
        now = self._now()
        led = self._load(None, key, now)
        if self._settings.enabled:
            try:
                led = self._load(self._ledger_path(key), key, now)
            except (OSError, ValueError) as exc:
                logger.debug("Pacer ledger unreadable for %s: %s", key, exc)
        return LedgerSnapshot(
            limit=led.limit,
            limit_source=led.limit_source,
            used=len(led.sent),
            next_slot_at=max(_ledger_slot(led, budget, now), led.blocked_until),
            blocked_until=led.blocked_until,
            window_seconds=budget.window_s,
        )
