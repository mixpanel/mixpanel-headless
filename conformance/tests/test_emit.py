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
        ("A" * 45, "entropy-shape"),
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
