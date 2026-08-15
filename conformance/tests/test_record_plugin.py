"""Unit tests for the record plugin's transport wrapper (design D1, PR-2).

Covers the PR-2 mandated cases: a transport round-trip through a live
``RecordSession`` (entry-point wrap + transport hook + attribution), a
stream-backed response captured by the TEE without disturbing the consumer's
chunk boundaries (design D1.1), and the D1.4 virtual sleep advancing the
frozen monotonic clock.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from conformance.record.clock import RecordClock
from conformance.record.plugin import RecordOptions, RecordSession
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session


def _make_session() -> Session:
    """Build a small service-account session for wrapper tests.

    Returns:
        A ``Session`` bound to a fake service account on project 12345.
    """
    return Session(
        account=ServiceAccount(
            name="test_account",
            region="us",
            username="test_user",
            secret=SecretStr("test_secret"),
        ),
        project=Project(id="12345"),
    )


@pytest.fixture
def record_session(tmp_path: Path) -> Iterator[RecordSession]:
    """Provide an ACTIVATED record session, deactivated on teardown.

    Args:
        tmp_path: pytest-provided output directory for the session.

    Yields:
        The active :class:`RecordSession` (clock frozen, registry wrapped,
        transport hooked).
    """
    session = RecordSession(
        RecordOptions(
            out_dir=tmp_path / "vectors",
            extraction_date="2026-08-14",
            source_commit="0" * 40,
        )
    )
    session.activate()
    try:
        yield session
    finally:
        session.deactivate()


class _ChunkedStream(httpx.SyncByteStream):
    """Handler-side one-shot byte stream with explicit chunk boundaries."""

    def __init__(self, chunks: list[bytes]) -> None:
        """Store the chunk list to yield.

        Args:
            chunks: Body chunks in yield order.
        """
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        """Yield each configured chunk exactly once.

        Returns:
            Iterator over the configured chunks.
        """
        return iter(self._chunks)


def test_transport_round_trip_records_request_and_response(
    record_session: RecordSession,
) -> None:
    """A wrapped entry-point call records interaction + result (design D1.1/2).

    Drives ``api_client.list_annotations`` through a MockTransport and
    asserts the capture holds the attributed interaction (method, path,
    auth header, JSON body) and the encoded entry-call result.

    Raises:
        AssertionError: If any capture field is missing or wrong.
    """
    from mixpanel_headless._internal.api_client import MixpanelAPIClient

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve a fixed annotation list.

        Args:
            request: The incoming request.

        Returns:
            A 200 JSON response with one annotation.
        """
        del request
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "results": [
                    {
                        "id": 1,
                        "project_id": 12345,
                        "date": "2026-03-31",
                        "description": "hi",
                        "tags": [],
                    }
                ],
            },
        )

    record_session.begin_test("tests/unit/test_fake.py::test_round_trip", None)
    client = MixpanelAPIClient(
        session=_make_session(), _transport=httpx.MockTransport(handler)
    )
    result = client.list_annotations()
    record_session.finish_test("tests/unit/test_fake.py::test_round_trip")

    assert len(result) == 1
    capture = record_session.captures[-1]
    assert capture.nodeid == "tests/unit/test_fake.py::test_round_trip"
    calls = [
        c for c in capture.entry_calls if c.entry.api == "api_client.list_annotations"
    ]
    assert len(calls) == 1
    assert calls[0].returned
    assert len(capture.interactions) == 1
    interaction = capture.interactions[0]
    assert interaction.span_index == calls[0].index
    assert interaction.request.method == "GET"
    assert interaction.request.path.endswith("/annotations/")
    assert interaction.request.headers["authorization"].startswith("Basic ")
    assert interaction.response.status == 200
    assert interaction.response.body_bytes is not None
    assert b'"status"' in interaction.response.body_bytes


def test_stream_backed_response_teed_without_consuming(
    record_session: RecordSession,
) -> None:
    """The stream TEE records chunks as the consumer reads them (design D1.1).

    A raw ``httpx.Client`` streams a two-chunk body through MockTransport;
    the recorder must capture both chunk boundaries verbatim WITHOUT
    pre-reading (which would raise ``httpx.StreamConsumed`` for the test).

    Raises:
        AssertionError: If chunks are missing, merged, or reordered.
    """
    chunks = [b'{"a": 1}\n', b'{"b": 2}\n']

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve the chunked stream body.

        Args:
            request: The incoming request.

        Returns:
            A 200 response backed by :class:`_ChunkedStream`.
        """
        del request
        return httpx.Response(200, stream=_ChunkedStream(list(chunks)))

    record_session.begin_test("tests/unit/test_fake.py::test_stream", None)
    consumed: list[bytes] = []
    with (
        httpx.Client(transport=httpx.MockTransport(handler)) as client,
        client.stream("GET", "https://example.test/export") as response,
    ):
        for chunk in response.iter_raw():
            consumed.append(chunk)
    record_session.finish_test("tests/unit/test_fake.py::test_stream")

    assert consumed == chunks  # consumer saw the exact boundaries
    capture = record_session.captures[-1]
    assert len(capture.interactions) == 1
    recorded = capture.interactions[0].response
    assert recorded.stream_chunks == chunks
    assert recorded.body_bytes is None
    # Raw-httpx traffic has no entry point on-stack (P7 pattern, D1.3).
    assert capture.interactions[0].span_index is None


def test_virtual_sleep_advances_frozen_monotonic_clock() -> None:
    """``time.sleep`` under the record clock advances ``time.monotonic``.

    Design D1.4: a plain no-op sleep under a frozen monotonic clock would
    loop forever in wall-clock-deadline polls; the virtual sleep must tick
    the frozen clock by exactly the requested duration.

    Raises:
        AssertionError: If the monotonic clock does not advance by the
            slept amount.
    """
    import time

    clock = RecordClock()
    clock.start()
    try:
        before = time.monotonic()
        time.sleep(1.5)
        after = time.monotonic()
    finally:
        clock.stop()
    assert after - before == pytest.approx(1.5)


def test_virtual_sleep_rejects_negative_durations() -> None:
    """Negative sleep durations raise ``ValueError`` like real ``time.sleep``.

    Raises:
        AssertionError: If no ``ValueError`` is raised.
    """
    import time

    clock = RecordClock()
    clock.start()
    try:
        with pytest.raises(ValueError, match="non-negative"):
            time.sleep(-1)
    finally:
        clock.stop()


def test_deterministic_uuid_stream_resets_per_test() -> None:
    """``uuid.uuid4`` yields the counter stream, reset by ``reset_test_state``.

    Raises:
        AssertionError: If the stream deviates from the D1.4 template or
            fails to reset.
    """
    import uuid

    clock = RecordClock()
    clock.start()
    try:
        first = str(uuid.uuid4())
        second = str(uuid.uuid4())
        clock.reset_test_state()
        third = str(uuid.uuid4())
    finally:
        clock.stop()
    assert first == "00000000-0000-4000-8000-000000000000"
    assert second == "00000000-0000-4000-8000-000000000001"
    assert third == first


# ---------------------------------------------------------------------------
# Session extraction Mock-safety + D5.2 acceptance paths (PR-5 fixes)
# ---------------------------------------------------------------------------


def test_sessions_for_tolerates_mock_client() -> None:
    """A Workspace wrapping a Mock client yields no session, no raise.

    Builder-only tests construct real ``Workspace`` objects around
    ``unittest.mock`` clients; the extractor must degrade to
    ``(None, ...)`` instead of raising inside the wrapped call (PR-5
    regression: 632 facade-builder tests failed under record mode).

    Raises:
        AssertionError: If a mock leaks through as a session.
    """
    from unittest.mock import Mock

    from mixpanel_headless.workspace import Workspace

    workspace = object.__new__(Workspace)
    workspace._api_client = Mock()
    workspace._session = Mock()
    client_session, facade_session = RecordSession._sessions_for(workspace, {})
    assert client_session is None
    assert facade_session is None


def test_sessions_for_returns_real_facade_session() -> None:
    """A real facade session survives the type gate.

    Raises:
        AssertionError: If the real ``Session`` is dropped.
    """
    from unittest.mock import Mock

    from mixpanel_headless.workspace import Workspace

    session = _make_session()
    workspace = object.__new__(Workspace)
    workspace._api_client = Mock()
    workspace._session = session
    client_session, facade_session = RecordSession._sessions_for(workspace, {})
    assert client_session is None
    assert facade_session is session


def _probe_style_span(input_encoded: dict[str, object]) -> object:
    """Build a session-less entry-call capture (``probe_region`` shape).

    Args:
        input_encoded: The encoded ``call.input`` carrying the credential.

    Returns:
        An :class:`EntryCallCapture` with no bound session.
    """
    from conformance.record.capture import EntryCallCapture
    from conformance.record.registry import REGISTRY_BY_API

    return EntryCallCapture(
        index=0,
        entry=REGISTRY_BY_API["region_probe.probe_region"],
        input_encoded=input_encoded,
        session=None,
        workspace_session=None,
    )


def test_verify_authorization_accepts_input_carried_credential(
    tmp_path: Path,
) -> None:
    """D5.2 path 3: an auth value present in ``call.input`` is accepted.

    Args:
        tmp_path: Session output directory (unused beyond construction).

    Raises:
        AssertionError: If the input-carried credential aborts recording.
    """
    from conformance.record.capture import RecordedRequest

    record = RecordSession(
        RecordOptions(
            out_dir=tmp_path, extraction_date="2026-08-14", source_commit="0" * 40
        )
    )
    span = _probe_style_span({"headers": {"Authorization": "Basic dTpz"}})
    snapshot = RecordedRequest(
        method="GET",
        scheme_host="https://mixpanel.com",
        path="/api/app/me",
        params={},
        headers={"authorization": "Basic dTpz"},
        content=b"",
    )
    record._verify_authorization("tests/x.py::t", span, snapshot)  # type: ignore[arg-type]
    assert record.fatal_error is None


def test_verify_authorization_rejects_foreign_credential(tmp_path: Path) -> None:
    """D5.2: an auth value from NOWHERE (no session, not in input) aborts.

    Args:
        tmp_path: Session output directory (unused beyond construction).

    Raises:
        AssertionError: If the foreign credential is accepted.
    """
    import pytest as _pytest

    from conformance.record.capture import RecordedRequest, RecordingAbortError

    record = RecordSession(
        RecordOptions(
            out_dir=tmp_path, extraction_date="2026-08-14", source_commit="0" * 40
        )
    )
    span = _probe_style_span({"headers": {"Authorization": "Basic dTpz"}})
    snapshot = RecordedRequest(
        method="GET",
        scheme_host="https://mixpanel.com",
        path="/api/app/me",
        params={},
        headers={"authorization": "Basic c29tZW9uZTplbHNl"},
        content=b"",
    )
    with _pytest.raises(RecordingAbortError):
        record._verify_authorization("tests/x.py::t", span, snapshot)  # type: ignore[arg-type]
    assert record.fatal_error is not None


def test_verify_authorization_defers_resolver_backed_session(
    tmp_path: Path,
) -> None:
    """D5.2 path 2: resolver-backed sessions defer verification to emit.

    Args:
        tmp_path: Session output directory (unused beyond construction).

    Raises:
        AssertionError: If a resolver-backed bearer aborts recording.
    """
    from conformance.record.capture import EntryCallCapture, RecordedRequest
    from conformance.record.registry import REGISTRY_BY_API
    from mixpanel_headless._internal.auth.account import OAuthTokenAccount

    record = RecordSession(
        RecordOptions(
            out_dir=tmp_path, extraction_date="2026-08-14", source_commit="0" * 40
        )
    )
    session = Session(
        account=OAuthTokenAccount(name="ci", region="us", token_env="MP_OAUTH_TOKEN"),
        project=Project(id="12345"),
    )
    span = EntryCallCapture(
        index=0,
        entry=REGISTRY_BY_API["api_client.list_annotations"],
        input_encoded={},
        session=session,
        workspace_session=None,
    )
    snapshot = RecordedRequest(
        method="GET",
        scheme_host="https://mixpanel.com",
        path="/api/app/projects/12345/annotations/",
        params={},
        headers={"authorization": "Bearer resolved-tok"},
        content=b"",
    )
    record._verify_authorization("tests/x.py::t", span, snapshot)
    assert record.fatal_error is None


def test_reset_test_state_moves_clock_back_to_epoch() -> None:
    """Per-test reset returns the frozen clock to the epoch (design D1.4).

    Virtual-sleep ticks must not accumulate across tests: jittered backoff
    durations would otherwise leak a nondeterministic offset into every
    later ``datetime.now()``-derived payload (PR-5 double-run regression).

    Raises:
        AssertionError: If time survives the reset.
    """
    import datetime as _dt
    import time as _time

    clock = RecordClock()
    clock.start()
    try:
        epoch_now = _dt.datetime.now(_dt.timezone.utc)
        _time.sleep(123.456)
        assert _dt.datetime.now(_dt.timezone.utc) > epoch_now
        clock.reset_test_state()
        assert _dt.datetime.now(_dt.timezone.utc) == epoch_now
    finally:
        clock.stop()


def test_snapshot_request_records_percent_encoded_path() -> None:
    """The transport snapshot keeps the RAW (encoded) request path.

    ``httpx.URL.path`` percent-decodes, which would erase the library's
    URL-encoding contract (PR-5 audit finding F3: a port that fails to
    encode ``"My Event / Test"`` would replay identically).

    Raises:
        AssertionError: If the decoded path leaks into the snapshot.
    """
    from urllib.parse import quote

    from conformance.record.plugin import _snapshot_request

    encoded = quote("My Event / Test", safe="")
    request = httpx.Request(
        "POST",
        f"https://mixpanel.com/api/app/projects/12345/schemas/event/{encoded}",
        params={"q": "1"},
    )
    snapshot = _snapshot_request(request)
    assert snapshot.path == (
        "/api/app/projects/12345/schemas/event/My%20Event%20%2F%20Test"
    )
    assert snapshot.params == {"q": "1"}


def test_client_options_captured_only_when_non_default() -> None:
    """Non-default ``max_retries`` is captured; the default is omitted (F4).

    Raises:
        AssertionError: If defaults leak in or non-defaults are dropped.
    """
    import httpx as _httpx

    from mixpanel_headless._internal.api_client import MixpanelAPIClient

    transport = _httpx.MockTransport(lambda _request: _httpx.Response(200))
    session = _make_session()
    tuned = MixpanelAPIClient(session=session, max_retries=1, _transport=transport)
    default = MixpanelAPIClient(session=session, _transport=transport)
    assert RecordSession._client_options_for(tuned, {}) == {"max_retries": 1}
    assert RecordSession._client_options_for(default, {}) is None
    assert RecordSession._client_options_for(None, {"client": tuned}) == {
        "max_retries": 1
    }
