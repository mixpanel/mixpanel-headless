"""Replay transport for wire/parse vectors (design D7 ``VectorTransport``).

Serves each recorded interaction's response (or raises its recorded
``transport_error``) while capturing every actual outgoing request for
diffing. Ordered interactions serve POSITIONALLY — interaction *i*'s
response answers request *i* regardless of whether the request matches, so
mismatches surface as diffs, never as serving failures. Interactions inside
an ``unordered_group`` serve BY KEY: the recorded member whose canonical
``(method, path, params)`` matches the incoming request, each consumable
once (design D2/D7 — positional serving would hand CDN file bodies to the
wrong URLs under async scheduling).
"""

from __future__ import annotations

import base64
import json
from collections.abc import AsyncIterator, Iterator, Mapping, Sequence
from typing import Any

import httpx

from conformance.record.capture import RecordedRequest, snapshot_request
from conformance.runner.canonical import canonicalize


class VectorReplayError(Exception):
    """Raised through the library when replay traffic exceeds the recording.

    Deliberately NOT an ``httpx.HTTPError``: library retry/error-mapping
    paths must not swallow it as ordinary transport weather. Whatever the
    library does with it, the vector fails afterwards on the extra-request
    check — this exception just stops runaway loops fast.
    """


class _ReplaySyncStream(httpx.SyncByteStream):
    """Sync response stream rebuilding recorded ``body_stream`` chunks.

    Chunk boundaries are served verbatim (design D2 — the gzip/JSONL
    chunk-reassembly contract depends on them).
    """

    def __init__(self, chunks: list[bytes]) -> None:
        """Store the decoded chunk list.

        Args:
            chunks: Body chunks in recorded order.
        """
        self._chunks = chunks

    def __iter__(self) -> Iterator[bytes]:
        """Yield each recorded chunk exactly once.

        Returns:
            Iterator over the recorded chunks.
        """
        return iter(self._chunks)


class _ReplayAsyncStream(httpx.AsyncByteStream):
    """Async mirror of :class:`_ReplaySyncStream`."""

    def __init__(self, chunks: list[bytes]) -> None:
        """Store the decoded chunk list.

        Args:
            chunks: Body chunks in recorded order.
        """
        self._chunks = chunks

    async def __aiter__(self) -> AsyncIterator[bytes]:
        """Yield each recorded chunk exactly once.

        Yields:
            The recorded chunks, in order.
        """
        for chunk in self._chunks:
            yield chunk


def request_key(method: str, path: str, params: Mapping[str, Any] | None) -> str:
    """Compute the canonical ``(method, path, params)`` key (design D2).

    The SAME key ``emit.interaction_sort_key`` uses at write time, so keyed
    serving inside unordered groups can never disagree with the committed
    corpus ordering.

    Args:
        method: HTTP method.
        path: Raw (percent-encoded) request path.
        params: Decoded query params, or None/empty for none.

    Returns:
        The canonical JSON of the triple (empty params normalize to None,
        matching the emit-side omission of empty ``params``).
    """
    return canonicalize([method, path, dict(params) if params else None])


def _recorded_key(interaction: Mapping[str, Any]) -> str:
    """Compute the serving key for one recorded interaction.

    Args:
        interaction: A vector ``expect.interactions[]`` entry.

    Returns:
        The canonical ``(method, path, params)`` key.
    """
    request = interaction.get("request")
    request_map: Mapping[str, Any] = request if isinstance(request, Mapping) else {}
    return request_key(
        str(request_map.get("method")),
        str(request_map.get("path")),
        request_map.get("params"),
    )


def decode_stream_chunks(body_stream: Sequence[Mapping[str, Any]]) -> list[bytes]:
    """Decode a recorded ``body_stream`` into raw chunk bytes.

    Args:
        body_stream: The vector's chunk list (``{"encoding", "data"}``).

    Returns:
        The chunks as bytes, boundaries preserved.

    Raises:
        VectorReplayError: On an unknown chunk encoding (malformed vector).
    """
    chunks: list[bytes] = []
    for chunk in body_stream:
        encoding = chunk.get("encoding")
        data = str(chunk.get("data", ""))
        if encoding == "utf8":
            chunks.append(data.encode("utf-8"))
        elif encoding == "base64":
            chunks.append(base64.b64decode(data))
        else:
            raise VectorReplayError(f"unknown body_stream encoding {encoding!r}")
    return chunks


def build_transport_error(response: Mapping[str, Any]) -> BaseException:
    """Build the exception a ``transport_error`` interaction re-raises.

    Args:
        response: The recorded ``{"transport_error": ..., "message"?: ...}``.

    Returns:
        An instance of the named ``httpx`` exception class, constructed
        with the recorded message (empty string when none was recorded).

    Raises:
        VectorReplayError: If the class name does not resolve to an
            ``httpx`` exception type (malformed vector).
    """
    name = str(response.get("transport_error"))
    cls = getattr(httpx, name, None)
    if not (isinstance(cls, type) and issubclass(cls, Exception)):
        raise VectorReplayError(f"unknown transport_error class {name!r}")
    return cls(str(response.get("message", "")))


def build_response(response: Mapping[str, Any]) -> httpx.Response:
    """Build the canned ``httpx.Response`` for one recorded interaction.

    Args:
        response: The recorded ``givenResponse`` object.

    Returns:
        A response carrying the recorded status/headers/body; stream-backed
        bodies preserve chunk boundaries via :class:`_ReplaySyncStream`.

    Raises:
        VectorReplayError: On malformed body encodings.
    """
    status = int(response.get("status", 0))
    headers = {
        str(key): str(value)
        for key, value in dict(response.get("headers") or {}).items()
    }
    if "body_stream" in response:
        chunks = decode_stream_chunks(response["body_stream"])
        return httpx.Response(status, headers=headers, stream=_ReplaySyncStream(chunks))
    content = b""
    if "body" in response:
        content = json.dumps(
            response["body"], separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    elif "body_text" in response:
        content = str(response["body_text"]).encode("utf-8")
    elif "body_base64" in response:
        content = base64.b64decode(str(response["body_base64"]))
    return httpx.Response(status, headers=headers, content=content)


class VectorTransport(httpx.BaseTransport, httpx.AsyncBaseTransport):
    """Serve recorded interactions to live library requests (design D7).

    One instance per vector, shared by every client the vector's replay
    constructs (setup + measured calls all diff against the same sequence).
    Each recorded interaction is consumable exactly once.

    Attributes:
        pairs: ``(recorded_index, actual_snapshot)`` in serve order — the
            diff input.
        extra_requests: Snapshots of requests that arrived after the
            recording was exhausted (any entry fails the vector).
    """

    def __init__(self, interactions: Sequence[Mapping[str, Any]]) -> None:
        """Bind the transport to a vector's recorded interactions.

        Args:
            interactions: The vector's ``expect.interactions[]`` in
                recorded order.
        """
        self._interactions = list(interactions)
        self._consumed = [False] * len(self._interactions)
        self.pairs: list[tuple[int, RecordedRequest]] = []
        self.extra_requests: list[RecordedRequest] = []

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        """Serve one sync request from the recording.

        Args:
            request: The live outgoing request.

        Returns:
            The recorded canned response.

        Raises:
            VectorReplayError: When the recording is exhausted.
            Exception: The recorded ``transport_error`` exception.
        """
        return self._serve(request)

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        """Serve one async request from the recording.

        Args:
            request: The live outgoing request.

        Returns:
            The recorded canned response (async-stream-backed when the
            recording carries ``body_stream``).

        Raises:
            VectorReplayError: When the recording is exhausted.
            Exception: The recorded ``transport_error`` exception.
        """
        response = self._serve(request, is_async=True)
        return response

    def _serve(
        self, request: httpx.Request, *, is_async: bool = False
    ) -> httpx.Response:
        """Select, consume, and serve the matching recorded interaction.

        Args:
            request: The live outgoing request.
            is_async: True when serving the async seam (stream bodies are
                rebuilt with the async stream class).

        Returns:
            The canned response.

        Raises:
            VectorReplayError: When the recording is exhausted.
            Exception: The recorded ``transport_error`` exception.
        """
        snapshot = snapshot_request(request)
        index = self._select_index(snapshot)
        if index is None:
            self.extra_requests.append(snapshot)
            raise VectorReplayError(
                "request beyond the recorded interaction sequence: "
                f"{snapshot.method} {snapshot.scheme_host}{snapshot.path}"
            )
        self._consumed[index] = True
        self.pairs.append((index, snapshot))
        recorded = self._interactions[index].get("response")
        response_map: Mapping[str, Any] = (
            recorded if isinstance(recorded, Mapping) else {}
        )
        if "transport_error" in response_map:
            raise build_transport_error(response_map)
        response = build_response(response_map)
        if is_async and "body_stream" in response_map:
            chunks = decode_stream_chunks(response_map["body_stream"])
            response = httpx.Response(
                response.status_code,
                headers=response.headers,
                stream=_ReplayAsyncStream(chunks),
            )
        return response

    def _select_index(self, snapshot: RecordedRequest) -> int | None:
        """Pick the recorded interaction that answers this request.

        Positional for ordered interactions; keyed by canonical
        ``(method, path, params)`` inside an unordered group, falling back
        to the group's first unconsumed member when no key matches (the
        pairing diff then fails with a precise mismatch instead of a vague
        serving error).

        Args:
            snapshot: The live request snapshot.

        Returns:
            The selected recorded index, or None when exhausted.
        """
        head: int | None = None
        for position, consumed in enumerate(self._consumed):
            if not consumed:
                head = position
                break
        if head is None:
            return None
        group = self._interactions[head].get("unordered_group")
        if not isinstance(group, int) or isinstance(group, bool):
            return head
        candidates = [
            position
            for position, interaction in enumerate(self._interactions)
            if not self._consumed[position]
            and interaction.get("unordered_group") == group
        ]
        actual_key = request_key(snapshot.method, snapshot.path, snapshot.params)
        for position in candidates:
            if _recorded_key(self._interactions[position]) == actual_key:
                return position
        return candidates[0]

    def unconsumed_indexes(self) -> list[int]:
        """Return recorded interaction positions never served.

        Returns:
            Indexes of unconsumed interactions (any entry fails the
            vector — missing traffic, design D2).
        """
        return [
            position for position, consumed in enumerate(self._consumed) if not consumed
        ]
