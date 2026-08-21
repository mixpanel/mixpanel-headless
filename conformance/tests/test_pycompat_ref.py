"""Unit tests for the D13 reference module and the D4.2 adapters (PR-3).

Covers the pythonCompat reference wrappers against the D13 case list (the
authored gate vectors will freeze exactly these outputs), the wire-stub
mirror client against a MockTransport (single call, sequence, streaming
chunk boundaries, transport-error surfacing), and the two adapter shims.
"""

from __future__ import annotations

from collections.abc import Iterator

import httpx
import pytest

from conformance.record.adapters import iter_jsonl_lines, selector_label_fn
from conformance.record.pycompat_ref import (
    WireStubClient,
    python_float_str,
    python_str,
    zfill,
)
from mixpanel_headless.types import UserAction


@pytest.mark.parametrize(
    ("value", "width", "expected"),
    [
        ("-1", 3, "-01"),
        ("5", 3, "005"),
        ("+7", 3, "+07"),
        ("", 2, "00"),
        ("12345", 3, "12345"),
        ("\U0001f40d", 3, "00\U0001f40d"),
    ],
)
def test_zfill_matches_python_semantics(value: str, width: int, expected: str) -> None:
    """``zfill`` reproduces the D13 edge set (sign-aware, non-BMP safe).

    Args:
        value: Input string.
        width: Target width.
        expected: CPython's ``str.zfill`` result.

    Raises:
        AssertionError: If the wrapper deviates from CPython.
    """
    assert zfill(value, width) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "True"),
        (None, "None"),
        ([1, "a"], "[1, 'a']"),
        ({"k": None}, "{'k': None}"),
    ],
)
def test_python_str_matches_python_semantics(value: object, expected: str) -> None:
    """``python_str`` reproduces Python ``str()`` rendering (R11.1).

    Args:
        value: Input value.
        expected: CPython's ``str()`` result.

    Raises:
        AssertionError: If the wrapper deviates from CPython.
    """
    assert python_str(value) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (18.0, "18.0"),
        (1.5, "1.5"),
        (1e16, "1e+16"),
        (1e-4, "0.0001"),
        (1e-5, "1e-05"),
        (-0.0, "-0.0"),
    ],
)
def test_python_float_str_matches_repr(value: float, expected: str) -> None:
    """``python_float_str`` reproduces the D13 float-rendering case list.

    Args:
        value: Input float.
        expected: CPython's ``repr(float)`` result.

    Raises:
        AssertionError: If the wrapper deviates from CPython.
    """
    assert python_float_str(value) == expected


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


def test_wirestub_single_request_parses_json_body() -> None:
    """The stub issues exactly the directed request and returns status+body.

    Raises:
        AssertionError: If the request or result deviates.
    """
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Record the request and serve a JSON pong.

        Args:
            request: The incoming request.

        Returns:
            A 200 JSON response.
        """
        seen.append(request)
        return httpx.Response(200, json={"ok": True})

    client = WireStubClient(transport=httpx.MockTransport(handler))
    try:
        result = client.request(
            "GET", "/ping", params={"q": "1"}, headers={"x-gate": "yes"}
        )
    finally:
        client.close()
    assert result == {"status": 200, "body": {"ok": True}}
    assert len(seen) == 1
    assert seen[0].url.path == "/ping"
    assert seen[0].url.params["q"] == "1"
    assert seen[0].headers["x-gate"] == "yes"


def test_wirestub_request_sequence_preserves_order() -> None:
    """``request_sequence`` issues calls in input order (multi-interaction).

    Raises:
        AssertionError: If order or results deviate.
    """
    paths: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve the request path back as text.

        Args:
            request: The incoming request.

        Returns:
            A 200 text response naming the path.
        """
        paths.append(request.url.path)
        return httpx.Response(
            200, text=request.url.path, headers={"content-type": "text/plain"}
        )

    client = WireStubClient(transport=httpx.MockTransport(handler))
    try:
        results = client.request_sequence(
            [
                {"method": "GET", "path": "/b"},
                {"method": "POST", "path": "/a", "json_body": {"n": 1}},
            ]
        )
    finally:
        client.close()
    assert paths == ["/b", "/a"]
    assert results == [
        {"status": 200, "body": "/b"},
        {"status": 200, "body": "/a"},
    ]


def test_wirestub_stream_chunks_preserves_boundaries() -> None:
    """``stream_chunks`` returns the transport's chunk boundaries verbatim.

    Raises:
        AssertionError: If chunks are merged, split, or reordered.
    """
    chunks = [b'{"a": 1}\n{"b"', b": 2}\n"]

    def handler(request: httpx.Request) -> httpx.Response:
        """Serve the chunked stream body.

        Args:
            request: The incoming request.

        Returns:
            A 200 response backed by the chunk stream.
        """
        del request
        return httpx.Response(200, stream=_ChunkedStream(list(chunks)))

    client = WireStubClient(transport=httpx.MockTransport(handler))
    try:
        received = client.stream_chunks("GET", "/export")
    finally:
        client.close()
    assert received == ['{"a": 1}\n{"b"', ": 2}\n"]


def test_wirestub_surfaces_transport_errors_unwrapped() -> None:
    """Transport failures propagate as-is (design D13 error-surfacing gate).

    Raises:
        AssertionError: If the error is swallowed or wrapped.
    """

    def handler(request: httpx.Request) -> httpx.Response:
        """Raise a connect error like a dead host.

        Args:
            request: The incoming request.

        Returns:
            Never returns.

        Raises:
            httpx.ConnectError: Always.
        """
        raise httpx.ConnectError("boom", request=request)

    client = WireStubClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(httpx.ConnectError):
            client.request("GET", "/down")
    finally:
        client.close()


def test_selector_label_adapter_flattens_factory_and_closure() -> None:
    """``selector_label_fn(attr, action)`` equals factory-then-closure.

    Args:
        None.

    Raises:
        AssertionError: If the adapter and the real factory disagree.
    """
    from mixpanel_headless import replay_labels

    action = UserAction(
        timestamp=1,
        action="click",
        target_node_id=5,
        target_desc='button "Submit"',
        url="https://app.test/page",
        metadata={"attributes": {"data-testid": "submit-button"}},
        description="Clicked button",
    )
    expected = replay_labels.selector_label_fn("data-testid")(action)
    assert selector_label_fn("data-testid", action) == expected


def test_iter_jsonl_lines_adapter_reassembles_split_lines() -> None:
    """The chunk adapter drives the real buffering logic (design D4.2 item 9).

    A line split across a chunk boundary must reassemble exactly once.

    Raises:
        AssertionError: If lines are split, duplicated, or dropped.
    """
    lines = iter_jsonl_lines([b'{"a": 1}\n{"b"', b": 2}\n"])
    assert lines == ['{"a": 1}', '{"b": 2}']
