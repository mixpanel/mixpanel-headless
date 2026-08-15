"""Vector execution + diffing for the Python corpus runner (design D7).

Re-executes library code from ``call.input`` for every vector — never
replays recordings against themselves. Builder/validator vectors resolve
their entry point through the SAME registry the recorder used; wire/parse
vectors rebuild the recorded client around a
:class:`conformance.runner.transport.VectorTransport`, execute
``call.setup[]`` then the measured call, and diff (a) every captured
request against the recorded interaction sequence, (b) the returned/raised
value against ``expect.result``/``expect.error``, and (c) recorded-callback
call logs against ``expect.callback_calls``.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import tempfile
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from conformance.record.capture import RecordedRequest
from conformance.record.codecs import (
    RecordingCallback,
    decode_input_kwargs,
    encode_expect_value,
    encode_output,
)
from conformance.record.emit import _encode_error
from conformance.record.registry import (
    KIND_BUILDER,
    KIND_VALIDATOR,
    REGISTRY_BY_API,
    RegistryEntry,
    resolve_callable,
)
from conformance.runner.canonical import (
    canonicalize,
    canonicalize_error,
    headers_match,
)
from conformance.runner.loading import LoadedVector
from conformance.runner.targets import (
    TargetConstructionError,
    build_session,
    default_builder_session,
    make_api_client,
    make_oauth_flow,
    make_replays_service,
    make_wirestub_client,
    make_workspace,
    probe_region_callable,
)
from conformance.runner.transport import VectorTransport

_SCRUBBED_ENV_VARS = (
    "MP_USERNAME",
    "MP_SECRET",
    "MP_OAUTH_TOKEN",
    "MP_PROJECT_ID",
    "MP_REGION",
    "MP_WORKSPACE_ID",
    "MP_AUTH_FILE",
    "MP_CONFIG_PATH",
    "MP_OAUTH_STORAGE_DIR",
    "MP_TEST_GUARD_REAL_HOME",
)
"""Env vars scrubbed inside the per-vector sandbox: replay sessions come
from ``call.session`` exclusively — ambient credentials/config must never
leak into (or be touched by) a replay (mirrors tests/conftest
``_clean_mp_env``, design D1.5)."""


@contextlib.contextmanager
def _isolated_home() -> Iterator[None]:
    """Sandbox ``$HOME`` + ``MP_*`` env for one vector's replay (PR-6).

    Library code paths write per-account caches under ``Path.home()/.mp``
    (``MeService`` after a ``/me`` fetch). Two hazards without this:
    the replay POLLUTES THE REAL ``~/.mp`` with fake test state, and one
    vector's cache leaks into the next (a warm me-cache suppresses a
    recorded ``/me`` fetch, failing the interaction diff). A fresh temp
    HOME per vector removes both; the cost is ~1 ms per vector.

    Yields:
        None while the sandbox is active.
    """
    saved = {
        name: os.environ.get(name)
        for name in ("HOME", "USERPROFILE", *_SCRUBBED_ENV_VARS)
    }
    with tempfile.TemporaryDirectory(prefix="mp-conformance-home-") as home:
        os.environ["HOME"] = home
        os.environ["USERPROFILE"] = home
        for name in _SCRUBBED_ENV_VARS:
            os.environ.pop(name, None)
        try:
            yield
        finally:
            for name, value in saved.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value


_REQUEST_CORE_KEYS = (
    "method",
    "scheme_host",
    "path",
    "params",
    "json_body",
    "body_text",
    "body_base64",
)
"""``expectedRequest`` keys compared as one canonical structure; header and
absence assertions (``headers_contain``/``headers_absent``/``params_absent``)
diff separately with their own semantics (design D5.6/D6 rules 7-8)."""


@dataclass
class VectorOutcome:
    """Result of replaying one vector (design D9.3 taxonomy: this is the
    ``vector_failed``-vs-passed axis; runner crashes never reach here).

    Attributes:
        id: The vector id.
        kind: The vector kind.
        passed: True when every diff came back clean.
        reasons: Human-readable failure reasons (empty when passed).
    """

    id: str
    kind: str
    passed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class _ReplayContext:
    """Mutable per-vector replay state shared by setup + measured calls.

    Attributes:
        transport: The vector's replay transport.
        interactions: The recorded interactions (for target construction).
        session_encoded: The vector's ``call.session`` object, if any.
        workspace_session_encoded: ``call.workspace_session``, if any.
        client_options: Recorded client constructor options, if any.
        client: The current ``MixpanelAPIClient`` (built lazily; replaced
            when a setup call returns a sibling client — ``use()``).
        workspace: The current ``Workspace`` facade (built lazily).
        callback_stubs: Recording stubs injected for callback kwargs of the
            MEASURED call, keyed by kwarg name.
    """

    transport: VectorTransport
    interactions: list[Mapping[str, Any]]
    session_encoded: Mapping[str, Any] | None
    workspace_session_encoded: Mapping[str, Any] | None
    client_options: Mapping[str, Any] | None
    client: Any = None
    workspace: Any = None
    callback_stubs: dict[str, Any] = field(default_factory=dict)

    def get_client(self) -> Any:
        """Return (building lazily) the replay ``MixpanelAPIClient``.

        Returns:
            The client bound to the vector transport.

        Raises:
            TargetConstructionError: When no session is available to build
                a real client from.
        """
        if self.client is None:
            if self.session_encoded is None:
                # Only reachable for targets whose recorded client was
                # never exercised (ReplaysService CDN-only walks).
                session_obj = default_builder_session()
                browser_token = None
            else:
                session_obj = build_session(self.session_encoded)
                browser_token = (
                    str(self.session_encoded["token"])
                    if "token" in self.session_encoded
                    else None
                )
            self.client = make_api_client(
                session_obj, self.transport, self.client_options, browser_token
            )
        return self.client

    def get_workspace(self) -> Any:
        """Return (building lazily) the replay ``Workspace`` facade.

        The facade session is ``workspace_session`` when the vector carries
        one (two-session pattern, design D5.1), else the client session,
        else the synthetic builder session.

        Returns:
            The facade bound to the injected client.
        """
        if self.workspace is None:
            client = self.get_client()
            if self.workspace_session_encoded is not None:
                facade_session = build_session(self.workspace_session_encoded)
            elif self.session_encoded is not None:
                facade_session = build_session(self.session_encoded)
            else:
                facade_session = default_builder_session()
            self.workspace = make_workspace(facade_session, client)
        return self.workspace


def _serialize_actual_request(snapshot: RecordedRequest) -> dict[str, Any]:
    """Serialize a live request snapshot into the ``expectedRequest`` core.

    Mirrors ``conformance.record.emit._emit_request`` minus the header
    allowlist (headers diff via ``headers_contain`` subset semantics
    instead), so the replay-side representation can never disagree with
    what the recorder would have written.

    Args:
        snapshot: The captured live request.

    Returns:
        The core request object (method/scheme_host/path/params/body).
    """
    request: dict[str, Any] = {
        "method": snapshot.method,
        "scheme_host": snapshot.scheme_host,
        "path": snapshot.path,
    }
    if snapshot.params:
        request["params"] = snapshot.params
    if snapshot.content:
        content_type = snapshot.headers.get("content-type", "")
        body: dict[str, Any] | None = None
        if "json" in content_type:
            try:
                body = {"json_body": json.loads(snapshot.content)}
            except (ValueError, UnicodeDecodeError):
                body = None
        if body is None:
            try:
                body = {"body_text": snapshot.content.decode("utf-8")}
            except UnicodeDecodeError:
                body = {
                    "body_base64": base64.b64encode(snapshot.content).decode("ascii")
                }
        request.update(body)
    return request


def _compare_request(
    position: int,
    recorded: Mapping[str, Any],
    snapshot: RecordedRequest,
) -> list[str]:
    """Diff one served request against its recorded expectation.

    Args:
        position: The recorded interaction index (for messages).
        recorded: The recorded ``expectedRequest`` object.
        snapshot: The live request snapshot paired with it.

    Returns:
        Failure reasons (empty when the request matches).
    """
    failures: list[str] = []
    actual_core = _serialize_actual_request(snapshot)
    recorded_core = {
        key: recorded[key] for key in _REQUEST_CORE_KEYS if key in recorded
    }
    actual_canonical = canonicalize(actual_core)
    recorded_canonical = canonicalize(recorded_core)
    if actual_canonical != recorded_canonical:
        failures.append(
            f"interaction[{position}] request mismatch: "
            f"expected {recorded_canonical} got {actual_canonical}"
        )
    headers_contain = recorded.get("headers_contain")
    if isinstance(headers_contain, Mapping) and not headers_match(
        headers_contain, snapshot.headers
    ):
        failures.append(
            f"interaction[{position}] headers_contain mismatch: "
            f"expected {canonicalize(dict(headers_contain))} against "
            f"{canonicalize(dict(snapshot.headers))}"
        )
    for header in recorded.get("headers_absent", []):
        if str(header).lower() in snapshot.headers:
            failures.append(
                f"interaction[{position}] header {header!r} asserted absent but present"
            )
    for param in recorded.get("params_absent", []):
        if str(param) in snapshot.params:
            failures.append(
                f"interaction[{position}] param {param!r} asserted absent but present"
            )
    return failures


def _diff_interactions(
    transport: VectorTransport, interactions: list[Mapping[str, Any]]
) -> list[str]:
    """Diff the transport's served traffic against the recording (D2/D7).

    Args:
        transport: The vector transport after replay.
        interactions: The recorded interactions.

    Returns:
        Failure reasons: per-pair request mismatches, extra live requests,
        and recorded interactions never served.
    """
    failures: list[str] = []
    for position, snapshot in transport.pairs:
        request = interactions[position].get("request")
        request_map: Mapping[str, Any] = request if isinstance(request, Mapping) else {}
        failures.extend(_compare_request(position, request_map, snapshot))
    for snapshot in transport.extra_requests:
        failures.append(
            "extra request beyond the recording: "
            f"{snapshot.method} {snapshot.scheme_host}{snapshot.path}"
        )
    unconsumed = transport.unconsumed_indexes()
    if unconsumed:
        failures.append(f"recorded interactions never fired at replay: {unconsumed}")
    return failures


def _diff_callback_calls(
    expect: Mapping[str, Any], stubs: Mapping[str, Any]
) -> list[str]:
    """Diff injected callback stubs' logs against ``expect.callback_calls``.

    Args:
        expect: The vector's ``expect`` object.
        stubs: Injected stubs by kwarg name (``RecordingCallback`` or the
            replay client factory — anything with a ``calls`` list).

    Returns:
        Failure reasons (empty when every log matches).
    """
    failures: list[str] = []
    expected: Mapping[str, Any] = expect.get("callback_calls") or {}
    for name, stub in stubs.items():
        expected_log = expected.get(name, [])
        actual_log = list(stub.calls)
        if canonicalize(actual_log) != canonicalize(expected_log):
            failures.append(
                f"callback {name!r} call-log mismatch: "
                f"expected {canonicalize(expected_log)} got "
                f"{canonicalize(actual_log)}"
            )
    for name in expected:
        if name not in stubs:
            failures.append(
                f"recorded callback {name!r} had no injected stub at replay"
            )
    return failures


def _diff_error(expect_error: Mapping[str, Any], raised: BaseException) -> list[str]:
    """Diff a raised exception against ``expect.error`` (design D4.3/D6.6).

    Args:
        expect_error: The vector's expected-error object.
        raised: The exception the replayed call raised.

    Returns:
        Failure reasons (empty on a structural match).
    """
    encoded = _encode_error(raised)
    if encoded is None:
        return [
            "call raised an uncoded/unencodable exception at replay: "
            f"{type(raised).__name__}: {raised}"
        ]
    actual = canonicalize_error(encoded)
    expected = canonicalize_error(expect_error)
    if actual != expected:
        return [f"error mismatch: expected {expected} got {actual}"]
    return []


def _encode_result(entry: RegistryEntry | None, result: Any) -> Any:
    """Encode a replayed return value the way the recorder did (D1.2).

    Iterators are exhausted and encoded item-by-item (``expect.result`` is
    the array of yielded items, design D2); everything else dispatches
    through the entry's output codec.

    Args:
        entry: The registry entry, when the api resolves to one.
        result: The live return value.

    Returns:
        The vector-JSON representation.
    """
    if isinstance(result, Iterator):
        return [encode_expect_value(item) for item in result]
    codec = entry.output_codec if entry is not None else "json"
    return encode_output(codec, result)


def _collect_stubs(decoded: Mapping[str, Any]) -> dict[str, Any]:
    """Extract injected callback stubs from decoded call kwargs.

    Args:
        decoded: The decoded ``call.input`` kwargs.

    Returns:
        ``{kwarg_name: stub}`` for every ``RecordingCallback`` value.
    """
    return {
        name: value
        for name, value in decoded.items()
        if isinstance(value, RecordingCallback)
    }


def _execute_wire_call(
    context: _ReplayContext,
    api: str,
    encoded_input: Mapping[str, Any],
    *,
    measured: bool,
) -> Any:
    """Execute one entry-point call against the replay context (design D7).

    Args:
        context: The vector's replay context.
        api: The dotted entry-point name (``call.api`` / setup api).
        encoded_input: The encoded kwargs to decode and pass.
        measured: True for the measured call (callback stubs are collected
            for the callback-log diff; setup stubs are not diffed, matching
            the D2 setup-return limitation).

    Returns:
        The call's raw return value.

    Raises:
        TargetConstructionError: If the api prefix has no replay target.
        BaseException: Whatever the library call raises (the caller diffs
            it against ``expect.error``).
    """
    prefix, _, method_name = api.partition(".")
    decoded = decode_input_kwargs(encoded_input)
    stubs = _collect_stubs(decoded)
    if prefix == "api_client":
        target = getattr(context.get_client(), method_name)
    elif prefix == "workspace":
        target = getattr(context.get_workspace(), method_name)
    elif prefix == "pagination":
        func = resolve_callable(REGISTRY_BY_API[api])
        client = context.get_client()

        def target(**kwargs: Any) -> Any:
            """Invoke the paginator with the replay client prepended.

            Args:
                **kwargs: Decoded vector kwargs.

            Returns:
                The paginator's return value.
            """
            return func(client, **kwargs)

    elif prefix == "region_probe":
        target, factory = probe_region_callable(
            context.transport, context.interactions, decoded
        )
        stubs["client_factory"] = factory
    elif prefix == "oauth_flow":
        flow = make_oauth_flow(context.transport, context.interactions)
        target = getattr(flow, method_name)
    elif prefix == "replays":
        service = make_replays_service(context.get_client(), context.transport)
        target = getattr(service, method_name)
    elif prefix == "wirestub":
        target = getattr(make_wirestub_client(context.transport), method_name)
    else:
        raise TargetConstructionError(
            f"no replay target for api prefix {prefix!r} ({api})"
        )
    if measured:
        context.callback_stubs = stubs
    result = target(**decoded)
    from mixpanel_headless._internal.api_client import MixpanelAPIClient
    from mixpanel_headless.workspace import Workspace

    if isinstance(result, MixpanelAPIClient):
        # ``use()``/``with_project()`` siblings: later calls in the test
        # ran against the returned client (design D2 wire_state model).
        context.client = result
        context.workspace = None
    elif isinstance(result, Workspace):
        context.workspace = result
    return result


def _run_wire(vector: LoadedVector) -> list[str]:
    """Replay one wire/parse vector and return its failure reasons.

    Args:
        vector: The loaded vector (kind ``wire`` or ``parse``).

    Returns:
        Failure reasons (empty when the vector passes).
    """
    body = vector.body
    call: Mapping[str, Any] = body["call"]
    expect: Mapping[str, Any] = body["expect"]
    interactions_raw = expect.get("interactions") or []
    interactions: list[Mapping[str, Any]] = list(interactions_raw)
    transport = VectorTransport(interactions)
    context = _ReplayContext(
        transport=transport,
        interactions=interactions,
        session_encoded=call.get("session"),
        workspace_session_encoded=call.get("workspace_session"),
        client_options=call.get("client_options"),
    )
    failures: list[str] = []
    for setup in call.get("setup") or []:
        try:
            _execute_wire_call(
                context, str(setup["api"]), setup.get("input") or {}, measured=False
            )
        except Exception:  # noqa: S110 - deliberate, see comment
            # Setup returns/raises are NOT diffed (design D2 logged
            # limitation): earlier test calls may have raised under
            # pytest.raises at record time too. Their request sides stay
            # fully diffed via interactions[]; divergence surfaces there.
            continue
    raised: BaseException | None = None
    result: Any = None
    try:
        result = _execute_wire_call(
            context, str(call["api"]), call.get("input") or {}, measured=True
        )
        if isinstance(result, Iterator):
            result = [encode_expect_value(item) for item in result]
        else:
            entry = REGISTRY_BY_API.get(str(call["api"]))
            result = _encode_result(entry, result)
    except Exception as exc:
        raised = exc
    if "error" in expect:
        if raised is None:
            failures.append(
                "expected error "
                f"{canonicalize_error(expect['error'])} but call returned "
                f"{canonicalize(result)}"
            )
        else:
            failures.extend(_diff_error(expect["error"], raised))
    elif raised is not None:
        failures.append(
            f"unexpected error at replay: {type(raised).__name__}: {raised}"
        )
    elif "result" in expect:
        expected_canonical = canonicalize(expect["result"])
        actual_canonical = canonicalize(result)
        if expected_canonical != actual_canonical:
            failures.append(
                f"result mismatch: expected {expected_canonical} got {actual_canonical}"
            )
    if vector.kind == "wire":
        failures.extend(_diff_interactions(transport, interactions))
    failures.extend(_diff_callback_calls(expect, context.callback_stubs))
    return failures


def _resolve_builder_target(entry: RegistryEntry, decoded: dict[str, Any]) -> Any:
    """Resolve the callable for a builder/validator vector (design D7).

    Module-level targets resolve through the registry; ``Workspace``
    facade methods bind to a synthetic-session facade over an EMPTY
    ``VectorTransport`` (any network attempt fails loudly); method-on-value
    targets (``types.CohortDefinition.to_dict``) bind to the decoded
    ``self`` receiver from ``call.input``.

    Args:
        entry: The registry entry for ``call.api``.
        decoded: Decoded kwargs (``self`` is popped here when present).

    Returns:
        The bound callable to invoke with the remaining kwargs.

    Raises:
        TargetConstructionError: When a method target misses its receiver.
    """
    _, _, attr_path = entry.target.partition(":")
    if "." not in attr_path:
        return resolve_callable(entry)
    cls_name, method_name = attr_path.split(".", 1)
    if cls_name == "Workspace":
        session_obj = default_builder_session()
        client = make_api_client(session_obj, VectorTransport([]), None)
        workspace = make_workspace(session_obj, client)
        return getattr(workspace, method_name)
    receiver = decoded.pop("self", None)
    if receiver is None:
        raise TargetConstructionError(
            f"method-on-value entry {entry.api} without a decoded 'self' "
            "receiver in call.input"
        )
    return getattr(receiver, method_name)


def _run_builder(vector: LoadedVector) -> list[str]:
    """Replay one builder/validation-error vector (design D7).

    Args:
        vector: The loaded vector.

    Returns:
        Failure reasons (empty when the vector passes).
    """
    body = vector.body
    call: Mapping[str, Any] = body["call"]
    api = str(call["api"])
    entry = REGISTRY_BY_API.get(api)
    if entry is None or entry.kind not in (KIND_BUILDER, KIND_VALIDATOR):
        return [f"api {api!r} is not a registered builder/validator entry"]
    decoded = decode_input_kwargs(call.get("input") or {})
    stubs = _collect_stubs(decoded)
    target = _resolve_builder_target(entry, decoded)
    expect: Mapping[str, Any] = body["expect"]
    failures: list[str] = []
    raised: BaseException | None = None
    result: Any = None
    try:
        raw = target(**decoded)
        result = _encode_result(entry, raw)
    except Exception as exc:
        raised = exc
    if "error" in expect:
        if raised is None:
            failures.append(
                "expected error "
                f"{canonicalize_error(expect['error'])} but call returned "
                f"{canonicalize(result)}"
            )
        else:
            failures.extend(_diff_error(expect["error"], raised))
    elif raised is not None:
        failures.append(
            f"unexpected error at replay: {type(raised).__name__}: {raised}"
        )
    else:
        expected_canonical = canonicalize(expect.get("output"))
        actual_canonical = canonicalize(result)
        if expected_canonical != actual_canonical:
            failures.append(
                f"output mismatch: expected {expected_canonical} got {actual_canonical}"
            )
    failures.extend(_diff_callback_calls(expect, stubs))
    return failures


def run_vector(vector: LoadedVector) -> VectorOutcome:
    """Replay one vector under the already-installed replay clock (D7).

    Any exception escaping the vector's own execution (decode failures,
    target construction, library crashes) is caught HERE and reported as a
    vector failure — the D9.3 ``runner_crashed`` verdict is reserved for
    failures outside vector execution (corpus load, clock setup, harness
    bugs), which the CLI handles at its own level.

    Args:
        vector: The loaded vector.

    Returns:
        The outcome with pass/fail and reasons.
    """
    try:
        with _isolated_home():
            if vector.kind in ("builder", "validation-error"):
                reasons = _run_builder(vector)
            elif vector.kind in ("wire", "parse"):
                reasons = _run_wire(vector)
            else:
                reasons = [f"unknown vector kind {vector.kind!r}"]
    except Exception as exc:  # noqa: BLE001 - vector isolation boundary
        reasons = [
            f"replay infrastructure error inside vector: {type(exc).__name__}: {exc}"
        ]
    return VectorOutcome(
        id=vector.id, kind=vector.kind, passed=not reasons, reasons=reasons
    )
