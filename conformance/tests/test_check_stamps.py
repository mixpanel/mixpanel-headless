"""Unit tests for the corpus stamp-provenance guard (``check_stamps``).

The guard has two rules. Rule 1 (reachability): every ``source_commit`` /
``generated_from`` stamp must be a 40-hex SHA reachable from main, with
authored bundles exempt only through the explicit legacy allowlist. Rule 2
(stamp moves with content): when in-scope corpus content changes against
the merge-base, ``manifest.source_commit`` must change too.

Both rules are tested from fixtures with an injected reachability
predicate, so no git history is needed. The PR #223 state (new vectors and
regenerated contract artifacts under the previous, unreachable stamps) is
reproduced as a fixture and must fail BOTH rules. A small temp-git-repo
suite covers the real git layer and the CLI exit codes.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from conformance.record.check_stamps import (
    GENERATED_CONTRACT_ARTIFACTS,
    LEGACY_AUTHORED_STAMPS,
    StampFinding,
    check_reachability,
    check_stamp_moved,
    content_moved,
    git_is_ancestor,
    main,
    strip_stamps,
)

#: The squash of PR #223 on main — the repaired stamp.
MAIN_SHA = "c9991d1eed03fec1830b6e460091724b9263b8aa"
#: The pre-squash PR #215 branch tip the corpus carried before the repair.
OLD_SHA = "390c6e7fe79485d3844c75af78fb5fe90142af68"
#: The pre-implementation PR #223 branch commit the contract carried.
OLD_CONTRACT_SHA = "4504f3e3d25749768b053ccfd46a07302d3fc5c4"
#: Legacy stamp shared by most hand-authored bundles.
LEGACY_SHA = "52696743b913a0c4c152deb48af987ae412b5aee"


def _reachable(*shas: str) -> Callable[[str], bool]:
    """Build a reachability predicate from an explicit set of SHAs.

    Args:
        *shas: The SHAs to treat as ancestors of main.

    Returns:
        A predicate returning True only for the given SHAs.
    """
    allowed = frozenset(shas)
    return lambda sha: sha in allowed


def _vector(vector_id: str, output: str = "ok") -> dict[str, object]:
    """Build a minimal builder-kind vector object.

    Args:
        vector_id: The vector ``id`` field.
        output: The ``expect.output`` payload (varied to force byte drift).

    Returns:
        A minimal vector dict.
    """
    return {
        "call": {"api": "expressions.normalize_on_expression", "input": {"on": "x"}},
        "capability": "segmentation",
        "expect": {"output": output},
        "id": vector_id,
        "kind": "builder",
        "origin": "extracted",
        "schema_version": "1.0",
    }


def _bundle_bytes(
    stamp: str | None, vectors: list[dict[str, object]], source_file: str = "t.py"
) -> bytes:
    """Serialize a JSONL bundle with a ``$bundle`` header line.

    Args:
        stamp: ``$bundle.source_commit`` value; None omits the key (the
            storybook-harvest header shape).
        vectors: Vector objects, one per line.
        source_file: Header ``source_file`` value.

    Returns:
        The bundle bytes (trailing newline included).
    """
    header: dict[str, object] = {"count": len(vectors), "source_file": source_file}
    if stamp is not None:
        header["source_commit"] = stamp
    lines = [json.dumps({"$bundle": header}, sort_keys=True, separators=(",", ":"))]
    lines.extend(json.dumps(v, sort_keys=True, separators=(",", ":")) for v in vectors)
    return ("\n".join(lines) + "\n").encode("utf-8")


def _manifest_bytes(stamp: str, total: int = 3, date: str = "2026-09-03") -> bytes:
    """Serialize a minimal manifest.

    Args:
        stamp: ``source_commit`` value.
        total: ``counts.total`` value (varied to force content drift).
        date: ``extraction_date`` value.

    Returns:
        Single-line canonical manifest bytes.
    """
    body = {
        "counts": {"total": total},
        "extraction_date": date,
        "schema_version": "1.0",
        "source_commit": stamp,
        "tool_versions": {"python": "3.14.6"},
    }
    return (json.dumps(body, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write(path: Path, data: bytes) -> None:
    """Write bytes, creating parent directories.

    Args:
        path: Destination path.
        data: Bytes to write.

    Returns:
        None.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _make_tree(
    root: Path, stamp: str, contract_stamp: str | None = None
) -> tuple[Path, Path]:
    """Create a corpus + contract pair under ``root``.

    The corpus holds a manifest, an api-index, two extracted bundles, one
    allowlisted legacy authored bundle, one storybook authored bundle with
    no stamp, and an ``enums`` sidecar. The contract directory holds the
    four generated artifacts plus the hand-maintained overrides file.

    Args:
        root: Directory to populate.
        stamp: ``source_commit`` for the manifest and extracted bundles.
        contract_stamp: ``generated_from`` for the artifacts (defaults to
            ``stamp``).

    Returns:
        ``(vectors_dir, contract_dir)``.
    """
    vectors = root / "vectors"
    contract = root / "contract"
    _write(vectors / "manifest.json", _manifest_bytes(stamp))
    _write(vectors / "api-index.json", b'{"expressions.normalize_on_expression":{}}\n')
    _write(
        vectors / "segmentation" / "test_expressions.jsonl",
        _bundle_bytes(stamp, [_vector("seg/a"), _vector("seg/b")]),
    )
    _write(
        vectors / "funnels" / "test_funnels.jsonl",
        _bundle_bytes(stamp, [_vector("fun/a")]),
    )
    _write(
        vectors / "authored" / "compat" / "wirestub.jsonl",
        _bundle_bytes(LEGACY_AUTHORED_STAMPS["authored/compat/wirestub.jsonl"], []),
    )
    _write(
        vectors / "authored" / "parse" / "storybook" / "boards.jsonl",
        _bundle_bytes(None, []),
    )
    _write(vectors / "enums" / "bookmark_enums.json", b"{}\n")
    generated_from = stamp if contract_stamp is None else contract_stamp
    for name in GENERATED_CONTRACT_ARTIFACTS:
        _write(
            contract / name,
            json.dumps({"generated_from": generated_from, "x": 1}).encode() + b"\n",
        )
    _write(contract / "coverage_overrides.json", b'{"models":{}}\n')
    return vectors, contract


def _rules(findings: list[StampFinding]) -> set[str]:
    """Collect the distinct rule labels in a findings list.

    Args:
        findings: Findings under test.

    Returns:
        The set of ``rule`` values.
    """
    return {f.rule for f in findings}


def _paths(findings: list[StampFinding]) -> set[str]:
    """Collect the distinct paths in a findings list.

    Args:
        findings: Findings under test.

    Returns:
        The set of ``path`` values.
    """
    return {f.path for f in findings}


class TestReachability:
    """Rule 1: every stamp is a 40-hex SHA reachable from main."""

    def test_repaired_tree_is_clean(self, tmp_path: Path) -> None:
        """A corpus stamped with a main-reachable SHA has no findings.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        assert check_reachability(vectors, contract, _reachable(MAIN_SHA)) == []

    def test_pr223_state_fails_on_every_stamp(self, tmp_path: Path) -> None:
        """The PR #223 state (old unreachable stamps) fails rule 1 everywhere.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, OLD_SHA, OLD_CONTRACT_SHA)
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert _rules(findings) == {"reachability"}
        assert _paths(findings) == {
            "manifest.json",
            "segmentation/test_expressions.jsonl",
            "funnels/test_funnels.jsonl",
            *(f"contract/{name}" for name in GENERATED_CONTRACT_ARTIFACTS),
        }
        assert all("not reachable from main" in f.detail for f in findings)

    def test_short_sha_is_rejected(self, tmp_path: Path) -> None:
        """An abbreviated SHA is not a durable stamp even if it resolves.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        _write(vectors / "manifest.json", _manifest_bytes("c9991d1"))
        findings = check_reachability(vectors, contract, lambda _sha: True)
        assert any(
            f.path == "manifest.json" and "not a 40-hex SHA" in f.detail
            for f in findings
        )

    def test_bundle_stamp_must_equal_manifest_stamp(self, tmp_path: Path) -> None:
        """A reachable bundle stamp that differs from the manifest is a hand edit.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        other = "a" * 40
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        _write(
            vectors / "funnels" / "test_funnels.jsonl",
            _bundle_bytes(other, [_vector("fun/a")]),
        )
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA, other))
        assert [f.path for f in findings] == ["funnels/test_funnels.jsonl"]
        assert "!= manifest source_commit" in findings[0].detail

    def test_missing_manifest_fails(self, tmp_path: Path) -> None:
        """A corpus without a manifest cannot be provenance-checked.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        (vectors / "manifest.json").unlink()
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert findings == [
            StampFinding("reachability", "manifest.json", "manifest missing")
        ]

    def test_malformed_bundle_header_fails(self, tmp_path: Path) -> None:
        """A bundle whose first line is not a ``$bundle`` header is reported.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        _write(vectors / "funnels" / "test_funnels.jsonl", b'{"id":"x"}\n')
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert [f.detail for f in findings] == ["first line lacks $bundle header"]

    def test_legacy_authored_stamps_are_allowlisted(self, tmp_path: Path) -> None:
        """Allowlisted authored bundles pass with their legacy or absent stamp.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        assert not _reachable(MAIN_SHA)(LEGACY_SHA)
        assert check_reachability(vectors, contract, _reachable(MAIN_SHA)) == []

    def test_new_authored_bundle_needs_reachable_stamp(self, tmp_path: Path) -> None:
        """An authored bundle outside the allowlist must carry a reachable SHA.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        new_rel = "authored/replays/new-seed.jsonl"
        _write(vectors / new_rel, _bundle_bytes(LEGACY_SHA, []))
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert [f.path for f in findings] == [new_rel]
        _write(vectors / new_rel, _bundle_bytes(None, []))
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert [f.path for f in findings] == [new_rel]
        _write(vectors / new_rel, _bundle_bytes(MAIN_SHA, []))
        assert check_reachability(vectors, contract, _reachable(MAIN_SHA)) == []

    def test_allowlisted_authored_bundle_with_new_stamp_is_checked(
        self, tmp_path: Path
    ) -> None:
        """Changing an allowlisted authored stamp drops the exemption.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        rel = "authored/compat/wirestub.jsonl"
        _write(vectors / rel, _bundle_bytes("b" * 40, []))
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert [f.path for f in findings] == [rel]

    def test_generated_artifact_without_stamp_fails(self, tmp_path: Path) -> None:
        """A generated contract artifact must carry ``generated_from``.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        _write(contract / "tag-universe.json", b'{"tags":[]}\n')
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert findings == [
            StampFinding(
                "reachability", "contract/tag-universe.json", "generated_from missing"
            )
        ]

    def test_missing_generated_artifact_fails(self, tmp_path: Path) -> None:
        """A missing generated contract artifact is reported by name.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        (contract / "model-coverage.json").unlink()
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert findings == [
            StampFinding(
                "reachability",
                "contract/model-coverage.json",
                "generated artifact missing",
            )
        ]

    def test_input_json_without_stamp_is_ignored(self, tmp_path: Path) -> None:
        """Hand-maintained contract inputs without the key are not checked.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        _write(contract / "notes.json", b'{"free":"form"}\n')
        assert check_reachability(vectors, contract, _reachable(MAIN_SHA)) == []

    def test_input_json_with_unreachable_stamp_is_checked(self, tmp_path: Path) -> None:
        """Any contract JSON that carries ``generated_from`` is held to rule 1.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        _write(
            contract / "extra.json", json.dumps({"generated_from": OLD_SHA}).encode()
        )
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert [f.path for f in findings] == ["contract/extra.json"]

    def test_non_object_contract_json_fails(self, tmp_path: Path) -> None:
        """A contract JSON file that is not an object is reported.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        vectors, contract = _make_tree(tmp_path, MAIN_SHA)
        _write(contract / "error-codes.json", b"[]\n")
        findings = check_reachability(vectors, contract, _reachable(MAIN_SHA))
        assert [f.detail for f in findings] == ["not a JSON object"]


class TestStripStamps:
    """``strip_stamps`` removes exactly the stamp fields per file shape."""

    def test_manifest_drops_both_stamps(self) -> None:
        """Manifest stamps differing only in date/commit strip to equal bytes."""
        a = strip_stamps("manifest.json", _manifest_bytes(OLD_SHA, date="2026-08-21"))
        b = strip_stamps("manifest.json", _manifest_bytes(MAIN_SHA, date="2026-09-03"))
        assert a == b
        assert a is not None and b"source_commit" not in a

    def test_manifest_content_change_survives(self) -> None:
        """A manifest count change is not masked by stripping."""
        a = strip_stamps("manifest.json", _manifest_bytes(MAIN_SHA, total=3))
        b = strip_stamps("manifest.json", _manifest_bytes(MAIN_SHA, total=4))
        assert a != b

    def test_bundle_drops_header_stamp_only(self) -> None:
        """Bundle headers differing only in ``source_commit`` strip equal."""
        vectors = [_vector("seg/a")]
        a = strip_stamps("seg/x.jsonl", _bundle_bytes(OLD_SHA, vectors))
        b = strip_stamps("seg/x.jsonl", _bundle_bytes(MAIN_SHA, vectors))
        assert a == b
        c = strip_stamps(
            "seg/x.jsonl", _bundle_bytes(MAIN_SHA, [_vector("seg/a", "no")])
        )
        assert a != c

    def test_other_files_and_malformed_inputs_pass_through(self) -> None:
        """Non-stamped files, malformed JSON, and None are returned unchanged."""
        assert strip_stamps("api-index.json", b"{}") == b"{}"
        assert strip_stamps("manifest.json", b"not json") == b"not json"
        assert strip_stamps("seg/x.jsonl", b"not json\n{}") == b"not json\n{}"
        assert strip_stamps("seg/x.jsonl", b'{"id":"x"}\n') == b'{"id":"x"}\n'
        assert strip_stamps("manifest.json", None) is None


class TestStampMoved:
    """Rule 2: content that moves must move ``manifest.source_commit``."""

    @staticmethod
    def _base() -> dict[str, bytes | None]:
        """Build the merge-base file map (the pre-PR #223 corpus shape).

        Returns:
            Corpus-relative path → bytes.
        """
        return {
            "manifest.json": _manifest_bytes(OLD_SHA, total=3, date="2026-08-21"),
            "api-index.json": b'{"a":{}}\n',
            "segmentation/test_expressions.jsonl": _bundle_bytes(
                OLD_SHA, [_vector("seg/a"), _vector("seg/b")]
            ),
            "authored/compat/wirestub.jsonl": _bundle_bytes(LEGACY_SHA, []),
        }

    def test_pr223_state_fails(self) -> None:
        """New bundle + changed counts under the SAME stamp is the PR #223 bug."""
        base = self._base()
        head = dict(base)
        head["manifest.json"] = _manifest_bytes(OLD_SHA, total=4, date="2026-08-21")
        head["bookmarks/test_report_links.jsonl"] = _bundle_bytes(
            OLD_SHA, [_vector("bm/a")]
        )
        findings = check_stamp_moved(base, head)
        assert len(findings) == 1
        finding = findings[0]
        assert finding.rule == "stamp_not_moved"
        assert finding.path == "manifest.json"
        assert OLD_SHA in finding.detail
        assert "bookmarks/test_report_links.jsonl" in finding.detail
        assert "manifest.json" in finding.detail

    def test_stamp_only_repin_is_clean(self) -> None:
        """Re-stamping every header and the manifest date/commit moves no content."""
        base = self._base()
        head = {
            "manifest.json": _manifest_bytes(MAIN_SHA, total=3, date="2026-09-03"),
            "api-index.json": base["api-index.json"],
            "segmentation/test_expressions.jsonl": _bundle_bytes(
                MAIN_SHA, [_vector("seg/a"), _vector("seg/b")]
            ),
            "authored/compat/wirestub.jsonl": base["authored/compat/wirestub.jsonl"],
        }
        assert content_moved(base, head) == []
        assert check_stamp_moved(base, head) == []

    def test_content_and_stamp_moving_together_is_clean(self) -> None:
        """Content may change freely when the manifest stamp changes with it."""
        base = self._base()
        head = dict(base)
        head["manifest.json"] = _manifest_bytes(MAIN_SHA, total=4)
        head["bookmarks/new.jsonl"] = _bundle_bytes(MAIN_SHA, [_vector("bm/a")])
        assert check_stamp_moved(base, head) == []

    def test_vector_body_change_is_content(self) -> None:
        """A single vector-line byte change under the same stamp fails."""
        base = self._base()
        head = dict(base)
        head["segmentation/test_expressions.jsonl"] = _bundle_bytes(
            OLD_SHA, [_vector("seg/a"), _vector("seg/b", "changed")]
        )
        assert content_moved(base, head) == ["segmentation/test_expressions.jsonl"]
        assert _rules(check_stamp_moved(base, head)) == {"stamp_not_moved"}

    def test_api_index_and_removed_bundle_are_content(self) -> None:
        """api-index changes and bundle removals count as content moves."""
        base = self._base()
        head = dict(base)
        head["api-index.json"] = b'{"a":{},"b":{}}\n'
        head["segmentation/test_expressions.jsonl"] = None
        assert content_moved(base, head) == [
            "api-index.json",
            "segmentation/test_expressions.jsonl",
        ]

    def test_out_of_scope_changes_are_ignored(self) -> None:
        """Authored and enums edits do not require a stamp move."""
        base = self._base()
        head = dict(base)
        head["authored/compat/wirestub.jsonl"] = _bundle_bytes(
            LEGACY_SHA, [_vector("w")]
        )
        head["enums/bookmark_enums.json"] = b'{"new":1}\n'
        assert content_moved(base, head) == []
        assert check_stamp_moved(base, head) == []

    def test_first_corpus_commit_has_no_base_stamp(self) -> None:
        """With no manifest at the merge-base there is nothing to compare."""
        head = self._base()
        base: dict[str, bytes | None] = dict.fromkeys(head)
        assert check_stamp_moved(base, head) == []

    def test_many_moved_paths_are_elided(self) -> None:
        """Long moved-path lists are truncated in the finding detail."""
        base = self._base()
        head = dict(base)
        for i in range(25):
            head[f"filters/b{i:02d}.jsonl"] = _bundle_bytes(OLD_SHA, [_vector("f")])
        findings = check_stamp_moved(base, head)
        assert "... 5 more" in findings[0].detail


def _git(repo: Path, *args: str) -> str:
    """Run git in a scratch repository with identity and signing pinned.

    Args:
        repo: Repository directory.
        *args: Arguments after ``git``.

    Returns:
        Stripped stdout.

    Raises:
        subprocess.CalledProcessError: When git exits non-zero.
    """
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    proc = subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "-c",
            "commit.gpgsign=false",
            *args,
        ],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return proc.stdout.strip()


@pytest.fixture
def scratch_repo(tmp_path: Path) -> Path:
    """Create a git repo whose ``main`` holds a corpus stamped with a main SHA.

    Commit 1 ("lib") is the stamp target; commit 2 adds the corpus under
    ``conformance/vectors`` + ``conformance/contract`` stamped with commit 1.

    Args:
        tmp_path: pytest-provided scratch directory.

    Returns:
        The repository root.
    """
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "lib.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "add", "lib.py")
    _git(repo, "commit", "-q", "-m", "lib")
    lib_sha = _git(repo, "rev-parse", "HEAD")
    _make_tree(repo / "conformance", lib_sha)
    _git(repo, "add", "conformance")
    _git(repo, "commit", "-q", "-m", "corpus")
    return repo


class TestGitLayer:
    """The git-backed predicate and the CLI against a scratch repository."""

    def test_is_ancestor_predicate(self, scratch_repo: Path) -> None:
        """Reachable SHAs answer True; foreign or garbage SHAs answer False.

        Args:
            scratch_repo: Scratch repository fixture.
        """
        predicate = git_is_ancestor(scratch_repo, "main")
        head = _git(scratch_repo, "rev-parse", "HEAD")
        assert predicate(head) is True
        assert predicate(_git(scratch_repo, "rev-parse", "HEAD~1")) is True
        assert predicate("f" * 40) is False
        assert predicate("f" * 40) is False  # memoized path

    def test_clean_main_exits_zero(
        self, scratch_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A tree whose stamps point into main passes both rules.

        Args:
            scratch_repo: Scratch repository fixture.
            capsys: pytest stdout capture.
        """
        code = main(
            ["--repo", str(scratch_repo), "--main-ref", "main", "--base-ref", "main"]
        )
        assert code == 0
        assert "CLEAN" in capsys.readouterr().out

    def test_pr_adding_vectors_under_old_stamp_exits_one(
        self, scratch_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A PR that adds a bundle without moving the stamp fails rule 2.

        Args:
            scratch_repo: Scratch repository fixture.
            capsys: pytest stdout capture.
        """
        _git(scratch_repo, "checkout", "-q", "-b", "pr")
        _write(
            scratch_repo / "conformance/vectors/bookmarks/new.jsonl",
            _bundle_bytes(_git(scratch_repo, "rev-parse", "main~1"), [_vector("b")]),
        )
        _git(scratch_repo, "add", "conformance")
        _git(scratch_repo, "commit", "-q", "-m", "add vectors, forgot stamp")
        code = main(
            ["--repo", str(scratch_repo), "--main-ref", "main", "--base-ref", "main"]
        )
        out = capsys.readouterr().out
        assert code == 1
        assert "[stamp_not_moved]" in out
        assert "bookmarks/new.jsonl" in out
        assert "[reachability]" not in out

    def test_pr_repinned_to_main_sha_exits_zero(self, scratch_repo: Path) -> None:
        """The two-step protocol: re-stamp with the main squash SHA and pass.

        Args:
            scratch_repo: Scratch repository fixture.
        """
        main_sha = _git(scratch_repo, "rev-parse", "main")
        _git(scratch_repo, "checkout", "-q", "-b", "repin")
        _make_tree(scratch_repo / "conformance", main_sha)
        _write(
            scratch_repo / "conformance/vectors/bookmarks/new.jsonl",
            _bundle_bytes(main_sha, [_vector("b")]),
        )
        code = main(
            ["--repo", str(scratch_repo), "--main-ref", "main", "--base-ref", "main"]
        )
        assert code == 0

    def test_unreachable_stamp_exits_one(
        self, scratch_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A stamp naming a commit outside main fails rule 1 in the CLI.

        Args:
            scratch_repo: Scratch repository fixture.
            capsys: pytest stdout capture.
        """
        _git(scratch_repo, "checkout", "-q", "-b", "side")
        (scratch_repo / "side.txt").write_text("s\n", encoding="utf-8")
        _git(scratch_repo, "add", "side.txt")
        _git(scratch_repo, "commit", "-q", "-m", "side-only commit")
        side_sha = _git(scratch_repo, "rev-parse", "HEAD")
        _make_tree(scratch_repo / "conformance", side_sha)
        code = main(["--repo", str(scratch_repo), "--main-ref", "main"])
        out = capsys.readouterr().out
        assert code == 1
        assert "[reachability]" in out
        assert side_sha in out

    def test_unknown_main_ref_exits_two(
        self, scratch_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """An unresolvable main ref is a usage error, not a pass.

        Args:
            scratch_repo: Scratch repository fixture.
            capsys: pytest stderr capture.
        """
        code = main(["--repo", str(scratch_repo), "--main-ref", "origin/nope"])
        assert code == 2
        assert "error:" in capsys.readouterr().err

    def test_missing_vectors_dir_exits_two(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """A missing corpus directory is a usage error.

        Args:
            tmp_path: pytest-provided scratch directory.
            capsys: pytest stderr capture.
        """
        assert main(["--repo", str(tmp_path)]) == 2
        assert "does not exist" in capsys.readouterr().err
