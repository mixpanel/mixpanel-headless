"""Tests for how MixpanelAPIClient works with the shared query ledger (pacer).

Tests use httpx.MockTransport for deterministic HTTP mocking and record
``time.sleep`` calls instead of waiting.
"""

from __future__ import annotations

import json
import logging
import math
import os
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from mixpanel_headless._internal import api_client as api_client_module
from mixpanel_headless._internal import pacer as pacer_module
from mixpanel_headless._internal.api_client import (
    PACER_TRIPPED_EXTENSION,
    MixpanelAPIClient,
    pacer_window_tripped,
)
from mixpanel_headless._internal.auth.session import Session
from mixpanel_headless._internal.pacer import LedgerKey, Pacer, PacerSettings
from mixpanel_headless._internal.pagination import paginate_all
from mixpanel_headless.exceptions import MixpanelHeadlessError, RateLimitError
from tests.conftest import _MP_ENV_VARS, make_session

#: Retry-After value the fake server sends with every 429 in these tests.
_RETRY_AFTER_S = 45


@pytest.fixture
def test_credentials() -> Session:
    """Create service-account test credentials."""
    return make_session(
        username="test_user",
        secret="test_secret",
        project_id="12345",
        region="us",
    )


@pytest.fixture
def recorded_sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """Capture every ``time.sleep`` call instead of waiting.

    Args:
        monkeypatch: pytest monkeypatch fixture (restores ``time.sleep``).

    Returns:
        A list that accumulates the seconds passed to each ``time.sleep``
        call, in order.
    """
    calls: list[float] = []

    def fake_sleep(seconds: float) -> None:
        """Record a sleep instead of performing it.

        Args:
            seconds: Requested sleep duration.
        """
        calls.append(seconds)

    monkeypatch.setattr(time, "sleep", fake_sleep)
    return calls


def _one_429_then(
    success: httpx.Response, tripped: str | None
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a handler that answers 429 once, then the given success response.

    Args:
        success: Response to return from the second request on.
        tripped: Value for the pacer marker extension on the 429, or ``None``
            to send the 429 with no marker.

    Returns:
        A MockTransport handler.
    """
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a 429 on the first call and the success response after.

        Args:
            request: The incoming request.

        Returns:
            The rate-limit response or the success response.
        """
        nonlocal calls
        calls += 1
        if calls == 1:
            extensions: dict[str, Any] = (
                {} if tripped is None else {PACER_TRIPPED_EXTENSION: tripped}
            )
            return httpx.Response(
                429,
                json={"error": "rate limited"},
                headers={"Retry-After": str(_RETRY_AFTER_S)},
                extensions=extensions,
            )
        return success

    return handler


def _client(
    credentials: Session, handler: Callable[[httpx.Request], httpx.Response]
) -> MixpanelAPIClient:
    """Create a client with a mock transport.

    Args:
        credentials: Session for the client.
        handler: MockTransport handler.

    Returns:
        The client.
    """
    return MixpanelAPIClient(
        session=credentials, _transport=httpx.MockTransport(handler)
    )


def _run_execute_with_retry(client: MixpanelAPIClient) -> None:
    """Send one Query API request through ``_execute_with_retry``.

    Args:
        client: Client under test.
    """
    client.request("GET", "https://mixpanel.com/api/query/segmentation")


def _run_app_request(client: MixpanelAPIClient) -> None:
    """Send one App API request through ``app_request``.

    Args:
        client: Client under test.
    """
    client.app_request("GET", "/projects/12345/items")


def _run_export(client: MixpanelAPIClient) -> None:
    """Stream one export through ``export_events``.

    Args:
        client: Client under test.
    """
    list(client.export_events("2024-01-01", "2024-01-01"))


def _run_short_link(client: MixpanelAPIClient) -> None:
    """Send one shortlink GET through ``_get_short_link``.

    Args:
        client: Client under test.
    """
    client._get_short_link("https://mixpanel.com/s/abc")


def _run_paginate_all(client: MixpanelAPIClient) -> None:
    """Walk one paginated App API listing through ``paginate_all``.

    Args:
        client: Client under test.
    """
    list(paginate_all(client, "/projects/12345/items"))


_SEND_PATHS: list[tuple[str, Callable[[MixpanelAPIClient], None], httpx.Response]] = [
    (
        "execute_with_retry",
        _run_execute_with_retry,
        httpx.Response(200, json={"ok": True}),
    ),
    (
        "app_request",
        _run_app_request,
        httpx.Response(200, json={"status": "ok", "results": []}),
    ),
    (
        "export_events",
        _run_export,
        httpx.Response(200, content=b'{"event": "A", "properties": {}}\n'),
    ),
    ("get_short_link", _run_short_link, httpx.Response(200, text="ok")),
    (
        "paginate_all",
        _run_paginate_all,
        httpx.Response(
            200,
            json={
                "status": "ok",
                "results": [{"id": 1}],
                "pagination": {"page_size": 100, "next_cursor": None},
            },
        ),
    ),
]
_SEND_PATH_IDS = [name for name, _, _ in _SEND_PATHS]


class TestTestIsolation:
    """The autouse test fixture keeps the pacer off and its settings unset."""

    def test_pacer_is_off_in_every_test(self) -> None:
        """``MP_PACER`` is ``off`` unless a test opts back in."""
        assert os.environ.get("MP_PACER") == "off"

    def test_pacer_settings_env_vars_are_scrubbed(self) -> None:
        """The pacer tuning variables are in the scrubbed list and unset."""
        assert "MP_PACER_MAX_WAIT" in _MP_ENV_VARS
        assert "MP_PACER_QUERY_LIMIT" in _MP_ENV_VARS
        assert "MP_PACER_MAX_WAIT" not in os.environ
        assert "MP_PACER_QUERY_LIMIT" not in os.environ


class TestPacerWindowTripped:
    """Test the helper that reads the pacer marker from a response."""

    def test_window_marker_is_tripped(self) -> None:
        """A ``window`` marker reports a window trip."""
        response = httpx.Response(429, extensions={PACER_TRIPPED_EXTENSION: "window"})
        assert pacer_window_tripped(response) is True

    def test_concurrency_marker_is_not_a_window_trip(self) -> None:
        """A ``concurrency`` marker keeps the ordinary retry wait."""
        response = httpx.Response(
            429, extensions={PACER_TRIPPED_EXTENSION: "concurrency"}
        )
        assert pacer_window_tripped(response) is False

    def test_no_marker_is_not_a_window_trip(self) -> None:
        """A response with no marker is not a window trip."""
        assert pacer_window_tripped(httpx.Response(429)) is False


class TestRetryWaitAfterPacerTrip:
    """Every 429 retry loop skips its own wait after a pacer window trip."""

    @pytest.mark.parametrize(
        ("name", "run", "success"), _SEND_PATHS, ids=_SEND_PATH_IDS
    )
    def test_window_trip_retries_with_zero_wait(
        self,
        test_credentials: Session,
        recorded_sleeps: list[float],
        name: str,
        run: Callable[[MixpanelAPIClient], None],
        success: httpx.Response,
    ) -> None:
        """A 429 marked ``window`` retries at once; the pacer owns the wait.

        Args:
            test_credentials: Session fixture.
            recorded_sleeps: Recorded ``time.sleep`` durations.
            name: Send path id.
            run: Callable that drives the send path.
            success: Response returned after the 429.
        """
        with _client(test_credentials, _one_429_then(success, "window")) as client:
            run(client)
        assert recorded_sleeps == [0.0], name

    @pytest.mark.parametrize("tripped", [None, "concurrency"])
    @pytest.mark.parametrize(
        ("name", "run", "success"), _SEND_PATHS, ids=_SEND_PATH_IDS
    )
    def test_other_429_keeps_retry_after_wait(
        self,
        test_credentials: Session,
        recorded_sleeps: list[float],
        name: str,
        run: Callable[[MixpanelAPIClient], None],
        success: httpx.Response,
        tripped: str | None,
    ) -> None:
        """A 429 with no marker, or a concurrency marker, waits as before.

        Args:
            test_credentials: Session fixture.
            recorded_sleeps: Recorded ``time.sleep`` durations.
            name: Send path id.
            run: Callable that drives the send path.
            success: Response returned after the 429.
            tripped: Marker value on the 429, or ``None`` for no marker.
        """
        with _client(test_credentials, _one_429_then(success, tripped)) as client:
            run(client)
        assert recorded_sleeps == [float(_RETRY_AFTER_S)], name


# =============================================================================
# Event hooks: the pacer sees every send
# =============================================================================

#: Ledger key of a Query API request from the ``test_credentials`` session.
_QUERY_KEY = LedgerKey(host="mixpanel.com", project_id="12345", bucket="query")

#: ``RateLimit-Policy`` of a real Query API 429 (quota 2 for these tests).
_POLICY_Q2 = '"project";q=2;w=3600, "project-concurrency";q=5;qu="concurrent-requests"'

#: ``RateLimit`` header of a real Query API window trip.
_WINDOW_TRIP = '"project";r=0;t=3600, "project-concurrency";r=3'


@pytest.fixture
def pacer_on(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Turn the pacer on with ledgers and config under a temporary directory.

    Args:
        monkeypatch: pytest monkeypatch fixture.
        tmp_path: Temporary directory for this test.

    Returns:
        The storage root (``MP_STORAGE_DIR``) that holds the ledgers.
    """
    storage = tmp_path / "storage"
    # tests/conftest.py pins the library entry point; also start each test
    # with an unused process wait budget.
    pacer_module.reset_wait_budget()
    monkeypatch.setenv("MP_PACER", "on")
    monkeypatch.setenv("MP_STORAGE_DIR", str(storage))
    monkeypatch.setenv("MP_CONFIG_PATH", str(tmp_path / "config.toml"))
    return storage


class _FakeTime:
    """A clock and a sleep function; each sleep advances the clock."""

    def __init__(self, start: float = 1_000_000.0) -> None:
        """Start the clock.

        Args:
            start: Initial epoch seconds.
        """
        self.now = start
        self.sleeps: list[float] = []

    def clock(self) -> float:
        """Return the current fake time.

        Returns:
            Epoch seconds.
        """
        return self.now

    def sleep(self, seconds: float) -> None:
        """Record a sleep and advance the clock by it.

        Args:
            seconds: Seconds to sleep.
        """
        self.sleeps.append(seconds)
        self.now += seconds


def _install_pacer(
    client: MixpanelAPIClient, fake: _FakeTime, settings: PacerSettings
) -> Pacer:
    """Replace a client's pacer with one on a fake clock.

    The hooks read ``client._pacer`` at each call, so the swap takes effect
    for the next request.

    Args:
        client: Client under test.
        fake: Fake clock and sleep.
        settings: Pacer settings.

    Returns:
        The installed pacer.
    """
    client._ensure_client()
    pacer = Pacer(settings, clock=fake.clock, sleep=fake.sleep)
    client._pacer = pacer
    return pacer


def _ok_json(payload: dict[str, Any]) -> Callable[[httpx.Request], httpx.Response]:
    """Build a handler that answers 200 with a JSON body.

    Args:
        payload: The JSON body.

    Returns:
        A MockTransport handler.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the JSON body.

        Args:
            request: The incoming request.

        Returns:
            A 200 response.
        """
        del request
        return httpx.Response(200, json=payload)

    return handler


def _universal_handler(request: httpx.Request) -> httpx.Response:
    """Answer any request from the send-path table with a valid 200.

    Args:
        request: The incoming request.

    Returns:
        A response shaped for the path of the request.
    """
    path = request.url.path
    if path.startswith("/api/2.0/export"):
        return httpx.Response(200, content=b'{"event": "A", "properties": {}}\n')
    if path.startswith("/s/"):
        return httpx.Response(200, text="ok")
    if path.endswith("/download/"):
        return httpx.Response(200, content=b"id,name\n1,a\n")
    if path.endswith("/lookup-tables/"):
        return httpx.Response(200, json={"status": "ok", "results": {"id": 1}})
    return httpx.Response(
        200,
        json={
            "status": "ok",
            "results": [],
            "pagination": {"page_size": 100, "next_cursor": None},
        },
    )


_HOOKED_SEND_PATHS: list[
    tuple[str, Callable[[MixpanelAPIClient], object], str | None]
] = [
    (
        "query_request",
        lambda c: c._request("GET", c._build_url("query", "/segmentation")),
        "query",
    ),
    ("app_request", lambda c: c.app_request("GET", "/projects/12345/items"), None),
    (
        "export_events",
        lambda c: list(c.export_events("2024-01-01", "2024-01-01")),
        None,
    ),
    ("export_profiles", lambda c: list(c.export_profiles()), "query"),
    ("profiles_first_page", lambda c: c.export_profiles_page(page=0), "query"),
    (
        "profiles_later_page",
        lambda c: c.export_profiles_page(page=1, session_id="abc"),
        None,
    ),
    ("get_short_link", lambda c: c._get_short_link("https://mixpanel.com/s/abc"), None),
    ("paginate_all", lambda c: list(paginate_all(c, "/projects/12345/items")), None),
    ("register_lookup_table", lambda c: c.register_lookup_table({"name": "t"}), None),
    (
        "mark_lookup_table_ready",
        lambda c: c.mark_lookup_table_ready({"ready": "1"}),
        None,
    ),
    ("download_lookup_table", lambda c: c.download_lookup_table(1), None),
    (
        "insights_query",
        lambda c: c.insights_query({"bookmark": {}, "project_id": 12345}),
        "query",
    ),
    (
        "arb_funnels_query",
        lambda c: c.arb_funnels_query(
            {"bookmark": {}, "project_id": 12345, "query_type": "flows_sankey"}
        ),
        "query",
    ),
    ("activity_feed", lambda c: c.activity_feed(["user-1"]), "query"),
]


class TestEventHooks:
    """The pacer hooks run for every request the client sends."""

    @pytest.mark.parametrize(
        ("name", "run", "bucket"),
        _HOOKED_SEND_PATHS,
        ids=[name for name, _, _ in _HOOKED_SEND_PATHS],
    )
    def test_every_send_path_passes_through_the_hooks(
        self,
        test_credentials: Session,
        pacer_on: Path,
        monkeypatch: pytest.MonkeyPatch,
        name: str,
        run: Callable[[MixpanelAPIClient], object],
        bucket: str | None,
    ) -> None:
        """Each send path calls ``before_send`` and ``after_response`` once.

        The key that reaches ``before_send`` names the bucket the server
        counts the request against, or is None for a free request.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            monkeypatch: pytest monkeypatch fixture.
            name: Send path id.
            run: Callable that drives the send path.
            bucket: Expected ledger bucket, or None for a free request.
        """
        del pacer_on
        seen_keys: list[LedgerKey | None] = []
        seen_statuses: list[int] = []
        real_before = Pacer.before_send
        real_after = Pacer.after_response

        def spy_before(
            self: Pacer, request: httpx.Request, key: LedgerKey | None
        ) -> float:
            """Record the key, then pace as usual.

            Args:
                self: The pacer.
                request: The request.
                key: The ledger key.

            Returns:
                The seconds the real pacer slept.
            """
            seen_keys.append(key)
            return real_before(self, request, key)

        def spy_after(self: Pacer, response: httpx.Response) -> None:
            """Record the status, then observe as usual.

            Args:
                self: The pacer.
                response: The response.
            """
            seen_statuses.append(response.status_code)
            real_after(self, response)

        monkeypatch.setattr(Pacer, "before_send", spy_before)
        monkeypatch.setattr(Pacer, "after_response", spy_after)
        with _client(test_credentials, _universal_handler) as client:
            client.set_workspace_id(99)
            run(client)

        assert len(seen_keys) == 1, name
        assert seen_statuses == [200], name
        key = seen_keys[0]
        assert (key.bucket if key is not None else None) == bucket, name

    def test_counted_request_is_recorded_in_the_ledger(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """A Query API request is recorded in the ledger on disk.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        with _client(test_credentials, _ok_json({"ok": True})) as client:
            client._request("GET", client._build_url("query", "/segmentation"))
            pacer = client._pacer
            assert pacer is not None
            snap = pacer.snapshot(_QUERY_KEY)
        assert snap.used == 1
        assert (pacer_on / "pacer" / "mixpanel.com" / "12345-query.json").is_file()

    def test_free_requests_write_no_ledger(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """App API requests and later engage pages create no ledger file.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        with _client(test_credentials, _universal_handler) as client:
            client.app_request("GET", "/projects/12345/items")
            client.export_profiles_page(page=1, session_id="abc")
        assert not (pacer_on / "pacer").exists()

    def test_with_project_client_is_paced_on_its_own_ledger(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """A client from ``with_project`` has the hooks, keyed on its project.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        with _client(test_credentials, _ok_json({"ok": True})) as client:
            other = client.with_project("777")
            with other:
                other._request("GET", other._build_url("query", "/segmentation"))
        assert (pacer_on / "pacer" / "mixpanel.com" / "777-query.json").is_file()
        assert not (pacer_on / "pacer" / "mixpanel.com" / "12345-query.json").exists()


class TestPacerOff:
    """With ``MP_PACER=off`` the client behaves exactly as before."""

    def test_off_creates_no_ledger_and_marks_nothing(
        self,
        test_credentials: Session,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        recorded_sleeps: list[float],
    ) -> None:
        """No ledger directory, no request marker, and no sleep.

        Args:
            test_credentials: Session fixture.
            tmp_path: Temporary directory for this test.
            monkeypatch: pytest monkeypatch fixture.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        monkeypatch.setenv("MP_STORAGE_DIR", str(tmp_path / "storage"))
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the request and answer 200.

            Args:
                request: The incoming request.

            Returns:
                A 200 response.
            """
            seen.append(request)
            return httpx.Response(200, json={"ok": True})

        with _client(test_credentials, handler) as client:
            result = client._request("GET", client._build_url("query", "/segmentation"))
            list(client.export_events("2024-01-01", "2024-01-01"))
            assert client._pacer is not None
            assert client._pacer.settings.enabled is False

        assert result == {"ok": True}
        assert not (tmp_path / "storage").exists()
        assert all("mp_pacer" not in request.extensions for request in seen)
        assert recorded_sleeps == []

    def test_off_keeps_the_old_retry_wait(
        self, test_credentials: Session, recorded_sleeps: list[float]
    ) -> None:
        """A 429 with window-trip headers still waits the old ``Retry-After``.

        With the pacer off the response is never marked, so the loop keeps
        its own wait.

        Args:
            test_credentials: Session fixture.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Return one window-trip 429, then 200.

            Args:
                request: The incoming request.

            Returns:
                The response.
            """
            del request
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(
                    429,
                    headers={
                        "RateLimit-Policy": _POLICY_Q2,
                        "RateLimit": _WINDOW_TRIP,
                        "Retry-After": "7",
                    },
                )
            return httpx.Response(200, json={"ok": True})

        with _client(test_credentials, handler) as client:
            client._request("GET", client._build_url("query", "/segmentation"))
        assert recorded_sleeps == [7.0]


class TestPacerRaises:
    """A budget error from the request hook is final and sends nothing."""

    def test_rate_limit_error_is_not_retried_and_sends_nothing(
        self,
        test_credentials: Session,
        pacer_on: Path,
        monkeypatch: pytest.MonkeyPatch,
        recorded_sleeps: list[float],
    ) -> None:
        """With a configured limit reached, the next query raises at once.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            monkeypatch: pytest monkeypatch fixture.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        del pacer_on
        monkeypatch.setenv("MP_PACER_QUERY_LIMIT", "1")
        monkeypatch.setenv("MP_PACER_MAX_WAIT", "0")
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Count the request and answer 200.

            Args:
                request: The incoming request.

            Returns:
                A 200 response.
            """
            del request
            nonlocal calls
            calls += 1
            return httpx.Response(200, json={"ok": True})

        with _client(test_credentials, handler) as client:
            url = client._build_url("query", "/segmentation")
            client._request("GET", url)
            assert calls == 1
            with pytest.raises(RateLimitError) as info:
                client._request("GET", url)

        assert calls == 1
        assert recorded_sleeps == []
        assert info.value.details["sent"] is False
        assert info.value.details["limit"] == 1
        assert info.value.details["limit_source"] == "configured"
        assert info.value.retry_after is not None and info.value.retry_after > 0

    def test_two_clients_share_one_ledger(
        self,
        test_credentials: Session,
        pacer_on: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Requests from one client use up the budget another client sees.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            monkeypatch: pytest monkeypatch fixture.
        """
        del pacer_on
        monkeypatch.setenv("MP_PACER_QUERY_LIMIT", "2")
        monkeypatch.setenv("MP_PACER_MAX_WAIT", "0")
        with (
            _client(test_credentials, _ok_json({"ok": True})) as first,
            _client(test_credentials, _ok_json({"ok": True})) as second,
        ):
            url = first._build_url("query", "/segmentation")
            first._request("GET", url)
            second._request("GET", url)
            with pytest.raises(RateLimitError):
                first._request("GET", url)
            with pytest.raises(RateLimitError):
                second._request("GET", url)


def _window_trip_then_ok() -> tuple[
    Callable[[httpx.Request], httpx.Response], list[int]
]:
    """Build a handler that trips the window once, then answers 200.

    Returns:
        The handler and a one-item list holding the number of requests.
    """
    calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        """Return a real-shaped window-trip 429 first, then 200.

        Args:
            request: The incoming request.

        Returns:
            The response.
        """
        del request
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(
                429,
                headers={
                    "RateLimit-Policy": _POLICY_Q2,
                    "RateLimit": _WINDOW_TRIP,
                    "Retry-After": "3600",
                },
                json={"error": "rate limited"},
            )
        return httpx.Response(200, json={"ok": True})

    return handler, calls


class TestLearnedLimit:
    """A 429 teaches the limit; the retry then waits exactly or raises."""

    def test_retry_waits_exactly_for_the_learned_slot(
        self,
        test_credentials: Session,
        pacer_on: Path,
        recorded_sleeps: list[float],
    ) -> None:
        """The retry loop does not sleep; the pacer sleeps the exact hint.

        The server says the quota is 2 per hour and the ledger holds no
        request, so the trip is unexplained and the next slot is
        ``window / limit`` = 1800 s away.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        del pacer_on
        fake = _FakeTime()
        handler, calls = _window_trip_then_ok()
        with _client(test_credentials, handler) as client:
            pacer = _install_pacer(client, fake, PacerSettings(max_wait_s=math.inf))
            result = client._request("GET", client._build_url("query", "/segmentation"))
            snap = pacer.snapshot(_QUERY_KEY)

        assert result == {"ok": True}
        assert calls[0] == 2
        assert recorded_sleeps == [0.0]  # the retry loop's own wait
        assert fake.sleeps == [1800.0]  # the pacer's exact wait
        assert snap.limit == 2
        assert snap.limit_source == "server"
        assert snap.used == 1

    def test_retry_raises_when_the_learned_slot_is_too_far(
        self,
        test_credentials: Session,
        pacer_on: Path,
        recorded_sleeps: list[float],
    ) -> None:
        """With the default 30 s ceiling the retry raises and sends nothing.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        del pacer_on
        fake = _FakeTime()
        handler, calls = _window_trip_then_ok()
        with _client(test_credentials, handler) as client:
            _install_pacer(client, fake, PacerSettings())
            with pytest.raises(RateLimitError) as info:
                client._request("GET", client._build_url("query", "/segmentation"))

        assert calls[0] == 1
        assert recorded_sleeps == [0.0]
        assert fake.sleeps == []
        assert info.value.retry_after == 1800
        assert info.value.details["sent"] is False
        assert info.value.details["limit_source"] == "server"
        assert info.value.details["reason"] == "server"

    def test_export_is_not_paced(
        self,
        test_credentials: Session,
        pacer_on: Path,
        recorded_sleeps: list[float],
    ) -> None:
        """An export 429 takes today's retry wait; the pacer never touches export.

        The pacer covers the Query API only. Export keeps its own retry loop:
        ``Retry-After: 120`` is capped at the 60 s backoff ceiling.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        fake = _FakeTime()
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Return an export window-trip 429 first, then one event.

            Args:
                request: The incoming request.

            Returns:
                The response.
            """
            del request
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(
                    429, headers={"RateLimit": _WINDOW_TRIP, "Retry-After": "120"}
                )
            return httpx.Response(200, content=b'{"event": "A", "properties": {}}\n')

        with _client(test_credentials, handler) as client:
            _install_pacer(client, fake, PacerSettings(max_wait_s=math.inf))
            events = list(client.export_events("2024-01-01", "2024-01-01"))

        assert events == [{"event": "A", "properties": {}}]
        assert calls == 2
        assert recorded_sleeps == [60.0]  # today's capped Retry-After wait
        assert fake.sleeps == []
        assert not (pacer_on / "pacer").exists()


class TestHookEdges:
    """Edge cases of the hook wiring."""

    def test_pacer_survives_close_and_reopen(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """A client rebuilt after ``close`` keeps its pacer.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        del pacer_on
        client = _client(test_credentials, _ok_json({"ok": True}))
        client._ensure_client()
        pacer = client._pacer
        client.close()
        client._ensure_client()
        assert client._pacer is pacer
        client.close()

    def test_streamed_body_is_paced_without_reading_it(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """A request body that is not read yet does not break the hook.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        del pacer_on
        with _client(test_credentials, _ok_json({"ok": True})) as client:
            url = client._build_url("query", "/segmentation") + "?project_id=12345"
            request = httpx.Request("POST", url, content=iter([b"session_id=abc"]))
            client._pacer_before(request)
            assert request.extensions["mp_pacer"][0] == _QUERY_KEY

    def test_hooks_do_nothing_before_the_pacer_exists(
        self, test_credentials: Session
    ) -> None:
        """The hooks are no-ops on a client whose HTTP client is not built.

        Args:
            test_credentials: Session fixture.
        """
        client = MixpanelAPIClient(session=test_credentials)
        request = httpx.Request(
            "GET", "https://mixpanel.com/api/query/segmentation?project_id=12345"
        )
        client._pacer_before(request)
        client._pacer_after(httpx.Response(429, request=request))
        assert "mp_pacer" not in request.extensions
        assert client._pacer is None

    def test_request_hook_skips_a_client_with_no_session(
        self,
        test_credentials: Session,
        pacer_on: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With no session the request hook sends the request unpaced.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            monkeypatch: pytest monkeypatch fixture.
        """
        with _client(test_credentials, _ok_json({"ok": True})) as client:
            monkeypatch.setattr(client, "_session", None)
            request = httpx.Request(
                "GET", "https://mixpanel.com/api/query/segmentation?project_id=12345"
            )
            client._pacer_before(request)
        assert "mp_pacer" not in request.extensions
        assert not (pacer_on / "pacer").exists()


class TestClassificationFailsOpen:
    """A failure while classifying a request never blocks the request."""

    @pytest.mark.parametrize(
        ("target", "error"),
        [
            ("classify", ValueError("classify failed")),
            ("classify", RecursionError("deeply nested body")),
            ("classify", httpx.InvalidURL("bad base URL")),
            ("_api_family_for", ValueError("unexpected URL")),
            ("_endpoints_for", KeyError("region")),
        ],
        ids=[
            "classify-value-error",
            "classify-recursion",
            "classify-invalid-url",
            "family",
            "endpoints",
        ],
    )
    def test_request_is_sent_unpaced(
        self,
        test_credentials: Session,
        pacer_on: Path,
        monkeypatch: pytest.MonkeyPatch,
        target: str,
        error: BaseException,
    ) -> None:
        """The request goes out unpaced, and no exception escapes.

        The request carries a counted Query API URL, so without the failure
        it would be paced.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            monkeypatch: pytest monkeypatch fixture.
            target: The api_client function that raises.
            error: The exception it raises.
        """

        def boom(*args: object, **kwargs: object) -> None:
            """Raise the configured error.

            Args:
                *args: Ignored.
                **kwargs: Ignored.

            Raises:
                BaseException: Always, the parametrized error.
            """
            del args, kwargs
            raise error

        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the request and answer 200.

            Args:
                request: The incoming request.

            Returns:
                A 200 response.
            """
            calls.append(request)
            return httpx.Response(200, json={"ok": True})

        with _client(test_credentials, handler) as client:
            url = client._build_url("query", "/segmentation") + "?project_id=12345"
            monkeypatch.setattr(
                "mixpanel_headless._internal.api_client." + target, boom
            )
            # Send through the raw client: only the request hook runs the
            # patched function, so the test isolates the hook.
            result = client._ensure_client().get(url).json()

        assert result == {"ok": True}
        assert len(calls) == 1
        assert "mp_pacer" not in calls[0].extensions
        assert not (pacer_on / "pacer").exists()

    def test_classification_failure_warns_once_per_process(
        self,
        test_credentials: Session,
        pacer_on: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Two failing requests log the fixed internal-error WARNING exactly once.

        Pacing that stops silently must be visible, but only once per
        process; each failure still logs at DEBUG with the traceback.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            monkeypatch: pytest monkeypatch fixture.
            caplog: pytest log capture fixture.
        """
        del pacer_on

        def boom(*args: object, **kwargs: object) -> None:
            """Fail classification.

            Args:
                *args: Ignored.
                **kwargs: Ignored.

            Raises:
                ValueError: Always.
            """
            del args, kwargs
            raise ValueError("classify failed")

        pacer_module._reset_warn_once()
        caplog.set_level(logging.DEBUG)
        with _client(test_credentials, _ok_json({"ok": True})) as client:
            url = client._build_url("query", "/segmentation") + "?project_id=12345"
            monkeypatch.setattr("mixpanel_headless._internal.api_client.classify", boom)
            for _ in range(2):
                assert client._ensure_client().get(url).json() == {"ok": True}

        warnings = [
            r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
        ]
        assert warnings == [pacer_module._INTERNAL_WARNING]
        debug_with_trace = [
            r
            for r in caplog.records
            if r.levelno == logging.DEBUG and r.exc_info is not None
        ]
        assert len(debug_with_trace) >= 2


def _seed_ledger(
    storage: Path,
    key: LedgerKey,
    *,
    limit: int,
    limit_source: str,
    learned_at: float,
    sent: list[float],
    blocked_until: float = 0.0,
) -> None:
    """Write a ledger file directly, as another process would leave it.

    Args:
        storage: The storage root (``MP_STORAGE_DIR``).
        key: The ledger key.
        limit: The stored limit.
        limit_source: ``default``, ``configured``, or ``server``.
        learned_at: When a server limit was learned (epoch seconds).
        sent: Reservation times.
        blocked_until: The stored floor on the next slot.
    """
    path = storage / "pacer" / key.host / f"{key.project_id}-{key.bucket}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "v": 1,
                "limit": limit,
                "limit_source": limit_source,
                "learned_at": learned_at,
                "blocked_until": blocked_until,
                "sent": sent,
            }
        ),
        encoding="utf-8",
    )


_REFUSED_PATHS: list[tuple[str, Callable[[MixpanelAPIClient], object], LedgerKey]] = [
    (
        "query_request",
        lambda c: c._request("GET", c._build_url("query", "/segmentation")),
        _QUERY_KEY,
    ),
    ("export_profiles", lambda c: list(c.export_profiles()), _QUERY_KEY),
    ("profiles_first_page", lambda c: c.export_profiles_page(page=0), _QUERY_KEY),
]


class TestRefusalOnEveryCountedPath:
    """A budget refusal is final on every counted send path."""

    @pytest.mark.parametrize(
        ("name", "run", "key"),
        _REFUSED_PATHS,
        ids=[name for name, _, _ in _REFUSED_PATHS],
    )
    def test_refusal_is_not_retried_and_sends_nothing(
        self,
        test_credentials: Session,
        pacer_on: Path,
        monkeypatch: pytest.MonkeyPatch,
        recorded_sleeps: list[float],
        name: str,
        run: Callable[[MixpanelAPIClient], object],
        key: LedgerKey,
    ) -> None:
        """The first request uses the last slot; the second raises unsent.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            monkeypatch: pytest monkeypatch fixture.
            recorded_sleeps: Recorded ``time.sleep`` durations.
            name: Send path id.
            run: Callable that drives the send path.
            key: The ledger the path counts against.
        """
        monkeypatch.setenv("MP_PACER_MAX_WAIT", "0")
        _seed_ledger(
            pacer_on,
            key,
            limit=1,
            limit_source="server",
            learned_at=time.time(),
            sent=[],
        )
        calls: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the request and answer like the real API.

            Args:
                request: The incoming request.

            Returns:
                The response.
            """
            calls.append(request)
            return _universal_handler(request)

        with _client(test_credentials, handler) as client:
            run(client)
            with pytest.raises(RateLimitError) as info:
                run(client)

        assert len(calls) == 1, name
        assert recorded_sleeps == [], name
        assert info.value.details["sent"] is False, name
        assert info.value.details["bucket"] == key.bucket, name


class TestServerSignals:
    """End-to-end responses to what the server reports."""

    def test_concurrency_429_keeps_the_short_wait(
        self,
        test_credentials: Session,
        pacer_on: Path,
        recorded_sleeps: list[float],
    ) -> None:
        """A concurrency trip waits ``Retry-After`` in the loop, not in the pacer.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        del pacer_on
        fake = _FakeTime()
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a real concurrency 429 first, then 200.

            Args:
                request: The incoming request.

            Returns:
                The response.
            """
            del request
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(
                    429,
                    headers={
                        "RateLimit-Policy": (
                            '"project";q=60;w=3600, '
                            '"project-concurrency";q=5;qu="concurrent-requests"'
                        ),
                        "RateLimit": '"project";r=12, "project-concurrency";r=0;t=10',
                        "Retry-After": "10",
                    },
                )
            return httpx.Response(200, json={"ok": True})

        with _client(test_credentials, handler) as client:
            pacer = _install_pacer(client, fake, PacerSettings())
            result = client._request("GET", client._build_url("query", "/segmentation"))
            snap = pacer.snapshot(_QUERY_KEY)

        assert result == {"ok": True}
        assert recorded_sleeps == [10.0]
        assert fake.sleeps == []
        assert snap.used == 1
        assert snap.blocked_until == 0

    @pytest.mark.parametrize("status", [401, 402])
    def test_401_and_402_keep_their_errors_and_refund(
        self,
        test_credentials: Session,
        pacer_on: Path,
        monkeypatch: pytest.MonkeyPatch,
        status: int,
    ) -> None:
        """The error type matches the pacer-off type, and nothing is counted.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            monkeypatch: pytest monkeypatch fixture.
            status: The rejected status.
        """
        del pacer_on
        handler = _status_handler(status)

        def send_once() -> tuple[type[BaseException], int]:
            """Send one query and report its error type and the ledger count.

            Returns:
                The exception type and the query ledger's used count.
            """
            with _client(test_credentials, handler) as client:
                with pytest.raises(MixpanelHeadlessError) as info:
                    client._request("GET", client._build_url("query", "/segmentation"))
                assert client._pacer is not None
                used = client._pacer.snapshot(_QUERY_KEY).used
            return type(info.value), used

        monkeypatch.setenv("MP_PACER", "off")
        off_type, _ = send_once()
        monkeypatch.setenv("MP_PACER", "on")
        on_type, used = send_once()

        assert on_type is off_type
        assert used == 0

    def test_config_file_project_limit_applies(
        self,
        test_credentials: Session,
        pacer_on: Path,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A per-project limit in the config file blocks from the first request.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            tmp_path: Temporary directory (holds the config file).
            monkeypatch: pytest monkeypatch fixture.
        """
        del pacer_on
        monkeypatch.setenv("MP_PACER_MAX_WAIT", "0")
        (tmp_path / "config.toml").write_text(
            '[settings.pacer_query_limits]\n"12345" = 1\n', encoding="utf-8"
        )
        # The library reads the config file only with owner-only permissions.
        (tmp_path / "config.toml").chmod(0o600)
        with _client(test_credentials, _ok_json({"ok": True})) as client:
            url = client._build_url("query", "/segmentation")
            client._request("GET", url)
            with pytest.raises(RateLimitError) as info:
                client._request("GET", url)
        assert info.value.details["limit_source"] == "configured"
        assert info.value.details["limit"] == 1

    def test_accepted_probe_keeps_the_default_limit(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """A full default ledger still sends; a 200 keeps the default limit.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        del pacer_on
        fake = _FakeTime()
        with _client(test_credentials, _ok_json({"ok": True})) as client:
            pacer = _install_pacer(client, fake, PacerSettings())
            for _ in range(60):
                pacer.reserve(_QUERY_KEY)
            url = client._build_url("query", "/segmentation")
            client._request("GET", url)
            client._request("GET", url)
            snap = pacer.snapshot(_QUERY_KEY)
        assert fake.sleeps == []
        assert snap.limit_source == "default"
        assert snap.used == 62

    def test_foreign_traffic_waits_the_hint_with_no_ceiling(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """An unexplained window trip at q=60 waits exactly 60 s, once.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        del pacer_on
        fake = _FakeTime()
        handler, calls = _foreign_trip_then_ok()
        with _client(test_credentials, handler) as client:
            _install_pacer(client, fake, PacerSettings(max_wait_s=math.inf))
            url = client._build_url("query", "/segmentation")
            assert client._request("GET", url) == {"ok": True}
            assert client._request("GET", url) == {"ok": True}
        assert calls[0] == 3
        assert fake.sleeps == [60.0]

    def test_foreign_traffic_raises_with_the_default_ceiling(
        self,
        test_credentials: Session,
        pacer_on: Path,
        recorded_sleeps: list[float],
    ) -> None:
        """With the 30 s ceiling the retry raises at once, blaming the server.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        del pacer_on
        fake = _FakeTime()
        handler, calls = _foreign_trip_then_ok()
        with _client(test_credentials, handler) as client:
            _install_pacer(client, fake, PacerSettings())
            with pytest.raises(RateLimitError) as info:
                client._request("GET", client._build_url("query", "/segmentation"))
        assert calls[0] == 1
        assert recorded_sleeps == [0.0]
        assert info.value.details["reason"] == "server"
        assert info.value.retry_after == 60

    def test_429_body_timeout_is_an_http_error(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """A 429 whose body read times out raises ``HTTP_ERROR``.

        It never escapes as ``RuntimeError`` (``httpx.StreamConsumed``).

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        del pacer_on

        def handler(request: httpx.Request) -> httpx.Response:
            """Return a 429 whose body stream times out.

            Args:
                request: The incoming request.

            Returns:
                The response.
            """
            del request
            return httpx.Response(429, stream=_TimeoutStream())

        with (
            _client(test_credentials, handler) as client,
            pytest.raises(MixpanelHeadlessError) as info,
        ):
            client._request("GET", client._build_url("query", "/segmentation"))
        assert info.value.code == "HTTP_ERROR"

    def test_unknown_429_keeps_the_old_wait(
        self,
        test_credentials: Session,
        pacer_on: Path,
        recorded_sleeps: list[float],
    ) -> None:
        """A header-less 429 with an unknown body waits ``Retry-After`` as before.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        del pacer_on
        fake = _FakeTime()
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Return an unexplained 429 first, then 200.

            Args:
                request: The incoming request.

            Returns:
                The response.
            """
            del request
            nonlocal calls
            calls += 1
            if calls == 1:
                return httpx.Response(
                    429, headers={"Retry-After": "5"}, text="slow down"
                )
            return httpx.Response(200, json={"ok": True})

        with _client(test_credentials, handler) as client:
            _install_pacer(client, fake, PacerSettings())
            result = client._request("GET", client._build_url("query", "/segmentation"))
        assert result == {"ok": True}
        assert recorded_sleeps == [5.0]
        assert fake.sleeps == []


class TestTransportErrors:
    """A request the server never saw gives its slot back."""

    @pytest.mark.parametrize("error", [httpx.ConnectError, httpx.ConnectTimeout])
    def test_connect_failure_refunds_a_query(
        self,
        test_credentials: Session,
        pacer_on: Path,
        error: type[httpx.TransportError],
    ) -> None:
        """A connect failure on a counted query leaves the ledger empty.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            error: The connect failure.
        """
        del pacer_on
        with _client(test_credentials, _raising_handler(error)) as client:
            with pytest.raises(MixpanelHeadlessError) as info:
                client._request("GET", client._build_url("query", "/segmentation"))
            assert client._pacer is not None
            snap = client._pacer.snapshot(_QUERY_KEY)
        assert info.value.code == "HTTP_ERROR"
        assert snap.used == 0

    def test_read_timeout_is_not_refunded(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """A read timeout keeps the slot: the server may have counted it.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        del pacer_on
        with _client(test_credentials, _raising_handler(httpx.ReadTimeout)) as client:
            with pytest.raises(MixpanelHeadlessError):
                client._request("GET", client._build_url("query", "/segmentation"))
            assert client._pacer is not None
            snap = client._pacer.snapshot(_QUERY_KEY)
        assert snap.used == 1


class TestRefundGuards:
    """The refund helper ignores errors it cannot act on."""

    def test_connect_error_with_no_request_is_ignored(
        self, test_credentials: Session, pacer_on: Path
    ) -> None:
        """A connect error that carries no request refunds nothing and never raises.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
        """
        with _client(test_credentials, _ok_json({"ok": True})) as client:
            client._refund_unsent(httpx.ConnectError("no request attached"))
        assert not (pacer_on / "pacer").exists()

    def test_client_with_no_pacer_is_ignored(self, test_credentials: Session) -> None:
        """Before the HTTP client exists there is nothing to refund.

        Args:
            test_credentials: Session fixture.
        """
        client = MixpanelAPIClient(session=test_credentials)
        request = httpx.Request("GET", "https://mixpanel.com/api/query/insights")
        client._refund_unsent(httpx.ConnectError("refused", request=request))
        assert client._pacer is None


class TestPacerConstructionFallback:
    """A failure while building the pacer turns pacing off, not the client."""

    def test_construction_failure_turns_pacing_off(
        self,
        test_credentials: Session,
        pacer_on: Path,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Requests still work, and one WARNING names the failure.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            monkeypatch: pytest monkeypatch fixture.
            caplog: pytest log capture fixture.
        """

        def broken(config_path: Path | None = None) -> PacerSettings:
            """Fail like an unexpected bug in settings resolution.

            Args:
                config_path: Ignored.

            Raises:
                RuntimeError: Always.
            """
            del config_path
            raise RuntimeError("boom")

        monkeypatch.setattr(api_client_module, "load_pacer_settings", broken)
        monkeypatch.setattr(api_client_module, "_pacer_fallback_warned", False)
        caplog.set_level(logging.WARNING, logger=api_client_module.__name__)
        for _ in range(2):
            with _client(test_credentials, _ok_json({"ok": True})) as client:
                url = client._build_url("query", "/segmentation")
                assert client._request("GET", url) == {"ok": True}
                assert client._pacer is not None
                assert client._pacer.settings.enabled is False

        messages = [r.getMessage() for r in caplog.records]
        warnings = [m for m in messages if "request pacing is off" in m]
        assert warnings == ["request pacing is off for this process: RuntimeError"]
        assert not (pacer_on / "pacer").exists()


class TestRetryLogMessage:
    """The retry WARNING says who owns the wait."""

    def test_window_trip_logs_retry_through_the_pacer(
        self,
        test_credentials: Session,
        pacer_on: Path,
        recorded_sleeps: list[float],
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """After a window trip the log names the pacer, not a 0.0 s wait.

        Args:
            test_credentials: Session fixture.
            pacer_on: Pacer storage root.
            recorded_sleeps: Recorded ``time.sleep`` durations.
            caplog: pytest log capture fixture.
        """
        del pacer_on, recorded_sleeps
        caplog.set_level(logging.WARNING, logger=api_client_module.__name__)
        handler, _ = _window_trip_then_ok()
        with _client(test_credentials, handler) as client:
            _install_pacer(client, _FakeTime(), PacerSettings(max_wait_s=math.inf))
            client._request("GET", client._build_url("query", "/segmentation"))
        messages = [r.getMessage() for r in caplog.records]
        assert any(
            m.startswith("Rate limited; retrying through the request pacer")
            for m in messages
        ), messages
        assert not any("retrying in 0.0" in m for m in messages), messages

    @pytest.mark.parametrize(
        ("run", "logger_name", "prefix"),
        [
            (
                _run_execute_with_retry,
                "mixpanel_headless._internal.api_client",
                "Rate limited; retrying through the request pacer",
            ),
            (
                _run_paginate_all,
                "mixpanel_headless._internal.pagination",
                "Rate limited during pagination; retrying through the request pacer",
            ),
        ],
        ids=["execute_with_retry", "paginate_all"],
    )
    def test_marker_selects_the_pacer_message(
        self,
        test_credentials: Session,
        recorded_sleeps: list[float],
        caplog: pytest.LogCaptureFixture,
        run: Callable[[MixpanelAPIClient], None],
        logger_name: str,
        prefix: str,
    ) -> None:
        """A window marker selects the pacer message; no marker keeps the old one.

        Args:
            test_credentials: Session fixture.
            recorded_sleeps: Recorded ``time.sleep`` durations.
            caplog: pytest log capture fixture.
            run: Callable that drives the send path.
            logger_name: The logger of the retry loop.
            prefix: The expected start of the pacer message.
        """
        del recorded_sleeps
        caplog.set_level(logging.WARNING, logger=logger_name)
        success = {
            "status": "ok",
            "results": [],
            "pagination": {"page_size": 100, "next_cursor": None},
        }
        with _client(
            test_credentials, _one_429_then(httpx.Response(200, json=success), "window")
        ) as client:
            run(client)
        with _client(
            test_credentials, _one_429_then(httpx.Response(200, json=success), None)
        ) as client:
            run(client)
        messages = [r.getMessage() for r in caplog.records if r.name == logger_name]
        assert len(messages) == 2, messages
        assert messages[0].startswith(prefix)
        assert f"retrying in {float(_RETRY_AFTER_S):.1f} seconds" in messages[1]


class _TimeoutStream(httpx.SyncByteStream):
    """A response body whose first read times out."""

    def __iter__(self) -> Iterator[bytes]:
        """Fail the body read.

        Raises:
            httpx.ReadTimeout: Always.
        """
        raise httpx.ReadTimeout("body read timed out")


def _status_handler(status: int) -> Callable[[httpx.Request], httpx.Response]:
    """Build a handler that always answers with one status.

    Args:
        status: The status code.

    Returns:
        A MockTransport handler.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the status with a small JSON error body.

        Args:
            request: The incoming request.

        Returns:
            The response.
        """
        del request
        return httpx.Response(status, json={"error": "rejected"})

    return handler


def _raising_handler(
    error: type[httpx.TransportError],
) -> Callable[[httpx.Request], httpx.Response]:
    """Build a handler that fails every request with a transport error.

    Args:
        error: The transport error class.

    Returns:
        A MockTransport handler.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Raise the transport error.

        Args:
            request: The incoming request.

        Raises:
            httpx.TransportError: Always, of the configured class.
        """
        raise error("transport failed", request=request)

    return handler


def _foreign_trip_then_ok() -> tuple[
    Callable[[httpx.Request], httpx.Response], list[int]
]:
    """Build a handler whose first answer is a window trip the ledger cannot explain.

    The headers report q=60 while the local ledger is empty, as when another
    machine used the project's quota.

    Returns:
        The handler and a one-item list holding the number of requests.
    """
    calls = [0]

    def handler(request: httpx.Request) -> httpx.Response:
        """Return the unexplained window trip first, then 200.

        Args:
            request: The incoming request.

        Returns:
            The response.
        """
        del request
        calls[0] += 1
        if calls[0] == 1:
            return httpx.Response(
                429,
                headers={
                    "RateLimit-Policy": (
                        '"project";q=60;w=3600, '
                        '"project-concurrency";q=5;qu="concurrent-requests"'
                    ),
                    "RateLimit": _WINDOW_TRIP,
                    "Retry-After": "3600",
                },
            )
        return httpx.Response(200, json={"ok": True})

    return handler, calls


class _CountingResolver:
    """A token resolver whose bearer changes on every call."""

    def __init__(self, fail_on_call: int | None = None) -> None:
        """Start the counter.

        Args:
            fail_on_call: The 1-based call that raises, or None to never raise.
        """
        self.calls = 0
        self._fail_on_call = fail_on_call

    def _next(self) -> str:
        """Return the next token, or raise on the configured call.

        Returns:
            ``tok-<n>`` for call ``n``.

        Raises:
            RuntimeError: On the configured failing call.
        """
        self.calls += 1
        if self.calls == self._fail_on_call:
            raise RuntimeError("token refresh failed")
        return f"tok-{self.calls}"

    def get_browser_token(self, name: str, region: str) -> str:
        """Return the next token for a browser account.

        Args:
            name: Account name (ignored).
            region: Account region (ignored).

        Returns:
            The next token.
        """
        del name, region
        return self._next()

    def get_static_token(self, account: object) -> str:
        """Return the next token for a static-token account.

        Args:
            account: The account (ignored).

        Returns:
            The next token.
        """
        del account
        return self._next()


class TestAuthRefreshAfterPacerSleep:
    """A request that waited in the pacer goes out with a fresh bearer."""

    @staticmethod
    def _oauth_client(
        resolver: _CountingResolver, seen: list[str | None]
    ) -> MixpanelAPIClient:
        """Build an OAuth-token client that records each Authorization header.

        Args:
            resolver: The token resolver.
            seen: Receives the Authorization header of each sent request.

        Returns:
            The client.
        """

        def handler(request: httpx.Request) -> httpx.Response:
            """Record the Authorization header and answer 200.

            Args:
                request: The incoming request.

            Returns:
                A 200 response.
            """
            seen.append(request.headers.get("Authorization"))
            return httpx.Response(200, json={"ok": True})

        session = make_session(project_id="12345", region="us", oauth_token="static")
        return MixpanelAPIClient(
            session=session,
            token_resolver=resolver,
            _transport=httpx.MockTransport(handler),
        )

    def test_header_is_refreshed_after_a_sleep(self, pacer_on: Path) -> None:
        """The second request waits a window, then sends a newly resolved token.

        Args:
            pacer_on: Pacer storage root.
        """
        del pacer_on
        resolver = _CountingResolver()
        seen: list[str | None] = []
        with self._oauth_client(resolver, seen) as client:
            fake = _FakeTime()
            _install_pacer(
                client, fake, PacerSettings(max_wait_s=math.inf, query_limit=1)
            )
            url = client._build_url("query", "/segmentation")
            client._request("GET", url)
            client._request("GET", url)
        assert fake.sleeps and fake.sleeps[0] > 0
        assert seen == ["Bearer tok-1", "Bearer tok-3"]
        assert resolver.calls == 3

    def test_no_sleep_costs_no_extra_resolve(self, pacer_on: Path) -> None:
        """A request that did not wait resolves its token exactly once.

        Args:
            pacer_on: Pacer storage root.
        """
        del pacer_on
        resolver = _CountingResolver()
        seen: list[str | None] = []
        with self._oauth_client(resolver, seen) as client:
            _install_pacer(client, _FakeTime(), PacerSettings())
            client._request("GET", client._build_url("query", "/segmentation"))
        assert seen == ["Bearer tok-1"]
        assert resolver.calls == 1

    def test_failed_refresh_raises_and_refunds(self, pacer_on: Path) -> None:
        """A refresh that fails after a wait raises its error and sends nothing.

        Without the pacer the same failure surfaces before any send, so the
        paced request behaves the same: the original error reaches the
        caller, the request is never sent, and its reservation is refunded.

        Args:
            pacer_on: Pacer storage root.
        """
        resolver = _CountingResolver(fail_on_call=3)
        seen: list[str | None] = []
        fake = _FakeTime()
        with self._oauth_client(resolver, seen) as client:
            _install_pacer(
                client, fake, PacerSettings(max_wait_s=math.inf, query_limit=1)
            )
            url = client._build_url("query", "/segmentation")
            client._request("GET", url)
            with pytest.raises(RuntimeError, match="token refresh failed"):
                client._request("GET", url)
        # The second request slept to its slot, then failed before the send.
        assert len(fake.sleeps) == 1
        second_slot = fake.now
        ledger = json.loads(
            (pacer_on / "pacer" / "mixpanel.com" / "12345-query.json").read_text()
        )
        assert seen == ["Bearer tok-1"]  # the second request never went out
        assert second_slot not in ledger["sent"]  # its reservation was refunded

    def test_session_swap_during_the_wait_keeps_the_original_header(
        self, pacer_on: Path
    ) -> None:
        """A session swapped during the wait does not re-sign the waiting request.

        Another thread can call ``use(account=...)`` while a request sleeps in
        the pacer. The request's URL still belongs to the old session, so it
        keeps the header it was built with, and no new token is resolved.

        Args:
            pacer_on: Pacer storage root.
        """
        del pacer_on
        resolver = _CountingResolver()
        seen: list[str | None] = []
        with self._oauth_client(resolver, seen) as client:
            other = make_session(project_id="999", region="us", oauth_token="other")

            class _SwappingTime(_FakeTime):
                """A fake clock whose sleep swaps the client's session."""

                def sleep(self, seconds: float) -> None:
                    """Swap the session, then advance the clock.

                    Args:
                        seconds: Seconds to sleep.
                    """
                    client._session = other
                    super().sleep(seconds)

            fake = _SwappingTime()
            _install_pacer(
                client, fake, PacerSettings(max_wait_s=math.inf, query_limit=1)
            )
            url = client._build_url("query", "/segmentation")
            client._request("GET", url)
            client._request("GET", url)
        assert fake.sleeps and fake.sleeps[0] > 0
        assert seen == ["Bearer tok-1", "Bearer tok-2"]
        assert resolver.calls == 2  # no refresh after the swap

    def test_retry_after_a_refresh_reuses_the_refreshed_header(
        self, pacer_on: Path, recorded_sleeps: list[float]
    ) -> None:
        """A retry of a refreshed request carries the new header, with no lookup.

        The retry loop rebuilds each attempt from headers captured before the
        wait. After a concurrency 429 the retry does not wait in the pacer,
        so without help it would resend the bearer that expired during the
        first wait.

        Args:
            pacer_on: Pacer storage root.
            recorded_sleeps: Recorded ``time.sleep`` durations.
        """
        del pacer_on
        resolver = _CountingResolver()
        seen: list[str | None] = []
        calls = 0

        def handler(request: httpx.Request) -> httpx.Response:
            """Answer 200, except a real concurrency 429 for the second request.

            Args:
                request: The incoming request.

            Returns:
                The response.
            """
            nonlocal calls
            calls += 1
            seen.append(request.headers.get("Authorization"))
            if calls == 2:
                return httpx.Response(
                    429,
                    headers={
                        "RateLimit-Policy": (
                            '"project";q=60;w=3600, '
                            '"project-concurrency";q=5;qu="concurrent-requests"'
                        ),
                        "RateLimit": '"project";r=12, "project-concurrency";r=0;t=10',
                        "Retry-After": "1",
                    },
                )
            return httpx.Response(200, json={"ok": True})

        session = make_session(project_id="12345", region="us", oauth_token="static")
        with MixpanelAPIClient(
            session=session,
            token_resolver=resolver,
            _transport=httpx.MockTransport(handler),
        ) as client:
            fake = _FakeTime()
            _install_pacer(
                client, fake, PacerSettings(max_wait_s=math.inf, query_limit=1)
            )
            url = client._build_url("query", "/segmentation")
            client._request("GET", url)
            assert client._request("GET", url) == {"ok": True}

        assert len(fake.sleeps) == 1  # only the second request waited
        assert recorded_sleeps == [1.0]  # the loop's concurrency wait
        assert seen == ["Bearer tok-1", "Bearer tok-3", "Bearer tok-3"]
        assert resolver.calls == 3  # tok-1, tok-2 (built), tok-3 (refresh)

    def test_request_without_authorization_is_untouched(self, pacer_on: Path) -> None:
        """A request with no Authorization header gets none after a sleep.

        Args:
            pacer_on: Pacer storage root.
        """
        del pacer_on
        resolver = _CountingResolver()
        seen: list[str | None] = []
        with self._oauth_client(resolver, seen) as client:
            fake = _FakeTime()
            pacer = _install_pacer(
                client, fake, PacerSettings(max_wait_s=math.inf, query_limit=1)
            )
            pacer.reserve(_QUERY_KEY)  # the next counted request must wait
            url = client._build_url("query", "/segmentation") + "?project_id=12345"
            client._ensure_client().get(url)
        assert fake.sleeps and fake.sleeps[0] > 0
        assert seen == [None]
        assert resolver.calls == 0
