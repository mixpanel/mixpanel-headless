"""Stamp-provenance guard for the conformance corpus (CI, before the D8 drift check).

The corpus carries two provenance stamps that name the library source it
was produced from: ``manifest.json`` ``source_commit`` (mirrored into the
``$bundle.source_commit`` header of every extracted bundle) and the
``generated_from`` field of the generated ``conformance/contract/*.json``
artifacts. Both are injected by the operator (design D3), never computed
with ``git rev-parse``, so the D8 drift check feeds the committed stamp back
into the re-extraction and can never notice a wrong one. This module is the
missing check. It is stdlib-only (plus a ``git`` subprocess).

Rules:

1. **Reachability.** ``manifest.source_commit`` must be a 40-hex SHA that is
   an ancestor of the main branch (``git merge-base --is-ancestor``). The
   same holds for every extracted bundle's ``$bundle.source_commit`` (which
   must also equal the manifest stamp — record mode writes one value
   everywhere, so a mismatch means a hand edit) and for every
   ``generated_from`` under ``conformance/contract/``. Authored bundles are
   exempt only through the explicit :data:`LEGACY_AUTHORED_STAMPS` allowlist
   of their existing hand-authored provenance; a new authored bundle, or an
   allowlisted one whose stamp changed, must carry a reachable SHA.
2. **Stamp moves with content.** When any in-scope corpus file
   (``conformance/vectors/**`` minus ``authored/**`` and ``enums/**``)
   differs from the merge-base with main in anything other than the stamp
   fields, ``manifest.source_commit`` must also differ from the merge-base
   value. This is the PR #223 failure mode (new vectors under the old pin).

CLI:
    ```bash
    uv run python -m conformance.record.check_stamps --main-ref origin/main
    uv run python -m conformance.record.check_stamps \\
        --main-ref origin/main --base-ref origin/main   # PR: rules 1 + 2
    ```

Exit codes: 0 clean, 1 findings, 2 usage or git error.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

#: Predicate answering "is this SHA an ancestor of main?".
IsAncestor = Callable[[str], bool]

#: Full 40-character lowercase hex SHA-1.
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

#: Top-level corpus directories that record mode never emits (design D8).
_OUT_OF_SCOPE_DIRS = frozenset({"authored", "enums"})

#: Corpus-relative path of the manifest.
MANIFEST_NAME = "manifest.json"

#: Manifest fields that are stamps (injected at record time, not content).
_MANIFEST_STAMP_KEYS = frozenset({"source_commit", "extraction_date"})

#: Contract artifacts written by ``generate_contract.py``; each MUST carry
#: ``generated_from``. Other ``*.json`` files in the contract directory
#: (e.g. the hand-maintained ``coverage_overrides.json``) are inputs and are
#: checked only when they carry the key.
GENERATED_CONTRACT_ARTIFACTS: tuple[str, ...] = (
    "error-codes.json",
    "literal-aliases.json",
    "model-coverage.json",
    "tag-universe.json",
)

#: Existing authored bundles and the hand-authored provenance they carry.
#: ``None`` means the header has no ``source_commit`` at all (the storybook
#: harvest bundles record ``generator`` + ``provenance`` instead). These
#: values predate the reachability rule and are left as-is on purpose: they
#: are authored-time provenance, not extraction provenance. Any authored
#: bundle NOT listed here, or listed with a different stamp, must carry a
#: main-reachable 40-hex SHA.
LEGACY_AUTHORED_STAMPS: Mapping[str, str | None] = {
    "authored/bookmarks/date-builders.jsonl": (
        "52696743b913a0c4c152deb48af987ae412b5aee"
    ),
    "authored/compat/pythoncompat-b0.jsonl": (
        "b5c1369824052d97931ff8c4516cbfb24d73a7ad"
    ),
    "authored/compat/pythoncompat.jsonl": "52696743b913a0c4c152deb48af987ae412b5aee",
    "authored/compat/wirestub.jsonl": "52696743b913a0c4c152deb48af987ae412b5aee",
    "authored/funnels/live-query-transforms.jsonl": (
        "52696743b913a0c4c152deb48af987ae412b5aee"
    ),
    "authored/parse/phase008.jsonl": "52696743b913a0c4c152deb48af987ae412b5aee",
    "authored/parse/storybook/arb_funnels.jsonl": None,
    "authored/parse/storybook/boards.jsonl": None,
    "authored/parse/storybook/bookmarks.jsonl": None,
    "authored/parse/storybook/insights.jsonl": None,
    "authored/replays/rrweb-seed.jsonl": "52696743b913a0c4c152deb48af987ae412b5aee",
    "authored/retention/live-query-transforms.jsonl": (
        "52696743b913a0c4c152deb48af987ae412b5aee"
    ),
    "authored/streaming/jsonl-chunks.jsonl": (
        "52696743b913a0c4c152deb48af987ae412b5aee"
    ),
    "authored/validation/uncovered-codes.jsonl": (
        "52696743b913a0c4c152deb48af987ae412b5aee"
    ),
}

#: Maximum paths listed per finding before eliding (keeps CI logs sane).
_MAX_LISTED_PATHS = 20


@dataclass(frozen=True)
class StampFinding:
    """One stamp-provenance violation.

    Attributes:
        rule: ``"reachability"`` (rule 1) or ``"stamp_not_moved"`` (rule 2).
        path: Repo- or corpus-relative path the finding concerns.
        detail: Human-readable specifics.
    """

    rule: str
    path: str
    detail: str


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------


def _in_scope(rel: str) -> bool:
    """Decide whether a corpus-relative path is in the extracted scope.

    Args:
        rel: POSIX-style path relative to the corpus root.

    Returns:
        True unless the first path segment is ``authored`` or ``enums``.
    """
    parts = Path(rel).parts
    return not (parts and parts[0] in _OUT_OF_SCOPE_DIRS)


def _load_json_object(data: bytes) -> dict[str, object] | None:
    """Parse bytes as a JSON object.

    Args:
        data: Raw file bytes.

    Returns:
        The parsed dict, or None when the bytes are not a JSON object.
    """
    try:
        obj = json.loads(data)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    return obj if isinstance(obj, dict) else None


def _bundle_header(data: bytes) -> dict[str, object] | None:
    """Parse the ``$bundle`` header object from the first line of a bundle.

    Args:
        data: Raw bundle bytes.

    Returns:
        The ``$bundle`` object, or None when the first line is not a JSON
        object with a ``$bundle`` dict.
    """
    first = data.split(b"\n", 1)[0]
    outer = _load_json_object(first)
    if outer is None:
        return None
    header = outer.get("$bundle")
    return header if isinstance(header, dict) else None


def _manifest_stamp(data: bytes | None) -> object:
    """Read ``source_commit`` from manifest bytes.

    Args:
        data: Raw manifest bytes, or None when the manifest is absent.

    Returns:
        The ``source_commit`` value (any JSON type), or None when absent
        or unparsable.
    """
    if data is None:
        return None
    obj = _load_json_object(data)
    return None if obj is None else obj.get("source_commit")


def _check_sha(
    rule: str, path: str, label: str, value: object, is_ancestor: IsAncestor
) -> list[StampFinding]:
    """Validate one stamp value: present, 40-hex, ancestor of main.

    Args:
        rule: Finding rule label.
        path: Path used in findings.
        label: Field name used in the finding detail.
        value: The stamp value as read from the file.
        is_ancestor: Reachability predicate.

    Returns:
        Zero or one finding.
    """
    if not isinstance(value, str) or not SHA_RE.match(value):
        return [StampFinding(rule, path, f"{label} is not a 40-hex SHA: {value!r}")]
    if not is_ancestor(value):
        return [StampFinding(rule, path, f"{label} {value} is not reachable from main")]
    return []


# --------------------------------------------------------------------------
# Rule 1 — reachability
# --------------------------------------------------------------------------


def check_reachability(
    vectors: Path, contract: Path, is_ancestor: IsAncestor
) -> list[StampFinding]:
    """Apply rule 1 to a corpus tree and a contract directory.

    Args:
        vectors: Corpus root (``conformance/vectors``).
        contract: Contract artifact directory (``conformance/contract``).
        is_ancestor: Predicate answering whether a SHA is reachable from
            main. Injected so tests need no git history.

    Returns:
        All rule-1 findings (empty when clean).
    """
    findings: list[StampFinding] = []
    manifest_path = vectors / MANIFEST_NAME
    if not manifest_path.is_file():
        return [StampFinding("reachability", MANIFEST_NAME, "manifest missing")]
    manifest_stamp = _manifest_stamp(manifest_path.read_bytes())
    findings.extend(
        _check_sha(
            "reachability", MANIFEST_NAME, "source_commit", manifest_stamp, is_ancestor
        )
    )
    for bundle_path in sorted(vectors.rglob("*.jsonl")):
        rel = bundle_path.relative_to(vectors).as_posix()
        header = _bundle_header(bundle_path.read_bytes())
        if header is None:
            findings.append(
                StampFinding("reachability", rel, "first line lacks $bundle header")
            )
            continue
        stamp = header.get("source_commit")
        if _in_scope(rel):
            if stamp != manifest_stamp:
                findings.append(
                    StampFinding(
                        "reachability",
                        rel,
                        f"$bundle.source_commit {stamp!r} != manifest "
                        f"source_commit {manifest_stamp!r}",
                    )
                )
            findings.extend(
                _check_sha(
                    "reachability", rel, "$bundle.source_commit", stamp, is_ancestor
                )
            )
            continue
        if rel in LEGACY_AUTHORED_STAMPS and LEGACY_AUTHORED_STAMPS[rel] == stamp:
            continue
        findings.extend(
            _check_sha("reachability", rel, "$bundle.source_commit", stamp, is_ancestor)
        )
    findings.extend(_check_contract(contract, is_ancestor))
    return findings


def _check_contract(contract: Path, is_ancestor: IsAncestor) -> list[StampFinding]:
    """Apply rule 1 to the ``generated_from`` stamps under ``contract``.

    Args:
        contract: Contract artifact directory.
        is_ancestor: Reachability predicate.

    Returns:
        Findings for missing generated artifacts, missing keys on generated
        artifacts, and unreachable or malformed ``generated_from`` values.
    """
    findings: list[StampFinding] = []
    present = {p.name: p for p in contract.glob("*.json")} if contract.is_dir() else {}
    for name in GENERATED_CONTRACT_ARTIFACTS:
        if name not in present:
            findings.append(
                StampFinding(
                    "reachability", f"contract/{name}", "generated artifact missing"
                )
            )
    for name in sorted(present):
        obj = _load_json_object(present[name].read_bytes())
        rel = f"contract/{name}"
        if obj is None:
            findings.append(StampFinding("reachability", rel, "not a JSON object"))
            continue
        if "generated_from" not in obj:
            if name in GENERATED_CONTRACT_ARTIFACTS:
                findings.append(
                    StampFinding("reachability", rel, "generated_from missing")
                )
            continue
        findings.extend(
            _check_sha(
                "reachability",
                rel,
                "generated_from",
                obj["generated_from"],
                is_ancestor,
            )
        )
    return findings


# --------------------------------------------------------------------------
# Rule 2 — the stamp must move when content moves
# --------------------------------------------------------------------------


def strip_stamps(rel: str, data: bytes | None) -> bytes | None:
    """Return the content of a corpus file with its stamp fields removed.

    Args:
        rel: Corpus-relative POSIX path (decides the file's stamp shape).
        data: Raw bytes, or None when the file does not exist on that side.

    Returns:
        None when ``data`` is None. For ``manifest.json``: canonical JSON
        without ``source_commit`` / ``extraction_date``. For a ``.jsonl``
        bundle: the header re-serialized without ``$bundle.source_commit``,
        followed by the untouched body lines. Anything else (including a
        malformed manifest or header) is returned unchanged.
    """
    if data is None:
        return None
    if rel == MANIFEST_NAME:
        obj = _load_json_object(data)
        if obj is None:
            return data
        body = {k: v for k, v in obj.items() if k not in _MANIFEST_STAMP_KEYS}
        return json.dumps(body, sort_keys=True).encode("utf-8")
    if rel.endswith(".jsonl"):
        first, _, rest = data.partition(b"\n")
        outer = _load_json_object(first)
        header = outer.get("$bundle") if outer is not None else None
        if outer is None or not isinstance(header, dict):
            return data
        header = {k: v for k, v in header.items() if k != "source_commit"}
        outer = {**outer, "$bundle": header}
        return json.dumps(outer, sort_keys=True).encode("utf-8") + b"\n" + rest
    return data


def content_moved(
    base: Mapping[str, bytes | None], head: Mapping[str, bytes | None]
) -> list[str]:
    """List in-scope corpus paths whose stamp-stripped content differs.

    Args:
        base: Corpus-relative path → bytes at the merge-base (None = absent).
        head: Corpus-relative path → bytes at the head (None = absent).

    Returns:
        Sorted paths that were added, removed, or changed in anything other
        than stamp fields. Out-of-scope paths are ignored.
    """
    moved: list[str] = []
    for rel in sorted(set(base) | set(head)):
        if not _in_scope(rel):
            continue
        if strip_stamps(rel, base.get(rel)) != strip_stamps(rel, head.get(rel)):
            moved.append(rel)
    return moved


def check_stamp_moved(
    base: Mapping[str, bytes | None], head: Mapping[str, bytes | None]
) -> list[StampFinding]:
    """Apply rule 2 to a base/head pair of corpus file maps.

    Both maps must include ``manifest.json`` when it exists on that side;
    other entries may be limited to the files git reports as changed.

    Args:
        base: Corpus-relative path → bytes at the merge-base (None = absent).
        head: Corpus-relative path → bytes at the head (None = absent).

    Returns:
        One finding when content moved but ``source_commit`` did not; empty
        otherwise. A base side with no manifest (first corpus commit) has no
        stamp to compare and yields no finding.
    """
    moved = content_moved(base, head)
    if not moved:
        return []
    base_stamp = _manifest_stamp(base.get(MANIFEST_NAME))
    head_stamp = _manifest_stamp(head.get(MANIFEST_NAME))
    if base_stamp is None or base_stamp != head_stamp:
        return []
    listed = ", ".join(moved[:_MAX_LISTED_PATHS])
    if len(moved) > _MAX_LISTED_PATHS:
        listed += f", ... {len(moved) - _MAX_LISTED_PATHS} more"
    return [
        StampFinding(
            "stamp_not_moved",
            MANIFEST_NAME,
            f"{len(moved)} in-scope file(s) changed beyond stamp lines but "
            f"source_commit is still {base_stamp}: {listed}",
        )
    ]


# --------------------------------------------------------------------------
# git layer
# --------------------------------------------------------------------------


class GitError(RuntimeError):
    """Raised when a required ``git`` invocation fails."""


def _git(
    repo: Path, *args: str, check: bool = True
) -> subprocess.CompletedProcess[bytes]:
    """Run a git command inside ``repo``.

    Args:
        repo: Repository working directory.
        *args: Arguments after ``git``.
        check: Raise :class:`GitError` on a non-zero exit when True.

    Returns:
        The completed process (stdout/stderr captured as bytes).

    Raises:
        GitError: When ``check`` is True and git exits non-zero, or git is
            not installed.
    """
    try:
        proc = subprocess.run(
            ["git", *args], cwd=repo, capture_output=True, check=False
        )
    except OSError as exc:  # git missing
        raise GitError(f"cannot run git: {exc}") from exc
    if check and proc.returncode != 0:
        raise GitError(
            f"git {' '.join(args)} failed ({proc.returncode}): "
            f"{proc.stderr.decode('utf-8', 'replace').strip()}"
        )
    return proc


def git_is_ancestor(repo: Path, main_ref: str) -> IsAncestor:
    """Build a memoized "reachable from ``main_ref``" predicate.

    Args:
        repo: Repository working directory.
        main_ref: The main-branch ref to test against (e.g. ``origin/main``).

    Returns:
        A predicate that runs ``git merge-base --is-ancestor <sha> <main_ref>``
        once per distinct SHA. Exit 0 → True; exit 1 → False; any other
        exit (unknown SHA, unknown ref) → False.

    Raises:
        GitError: When ``main_ref`` cannot be resolved at build time.
    """
    _git(repo, "rev-parse", "--verify", "--quiet", f"{main_ref}^{{commit}}")
    cache: dict[str, bool] = {}

    def predicate(sha: str) -> bool:
        """Answer reachability for one SHA, memoized.

        Args:
            sha: Full commit SHA.

        Returns:
            True when ``sha`` is an ancestor of (or equal to) ``main_ref``.
        """
        if sha not in cache:
            proc = _git(repo, "merge-base", "--is-ancestor", sha, main_ref, check=False)
            cache[sha] = proc.returncode == 0
        return cache[sha]

    return predicate


def git_show(repo: Path, ref: str, repo_rel: str) -> bytes | None:
    """Read a file's bytes at ``ref``.

    Args:
        repo: Repository working directory.
        ref: Commit-ish.
        repo_rel: Repo-relative POSIX path.

    Returns:
        The bytes, or None when the path does not exist at ``ref``.
    """
    proc = _git(repo, "show", f"{ref}:{repo_rel}", check=False)
    return proc.stdout if proc.returncode == 0 else None


def collect_pr_file_maps(
    repo: Path, vectors_rel: str, base_ref: str
) -> tuple[str, dict[str, bytes | None], dict[str, bytes | None]]:
    """Gather the base/head corpus file maps rule 2 needs.

    The base side is the merge-base of ``base_ref`` and ``HEAD``; the head
    side is the working tree (identical to ``HEAD`` in CI, and inclusive of
    uncommitted edits when run locally). Only files git reports as changed
    are loaded, plus ``manifest.json`` on both sides.

    Args:
        repo: Repository working directory.
        vectors_rel: Repo-relative corpus path (``conformance/vectors``).
        base_ref: Ref to compute the merge-base against (e.g. ``origin/main``).

    Returns:
        ``(merge_base_sha, base_map, head_map)`` with corpus-relative keys.

    Raises:
        GitError: When the merge-base or the diff cannot be computed.
    """
    merge_base = _git(repo, "merge-base", base_ref, "HEAD").stdout.decode().strip()
    out = _git(repo, "diff", "--name-only", "-z", merge_base, "--", vectors_rel).stdout
    changed = [p.decode("utf-8") for p in out.split(b"\0") if p]
    prefix = vectors_rel.rstrip("/") + "/"
    rels = {p[len(prefix) :] for p in changed if p.startswith(prefix)}
    rels.add(MANIFEST_NAME)
    base: dict[str, bytes | None] = {}
    head: dict[str, bytes | None] = {}
    for rel in sorted(rels):
        base[rel] = git_show(repo, merge_base, prefix + rel)
        head_path = repo / prefix / rel
        head[rel] = head_path.read_bytes() if head_path.is_file() else None
    return merge_base, base, head


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------


def _print_report(findings: list[StampFinding]) -> None:
    """Print findings grouped by rule to stdout.

    Args:
        findings: Findings from both rules (may be empty).

    Returns:
        None.
    """
    if not findings:
        print(
            "stamp check: CLEAN (all stamps reachable from main; stamp moved with content)"
        )
        return
    by_rule: dict[str, list[StampFinding]] = {}
    for finding in findings:
        by_rule.setdefault(finding.rule, []).append(finding)
    print(f"stamp check: FAILED — {len(findings)} finding(s)")
    for rule in sorted(by_rule):
        members = by_rule[rule]
        print(f"  [{rule}] {len(members)} finding(s):")
        for finding in members[:_MAX_LISTED_PATHS]:
            print(f"    {finding.path}: {finding.detail}")
        if len(members) > _MAX_LISTED_PATHS:
            print(f"    ... {len(members) - _MAX_LISTED_PATHS} more elided")


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for ``python -m conformance.record.check_stamps``.

    Args:
        argv: Argument list; defaults to ``sys.argv[1:]``.

    Returns:
        0 when clean, 1 on any finding, 2 on a usage or git error.
    """
    parser = argparse.ArgumentParser(
        prog="python -m conformance.record.check_stamps",
        description="Corpus stamp-provenance guard (rules 1 + 2).",
    )
    parser.add_argument(
        "--repo", type=Path, default=Path.cwd(), help="repository root (default: cwd)"
    )
    parser.add_argument(
        "--vectors",
        default="conformance/vectors",
        help="repo-relative corpus root (default: conformance/vectors)",
    )
    parser.add_argument(
        "--contract",
        default="conformance/contract",
        help="repo-relative contract dir (default: conformance/contract)",
    )
    parser.add_argument(
        "--main-ref",
        default="origin/main",
        help="ref every stamp must be reachable from (default: origin/main)",
    )
    parser.add_argument(
        "--base-ref",
        default=None,
        help="enable rule 2 against the merge-base with this ref (PR runs)",
    )
    args = parser.parse_args(argv)
    repo: Path = args.repo
    vectors = repo / args.vectors
    contract = repo / args.contract
    if not vectors.is_dir():
        print(f"error: vectors directory does not exist: {vectors}", file=sys.stderr)
        return 2
    try:
        is_ancestor = git_is_ancestor(repo, args.main_ref)
        findings = check_reachability(vectors, contract, is_ancestor)
        if args.base_ref is not None:
            merge_base, base, head = collect_pr_file_maps(
                repo, str(args.vectors), args.base_ref
            )
            print(f"stamp check: rule 2 against merge-base {merge_base}")
            findings.extend(check_stamp_moved(base, head))
    except GitError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    _print_report(findings)
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
