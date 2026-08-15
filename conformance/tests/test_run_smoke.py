"""Unit tests for the smoke-run classifier (design D9 / GATE-VERDICT R9).

Covers the R9 infrastructure-only flag: a caught sabotage run whose
failure reasons are ALL runner-side ``replay infrastructure error inside
vector`` strings is flagged for manual review — such a "catch" proves
nothing about behavioral divergence (audit finding L2-F2).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from conformance.smoke.run_smoke import INFRA_REASON_PREFIX, _classify

_INFRA_REASON = "replay infrastructure error inside vector: RuntimeError: harness broke"
"""A reason string in the exact ``execute.run_vector`` infrastructure shape."""

_BEHAVIORAL_REASON = "output mismatch: expected 1 got 2"
"""A genuine behavioral-diff reason string."""


def _report(failures: list[dict[str, Any]]) -> dict[str, Any]:
    """Build a minimal runner JSON report around the given failures.

    Args:
        failures: The ``failures[]`` entries (id/kind/reasons dicts).

    Returns:
        A parsed-report dict in the shape ``conformance.runner`` emits.
    """
    return {
        "status": "vector_failed" if failures else "ok",
        "total": 10,
        "passed": 10 - len(failures),
        "failed": len(failures),
        "failures": failures,
        "runtime_seconds": 1.5,
    }


def test_caught_run_with_behavioral_reasons_not_flagged() -> None:
    """A catch backed by at least one behavioral diff is a real catch.

    Raises:
        AssertionError: If the flag fires despite behavioral reasons.
    """
    report = _report(
        [
            {"id": "a/b/c", "kind": "wire", "reasons": [_BEHAVIORAL_REASON]},
            {"id": "d/e/f", "kind": "builder", "reasons": [_INFRA_REASON]},
        ]
    )
    outcome = _classify("S01", 1, report, None)
    assert outcome.status == "caught"
    assert outcome.infrastructure_only is False


def test_caught_run_with_only_infra_reasons_is_flagged() -> None:
    """All-infrastructure failure reasons trigger the R9 review flag.

    Raises:
        AssertionError: If the flag does not fire.
    """
    report = _report(
        [
            {"id": "a/b/c", "kind": "wire", "reasons": [_INFRA_REASON]},
            {"id": "d/e/f", "kind": "builder", "reasons": [_INFRA_REASON]},
        ]
    )
    outcome = _classify("S02", 1, report, None)
    assert outcome.status == "caught"
    assert outcome.infrastructure_only is True


def test_clean_control_run_not_flagged() -> None:
    """A clean control run (no failures) never carries the flag.

    Raises:
        AssertionError: If a failure-free run is flagged.
    """
    outcome = _classify("control", 0, _report([]), None)
    assert outcome.status == "clean"
    assert outcome.infrastructure_only is False


def test_error_run_not_flagged() -> None:
    """Runner crashes stay ERROR (never a catch) and carry no flag.

    Raises:
        AssertionError: If the crash path is flagged or misclassified.
    """
    outcome = _classify("S03", 2, None, "corpus runner timed out")
    assert outcome.status == "error"
    assert outcome.infrastructure_only is False


def test_infra_prefix_matches_runner_source() -> None:
    """The R9 prefix constant must track the runner's literal reason string.

    ``execute.run_vector`` builds the infrastructure reason inline; if
    that wording drifts, the R9 flag silently never fires — this drift
    guard fails loudly instead.

    Raises:
        AssertionError: If the prefix no longer appears in
            ``conformance/runner/execute.py``.
    """
    from conformance.runner import execute

    source = Path(execute.__file__).read_text(encoding="utf-8")
    assert f'"{INFRA_REASON_PREFIX}' in source


def test_empty_reason_lists_do_not_vacuously_flag() -> None:
    """Failures with empty reason lists must not satisfy the flag vacuously.

    Raises:
        AssertionError: If ``all()`` over zero reasons flags the run.
    """
    report = _report([{"id": "a/b/c", "kind": "wire", "reasons": []}])
    outcome = _classify("S04", 1, report, None)
    assert outcome.status == "caught"
    assert outcome.infrastructure_only is False
