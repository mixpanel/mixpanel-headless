"""Python differential-oracle server (design D14).

Implements the newline-delimited JSON-RPC 2.0 oracle protocol whose
normative specification lives at ``conformance/schema/oracle-protocol.md``:
``oracle.info`` / ``oracle.call`` / ``oracle.shutdown``, ASCII-safe framing
(``ensure_ascii=True``), and the R5.4 error-mapping rule — expected library
errors are DATA (``ok: false`` payloads with class name + code, messages
stripped), while only harness bugs surface as JSON-RPC ``error`` objects.

Phase-1 ``oracle.call`` surface (design D14): exactly the D4 BUILDER-side
registry entries — the five ``Workspace.build_*`` facades, the module-level
builders/validators/serializers, and the pythonCompat reference functions
including the D13 wire stub (which replays against a
:class:`conformance.runner.transport.VectorTransport` built from the
optional ``interactions`` param). ``wire_api``/``wire_state`` registry
entries are OUT of oracle scope in Phase 1 and answer with the
``WIRE_OUT_OF_SCOPE`` skip payload.

The stdin/stdout loop and the frozen clock/UUID environment (design D7)
live in ``conformance/oracle_py/__main__.py``; this module is transport-free
so protocol behavior is unit-testable in-process.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from conformance.record.codecs import (
    UndecodableValueError,
    UnencodableValueError,
    decode_input_kwargs,
)
from conformance.record.emit import _encode_error
from conformance.record.registry import (
    KIND_BUILDER,
    KIND_VALIDATOR,
    REGISTRY_BY_API,
    RegistryEntry,
)
from conformance.runner.canonical import (
    CanonicalizationError,
    canonicalize,
    canonicalize_error,
)
from conformance.runner.execute import (
    _encode_result,
    _isolated_home,
    _resolve_builder_target,
)
from conformance.runner.targets import TargetConstructionError

PROTOCOL_VERSION = "1.0"
"""Version stamp returned by ``oracle.info`` (oracle-protocol.md §2)."""

JSONRPC_PARSE_ERROR = -32700
"""JSON-RPC 2.0: the request line was not valid JSON."""

JSONRPC_INVALID_REQUEST = -32600
"""JSON-RPC 2.0: the request object was malformed."""

JSONRPC_METHOD_NOT_FOUND = -32601
"""JSON-RPC 2.0: the method is not one of the three oracle methods."""

JSONRPC_INVALID_PARAMS = -32602
"""JSON-RPC 2.0: params failed validation (unknown api, undecodable input)."""

JSONRPC_INTERNAL_ERROR = -32000
"""JSON-RPC 2.0 server range: harness-level failure inside the oracle
(unencodable output, canonicalization rejection, unexpected dispatch bug —
never an expected library error, which is ``ok: false`` DATA per R5.4)."""

WIRE_OUT_OF_SCOPE_CODE = "WIRE_OUT_OF_SCOPE"
"""Skip code answered for ``wire_api``/``wire_state`` apis (Phase-1 scope)."""


class OracleProtocolError(Exception):
    """A request failed at the PROTOCOL level (JSON-RPC ``error`` object).

    Raised internally by the dispatch/call paths for harness bugs — unknown
    api names, undecodable inputs, unencodable outputs, canonicalization
    rejections (e.g. a lone-surrogate string from a fuzz strategy, design
    D14). Expected library errors never raise this; they are returned as
    ``ok: false`` result DATA.

    Attributes:
        code: The JSON-RPC error code (one of the module constants).
    """

    def __init__(self, code: int, message: str) -> None:
        """Initialize the protocol error.

        Args:
            code: JSON-RPC error code.
            message: Human-readable description (free-form; never compared).
        """
        super().__init__(message)
        self.code = code


def _library_version() -> str:
    """Return the installed ``mixpanel_headless`` version for ``oracle.info``.

    Returns:
        The distribution version string, or ``"unknown"`` when metadata is
        unavailable (e.g. a non-installed source tree).
    """
    import importlib.metadata

    try:
        return importlib.metadata.version("mixpanel_headless")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def _source_commit() -> str:
    """Return the source-commit stamp for ``oracle.info``.

    Resolution order (oracle-protocol.md §3): the committed corpus
    manifest's ``source_commit`` when ``conformance/vectors/manifest.json``
    exists, else the ``CONFORMANCE_RECORD_COMMIT`` environment variable,
    else ``"unknown"``. Never ``git rev-parse`` — the oracle must not vary
    with worktree state (mirrors the design D3 injected-stamp rule).

    Returns:
        The 40-char commit SHA or ``"unknown"``.
    """
    manifest_path = Path(__file__).resolve().parents[1] / "vectors" / "manifest.json"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        commit = manifest.get("source_commit")
        if isinstance(commit, str) and commit:
            return commit
    except (OSError, ValueError):
        pass
    return os.environ.get("CONFORMANCE_RECORD_COMMIT", "unknown")


class OracleServer:
    """Stateful protocol server: one instance per oracle process/session.

    Transport-free by design: :meth:`handle_line` maps one request line to
    one response line, so the stdin/stdout loop (``__main__``) and the unit
    tests share the exact same dispatch path. In-process consumers (the
    fuzz-harness tests) may call :meth:`call_api` directly.

    Example:
        ```python
        server = OracleServer()
        server.handle_line(
            '{"jsonrpc": "2.0", "id": 1, "method": "oracle.info"}'
        )
        # '{"id": 1, "jsonrpc": "2.0", "result": {...}}'
        ```
    """

    def __init__(self, reset: Callable[[], None] | None = None) -> None:
        """Initialize the server.

        Args:
            reset: Per-call determinism hook invoked at the START of every
                ``oracle.call`` — ``RecordClock.reset_test_state`` in the
                real process (design D1.4/D7: UUID counter + frozen-clock
                epoch reset so no call's output depends on earlier calls).
                ``None`` in unit tests of clock-free targets.
        """
        self._reset = reset
        self._shutdown_requested = False

    @property
    def shutdown_requested(self) -> bool:
        """Return True once ``oracle.shutdown`` has been served.

        Returns:
            True when the read loop should exit after the current response.
        """
        return self._shutdown_requested

    def handle_line(self, line: str) -> str | None:
        """Serve one request line and return the response line.

        Never raises: every failure mode becomes a JSON-RPC ``error``
        response (a strategy-generated poison value must produce a
        protocol-level error, "not a hang or crash" — design D14).

        Args:
            line: One newline-stripped request line.

        Returns:
            The single-line, ASCII-safe JSON response, or ``None`` for
            blank lines (ignored per oracle-protocol.md §1).
        """
        if not line.strip():
            return None
        try:
            request = json.loads(line)
        except ValueError:
            return self._encode_response(
                None, error=(JSONRPC_PARSE_ERROR, "request line is not valid JSON")
            )
        if not isinstance(request, Mapping):
            return self._encode_response(
                None, error=(JSONRPC_INVALID_REQUEST, "request is not an object")
            )
        request_id = request.get("id")
        if request.get("jsonrpc") != "2.0":
            return self._encode_response(
                request_id,
                error=(JSONRPC_INVALID_REQUEST, "jsonrpc member must be '2.0'"),
            )
        method = request.get("method")
        if not isinstance(method, str):
            return self._encode_response(
                request_id,
                error=(JSONRPC_INVALID_REQUEST, "method member must be a string"),
            )
        try:
            result = self._dispatch(method, request.get("params"))
        except OracleProtocolError as exc:
            return self._encode_response(request_id, error=(exc.code, str(exc)))
        except Exception as exc:  # noqa: BLE001 - protocol crash boundary (D14)
            return self._encode_response(
                request_id,
                error=(
                    JSONRPC_INTERNAL_ERROR,
                    f"oracle dispatch failed: {type(exc).__name__}: {exc}",
                ),
            )
        return self._encode_response(request_id, result=result)

    def _dispatch(self, method: str, params: object) -> dict[str, Any]:
        """Route one request to its method handler.

        Args:
            method: The JSON-RPC method name.
            params: The raw ``params`` member (may be absent/None).

        Returns:
            The ``result`` object for the response.

        Raises:
            OracleProtocolError: For unknown methods or invalid params.
        """
        if method == "oracle.info":
            return self.info()
        if method == "oracle.shutdown":
            self._shutdown_requested = True
            return {"ok": True}
        if method == "oracle.call":
            if not isinstance(params, Mapping):
                raise OracleProtocolError(
                    JSONRPC_INVALID_PARAMS, "oracle.call requires a params object"
                )
            return self._call_from_params(params)
        raise OracleProtocolError(
            JSONRPC_METHOD_NOT_FOUND, f"unknown method {method!r}"
        )

    def info(self) -> dict[str, Any]:
        """Build the ``oracle.info`` result (oracle-protocol.md §3).

        Returns:
            ``{language, library_version, source_commit, protocol_version}``.
        """
        return {
            "language": "python",
            "library_version": _library_version(),
            "source_commit": _source_commit(),
            "protocol_version": PROTOCOL_VERSION,
        }

    def _call_from_params(self, params: Mapping[str, Any]) -> dict[str, Any]:
        """Validate ``oracle.call`` params and delegate to :meth:`call_api`.

        Args:
            params: The raw params object.

        Returns:
            The call result payload.

        Raises:
            OracleProtocolError: If ``api`` is missing/non-string or the
                optional members carry the wrong types.
        """
        api = params.get("api")
        if not isinstance(api, str) or not api:
            raise OracleProtocolError(
                JSONRPC_INVALID_PARAMS, "params.api must be a non-empty string"
            )
        encoded_input = params.get("input") or {}
        if not isinstance(encoded_input, Mapping):
            raise OracleProtocolError(
                JSONRPC_INVALID_PARAMS, "params.input must be an object when present"
            )
        session = params.get("session")
        if session is not None and not isinstance(session, Mapping):
            raise OracleProtocolError(
                JSONRPC_INVALID_PARAMS, "params.session must be an object when present"
            )
        interactions = params.get("interactions")
        if interactions is not None and not isinstance(interactions, Sequence):
            raise OracleProtocolError(
                JSONRPC_INVALID_PARAMS,
                "params.interactions must be an array when present",
            )
        return self.call_api(
            api,
            encoded_input,
            session=session,
            interactions=interactions,
        )

    def call_api(
        self,
        api: str,
        encoded_input: Mapping[str, Any],
        *,
        session: Mapping[str, Any] | None = None,
        interactions: Sequence[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Execute one registry-resolved api call (oracle-protocol.md §4).

        Args:
            api: The PYTHON dotted vector name (design D14: language-neutral
                naming — oracle-ts applies the naming map itself).
            encoded_input: ``call.input``-shaped kwargs (``$type``-tagged
                per design D4.4).
            session: Accepted for protocol-shape parity but UNUSED in
                Phase 1 — the builder surface is session-free (facade
                builders bind a synthetic session; sessions become
                meaningful when wire scope arrives in Phase 3).
            interactions: Recorded-interaction objects for the D13
                ``wirestub.*`` apis (Phase-1 protocol extension,
                oracle-protocol.md §4.3); ignored for builder apis.

        Returns:
            ``{ok: true, output: ...}`` or ``{ok: false, error: {class,
            code?, errors?}}`` (messages stripped per R5.4).

        Raises:
            OracleProtocolError: For unknown apis, undecodable input, and
                unencodable/uncanonicalizable outputs (harness-level, D14).
        """
        if self._reset is not None:
            self._reset()
        del session  # Phase-1 builder surface is session-free (see Args).
        entry = REGISTRY_BY_API.get(api)
        if entry is None:
            raise OracleProtocolError(
                JSONRPC_INVALID_PARAMS,
                f"unknown api {api!r} (not a registry entry — design D14 "
                "resolves api names through conformance/record/registry.py)",
            )
        if entry.kind in (KIND_BUILDER, KIND_VALIDATOR):
            return self._call_builder(entry, encoded_input)
        if api.partition(".")[0] == "wirestub":
            return self._call_wirestub(entry, encoded_input, interactions or [])
        return {
            "ok": False,
            "error": {"class": "Unsupported", "code": WIRE_OUT_OF_SCOPE_CODE},
        }

    def _call_builder(
        self, entry: RegistryEntry, encoded_input: Mapping[str, Any]
    ) -> dict[str, Any]:
        """Execute a builder/validator entry (the Phase-1 v1 surface, D14).

        Args:
            entry: The resolved registry entry.
            encoded_input: The ``$type``-tagged kwargs.

        Returns:
            The ``ok: true/false`` payload.

        Raises:
            OracleProtocolError: For undecodable input, target-construction
                failures, or unencodable outputs.
        """
        decoded = self._decode_input(encoded_input)
        try:
            target = _resolve_builder_target(entry, decoded)
        except TargetConstructionError as exc:
            raise OracleProtocolError(
                JSONRPC_INVALID_PARAMS, f"target construction failed: {exc}"
            ) from exc
        return self._invoke(entry, target, decoded)

    def _call_wirestub(
        self,
        entry: RegistryEntry,
        encoded_input: Mapping[str, Any],
        interactions: Sequence[Mapping[str, Any]],
    ) -> dict[str, Any]:
        """Execute a D13 wire-stub entry against a ``VectorTransport``.

        The Phase-1 transport story for the gate stub ONLY (design D14 puts
        real wire apis out of oracle scope until Phase 3): the caller ships
        the canned ``interactions[]`` and the stub replays through the same
        keyed transport the corpus runner uses.

        Args:
            entry: The ``wirestub.*`` registry entry.
            encoded_input: The ``$type``-tagged kwargs.
            interactions: Recorded-interaction objects served as canned
                responses.

        Returns:
            The ``ok: true/false`` payload.

        Raises:
            OracleProtocolError: For undecodable input or unencodable
                outputs.
        """
        from conformance.runner.targets import make_wirestub_client
        from conformance.runner.transport import VectorTransport

        decoded = self._decode_input(encoded_input)
        transport = VectorTransport(list(interactions))
        client = make_wirestub_client(transport)
        target = getattr(client, entry.api.partition(".")[2])
        return self._invoke(entry, target, decoded)

    def _decode_input(self, encoded_input: Mapping[str, Any]) -> dict[str, Any]:
        """Decode ``$type``-tagged kwargs through the shared codec table.

        Args:
            encoded_input: The ``call.input``-shaped object.

        Returns:
            Live Python kwargs.

        Raises:
            OracleProtocolError: If any value has no decoder (harness bug —
                the fuzz strategies encode through the SAME codec table).
        """
        try:
            return decode_input_kwargs(encoded_input)
        except UndecodableValueError as exc:
            raise OracleProtocolError(
                JSONRPC_INVALID_PARAMS, f"input decode failed: {exc}"
            ) from exc

    def _invoke(
        self,
        entry: RegistryEntry,
        target: Callable[..., Any],
        decoded: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Call the resolved target and encode its outcome as call DATA.

        Runs inside the same ``$HOME``/``MP_*`` sandbox as the corpus
        runner (design D7 via ``_isolated_home``) so library code can never
        read ambient credentials or pollute the real ``~/.mp``.

        Args:
            entry: The registry entry (output codec dispatch).
            target: The bound callable.
            decoded: Decoded kwargs.

        Returns:
            ``{ok: true, output}`` for returns; ``{ok: false, error}`` for
            raised library errors (messages stripped, R5.4).

        Raises:
            OracleProtocolError: If the RETURNED value cannot be encoded or
                canonicalized (harness-level per design D14 — e.g. a
                lone-surrogate string must yield a protocol error, never a
                crash).
        """
        raised: BaseException | None = None
        output: Any = None
        with _isolated_home():
            try:
                output = _encode_result(entry, target(**decoded))
            except UnencodableValueError as exc:
                raise OracleProtocolError(
                    JSONRPC_INTERNAL_ERROR, f"output encode failed: {exc}"
                ) from exc
            except Exception as exc:  # noqa: BLE001 - library errors are DATA
                raised = exc
        if raised is not None:
            return {"ok": False, "error": self._error_payload(raised)}
        try:
            canonicalize(output)
        except CanonicalizationError as exc:
            raise OracleProtocolError(
                JSONRPC_INTERNAL_ERROR, f"output canonicalization failed: {exc}"
            ) from exc
        return {"ok": True, "output": output}

    def _error_payload(self, raised: BaseException) -> dict[str, Any]:
        """Serialize a raised library error as comparable DATA (R5.4).

        Coded library errors serialize through the SAME structural encoder
        the recorder uses (``conformance.record.emit._encode_error``:
        class + code + ``errors[]`` with messages/suggestions/fixes
        stripped). Uncoded builtin raises (``ValueError``/``TypeError`` —
        R5.5-excluded from the corpus) still need a comparable differential
        value, so they encode as their bare class name: "Python raised
        ValueError / TS raised ValueError" stays a comparable pair.

        Args:
            raised: The exception the library call raised.

        Returns:
            The ``ok: false`` error object.

        Raises:
            OracleProtocolError: If the payload itself cannot be
                canonicalized (harness-level).
        """
        encoded = _encode_error(raised)
        if encoded is None:
            encoded = {"class": type(raised).__name__}
        try:
            canonicalize_error(encoded)
        except CanonicalizationError as exc:
            raise OracleProtocolError(
                JSONRPC_INTERNAL_ERROR, f"error payload canonicalization failed: {exc}"
            ) from exc
        return encoded

    def _encode_response(
        self,
        request_id: object,
        *,
        result: dict[str, Any] | None = None,
        error: tuple[int, str] | None = None,
    ) -> str:
        """Frame one JSON-RPC response as a single ASCII-safe line.

        ``ensure_ascii=True`` is the D14 framing rule: non-ASCII (and any
        astral character) is ``\\uXXXX``-escaped so no strategy-generated
        string can kill the bridge with a stdout encoding error; JSON
        string-escaping guarantees the payload never contains a raw
        newline, keeping the line framing safe.

        Args:
            request_id: The request's ``id`` member (echoed; ``None`` for
                unparseable requests).
            result: The result object (mutually exclusive with ``error``).
            error: ``(code, message)`` for error responses.

        Returns:
            The serialized response line (no trailing newline).
        """
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id}
        if error is not None:
            response["error"] = {"code": error[0], "message": error[1]}
        else:
            response["result"] = result
        return json.dumps(response, ensure_ascii=True, sort_keys=True)
