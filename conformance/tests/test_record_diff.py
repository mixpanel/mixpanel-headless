"""Unit tests for the record-mode drift diff tool (design D8, PR-9).

Fixture-pair tests for ``conformance.record.diff`` per the D17.5 ruling
("diff tool <- fixture pairs"). The normative D8 semantics under test:
scope excludes ``authored/**`` and ``enums/**`` by path; within scope the
check is BIDIRECTIONAL — (1) bundle-path set equality, (2) per-vector-id
set equality within each bundle, (3) byte equality per vector line and per
``$bundle`` header, (4) manifest byte equality (stamps are injected, so
full equality applies). Any asymmetry in either direction fails.
"""

from __future__ import annotations

import json
from pathlib import Path

from conformance.record.diff import DiffFinding, diff_corpora, main


def _write_bundle(
    path: Path, source_file: str, vectors: list[dict[str, object]]
) -> None:
    """Write a JSONL vector bundle with a ``$bundle`` header line.

    Args:
        path: Destination ``.jsonl`` file path (parents created).
        source_file: Value for the header's ``source_file`` field.
        vectors: Vector objects to serialize, one per line, in order.

    Returns:
        None. The bundle is written to disk.

    Raises:
        OSError: If the destination cannot be written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {
        "$bundle": {
            "count": len(vectors),
            "source_commit": "52696743b913a0c4c152deb48af987ae412b5aee",
            "source_file": source_file,
        }
    }
    lines = [json.dumps(header, sort_keys=True, separators=(",", ":"))]
    lines.extend(json.dumps(v, sort_keys=True, separators=(",", ":")) for v in vectors)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _vector(vector_id: str, output: str = "ok") -> dict[str, object]:
    """Build a minimal vector object for bundle fixtures.

    Args:
        vector_id: The vector ``id`` field.
        output: The ``expect.output`` payload (varied to force byte drift).

    Returns:
        A minimal builder-kind vector dict.
    """
    return {
        "call": {"api": "expressions.normalize_on_expression", "input": {"on": "x"}},
        "capability": "segmentation",
        "expect": {"output": output},
        "id": vector_id,
        "kind": "builder",
        "origin": "extracted",
        "schema_version": "1.0",
        "source_test": "tests/unit/_internal/test_expressions.py::test_x",
    }


def _make_corpus(root: Path) -> Path:
    """Create a small but complete extracted-corpus tree under ``root``.

    The tree contains a manifest, an api-index, two capability bundles,
    plus out-of-scope content (``authored/**``, ``enums/**``, ``.gitkeep``)
    that the D8 diff must ignore.

    Args:
        root: Directory to populate (created if missing).

    Returns:
        The corpus root path (same as ``root``).

    Raises:
        OSError: If any fixture file cannot be written.
    """
    root.mkdir(parents=True, exist_ok=True)
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "extraction_date": "2026-08-14",
                "schema_version": "1.0",
                "source_commit": "52696743b913a0c4c152deb48af987ae412b5aee",
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    (root / "api-index.json").write_text(
        json.dumps(
            {"expressions.normalize_on_expression": {"kind": "builder"}}, sort_keys=True
        )
        + "\n",
        encoding="utf-8",
    )
    (root / ".gitkeep").write_text("", encoding="utf-8")
    _write_bundle(
        root / "segmentation" / "test_expressions.jsonl",
        "tests/unit/_internal/test_expressions.py",
        [_vector("segmentation/expressions/a"), _vector("segmentation/expressions/b")],
    )
    _write_bundle(
        root / "funnels" / "test_funnels.jsonl",
        "tests/unit/test_funnels.py",
        [_vector("funnels/workspace.build_funnel_params/a")],
    )
    _write_bundle(
        root / "authored" / "compat" / "pythoncompat.jsonl",
        "conformance/record/pycompat_ref.py",
        [_vector("compat/pycompat.zfill/authored-1")],
    )
    (root / "enums").mkdir(exist_ok=True)
    (root / "enums" / "bookmark_enums.json").write_text("{}\n", encoding="utf-8")
    return root


def _categories(findings: list[DiffFinding]) -> set[str]:
    """Collect the category labels present in a findings list.

    Args:
        findings: Findings returned by ``diff_corpora``.

    Returns:
        The set of ``category`` values.
    """
    return {f.category for f in findings}


class TestDiffCorpora:
    """Behavioral tests for ``diff_corpora`` against fixture pairs."""

    def test_identical_trees_are_clean(self, tmp_path: Path) -> None:
        """Byte-identical corpora produce zero findings.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        assert diff_corpora(a, b) == []

    def test_bundle_only_in_candidate_fails(self, tmp_path: Path) -> None:
        """A bundle present only on the re-extracted side is drift.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        _write_bundle(
            a / "retention" / "test_retention.jsonl",
            "tests/unit/test_retention.py",
            [_vector("retention/x/a")],
        )
        findings = diff_corpora(a, b)
        assert "bundle_only_in_candidate" in _categories(findings)

    def test_bundle_only_in_reference_fails(self, tmp_path: Path) -> None:
        """A bundle present only on the committed side is drift.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        (a / "funnels" / "test_funnels.jsonl").unlink()
        findings = diff_corpora(a, b)
        assert "bundle_only_in_reference" in _categories(findings)

    def test_vector_id_added_fails(self, tmp_path: Path) -> None:
        """An id present only on the re-extracted side of a bundle is drift.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        _write_bundle(
            a / "segmentation" / "test_expressions.jsonl",
            "tests/unit/_internal/test_expressions.py",
            [
                _vector("segmentation/expressions/a"),
                _vector("segmentation/expressions/b"),
                _vector("segmentation/expressions/new"),
            ],
        )
        findings = diff_corpora(a, b)
        assert "vector_only_in_candidate" in _categories(findings)

    def test_vector_id_removed_fails(self, tmp_path: Path) -> None:
        """An id present only on the committed side of a bundle is drift.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        _write_bundle(
            a / "segmentation" / "test_expressions.jsonl",
            "tests/unit/_internal/test_expressions.py",
            [_vector("segmentation/expressions/a")],
        )
        findings = diff_corpora(a, b)
        assert "vector_only_in_reference" in _categories(findings)

    def test_vector_line_byte_change_fails(self, tmp_path: Path) -> None:
        """A byte-level change in one vector line is drift.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        _write_bundle(
            a / "segmentation" / "test_expressions.jsonl",
            "tests/unit/_internal/test_expressions.py",
            [
                _vector("segmentation/expressions/a", output="DRIFTED"),
                _vector("segmentation/expressions/b"),
            ],
        )
        findings = diff_corpora(a, b)
        assert "vector_bytes_differ" in _categories(findings)
        drifted = [f for f in findings if f.category == "vector_bytes_differ"]
        assert any("segmentation/expressions/a" in f.detail for f in drifted)

    def test_bundle_header_change_fails(self, tmp_path: Path) -> None:
        """A byte-level change in the ``$bundle`` header line is drift.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        bundle = a / "funnels" / "test_funnels.jsonl"
        lines = bundle.read_text(encoding="utf-8").splitlines()
        header = json.loads(lines[0])
        header["$bundle"]["source_commit"] = "0" * 40
        lines[0] = json.dumps(header, sort_keys=True, separators=(",", ":"))
        bundle.write_text("\n".join(lines) + "\n", encoding="utf-8")
        findings = diff_corpora(a, b)
        assert "bundle_header_differs" in _categories(findings)

    def test_manifest_drift_fails(self, tmp_path: Path) -> None:
        """Any manifest byte difference is drift (stamps are injected).

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        (a / "manifest.json").write_text(
            '{"schema_version": "1.0"}\n', encoding="utf-8"
        )
        findings = diff_corpora(a, b)
        assert "manifest_differs" in _categories(findings)

    def test_api_index_drift_fails(self, tmp_path: Path) -> None:
        """Any api-index byte difference is drift (it is an extracted artifact).

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        (a / "api-index.json").write_text("{}\n", encoding="utf-8")
        findings = diff_corpora(a, b)
        assert "api_index_differs" in _categories(findings)

    def test_missing_manifest_fails(self, tmp_path: Path) -> None:
        """A side without a manifest is a structural failure, not a pass.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        (a / "manifest.json").unlink()
        findings = diff_corpora(a, b)
        assert "manifest_differs" in _categories(findings)

    def test_authored_and_enums_are_out_of_scope(self, tmp_path: Path) -> None:
        """Differences under ``authored/**`` and ``enums/**`` are ignored.

        Record mode never emits those paths, so a whole-tree diff would
        report them missing on every run (design D8).

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        # Candidate (re-extract output) has NO authored/enums content at all.
        (a / "authored" / "compat" / "pythoncompat.jsonl").unlink()
        (a / "enums" / "bookmark_enums.json").unlink()
        assert diff_corpora(a, b) == []

    def test_stray_non_jsonl_files_are_ignored(self, tmp_path: Path) -> None:
        """Non-bundle files like ``.gitkeep`` never participate in the diff.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        (a / ".gitkeep").unlink()
        (b / "segmentation" / "notes.txt").write_text("scratch\n", encoding="utf-8")
        assert diff_corpora(a, b) == []

    def test_duplicate_id_within_bundle_fails(self, tmp_path: Path) -> None:
        """A duplicate vector id inside one bundle is a structural failure.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        _write_bundle(
            a / "segmentation" / "test_expressions.jsonl",
            "tests/unit/_internal/test_expressions.py",
            [
                _vector("segmentation/expressions/a"),
                _vector("segmentation/expressions/a"),
                _vector("segmentation/expressions/b"),
            ],
        )
        findings = diff_corpora(a, b)
        assert "bundle_malformed" in _categories(findings)


class TestMain:
    """Exit-code contract of the ``python -m conformance.record.diff`` CLI."""

    def test_main_clean_returns_zero(self, tmp_path: Path) -> None:
        """Identical corpora exit 0.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        assert main([str(a), str(b)]) == 0

    def test_main_drift_returns_one(self, tmp_path: Path) -> None:
        """Any drift exits 1.

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        a = _make_corpus(tmp_path / "a")
        b = _make_corpus(tmp_path / "b")
        (a / "manifest.json").write_text("{}\n", encoding="utf-8")
        assert main([str(a), str(b)]) == 1

    def test_main_missing_dir_returns_two(self, tmp_path: Path) -> None:
        """A nonexistent corpus directory is a usage error (exit 2).

        Args:
            tmp_path: pytest-provided scratch directory.
        """
        b = _make_corpus(tmp_path / "b")
        assert main([str(tmp_path / "missing"), str(b)]) == 2
