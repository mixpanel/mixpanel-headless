"""Pytest-free corpus-runner CLI (design D7/D9.3).

Usage:
    ```bash
    uv run python -m conformance.runner --vectors conformance/vectors \
        [--filter '<glob>'] [--report json]
    ```

Exit codes and report verdicts (design D9.3 — a crash is NEVER a catch):

- ``0`` — every selected vector passed (``status: "ok"``).
- ``1`` — >=1 vector executed and diffed red (``status: "vector_failed"``).
- ``2`` — the runner itself failed before/outside vector execution:
  missing dependency (freezegun), corpus load error, clock setup, harness
  bug (``status: "runner_crashed"``). The D9 smoke test treats any exit-2
  in any run as a smoke ERROR, distinct from both PASS and MISS.

The CLI is NOT dependency-free: it imports ``mixpanel_headless`` + ``httpx``
AND ``freezegun`` (dev extras) for the D1.4 clock shim — environments that
run it MUST ``uv sync --all-extras`` first (design D9.2 step 2). A missing
``freezegun`` fails fast with a clear ``runner_crashed`` report instead of
silently skipping the freeze.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def _report(payload: dict[str, Any], as_json: bool) -> None:
    """Write the final report to stdout.

    Args:
        payload: The report object.
        as_json: True for ``--report json`` (machine-readable, one
            document); False for a human-readable summary.
    """
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(
        f"[conformance.runner] status={payload['status']} "
        f"total={payload.get('total', 0)} passed={payload.get('passed', 0)} "
        f"failed={payload.get('failed', 0)} "
        f"runtime={payload.get('runtime_seconds', 0.0):.1f}s"
    )
    for failure in payload.get("failures", []):
        print(f"  FAIL {failure['id']}")
        for reason in failure["reasons"]:
            print(f"    - {reason}")
    if payload.get("error"):
        print(f"  ERROR: {payload['error']}")


def _crash(message: str, as_json: bool) -> int:
    """Emit a ``runner_crashed`` report and return exit code 2 (D9.3).

    Args:
        message: The infrastructure failure description.
        as_json: Report format flag.

    Returns:
        The exit code 2.
    """
    _report(
        {
            "status": "runner_crashed",
            "total": 0,
            "passed": 0,
            "failed": 0,
            "failures": [],
            "error": message,
        },
        as_json,
    )
    return 2


def main(argv: list[str] | None = None) -> int:
    """Run the corpus and print the report (design D7 CLI).

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code (0 pass / 1 vector_failed / 2 runner_crashed).
    """
    parser = argparse.ArgumentParser(
        prog="python -m conformance.runner",
        description="Replay the conformance-vector corpus against src/ (D7).",
    )
    parser.add_argument(
        "--vectors",
        required=True,
        type=Path,
        help="Corpus root directory (conformance/vectors).",
    )
    parser.add_argument(
        "--filter",
        default=None,
        help="fnmatch glob over vector ids (e.g. 'segmentation/*').",
    )
    parser.add_argument(
        "--report",
        choices=("json", "text"),
        default="text",
        help="Report format (json for the D9 smoke harness).",
    )
    args = parser.parse_args(argv)
    as_json = args.report == "json"
    try:
        import freezegun  # noqa: F401
    except ImportError:
        return _crash(
            "freezegun is not installed — the D1.4 replay clock shim cannot "
            "run. Bootstrap the environment with `uv sync --all-extras` "
            "(design D9.2 step 2).",
            as_json,
        )
    started = time.perf_counter()
    try:
        from conformance.record.clock import RecordClock
        from conformance.runner.execute import run_vector
        from conformance.runner.loading import CorpusLoadError, load_vectors

        try:
            vectors = load_vectors(args.vectors, args.filter)
        except CorpusLoadError as exc:
            return _crash(f"corpus load failed: {exc}", as_json)
        if not vectors:
            return _crash(
                f"no vectors matched under {args.vectors} (filter={args.filter!r})",
                as_json,
            )
        clock = RecordClock()
        clock.start()
        try:
            outcomes = []
            for vector in vectors:
                clock.reset_test_state()
                outcomes.append(run_vector(vector))
        finally:
            clock.stop()
    except Exception as exc:  # noqa: BLE001 - D9.3 crash boundary
        return _crash(f"{type(exc).__name__}: {exc}", as_json)
    runtime = time.perf_counter() - started
    failures = [
        {"id": outcome.id, "kind": outcome.kind, "reasons": outcome.reasons}
        for outcome in outcomes
        if not outcome.passed
    ]
    payload: dict[str, Any] = {
        "status": "vector_failed" if failures else "ok",
        "total": len(outcomes),
        "passed": len(outcomes) - len(failures),
        "failed": len(failures),
        "failures": failures,
        "error": None,
        "runtime_seconds": round(runtime, 3),
    }
    _report(payload, as_json)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
