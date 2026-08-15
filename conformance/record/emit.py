"""Vector serialization + corpus emission for record mode (design D3/D5/D10).

The record plugin hands this module the raw per-test captures at session
finish; :func:`emit_corpus` classifies each capture (design D1.3 per-capture
classification), serializes vectors, runs the global id-collision pass, the
D5 header-allowlist / auth-pattern / redaction rules, the emit-side
unordered-group sort, and self-validates EVERY emitted vector against the
committed schema before writing JSONL bundles + ``manifest.json`` +
``api-index.json`` (design D3 layout).

All output is canonical JSON (sorted keys, compact separators, UTF-8) so a
re-extraction with the same injected date/commit stamps is byte-identical
(design D3 regeneration story / D8 drift check).
"""

from __future__ import annotations

import base64
import hashlib
import inspect
import json
import platform
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from conformance.record.capture import (
    EntryCallCapture,
    RecordedInteraction,
    RecordedRequest,
    RecordedResponse,
    RecordingAbortError,
    TestCapture,
)
from conformance.record.clock import RECORD_EPOCH
from conformance.record.codecs import UnencodableValueError, encode_expect_value
from conformance.record.registry import (
    KIND_BUILDER,
    KIND_VALIDATOR,
    KIND_WIRE_API,
    KIND_WIRE_STATE,
    REGISTRY_BY_API,
    resolve_callable,
)

if TYPE_CHECKING:
    from mixpanel_headless._internal.auth.session import Session

SCHEMA_VERSION = "1.0"
"""Vector schema version stamped into every vector and the manifest."""

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schema" / "vector.schema.json"
"""The committed vector schema used for emit-time self-validation."""

_SLUG_BAD_CHARS = re.compile(r"[^a-z0-9_-]+")
"""Characters replaced by ``-`` when slugging a nodeid (design D3)."""

_ENTROPY_SHAPE = re.compile(r"^[A-Za-z0-9+/=_-]{40,}$")
"""Base64/hex-shaped string screen for the D5.4 redaction denylist."""

_ENTROPY_MIN_DISTINCT_CHARS = 10
"""Minimum distinct characters for an entropy-shape hit: real base64/hex
credentials are high-diversity, while low-diversity fixtures (a 4 KiB
``"x" * 4096`` truncation body, ``"a" * 64`` filler ids) carry no secret
entropy and must not abort extraction (design D5.4, PR-5 refinement)."""

_FS_PATH_MARKERS = ("/pytest-", "/tmp/", "/var/folders/", "/private/var/")
"""Substrings marking test-temp filesystem paths (D10 ``fs_dependent``)."""

_HTTPX_DEFAULT_ACCEPT_ENCODINGS = frozenset(
    {"gzip, deflate", "gzip, deflate, br", "gzip, deflate, br, zstd", "identity"}
)
"""httpx-default ``accept-encoding`` values — never emitted (design D5.6)."""

_WIRE_KINDS = frozenset({KIND_WIRE_API, KIND_WIRE_STATE})
"""Registry kinds participating in the wire setup/measured model (D2)."""

_CAPABILITY_PATH_TABLE: tuple[tuple[str, str], ...] = (
    ("segmentation", "segmentation"),
    ("funnel", "funnels"),
    ("flows", "flows"),
    ("retention", "retention"),
    ("engage", "engage"),
    ("cohort", "cohorts"),
    ("bookmark", "bookmarks"),
    ("insights", "bookmarks"),
    ("annotation", "entities"),
    ("dashboard", "entities"),
    ("webhook", "entities"),
    ("feature-flag", "entities"),
    ("experiment", "entities"),
    ("alert", "entities"),
    ("lexicon", "data-governance"),
    ("lookup", "data-governance"),
    ("upload", "data-governance"),
    ("storage.googleapis.com", "data-governance"),
    ("drop", "data-governance"),
    ("custom-propert", "data-governance"),
    ("custom-event", "data-governance"),
    ("replay", "replays"),
    ("export", "streaming"),
    ("stream", "streaming"),
    ("/me", "auth"),
    ("oauth", "auth"),
    ("token", "auth"),
    ("events/names", "discovery"),
    ("events/properties", "discovery"),
    ("events/top", "discovery"),
    ("properties/values", "discovery"),
)
"""Ordered endpoint-substring -> capability table for wire vectors (D3)."""


@dataclass(frozen=True)
class EmitOptions:
    """Configuration for one emit pass (design D3 manifest stamps).

    Attributes:
        out_dir: Root directory receiving bundles + manifest + api-index.
        extraction_date: Externally-injected manifest date stamp.
        source_commit: Externally-injected manifest commit stamp.
    """

    out_dir: Path
    extraction_date: str
    source_commit: str


@dataclass
class EmitSummary:
    """Result of one emit pass (returned to the plugin for reporting).

    Attributes:
        total_vectors: Number of vectors written across all bundles.
        bundle_paths: Paths of the JSONL bundles written.
        exclusions: Manifest exclusion category counts.
    """

    total_vectors: int
    bundle_paths: list[Path] = field(default_factory=list)
    exclusions: dict[str, int] = field(default_factory=dict)


@dataclass
class _PendingVector:
    """A classified vector awaiting id assignment and serialization.

    Attributes:
        nodeid: Owning pytest nodeid.
        call_index: Entry-call index used for the ``-N`` ordinal ordering.
        api: The measured ``call.api`` dotted name.
        capability: Corpus capability directory.
        kind: Vector kind (``builder``/``wire``/``validation-error``).
        body: The vector object minus ``id`` (filled in during emission).
    """

    nodeid: str
    call_index: int
    api: str
    capability: str
    kind: str
    body: dict[str, Any]


class KeepOrderDict(dict[str, Any]):
    """Marker dict whose key ORDER is data, not presentation (PR-6).

    Sorted-keys storage is lossy for order-sensitive payload subtrees:
    ``call.input`` dicts pass through the library into form bodies /
    ``json.dumps``'d strings in USER order, and served response-body
    object order drives outputs like ``get_event_properties`` (dict-key
    iteration). Subtrees wrapped in this marker serialize in insertion
    order — still fully deterministic across re-extraction (the order
    comes from test source), so the D8 drift byte-diff is unaffected.
    Everything else keeps sorted keys per design D3.
    """


def keep_order_tree(value: Any) -> Any:
    """Recursively mark a payload subtree as order-preserving.

    Args:
        value: A JSON-encodable structure (dicts preserve insertion order).

    Returns:
        The same structure with every dict converted to
        :class:`KeepOrderDict`.
    """
    if isinstance(value, dict):
        return KeepOrderDict(
            (key, keep_order_tree(member)) for key, member in value.items()
        )
    if isinstance(value, list):
        return [keep_order_tree(member) for member in value]
    return value


def _canonical_tree(value: Any) -> Any:
    """Rebuild a structure with canonical key order for serialization.

    Args:
        value: A JSON-encodable structure, possibly carrying
            :class:`KeepOrderDict` subtrees.

    Returns:
        A new structure whose plain dicts are rebuilt in sorted-key order
        (codepoint sort, matching ``json.dumps(sort_keys=True)``) and whose
        :class:`KeepOrderDict` nodes keep insertion order.
    """
    if isinstance(value, KeepOrderDict):
        return {key: _canonical_tree(member) for key, member in value.items()}
    if isinstance(value, dict):
        return {key: _canonical_tree(value[key]) for key in sorted(value)}
    if isinstance(value, list):
        return [_canonical_tree(member) for member in value]
    return value


def canonical_json(value: Any) -> str:
    """Serialize a value as canonical vector JSON (design D3 bundling).

    Sorted keys (except :class:`KeepOrderDict` payload subtrees), compact
    separators, UTF-8 (non-ASCII emitted verbatim) — the byte-stable form
    both the bundles and the D8 drift diff rely on.

    Args:
        value: A JSON-encodable structure.

    Returns:
        The canonical JSON string (no trailing newline).
    """
    return json.dumps(_canonical_tree(value), separators=(",", ":"), ensure_ascii=False)


def interaction_sort_key(interaction: Mapping[str, Any]) -> str:
    """Compute the canonical ``(method, path, params)`` key (design D2/D6.9).

    Used both for the emit-side unordered-group sort and (later, D7) keyed
    serving inside unordered groups.

    Args:
        interaction: A serialized interaction object.

    Returns:
        The canonical JSON of the request's method/path/params triple.
    """
    request = interaction.get("request", {})
    return canonical_json(
        [request.get("method"), request.get("path"), request.get("params")]
    )


def sort_unordered_groups(
    interactions: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sort members of each unordered group by canonical key (design D2).

    Interactions WITHOUT ``unordered_group`` keep their recorded positions;
    within each group id, members are reordered among the positions the
    group occupies, sorted by :func:`interaction_sort_key` — emit-side
    determinism so async scheduling never produces spurious drift diffs.

    Args:
        interactions: Serialized interaction objects in recorded order.

    Returns:
        A new list with each unordered group's members sorted.
    """
    result: list[dict[str, Any] | None] = list(interactions)
    groups: dict[int, list[int]] = {}
    for position, interaction in enumerate(interactions):
        group = interaction.get("unordered_group")
        if isinstance(group, int):
            groups.setdefault(group, []).append(position)
    for positions in groups.values():
        members = sorted((interactions[p] for p in positions), key=interaction_sort_key)
        for position, member in zip(positions, members, strict=True):
            result[position] = member
    return [entry for entry in result if entry is not None]


# ---------------------------------------------------------------------------
# Slugging + id collision pass (design D3)
# ---------------------------------------------------------------------------


def slug_for_nodeid(nodeid: str) -> str:
    """Derive the deterministic slug from a FULL pytest nodeid (design D3).

    Module path stem + test class (if any) + function name + parametrize id,
    lowercased, with ``[^a-z0-9_-]`` runs collapsed to ``-``.

    Args:
        nodeid: The exact pytest nodeid.

    Returns:
        The sanitized slug (no collision suffix).
    """
    file_part, _, test_part = nodeid.partition("::")
    stem = Path(file_part).stem
    raw = f"{stem}-{test_part.replace('::', '-')}".lower()
    return _SLUG_BAD_CHARS.sub("-", raw).strip("-")


def build_slug_map(nodeids: Iterable[str]) -> dict[str, str]:
    """Run the global id-collision pass over all collected nodeids (D3).

    Any two DIFFERENT nodeids whose slugs collide (case-only parametrize-id
    clashes after lowercasing) each get a deterministic
    ``-h<first-8-hex-of-sha1(nodeid)>`` suffix — both colliders suffixed.

    Args:
        nodeids: Every collected nodeid (superset of emitting nodeids).

    Returns:
        Mapping of nodeid to final collision-free slug.
    """
    unique = sorted(set(nodeids))
    slugs = {nodeid: slug_for_nodeid(nodeid) for nodeid in unique}
    counts = Counter(slugs.values())
    result: dict[str, str] = {}
    for nodeid, slug in slugs.items():
        if counts[slug] > 1:
            digest = hashlib.sha1(nodeid.encode("utf-8")).hexdigest()[:8]
            result[nodeid] = f"{slug}-h{digest}"
        else:
            result[nodeid] = slug
    return result


# ---------------------------------------------------------------------------
# Session serialization + credential rules (design D5)
# ---------------------------------------------------------------------------


def _encode_session(
    session: Session, resolved_token: str | None = None
) -> dict[str, Any]:
    """Serialize a bound session into the vector ``call.session`` object.

    Credentials are recorded VERBATIM — they are fake test values whatever
    their spelling (design D5.1); the D5.4 redaction screen is the
    real-secret tripwire.

    Args:
        session: The session bound to the requesting client.
        resolved_token: Bearer token observed on the wire for
            resolver-backed accounts (``oauth_browser`` / env-backed
            ``oauth_token`` whose ``token`` is None) — adopted into the
            encoded session so replay can reproduce the auth header
            (design D5.2 PR-5 refinement).

    Returns:
        The schema ``$defs.session`` object.

    Raises:
        RecordingAbortError: If the account type is not one of the three
            first-class variants.
    """
    from mixpanel_headless._internal.auth.account import (
        OAuthBrowserAccount,
        OAuthTokenAccount,
        ServiceAccount,
    )

    account = session.account
    encoded: dict[str, Any] = {
        "region": account.region,
        "project_id": session.project.id,
        "account_name": account.name,
    }
    if session.workspace is not None:
        encoded["workspace_id"] = session.workspace.id
    if session.headers:
        # Custom headers attached at resolution time are LIBRARY-sent
        # traffic (they appear in headers_contain via the D5.6 custom-key
        # allowlist), so replay must rebuild the session with them or the
        # header diff can never pass (PR-6 replay finding).
        encoded["headers"] = {
            str(key): str(value) for key, value in session.headers.items()
        }
    if isinstance(account, ServiceAccount):
        encoded["type"] = "service_account"
        encoded["username"] = account.username
        encoded["secret"] = account.secret.get_secret_value()
        if account.default_project is not None:
            encoded["default_project"] = account.default_project
    elif isinstance(account, OAuthTokenAccount):
        encoded["type"] = "oauth_token"
        if account.token is not None:
            encoded["token"] = account.token.get_secret_value()
        elif resolved_token is not None:
            encoded["token"] = resolved_token
        if account.default_project is not None:
            encoded["default_project"] = account.default_project
    elif isinstance(account, OAuthBrowserAccount):
        encoded["type"] = "oauth_browser"
        if resolved_token is not None:
            encoded["token"] = resolved_token
    else:  # pragma: no cover - the Account union is closed
        raise RecordingAbortError(
            f"unknown account type {type(account).__name__} cannot be recorded"
        )
    return encoded


def _session_auth_value(session: Session) -> str | None:
    """Compute the exact expected ``authorization`` value for a session.

    Args:
        session: The bound session.

    Returns:
        The exact header value, or None when not derivable
        (``oauth_browser`` resolves via TokenResolver).
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


def _session_allowed_strings(sessions: Iterable[Session | None]) -> set[str]:
    """Collect every credential-derivable string for the redaction screen.

    Args:
        sessions: The sessions attached to one vector (client + facade).

    Returns:
        Exact strings that must NOT trip the D5.4 denylist: usernames,
        secrets, tokens, computed auth values, and their regex patterns.
    """
    allowed: set[str] = set()
    for session in sessions:
        if session is None:
            continue
        encoded = _encode_session(session)
        for key in ("username", "secret", "token"):
            value = encoded.get(key)
            if isinstance(value, str):
                allowed.add(value)
        auth = _session_auth_value(session)
        if auth is not None:
            allowed.add(auth)
            allowed.add(f"^{re.escape(auth)}$")
            allowed.add(auth.split(" ", 1)[1])
    return allowed


def _redaction_scan(vector: Mapping[str, Any], allowed: set[str]) -> None:
    """Apply the D5.4 redaction denylist over one emitted vector.

    Rules (design D5.4): base64/hex-shaped strings of length >= 40 not
    derivable from the bound session's credentials, ``sk-`` prefixes,
    ``Bearer`` values not equal to the bound session's token, and absolute
    home paths. Hits fail extraction loudly — never a silent scrub. The
    entropy rule deliberately skips ``$type: bytes`` payload data,
    ``body_base64``, and ``body_stream`` chunk data (base64 by
    construction — e.g. recorded CSV upload bodies). URL-path-shaped
    strings (leading ``/`` or >2 slash segments) are exempt from the
    entropy rule: the base64 alphabet contains ``/``, so API paths like
    ``/api/app/projects/12345/annotations/tags/`` would otherwise
    false-positive.

    Args:
        vector: The fully-serialized vector object.
        allowed: Exact strings derivable from the vector's own sessions.

    Raises:
        RecordingAbortError: On any denylist hit.
    """

    def fail(rule: str, value: str) -> None:
        """Raise the loud extraction failure for one denylist hit.

        Args:
            rule: The violated rule name.
            value: The offending string (truncated in the message).

        Raises:
            RecordingAbortError: Always.
        """
        raise RecordingAbortError(
            f"redaction denylist hit ({rule}) in vector "
            f"{vector.get('id', '<unassigned>')}: {value[:80]!r} — design D5.4"
        )

    def scan(node: Any, *, skip_entropy: bool) -> None:
        """Recursively scan one JSON node.

        Args:
            node: Current JSON value.
            skip_entropy: True under known-base64 payload fields.
        """
        if isinstance(node, str):
            if node in allowed:
                return
            if node.startswith("sk-"):
                fail("sk-prefix", node)
            if "/Users/" in node or "/home/" in node:
                fail("home-path", node)
            if node.startswith("Bearer "):
                fail("foreign-bearer", node)
            if (
                not skip_entropy
                and _ENTROPY_SHAPE.fullmatch(node)
                and not node.startswith("/")
                and node.count("/") <= 2
                and len(set(node)) >= _ENTROPY_MIN_DISTINCT_CHARS
            ):
                fail("entropy-shape", node)
            return
        if isinstance(node, Mapping):
            base64_payload = node.get("$type") == "bytes" or "body_stream" in node
            for key, value in node.items():
                child_skip = (
                    skip_entropy
                    or key in ("body_base64", "body_stream")
                    or (base64_payload and key == "data")
                )
                scan(value, skip_entropy=child_skip)
            return
        if isinstance(node, list):
            for value in node:
                scan(value, skip_entropy=skip_entropy)

    scan(vector, skip_entropy=False)


# ---------------------------------------------------------------------------
# Request/response serialization (design D1.1/D5.6)
# ---------------------------------------------------------------------------


def _emit_request_headers(
    recorded: RecordedRequest, session: Session | None
) -> tuple[dict[str, Any], list[str]]:
    """Apply the D5.6 emission allowlist to one recorded request's headers.

    Kept: ``authorization`` (as the D5.2 session-derived pattern),
    ``content-type`` when the library set it, custom headers the bound
    session injected, and ``accept-encoding`` only when it differs from
    httpx's default (recorded with a ``node_only`` flag). Transport-added
    headers are never emitted.

    When the bound session yields no derivable expectation (resolver-backed
    accounts, or no session at all — ``probe_region``-style inputs), the
    pattern is generated from the OBSERVED value: capture-time verification
    (design D5.2 acceptance paths 2/3) already proved that value is either
    resolver-resolved for the bound session or carried inside
    ``call.input``, so it replays from the vector itself.

    Args:
        recorded: The captured request snapshot (lowercase header keys).
        session: The session bound to the requesting client, if known.

    Returns:
        ``(headers_contain, headers_node_only)`` — both possibly empty.

    Raises:
        RecordingAbortError: If an observed ``authorization`` value
            contradicts a session-derivable expectation (recorder
            attribution bug surfacing at emit time).
    """
    contain: dict[str, Any] = {}
    node_only: list[str] = []
    custom_keys = (
        {key.lower() for key in session.headers} if session is not None else set()
    )
    for key, value in recorded.headers.items():
        if key == "authorization":
            expected = _session_auth_value(session) if session is not None else None
            if expected is not None and value != expected:
                raise RecordingAbortError(
                    "authorization header contradicts the bound session "
                    f"at emit time ({recorded.method} {recorded.path}) — "
                    "design D5.2"
                )
            contain[key] = {"pattern": f"^{re.escape(expected or value)}$"}
        elif key == "content-type" or key in custom_keys:
            contain[key] = value
        elif key == "accept-encoding":
            if value not in _HTTPX_DEFAULT_ACCEPT_ENCODINGS:
                contain[key] = value
                node_only.append(key)
    return contain, node_only


def _emit_request(recorded: RecordedRequest, session: Session | None) -> dict[str, Any]:
    """Serialize one recorded request into the schema ``expectedRequest``.

    Args:
        recorded: The captured request snapshot.
        session: The bound session for header allowlisting.

    Returns:
        The ``expectedRequest`` object.

    Raises:
        RecordingAbortError: Propagated from the header allowlist pass.
    """
    request: dict[str, Any] = {
        "method": recorded.method,
        "scheme_host": recorded.scheme_host,
        "path": recorded.path,
    }
    if recorded.params:
        request["params"] = recorded.params
    headers_contain, node_only = _emit_request_headers(recorded, session)
    if headers_contain:
        request["headers_contain"] = headers_contain
    if node_only:
        request["headers_node_only"] = node_only
    if recorded.content:
        content_type = recorded.headers.get("content-type", "")
        body: dict[str, Any] | None = None
        if "json" in content_type:
            try:
                body = {"json_body": json.loads(recorded.content)}
            except (ValueError, UnicodeDecodeError):
                body = None
        if body is None:
            try:
                body = {"body_text": recorded.content.decode("utf-8")}
            except UnicodeDecodeError:
                body = {
                    "body_base64": base64.b64encode(recorded.content).decode("ascii")
                }
        request.update(body)
    return request


def _emit_response(recorded: RecordedResponse) -> dict[str, Any]:
    """Serialize one recorded response into ``givenResponse``/``transportError``.

    Args:
        recorded: The captured response snapshot.

    Returns:
        The response side of an interaction.

    Raises:
        RecordingAbortError: If the capture is incomplete (no status and no
            transport error — a recorder bug).
    """
    if recorded.transport_error is not None:
        error: dict[str, Any] = {"transport_error": recorded.transport_error}
        if recorded.transport_error_message is not None:
            # Library error details may embed the message verbatim
            # (probe_region attempt bodies) — replay re-raises with it.
            error["message"] = recorded.transport_error_message
        return error
    if recorded.status is None:
        raise RecordingAbortError(
            "recorded response has neither status nor transport_error — "
            "recorder bug (design D1.1)"
        )
    response: dict[str, Any] = {"status": recorded.status}
    if recorded.headers:
        response["headers"] = dict(recorded.headers)
    # NOTE: parsed JSON bodies below are wrapped keep_order_tree — served
    # object key order is mock-environment data the replay must reproduce
    # (get_event_properties returns keys in body order, PR-6).
    if recorded.stream_chunks is not None:
        chunks: list[dict[str, str]] = []
        for chunk in recorded.stream_chunks:
            try:
                chunks.append({"encoding": "utf8", "data": chunk.decode("utf-8")})
            except UnicodeDecodeError:
                chunks.append(
                    {
                        "encoding": "base64",
                        "data": base64.b64encode(chunk).decode("ascii"),
                    }
                )
        if chunks:
            response["body_stream"] = chunks
    elif recorded.body_bytes:
        content_type = (recorded.headers or {}).get("content-type", "")
        body: dict[str, Any] | None = None
        if "json" in content_type:
            try:
                body = {"body": keep_order_tree(json.loads(recorded.body_bytes))}
            except (ValueError, UnicodeDecodeError):
                body = None
        if body is None:
            try:
                body = {"body_text": recorded.body_bytes.decode("utf-8")}
            except UnicodeDecodeError:
                body = {
                    "body_base64": base64.b64encode(recorded.body_bytes).decode("ascii")
                }
        response.update(body)
    return response


def _emit_interaction(
    interaction: RecordedInteraction, session: Session | None
) -> dict[str, Any]:
    """Serialize one transport interaction (design D2 ``interactions[]``).

    Args:
        interaction: The captured interaction.
        session: The bound session for header allowlisting.

    Returns:
        The ``interaction`` object with ``seq``.
    """
    return {
        "seq": interaction.seq,
        "request": _emit_request(interaction.request, session),
        "response": _emit_response(interaction.response),
    }


# ---------------------------------------------------------------------------
# Error serialization (design D4.3)
# ---------------------------------------------------------------------------


def _encode_error(error: BaseException) -> dict[str, Any] | None:
    """Serialize a raised library error structurally (design D4.3, R5.4).

    Args:
        error: The exception the measured call raised.

    Returns:
        The ``expectedError`` object, or None for uncoded raises
        (``ValueError``/``TypeError``/pydantic — excluded per R5.5).
    """
    import httpx as _httpx

    from mixpanel_headless.exceptions import (
        BookmarkValidationError,
        MixpanelHeadlessError,
    )

    if isinstance(error, BookmarkValidationError):
        errors = [
            {"path": err.path, "code": err.code, "severity": err.severity}
            for err in error.errors
        ]
        return {
            "class": type(error).__name__,
            "code": error.code,
            "errors": errors,
        }
    if isinstance(error, MixpanelHeadlessError):
        encoded: dict[str, Any] = {
            "class": type(error).__name__,
            "code": error.code,
        }
        details: dict[str, Any] = {}
        for key, value in error.details.items():
            if key in ("message", "suggestion", "fix"):
                continue
            try:
                details[key] = encode_expect_value(value)
            except UnencodableValueError:
                continue
        if details:
            encoded["details_contain"] = details
        return encoded
    if isinstance(error, _httpx.HTTPError):
        return {"class": type(error).__name__}
    return None


# ---------------------------------------------------------------------------
# Classification (design D1.3/D2/D10)
# ---------------------------------------------------------------------------


def _contains_fs_path(node: Any) -> bool:
    """Detect test-temp filesystem paths inside encoded input (D10).

    ``call.input`` values pointing at pytest ``tmp_path`` files cannot be
    replayed in either runner AND change every run (nondeterministic temp
    names), so such vectors are excluded as ``fs_dependent``.

    Args:
        node: Encoded input JSON node.

    Returns:
        True when any nested string carries a temp-path marker.
    """
    if isinstance(node, str):
        return any(marker in node for marker in _FS_PATH_MARKERS)
    if isinstance(node, Mapping):
        return any(_contains_fs_path(value) for value in node.values())
    if isinstance(node, list):
        return any(_contains_fs_path(value) for value in node)
    return False


def _wire_capability(
    measured: EntryCallCapture, interactions: Sequence[RecordedInteraction]
) -> str:
    """Assign the corpus capability for one wire vector (design D3).

    Registry-assigned capabilities win (module-level wire entries);
    otherwise the endpoint->capability table is consulted over the measured
    call's first attributed interaction, falling back to ``entities``.

    Args:
        measured: The measured wire entry call.
        interactions: The vector's interactions in order.

    Returns:
        The capability directory name.
    """
    if measured.entry.capability:
        return measured.entry.capability
    for interaction in interactions:
        target = f"{interaction.request.scheme_host}{interaction.request.path}".lower()
        for marker, capability in _CAPABILITY_PATH_TABLE:
            if marker in target:
                return capability
    return "entities"


def _builder_vector(call: EntryCallCapture, nodeid: str) -> _PendingVector | None:
    """Build the pending vector for one builder/validator entry call.

    Args:
        call: The captured entry call (not excluded).
        nodeid: The owning test's nodeid.

    Returns:
        The pending vector, or None when the raise was uncoded (the caller
        counts ``uncoded_raise``).
    """
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_test": nodeid,
        "origin": "extracted",
        "capability": call.entry.capability or "validation",
        "call": {
            "api": call.entry.api,
            # keep_order_tree: input dicts flow through the library in
            # USER order (form bodies, json.dumps'd strings — PR-6).
            "input": keep_order_tree(call.input_encoded or {}),
        },
    }
    if call.error is not None:
        encoded_error = _encode_error(call.error)
        if encoded_error is None:
            return None
        kind = (
            "validation-error"
            if encoded_error.get("errors") is not None
            else KIND_BUILDER
        )
        body["kind"] = kind
        body["expect"] = {"error": encoded_error}
    else:
        body["kind"] = KIND_BUILDER
        kind = KIND_BUILDER
        output = (
            call.iterator_items
            if call.iterator_items is not None
            else call.result_encoded
        )
        body["expect"] = {"output": output}
    callback_calls = {name: log for name, log in call.callback_calls.items() if log}
    if callback_calls:
        # Observed call logs for $type:callback kwargs (design D4.4); the
        # runners diff their recording stubs' logs against this.
        body["expect"]["callback_calls"] = callback_calls
    return _PendingVector(
        nodeid=nodeid,
        call_index=call.index,
        api=call.entry.api,
        capability=str(body["capability"]),
        kind=str(body["kind"]),
        body=body,
    )


def _interaction_session(
    capture: TestCapture,
    interaction: RecordedInteraction,
    default: Session | None,
) -> Session | None:
    """Resolve the session bound to the entry call that fired ``interaction``.

    Setup calls may run under a different session than the measured call
    (``use(account=...)`` sequences), so per-interaction header allowlisting
    must consult the interaction's OWN span, not the measured call's.

    Args:
        capture: The owning test capture.
        interaction: The attributed transport interaction.
        default: Fallback session (the measured call's) when the span
            carries none.

    Returns:
        The span's session, or ``default`` when unavailable.
    """
    index = interaction.span_index
    if index is not None and 0 <= index < len(capture.entry_calls):
        session = capture.entry_calls[index].session
        if session is not None:
            return session
    return default


def _resolved_session_token(
    capture: TestCapture,
    session: Session | None,
    attributed: Sequence[RecordedInteraction],
) -> tuple[str | None, str | None]:
    """Adopt the observed bearer for resolver-backed sessions (design D5.2).

    ``oauth_browser`` and env-backed ``oauth_token`` sessions resolve their
    bearer via a ``TokenResolver`` at request time, so no expectation is
    derivable from the session object. When every observed bearer across
    the vector is IDENTICAL, that value becomes the encoded session's
    ``token`` (replay reproduces the header). When observed values VARY
    (rotating-resolver freshness tests), the resolver stub is an
    unserializable dependency and the vector is excluded.

    Args:
        capture: The owning test capture.
        session: The measured call's session.
        attributed: The vector's attributed interactions.

    Returns:
        ``(resolved_token, exclusion_category)`` — at most one is non-None.
    """
    if session is None or _session_auth_value(session) is not None:
        return None, None
    observed: set[str] = set()
    for interaction in attributed:
        if _interaction_session(capture, interaction, session) != session:
            continue
        value = interaction.request.headers.get("authorization")
        if value is not None:
            observed.add(value)
    if len(observed) > 1:
        return None, "unserializable_input"
    if observed:
        value = next(iter(observed))
        if value.startswith("Bearer "):
            return value[len("Bearer ") :], None
    return None, None


def _fallback_auth_strings(capture: TestCapture) -> set[str]:
    """Collect capture-time-justified auth values for the redaction screen.

    Observed ``authorization`` values that capture-time verification
    accepted through the D5.2 fallback paths (input-carried credentials,
    resolver-resolved bearers) legitimately appear in emitted vectors as
    patterns / adopted session tokens, so they must not trip the
    ``foreign-bearer`` / entropy rules.

    Args:
        capture: The finished test capture.

    Returns:
        Exact strings (value, pattern form, token part) to allow.
    """
    allowed: set[str] = set()
    for interaction in capture.interactions:
        index = interaction.span_index
        if index is None or not (0 <= index < len(capture.entry_calls)):
            continue
        session = capture.entry_calls[index].session
        if session is not None and _session_auth_value(session) is not None:
            continue
        value = interaction.request.headers.get("authorization")
        if value is None:
            continue
        allowed.add(value)
        allowed.add(f"^{re.escape(value)}$")
        if " " in value:
            allowed.add(value.split(" ", 1)[1])
    return allowed


def _wire_vector(
    capture: TestCapture,
    wire_calls: Sequence[EntryCallCapture],
    attributed: Sequence[RecordedInteraction],
) -> tuple[_PendingVector | None, str | None]:
    """Build the single wire vector for one test (design D2 setup/measured).

    Args:
        capture: The full test capture.
        wire_calls: Wire-kind entry calls in call order.
        attributed: Transport interactions attributed to entry calls.

    Returns:
        ``(vector, exclusion_category)`` — exactly one is non-None.
    """
    measured: EntryCallCapture | None = None
    for call in wire_calls:
        if call.entry.kind == KIND_WIRE_API:
            measured = call
    if measured is None:
        return None, "wire_state_only_traffic"
    for call in wire_calls:
        if call.index > measured.index and any(
            interaction.span_index == call.index for interaction in attributed
        ):
            return None, "post_measured_traffic"
        if call.excluded_reason is not None:
            return None, call.excluded_reason
        if _contains_fs_path(call.input_encoded):
            return None, "fs_dependent"
    if measured.error is None and (
        measured.iterator_items is not None and not measured.iterator_finished
    ):
        return None, "partial_iterator"
    expect: dict[str, Any] = {}
    if measured.error is not None:
        encoded_error = _encode_error(measured.error)
        if encoded_error is None:
            return None, "uncoded_raise"
        expect["error"] = encoded_error
    else:
        expect["result"] = (
            measured.iterator_items
            if measured.iterator_items is not None
            else measured.result_encoded
        )
    session = measured.session
    resolved_token, token_exclusion = _resolved_session_token(
        capture, session, attributed
    )
    if token_exclusion is not None:
        return None, token_exclusion
    interactions = sort_unordered_groups(
        [
            _emit_interaction(
                interaction, _interaction_session(capture, interaction, session)
            )
            for interaction in attributed
        ]
    )
    if not interactions:
        return None, "no_seam_hit"
    expect["interactions"] = interactions
    callback_calls = {name: log for name, log in measured.callback_calls.items() if log}
    if callback_calls:
        # Observed call logs for $type:callback kwargs (design D4.4); the
        # runners inject recording stubs and diff their logs against this.
        expect["callback_calls"] = callback_calls
    call_obj: dict[str, Any] = {
        "api": measured.entry.api,
        # keep_order_tree: input dicts flow through the library in USER
        # order (form bodies, json.dumps'd strings — PR-6).
        "input": keep_order_tree(measured.input_encoded or {}),
    }
    setup = [
        {
            "api": call.entry.api,
            "input": keep_order_tree(call.input_encoded or {}),
        }
        for call in wire_calls
        if call.index < measured.index
    ]
    if setup:
        call_obj["setup"] = setup
    if session is not None:
        call_obj["session"] = _encode_session(session, resolved_token)
    if measured.workspace_session is not None:
        call_obj["workspace_session"] = _encode_session(measured.workspace_session)
    if measured.client_options is not None:
        call_obj["client_options"] = dict(measured.client_options)
    capability = _wire_capability(measured, attributed)
    body: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "source_test": capture.nodeid,
        "origin": "extracted",
        "capability": capability,
        "kind": "wire",
        "call": call_obj,
        "expect": expect,
    }
    return (
        _PendingVector(
            nodeid=capture.nodeid,
            call_index=measured.index,
            api=measured.entry.api,
            capability=capability,
            kind="wire",
            body=body,
        ),
        None,
    )


_DETAILED_EXCLUSIONS = frozenset(
    {
        "uncoded_raise",
        "unserializable_input",
        "test_local_clock",
        "fs_dependent",
        "layer3_deferred",
        "raw_transport_no_entrypoint",
        "freeze_incompatible",
        "partial_iterator",
        "post_measured_traffic",
    }
)
"""Exclusion categories whose per-nodeid callsites are written into the
manifest (design D4.3 ``uncoded_raises`` worklist; D10 "logged with
callsite so the codec table grows deliberately"). High-volume categories
(``no_seam_hit``, ``cli``, ``hypothesis``, ...) are counted only."""


class _ExclusionLog:
    """Exclusion counter + per-nodeid callsite log (design D10/D4.3).

    Attributes:
        counts: Category -> excluded-capture count.
        details: Category -> sorted-later nodeid list, kept only for
            :data:`_DETAILED_EXCLUSIONS` categories.
    """

    def __init__(self) -> None:
        """Initialize empty counts and details."""
        self.counts: Counter[str] = Counter()
        self.details: dict[str, list[str]] = {}

    def add(self, category: str, nodeid: str) -> None:
        """Count one exclusion, logging the callsite for detail categories.

        Args:
            category: The D10 exclusion category name.
            nodeid: The excluded capture's pytest nodeid.
        """
        self.counts[category] += 1
        if category in _DETAILED_EXCLUSIONS:
            self.details.setdefault(category, []).append(nodeid)


def _classify_capture(
    capture: TestCapture, exclusions: _ExclusionLog
) -> list[_PendingVector]:
    """Classify one test capture into vectors + exclusion counts (D1.3/D10).

    Args:
        capture: The finished test capture.
        exclusions: Mutable exclusion log (category -> count + callsites).

    Returns:
        Pending vectors emitted by this test, in entry-call order.
    """
    nodeid = capture.nodeid
    if capture.suppressed_category is not None:
        exclusions.add(capture.suppressed_category, nodeid)
        return []
    if capture.cli_used:
        exclusions.add("cli", nodeid)
        return []
    if capture.outcome == "skipped":
        exclusions.add("skipped_upstream", nodeid)
        return []
    if capture.outcome == "failed":
        exclusions.add("freeze_incompatible", nodeid)
        return []
    vectors: list[_PendingVector] = []
    for call in capture.entry_calls:
        if call.entry.kind not in (KIND_BUILDER, KIND_VALIDATOR):
            continue
        if call.excluded_reason is not None:
            exclusions.add(call.excluded_reason, nodeid)
            continue
        if _contains_fs_path(call.input_encoded):
            exclusions.add("fs_dependent", nodeid)
            continue
        vector = _builder_vector(call, capture.nodeid)
        if vector is None:
            exclusions.add("uncoded_raise", nodeid)
        else:
            vectors.append(vector)
    wire_calls = [
        call for call in capture.entry_calls if call.entry.kind in _WIRE_KINDS
    ]
    attributed = [
        interaction
        for interaction in capture.interactions
        if interaction.span_index is not None
    ]
    raw = [
        interaction
        for interaction in capture.interactions
        if interaction.span_index is None
    ]
    if raw:
        exclusions.add("raw_transport_no_entrypoint", nodeid)
    if wire_calls and attributed:
        vector, category = _wire_vector(capture, wire_calls, attributed)
        if vector is not None:
            vectors.append(vector)
        elif category is not None:
            exclusions.add(category, nodeid)
    elif wire_calls:
        # Wire entry points ran but never reached the transport (e.g. an
        # input-validation raise before any request) — counted separately
        # from no_seam_hit for D10 denominator honesty.
        exclusions.add("wire_call_no_transport", nodeid)
    if not vectors and not capture.entry_calls and not capture.interactions:
        exclusions.add("no_seam_hit", nodeid)
    vectors.sort(key=lambda vector: vector.call_index)
    return vectors


# ---------------------------------------------------------------------------
# api-index sidecar (design D4.4)
# ---------------------------------------------------------------------------


def _api_index_entry(api: str, capability: str) -> dict[str, Any]:
    """Build one api-index record for a distinct ``call.api`` (design D4.4).

    Args:
        api: The dotted vector name.
        capability: The capability observed for this api's first vector.

    Returns:
        The sidecar record with kind, target module, and signature shape.
    """
    entry = REGISTRY_BY_API[api]
    func = resolve_callable(entry)
    positional: list[str] = []
    kwonly: list[str] = []
    parameters = list(inspect.signature(func).parameters.values())
    for position, parameter in enumerate(parameters):
        if position == 0 and parameter.name in ("self", "cls"):
            continue
        if parameter.kind is inspect.Parameter.KEYWORD_ONLY:
            kwonly.append(parameter.name)
        elif parameter.kind in (
            inspect.Parameter.POSITIONAL_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            positional.append(parameter.name)
    return {
        "kind": entry.kind,
        "target": entry.target,
        "module": entry.target.partition(":")[0],
        "params": positional,
        "kwonly": kwonly,
        "capability": entry.capability or capability,
    }


# ---------------------------------------------------------------------------
# Emission pipeline (design D3)
# ---------------------------------------------------------------------------


def _validate_vector(vector: Mapping[str, Any], validator: Any) -> None:
    """Self-validate one vector against the committed schema (design D1/D3).

    Args:
        vector: The fully-assembled vector object.
        validator: A prepared ``jsonschema`` Draft 2020-12 validator.

    Raises:
        RecordingAbortError: If the vector violates the schema.
    """
    errors = sorted(validator.iter_errors(vector), key=str)
    if errors:
        raise RecordingAbortError(
            f"vector {vector.get('id', '<unassigned>')} failed schema "
            f"self-validation: {errors[0].message} at "
            f"{'/'.join(str(part) for part in errors[0].absolute_path)}"
        )


def _tool_versions() -> dict[str, str]:
    """Collect the manifest ``tool_versions`` block (design D3).

    Returns:
        Versions of python, httpx, pydantic, and hypothesis.
    """
    import httpx as _httpx
    import pydantic as _pydantic

    try:
        import hypothesis as _hypothesis

        hypothesis_version = _hypothesis.__version__
    except ImportError:  # pragma: no cover - hypothesis is a dev dep
        hypothesis_version = "absent"
    return {
        "python": platform.python_version(),
        "httpx": _httpx.__version__,
        "pydantic": _pydantic.version.VERSION,
        "hypothesis": hypothesis_version,
    }


def emit_corpus(
    captures: Sequence[TestCapture],
    collected_nodeids: Sequence[str],
    options: EmitOptions,
) -> EmitSummary:
    """Serialize all captures into the on-disk corpus (design D3 layout).

    Pipeline: classify captures (D1.3/D10) -> assign deterministic ids with
    the global collision pass + ``-N`` ordinals (D3) -> redaction-scan and
    schema-validate every vector (D5.4/D1) -> write per-(capability, source
    file) JSONL bundles sorted by id, ``manifest.json``, and
    ``api-index.json``.

    Args:
        captures: Finished per-test captures in run order.
        collected_nodeids: Every collected nodeid (for the collision pass);
            when empty, the capture nodeids are used.
        options: Output directory and manifest stamps.

    Returns:
        The emit summary (vector count, bundle paths, exclusion counts).

    Raises:
        RecordingAbortError: On duplicate final vector ids, redaction hits,
            or schema self-validation failures.
    """
    exclusions = _ExclusionLog()
    pending: list[_PendingVector] = []
    for capture in captures:
        pending.extend(_classify_capture(capture, exclusions))

    nodeids = list(collected_nodeids) or [capture.nodeid for capture in captures]
    slug_map = build_slug_map(nodeids)

    per_nodeid: Counter[str] = Counter(vector.nodeid for vector in pending)
    ordinal: Counter[str] = Counter()
    for vector in pending:
        slug = (
            slug_map.get(vector.nodeid)
            or build_slug_map([vector.nodeid])[vector.nodeid]
        )
        # The api segment is lowercased for the id ONLY (schema id charset
        # is ^[a-z0-9_./-]+$; ``types.CohortDefinition.to_dict`` carries
        # class-name case) — ``call.api`` itself stays verbatim.
        vector_id = f"{vector.capability}/{vector.api.lower()}/{slug}"
        if per_nodeid[vector.nodeid] > 1:
            ordinal[vector.nodeid] += 1
            vector_id = f"{vector_id}-{ordinal[vector.nodeid]}"
        vector.body["id"] = vector_id

    seen_ids: set[str] = set()
    for vector in pending:
        vector_id = str(vector.body["id"])
        if vector_id in seen_ids:
            raise RecordingAbortError(
                f"duplicate final vector id {vector_id!r} — emit-time hard "
                "error (design D3)"
            )
        seen_ids.add(vector_id)

    from jsonschema.validators import Draft202012Validator

    with _SCHEMA_PATH.open(encoding="utf-8") as handle:
        validator = Draft202012Validator(json.load(handle))

    sessions_by_id: dict[str, set[str]] = {}
    for capture in captures:
        allowed = _session_allowed_strings(
            session
            for call in capture.entry_calls
            for session in (call.session, call.workspace_session)
        )
        allowed |= _fallback_auth_strings(capture)
        sessions_by_id[capture.nodeid] = allowed
    for vector in pending:
        _validate_vector(vector.body, validator)
        _redaction_scan(vector.body, sessions_by_id.get(vector.nodeid, set()))

    bundles: dict[tuple[str, str], list[_PendingVector]] = {}
    for vector in pending:
        source_file = vector.nodeid.partition("::")[0]
        bundles.setdefault((vector.capability, source_file), []).append(vector)

    out_dir = options.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    bundle_paths: list[Path] = []
    for (capability, source_file), members in sorted(bundles.items()):
        members.sort(key=lambda vector: str(vector.body["id"]))
        bundle_dir = out_dir / capability
        bundle_dir.mkdir(parents=True, exist_ok=True)
        bundle_path = bundle_dir / f"{Path(source_file).stem}.jsonl"
        header = {
            "$bundle": {
                "source_commit": options.source_commit,
                "source_file": source_file,
                "count": len(members),
            }
        }
        lines = [canonical_json(header)]
        lines.extend(canonical_json(vector.body) for vector in members)
        bundle_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        bundle_paths.append(bundle_path)

    api_capability: dict[str, str] = {}
    for vector in sorted(pending, key=lambda vector: str(vector.body["id"])):
        apis = [vector.api] + [
            str(setup["api"]) for setup in vector.body["call"].get("setup", [])
        ]
        for api in apis:
            api_capability.setdefault(api, vector.capability)
    api_index = {
        api: _api_index_entry(api, capability)
        for api, capability in sorted(api_capability.items())
    }
    (out_dir / "api-index.json").write_text(
        canonical_json(api_index) + "\n", encoding="utf-8"
    )

    counts_by_kind = Counter(vector.kind for vector in pending)
    counts_by_capability = Counter(vector.capability for vector in pending)
    with_setup = sum(1 for vector in pending if vector.body["call"].get("setup"))
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "source_commit": options.source_commit,
        "extraction_date": options.extraction_date,
        "record_epoch": RECORD_EPOCH,
        "counts": {
            "total": len(pending),
            "with_setup": with_setup,
            "by_kind": dict(sorted(counts_by_kind.items())),
            "by_capability": dict(sorted(counts_by_capability.items())),
        },
        "exclusions": dict(sorted(exclusions.counts.items())),
        "exclusion_details": {
            category: sorted(set(nodeids))
            for category, nodeids in sorted(exclusions.details.items())
        },
        "tool_versions": _tool_versions(),
    }
    (out_dir / "manifest.json").write_text(
        canonical_json(manifest) + "\n", encoding="utf-8"
    )

    return EmitSummary(
        total_vectors=len(pending),
        bundle_paths=bundle_paths,
        exclusions=dict(exclusions.counts),
    )


__all__ = [
    "SCHEMA_VERSION",
    "EmitOptions",
    "EmitSummary",
    "build_slug_map",
    "canonical_json",
    "emit_corpus",
    "interaction_sort_key",
    "slug_for_nodeid",
    "sort_unordered_groups",
]
