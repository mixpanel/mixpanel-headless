"""In-memory capture model shared by the record plugin and emitter.

The plugin (``conformance/record/plugin.py``) fills these structures during
the test run; the emitter (``conformance/record/emit.py``) classifies them
into vectors and manifest exclusion counts at session finish. Keeping the
model in its own module avoids a plugin<->emit import cycle.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from conformance.record.registry import RegistryEntry
    from mixpanel_headless._internal.auth.session import Session


class RecordingAbortError(Exception):
    """Fatal record-run error — extraction must fail loudly (design D5).

    Raised for the D5.2 session-relative authorization mismatch, the D5.4
    redaction-denylist hit, emit-time schema self-validation failures, and
    duplicate final vector ids (design D3). Never caught and continued: a
    hit means either a recorder bug or credential leakage.
    """


@dataclass
class RecordedRequest:
    """Transport-level snapshot of one outgoing HTTP request (design D1.1).

    Attributes:
        method: HTTP method (``GET``/``POST``/...).
        scheme_host: ``scheme://host[:port]`` — present so region-table
            sabotage stays observable (design D9 S4).
        path: URL path component.
        params: Decoded query params as httpx renders them — all values
            strings; repeated keys become lists of strings (wire-seam §3).
        headers: Request headers with lowercase keys (design D5.3).
        content: Raw request body bytes (empty for body-less requests).
    """

    method: str
    scheme_host: str
    path: str
    params: dict[str, str | list[str]]
    headers: dict[str, str]
    content: bytes


@dataclass
class RecordedResponse:
    """Transport-level snapshot of one response or transport error.

    Exactly one of the body representations is populated: ``body_bytes``
    for in-memory bodies, ``stream_chunks`` for TEE-captured streaming
    bodies (design D1.1 — chunk boundaries verbatim), or neither for
    empty bodies / transport errors.

    Attributes:
        status: HTTP status code; None when the handler raised.
        headers: Response headers with lowercase keys; None when the
            handler raised.
        body_bytes: In-memory response body bytes.
        stream_chunks: TEE-captured chunks in consumption order.
        transport_error: Exception class name when the handler raised
            (design D1.1 ``transport_error`` representation).
    """

    status: int | None = None
    headers: dict[str, str] | None = None
    body_bytes: bytes | None = None
    stream_chunks: list[bytes] | None = None
    transport_error: str | None = None


@dataclass
class RecordedInteraction:
    """One request/response pair observed at the transport seam.

    Attributes:
        seq: Monotonically increasing per-test sequence number (design D1.1).
        request: The request snapshot.
        response: The response snapshot (filled after the handler returns).
        span_index: Index into the owning test's ``entry_calls`` for the
            wire entry-point call on-stack when this interaction fired, or
            None for the P7 raw-httpx pattern (design D1.3).
        is_async: True when captured via ``handle_async_request``.
    """

    seq: int
    request: RecordedRequest
    response: RecordedResponse
    span_index: int | None
    is_async: bool


@dataclass
class EntryCallCapture:
    """One outermost registry entry-point invocation (design D1.2).

    Attributes:
        index: Position within the owning test's ``entry_calls``.
        entry: The registry entry that was invoked.
        input_encoded: ``call.input`` encoded AT CALL TIME (before the
            library or test can mutate argument objects).
        session: The Session bound to the client that will make requests
            (design D5.1), or None when no client is derivable.
        workspace_session: The Workspace facade session when it differs
            from ``session`` (design D5.1 two-session pattern), else None.
        result_encoded: Encoded return value (``expect.result`` shape).
        returned: True once the call returned (distinguishes a legitimate
            encoded None result from "never completed").
        error: The exception instance the call raised, if any.
        iterator_items: Encoded items yielded so far, for iterator-returning
            calls (streams — design D2 "array of yielded items").
        iterator_finished: True when the returned iterator was consumed to
            exhaustion (partial consumption cannot be replayed).
        excluded_reason: Manifest category excluding this capture from
            emission (``test_local_clock`` / ``unserializable_input``), or
            None when emittable.
    """

    index: int
    entry: RegistryEntry
    input_encoded: dict[str, Any] | None
    session: Session | None
    workspace_session: Session | None
    result_encoded: Any = None
    returned: bool = False
    error: BaseException | None = None
    iterator_items: list[Any] | None = None
    iterator_finished: bool = False
    excluded_reason: str | None = None


@dataclass
class TestCapture:
    """Everything recorded for a single pytest nodeid (design D1.3 keying).

    Attributes:
        nodeid: The exact pytest nodeid (vector ``source_test``).
        suppressed_category: Exclusion category decided at setup time
            (``hypothesis``/``live``/``destructive``/``layer3_deferred``);
            when set, no recording happens for the test.
        entry_calls: Outermost entry-point invocations in call order.
        interactions: Transport interactions in firing order.
        cli_used: True when ``CliRunner.invoke`` ran inside the test
            (design D10 per-test CLI detection).
        outcome: Final pytest outcome (``passed``/``failed``/``skipped``).
    """

    nodeid: str
    suppressed_category: str | None = None
    entry_calls: list[EntryCallCapture] = field(default_factory=list)
    interactions: list[RecordedInteraction] = field(default_factory=list)
    cli_used: bool = False
    outcome: str = "passed"
