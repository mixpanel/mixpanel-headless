"""Record-mode drift diff (design D8, normative semantics).

Compares a freshly re-extracted vector tree (the *candidate*, e.g.
``/tmp/re-extract``) against the committed corpus (the *reference*,
``conformance/vectors``) and fails on ANY asymmetry in either direction.

Scope is the EXTRACTED subset only: ``authored/**`` and ``enums/**`` are
excluded by path (record mode never emits them; a whole-tree diff would
report them missing on every run). Within scope the check is bidirectional:

1. bundle-path set equality (a ``.jsonl`` bundle present on only one side
   fails);
2. per-vector-id set equality within each bundle (added/removed ids fail);
3. byte equality per vector line and per ``$bundle`` header line;
4. manifest equality after dropping nothing (stamps are injected at record
   time, so full byte equality applies) — plus byte equality of the
   ``api-index.json`` sidecar, which is likewise emitted deterministically.

CLI:
    ```bash
    uv run python -m conformance.record.diff /tmp/re-extract conformance/vectors
    ```

Exit codes: 0 clean, 1 drift detected, 2 usage error (missing directory).
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

#: Top-level directories excluded from the drift scope (design D8): record
#: mode never emits them, so they exist only on the committed side.
_OUT_OF_SCOPE_DIRS = frozenset({"authored", "enums"})

#: Maximum findings printed per category before eliding (keeps CI logs sane).
_MAX_PRINTED_PER_CATEGORY = 20


@dataclass(frozen=True)
class DiffFinding:
    """One detected drift (or structural) problem.

    Attributes:
        category: Machine-readable label, e.g. ``"vector_bytes_differ"``,
            ``"bundle_only_in_candidate"``, ``"manifest_differs"``.
        path: Corpus-relative path of the file the finding concerns.
        detail: Human-readable specifics (vector id, side, etc.).
    """

    category: str
    path: str
    detail: str


@dataclass(frozen=True)
class _Bundle:
    """Parsed content of one JSONL vector bundle.

    Attributes:
        header: Raw bytes of the first (``$bundle`` header) line.
        vectors: Mapping of vector id to the raw bytes of its line.
    """

    header: bytes
    vectors: dict[str, bytes]


def _in_scope(rel: Path) -> bool:
    """Decide whether a corpus-relative path participates in the D8 diff.

    Args:
        rel: Path relative to the corpus root.

    Returns:
        True when the path is not under an out-of-scope top-level directory.
    """
    return not (rel.parts and rel.parts[0] in _OUT_OF_SCOPE_DIRS)


def _bundle_paths(root: Path) -> set[str]:
    """Enumerate in-scope bundle paths (relative, POSIX-style) under a corpus.

    Args:
        root: Corpus root directory.

    Returns:
        The set of relative ``.jsonl`` paths inside the D8 scope.
    """
    return {
        rel.as_posix()
        for p in root.rglob("*.jsonl")
        if _in_scope(rel := p.relative_to(root))
    }


def _load_bundle(path: Path, rel: str) -> tuple[_Bundle | None, list[DiffFinding]]:
    """Parse a JSONL bundle into its header line and id-keyed vector lines.

    Args:
        path: Absolute path of the bundle file.
        rel: Corpus-relative path used in findings.

    Returns:
        A pair ``(bundle, findings)``. ``bundle`` is None when the file is
        structurally malformed (empty, non-JSON line, missing/duplicate id,
        missing ``$bundle`` header), in which case ``findings`` explains why.
    """
    findings: list[DiffFinding] = []
    raw_lines = [ln for ln in path.read_bytes().split(b"\n") if ln]
    if not raw_lines:
        return None, [DiffFinding("bundle_malformed", rel, "empty bundle file")]
    header = raw_lines[0]
    try:
        header_obj = json.loads(header)
    except json.JSONDecodeError as exc:
        return None, [DiffFinding("bundle_malformed", rel, f"header not JSON: {exc}")]
    if not isinstance(header_obj, dict) or "$bundle" not in header_obj:
        return None, [
            DiffFinding("bundle_malformed", rel, "first line lacks $bundle header")
        ]
    vectors: dict[str, bytes] = {}
    for lineno, line in enumerate(raw_lines[1:], start=2):
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:
            findings.append(
                DiffFinding("bundle_malformed", rel, f"line {lineno} not JSON: {exc}")
            )
            continue
        vector_id = obj.get("id") if isinstance(obj, dict) else None
        if not isinstance(vector_id, str):
            findings.append(
                DiffFinding(
                    "bundle_malformed", rel, f"line {lineno} has no string 'id'"
                )
            )
            continue
        if vector_id in vectors:
            findings.append(
                DiffFinding(
                    "bundle_malformed", rel, f"duplicate vector id {vector_id!r}"
                )
            )
            continue
        vectors[vector_id] = line
    if findings:
        return None, findings
    return _Bundle(header=header, vectors=vectors), findings


def _diff_top_level_file(
    candidate: Path, reference: Path, name: str, category: str
) -> list[DiffFinding]:
    """Byte-compare one required top-level extracted file on both sides.

    Args:
        candidate: Re-extracted corpus root.
        reference: Committed corpus root.
        name: File name relative to the roots (e.g. ``"manifest.json"``).
        category: Finding category to emit on any difference or absence.

    Returns:
        Zero or one finding.
    """
    cand, ref = candidate / name, reference / name
    if not cand.is_file() or not ref.is_file():
        missing = [
            side
            for side, p in (("candidate", cand), ("reference", ref))
            if not p.is_file()
        ]
        return [DiffFinding(category, name, f"missing on: {', '.join(missing)}")]
    if cand.read_bytes() != ref.read_bytes():
        return [DiffFinding(category, name, "byte content differs")]
    return []


def _diff_bundle_pair(candidate: Path, reference: Path, rel: str) -> list[DiffFinding]:
    """Apply D8 checks 2-3 to one bundle present on both sides.

    Args:
        candidate: Re-extracted corpus root.
        reference: Committed corpus root.
        rel: Corpus-relative bundle path.

    Returns:
        Findings for header drift, id-set asymmetry, and per-line byte drift.
    """
    cand_bundle, cand_findings = _load_bundle(candidate / rel, rel)
    ref_bundle, ref_findings = _load_bundle(reference / rel, rel)
    findings = cand_findings + ref_findings
    if cand_bundle is None or ref_bundle is None:
        return findings
    if cand_bundle.header != ref_bundle.header:
        findings.append(
            DiffFinding("bundle_header_differs", rel, "$bundle header bytes differ")
        )
    cand_ids, ref_ids = set(cand_bundle.vectors), set(ref_bundle.vectors)
    for vector_id in sorted(cand_ids - ref_ids):
        findings.append(DiffFinding("vector_only_in_candidate", rel, vector_id))
    for vector_id in sorted(ref_ids - cand_ids):
        findings.append(DiffFinding("vector_only_in_reference", rel, vector_id))
    for vector_id in sorted(cand_ids & ref_ids):
        if cand_bundle.vectors[vector_id] != ref_bundle.vectors[vector_id]:
            findings.append(DiffFinding("vector_bytes_differ", rel, vector_id))
    return findings


def diff_corpora(candidate: Path, reference: Path) -> list[DiffFinding]:
    """Run the full D8 bidirectional drift check between two corpus trees.

    Args:
        candidate: Root of the freshly re-extracted tree (e.g.
            ``/tmp/re-extract``).
        reference: Root of the committed corpus
            (``conformance/vectors``).

    Returns:
        All findings, ordered by check (bundles, then per-bundle content,
        then manifest/api-index). Empty means byte-clean within scope.
    """
    findings: list[DiffFinding] = []
    cand_bundles = _bundle_paths(candidate)
    ref_bundles = _bundle_paths(reference)
    for rel in sorted(cand_bundles - ref_bundles):
        findings.append(
            DiffFinding("bundle_only_in_candidate", rel, "no committed counterpart")
        )
    for rel in sorted(ref_bundles - cand_bundles):
        findings.append(
            DiffFinding("bundle_only_in_reference", rel, "not re-extracted")
        )
    for rel in sorted(cand_bundles & ref_bundles):
        findings.extend(_diff_bundle_pair(candidate, reference, rel))
    findings.extend(
        _diff_top_level_file(candidate, reference, "manifest.json", "manifest_differs")
    )
    findings.extend(
        _diff_top_level_file(
            candidate, reference, "api-index.json", "api_index_differs"
        )
    )
    return findings


def _print_report(findings: list[DiffFinding]) -> None:
    """Print a per-category drift report to stdout.

    Args:
        findings: Findings from :func:`diff_corpora` (may be empty).

    Returns:
        None. Output goes to stdout only.
    """
    if not findings:
        print("drift check: CLEAN (byte-identical within D8 scope)")
        return
    by_category: dict[str, list[DiffFinding]] = {}
    for finding in findings:
        by_category.setdefault(finding.category, []).append(finding)
    print(f"drift check: FAILED — {len(findings)} finding(s)")
    for category in sorted(by_category):
        members = by_category[category]
        print(f"  [{category}] {len(members)} finding(s):")
        for finding in members[:_MAX_PRINTED_PER_CATEGORY]:
            print(f"    {finding.path}: {finding.detail}")
        if len(members) > _MAX_PRINTED_PER_CATEGORY:
            print(f"    ... {len(members) - _MAX_PRINTED_PER_CATEGORY} more elided")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python -m conformance.record.diff``.

    Args:
        argv: Argument list (candidate dir, reference dir); defaults to
            ``sys.argv[1:]``.

    Returns:
        0 when the corpora are byte-identical within scope, 1 on any drift,
        2 when either directory does not exist.
    """
    parser = argparse.ArgumentParser(
        prog="python -m conformance.record.diff",
        description="Bidirectional record-mode drift check (design D8).",
    )
    parser.add_argument("candidate", type=Path, help="freshly re-extracted vectors dir")
    parser.add_argument(
        "reference", type=Path, help="committed corpus dir (conformance/vectors)"
    )
    args = parser.parse_args(argv)
    candidate: Path = args.candidate
    reference: Path = args.reference
    for label, root in (("candidate", candidate), ("reference", reference)):
        if not root.is_dir():
            print(f"error: {label} directory does not exist: {root}", file=sys.stderr)
            return 2
    findings = diff_corpora(candidate, reference)
    _print_report(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
