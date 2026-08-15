"""Record-mode pytest plugin (design D1) — transport hook + entry-point wrap.

Load with ``-p conformance.record.plugin`` and activate with
``--mp-record-vectors=<dir>`` (or ``CONFORMANCE_RECORD_DIR``); OFF by default
so the normal suite is unaffected (design D1.3). Because the repo installs
only ``src/`` into the venv, record invocations must put the repo root on
``sys.path`` — use ``uv run python -m pytest`` (the ``just
conformance-record`` recipe does).

Responsibilities (design section in parentheses):

- Freeze clock/UUID and install the VIRTUAL sleep for the whole run (D1.4)
  via :class:`conformance.record.clock.RecordClock`.
- Wrap every registry entry point once per session; record
  ``(args, kwargs) -> return | raise`` for the OUTERMOST call only
  (re-entrancy guard, D1.2) and mark the entry/exit span so transport
  interactions attribute to the on-stack wire call (span stack, D1.2).
- Patch ``httpx.MockTransport.handle_request``/``handle_async_request`` at
  the class level to record every interaction; stream bodies are captured
  by a TEE, never a read-ahead (D1.1).
- Verify every observed ``authorization`` header against the bound
  session's credentials — a mismatch is an attribution bug or credential
  leakage and fails the run (D5.2 session-relative abort rule).
- Key captures by pytest nodeid; per-capture classification happens in
  ``conformance/record/emit.py`` at session finish (D1.3/D10).
"""

from __future__ import annotations

import base64
import contextlib
import functools
import inspect
import os
import threading
import unittest.mock as umock
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from conformance.record.capture import (
    EntryCallCapture,
    RecordedInteraction,
    RecordedRequest,
    RecordedResponse,
    RecordingAbortError,
    TestCapture,
)
from conformance.record.clock import RecordClock
from conformance.record.codecs import (
    UnencodableValueError,
    encode_expect_value,
    encode_input_kwargs,
    encode_output,
)
from conformance.record.registry import (
    KIND_BUILDER,
    KIND_VALIDATOR,
    REGISTRY,
    RegistryEntry,
    resolve_owner,
)

if TYPE_CHECKING:
    from mixpanel_headless._internal.auth.session import Session

LAYER3_DEFERRED_NODEIDS: frozenset[str] = frozenset(
    {
        # unittest.mock.patch of the module constant MAX_PAGES — a vector
        # cannot express "patch MAX_PAGES first" (design D2 exclusion 2).
        "tests/unit/test_pagination.py::TestPaginateAllRobustness"
        "::test_infinite_loop_same_cursor",
    }
)
"""Static layer3_deferred nodeids (design D10); PR-5 extends this during the
full-extraction triage (duration-assert families, OAuth interactive login)."""


@dataclass(frozen=True)
class RecordOptions:
    """Record-run configuration resolved from flags/env (design D1.3/D3).

    Attributes:
        out_dir: Vector output directory (``--mp-record-vectors``).
        extraction_date: Externally-injected manifest date stamp
            (``--mp-record-date``; NEVER the wall clock, design D3).
        source_commit: Externally-injected manifest commit stamp
            (``--mp-record-commit``; NEVER ``git rev-parse``, design D3).
    """

    out_dir: Path
    extraction_date: str
    source_commit: str


class _ThreadState(threading.local):
    """Per-thread span stack + re-entrancy depth (design D1.2).

    Attributes:
        span_stack: Entry calls currently on-stack, innermost last.
        depth: Wrapper nesting depth; capture is suppressed when > 0
            (outermost-wins re-entrancy guard).
    """

    def __init__(self) -> None:
        """Initialize empty per-thread state."""
        self.span_stack: list[EntryCallCapture] = []
        self.depth: int = 0


class _TeeSyncStream(httpx.SyncByteStream):
    """Sync stream TEE: records chunks AS THE CONSUMER YIELDS them (D1.1).

    Reading ahead would raise ``httpx.StreamConsumed`` in the test and
    destroy the chunk boundaries ``body_stream`` exists to preserve.
    """

    def __init__(self, inner: httpx.SyncByteStream, sink: list[bytes]) -> None:
        """Wrap ``inner`` so every yielded chunk is appended to ``sink``.

        Args:
            inner: The handler-provided one-shot byte stream.
            sink: Capture list receiving chunk copies in yield order.
        """
        self._inner = inner
        self._sink = sink

    def __iter__(self) -> Iterator[bytes]:
        """Yield chunks from the inner stream, recording each verbatim.

        Returns:
            Iterator over the inner stream's chunks, unchanged.
        """
        for chunk in self._inner:
            self._sink.append(chunk)
            yield chunk

    def close(self) -> None:
        """Close the inner stream (test behavior unchanged)."""
        self._inner.close()


class _TeeAsyncStream(httpx.AsyncByteStream):
    """Async stream TEE — mirror of :class:`_TeeSyncStream` (design D1.1)."""

    def __init__(self, inner: httpx.AsyncByteStream, sink: list[bytes]) -> None:
        """Wrap ``inner`` so every yielded chunk is appended to ``sink``.

        Args:
            inner: The handler-provided one-shot async byte stream.
            sink: Capture list receiving chunk copies in yield order.
        """
        self._inner = inner
        self._sink = sink

    async def __aiter__(self) -> Any:
        """Yield chunks from the inner stream, recording each verbatim.

        Yields:
            The inner stream's chunks, unchanged.
        """
        async for chunk in self._inner:
            self._sink.append(chunk)
            yield chunk

    async def aclose(self) -> None:
        """Close the inner stream (test behavior unchanged)."""
        await self._inner.aclose()


def _snapshot_request(request: httpx.Request) -> RecordedRequest:
    """Snapshot an outgoing request at the transport seam (design D1.1).

    Args:
        request: The httpx request about to reach the mock handler.

    Returns:
        The immutable capture-side request representation.
    """
    request.read()
    url = request.url
    port = f":{url.port}" if url.port is not None else ""
    params: dict[str, str | list[str]] = {}
    for key, value in url.params.multi_items():
        existing = params.get(key)
        if existing is None:
            params[key] = value
        elif isinstance(existing, list):
            existing.append(value)
        else:
            params[key] = [existing, value]
    return RecordedRequest(
        method=request.method,
        scheme_host=f"{url.scheme}://{url.host}{port}",
        path=url.path,
        params=params,
        headers={k.lower(): v for k, v in request.headers.items()},
        content=request.content,
    )


def _fill_response(
    recorded: RecordedResponse, response: httpx.Response, *, is_async: bool
) -> None:
    """Record a handler response, installing a stream TEE when needed.

    In-memory bodies (``content=``/``json=`` responses expose ``_content``)
    are captured directly — safe per design D1.1. Stream-backed bodies get
    the TEE so chunk boundaries are recorded verbatim as the consumer reads.

    Args:
        recorded: The capture slot to fill.
        response: The handler-returned response.
        is_async: True when serving ``handle_async_request``.
    """
    recorded.status = response.status_code
    headers = {k.lower(): v for k, v in response.headers.items()}
    headers.pop("content-length", None)
    recorded.headers = headers
    content = getattr(response, "_content", None)
    if isinstance(content, bytes):
        recorded.body_bytes = content
        return
    chunks: list[bytes] = []
    recorded.stream_chunks = chunks
    if is_async:
        response.stream = _TeeAsyncStream(
            response.stream,  # type: ignore[arg-type]
            chunks,
        )
    else:
        response.stream = _TeeSyncStream(
            response.stream,  # type: ignore[arg-type]
            chunks,
        )


def _expected_authorization(session: Session) -> str | None:
    """Derive the expected ``authorization`` value from a bound session.

    Design D5.2: the credential expectation is generated FROM THE BOUND
    SESSION, never from a fixed literal table, so fake-but-unusual
    credentials pass by construction.

    Args:
        session: The session bound to the requesting client.

    Returns:
        The exact expected header value, or None when no expectation can
        be derived (``oauth_browser`` resolves via TokenResolver — any
        observed auth header for such a session aborts in PR-2 scope).
    """
    from mixpanel_headless._internal.auth.account import (
        OAuthTokenAccount,
        ServiceAccount,
    )

    account = session.account
    if isinstance(account, ServiceAccount):
        raw = f"{account.username}:{account.secret.get_secret_value()}"
        return "Basic " + base64.b64encode(raw.encode("utf-8")).decode("ascii")
    if isinstance(account, OAuthTokenAccount) and account.token is not None:
        return "Bearer " + account.token.get_secret_value()
    return None


def _module_clock_mocked(func: Callable[..., Any]) -> bool:
    """Detect a test-local clock mock shadowing the D1.4 freeze (design D1.2).

    tests/unit/test_bookmark_builders.py patches the module ``date``
    attribute to a fixed instant; captures taken under such a mock would
    deterministically fail replay under ``RECORD_EPOCH`` and are excluded
    as ``test_local_clock``.

    Args:
        func: The wrapped callable whose defining module is checked.

    Returns:
        True when the module's ``date``/``datetime`` attribute is currently
        a ``unittest.mock`` object.
    """
    module = inspect.getmodule(func)
    if module is None:
        return False
    return any(
        isinstance(getattr(module, attr, None), umock.NonCallableMock)
        for attr in ("date", "datetime")
    )


class RecordSession:
    """Session-scoped recorder state machine (design D1).

    Owns the clock patches, the registry wrappers, the transport hook, and
    the per-test capture list. Instantiated once per record run by
    :func:`pytest_configure`; also constructible directly for unit tests
    (``activate()``/``deactivate()`` are exception-safe pairs).
    """

    def __init__(self, options: RecordOptions) -> None:
        """Initialize an inactive record session.

        Args:
            options: Output directory and manifest stamps.
        """
        self.options = options
        self.clock = RecordClock()
        self.captures: list[TestCapture] = []
        self.collected_nodeids: list[str] = []
        self.fatal_error: str | None = None
        self._current: TestCapture | None = None
        self._thread_state = _ThreadState()
        self._patchers: list[Any] = []
        self._active = False

    # ------------------------------------------------------------------
    # Activation / deactivation
    # ------------------------------------------------------------------

    def activate(self) -> None:
        """Install clock, registry wrappers, transport hook, CLI detector.

        Raises:
            RuntimeError: If already active.
        """
        if self._active:
            raise RuntimeError("RecordSession is already active")
        self.clock.start()
        try:
            self._wrap_registry()
            self._patch_transport()
            self._patch_cli_runner()
        except Exception:
            self.deactivate()
            raise
        self._active = True

    def deactivate(self) -> None:
        """Undo every patch installed by :meth:`activate` (idempotent)."""
        while self._patchers:
            patcher = self._patchers.pop()
            with contextlib.suppress(Exception):
                patcher.stop()
        if self.clock.active:
            self.clock.stop()
        self._active = False

    def _wrap_registry(self) -> None:
        """Wrap every registry entry once per session (design D1.2).

        Raises:
            ImportError: If a registry target module cannot be imported.
            AttributeError: If a registry target attribute is missing.
        """
        for entry in REGISTRY:
            owner, attr = resolve_owner(entry)
            func = getattr(owner, attr)
            wrapper = self._build_wrapper(entry, func)
            patcher = umock.patch.object(owner, attr, wrapper)
            patcher.start()
            self._patchers.append(patcher)

    def _patch_transport(self) -> None:
        """Patch ``httpx.MockTransport`` handlers at the class level (D1.1)."""
        original_sync = httpx.MockTransport.handle_request
        original_async = httpx.MockTransport.handle_async_request

        @functools.wraps(original_sync)
        def handle_request(
            transport_self: httpx.MockTransport, request: httpx.Request
        ) -> httpx.Response:
            """Record then delegate one sync transport interaction.

            Args:
                transport_self: The mock transport instance.
                request: The outgoing request.

            Returns:
                The handler's response, with a TEE installed when streamed.
            """
            interaction = self._before_transport(request, is_async=False)
            if interaction is None:
                return original_sync(transport_self, request)
            try:
                response = original_sync(transport_self, request)
            except BaseException as exc:
                interaction.response.transport_error = type(exc).__name__
                raise
            _fill_response(interaction.response, response, is_async=False)
            return response

        @functools.wraps(original_async)
        async def handle_async_request(
            transport_self: httpx.MockTransport, request: httpx.Request
        ) -> httpx.Response:
            """Record then delegate one async transport interaction.

            Args:
                transport_self: The mock transport instance.
                request: The outgoing request.

            Returns:
                The handler's response, with a TEE installed when streamed.
            """
            interaction = self._before_transport(request, is_async=True)
            if interaction is None:
                return await original_async(transport_self, request)
            try:
                response = await original_async(transport_self, request)
            except BaseException as exc:
                interaction.response.transport_error = type(exc).__name__
                raise
            _fill_response(interaction.response, response, is_async=True)
            return response

        for attr, replacement in (
            ("handle_request", handle_request),
            ("handle_async_request", handle_async_request),
        ):
            patcher = umock.patch.object(httpx.MockTransport, attr, replacement)
            patcher.start()
            self._patchers.append(patcher)

    def _patch_cli_runner(self) -> None:
        """Install the per-test ``CliRunner.invoke`` detector (design D10)."""
        import typer.testing

        original_invoke = typer.testing.CliRunner.invoke

        @functools.wraps(original_invoke)
        def invoke(runner_self: Any, *args: Any, **kwargs: Any) -> Any:
            """Flag the current test as CLI-driven, then delegate.

            Args:
                runner_self: The CliRunner instance.
                *args: Positional arguments for the original invoke.
                **kwargs: Keyword arguments for the original invoke.

            Returns:
                The original invoke result.
            """
            if self._current is not None:
                self._current.cli_used = True
            return original_invoke(runner_self, *args, **kwargs)

        patcher = umock.patch.object(typer.testing.CliRunner, "invoke", invoke)
        patcher.start()
        self._patchers.append(patcher)

    # ------------------------------------------------------------------
    # Per-test lifecycle
    # ------------------------------------------------------------------

    def begin_test(self, nodeid: str, suppressed_category: str | None) -> None:
        """Open a capture for one test and reset per-test determinism state.

        Args:
            nodeid: The pytest nodeid keying the capture (design D1.3).
            suppressed_category: Exclusion category decided at setup time,
                or None to record normally.
        """
        self.clock.reset_test_state()
        self._current = TestCapture(
            nodeid=nodeid, suppressed_category=suppressed_category
        )

    def note_outcome(self, nodeid: str, outcome: str) -> None:
        """Record a test phase outcome (worst outcome wins).

        Args:
            nodeid: The reporting test's nodeid.
            outcome: ``passed`` / ``failed`` / ``skipped`` for one phase.
        """
        capture = self._current
        if capture is None or capture.nodeid != nodeid:
            return
        if outcome == "failed" or (
            outcome == "skipped" and capture.outcome != "failed"
        ):
            capture.outcome = outcome

    def finish_test(self, nodeid: str) -> None:
        """Close the current capture and append it to the session list.

        Args:
            nodeid: The finishing test's nodeid (must match the open one).
        """
        capture = self._current
        if capture is not None and capture.nodeid == nodeid:
            self.captures.append(capture)
            self._current = None

    # ------------------------------------------------------------------
    # Entry-point wrapping (design D1.2)
    # ------------------------------------------------------------------

    def _build_wrapper(
        self, entry: RegistryEntry, func: Callable[..., Any]
    ) -> Callable[..., Any]:
        """Build the recording wrapper for one registry entry.

        Args:
            entry: The registry entry being wrapped.
            func: The original callable (plain function off the class or
                module).

        Returns:
            A ``functools.wraps``-preserving replacement callable.
        """
        signature = inspect.signature(func)
        is_method = "." in entry.target.partition(":")[2]

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            """Record the outermost invocation, then delegate.

            Args:
                *args: Original positional arguments (self included for
                    methods).
                **kwargs: Original keyword arguments.

            Returns:
                The original callable's return value (iterators wrapped so
                yielded items are recorded as the test consumes them).
            """
            state = self._thread_state
            capture = self._current
            if (
                capture is None
                or capture.suppressed_category is not None
                or state.depth > 0
            ):
                return func(*args, **kwargs)
            call = self._open_entry_call(
                entry, func, signature, is_method, args, kwargs
            )
            try:
                with self._span(call):
                    result = func(*args, **kwargs)
            except BaseException as exc:
                call.error = exc
                raise
            if isinstance(result, Iterator):
                return self._wrap_iterator(call, result)
            self._record_result(call, result)
            return result

        return wrapper

    def _open_entry_call(
        self,
        entry: RegistryEntry,
        func: Callable[..., Any],
        signature: inspect.Signature,
        is_method: bool,
        args: tuple[Any, ...],
        kwargs: dict[str, Any],
    ) -> EntryCallCapture:
        """Create and append the entry-call capture for one invocation.

        Encodes ``call.input`` AT CALL TIME (before mutation is possible),
        binds only explicitly-passed arguments (defaults stay defaults —
        design D1.2), extracts bound sessions, and applies the test-local
        clock-mock check for module-level builder entries.

        Args:
            entry: The registry entry invoked.
            func: The original callable (for clock-mock module lookup).
            signature: The callable's signature (bound without defaults).
            is_method: True when the first positional argument is ``self``.
            args: Original positional arguments.
            kwargs: Original keyword arguments.

        Returns:
            The appended :class:`EntryCallCapture`.
        """
        capture = self._current
        assert capture is not None  # guarded by the wrapper
        instance: Any = args[0] if (is_method and args) else None
        excluded: str | None = None
        arguments: dict[str, Any] = {}
        try:
            bound = signature.bind(*args, **kwargs)
        except TypeError:
            # The call itself will raise identically; record the shell so
            # ordering stays intact and let the library error propagate.
            excluded = "unserializable_input"
        else:
            parameters = list(signature.parameters.values())
            for name, value in bound.arguments.items():
                param = signature.parameters[name]
                if is_method and parameters and name == parameters[0].name:
                    continue
                if param.kind is inspect.Parameter.VAR_KEYWORD:
                    arguments.update(dict(value))
                else:
                    arguments[name] = value
        session, workspace_session = self._sessions_for(instance, arguments)
        arguments = {
            name: value
            for name, value in arguments.items()
            if not self._is_client_like(value)
        }
        if (
            is_method
            and instance is not None
            and entry.kind in (KIND_BUILDER, KIND_VALIDATOR)
            and not self._is_client_like(instance)
        ):
            # Method-on-value entries (types.CohortDefinition.to_dict): the
            # receiver IS the input — encoded under its parameter name so
            # the runner can decode it via the $type table and re-invoke
            # (design D4.2 item 8). Client/facade receivers are rebuilt
            # from call.session instead (design D7).
            arguments = {"self": instance, **arguments}
        if (
            excluded is None
            and not is_method
            and entry.kind in (KIND_BUILDER, KIND_VALIDATOR)
            and _module_clock_mocked(func)
        ):
            excluded = "test_local_clock"
        input_encoded: dict[str, Any] | None = None
        if excluded is None:
            try:
                input_encoded = encode_input_kwargs(arguments)
            except UnencodableValueError:
                excluded = "unserializable_input"
        call = EntryCallCapture(
            index=len(capture.entry_calls),
            entry=entry,
            input_encoded=input_encoded,
            session=session,
            workspace_session=workspace_session,
            excluded_reason=excluded,
        )
        capture.entry_calls.append(call)
        return call

    @staticmethod
    def _is_client_like(value: Any) -> bool:
        """Return whether a value is a client/facade instance (design D7).

        Such arguments are dropped from ``call.input``: the runner rebuilds
        the client from ``call.session`` and passes it itself (the
        ``paginate_all(client, ...)`` module-function pattern).

        Args:
            value: Candidate argument value.

        Returns:
            True for ``MixpanelAPIClient`` / ``Workspace`` instances.
        """
        from mixpanel_headless._internal.api_client import MixpanelAPIClient
        from mixpanel_headless.workspace import Workspace

        return isinstance(value, MixpanelAPIClient | Workspace)

    @staticmethod
    def _sessions_for(
        instance: Any, arguments: dict[str, Any]
    ) -> tuple[Session | None, Session | None]:
        """Extract the bound client session (+ facade session) for a call.

        Design D5.1: ``call.session`` is the session ACTUALLY bound to the
        client that makes the requests; ``workspace_session`` carries the
        facade session only when the two differ (two-session pattern).

        Args:
            instance: The receiver for method calls (None for module
                functions).
            arguments: Bound non-self arguments (scanned for a client when
                the receiver itself is not one).

        Returns:
            ``(client_session, workspace_session_or_None)``.
        """
        from mixpanel_headless._internal.api_client import MixpanelAPIClient
        from mixpanel_headless.workspace import Workspace

        if isinstance(instance, MixpanelAPIClient):
            return instance._session, None
        if isinstance(instance, Workspace):
            client = instance._api_client
            client_session = client._session if client is not None else None
            facade_session = instance._session
            if client_session is not None and facade_session == client_session:
                return client_session, None
            return client_session, facade_session
        for value in arguments.values():
            if isinstance(value, MixpanelAPIClient):
                return value._session, None
        return None, None

    @contextlib.contextmanager
    def _span(self, call: EntryCallCapture) -> Iterator[None]:
        """Mark ``call`` as on-stack for attribution + re-entrancy guarding.

        Args:
            call: The entry call now executing.

        Yields:
            None while the span is active.
        """
        state = self._thread_state
        state.depth += 1
        state.span_stack.append(call)
        try:
            yield
        finally:
            state.span_stack.pop()
            state.depth -= 1

    def _wrap_iterator(
        self, call: EntryCallCapture, inner: Iterator[Any]
    ) -> Iterator[Any]:
        """Wrap an iterator result so consumption stays attributed (D1.2/D2).

        Each ``next()`` re-enters the span (nested transport traffic during
        lazy pagination/streaming attributes to this call); yielded items
        are encoded into ``iterator_items`` (``expect.result`` = the array
        of yielded items, design D2).

        Args:
            call: The entry call that returned the iterator.
            inner: The library-returned iterator.

        Returns:
            A generator yielding the inner items unchanged.
        """

        def _generator() -> Iterator[Any]:
            """Yield inner items, recording each; mark exhaustion.

            Yields:
                The inner iterator's items, unchanged.

            Raises:
                BaseException: Whatever the inner iterator raises (recorded
                    on the entry call first).
            """
            items: list[Any] = []
            call.iterator_items = items
            while True:
                try:
                    with self._span(call):
                        item = next(inner)
                except StopIteration:
                    break
                except BaseException as exc:
                    call.error = exc
                    raise
                if call.excluded_reason is None:
                    try:
                        items.append(encode_expect_value(item))
                    except UnencodableValueError:
                        call.excluded_reason = "unserializable_input"
                yield item
            call.iterator_finished = True
            call.returned = True

        return _generator()

    def _record_result(self, call: EntryCallCapture, result: Any) -> None:
        """Encode a completed call's return value (design D1.2).

        Dispatches through the entry's ``output_codec`` (design D4.4) so
        validator returns serialize structurally per design D4.3 and
        model-class returns become name strings (D4.2 item 7).

        Args:
            call: The entry call that returned.
            result: The raw return value.
        """
        call.returned = True
        if call.excluded_reason is not None:
            return
        try:
            call.result_encoded = encode_output(call.entry.output_codec, result)
        except UnencodableValueError:
            call.excluded_reason = "unserializable_input"

    # ------------------------------------------------------------------
    # Transport capture (design D1.1)
    # ------------------------------------------------------------------

    def _before_transport(
        self, request: httpx.Request, *, is_async: bool
    ) -> RecordedInteraction | None:
        """Record the request side of a transport interaction.

        Args:
            request: The outgoing request.
            is_async: True under ``handle_async_request``.

        Returns:
            The appended interaction, or None when recording is inactive
            for the current test (suppressed category or no open capture).

        Raises:
            RecordingAbortError: On the D5.2 session-relative auth mismatch.
        """
        capture = self._current
        if capture is None or capture.suppressed_category is not None:
            return None
        span = (
            self._thread_state.span_stack[-1] if self._thread_state.span_stack else None
        )
        snapshot = _snapshot_request(request)
        if span is not None:
            self._verify_authorization(capture.nodeid, span, snapshot)
        interaction = RecordedInteraction(
            seq=len(capture.interactions),
            request=snapshot,
            response=RecordedResponse(),
            span_index=span.index if span is not None else None,
            is_async=is_async,
        )
        capture.interactions.append(interaction)
        return interaction

    def _verify_authorization(
        self, nodeid: str, span: EntryCallCapture, snapshot: RecordedRequest
    ) -> None:
        """Enforce the D5.2 abort rule on an observed authorization header.

        Args:
            nodeid: The current test's nodeid (for the error message).
            span: The attributed entry call carrying the bound session.
            snapshot: The recorded request.

        Raises:
            RecordingAbortError: When the observed value does not decode to
                the bound session's credentials (attribution bug or
                credential leakage), or no expectation can be derived for
                the session (``oauth_browser`` — unsupported in PR-2).
        """
        observed = snapshot.headers.get("authorization")
        if observed is None:
            return
        session = span.session
        expected = _expected_authorization(session) if session is not None else None
        if expected is None or observed != expected:
            message = (
                f"authorization header on {snapshot.method} {snapshot.path} in "
                f"{nodeid} does not match the session bound to the requesting "
                f"client (api={span.entry.api}) — recorder attribution bug or "
                "credential leakage (design D5.2); record run aborted"
            )
            self.fatal_error = message
            raise RecordingAbortError(message)

    # ------------------------------------------------------------------
    # Finalization
    # ------------------------------------------------------------------

    def finalize(self) -> None:
        """Run the emit pipeline over all captures (design D3/D5/D10).

        Raises:
            RecordingAbortError: If a fatal capture-time error occurred, or
                emit-time validation (schema/redaction/id collision) fails.
        """
        if self.fatal_error is not None:
            raise RecordingAbortError(self.fatal_error)
        from conformance.record import emit

        summary = emit.emit_corpus(
            captures=self.captures,
            collected_nodeids=self.collected_nodeids,
            options=emit.EmitOptions(
                out_dir=self.options.out_dir,
                extraction_date=self.options.extraction_date,
                source_commit=self.options.source_commit,
            ),
        )
        print(
            f"\n[mp-record] wrote {summary.total_vectors} vectors in "
            f"{len(summary.bundle_paths)} bundles to {self.options.out_dir}"
        )


def _suppression_category(item: pytest.Item) -> str | None:
    """Decide the setup-time exclusion category for a test (design D10).

    Args:
        item: The collected pytest item.

    Returns:
        ``live`` / ``destructive`` (marker), ``layer3_deferred`` (static
        nodeid list), ``hypothesis`` (runtime ``@given`` detection — NOT
        filename-only, design D10), or None to record normally.
    """
    if item.get_closest_marker("live") is not None:
        return "live"
    if item.get_closest_marker("destructive") is not None:
        return "destructive"
    if item.nodeid in LAYER3_DEFERRED_NODEIDS:
        return "layer3_deferred"
    test_obj = getattr(item, "obj", None)
    if test_obj is not None and hasattr(test_obj, "hypothesis"):
        return "hypothesis"
    return None


class RecordPlugin:
    """Pytest hook layer delegating to a :class:`RecordSession`."""

    def __init__(self, record_session: RecordSession) -> None:
        """Bind the hook layer to an activated record session.

        Args:
            record_session: The session receiving lifecycle events.
        """
        self._record = record_session

    def pytest_collection_modifyitems(self, items: list[pytest.Item]) -> None:
        """Snapshot collected nodeids for the emit-time id-collision pass.

        Also force-loads the Hypothesis ``ci`` profile defensively
        (derandomize — design D1.5); PBT tests are excluded anyway.

        Args:
            items: All collected test items.
        """
        self._record.collected_nodeids = [item.nodeid for item in items]
        try:
            from hypothesis import settings

            settings.load_profile("ci")
        except Exception:  # profile only exists once tests/conftest ran
            pass

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_setup(self, item: pytest.Item) -> None:
        """Open the capture for ``item`` before fixtures run.

        Args:
            item: The test about to run.
        """
        self._record.begin_test(item.nodeid, _suppression_category(item))

    @pytest.hookimpl(wrapper=True)
    def pytest_runtest_makereport(
        self, item: pytest.Item, call: pytest.CallInfo[None]
    ) -> Any:
        """Track per-phase outcomes (failed tests become freeze_incompatible).

        Args:
            item: The reporting test item.
            call: The phase call info.

        Returns:
            The report produced by the inner hook implementations.
        """
        del call
        report = yield
        if isinstance(report, pytest.TestReport):
            if report.failed:
                self._record.note_outcome(item.nodeid, "failed")
            elif report.skipped:
                self._record.note_outcome(item.nodeid, "skipped")
        return report

    def pytest_runtest_logfinish(
        self, nodeid: str, location: tuple[str, int | None, str]
    ) -> None:
        """Close the capture once every phase of a test has finished.

        Args:
            nodeid: The finished test's nodeid.
            location: Unused pytest hook argument.
        """
        del location
        self._record.finish_test(nodeid)

    def pytest_sessionfinish(self, session: pytest.Session, exitstatus: int) -> None:
        """Emit the corpus at session end (design D1.3).

        Args:
            session: Unused pytest hook argument.
            exitstatus: Unused pytest hook argument.

        Raises:
            RecordingAbortError: Propagated from the emit pipeline.
        """
        del session, exitstatus
        self._record.finalize()


_SESSION_KEY: pytest.StashKey[RecordSession] = pytest.StashKey()
"""Config stash slot holding the active record session for unconfigure."""


def pytest_addoption(parser: pytest.Parser) -> None:
    """Register the record-mode command-line flags (design D1.3/D3).

    Args:
        parser: The pytest option parser.
    """
    group = parser.getgroup("mp-record", "conformance vector recording")
    group.addoption(
        "--mp-record-vectors",
        action="store",
        default=None,
        metavar="DIR",
        help="Enable record mode and write conformance vectors to DIR "
        "(fallback env var: CONFORMANCE_RECORD_DIR).",
    )
    group.addoption(
        "--mp-record-date",
        action="store",
        default=None,
        metavar="DATE",
        help="Manifest extraction_date stamp — injected externally, never "
        "the wall clock (fallback: CONFORMANCE_RECORD_DATE).",
    )
    group.addoption(
        "--mp-record-commit",
        action="store",
        default=None,
        metavar="SHA",
        help="Manifest source_commit stamp — injected externally, never "
        "git rev-parse (fallback: CONFORMANCE_RECORD_COMMIT).",
    )


def pytest_configure(config: pytest.Config) -> None:
    """Activate record mode when the flag or env fallback is present.

    Also sets a defensive ``faulthandler_timeout`` so any residual hang
    under the frozen clock produces a traceback, not a stalled extraction
    (design risk register #2).

    Args:
        config: The pytest configuration.
    """
    out_dir = config.getoption("--mp-record-vectors") or os.environ.get(
        "CONFORMANCE_RECORD_DIR"
    )
    if not out_dir:
        return
    extraction_date = (
        config.getoption("--mp-record-date")
        or os.environ.get("CONFORMANCE_RECORD_DATE")
        or "UNSPECIFIED"
    )
    source_commit = (
        config.getoption("--mp-record-commit")
        or os.environ.get("CONFORMANCE_RECORD_COMMIT")
        or "UNSPECIFIED"
    )
    if "faulthandler_timeout" not in config.inicfg:
        config.inicfg["faulthandler_timeout"] = "300"
    options = RecordOptions(
        out_dir=Path(out_dir),
        extraction_date=str(extraction_date),
        source_commit=str(source_commit),
    )
    record_session = RecordSession(options)
    record_session.activate()
    config.stash[_SESSION_KEY] = record_session
    config.pluginmanager.register(RecordPlugin(record_session), "mp-record-hooks")


def pytest_unconfigure(config: pytest.Config) -> None:
    """Restore all patches when the pytest session tears down.

    Args:
        config: The pytest configuration.
    """
    record_session = config.stash.get(_SESSION_KEY, None)
    if record_session is not None:
        record_session.deactivate()
