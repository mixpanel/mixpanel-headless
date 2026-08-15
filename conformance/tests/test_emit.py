"""Unit tests for the emit pipeline (design D3/D5, PR-2).

Covers the PR-2 mandated cases: the D5.4 redaction abort (loud failure,
never a silent scrub), emit determinism (two passes over the same captures
produce byte-identical trees), plus the D3 slug/collision/ordinal rules and
the D2 emit-side unordered-group sort.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from conformance.record.capture import (
    EntryCallCapture,
    RecordedInteraction,
    RecordedRequest,
    RecordedResponse,
    RecordingAbortError,
)
from conformance.record.capture import (
    # Aliased so pytest does not try to collect the dataclass as a test class.
    TestCapture as CapturedTest,
)
from conformance.record.emit import (
    EmitOptions,
    build_slug_map,
    emit_corpus,
    sort_unordered_groups,
)
from conformance.record.registry import REGISTRY_BY_API
from mixpanel_headless._internal.auth.account import ServiceAccount
from mixpanel_headless._internal.auth.session import Project, Session


def _make_session() -> Session:
    """Build the fake service-account session used by emit fixtures.

    Returns:
        A ``Session`` bound to ``test_user``/``test_secret`` on project
        12345 (the conftest reference shape, design D5.1).
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


def _builder_capture(
    nodeid: str, *, input_encoded: dict[str, object] | None = None
) -> CapturedTest:
    """Build a one-call builder test capture.

    Args:
        nodeid: The owning pytest nodeid.
        input_encoded: Optional ``call.input`` override.

    Returns:
        A capture holding one returned ``workspace.build_params`` call.
    """
    call = EntryCallCapture(
        index=0,
        entry=REGISTRY_BY_API["workspace.build_params"],
        input_encoded=input_encoded or {"events": ["Login"]},
        session=None,
        workspace_session=None,
        result_encoded={"sections": {}},
        returned=True,
    )
    return CapturedTest(nodeid=nodeid, entry_calls=[call])


def _wire_capture(nodeid: str) -> CapturedTest:
    """Build a one-call wire test capture with a single interaction.

    Args:
        nodeid: The owning pytest nodeid.

    Returns:
        A capture holding one ``api_client.list_annotations`` call with
        an attributed 200-JSON interaction.
    """
    session = _make_session()
    call = EntryCallCapture(
        index=0,
        entry=REGISTRY_BY_API["api_client.list_annotations"],
        input_encoded={},
        session=session,
        workspace_session=None,
        result_encoded=[{"id": 1}],
        returned=True,
    )
    interaction = RecordedInteraction(
        seq=0,
        request=RecordedRequest(
            method="GET",
            scheme_host="https://mixpanel.com",
            path="/api/app/projects/12345/annotations/",
            params={},
            headers={
                "authorization": "Basic dGVzdF91c2VyOnRlc3Rfc2VjcmV0",
                "host": "mixpanel.com",
                "accept": "*/*",
            },
            content=b"",
        ),
        response=RecordedResponse(
            status=200,
            headers={"content-type": "application/json"},
            body_bytes=b'{"status": "ok", "results": [{"id": 1}]}',
        ),
        span_index=0,
        is_async=False,
    )
    return CapturedTest(nodeid=nodeid, entry_calls=[call], interactions=[interaction])


def _options(out_dir: Path) -> EmitOptions:
    """Build emit options with fixed injected stamps.

    Args:
        out_dir: Output directory for the pass.

    Returns:
        The configured :class:`EmitOptions`.
    """
    return EmitOptions(
        out_dir=out_dir,
        extraction_date="2026-08-14",
        source_commit="52696743b913a0c4c152deb48af987ae412b5aee",
    )


def _tree_bytes(root: Path) -> dict[str, bytes]:
    """Read every file under a directory into a relpath -> bytes map.

    Args:
        root: The directory to walk.

    Returns:
        Mapping of POSIX relative path to file content.
    """
    return {
        str(path.relative_to(root).as_posix()): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


# ---------------------------------------------------------------------------
# Redaction abort (design D5.4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "rule"),
    [
        ("aB3dE5gH7jK9mN1pQ2sT4vW6yZ8xC0rF-_bD3fG5h", "entropy-shape"),
        ("sk-live-abc123", "sk-prefix"),
        ("/Users/someone/secret.txt", "home-path"),
        ("Bearer not-the-session-token", "foreign-bearer"),
    ],
)
def test_redaction_denylist_aborts_extraction(
    tmp_path: Path, value: str, rule: str
) -> None:
    """Every D5.4 denylist rule fails extraction loudly, never scrubbing.

    Args:
        tmp_path: Output directory for the aborted pass.
        value: The offending string planted in ``call.input``.
        rule: The rule name expected in the abort message.

    Raises:
        AssertionError: If emission succeeds or names the wrong rule.
    """
    capture = _builder_capture(
        "tests/unit/test_fake.py::test_redaction",
        input_encoded={"events": [value]},
    )
    with pytest.raises(RecordingAbortError, match=rule):
        emit_corpus([capture], [capture.nodeid], _options(tmp_path))


def test_session_derived_credentials_pass_redaction(tmp_path: Path) -> None:
    """Credentials derivable from the bound session never trip the screen.

    Design D5.4: the rules are session-relative — the vector's own auth
    pattern (a >=40-char base64-bearing string) must not abort.

    Args:
        tmp_path: Output directory for the pass.

    Raises:
        AssertionError: If a session-derived value aborts emission.
    """
    summary = emit_corpus(
        [_wire_capture("tests/unit/test_fake.py::test_ok")],
        ["tests/unit/test_fake.py::test_ok"],
        _options(tmp_path),
    )
    assert summary.total_vectors == 1


def test_low_diversity_entropy_shape_passes(tmp_path: Path) -> None:
    """Low-diversity long strings never trip the entropy screen (D5.4).

    A 4 KiB ``"x" * 4096`` truncation fixture matches the base64 SHAPE but
    carries no secret entropy; the distinct-character floor keeps such
    wire data recordable (PR-5 refinement).

    Args:
        tmp_path: Output directory for the pass.

    Raises:
        AssertionError: If a low-diversity string aborts emission.
    """
    capture = _builder_capture(
        "tests/unit/test_fake.py::test_low_diversity",
        input_encoded={"events": ["x" * 4096]},
    )
    summary = emit_corpus([capture], [capture.nodeid], _options(tmp_path))
    assert summary.total_vectors == 1


def _resolver_session() -> Session:
    """Build an env-backed oauth_token session with no inline bearer.

    Returns:
        A ``Session`` whose auth value is NOT derivable from the session
        object (resolver-backed — design D5.2 acceptance path 2).
    """
    from mixpanel_headless._internal.auth.account import OAuthTokenAccount

    return Session(
        account=OAuthTokenAccount(name="ci", region="us", token_env="MP_OAUTH_TOKEN"),
        project=Project(id="12345"),
    )


def _resolver_wire_capture(nodeid: str, bearers: list[str]) -> CapturedTest:
    """Build a wire capture whose interactions carry resolver bearers.

    Args:
        nodeid: The owning pytest nodeid.
        bearers: Observed ``authorization`` bearer token per interaction.

    Returns:
        A capture with one measured call and ``len(bearers)`` attributed
        interactions.
    """
    session = _resolver_session()
    call = EntryCallCapture(
        index=0,
        entry=REGISTRY_BY_API["api_client.list_annotations"],
        input_encoded={},
        session=session,
        workspace_session=None,
        result_encoded=[{"id": 1}],
        returned=True,
    )
    interactions = [
        RecordedInteraction(
            seq=seq,
            request=RecordedRequest(
                method="GET",
                scheme_host="https://mixpanel.com",
                path="/api/app/projects/12345/annotations/",
                params={},
                headers={"authorization": f"Bearer {bearer}"},
                content=b"",
            ),
            response=RecordedResponse(
                status=200,
                headers={"content-type": "application/json"},
                body_bytes=b'{"status": "ok", "results": [{"id": 1}]}',
            ),
            span_index=0,
            is_async=False,
        )
        for seq, bearer in enumerate(bearers)
    ]
    return CapturedTest(nodeid=nodeid, entry_calls=[call], interactions=interactions)


def test_resolver_backed_bearer_adopted_into_session(tmp_path: Path) -> None:
    """A unique observed bearer becomes the encoded session token (D5.2).

    Args:
        tmp_path: Output directory for the pass.

    Raises:
        AssertionError: If the token is not adopted or the auth pattern
            does not match the observed value.
    """
    import json as _json

    nodeid = "tests/unit/test_fake.py::test_resolver_adopted"
    summary = emit_corpus(
        [_resolver_wire_capture(nodeid, ["resolved-tok"])],
        [nodeid],
        _options(tmp_path),
    )
    assert summary.total_vectors == 1
    bundle = next(tmp_path.rglob("test_fake.jsonl"))
    vector = _json.loads(bundle.read_text().splitlines()[1])
    assert vector["call"]["session"]["token"] == "resolved-tok"
    pattern = vector["expect"]["interactions"][0]["request"]["headers_contain"][
        "authorization"
    ]["pattern"]
    assert "resolved\\-tok" in pattern


def test_rotating_bearer_excluded_as_unserializable(tmp_path: Path) -> None:
    """Distinct observed bearers exclude the vector (rotating resolver).

    The rotating ``TokenResolver`` stub is an unserializable dependency —
    a single session token cannot reproduce per-request rotation (D5.2).

    Args:
        tmp_path: Output directory for the pass.

    Raises:
        AssertionError: If a vector is emitted or the wrong category is
            counted.
    """
    nodeid = "tests/unit/test_fake.py::test_resolver_rotating"
    summary = emit_corpus(
        [_resolver_wire_capture(nodeid, ["tok-1", "tok-2"])],
        [nodeid],
        _options(tmp_path),
    )
    assert summary.total_vectors == 0
    assert summary.exclusions.get("unserializable_input") == 1


# ---------------------------------------------------------------------------
# Emit determinism (design D3)
# ---------------------------------------------------------------------------


def test_emit_is_byte_deterministic(tmp_path: Path) -> None:
    """Two emit passes over the same captures are byte-identical (D3/D8).

    Also locks the D3 shape rules along the way: bundle header line,
    id-sorted vector lines, ``-N`` ordinals for same-nodeid multi-emission,
    manifest + api-index sidecars present.

    Raises:
        AssertionError: If any emitted file differs between the passes or
            a shape rule is violated.
    """
    builder = _builder_capture("tests/unit/test_fake.py::test_builder")
    builder.entry_calls.append(
        EntryCallCapture(
            index=1,
            entry=REGISTRY_BY_API["workspace.build_params"],
            input_encoded={"events": ["Signup"]},
            session=None,
            workspace_session=None,
            result_encoded={"sections": {"show": []}},
            returned=True,
        )
    )
    captures = [builder, _wire_capture("tests/unit/test_fake.py::test_wire")]
    nodeids = [capture.nodeid for capture in captures]

    first = emit_corpus(captures, nodeids, _options(tmp_path / "one"))
    second = emit_corpus(captures, nodeids, _options(tmp_path / "two"))

    tree_one = _tree_bytes(tmp_path / "one")
    tree_two = _tree_bytes(tmp_path / "two")
    assert tree_one == tree_two
    assert first.total_vectors == second.total_vectors == 3
    assert {"manifest.json", "api-index.json"} <= set(tree_one)

    bundle = (tmp_path / "one" / "bookmarks" / "test_fake.jsonl").read_text(
        encoding="utf-8"
    )
    lines = bundle.splitlines()
    assert '"$bundle"' in lines[0]
    ids = [line.split('"id":"', 1)[1].split('"', 1)[0] for line in lines[1:]]
    assert ids == sorted(ids)
    # Same-nodeid multi-emission gets -N ordinals in call order (D3).
    assert any(vector_id.endswith("-1") for vector_id in ids)
    assert any(vector_id.endswith("-2") for vector_id in ids)


def test_duplicate_final_ids_are_a_hard_error(tmp_path: Path) -> None:
    """Duplicate final vector ids abort emission (design D3 hard error).

    Exercises the backstop via the fallback slug path: two case-colliding
    nodeids that were NOT in the collected list bypass the global collision
    pass, collapse to one slug, and must abort rather than silently
    overwrite each other.

    Raises:
        AssertionError: If emission does not raise.
    """
    captures = [
        _builder_capture("tests/unit/test_fake.py::test_dup[A]"),
        _builder_capture("tests/unit/test_fake.py::test_dup[a]"),
    ]
    with pytest.raises(RecordingAbortError, match="duplicate final vector id"):
        emit_corpus(
            captures, ["tests/unit/test_fake.py::test_other"], _options(tmp_path)
        )


# ---------------------------------------------------------------------------
# Slug collision pass + unordered-group sort (design D3/D2)
# ---------------------------------------------------------------------------


def test_slug_collision_pass_suffixes_both_colliders() -> None:
    """Case-only nodeid clashes get ``-h<sha1-8>`` suffixes on BOTH sides.

    Raises:
        AssertionError: If the collision pass leaves a clash or suffixes
            only one collider.
    """
    a = "tests/unit/test_x.py::test_param[A]"
    b = "tests/unit/test_x.py::test_param[a]"
    slug_map = build_slug_map([a, b])
    assert slug_map[a] != slug_map[b]
    assert "-h" in slug_map[a]
    assert "-h" in slug_map[b]
    unique = "tests/unit/test_x.py::test_other"
    assert "-h" not in build_slug_map([a, b, unique])[unique]


def test_unordered_group_members_sorted_by_canonical_key() -> None:
    """Group members are emit-sorted by ``(method, path, params)`` (D2).

    Interactions outside the group keep their positions; members reorder
    among the group's own positions.

    Raises:
        AssertionError: If sorting moves non-members or leaves members
            unsorted.
    """

    def interaction(path: str, group: int | None) -> dict[str, object]:
        """Build a minimal serialized interaction.

        Args:
            path: Request path (the sort discriminator).
            group: Optional unordered group id.

        Returns:
            The serialized interaction object.
        """
        body: dict[str, object] = {
            "request": {"method": "GET", "path": path, "params": {}},
            "response": {"status": 200},
        }
        if group is not None:
            body["unordered_group"] = group
        return body

    ordered = interaction("/first", None)
    result = sort_unordered_groups(
        [ordered, interaction("/z", 1), interaction("/a", 1)]
    )
    assert result[0] is ordered
    assert result[1]["request"]["path"] == "/a"
    assert result[2]["request"]["path"] == "/z"


def test_transport_error_message_emitted() -> None:
    """``_emit_response`` carries the handler exception message (PR-6).

    Raises:
        AssertionError: If the message is dropped or fabricated.
    """
    from conformance.record.emit import _emit_response

    with_message = RecordedResponse(
        transport_error="ConnectError",
        transport_error_message="DNS lookup failed",
    )
    assert _emit_response(with_message) == {
        "transport_error": "ConnectError",
        "message": "DNS lookup failed",
    }
    without_message = RecordedResponse(transport_error="ReadTimeout")
    assert _emit_response(without_message) == {"transport_error": "ReadTimeout"}


def test_session_custom_headers_encoded() -> None:
    """``_encode_session`` records resolution-time custom headers (PR-6).

    Raises:
        AssertionError: If headers are dropped or fabricated.
    """
    from conformance.record.emit import _encode_session

    plain = _make_session()
    assert "headers" not in _encode_session(plain)
    with_headers = Session(
        account=plain.account,
        project=plain.project,
        headers={"X-Tenant": "acme"},
    )
    assert _encode_session(with_headers)["headers"] == {"X-Tenant": "acme"}


def test_callback_calls_emitted_on_wire_vector(tmp_path: Path) -> None:
    """Non-empty callback logs become ``expect.callback_calls`` (D4.4).

    Raises:
        AssertionError: If the log is dropped or an empty log is emitted.
    """
    import json

    session = _make_session()
    entry = REGISTRY_BY_API["api_client.export_events"]
    call = EntryCallCapture(
        index=0,
        entry=entry,
        input_encoded={
            "from_date": "2024-01-01",
            "to_date": "2024-01-02",
            "on_batch": {"$type": "callback", "name": "on_batch"},
        },
        session=session,
        workspace_session=None,
        iterator_items=[{"event": "Login"}],
        iterator_finished=True,
        returned=True,
    )
    call.callback_calls = {"on_batch": [[[{"event": "Login"}]]], "unused": []}
    capture = CapturedTest(nodeid="tests/unit/test_fake.py::test_cb")
    capture.entry_calls.append(call)
    capture.interactions.append(
        RecordedInteraction(
            seq=0,
            request=RecordedRequest(
                method="GET",
                scheme_host="https://data.mixpanel.com",
                path="/api/2.0/export",
                params={"from_date": "2024-01-01", "to_date": "2024-01-02"},
                headers={
                    "authorization": "Basic dGVzdF91c2VyOnRlc3Rfc2VjcmV0",
                },
                content=b"",
            ),
            response=RecordedResponse(
                status=200,
                headers={"content-type": "application/json"},
                body_bytes=b'{"event": "Login"}',
            ),
            span_index=0,
            is_async=False,
        )
    )
    out_dir = tmp_path / "vectors"
    emit_corpus(
        [capture],
        [capture.nodeid],
        EmitOptions(
            out_dir=out_dir,
            extraction_date="2026-08-14",
            source_commit="0" * 40,
        ),
    )
    bundles = sorted(out_dir.rglob("test_fake.jsonl"))
    assert len(bundles) == 1
    lines = [json.loads(line) for line in bundles[0].read_text().splitlines()]
    vectors = [line for line in lines if "$bundle" not in line]
    assert len(vectors) == 1
    assert vectors[0]["expect"]["callback_calls"] == {
        "on_batch": [[[{"event": "Login"}]]]
    }


# ---------------------------------------------------------------------------
# Coded-guard error_only entries (coding-pass design §5 item 2, RR-7 fix c)
# ---------------------------------------------------------------------------


def test_error_only_success_calls_skipped_silently(tmp_path: Path) -> None:
    """Successful error_only constructions emit nothing and exclude nothing.

    A success-path construction on an ``error_only`` entry must be a
    SILENT skip — not an ``uncoded_raise`` (or any other) exclusion —
    so guard-entry registration cannot inflate the exclusion ledger
    (RR-7 fix c).

    Raises:
        AssertionError: If a vector is emitted or an exclusion is counted.
    """
    import json as jsonlib

    success = EntryCallCapture(
        index=0,
        entry=REGISTRY_BY_API["types.TimeComparison"],
        input_encoded={"type": "relative", "unit": "month"},
        session=None,
        workspace_session=None,
        result_encoded=None,
        returned=True,
    )
    guard_capture = CapturedTest(
        nodeid="tests/unit/test_fake.py::test_guard_success",
        entry_calls=[success],
    )
    builder = _builder_capture("tests/unit/test_fake.py::test_builder")
    captures = [guard_capture, builder]
    nodeids = [capture.nodeid for capture in captures]

    summary = emit_corpus(captures, nodeids, _options(tmp_path))

    assert summary.total_vectors == 1  # only the normal builder vector
    assert summary.exclusions.get("uncoded_raise", 0) == 0
    manifest = jsonlib.loads((tmp_path / "manifest.json").read_text("utf-8"))
    assert manifest["exclusions"].get("uncoded_raise", 0) == 0


def test_error_only_guard_error_emits_builder_error_vector(tmp_path: Path) -> None:
    """A coded guard raise on an error_only entry emits a builder vector.

    The vector carries ``expect.error`` with the domain class name and
    registry code (design §5 — R5.2/R5.3 contract).

    Raises:
        AssertionError: If the error vector is missing or mis-shaped.
    """
    from mixpanel_headless.exceptions import ParamValidationError

    failing = EntryCallCapture(
        index=0,
        entry=REGISTRY_BY_API["types.TimeComparison"],
        input_encoded={"type": "bogus"},
        session=None,
        workspace_session=None,
        error=ParamValidationError(
            "TimeComparison type must be one of "
            "['absolute-end', 'absolute-start', 'relative'], got 'bogus'",
            code="TC0_INVALID_TYPE",
        ),
    )
    guard_capture = CapturedTest(
        nodeid="tests/unit/test_fake.py::test_guard_error",
        entry_calls=[failing],
    )
    summary = emit_corpus([guard_capture], [guard_capture.nodeid], _options(tmp_path))

    assert summary.total_vectors == 1
    bundles = list(tmp_path.rglob("*.jsonl"))
    assert len(bundles) == 1
    lines = bundles[0].read_text("utf-8").splitlines()
    vector = next(line for line in lines if '"types.TimeComparison"' in line)
    assert (
        '"kind":"builder"' in vector.replace(" ", "") or '"kind": "builder"' in vector
    )
    assert "ParamValidationError" in vector
    assert "TC0_INVALID_TYPE" in vector
