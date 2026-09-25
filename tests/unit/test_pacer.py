"""Unit tests for the client-side request pacer (the shared query ledger).

Every test injects a fake clock and a fake sleep, and points the ledger
storage at ``tmp_path``. No test sleeps for real or touches the real
``~/.mp`` directory.
"""

from __future__ import annotations

import json
import logging
import math
import os
import stat
import sys
import threading
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx
import pytest

from mixpanel_headless._internal import client_metadata
from mixpanel_headless._internal import pacer as pacer_mod
from mixpanel_headless._internal.pacer import (
    BUDGETS,
    COUNTED_QUERY_ENDPOINTS,
    DEFAULT_MAX_WAIT_S,
    LEARNED_LIMIT_TTL_S,
    LONG_WAIT_LOG_S,
    MARGIN_S,
    Budget,
    LedgerKey,
    LedgerSnapshot,
    Pacer,
    PacerSettings,
    RateLimitInfo,
    classify,
    load_pacer_settings,
    parse_pacer_switch,
    parse_rate_limit_headers,
    report_internal_error,
    request_content,
)
from mixpanel_headless.exceptions import RateLimitError

NOW = 1_790_000_000.0
"""Fake epoch time used by most tests (2026-09-21 14:13:20 UTC)."""

W = 3600.0 + MARGIN_S
"""The effective window: the server window plus the latency margin."""

QKEY = LedgerKey(host="mixpanel.com", project_id="12345", bucket="query")
"""A Query API ledger key."""

US_QUERY = "https://mixpanel.com/api/query"
"""The US Query API base URL."""

US_ENGAGE = "https://mixpanel.com/api/query/engage"
"""The US Engage API base URL."""

US_EXPORT = "https://data.mixpanel.com/api/2.0"
"""The US Export API base URL."""

POLICY = '"project";q=60;w=3600, "project-concurrency";q=5;qu="concurrent-requests"'
"""The ``RateLimit-Policy`` header of a real Query API 429."""

WINDOW_TRIP = '"project";r=0;t=3600, "project-concurrency";r=3'
"""The ``RateLimit`` header of a real Query API quota trip."""

CONCURRENCY_TRIP = '"project";r=12, "project-concurrency";r=0;t=10'
"""The ``RateLimit`` header of a real Query API concurrency trip."""

WINDOW_BODY = (
    '{"request": "https://mixpanel.com/api/query/insights?project_id=12345", '
    '"error": "Query rate limit exceeded for project_id: 12345. This request '
    "exceeded the rate limit (61/60 queries running in the last hour). For more "
    "information, please consult our documentation at https://help.mixpanel.com/"
    'hc/en-us/articles/115004602563-Rate-Limits-for-Export-API-Endpoints"}'
)
"""The body of a real Query API quota trip."""

CONCURRENCY_BODY = (
    '{"error": "Query rate limit exceeded for project_id: 12345. This request '
    'exceeded the concurrency limit (6/5 queries running concurrently)."}'
)
"""The body of a real Query API concurrency trip."""

LOAD_SHED_BODY = (
    '{"error": "Query rate limit exceeded for project_id: 12345 For more '
    'information, please consult our documentation"}'
)
"""The body of a Query API load-shed 429, which has no rate-limit headers."""


class FakeClock:
    """A controllable wall clock for the pacer."""

    def __init__(self, now: float = NOW, step: float = 0.0) -> None:
        """Start the clock.

        Args:
            now: The first time the clock returns.
            step: Seconds added after each read (0 keeps the time fixed).
        """
        self.now = now
        self.step = step
        self._lock = threading.Lock()

    def __call__(self) -> float:
        """Return the current fake time, then advance it by ``step``.

        Returns:
            The fake epoch time.
        """
        with self._lock:
            value = self.now
            self.now += self.step
            return value

    def advance(self, seconds: float) -> None:
        """Move the clock forward.

        Args:
            seconds: Seconds to add.
        """
        self.now += seconds


@pytest.fixture(autouse=True)
def _reset_warn_once(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Clear the log-once memory and wait budget; run as the library, not the CLI.

    Importing ``mixpanel_headless.cli`` anywhere in the test session flips the
    process entry point to ``"cli"``, which makes max_wait a process budget.
    """
    monkeypatch.setattr(client_metadata, "_entry_point", "lib")
    pacer_mod._reset_warn_once()
    pacer_mod._reset_wait_budget()
    yield
    pacer_mod._reset_warn_once()
    pacer_mod._reset_wait_budget()


@pytest.fixture
def clock() -> FakeClock:
    """Provide a fixed fake clock at ``NOW``."""
    return FakeClock()


@pytest.fixture
def sleeps() -> list[float]:
    """Provide a list that records every sleep the pacer asks for."""
    return []


@pytest.fixture
def root(tmp_path: Path) -> Path:
    """Provide a temporary storage root for ledger files."""
    return tmp_path / "mp"


@pytest.fixture
def make_pacer(
    root: Path, clock: FakeClock, sleeps: list[float]
) -> Callable[..., Pacer]:
    """Provide a factory that builds a Pacer on the temporary root.

    Returns:
        A function that takes optional ``PacerSettings`` fields as keyword
        arguments and returns a Pacer with the fake clock and sleep.
    """

    def factory(**fields: Any) -> Pacer:
        """Build a Pacer with the given settings fields.

        Args:
            **fields: Keyword arguments for ``PacerSettings``.

        Returns:
            The Pacer.
        """
        return Pacer(
            PacerSettings(**fields),
            storage_root=root,
            clock=clock,
            sleep=sleeps.append,
        )

    return factory


def ledger_path(root: Path, key: LedgerKey = QKEY) -> Path:
    """Return the ledger file path for ``key`` under ``root``.

    Args:
        root: The storage root.
        key: The ledger key.

    Returns:
        The expected ledger file path.
    """
    return root / "pacer" / key.host / f"{key.project_id}-{key.bucket}.json"


def write_ledger(root: Path, key: LedgerKey = QKEY, **fields: Any) -> Path:
    """Write a ledger file with the given fields over sensible defaults.

    Args:
        root: The storage root.
        key: The ledger key.
        **fields: Field values that replace the defaults.

    Returns:
        The ledger file path.
    """
    data: dict[str, Any] = {
        "v": 1,
        "limit": 60,
        "limit_source": "default",
        "learned_at": 0,
        "blocked_until": 0,
        "sent": [],
    }
    data.update(fields)
    path = ledger_path(root, key)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def read_ledger(root: Path, key: LedgerKey = QKEY) -> dict[str, Any]:
    """Read and parse a ledger file.

    Args:
        root: The storage root.
        key: The ledger key.

    Returns:
        The parsed JSON object.
    """
    result: dict[str, Any] = json.loads(ledger_path(root, key).read_text("utf-8"))
    return result


def response(
    status: int,
    headers: Mapping[str, str] | None = None,
    text: str = "",
    url: str = f"{US_QUERY}/insights?project_id=12345",
) -> httpx.Response:
    """Build a response with a request attached.

    Args:
        status: HTTP status code.
        headers: Response headers.
        text: Response body.
        url: The request URL.

    Returns:
        The response.
    """
    return httpx.Response(
        status,
        headers=dict(headers or {}),
        text=text,
        request=httpx.Request("GET", url),
    )


def rl_headers(rate_limit: str = WINDOW_TRIP, policy: str = POLICY) -> dict[str, str]:
    """Build Query API 429 headers.

    Args:
        rate_limit: The ``RateLimit`` header value.
        policy: The ``RateLimit-Policy`` header value.

    Returns:
        The header mapping.
    """
    return {"RateLimit-Policy": policy, "RateLimit": rate_limit, "Retry-After": "3600"}


# =============================================================================
# Budgets and constants
# =============================================================================


class TestBudgets:
    """The budget table and constants match the server."""

    def test_query_budget(self) -> None:
        """The Query API budget is 60 per hour."""
        assert BUDGETS["query"] == Budget(limit=60, window_s=3600.0)

    def test_only_query_is_paced(self) -> None:
        """The pacer mirrors the Query API bucket only."""
        assert set(BUDGETS) == {"query"}

    def test_ledger_key_defaults_to_query(self) -> None:
        """A ledger key without a bucket is a Query API key."""
        assert LedgerKey(host="mixpanel.com", project_id="12345") == QKEY

    def test_counted_endpoints_match_server_list(self) -> None:
        """The counted endpoints are a copy of the server's list."""
        assert (
            frozenset(
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
            == COUNTED_QUERY_ENDPOINTS
        )

    def test_constants(self) -> None:
        """The margin, TTL, log threshold, and max wait have their set values."""
        assert MARGIN_S == 10.0
        assert LEARNED_LIMIT_TTL_S == 7 * 86400
        assert LONG_WAIT_LOG_S == 5.0
        assert DEFAULT_MAX_WAIT_S == 30.0

    def test_settings_defaults(self) -> None:
        """PacerSettings defaults to on, 30 s, and no configured limits."""
        settings = PacerSettings()
        assert settings.enabled is True
        assert settings.max_wait_s == 30.0
        assert settings.query_limit is None
        assert dict(settings.query_limits) == {}


# =============================================================================
# Classification
# =============================================================================


class TestClassify:
    """``classify`` mirrors the server's rules for counted requests."""

    @pytest.mark.parametrize(
        "path",
        [
            "insights",
            "segmentation",
            "segmentation/numeric",
            "funnels",
            "retention",
            "arb_funnels",
            "events/properties/top",
            "data_definitions/events",
            "cohorts/list",
            "stream/bookmark",
            "jql",
            "custom-query",
        ],
    )
    def test_counted_query_endpoints(self, path: str) -> None:
        """Every counted Query API endpoint maps to the query bucket."""
        url = httpx.URL(f"{US_QUERY}/{path}?project_id=12345")
        assert classify(url, "query", US_QUERY) == QKEY

    @pytest.mark.parametrize(
        "path", ["annotations", "custom_events", "workspaces", "project", ""]
    )
    def test_free_query_endpoints(self, path: str) -> None:
        """Query API endpoints outside the server list are not paced."""
        url = httpx.URL(f"{US_QUERY}/{path}?project_id=12345")
        assert classify(url, "query", US_QUERY) is None

    def test_no_project_id(self) -> None:
        """A request with no project_id cannot be keyed and is not paced."""
        url = httpx.URL(f"{US_QUERY}/insights")
        assert classify(url, "query", US_QUERY) is None

    @pytest.mark.parametrize("pid", ["../x", "", "a/b", "1 2", "x" * 65])
    def test_unsafe_project_id(self, pid: str) -> None:
        """A project_id that is not safe in a file name is not paced."""
        url = httpx.URL(f"{US_QUERY}/insights", params={"project_id": pid})
        assert classify(url, "query", US_QUERY) is None

    def test_engage_first_page(self) -> None:
        """The first engage page counts against the query bucket."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345")
        assert classify(url, "engage", US_ENGAGE) == QKEY

    def test_engage_stats(self) -> None:
        """Engage stats counts against the query bucket."""
        url = httpx.URL(f"{US_ENGAGE}/stats?project_id=12345")
        assert classify(url, "engage", US_ENGAGE) == QKEY

    def test_engage_aliases_is_free(self) -> None:
        """Engage aliases is free on the server."""
        url = httpx.URL(f"{US_ENGAGE}/aliases?project_id=12345")
        assert classify(url, "engage", US_ENGAGE) is None

    def test_engage_session_id_param_is_free(self) -> None:
        """An engage page with a session_id URL parameter is free."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345&session_id=abc")
        assert classify(url, "engage", US_ENGAGE) is None

    def test_engage_session_id_in_json_body_is_free(self) -> None:
        """An engage page with a session_id in its JSON body is free."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345")
        body = json.dumps({"page": 1, "session_id": "abc"}).encode()
        assert classify(url, "engage", US_ENGAGE, content=body) is None

    def test_engage_session_id_in_form_body_is_free(self) -> None:
        """An engage page with a session_id in a form body is free."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345")
        assert (
            classify(url, "engage", US_ENGAGE, content=b"page=1&session_id=abc") is None
        )

    @pytest.mark.parametrize(
        "body",
        [
            b"",
            b'{"page": 0}',
            b'{"session_id": ""}',
            b'{"session_id": null}',
            b"[1, 2]",
            b"\xff\xfe not utf8",
            b"page=0",
        ],
    )
    def test_engage_body_without_session_id_counts(self, body: bytes) -> None:
        """An engage body without a usable session_id still counts."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345")
        assert classify(url, "engage", US_ENGAGE, content=body) == QKEY

    def test_engage_form_body_that_starts_like_json_is_free(self) -> None:
        """A body that is not valid JSON is read as form data, like the server."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345")
        content = b"{x=1&session_id=abc"
        assert classify(url, "engage", US_ENGAGE, content=content) is None

    def test_engage_json_scalar_body_counts(self) -> None:
        """A JSON body that is not an object has no session_id and counts."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345")
        assert classify(url, "engage", US_ENGAGE, content=b'"session_id=abc"') == QKEY

    def test_engage_deeply_nested_json_counts(self) -> None:
        """A JSON body too deep to decode counts, like any decode failure."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345")
        content = b"[" * 200_000 + b"]" * 200_000
        assert classify(url, "engage", US_ENGAGE, content=content) == QKEY

    def test_session_id_body_ignored_outside_engage(self) -> None:
        """A session_id body does not free a non-engage endpoint."""
        url = httpx.URL(f"{US_QUERY}/insights?project_id=12345")
        body = b'{"session_id": "abc"}'
        assert classify(url, "query", US_QUERY, content=body) == QKEY

    def test_project_id_in_json_body(self) -> None:
        """A project_id sent only in the JSON body is read, like on the server."""
        url = httpx.URL(f"{US_QUERY}/insights")
        body = b'{"project_id": "12345", "bookmark": {}}'
        assert classify(url, "query", US_QUERY, content=body) == QKEY

    def test_int_project_id_in_json_body(self) -> None:
        """A JSON number project_id is read as its decimal string."""
        url = httpx.URL(f"{US_QUERY}/insights")
        assert (
            classify(url, "query", US_QUERY, content=b'{"project_id": 12345}') == QKEY
        )

    def test_project_id_in_form_body(self) -> None:
        """A project_id sent only in a form body is read."""
        url = httpx.URL(f"{US_QUERY}/insights")
        assert classify(url, "query", US_QUERY, content=b"project_id=12345") == QKEY

    def test_body_project_id_overrides_url(self) -> None:
        """The body value wins over the URL value, like on the server."""
        url = httpx.URL(f"{US_QUERY}/insights?project_id=999")
        body = b'{"project_id": "12345"}'
        assert classify(url, "query", US_QUERY, content=body) == QKEY

    def test_body_session_id_overrides_url(self) -> None:
        """An empty body session_id wins over a URL session_id, so the page counts."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345&session_id=abc")
        body = b'{"session_id": ""}'
        assert classify(url, "engage", US_ENGAGE, content=body) == QKEY

    @pytest.mark.parametrize(
        "body",
        [b'{"project_id": true}', b'{"project_id": 1.5}', b'{"project_id": [1]}'],
    )
    def test_unusable_body_project_id(self, body: bytes) -> None:
        """A body project_id that is not a string or integer is not paced."""
        url = httpx.URL(f"{US_QUERY}/insights?project_id=12345")
        assert classify(url, "query", US_QUERY, content=body) is None

    @pytest.mark.parametrize(
        "body", [b"\xff\xfe", b"[1, 2]", b"[" * 200_000 + b"]" * 200_000]
    )
    def test_undecodable_body_keeps_url_params(self, body: bytes) -> None:
        """A body that gives no params leaves the URL project_id in force."""
        url = httpx.URL(f"{US_QUERY}/insights?project_id=12345")
        assert classify(url, "query", US_QUERY, content=body) == QKEY

    def test_engage_under_query_family(self) -> None:
        """An engage path classified under the query family keeps engage rules."""
        counted = httpx.URL(f"{US_QUERY}/engage?project_id=12345")
        free = httpx.URL(f"{US_QUERY}/engage/aliases?project_id=12345")
        assert classify(counted, "query", US_QUERY) == QKEY
        assert classify(free, "query", US_QUERY) is None

    def test_export_not_paced(self) -> None:
        """Export API requests are not paced."""
        url = httpx.URL(f"{US_EXPORT}/export?project_id=12345&from_date=2026-01-01")
        assert classify(url, "export", US_EXPORT) is None

    @pytest.mark.parametrize("family", ["app", None, "other"])
    def test_other_families_not_paced(self, family: str | None) -> None:
        """App API and unknown families are not paced."""
        url = httpx.URL("https://mixpanel.com/api/app/me?project_id=12345")
        assert classify(url, family, "https://mixpanel.com/api/app") is None

    def test_eu_host(self) -> None:
        """The host separates regions."""
        base = "https://eu.mixpanel.com/api/query"
        url = httpx.URL(f"{base}/insights?project_id=7")
        assert classify(url, "query", base) == LedgerKey(
            "eu.mixpanel.com", "7", "query"
        )

    def test_custom_base_with_port(self) -> None:
        """A non-default port is part of the host key."""
        base = "http://127.0.0.1:8080/api/query"
        url = httpx.URL(f"{base}/insights?project_id=7")
        assert classify(url, "query", base) == LedgerKey("127.0.0.1:8080", "7", "query")

    def test_path_not_under_base(self) -> None:
        """A query URL whose path is not under the family base is not paced."""
        url = httpx.URL("https://mixpanel.com/other/insights?project_id=12345")
        assert classify(url, "query", US_QUERY) is None

    def test_missing_base(self) -> None:
        """A query family with no base is not paced."""
        url = httpx.URL(f"{US_QUERY}/insights?project_id=12345")
        assert classify(url, "query", None) is None

    def test_base_with_trailing_slash(self) -> None:
        """A base URL with a trailing slash still matches."""
        url = httpx.URL(f"{US_QUERY}/insights?project_id=12345")
        assert classify(url, "query", US_QUERY + "/") == QKEY


class TestRequestContent:
    """``request_content`` returns a request body when it is safe to read."""

    def test_json_body(self) -> None:
        """A JSON request body is returned as bytes."""
        request = httpx.Request("POST", US_ENGAGE, json={"session_id": "abc"})
        assert request_content(request) == b'{"session_id":"abc"}'

    def test_form_body(self) -> None:
        """A form request body is returned as bytes."""
        request = httpx.Request("POST", US_ENGAGE, data={"session_id": "abc"})
        assert request_content(request) == b"session_id=abc"

    def test_no_body(self) -> None:
        """A request with no body gives empty bytes."""
        assert request_content(httpx.Request("GET", US_QUERY)) == b""

    def test_streamed_body_not_read(self) -> None:
        """A streamed body that is not read yet gives None and stays unread."""

        def chunks() -> Iterator[bytes]:
            """Yield one body chunk.

            Yields:
                The chunk.
            """
            yield b"session_id=abc"

        request = httpx.Request("POST", US_ENGAGE, content=chunks())
        assert request_content(request) is None

    def test_feeds_classify(self) -> None:
        """The helper output makes a later engage page free in ``classify``."""
        request = httpx.Request(
            "POST", f"{US_ENGAGE}?project_id=12345", json={"session_id": "abc"}
        )
        key = classify(
            request.url, "engage", US_ENGAGE, content=request_content(request)
        )
        assert key is None


# =============================================================================
# Settings
# =============================================================================


@pytest.fixture
def config_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point ``MP_CONFIG_PATH`` at a temporary config path and clear pacer env.

    Returns:
        The config file path, not yet created.
    """
    path = tmp_path / "config.toml"
    monkeypatch.setenv("MP_CONFIG_PATH", str(path))
    for name in ("MP_PACER", "MP_PACER_MAX_WAIT", "MP_PACER_QUERY_LIMIT"):
        # setenv first so monkeypatch records the original state; teardown
        # then also undoes the direct os.environ writes in the tests below.
        monkeypatch.setenv(name, "")
        monkeypatch.delenv(name)
    return path


def write_config(path: Path, body: str) -> None:
    """Write a TOML config file with mode 0o600.

    Args:
        path: The config file path.
        body: The TOML text.
    """
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)


def pacer_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    """Return the WARNING messages the pacer logged.

    Args:
        caplog: The pytest log capture fixture.

    Returns:
        The formatted messages.
    """
    return [
        r.getMessage()
        for r in caplog.records
        if r.name == "mixpanel_headless._internal.pacer"
        and r.levelno == logging.WARNING
    ]


class TestParsePacerSwitch:
    """``parse_pacer_switch`` reads on/off values."""

    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("on", True),
            (" TRUE ", True),
            ("1", True),
            ("Yes", True),
            (True, True),
            ("off", False),
            ("False", False),
            ("0", False),
            (" no", False),
            (False, False),
            ("maybe", None),
            ("", None),
            (1, None),
            (None, None),
        ],
    )
    def test_values(self, value: object, expected: bool | None) -> None:
        """Each accepted spelling maps to on or off; anything else is None."""
        assert parse_pacer_switch(value) is expected


class TestLoadSettings:
    """``load_pacer_settings`` reads env, then config, then defaults."""

    def test_defaults(self, config_file: Path) -> None:
        """No env and no config file give the defaults."""
        assert load_pacer_settings() == PacerSettings()

    def test_env_off(self, config_file: Path, caplog: pytest.LogCaptureFixture) -> None:
        """MP_PACER=off disables the pacer and does not read the config."""
        write_config(config_file, "[settings\n")
        os.environ["MP_PACER"] = "off"
        assert load_pacer_settings().enabled is False
        assert pacer_warnings(caplog) == []

    def test_env_on_case_insensitive(self, config_file: Path) -> None:
        """MP_PACER accepts any case and surrounding space."""
        write_config(config_file, '[settings]\npacer = "off"\n')
        os.environ["MP_PACER"] = " ON "
        assert load_pacer_settings().enabled is True

    def test_config_off(self, config_file: Path) -> None:
        """``pacer = "off"`` in config disables the pacer."""
        write_config(config_file, '[settings]\npacer = "off"\n')
        assert load_pacer_settings().enabled is False

    def test_invalid_env_pacer(
        self, config_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An invalid MP_PACER value is logged and the config value applies."""
        write_config(config_file, '[settings]\npacer = "off"\n')
        os.environ["MP_PACER"] = "maybe"
        assert load_pacer_settings().enabled is False
        warnings = pacer_warnings(caplog)
        assert len(warnings) == 1
        assert warnings[0].startswith("Ignoring MP_PACER='maybe'")
        assert warnings[0].endswith("; request pacing stays on")

    def test_invalid_config_pacer(
        self, config_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An invalid config pacer value is logged and the default applies."""
        write_config(config_file, "[settings]\npacer = 5\n")
        assert load_pacer_settings().enabled is True
        assert any("[settings] pacer = 5" in m for m in pacer_warnings(caplog))

    @pytest.mark.parametrize(("value", "enabled"), [("false", False), ("true", True)])
    def test_config_pacer_toml_bool(
        self, config_file: Path, value: str, enabled: bool
    ) -> None:
        """A TOML boolean turns the pacer on or off."""
        write_config(config_file, f"[settings]\npacer = {value}\n")
        assert load_pacer_settings().enabled is enabled

    def test_env_pacer_false_disables(self, config_file: Path) -> None:
        """MP_PACER=false turns the pacer off."""
        os.environ["MP_PACER"] = "false"
        assert load_pacer_settings().enabled is False

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("120", 120.0),
            ("0", 0.0),
            ("2.5", 2.5),
            ("inf", math.inf),
            ("INF", math.inf),
        ],
    )
    def test_env_max_wait(self, config_file: Path, raw: str, expected: float) -> None:
        """MP_PACER_MAX_WAIT accepts seconds or inf."""
        os.environ["MP_PACER_MAX_WAIT"] = raw
        assert load_pacer_settings().max_wait_s == expected

    @pytest.mark.parametrize("raw", ["-5", "abc", "nan", ""])
    def test_invalid_env_max_wait(
        self, config_file: Path, raw: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An invalid MP_PACER_MAX_WAIT is logged and the default applies."""
        os.environ["MP_PACER_MAX_WAIT"] = raw
        assert load_pacer_settings().max_wait_s == DEFAULT_MAX_WAIT_S
        assert any("MP_PACER_MAX_WAIT" in m for m in pacer_warnings(caplog))

    def test_config_max_wait(self, config_file: Path) -> None:
        """``pacer_max_wait`` in config sets the max wait."""
        write_config(config_file, "[settings]\npacer_max_wait = 90\n")
        assert load_pacer_settings().max_wait_s == 90.0

    def test_config_max_wait_inf_string(self, config_file: Path) -> None:
        """``pacer_max_wait = "inf"`` in config means wait without limit."""
        write_config(config_file, '[settings]\npacer_max_wait = "inf"\n')
        assert load_pacer_settings().max_wait_s == math.inf

    def test_env_max_wait_beats_config(self, config_file: Path) -> None:
        """The env max wait wins over the config value."""
        write_config(config_file, "[settings]\npacer_max_wait = 90\n")
        os.environ["MP_PACER_MAX_WAIT"] = "5"
        assert load_pacer_settings().max_wait_s == 5.0

    @pytest.mark.parametrize("value", ["true", "-1", '"soon"', "nan"])
    def test_invalid_config_max_wait(
        self, config_file: Path, value: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An invalid config max wait is logged and the default applies."""
        write_config(config_file, f"[settings]\npacer_max_wait = {value}\n")
        assert load_pacer_settings().max_wait_s == DEFAULT_MAX_WAIT_S
        assert any("pacer_max_wait" in m for m in pacer_warnings(caplog))

    def test_env_query_limit(self, config_file: Path) -> None:
        """MP_PACER_QUERY_LIMIT sets the limit for all projects."""
        os.environ["MP_PACER_QUERY_LIMIT"] = "240"
        assert load_pacer_settings().query_limit == 240

    @pytest.mark.parametrize("raw", ["0", "-3", "abc", "1.5", ""])
    def test_invalid_env_query_limit(
        self, config_file: Path, raw: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """An invalid MP_PACER_QUERY_LIMIT is logged and ignored."""
        os.environ["MP_PACER_QUERY_LIMIT"] = raw
        assert load_pacer_settings().query_limit is None
        assert any("MP_PACER_QUERY_LIMIT" in m for m in pacer_warnings(caplog))

    def test_config_query_limits(
        self, config_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Valid per-project limits are kept and invalid entries are logged."""
        write_config(
            config_file,
            "[settings.pacer_query_limits]\n"
            '"3713224" = 240\n"9" = 0\n"8" = "x"\n"7" = true\n"6" = 1.5\n',
        )
        settings = load_pacer_settings()
        assert dict(settings.query_limits) == {"3713224": 240}
        assert len(pacer_warnings(caplog)) == 4

    def test_config_query_limits_not_table(
        self, config_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A pacer_query_limits value that is not a table is logged and ignored."""
        write_config(config_file, "[settings]\npacer_query_limits = 5\n")
        assert dict(load_pacer_settings().query_limits) == {}
        assert any("pacer_query_limits" in m for m in pacer_warnings(caplog))

    def test_malformed_config(
        self, config_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A malformed config file is logged and the defaults apply."""
        write_config(config_file, "[settings\n")
        assert load_pacer_settings() == PacerSettings()
        assert len(pacer_warnings(caplog)) == 1

    def test_explicit_config_path(self, tmp_path: Path, config_file: Path) -> None:
        """An explicit config path wins over MP_CONFIG_PATH."""
        other = tmp_path / "other.toml"
        write_config(other, "[settings]\npacer_max_wait = 7\n")
        assert load_pacer_settings(other).max_wait_s == 7.0

    def test_warnings_log_once(
        self, config_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The same invalid value logs one warning over many loads."""
        os.environ["MP_PACER_QUERY_LIMIT"] = "abc"
        load_pacer_settings()
        load_pacer_settings()
        assert len(pacer_warnings(caplog)) == 1

    def test_configured_query_limit_precedence(self) -> None:
        """The env limit wins over the per-project config value."""
        both = PacerSettings(query_limit=100, query_limits={"1": 240})
        per_project = PacerSettings(query_limits={"1": 240})
        assert both.configured_query_limit("1") == 100
        assert per_project.configured_query_limit("1") == 240
        assert per_project.configured_query_limit("2") is None


# =============================================================================
# Header parser
# =============================================================================


class TestParseRateLimitHeaders:
    """``parse_rate_limit_headers`` reads the server's 429 exactly and tolerantly."""

    def test_window_trip(self) -> None:
        """The real server quota trip gives the project quota and a window trip."""
        info = parse_rate_limit_headers(httpx.Headers(rl_headers()))
        assert info == RateLimitInfo(
            window_quota=60, window_seconds=3600, tripped="window"
        )

    def test_concurrency_trip(self) -> None:
        """The real server concurrency trip is classified as concurrency."""
        headers = httpx.Headers(rl_headers(CONCURRENCY_TRIP))
        info = parse_rate_limit_headers(headers)
        assert info == RateLimitInfo(60, 3600, "concurrency")

    def test_both_tripped_is_window(self) -> None:
        """When both limits trip, the window trip wins."""
        headers = httpx.Headers(
            rl_headers('"project";r=0;t=3600, "project-concurrency";r=0;t=10')
        )
        assert parse_rate_limit_headers(headers) == RateLimitInfo(60, 3600, "window")

    def test_jql_policies_prefer_project(self) -> None:
        """With JQL policies present, the project policy gives the quota."""
        policy = (
            '"endpoint-jql";q=30;w=3600, "project";q=240;w=3600, '
            '"project-concurrency";q=10;qu="concurrent-requests"'
        )
        rate = '"endpoint-jql";r=0;t=3600, "project";r=100, "project-concurrency";r=4'
        info = parse_rate_limit_headers(httpx.Headers(rl_headers(rate, policy)))
        assert info == RateLimitInfo(240, 3600, "window")

    def test_first_window_policy_without_project(self) -> None:
        """With no project policy, the first non-concurrency policy applies."""
        policy = '"endpoint-jql-concurrency";q=5;qu="concurrent-requests", "endpoint-jql";q=30;w=60'
        info = parse_rate_limit_headers(httpx.Headers({"RateLimit-Policy": policy}))
        assert info == RateLimitInfo(30, 60, None)

    def test_renamed_parameters(self) -> None:
        """The proposed ``a`` and ``w`` names in RateLimit are accepted."""
        headers = httpx.Headers(
            rl_headers('"project";a=0;w=3600, "project-concurrency";a=3')
        )
        assert parse_rate_limit_headers(headers) == RateLimitInfo(60, 3600, "window")

    def test_concurrency_by_policy_unit(self) -> None:
        """A tripped item whose policy counts concurrent requests is concurrency."""
        policy = '"project";q=60;w=3600, "slots";q=5;qu="concurrent-requests"'
        headers = httpx.Headers(rl_headers('"slots";r=0;t=10', policy))
        assert parse_rate_limit_headers(headers) == RateLimitInfo(
            60, 3600, "concurrency"
        )

    def test_tokens_without_quotes_are_ignored(self) -> None:
        """Item names given as bare tokens are not read; the server always quotes."""
        headers = httpx.Headers(
            {
                "RateLimit-Policy": "project;q=60;w=3600",
                "RateLimit": "project;r=0;t=3600",
            }
        )
        assert parse_rate_limit_headers(headers) is None

    def test_rate_limit_without_policy(self) -> None:
        """A RateLimit header alone gives the trip but no quota."""
        headers = httpx.Headers({"RateLimit": WINDOW_TRIP})
        assert parse_rate_limit_headers(headers) == RateLimitInfo(None, None, "window")

    def test_policy_without_rate_limit(self) -> None:
        """A policy alone gives the quota and no trip."""
        headers = httpx.Headers({"RateLimit-Policy": POLICY})
        assert parse_rate_limit_headers(headers) == RateLimitInfo(60, 3600, None)

    def test_policy_without_window(self) -> None:
        """A policy with no ``w`` gives the quota with no window length."""
        headers = httpx.Headers({"RateLimit-Policy": '"project";q=60'})
        assert parse_rate_limit_headers(headers) == RateLimitInfo(60, None, None)

    def test_nothing_recognizable(self) -> None:
        """With no rate-limit headers, the result is None."""
        assert parse_rate_limit_headers(httpx.Headers({"Retry-After": "10"})) is None

    @pytest.mark.parametrize(
        "policy",
        [
            ';;;,,,"',
            '"project";q=abc;w=3600',
            '"project";q=-1;w=3600',
            '"project";q=0;w=3600',
            '"project;q=60',
            "=;=;=",
            '"project";q="60"',
            '"project";q',
            "",
        ],
    )
    def test_malformed_policy(self, policy: str) -> None:
        """Malformed policies never raise and give no quota."""
        info = parse_rate_limit_headers(httpx.Headers({"RateLimit-Policy": policy}))
        assert info is None or info.window_quota is None

    @pytest.mark.parametrize(
        "rate",
        [
            '"project";r=zero;t=3600',
            '"project";r=0',
            ",,,",
            '"a";r=0;t=x',
            '"x"; r = 0 ; t',
        ],
    )
    def test_malformed_rate_limit(self, rate: str) -> None:
        """Malformed RateLimit values never raise."""
        info = parse_rate_limit_headers(httpx.Headers({"RateLimit": rate}))
        assert info is None or info.tripped in ("window", "concurrency")

    def test_spaces_around_params(self) -> None:
        """Spaces around parameters are tolerated."""
        headers = httpx.Headers(
            {
                "RateLimit-Policy": '"project" ; q=60 ; w=3600',
                "RateLimit": '"project" ; r=0 ; t=5',
            }
        )
        assert parse_rate_limit_headers(headers) == RateLimitInfo(60, 3600, "window")

    def test_parser_swallows_unexpected_errors(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unexpected error inside the parser gives None, not an exception."""

        def boom(value: str) -> list[Any]:
            """Raise an unexpected error.

            Args:
                value: Ignored.

            Returns:
                Never returns.
            """
            raise RuntimeError(value)

        monkeypatch.setattr(pacer_mod, "_parse_items", boom)
        assert parse_rate_limit_headers(httpx.Headers(rl_headers())) is None


# =============================================================================
# Ledger file layout
# =============================================================================


class TestLedgerFile:
    """The ledger file has the documented path, fields, and permissions."""

    def test_path_and_fields(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A reservation writes the documented JSON at the documented path."""
        make_pacer().reserve(QKEY)
        assert read_ledger(root) == {
            "v": 1,
            "limit": 60,
            "limit_source": "default",
            "learned_at": 0,
            "blocked_until": 0,
            "blocked_streak": 0,
            "sent": [NOW],
        }
        assert ledger_path(root).with_name("12345-query.json.lock").exists()

    @pytest.mark.skipif(os.name != "posix", reason="POSIX modes only")
    def test_directory_modes(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """Ledger directories are created with mode 0o700."""
        make_pacer().reserve(QKEY)
        for path in (root / "pacer", root / "pacer" / "mixpanel.com"):
            assert stat.S_IMODE(path.stat().st_mode) == 0o700

    def test_sent_pruned_to_window(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """Entries older than the window plus margin are dropped on save."""
        write_ledger(root, sent=[NOW - W - 1, NOW - W, NOW - 100])
        make_pacer().reserve(QKEY)
        assert read_ledger(root)["sent"] == [NOW - 100, NOW]


# =============================================================================
# reserve / before_send
# =============================================================================


class TestReserve:
    """``reserve`` and ``before_send`` pace counted requests."""

    def test_empty_ledger_sends_at_once(
        self, make_pacer: Callable[..., Pacer], sleeps: list[float]
    ) -> None:
        """An empty ledger gives a slot of now and no sleep."""
        request = httpx.Request("GET", f"{US_QUERY}/insights?project_id=12345")
        make_pacer().before_send(request, QKEY)
        assert sleeps == []
        assert request.extensions["mp_pacer"] == (QKEY, NOW)

    def test_none_key_is_noop(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A request with no key is not paced and touches no file."""
        request = httpx.Request("GET", "https://mixpanel.com/api/app/me")
        make_pacer().before_send(request, None)
        assert "mp_pacer" not in request.extensions
        assert not root.exists()

    def test_server_limit_waits_exactly(
        self, make_pacer: Callable[..., Pacer], root: Path, sleeps: list[float]
    ) -> None:
        """A full ledger with a server limit waits oldest + window + margin - now."""
        oldest = NOW - W + 12.0
        write_ledger(
            root,
            limit=3,
            limit_source="server",
            learned_at=NOW - 10,
            sent=[oldest, NOW - 50, NOW - 40],
        )
        request = httpx.Request("GET", f"{US_QUERY}/insights?project_id=12345")
        make_pacer().before_send(request, QKEY)
        assert sleeps == [pytest.approx(12.0)]
        assert request.extensions["mp_pacer"] == (QKEY, oldest + W)
        assert read_ledger(root)["sent"][-1] == oldest + W

    def test_wait_over_max_raises_and_writes_nothing(
        self, make_pacer: Callable[..., Pacer], root: Path, sleeps: list[float]
    ) -> None:
        """A wait longer than max_wait raises, writes nothing, and sends nothing."""
        sent = [NOW - W + 432.0] + [NOW - 10.0] * 59
        path = write_ledger(
            root, limit=60, limit_source="server", learned_at=NOW - 10, sent=sent
        )
        before = path.read_bytes()
        request = httpx.Request("GET", f"{US_QUERY}/insights?project_id=12345")
        with pytest.raises(RateLimitError) as info:
            make_pacer().before_send(request, QKEY)
        exc = info.value
        assert str(exc) == (
            "Mixpanel query budget exhausted for project 12345: 60 of 60 queries used "
            "in the last hour (Query API limit). The next slot opens at 14:20:32 UTC "
            "(in 7m 12s). No request was sent. To wait instead of failing, set "
            "MP_PACER_MAX_WAIT (seconds). Retry after 432 seconds."
        )
        assert exc.retry_after == 432
        assert exc.project_id == "12345"
        assert exc.request_method == "GET"
        assert exc.request_url == f"{US_QUERY}/insights?project_id=12345"
        assert exc.details["limit"] == 60
        assert exc.details["used"] == 60
        assert exc.details["window_seconds"] == 3600
        assert exc.details["next_slot_at"] == "2026-09-21T14:20:32Z"
        assert exc.details["limit_source"] == "server"
        assert exc.details["sent"] is False
        assert exc.details["bucket"] == "query"
        assert exc.details["reason"] == "ledger"
        assert path.read_bytes() == before
        assert sleeps == []
        assert "mp_pacer" not in request.extensions

    def test_reserve_raises_directly(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """``reserve`` itself raises when the wait is too long."""
        write_ledger(root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW])
        with pytest.raises(RateLimitError) as info:
            make_pacer().reserve(QKEY)
        assert info.value.request_url is None
        assert info.value.retry_after == math.ceil(W)
        assert "(in 60m 10s)" in str(info.value)

    def test_short_wait_message_seconds_only(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A wait under a minute prints seconds only."""
        write_ledger(
            root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW - W + 45.5]
        )
        with pytest.raises(RateLimitError) as info:
            make_pacer(max_wait_s=1.0).reserve(QKEY)
        assert "(in 46s)" in str(info.value)
        assert info.value.retry_after == 46

    def test_server_block_message(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A slot set by the server's block says so, with no guessed limit."""
        write_ledger(root, sent=[NOW - 5.0] * 3, blocked_until=NOW + 100.0)
        with pytest.raises(RateLimitError) as info:
            make_pacer().reserve(QKEY)
        assert str(info.value) == (
            "Mixpanel query budget exhausted for project 12345: the server reported "
            "the hourly limit reached, likely from other clients sharing this "
            "project. The next attempt opens at 14:15:00 UTC (in 1m 40s). No request "
            "was sent. To wait instead of failing, set MP_PACER_MAX_WAIT (seconds). "
            "Retry after 100 seconds."
        )
        assert info.value.details["reason"] == "server"
        assert info.value.details["used"] == 3

    def test_server_block_message_with_known_limit(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """With a limit the server confirmed, the block message names it."""
        write_ledger(
            root,
            limit=60,
            limit_source="server",
            learned_at=NOW,
            sent=[NOW - 5.0] * 3,
            blocked_until=NOW + 100.0,
        )
        with pytest.raises(RateLimitError) as info:
            make_pacer().reserve(QKEY)
        assert "the server reported the hourly limit (60) reached" in str(info.value)

    def test_block_that_the_ledger_explains_is_ledger_reason(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A block no later than the ledger's own slot keeps the ledger message."""
        write_ledger(
            root,
            limit=1,
            limit_source="server",
            learned_at=NOW,
            sent=[NOW],
            blocked_until=NOW + 50.0,
        )
        with pytest.raises(RateLimitError) as info:
            make_pacer().reserve(QKEY)
        assert info.value.details["reason"] == "ledger"
        assert "1 of 1 queries used" in str(info.value)

    def test_future_entries_beyond_horizon_dropped(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Entries more than one window ahead are dropped and logged once."""
        write_ledger(
            root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW + 2 * W]
        )
        pacer = make_pacer()
        assert pacer.reserve(QKEY) == NOW
        write_ledger(
            root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW + 2 * W]
        )
        assert pacer.reserve(QKEY) == NOW
        clock_warnings = [m for m in pacer_warnings(caplog) if "clock" in m]
        assert clock_warnings == [
            "Request pacer: ignoring ledger entries in the future; the system clock "
            "stepped back."
        ]

    def test_future_entries_within_max_wait_kept(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """With an unbounded wait, queued future reservations stay in the ledger."""
        write_ledger(
            root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW + 2 * W]
        )
        assert make_pacer(max_wait_s=math.inf).reserve(QKEY) == NOW + 3 * W

    def test_future_learned_at_is_clamped(
        self, make_pacer: Callable[..., Pacer], root: Path, clock: FakeClock
    ) -> None:
        """A learned_at in the future is saved as now, so the TTL still ends."""
        write_ledger(
            root, limit=3, limit_source="server", learned_at=NOW + 30 * 86400.0
        )
        pacer = make_pacer()
        pacer.reserve(QKEY)
        assert read_ledger(root)["learned_at"] == NOW
        clock.advance(LEARNED_LIMIT_TTL_S + 1)
        assert pacer.snapshot(QKEY).limit_source == "default"

    def test_reservation_two_windows_ahead_is_not_released_early(
        self, root: Path, clock: FakeClock
    ) -> None:
        """A slot two windows ahead sleeps in chunks until the clock reaches it."""
        write_ledger(
            root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW + W - 1]
        )
        sleeps: list[float] = []

        def sleeper(seconds: float) -> None:
            """Sleep by moving the fake clock forward.

            Args:
                seconds: Seconds to sleep.
            """
            sleeps.append(seconds)
            clock.advance(seconds)

        pacer = Pacer(
            PacerSettings(max_wait_s=math.inf),
            storage_root=root,
            clock=clock,
            sleep=sleeper,
        )
        request = httpx.Request("GET", US_QUERY)
        slept = pacer.before_send(request, QKEY)
        slot = NOW + 2 * W - 1
        assert request.extensions["mp_pacer"] == (QKEY, slot)
        assert slept == pytest.approx(slot - NOW)
        assert clock.now >= slot
        assert len(sleeps) == 2
        assert max(sleeps) <= W

    def test_stalled_clock_sleeps_exactly_the_wait(
        self, make_pacer: Callable[..., Pacer], root: Path, sleeps: list[float]
    ) -> None:
        """A clock that does not move during sleep still gets the full wait, once."""
        write_ledger(
            root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW + W - 1]
        )
        slept = make_pacer(max_wait_s=math.inf).before_send(
            httpx.Request("GET", US_QUERY), QKEY
        )
        assert slept == pytest.approx(2 * W - 1)
        assert sum(sleeps) == pytest.approx(2 * W - 1)
        assert max(sleeps) <= W

    def test_clock_jump_forward_ends_the_wait_early(
        self, root: Path, clock: FakeClock
    ) -> None:
        """A clock that jumps forward during a chunk is re-read, so the wait ends."""
        write_ledger(
            root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW + W - 1]
        )
        sleeps: list[float] = []

        def sleeper(seconds: float) -> None:
            """Sleep, while the wall clock jumps a whole day ahead.

            Args:
                seconds: Seconds to sleep.
            """
            sleeps.append(seconds)
            clock.advance(86400.0)

        pacer = Pacer(
            PacerSettings(max_wait_s=math.inf),
            storage_root=root,
            clock=clock,
            sleep=sleeper,
        )
        pacer.before_send(httpx.Request("GET", US_QUERY), QKEY)
        assert sleeps == [W]

    def test_horizon_keeps_reservations_within_a_day(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """With an unbounded wait, entries up to 24 h ahead stay; later ones drop."""
        pacer = make_pacer(max_wait_s=math.inf)
        write_ledger(
            root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW + 72000.0]
        )
        assert pacer.reserve(QKEY) == NOW + 72000.0 + W
        write_ledger(
            root,
            limit=1,
            limit_source="server",
            learned_at=NOW,
            sent=[NOW + 2 * 86400.0],
        )
        assert pacer.reserve(QKEY) == NOW
        assert any("clock" in m for m in pacer_warnings(caplog))

    def test_wait_equal_to_max_is_absorbed(
        self, make_pacer: Callable[..., Pacer], root: Path, sleeps: list[float]
    ) -> None:
        """A wait of exactly max_wait sleeps instead of raising."""
        write_ledger(root, blocked_until=NOW + 30.0)
        request = httpx.Request("GET", f"{US_QUERY}/insights?project_id=12345")
        make_pacer().before_send(request, QKEY)
        assert sleeps == [30.0]

    def test_default_limit_probes(
        self, make_pacer: Callable[..., Pacer], root: Path, sleeps: list[float]
    ) -> None:
        """A full ledger with the default limit sends a probe at once."""
        write_ledger(root, sent=[NOW - 100.0] * 60)
        assert make_pacer().reserve(QKEY) == NOW
        assert len(read_ledger(root)["sent"]) == 61

    def test_configured_limit_blocks_from_first_request(
        self, make_pacer: Callable[..., Pacer], clock: FakeClock
    ) -> None:
        """A configured limit blocks when full, with no probe."""
        pacer = make_pacer(query_limits={"12345": 2}, max_wait_s=math.inf)
        first = pacer.reserve(QKEY)
        clock.advance(1.0)
        pacer.reserve(QKEY)
        clock.advance(1.0)
        assert pacer.reserve(QKEY) == first + W
        snap = pacer.snapshot(QKEY)
        assert snap.limit == 2
        assert snap.limit_source == "configured"

    def test_env_limit_beats_config(self, make_pacer: Callable[..., Pacer]) -> None:
        """The process-wide limit wins over the per-project config limit."""
        pacer = make_pacer(
            query_limit=1, query_limits={"12345": 5}, max_wait_s=math.inf
        )
        pacer.reserve(QKEY)
        assert pacer.reserve(QKEY) == NOW + W

    def test_blocked_until_is_a_floor(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """``blocked_until`` delays the next slot even with an empty ledger."""
        write_ledger(root, blocked_until=NOW + 20.0)
        assert make_pacer().reserve(QKEY) == NOW + 20.0

    def test_blocked_until_capped_at_window(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A ``blocked_until`` beyond one window from now is capped."""
        write_ledger(root, blocked_until=NOW + 10 * W)
        assert make_pacer(max_wait_s=math.inf).reserve(QKEY) == NOW + W

    def test_long_wait_logs_warning(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A wait of 5 s or more logs one WARNING line."""
        write_ledger(
            root, limit=1, limit_source="server", learned_at=NOW, sent=[NOW - W + 23.0]
        )
        caplog.set_level(logging.DEBUG, logger="mixpanel_headless._internal.pacer")
        make_pacer().before_send(httpx.Request("GET", US_QUERY), QKEY)
        assert pacer_warnings(caplog) == [
            "Mixpanel query budget for project 12345: 1 of 1 used in the last hour; "
            "waiting 23s for the next slot."
        ]

    def test_short_wait_logs_debug(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A wait under 5 s logs at DEBUG only."""
        write_ledger(root, blocked_until=NOW + 4.9)
        caplog.set_level(logging.DEBUG, logger="mixpanel_headless._internal.pacer")
        make_pacer().before_send(httpx.Request("GET", US_QUERY), QKEY)
        assert pacer_warnings(caplog) == []
        assert any("waiting 5s" in r.getMessage() for r in caplog.records)

    def test_wait_of_exactly_threshold_warns(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A wait of exactly the threshold logs at WARNING."""
        write_ledger(root, blocked_until=NOW + LONG_WAIT_LOG_S)
        make_pacer().before_send(httpx.Request("GET", US_QUERY), QKEY)
        assert len(pacer_warnings(caplog)) == 1

    def test_two_pacers_share_state(
        self, root: Path, clock: FakeClock, sleeps: list[float]
    ) -> None:
        """Two Pacer objects on one storage root share one ledger."""
        settings = PacerSettings(query_limit=1, max_wait_s=math.inf)
        a = Pacer(settings, storage_root=root, clock=clock, sleep=sleeps.append)
        b = Pacer(settings, storage_root=root, clock=clock, sleep=sleeps.append)
        a.reserve(QKEY)
        assert b.reserve(QKEY) == NOW + W

    def test_threads_never_exceed_the_limit(self, root: Path) -> None:
        """Many threads all get a reservation and never exceed the limit."""
        clock = FakeClock(step=0.001)
        pacer = Pacer(
            PacerSettings(query_limit=5, max_wait_s=math.inf),
            storage_root=root,
            clock=clock,
            sleep=lambda _s: None,
        )
        slots: list[float] = []
        guard = threading.Lock()

        def worker() -> None:
            """Reserve one slot and record it."""
            slot = pacer.reserve(QKEY)
            with guard:
                slots.append(slot)

        threads = [threading.Thread(target=worker) for _ in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(slots) == 20
        ordered = sorted(slots)
        for i, start in enumerate(ordered):
            in_window = [s for s in ordered[i:] if s < start + W]
            assert len(in_window) <= 5

    def test_default_clock_sleep_and_root(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no injections, the pacer uses time.time, time.sleep, and MP_STORAGE_DIR."""
        monkeypatch.setenv("MP_STORAGE_DIR", str(tmp_path / "store"))
        slept: list[float] = []
        monkeypatch.setattr(time, "time", lambda: NOW)
        monkeypatch.setattr(time, "sleep", slept.append)
        write_ledger(tmp_path / "store", blocked_until=NOW + 3.0)
        Pacer(PacerSettings()).before_send(httpx.Request("GET", US_QUERY), QKEY)
        assert slept == [3.0]
        assert read_ledger(tmp_path / "store")["sent"] == [NOW + 3.0]


# =============================================================================
# Wait budget and sleep return
# =============================================================================


@pytest.fixture
def cli_entry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the process look like the ``mp`` CLI."""
    monkeypatch.setattr(client_metadata, "_entry_point", "cli")


class TestWaitBudget:
    """In the CLI, max_wait is a budget for the whole process."""

    def test_cli_budget_is_shared(
        self,
        cli_entry: None,
        make_pacer: Callable[..., Pacer],
        root: Path,
        sleeps: list[float],
    ) -> None:
        """Two 20 s waits with a 30 s budget: the second raises."""
        write_ledger(root, blocked_until=NOW + 20.0)
        pacer = make_pacer()
        pacer.before_send(httpx.Request("GET", US_QUERY), QKEY)
        with pytest.raises(RateLimitError):
            pacer.before_send(httpx.Request("GET", US_QUERY), QKEY)
        assert sleeps == [20.0]

    def test_library_budget_is_per_request(
        self, make_pacer: Callable[..., Pacer], root: Path, sleeps: list[float]
    ) -> None:
        """Outside the CLI, each request gets the full max wait."""
        write_ledger(root, blocked_until=NOW + 20.0)
        pacer = make_pacer()
        pacer.before_send(httpx.Request("GET", US_QUERY), QKEY)
        pacer.before_send(httpx.Request("GET", US_QUERY), QKEY)
        assert sleeps == [20.0, 20.0]

    def test_cli_budget_never_below_zero(
        self,
        cli_entry: None,
        make_pacer: Callable[..., Pacer],
        root: Path,
    ) -> None:
        """A spent budget still sends a request that needs no wait."""
        write_ledger(root, blocked_until=NOW + 20.0)
        pacer = make_pacer(max_wait_s=10.0)
        with pytest.raises(RateLimitError):
            pacer.reserve(QKEY)
        write_ledger(root)
        assert pacer.reserve(QKEY) == NOW

    def test_fork_resets_budget(
        self,
        cli_entry: None,
        make_pacer: Callable[..., Pacer],
        root: Path,
    ) -> None:
        """A forked child starts with a full budget."""
        write_ledger(root, blocked_until=NOW + 20.0)
        pacer = make_pacer()
        pacer.before_send(httpx.Request("GET", US_QUERY), QKEY)
        pacer_mod._reset_after_fork()
        pacer.before_send(httpx.Request("GET", US_QUERY), QKEY)


class TestSleepReturn:
    """``before_send`` returns the seconds it slept."""

    def test_returns_sleep(self, make_pacer: Callable[..., Pacer], root: Path) -> None:
        """A paced wait returns its length."""
        write_ledger(root, blocked_until=NOW + 12.5)
        assert make_pacer().before_send(httpx.Request("GET", US_QUERY), QKEY) == 12.5

    def test_no_wait_returns_zero(self, make_pacer: Callable[..., Pacer]) -> None:
        """A request with a free slot returns 0.0."""
        assert make_pacer().before_send(httpx.Request("GET", US_QUERY), QKEY) == 0.0

    def test_unpaced_returns_zero(
        self, make_pacer: Callable[..., Pacer], tmp_path: Path
    ) -> None:
        """No key, a disabled pacer, and a ledger failure all return 0.0."""
        request = httpx.Request("GET", US_QUERY)
        assert make_pacer().before_send(request, None) == 0.0
        disabled = Pacer(PacerSettings(enabled=False), storage_root=tmp_path / "x")
        assert disabled.before_send(request, QKEY) == 0.0
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        broken = Pacer(PacerSettings(), storage_root=blocker, clock=FakeClock())
        assert broken.before_send(request, QKEY) == 0.0

    def test_internal_error_returns_zero(
        self, make_pacer: Callable[..., Pacer], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unexpected pacer error returns 0.0."""

        def boom(*_args: object, **_kwargs: object) -> None:
            """Raise an unexpected error.

            Args:
                *_args: Ignored.
                **_kwargs: Ignored.

            Raises:
                RuntimeError: Always.
            """
            raise RuntimeError("bug")

        monkeypatch.setattr(Pacer, "_reserve", boom)
        assert make_pacer().before_send(httpx.Request("GET", US_QUERY), QKEY) == 0.0


# =============================================================================
# observe / after_response
# =============================================================================


def paced_response(
    pacer: Pacer,
    key: LedgerKey,
    status: int,
    headers: Mapping[str, str] | None = None,
    text: str = "",
) -> httpx.Response:
    """Reserve through ``before_send``, then build and observe a response.

    Args:
        pacer: The pacer.
        key: The ledger key.
        status: HTTP status code of the response.
        headers: Response headers.
        text: Response body.

    Returns:
        The observed response.
    """
    request = httpx.Request("GET", f"{US_QUERY}/insights?project_id=12345")
    pacer.before_send(request, key)
    resp = httpx.Response(
        status, headers=dict(headers or {}), text=text, request=request
    )
    pacer.after_response(resp)
    return resp


class TestObserve:
    """``observe`` and ``after_response`` learn from responses."""

    def test_success_keeps_reservation(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A 200 keeps the reservation and sets no marker."""
        resp = paced_response(make_pacer(), QKEY, 200)
        assert read_ledger(root)["sent"] == [NOW]
        assert "mp_pacer_tripped" not in resp.extensions

    def test_server_error_keeps_reservation(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A 500 keeps the reservation, because failed queries count."""
        paced_response(make_pacer(), QKEY, 500)
        assert read_ledger(root)["sent"] == [NOW]

    @pytest.mark.parametrize("status", [401, 402])
    def test_auth_and_plan_failures_refund(
        self, make_pacer: Callable[..., Pacer], root: Path, status: int
    ) -> None:
        """401 and 402 always refund."""
        paced_response(make_pacer(), QKEY, status)
        assert read_ledger(root)["sent"] == []

    def test_window_429_learns_and_refunds(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A quota 429 learns the limit, refunds, and marks a window trip."""
        resp = paced_response(make_pacer(), QKEY, 429, rl_headers(), WINDOW_BODY)
        data = read_ledger(root)
        assert data["sent"] == []
        assert data["limit"] == 60
        assert data["limit_source"] == "server"
        assert data["learned_at"] == NOW
        assert resp.extensions["mp_pacer_tripped"] == "window"

    def test_learned_limit_blocks(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """After learning the limit, a full ledger raises at once with the exact wait."""
        write_ledger(root, sent=[NOW - 5.0] * 60)
        pacer = make_pacer()
        paced_response(pacer, QKEY, 429, rl_headers(), WINDOW_BODY)
        with pytest.raises(RateLimitError) as info:
            pacer.reserve(QKEY)
        assert info.value.retry_after == math.ceil(W - 5.0)
        assert info.value.details["reason"] == "ledger"
        assert info.value.details["limit_source"] == "server"
        assert info.value.details["limit"] == 60

    def test_explained_window_trip_sets_no_block(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A window trip that the full ledger explains sets no blocked_until."""
        write_ledger(root, sent=[NOW - 5.0] * 60)
        paced_response(make_pacer(), QKEY, 429, rl_headers(), WINDOW_BODY)
        assert read_ledger(root)["blocked_until"] == 0

    def test_unexplained_window_trip_sets_block(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A window trip with room in the ledger blocks for W/limit and counts a streak."""
        write_ledger(root, sent=[NOW - 5.0] * 3)
        paced_response(make_pacer(), QKEY, 429, rl_headers(), WINDOW_BODY)
        data = read_ledger(root)
        assert data["blocked_until"] == NOW + 60.0
        assert data["blocked_streak"] == 1

    def test_unexplained_trips_back_off_exponentially(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """Each further unexplained window trip doubles the block."""
        pacer = make_pacer(max_wait_s=math.inf)
        blocks = []
        for _ in range(3):
            paced_response(pacer, QKEY, 429, rl_headers(), WINDOW_BODY)
            blocks.append(read_ledger(root)["blocked_until"])
        assert blocks == [NOW + 60.0, NOW + 120.0, NOW + 240.0]
        assert read_ledger(root)["blocked_streak"] == 3

    def test_backoff_capped_at_window(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """The backoff never blocks longer than the server window."""
        write_ledger(root, blocked_streak=10)
        paced_response(make_pacer(max_wait_s=math.inf), QKEY, 429, rl_headers())
        data = read_ledger(root)
        assert data["blocked_until"] == NOW + 3600.0
        assert data["blocked_streak"] == 11

    def test_success_resets_streak(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A 2xx counted response resets the streak to 0."""
        write_ledger(root, blocked_streak=2)
        paced_response(make_pacer(), QKEY, 200)
        assert read_ledger(root)["blocked_streak"] == 0

    def test_success_without_streak_touches_no_file(
        self, make_pacer: Callable[..., Pacer], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A 2xx with no streak adds no ledger read and no write."""
        pacer = make_pacer()
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)
        calls: list[str] = []
        real_load, real_save = Pacer._load, Pacer._save

        def spy_load(self: Pacer, *args: Any) -> Any:
            """Record a ledger read.

            Args:
                self: The pacer.
                *args: The real arguments.

            Returns:
                The real result.
            """
            calls.append("load")
            return real_load(self, *args)

        def spy_save(*args: Any) -> None:
            """Record a ledger write.

            Args:
                *args: The real arguments.
            """
            calls.append("save")
            real_save(*args)

        monkeypatch.setattr(Pacer, "_load", spy_load)
        monkeypatch.setattr(Pacer, "_save", staticmethod(spy_save))
        pacer.after_response(httpx.Response(200, request=request))
        assert calls == []

    @pytest.mark.parametrize(
        ("headers", "fill"),
        [(rl_headers(CONCURRENCY_TRIP), 0), (rl_headers(), 60)],
    )
    def test_explained_or_concurrency_trip_keeps_streak(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        headers: dict[str, str],
        fill: int,
    ) -> None:
        """A concurrency trip or a ledger-explained trip does not change the streak."""
        write_ledger(root, blocked_streak=2, sent=[NOW - 5.0] * fill)
        paced_response(make_pacer(), QKEY, 429, headers)
        assert read_ledger(root)["blocked_streak"] == 2

    def test_streak_reset_elsewhere_is_forgotten(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A streak that another process already reset is dropped from memory."""
        write_ledger(root, blocked_streak=2)
        pacer = make_pacer()
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)
        data = read_ledger(root)
        write_ledger(root, sent=data["sent"])
        pacer.after_response(httpx.Response(200, request=request))
        assert pacer._streak_keys == set()
        assert "blocked_streak" not in read_ledger(root)  # nothing to reset, no write

    def test_streak_reset_io_failure(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A streak reset that cannot write never raises and warns once."""
        write_ledger(root, blocked_streak=2)
        pacer = make_pacer()
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)
        path = ledger_path(root)
        path.unlink()
        path.mkdir()
        pacer.after_response(httpx.Response(200, request=request))
        assert any(
            m.startswith("Request pacing is off") for m in pacer_warnings(caplog)
        )

    def test_server_block_error_reports_streak(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A server-block error carries the streak in its details."""
        write_ledger(root, blocked_until=NOW + 100.0, blocked_streak=2)
        with pytest.raises(RateLimitError) as info:
            make_pacer().reserve(QKEY)
        assert info.value.details["blocked_streak"] == 2

    def test_unexplained_trip_uses_learned_limit(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """The block hint uses the limit that the 429 just taught."""
        policy = '"project";q=240;w=3600'
        paced_response(make_pacer(), QKEY, 429, rl_headers(WINDOW_TRIP, policy))
        assert read_ledger(root)["blocked_until"] == NOW + 15.0

    def test_load_shed_without_headers(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A 429 with no trip header refunds and sets no marker and no block."""
        resp = paced_response(make_pacer(), QKEY, 429, {}, LOAD_SHED_BODY)
        data = read_ledger(root)
        assert "mp_pacer_tripped" not in resp.extensions
        assert data["sent"] == []
        assert data["limit_source"] == "default"
        assert data["blocked_until"] == 0

    def test_body_text_is_not_used(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A 429 message body alone does not classify the trip."""
        resp = paced_response(make_pacer(), QKEY, 429, {}, WINDOW_BODY)
        assert "mp_pacer_tripped" not in resp.extensions

    def test_policy_without_trip_learns_nothing(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A 429 whose headers name no trip does not teach the limit."""
        paced_response(make_pacer(), QKEY, 429, {"RateLimit-Policy": POLICY})
        assert read_ledger(root)["limit_source"] == "default"

    def test_full_default_ledger_headerless_trip_sets_no_block(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A header-less 429 on a full default ledger leaves waiting to the retry loop."""
        write_ledger(root, sent=[NOW - 5.0] * 60)
        paced_response(make_pacer(), QKEY, 429, {}, LOAD_SHED_BODY)
        assert read_ledger(root)["blocked_until"] == 0

    def test_header_window_trip_without_policy_blocks(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A header-named window trip the ledger cannot explain sets blocked_until."""
        paced_response(make_pacer(), QKEY, 429, {"RateLimit": WINDOW_TRIP})
        assert read_ledger(root)["blocked_until"] == NOW + 60.0

    def test_concurrency_429_refunds_without_block(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A concurrency 429 refunds and does not set blocked_until."""
        resp = paced_response(
            make_pacer(), QKEY, 429, rl_headers(CONCURRENCY_TRIP), CONCURRENCY_BODY
        )
        data = read_ledger(root)
        assert data["sent"] == []
        assert data["blocked_until"] == 0
        assert resp.extensions["mp_pacer_tripped"] == "concurrency"

    def test_plain_query_429_ignores_retry_after(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A plain query 429 with a Retry-After still sets no block and no marker."""
        resp = paced_response(make_pacer(), QKEY, 429, {"Retry-After": "120"})
        assert read_ledger(root)["blocked_until"] == 0
        assert "mp_pacer_tripped" not in resp.extensions

    def test_learned_limit_expires(
        self, make_pacer: Callable[..., Pacer], root: Path, clock: FakeClock
    ) -> None:
        """A learned limit returns to the default after the TTL."""
        write_ledger(root, limit=3, limit_source="server", learned_at=NOW)
        pacer = make_pacer()
        clock.advance(LEARNED_LIMIT_TTL_S - 1)
        assert pacer.snapshot(QKEY).limit == 3
        clock.advance(2)
        snap = pacer.snapshot(QKEY)
        assert (snap.limit, snap.limit_source) == (60, "default")
        pacer.reserve(QKEY)
        data = read_ledger(root)
        assert (data["limit"], data["limit_source"], data["learned_at"]) == (
            60,
            "default",
            0,
        )

    def test_server_overrides_configured_limit(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        clock: FakeClock,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A 429 overrides a too-high configured limit and logs one warning."""
        pacer = make_pacer(query_limits={"12345": 240}, max_wait_s=math.inf)
        assert pacer.snapshot(QKEY).limit == 240
        paced_response(pacer, QKEY, 429, rl_headers(), WINDOW_BODY)
        paced_response(pacer, QKEY, 429, rl_headers(), WINDOW_BODY)
        snap = pacer.snapshot(QKEY)
        assert (snap.limit, snap.limit_source) == (60, "server")
        configured = [m for m in pacer_warnings(caplog) if m.startswith("configured")]
        assert configured == [
            "configured query limit 240 for project 12345, but the server reports 60"
        ]
        clock.advance(LEARNED_LIMIT_TTL_S + 1)
        snap = pacer.snapshot(QKEY)
        assert (snap.limit, snap.limit_source) == (240, "configured")

    def test_configured_limit_is_a_ceiling(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A configured limit below the server's stays in force and warns once."""
        pacer = make_pacer(query_limits={"12345": 40})
        paced_response(pacer, QKEY, 429, rl_headers(), WINDOW_BODY)
        snap = pacer.snapshot(QKEY)
        assert (snap.limit, snap.limit_source) == (40, "configured")
        data = read_ledger(root)
        assert (data["limit"], data["limit_source"]) == (60, "server")
        configured = [m for m in pacer_warnings(caplog) if m.startswith("configured")]
        assert configured == [
            "configured query limit 40 for project 12345, but the server reports 60"
        ]

    def test_stored_server_limit_with_lower_configured(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A stored server limit above the configured one keeps the configured one."""
        write_ledger(root, limit=240, limit_source="server", learned_at=NOW)
        snap = make_pacer(query_limit=100).snapshot(QKEY)
        assert (snap.limit, snap.limit_source) == (100, "configured")
        make_pacer(query_limit=100).reserve(QKEY)
        assert read_ledger(root)["limit"] == 240

    def test_matching_configured_limit_no_warning(
        self, make_pacer: Callable[..., Pacer], caplog: pytest.LogCaptureFixture
    ) -> None:
        """A 429 that confirms the configured limit logs no warning."""
        paced_response(make_pacer(query_limit=60), QKEY, 429, rl_headers(), WINDOW_BODY)
        assert pacer_warnings(caplog) == []

    def test_after_response_does_not_read_body(
        self, make_pacer: Callable[..., Pacer]
    ) -> None:
        """The pacer never reads a 429 body; the stream stays unread."""
        pacer = make_pacer()
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)
        resp = httpx.Response(
            429,
            headers=rl_headers(CONCURRENCY_TRIP),
            stream=httpx.ByteStream(b"body"),
            request=request,
        )
        pacer.after_response(resp)
        assert resp.extensions["mp_pacer_tripped"] == "concurrency"
        assert not resp.is_stream_consumed

    def test_after_response_without_extension(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A response to an unpaced request is ignored."""
        resp = response(429, rl_headers())
        make_pacer().after_response(resp)
        assert "mp_pacer_tripped" not in resp.extensions
        assert not root.exists()

    def test_after_response_without_request(
        self, make_pacer: Callable[..., Pacer]
    ) -> None:
        """A response with no request attached is ignored."""
        make_pacer().after_response(httpx.Response(429))

    def test_after_response_bad_extension(
        self, make_pacer: Callable[..., Pacer]
    ) -> None:
        """A malformed pacer extension is ignored."""
        resp = response(429)
        resp.request.extensions["mp_pacer"] = "garbage"
        make_pacer().after_response(resp)
        assert "mp_pacer_tripped" not in resp.extensions

    def test_observe_direct(self, make_pacer: Callable[..., Pacer], root: Path) -> None:
        """``observe`` can be called directly with a key and slot."""
        pacer = make_pacer()
        slot = pacer.reserve(QKEY)
        pacer.observe(QKEY, slot, response(401))
        assert read_ledger(root)["sent"] == []

    def test_refund_removes_one_entry_only(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A refund removes one matching entry, not every equal entry."""
        pacer = make_pacer()
        slot = pacer.reserve(QKEY)
        pacer.reserve(QKEY)
        pacer.observe(QKEY, slot, response(401))
        assert read_ledger(root)["sent"] == [NOW]

    def test_refund_of_unknown_slot_is_harmless(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A refund for a slot not in the ledger changes no entry."""
        pacer = make_pacer()
        pacer.reserve(QKEY)
        pacer.observe(QKEY, NOW - 1.0, response(401))
        assert read_ledger(root)["sent"] == [NOW]


# =============================================================================
# refund
# =============================================================================


class TestRefund:
    """``refund`` removes a reservation for a request the server never saw."""

    def test_refund_removes_reservation(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A refund removes the entry and pops the marker."""
        pacer = make_pacer()
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)
        pacer.refund(request)
        assert read_ledger(root)["sent"] == []
        assert "mp_pacer" not in request.extensions

    def test_second_refund_is_noop(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A second refund of the same request removes nothing more."""
        pacer = make_pacer()
        first = httpx.Request("GET", US_QUERY)
        second = httpx.Request("GET", US_QUERY)
        pacer.before_send(first, QKEY)
        pacer.before_send(second, QKEY)
        pacer.refund(first)
        pacer.refund(first)
        assert read_ledger(root)["sent"] == [NOW]

    def test_refund_without_marker(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A request that was not paced is ignored and no file is touched."""
        make_pacer().refund(httpx.Request("GET", US_QUERY))
        assert not root.exists()

    def test_refund_disabled(self, tmp_path: Path) -> None:
        """A disabled pacer does nothing on refund."""
        request = httpx.Request("GET", US_QUERY)
        request.extensions["mp_pacer"] = (QKEY, NOW)
        Pacer(PacerSettings(enabled=False), storage_root=tmp_path / "x").refund(request)
        assert not (tmp_path / "x").exists()

    def test_refund_io_failure(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A refund that cannot update the ledger never raises and warns once."""
        pacer = make_pacer()
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)
        path = ledger_path(root)
        path.unlink()
        path.mkdir()
        pacer.refund(request)
        assert any(
            m.startswith("Request pacing is off") for m in pacer_warnings(caplog)
        )

    def test_refund_bad_marker(
        self, make_pacer: Callable[..., Pacer], caplog: pytest.LogCaptureFixture
    ) -> None:
        """A malformed marker never raises; it is an internal error."""
        request = httpx.Request("GET", US_QUERY)
        request.extensions["mp_pacer"] = "garbage"
        make_pacer().refund(request)
        assert pacer_warnings(caplog) == [
            "Request pacer internal error; requests go out unpaced; please report."
        ]


# =============================================================================
# Disabled pacer
# =============================================================================


class TestDisabled:
    """A disabled pacer does nothing and touches no file."""

    def test_no_filesystem_access(self, tmp_path: Path, sleeps: list[float]) -> None:
        """Every method is a no-op and the storage root is never created."""
        root = tmp_path / "does-not-exist"
        pacer = Pacer(
            PacerSettings(enabled=False),
            storage_root=root,
            clock=FakeClock(),
            sleep=sleeps.append,
        )
        request = httpx.Request("GET", f"{US_QUERY}/insights?project_id=12345")
        pacer.before_send(request, QKEY)
        resp = httpx.Response(429, headers=rl_headers(), request=request)
        pacer.after_response(resp)
        assert pacer.reserve(QKEY) == NOW
        pacer.observe(QKEY, NOW, resp)
        snap = pacer.snapshot(QKEY)
        assert snap == LedgerSnapshot(
            limit=60,
            limit_source="default",
            used=0,
            next_slot_at=NOW,
            blocked_until=0.0,
            window_seconds=3600.0,
        )
        assert "mp_pacer" not in request.extensions
        assert "mp_pacer_tripped" not in resp.extensions
        assert sleeps == []
        assert not root.exists()


# =============================================================================
# Snapshot
# =============================================================================


class TestSnapshot:
    """``snapshot`` reports the ledger state without writing."""

    def test_empty(self, make_pacer: Callable[..., Pacer], root: Path) -> None:
        """An empty ledger reports the default limit and a slot of now."""
        snap = make_pacer().snapshot(QKEY)
        assert snap == LedgerSnapshot(60, "default", 0, NOW, 0.0, 3600.0)
        assert not root.exists()

    def test_full_server_ledger(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A full server ledger reports its next slot."""
        write_ledger(
            root,
            limit=2,
            limit_source="server",
            learned_at=NOW,
            sent=[NOW - 100.0, NOW - 50.0],
            blocked_until=NOW - 1,
        )
        before = ledger_path(root).read_bytes()
        snap = make_pacer().snapshot(QKEY)
        assert (snap.used, snap.next_slot_at) == (2, NOW - 100.0 + W)
        assert snap.blocked_until == NOW - 1
        assert ledger_path(root).read_bytes() == before

    def test_snapshot_fails_open(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A snapshot over an unreadable ledger reports the defaults."""
        path = ledger_path(root)
        path.mkdir(parents=True)  # a directory where the file should be
        assert make_pacer().snapshot(QKEY).used == 0


# =============================================================================
# Failure behavior
# =============================================================================


class TestFailOpen:
    """Pacer failures never block a request."""

    @pytest.mark.parametrize(
        "content",
        [
            "{not json",
            "[1, 2]",
            '{"v": 2, "sent": []}',
            '{"v": 1, "limit": "x", "limit_source": "default", "learned_at": 0, '
            '"blocked_until": 0, "sent": []}',
            '{"v": 1, "limit": 60, "limit_source": "weird", "learned_at": 0, '
            '"blocked_until": 0, "sent": []}',
            '{"v": 1, "limit": 60, "limit_source": "default", "learned_at": 0, '
            '"blocked_until": 0, "sent": ["a"]}',
            '{"v": 1, "limit": 0, "limit_source": "default", "learned_at": 0, '
            '"blocked_until": 0, "sent": []}',
            '{"v": 1, "limit": true, "limit_source": "default", "learned_at": 0, '
            '"blocked_until": 0, "sent": [true]}',
            '{"v": 1, "limit": 60, "limit_source": "server", "learned_at": 0, '
            '"blocked_until": "x", "sent": []}',
            '{"v": 1, "limit": 60, "limit_source": "server", "learned_at": 0, '
            '"blocked_until": NaN, "sent": []}',
            '{"v": 1, "limit": 60, "limit_source": "default", "learned_at": 0, '
            '"blocked_until": 0, "blocked_streak": -1, "sent": []}',
            '{"v": 1, "limit": 60, "limit_source": "default", "learned_at": 0, '
            '"blocked_until": 0, "blocked_streak": true, "sent": []}',
            '{"v": 1, "limit": 60, "limit_source": "server", "learned_at": 0, '
            '"blocked_until": 1e400, "sent": []}',
            "[" * 100_000,
        ],
    )
    def test_corrupt_ledger_rewritten(
        self, make_pacer: Callable[..., Pacer], root: Path, content: str
    ) -> None:
        """A corrupt ledger is treated as empty and rewritten on save."""
        path = ledger_path(root)
        path.parent.mkdir(parents=True)
        path.write_text(content, encoding="utf-8")
        assert make_pacer().reserve(QKEY) == NOW
        assert read_ledger(root)["sent"] == [NOW]

    def test_unwritable_storage(
        self,
        tmp_path: Path,
        clock: FakeClock,
        sleeps: list[float],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A storage root that cannot hold directories sends unpaced and warns once."""
        blocker = tmp_path / "file"
        blocker.write_text("x", encoding="utf-8")
        pacer = Pacer(
            PacerSettings(), storage_root=blocker, clock=clock, sleep=sleeps.append
        )
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)
        assert "mp_pacer" not in request.extensions
        assert pacer.reserve(QKEY) == NOW
        pacer.observe(QKEY, NOW, response(429, rl_headers()))
        assert pacer_warnings(caplog) == [
            "Request pacing is off for this process: cannot use the ledger under "
            f"{blocker} (FileExistsError). Requests go out unpaced."
        ]

    def test_unexpected_error_in_before_send(
        self,
        make_pacer: Callable[..., Pacer],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """An unexpected exception inside the pacer lets the request proceed."""

        def boom(*_args: object, **_kwargs: object) -> None:
            """Raise an unexpected error.

            Args:
                *_args: Ignored.
                **_kwargs: Ignored.

            Raises:
                RuntimeError: Always.
            """
            raise RuntimeError("bug")

        monkeypatch.setattr(Pacer, "_reserve", boom)
        request = httpx.Request("GET", US_QUERY)
        make_pacer().before_send(request, QKEY)
        make_pacer().before_send(request, QKEY)
        assert "mp_pacer" not in request.extensions
        assert pacer_warnings(caplog) == [
            "Request pacer internal error; requests go out unpaced; please report."
        ]

    def test_report_internal_error_warns_once(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The public helper logs the fixed internal-error warning once per process."""
        report_internal_error()
        report_internal_error()
        assert pacer_warnings(caplog) == [
            "Request pacer internal error; requests go out unpaced; please report."
        ]

    def test_report_internal_error_shares_dedup_with_pacer(
        self,
        make_pacer: Callable[..., Pacer],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A hook error after the helper adds no second internal-error warning."""

        def boom(*_args: object, **_kwargs: object) -> None:
            """Raise an unexpected error.

            Args:
                *_args: Ignored.
                **_kwargs: Ignored.

            Raises:
                RuntimeError: Always.
            """
            raise RuntimeError("bug")

        report_internal_error()
        monkeypatch.setattr(Pacer, "_reserve", boom)
        make_pacer().before_send(httpx.Request("GET", US_QUERY), QKEY)
        assert len(pacer_warnings(caplog)) == 1

    def test_type_error_is_an_internal_error(
        self,
        make_pacer: Callable[..., Pacer],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A TypeError is a bug, not an I/O failure, and gets the internal-error warning."""

        def boom(*_args: object, **_kwargs: object) -> None:
            """Raise a TypeError.

            Args:
                *_args: Ignored.
                **_kwargs: Ignored.

            Raises:
                TypeError: Always.
            """
            raise TypeError("bug")

        monkeypatch.setattr(Pacer, "_load", boom)
        make_pacer().before_send(httpx.Request("GET", US_QUERY), QKEY)
        assert pacer_warnings(caplog) == [
            "Request pacer internal error; requests go out unpaced; please report."
        ]

    def test_unexpected_error_in_after_response(
        self, make_pacer: Callable[..., Pacer], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An unexpected exception while observing never escapes."""
        pacer = make_pacer()
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)

        def boom(*_args: object, **_kwargs: object) -> None:
            """Raise an unexpected error.

            Args:
                *_args: Ignored.
                **_kwargs: Ignored.
            """
            raise RuntimeError("bug")

        monkeypatch.setattr(Pacer, "_observe", boom)
        resp = httpx.Response(429, request=request)
        pacer.after_response(resp)
        assert "mp_pacer_tripped" not in resp.extensions

    def test_observe_io_failure_sets_no_marker(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """When the ledger cannot be updated, the 429 carries no marker."""
        pacer = make_pacer()
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)
        path = ledger_path(root)
        path.unlink()
        path.mkdir()  # the save now fails
        resp = httpx.Response(429, headers=rl_headers(), request=request)
        pacer.after_response(resp)
        assert "mp_pacer_tripped" not in resp.extensions

    def test_unsafe_key_fails_open(
        self, make_pacer: Callable[..., Pacer], tmp_path: Path
    ) -> None:
        """A key with an unsafe project id writes nothing and sends unpaced."""
        key = LedgerKey(host="mixpanel.com", project_id="../../escape", bucket="query")
        assert make_pacer().reserve(key) == NOW
        assert not list(tmp_path.rglob("*escape*"))

    def test_unsafe_host_is_sanitized(
        self, make_pacer: Callable[..., Pacer], root: Path
    ) -> None:
        """A host with path characters is sanitized into one directory name."""
        key = LedgerKey(host="../evil:1", project_id="1", bucket="query")
        make_pacer().reserve(key)
        assert (root / "pacer" / ".._evil_1" / "1-query.json").exists()

    @pytest.mark.parametrize("host", ["", ".", ".."])
    def test_dot_hosts_are_sanitized(
        self, make_pacer: Callable[..., Pacer], root: Path, host: str
    ) -> None:
        """Empty and dot hosts map to a safe directory name."""
        make_pacer().reserve(LedgerKey(host=host, project_id="1", bucket="query"))
        assert (root / "pacer" / "_" / "1-query.json").exists()

    def test_file_lock_failure_falls_back(
        self,
        make_pacer: Callable[..., Pacer],
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """When the OS file lock fails, the thread lock works and one warning logs."""

        def fail(_fd: int) -> bool:
            """Fail like a file system with no lock support.

            Args:
                _fd: Ignored.

            Returns:
                Never returns.

            Raises:
                OSError: Always.
            """
            raise OSError("no locks")

        monkeypatch.setattr(pacer_mod, "_try_lock_fd", fail)
        pacer = make_pacer(query_limit=1, max_wait_s=math.inf)
        pacer.reserve(QKEY)
        assert pacer.reserve(QKEY) == NOW + W
        lock_warnings = [m for m in pacer_warnings(caplog) if "thread lock" in m]
        assert lock_warnings == [
            "Request pacing uses a thread lock only: processes on this machine are "
            "not paced together."
        ]

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX flock only")
    def test_busy_lock_times_out_and_fails_open(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A lock held elsewhere past the timeout sends the request unpaced."""
        import fcntl

        pacer = make_pacer()
        pacer.reserve(QKEY)
        monkeypatch.setattr(pacer_mod, "_LOCK_TIMEOUT_S", 0.0)
        lock_path = ledger_path(root).with_name("12345-query.json.lock")
        with open(lock_path, "a+b") as holder:
            fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
            request = httpx.Request("GET", US_QUERY)
            pacer.before_send(request, QKEY)
        assert "mp_pacer" not in request.extensions
        assert read_ledger(root)["sent"] == [NOW]
        assert any("(TimeoutError)" in m for m in pacer_warnings(caplog))

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX flock only")
    def test_busy_lock_retries_until_free(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A lock released before the timeout is taken after a short retry."""
        import fcntl

        pacer = make_pacer()
        pacer.reserve(QKEY)
        lock_path = ledger_path(root).with_name("12345-query.json.lock")
        holder = open(lock_path, "a+b")  # noqa: SIM115 - closed by the fake sleep
        fcntl.flock(holder.fileno(), fcntl.LOCK_EX)
        retries: list[float] = []

        def release(seconds: float) -> None:
            """Release the held lock instead of sleeping.

            Args:
                seconds: The retry delay.
            """
            retries.append(seconds)
            holder.close()

        monkeypatch.setattr(time, "sleep", release)
        assert pacer.reserve(QKEY) == NOW
        assert len(retries) == 1
        assert read_ledger(root)["sent"] == [NOW, NOW]

    def test_lock_is_on_the_sidecar(
        self,
        make_pacer: Callable[..., Pacer],
        root: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The OS lock is on the .lock file; saves replace the data file inode."""
        locked_inodes: list[int] = []
        real_try_lock = pacer_mod._try_lock_fd

        def spy(fd: int) -> bool:
            """Record the inode of the locked file, then lock it.

            Args:
                fd: The file descriptor to lock.

            Returns:
                The result of the real lock attempt.
            """
            locked_inodes.append(os.fstat(fd).st_ino)
            return real_try_lock(fd)

        monkeypatch.setattr(pacer_mod, "_try_lock_fd", spy)
        pacer = make_pacer()
        pacer.reserve(QKEY)
        data_inode_1 = ledger_path(root).stat().st_ino
        pacer.reserve(QKEY)
        data_inode_2 = ledger_path(root).stat().st_ino
        lock_inode = ledger_path(root).with_name("12345-query.json.lock").stat().st_ino
        assert locked_inodes == [lock_inode, lock_inode]
        assert data_inode_1 != data_inode_2

    def test_reset_after_fork(self) -> None:
        """The after-fork hook replaces the thread-lock registry and warn-once memory."""
        pacer_mod._warn_once("something")
        old_locks = pacer_mod._thread_locks
        old_guard = pacer_mod._thread_locks_guard
        pacer_mod._reset_after_fork()
        assert pacer_mod._thread_locks is not old_locks
        assert pacer_mod._thread_locks_guard is not old_guard
        assert pacer_mod._thread_locks == {}
        assert pacer_mod._warned == set()


# =============================================================================
# Edge cases
# =============================================================================


class TestEdgeCases:
    """Small branches that the main groups do not reach."""

    def test_config_max_wait_wrong_type(
        self, config_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A config max wait that is neither a number nor a string is ignored."""
        write_config(config_file, "[settings]\npacer_max_wait = [1]\n")
        assert load_pacer_settings().max_wait_s == DEFAULT_MAX_WAIT_S
        assert len(pacer_warnings(caplog)) == 1

    def test_engage_invalid_json_body_counts(self) -> None:
        """An engage body that looks like JSON but is not still counts."""
        url = httpx.URL(f"{US_ENGAGE}?project_id=12345")
        assert classify(url, "engage", US_ENGAGE, content=b'{"session_id": ') == QKEY

    def test_escaped_quote_in_header(self) -> None:
        """An escaped quote inside an item name never raises or misreads a quota."""
        headers = httpx.Headers(
            {"RateLimit-Policy": '"pro\\"ject";q=7;w=60, "project";q=60;w=3600'}
        )
        info = parse_rate_limit_headers(headers)
        assert info is None or info.window_quota == 60

    def test_unreadable_body_is_ignored(self, make_pacer: Callable[..., Pacer]) -> None:
        """A 429 whose body cannot be read is still observed from its headers."""

        class BrokenStream(httpx.SyncByteStream):
            """A response stream that fails when read."""

            def __iter__(self) -> Iterator[bytes]:
                """Fail at once.

                Returns:
                    Never returns.

                Raises:
                    httpx.ReadError: Always.
                """
                raise httpx.ReadError("broken")

        pacer = make_pacer()
        request = httpx.Request("GET", US_QUERY)
        pacer.before_send(request, QKEY)
        resp = httpx.Response(
            429,
            headers=rl_headers(CONCURRENCY_TRIP),
            stream=BrokenStream(),
            request=request,
        )
        pacer.after_response(resp)
        assert resp.extensions["mp_pacer_tripped"] == "concurrency"

    def test_settings_property(self) -> None:
        """The pacer exposes its settings."""
        settings = PacerSettings(max_wait_s=1.0)
        assert Pacer(settings).settings is settings

    def test_observe_swallows_unexpected_errors(
        self, make_pacer: Callable[..., Pacer], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``observe`` never raises, even on a bug inside the pacer."""

        def boom(*_args: object, **_kwargs: object) -> None:
            """Raise an unexpected error.

            Args:
                *_args: Ignored.
                **_kwargs: Ignored.
            """
            raise RuntimeError("bug")

        monkeypatch.setattr(Pacer, "_observe", boom)
        make_pacer().observe(QKEY, NOW, response(429))
