"""Deliberate-break smoke test for the conformance corpus (design D9).

Executes the fixed 13-patch sabotage protocol from the Phase-1 design of
record (D9.1 patch table, D9.2 worktree mechanics, D9.3 pass criterion):

1. A CONTROL worktree at the rig branch HEAD, bootstrapped with
   ``uv sync --all-extras``, must replay the committed corpus with
   0 ``vector_failed`` and 0 crashes.
2. Each sabotage patch ``S01..S13`` is applied to a fresh worktree at the
   SAME ref; the pytest-free corpus-runner CLI must report >=1
   ``vector_failed`` (status ``caught``) with no crash.
3. A runner crash (exit 2, unparseable report, timeout, bootstrap failure)
   is NEVER a catch — it is a smoke ERROR distinct from both PASS and MISS.

Usage:
    ```bash
    just conformance-smoke                       # full run, writes last-run.json
    just conformance-smoke -- --patches S05      # D9.3 re-run of one patch
    just conformance-smoke -- --skip-control --patches S03,S04
    ```

``conformance/smoke/last-run.json`` (committed provenance, design D9.3) is
written ONLY on a full run (control + all 13 patches) so partial re-runs
never masquerade as a complete smoke record.
"""

from __future__ import annotations

import argparse
import datetime
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SMOKE_DIR = Path(__file__).resolve().parent
"""Absolute path of ``conformance/smoke/`` in the invoking checkout."""

REPO_ROOT = SMOKE_DIR.parents[1]
"""Repository root of the invoking checkout (worktrees are added from here)."""

PATCHES_DIR = SMOKE_DIR / "patches"
"""Directory holding the fixed ``S01..S13`` unified-diff patch files."""

LAST_RUN_PATH = SMOKE_DIR / "last-run.json"
"""Committed provenance file written after every FULL smoke run (D9.3)."""

PATCH_IDS: tuple[str, ...] = tuple(f"S{n:02d}" for n in range(1, 14))
"""The fixed D9.1 patch identifiers, in run order."""

WORKTREE_PARENT = Path("/tmp")
"""Parent directory for throwaway smoke worktrees (design D9.2)."""

SYNC_TIMEOUT_SECONDS = 900
"""Timeout for ``uv sync --all-extras`` in a fresh worktree."""

RUNNER_TIMEOUT_SECONDS = 900
"""Timeout for one corpus-runner CLI invocation (budget is <=5 min, D7)."""

INFRA_REASON_PREFIX = "replay infrastructure error inside vector"
"""Reason prefix ``runner.execute.run_vector`` uses for in-vector harness
exceptions (decode failures, target construction crashes). A sabotage
"catch" whose failure reasons are ALL of this shape proves nothing about
behavioral divergence and is flagged for manual review (GATE-VERDICT
recommendation R9, audit finding L2-F2)."""


@dataclass(frozen=True)
class RunOutcome:
    """Result of one worktree run (control or one sabotage patch).

    Args:
        patch: Patch id (``"S01"``..``"S13"``) or ``"control"``.
        status: ``caught`` / ``missed`` / ``error`` for patches;
            ``clean`` / ``dirty`` / ``error`` for the control run (D9.3).
        failing_vector_count: Number of vectors that diffed red.
        first_failing_id: Vector id of the first failure, if any.
        total: Total vectors the runner executed (0 on crash).
        runtime_seconds: Runner-reported wall time (0.0 on crash).
        error: Infrastructure-failure description when ``status == "error"``.
        infrastructure_only: True when the run failed vectors but EVERY
            failure reason carries the :data:`INFRA_REASON_PREFIX` shape —
            a catch that needs manual review, not trust (R9).
    """

    patch: str
    status: str
    failing_vector_count: int
    first_failing_id: str | None
    total: int
    runtime_seconds: float
    error: str | None
    infrastructure_only: bool = False


def _run(
    cmd: list[str],
    cwd: Path,
    timeout: int,
    capture_stdout: bool,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess with stderr passed through to the console.

    stderr is NEVER captured or suppressed (repo debugging rule): bootstrap
    and runner diagnostics stream to the invoking terminal.

    Args:
        cmd: Command argv.
        cwd: Working directory (``uv run`` resolution is cwd-dependent).
        timeout: Seconds before the subprocess is killed.
        capture_stdout: True to capture stdout (runner JSON report).

    Returns:
        The completed process (stdout captured only when requested).

    Raises:
        subprocess.TimeoutExpired: If the command exceeds ``timeout``.
    """
    return subprocess.run(
        cmd,
        cwd=cwd,
        stdout=subprocess.PIPE if capture_stdout else None,
        stderr=None,
        text=True,
        timeout=timeout,
        check=False,
    )


def _remove_worktree(path: Path) -> None:
    """Force-remove a smoke worktree and prune stale registrations.

    Args:
        path: The worktree directory (may or may not exist).
    """
    if path.exists():
        _run(
            ["git", "worktree", "remove", "--force", str(path)],
            REPO_ROOT,
            timeout=120,
            capture_stdout=False,
        )
    _run(["git", "worktree", "prune"], REPO_ROOT, timeout=120, capture_stdout=False)


def _prepare_worktree(name: str, ref: str) -> tuple[Path, str | None]:
    """Create and bootstrap a fresh worktree at ``ref`` (design D9.2 steps 1-2).

    The ``uv sync --all-extras`` bootstrap is mandatory, not an optimization:
    the runner's clock shim imports ``freezegun`` from the dev extras, and a
    bare ``uv run`` in a fresh worktree would die on import in every run.

    Args:
        name: Worktree directory name under ``/tmp`` (e.g. ``mp-smoke-S03``).
        ref: Git ref the worktree is checked out at (the rig branch HEAD).

    Returns:
        ``(worktree_path, error)`` — ``error`` is None on success, else a
        description of the add/bootstrap failure (a smoke ERROR, never a
        catch).
    """
    path = WORKTREE_PARENT / name
    _remove_worktree(path)
    added = _run(
        ["git", "worktree", "add", "--detach", str(path), ref],
        REPO_ROOT,
        timeout=300,
        capture_stdout=False,
    )
    if added.returncode != 0:
        return path, f"git worktree add failed with exit {added.returncode}"
    try:
        synced = _run(
            ["uv", "sync", "--all-extras"],
            path,
            timeout=SYNC_TIMEOUT_SECONDS,
            capture_stdout=False,
        )
    except subprocess.TimeoutExpired:
        return path, "uv sync --all-extras timed out"
    if synced.returncode != 0:
        return path, f"uv sync --all-extras failed with exit {synced.returncode}"
    return path, None


def _apply_patch(worktree: Path, patch_id: str) -> str | None:
    """Apply one sabotage patch inside a worktree (design D9.2 step 3).

    Args:
        worktree: Bootstrapped worktree path.
        patch_id: One of ``PATCH_IDS``.

    Returns:
        None on success, else an error description (``git apply`` rejection
        fails loudly — Risk Register #7 anchor rot).
    """
    patch_path = PATCHES_DIR / f"{patch_id}.patch"
    if not patch_path.is_file():
        return f"patch file missing: {patch_path}"
    applied = _run(
        ["git", "apply", str(patch_path)],
        worktree,
        timeout=120,
        capture_stdout=False,
    )
    if applied.returncode != 0:
        return f"git apply {patch_path.name} failed with exit {applied.returncode}"
    return None


def _run_runner(worktree: Path) -> tuple[int, dict[str, Any] | None, str | None]:
    """Invoke the pytest-free corpus-runner CLI from the worktree cwd.

    Library code AND vectors both come from the worktree tree (D9.2 step 4);
    ``uv run`` resolution is cwd-dependent, so cwd is the worktree root.

    Args:
        worktree: Bootstrapped (and possibly patched) worktree path.

    Returns:
        ``(exit_code, report, error)`` — ``report`` is the parsed JSON
        report or None; ``error`` describes timeout/parse failures.
    """
    cmd = [
        "uv",
        "run",
        "python",
        "-m",
        "conformance.runner",
        "--vectors",
        str(worktree / "conformance" / "vectors"),
        "--report",
        "json",
    ]
    try:
        proc = _run(cmd, worktree, timeout=RUNNER_TIMEOUT_SECONDS, capture_stdout=True)
    except subprocess.TimeoutExpired:
        return -1, None, "corpus runner timed out"
    try:
        report_obj = json.loads(proc.stdout or "")
    except json.JSONDecodeError:
        return proc.returncode, None, "runner stdout was not a JSON report"
    if not isinstance(report_obj, dict):
        return proc.returncode, None, "runner report was not a JSON object"
    return proc.returncode, report_obj, None


def _classify(
    patch: str,
    exit_code: int,
    report: dict[str, Any] | None,
    error: str | None,
) -> RunOutcome:
    """Turn a runner invocation into a D9.3 verdict (a crash is NEVER a catch).

    Args:
        patch: ``"control"`` or a patch id.
        exit_code: Runner CLI exit code (0 ok / 1 vector_failed / 2 crash).
        report: Parsed JSON report, if stdout parsed.
        error: Infrastructure error from ``_run_runner``, if any.

    Returns:
        The classified :class:`RunOutcome`.
    """
    is_control = patch == "control"
    if error is not None or report is None or exit_code not in (0, 1):
        message = error or f"runner exited {exit_code} (runner_crashed)"
        if report is not None and report.get("error"):
            message = f"{message}: {report['error']}"
        return RunOutcome(
            patch=patch,
            status="error",
            failing_vector_count=0,
            first_failing_id=None,
            total=0,
            runtime_seconds=0.0,
            error=message,
        )
    failures = report.get("failures") or []
    failing_count = int(report.get("failed", len(failures)))
    first_id = str(failures[0]["id"]) if failures else None
    if is_control:
        status = "clean" if failing_count == 0 else "dirty"
    else:
        status = "caught" if failing_count >= 1 else "missed"
    reasons = [
        str(reason) for failure in failures for reason in (failure.get("reasons") or [])
    ]
    infrastructure_only = bool(reasons) and all(
        reason.startswith(INFRA_REASON_PREFIX) for reason in reasons
    )
    return RunOutcome(
        patch=patch,
        status=status,
        failing_vector_count=failing_count,
        first_failing_id=first_id,
        total=int(report.get("total", 0)),
        runtime_seconds=float(report.get("runtime_seconds", 0.0)),
        error=None,
        infrastructure_only=infrastructure_only,
    )


def _execute_one(patch: str, ref: str, keep_worktrees: bool) -> RunOutcome:
    """Run the control or one sabotage patch end-to-end (D9.2 steps 1-5).

    Args:
        patch: ``"control"`` or a patch id from ``PATCH_IDS``.
        ref: Git ref for the worktree (the rig branch HEAD).
        keep_worktrees: True to skip cleanup (debugging only).

    Returns:
        The classified :class:`RunOutcome` for this run.
    """
    name = f"mp-smoke-{patch}"
    worktree, prep_error = _prepare_worktree(name, ref)
    try:
        if prep_error is not None:
            return _classify(patch, -1, None, prep_error)
        if patch != "control":
            apply_error = _apply_patch(worktree, patch)
            if apply_error is not None:
                return _classify(patch, -1, None, apply_error)
        exit_code, report, run_error = _run_runner(worktree)
        return _classify(patch, exit_code, report, run_error)
    finally:
        if not keep_worktrees:
            _remove_worktree(worktree)


def _print_table(outcomes: list[RunOutcome]) -> None:
    """Print the per-patch result table (design D9.3).

    Args:
        outcomes: All run outcomes, control first.
    """
    print(f"{'patch':<9} {'status':<8} {'failing':>8}  first_failing_id")
    for outcome in outcomes:
        first = outcome.first_failing_id or "-"
        suffix = f"  [{outcome.error}]" if outcome.error else ""
        if outcome.infrastructure_only:
            suffix += "  [INFRA-ONLY: needs manual review (R9)]"
        print(
            f"{outcome.patch:<9} {outcome.status:<8} "
            f"{outcome.failing_vector_count:>8}  {first}{suffix}"
        )


def _write_last_run(ref_sha: str, outcomes: list[RunOutcome], passed: bool) -> None:
    """Write the committed provenance file ``last-run.json`` (design D9.3).

    Args:
        ref_sha: Full SHA of the ref every worktree ran at.
        outcomes: All run outcomes, control first.
        passed: True when the D9.3 pass criterion held.
    """
    control = next(o for o in outcomes if o.patch == "control")
    patches = [o for o in outcomes if o.patch != "control"]
    payload = {
        "commit": ref_sha,
        "date": datetime.date.today().isoformat(),
        "result": "PASS" if passed else "FAIL",
        "control": asdict(control),
        "patches": [asdict(o) for o in patches],
    }
    LAST_RUN_PATH.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {LAST_RUN_PATH}")


def main(argv: list[str] | None = None) -> int:
    """Run the deliberate-break smoke test (design D9).

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code: 0 when the D9.3 pass criterion holds for the
        selected runs, 1 otherwise.
    """
    parser = argparse.ArgumentParser(
        prog="python -m conformance.smoke.run_smoke",
        description="Deliberate-break smoke test over the conformance corpus (D9).",
    )
    parser.add_argument(
        "--patches",
        default=None,
        help="Comma-separated subset (e.g. 'S05,S07') for D9.3 re-runs; "
        "default runs all 13.",
    )
    parser.add_argument(
        "--skip-control",
        action="store_true",
        help="Skip the control run (subset re-runs only; full runs need it).",
    )
    parser.add_argument(
        "--ref",
        default="HEAD",
        help="Git ref for all worktrees (default: HEAD of this checkout).",
    )
    parser.add_argument(
        "--keep-worktrees",
        action="store_true",
        help="Leave /tmp worktrees in place for debugging (default: remove).",
    )
    args = parser.parse_args(argv)

    if args.patches is None:
        selected = list(PATCH_IDS)
    else:
        selected = [p.strip() for p in str(args.patches).split(",") if p.strip()]
        unknown = [p for p in selected if p not in PATCH_IDS]
        if unknown:
            parser.error(f"unknown patch ids: {unknown} (valid: {list(PATCH_IDS)})")

    resolved = _run(
        ["git", "rev-parse", args.ref],
        REPO_ROOT,
        timeout=60,
        capture_stdout=True,
    )
    if resolved.returncode != 0:
        print(f"cannot resolve ref {args.ref!r}", file=sys.stderr)
        return 1
    ref_sha = resolved.stdout.strip()
    print(f"smoke ref: {args.ref} = {ref_sha}")

    outcomes: list[RunOutcome] = []
    if not args.skip_control:
        print("== control run ==")
        outcomes.append(_execute_one("control", ref_sha, args.keep_worktrees))
        _print_table(outcomes)
    for patch_id in selected:
        print(f"== sabotage run {patch_id} ==")
        outcomes.append(_execute_one(patch_id, ref_sha, args.keep_worktrees))
        _print_table(outcomes[-1:])

    print("== smoke summary ==")
    _print_table(outcomes)

    flagged = [o.patch for o in outcomes if o.infrastructure_only]
    if flagged:
        # R9: an all-infrastructure-reason "catch" is not evidence of a
        # behavioral diff — surface it loudly without changing the D9.3
        # verdict (the flag rides last-run.json for the reviewer).
        print(
            "WARNING (R9): failure reasons are ALL replay-infrastructure "
            f"errors for: {', '.join(flagged)} — review these catches "
            "manually before trusting them."
        )

    control_ok = args.skip_control or any(
        o.patch == "control" and o.status == "clean" for o in outcomes
    )
    patches_ok = all(o.status == "caught" for o in outcomes if o.patch != "control")
    passed = control_ok and patches_ok

    full_run = not args.skip_control and selected == list(PATCH_IDS)
    if full_run:
        _write_last_run(ref_sha, outcomes, passed)
    else:
        print("partial run — last-run.json NOT written (full runs only)")

    print(f"smoke result: {'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
