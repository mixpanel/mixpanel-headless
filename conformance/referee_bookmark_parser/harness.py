"""bookmark_parser round-trip referee harness (design D15b, task PR-11).

Consumes the payload-handoff JSONL (one ``{"id", "bookmark_type",
"params"}`` object per line, produced by
:mod:`conformance.referee_bookmark_parser.handoff`) and drives the two
oracles that live in the READ-ONLY analytics checkout:

1. **structural** — ``bookmark_parser.validate.assert_valid_schema`` over
   the draft-04 ``common/schema/bookmark.json`` /
   ``funnels/schema/bookmark.json`` schemas (verdict = pass /
   ``jsonschema.exceptions.ValidationError``).
2. **deep** —
   ``analytics.bookmark_parser.insights.validate.
   validate_insights_bookmark_params_schema(params, require_all_keys=False)``
   (verdict = pass / ``voluptuous.error.MultipleInvalid``); insights
   payloads only.

This module is deliberately importable with the STDLIB ONLY — oracle
imports are lazy, resolved inside the recipe environments below, so the
repo test suite can unit-test the routing knowledge without the analytics
checkout mounted.

Invocation recipes (proven by recon transcripts in
``context/phase1/recon/referee-assets.md`` §1/§2A/§2B; run from the repo
root; NEVER write into the analytics checkout):

    ```bash
    # structural (draft-04) oracle
    PYTHONPATH=/Users/jaredmcfarland/Developer/analytics \
      uv run --no-project --with jsonschema==4.26.0 \
      python conformance/referee_bookmark_parser/harness.py \
      --oracle structural \
      --handoff conformance/referee_bookmark_parser/handoff.jsonl

    # deep insights (voluptuous) oracle
    PYTHONPATH=/Users/jaredmcfarland/Developer \
      uv run --no-project --with voluptuous==0.16.0 --with protobuf==7.35.1 \
      --with pandas==3.0.5 --with pytz==2026.3.post1 \
      python conformance/referee_bookmark_parser/harness.py \
      --oracle deep \
      --handoff conformance/referee_bookmark_parser/handoff.jsonl
    ```

Pinned wheel versions (resolved at the first scripted run, 2026-08-14,
per D15b — recon had left them "latest at run time", a listed risk):
``jsonschema==4.26.0`` (structural); ``voluptuous==0.16.0``,
``protobuf==7.35.1``, ``pandas==3.0.5``, ``pytz==2026.3.post1`` (deep).

Comparison rule (D15b): per-payload ACCEPT/REJECT verdicts per oracle,
never message equality. The deep validator is enum-loose on ``math`` (an
``Any()``/ALLOW_EXTRA branch — recon §2B ``bad-math-strict -> PASSED``),
so a deep ACCEPT is necessary-not-sufficient evidence. ``--selftest``
replays the recon positive/negative controls to prove the oracle wiring
is not vacuously green.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
import time
from collections.abc import Callable, Mapping
from functools import partial
from pathlib import Path
from typing import Any, cast

BOOKMARK_TYPES = frozenset({"insights", "funnels", "common"})
"""The D15b handoff ``bookmark_type`` vocabulary."""

COMMON_SCHEMA = "common/schema/bookmark.json"
"""Package-relative path of the draft-04 common bookmark schema."""

FUNNELS_SCHEMA = "funnels/schema/bookmark.json"
"""Package-relative path of the draft-04 funnels bookmark schema."""

HANDOFF_ROUTES: Mapping[str, str] = {
    "workspace.build_params": "insights",
    "bookmark_builders.build_time_section": "insights",
    "bookmark_builders.build_date_range": "common",
    "workspace.build_funnel_params": "funnels",
    "workspace.build_retention_params": "common",
    "workspace.build_flow_params": "common",
}
"""The bookmark-payload builder APIs fed to the referee and their types.

These are the six builder-kind registry entries whose outputs are bookmark
params (capabilities bookmarks/funnels/retention/flows); retention and
flows map to ``common`` because the analytics checkout ships no
retention/flows draft-04 schema (recon referee-assets.md §2 layout).
"""

_STRUCTURAL_REJECT = "jsonschema.exceptions.ValidationError"
"""Fully-qualified class whose raise means REJECT for the structural oracle."""

_DEEP_REJECT = "voluptuous.error.MultipleInvalid"
"""Fully-qualified class whose raise means REJECT for the deep oracle."""

_PINNED_WHEELS = {
    "structural": ("jsonschema",),
    "deep": ("voluptuous", "protobuf", "pandas", "pytz"),
}
"""Wheels whose resolved versions each oracle run records in its report."""


def wrap_payload(api: str, output: object) -> tuple[str, dict[str, object]]:
    """Wrap one builder output into a handoff ``(bookmark_type, params)``.

    Fragment builders are wrapped into the schema context that makes the
    structural check meaningful: ``build_date_range`` output becomes
    ``{"date_range": ...}`` (exactly the recon §2A probe shape) and
    ``build_time_section`` output becomes ``{"sections": {"time": ...}}``.
    Full-payload builders pass through unchanged.

    Args:
        api: The registry API name of the builder.
        output: The builder's canonical-JSON output value.

    Returns:
        The ``(bookmark_type, params)`` pair for the handoff entry.

    Raises:
        ValueError: If ``api`` is not a bookmark-payload builder, or the
            wrapped payload is not a JSON object (schemas have object
            roots — anything else is a producer bug, not a finding).
    """
    bookmark_type = HANDOFF_ROUTES.get(api)
    if bookmark_type is None:
        raise ValueError(f"{api!r} is not a bookmark-payload builder API")
    params: object = output
    if api == "bookmark_builders.build_date_range":
        params = {"date_range": output}
    elif api == "bookmark_builders.build_time_section":
        params = {"sections": {"time": output}}
    if not isinstance(params, dict):
        raise ValueError(
            f"{api!r} handoff params must be a JSON object, got {type(params).__name__}"
        )
    return bookmark_type, cast("dict[str, object]", params)


def _show_clauses(params: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Extract the ``sections.show`` clause objects from a payload.

    Args:
        params: The handoff params object.

    Returns:
        The list of show-clause mappings (empty when absent or malformed
        — dialect detection must never crash on odd payloads).
    """
    sections = params.get("sections")
    if not isinstance(sections, Mapping):
        return []
    show = sections.get("show")
    if not isinstance(show, list):
        return []
    return [clause for clause in show if isinstance(clause, Mapping)]


def detect_dialect(params: Mapping[str, object]) -> str:
    """Classify a payload's show-clause dialect (D15b dialect rule).

    Modern nested clauses carry ``behavior``/``measurement`` sub-objects;
    legacy flat clauses carry ``math``/``value`` at the top level, and
    legacy flat report params (flows, pre-migration funnels) carry
    top-level ``steps``.

    Args:
        params: The handoff params object.

    Returns:
        ``"modern-nested"``, ``"legacy-flat"``, ``"mixed"`` (both clause
        shapes present — flagged, never guessed), or ``"neutral"`` (no
        dialect-bearing structure).
    """
    modern = False
    legacy = "steps" in params
    for clause in _show_clauses(params):
        if "behavior" in clause or "measurement" in clause:
            modern = True
        elif "math" in clause or "value" in clause:
            legacy = True
    if modern and legacy:
        return "mixed"
    if modern:
        return "modern-nested"
    if legacy:
        return "legacy-flat"
    return "neutral"


def structural_schema_for(bookmark_type: str, params: Mapping[str, object]) -> str:
    """Pick the draft-04 schema for one payload (D15b routing).

    The funnels schema REQUIRES the legacy flat ``steps`` array, so it only
    applies to legacy-dialect funnel params; modern sections-dialect funnel
    payloads fall back to the common schema (its allOf-common layer) —
    feeding them to the funnels schema would reject correct library output,
    the same dead-weight trap D15a documents for ajv.

    Args:
        bookmark_type: The handoff ``bookmark_type`` value.
        params: The handoff params object.

    Returns:
        The package-relative schema path for
        ``bookmark_parser.validate.assert_valid_schema``.

    Raises:
        ValueError: If ``bookmark_type`` is outside the D15b vocabulary.
    """
    if bookmark_type not in BOOKMARK_TYPES:
        raise ValueError(f"unknown bookmark_type {bookmark_type!r}")
    if bookmark_type == "funnels" and "steps" in params:
        return FUNNELS_SCHEMA
    return COMMON_SCHEMA


class HarnessError(Exception):
    """Raised for harness-level failures (bad handoff, oracle import).

    Distinct from a REJECT verdict: a ``HarnessError`` means the referee
    could not run, mirroring the D9.3 crash-is-never-a-catch rule.
    """


def _class_name(exc: BaseException) -> str:
    """Return an exception's fully-qualified class name.

    Args:
        exc: The raised exception.

    Returns:
        ``module.QualName`` for cross-environment class matching (the
        oracle wheels are not importable in the repo environment, so
        verdict classification matches names, never classes).
    """
    return f"{type(exc).__module__}.{type(exc).__qualname__}"


def _first_line(exc: BaseException) -> str:
    """Render a one-line summary of an oracle rejection.

    Args:
        exc: The validation error raised by an oracle.

    Returns:
        The first line of ``str(exc)``, truncated for report hygiene.
    """
    return str(exc).split("\n", 1)[0][:200]


def normalize_reject_error(exc: BaseException) -> str:
    """Render a deterministic one-line representation of a REJECT error.

    ``voluptuous.error.MultipleInvalid`` aggregates equally-ranked
    sub-errors (e.g. the two missing required keys on one filter clause) in
    nondeterministic order, and ``str(exc)`` shows only the first — so raw
    first-line recording churned the committed deep-run artifact across
    identical runs (GATE-VERDICT L5-F1 / recommendation R11). When the
    error carries a ``.errors`` list of exceptions (duck-typed: the oracle
    wheels are not importable in the repo environment), ALL sub-error first
    lines are recorded, deduplicated and sorted; otherwise the plain first
    line is used.

    Args:
        exc: The validation error raised by an oracle.

    Returns:
        The normalized error string — invariant under sub-error ordering,
        so artifact diffs reflect only real verdict changes.
    """
    sub_errors = getattr(exc, "errors", None)
    if (
        isinstance(sub_errors, list)
        and sub_errors
        and all(isinstance(sub, BaseException) for sub in sub_errors)
    ):
        return "; ".join(sorted({_first_line(sub) for sub in sub_errors}))
    return _first_line(exc)


def _resolved_versions(oracle: str) -> dict[str, str]:
    """Record the wheel versions the current environment resolved.

    Args:
        oracle: ``"structural"`` or ``"deep"``.

    Returns:
        Mapping of distribution name to installed version (``"missing"``
        when the distribution is absent — the run will fail loudly at
        import time anyway).
    """
    from importlib import metadata

    versions: dict[str, str] = {}
    for dist in _PINNED_WHEELS[oracle]:
        try:
            versions[dist] = metadata.version(dist)
        except metadata.PackageNotFoundError:
            versions[dist] = "missing"
    return versions


def _load_structural_oracle() -> Callable[[Mapping[str, object], str], None]:
    """Import the draft-04 structural oracle from the analytics checkout.

    Returns:
        ``bookmark_parser.validate.assert_valid_schema`` (returns ``None``
        on success, raises ``jsonschema.exceptions.ValidationError``).

    Raises:
        HarnessError: When the import fails (PYTHONPATH recipe not
            followed, or the analytics checkout is absent).
    """
    try:
        module = importlib.import_module("bookmark_parser.validate")
    except ImportError as exc:
        raise HarnessError(
            "cannot import bookmark_parser.validate — run via the recipe "
            "PYTHONPATH=/Users/jaredmcfarland/Developer/analytics "
            f"uv run --no-project --with jsonschema==4.26.0 ... ({exc})"
        ) from exc
    # getattr on a dynamically imported module is untyped by nature; the
    # signature is pinned by recon referee-assets.md §2 and the cast is the
    # single justified Any-boundary in this harness.
    return cast(
        "Callable[[Mapping[str, object], str], None]",
        module.assert_valid_schema,
    )


def _load_deep_oracle() -> Callable[[Mapping[str, object]], None]:
    """Import the deep voluptuous insights oracle from analytics.

    Returns:
        A closure over
        ``validate_insights_bookmark_params_schema(params,
        require_all_keys=False)`` (raises
        ``voluptuous.error.MultipleInvalid`` on failure).

    Raises:
        HarnessError: When the import fails (PYTHONPATH recipe not
            followed, or a required wheel is missing).
    """
    try:
        module = importlib.import_module("analytics.bookmark_parser.insights.validate")
    except ImportError as exc:
        raise HarnessError(
            "cannot import analytics.bookmark_parser.insights.validate — run "
            "via the recipe PYTHONPATH=/Users/jaredmcfarland/Developer "
            "uv run --no-project --with voluptuous==0.16.0 --with "
            f"protobuf==7.35.1 --with pandas==3.0.5 --with pytz==2026.3.post1 ... ({exc})"
        ) from exc
    validate = cast(
        "Callable[..., object]",
        module.validate_insights_bookmark_params_schema,
    )

    def _run(params: Mapping[str, object]) -> None:
        """Validate one insights payload with ``require_all_keys=False``.

        Args:
            params: The handoff params object.

        Raises:
            voluptuous.error.MultipleInvalid: On validation failure.
        """
        validate(params, require_all_keys=False)

    return _run


def load_handoff(path: Path) -> list[dict[str, object]]:
    """Load and validate the payload-handoff JSONL.

    Args:
        path: The handoff file path.

    Returns:
        The handoff entries in file order.

    Raises:
        HarnessError: On unreadable files, malformed JSON, wrong entry
            shape, duplicate ids, or unknown ``bookmark_type`` values.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise HarnessError(f"cannot read handoff file {path}: {exc}") from exc
    entries: list[dict[str, object]] = []
    seen: set[str] = set()
    for lineno, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError as exc:
            raise HarnessError(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        if not isinstance(entry, dict) or set(entry) != {
            "id",
            "bookmark_type",
            "params",
        }:
            raise HarnessError(
                f"{path}:{lineno}: entry must be exactly "
                '{"id", "bookmark_type", "params"}'
            )
        entry_id = entry["id"]
        bookmark_type = entry["bookmark_type"]
        if not isinstance(entry_id, str) or entry_id in seen:
            raise HarnessError(f"{path}:{lineno}: missing or duplicate id")
        if bookmark_type not in BOOKMARK_TYPES:
            raise HarnessError(
                f"{path}:{lineno}: unknown bookmark_type {bookmark_type!r}"
            )
        if not isinstance(entry["params"], dict):
            raise HarnessError(f"{path}:{lineno}: params must be a JSON object")
        seen.add(entry_id)
        entries.append(cast("dict[str, object]", entry))
    if not entries:
        raise HarnessError(f"handoff file {path} contains no entries")
    return entries


def _judge(
    check: Callable[[], None], reject_class: str, oracle: str
) -> tuple[str, str | None]:
    """Run one oracle call and classify the outcome.

    Args:
        check: Zero-arg closure performing the validation call.
        reject_class: Fully-qualified exception class meaning REJECT.
        oracle: Oracle name (for crash diagnostics).

    Returns:
        ``("ACCEPT", None)`` or ``("REJECT", normalized-error)`` — the
        error rendered via :func:`normalize_reject_error` so committed
        artifacts stay deterministic across runs (R11).

    Raises:
        HarnessError: When the oracle raises anything OTHER than its
            documented rejection class (that is an oracle/harness crash,
            never a verdict — D9.3 discipline).
    """
    try:
        check()
    except Exception as exc:
        if _class_name(exc) == reject_class:
            return "REJECT", normalize_reject_error(exc)
        raise HarnessError(
            f"{oracle} oracle crashed with {_class_name(exc)}: {_first_line(exc)}"
        ) from exc
    return "ACCEPT", None


def run_structural(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Run the structural draft-04 oracle over every handoff entry.

    Args:
        entries: The loaded handoff entries.

    Returns:
        Per-entry result rows ``{id, bookmark_type, dialect, schema,
        verdict, error}``.

    Raises:
        HarnessError: On oracle import failure or non-verdict crashes.
    """
    assert_valid_schema = _load_structural_oracle()
    results: list[dict[str, object]] = []
    for entry in entries:
        params = cast("Mapping[str, object]", entry["params"])
        bookmark_type = str(entry["bookmark_type"])
        schema = structural_schema_for(bookmark_type, params)
        verdict, error = _judge(
            partial(assert_valid_schema, params, schema),
            _STRUCTURAL_REJECT,
            "structural",
        )
        results.append(
            {
                "id": entry["id"],
                "bookmark_type": bookmark_type,
                "dialect": detect_dialect(params),
                "schema": schema,
                "verdict": verdict,
                "error": error,
            }
        )
    return results


def run_deep(entries: list[dict[str, object]]) -> list[dict[str, object]]:
    """Run the deep voluptuous insights oracle over the handoff.

    Only ``bookmark_type == "insights"`` entries are validated — the deep
    oracle models insights bookmark params exclusively; funnels/common
    entries are recorded as ``SKIP_NON_INSIGHTS``. Both show-clause
    dialects are fed: the voluptuous ``Any(...)`` union models the modern
    multi-metric clause alongside the legacy flat clause (verified
    empirically at pin time; recon §2B documents the legacy shape and the
    ALLOW_EXTRA looseness that makes ACCEPT necessary-not-sufficient).

    Args:
        entries: The loaded handoff entries.

    Returns:
        Per-entry result rows ``{id, bookmark_type, dialect, verdict,
        error}``.

    Raises:
        HarnessError: On oracle import failure or non-verdict crashes.
    """
    deep = _load_deep_oracle()
    results: list[dict[str, object]] = []
    for entry in entries:
        params = cast("Mapping[str, object]", entry["params"])
        bookmark_type = str(entry["bookmark_type"])
        dialect = detect_dialect(params)
        if bookmark_type != "insights":
            verdict, error = "SKIP_NON_INSIGHTS", None
        else:
            verdict, error = _judge(partial(deep, params), _DEEP_REJECT, "deep")
        results.append(
            {
                "id": entry["id"],
                "bookmark_type": bookmark_type,
                "dialect": dialect,
                "verdict": verdict,
                "error": error,
            }
        )
    return results


_SELFTEST_DATE_RANGE = {
    "date_range": {
        "type": "in the last",
        "from_date": {"unit": "day", "value": 30},
        "to_date": {"unit": "day", "value": 0},
        "window": {"unit": "day", "value": 30},
    }
}
"""Recon §2A positive control for the structural oracle."""

_SELFTEST_LEGACY_INSIGHTS = {
    "sections": {
        "show": [
            {
                "math": "total",
                "resourceType": "events",
                "value": {"name": "Login", "resourceType": "events"},
            }
        ],
        "time": [
            {
                "dateRangeType": "in the last",
                "unit": "day",
                "window": {"unit": "day", "value": 30},
            }
        ],
    },
    "displayOptions": {
        "chartType": "line",
        "plotStyle": "standard",
        "analysis": "linear",
        "value": "absolute",
    },
}
"""Recon §2B positive control for the deep oracle (legacy flat dialect)."""


def _with_patch(base: Mapping[str, object], path: list[object], value: object) -> Any:
    """Deep-copy a control payload and patch one nested value.

    Args:
        base: The control payload to copy.
        path: Key/index path to the patched location.
        value: The replacement value.

    Returns:
        The patched deep copy (``Any`` because the mutation walk is
        structurally untyped by design — selftest fixtures only).
    """
    clone: Any = json.loads(json.dumps(base))
    node: Any = clone
    for key in path[:-1]:
        node = node[key]
    node[path[-1]] = value
    return clone


def run_selftest(oracle: str) -> list[dict[str, object]]:
    """Replay the recon positive/negative controls for one oracle.

    Proves the oracle wiring is not vacuously green: a broken PYTHONPATH,
    schema path, or exception mapping fails these controls before any
    corpus verdict is trusted.

    Args:
        oracle: ``"structural"`` or ``"deep"``.

    Returns:
        Control rows ``{control, expected, verdict, error, ok}``.

    Raises:
        HarnessError: On oracle import failure or non-verdict crashes.
    """
    checks: list[tuple[str, str, Callable[[], None]]]
    if oracle == "structural":
        validate = _load_structural_oracle()
        bad_unit = _with_patch(
            _SELFTEST_DATE_RANGE, ["date_range", "window", "unit"], "fortnight"
        )
        checks = [
            (
                "date-range-valid",
                "ACCEPT",
                lambda: validate(_SELFTEST_DATE_RANGE, COMMON_SCHEMA),
            ),
            (
                "date-range-bad-unit",
                "REJECT",
                lambda: validate(cast("Mapping[str, object]", bad_unit), COMMON_SCHEMA),
            ),
            (
                "funnels-missing-steps",
                "REJECT",
                lambda: validate({"date_range": {"type": "between"}}, FUNNELS_SCHEMA),
            ),
        ]
        reject_class = _STRUCTURAL_REJECT
    else:
        deep = _load_deep_oracle()
        bad_time = _with_patch(
            _SELFTEST_LEGACY_INSIGHTS, ["sections", "time", 0, "unit"], "fortnight"
        )
        bad_show = _with_patch(
            _SELFTEST_LEGACY_INSIGHTS, ["sections", "show"], "not-a-list"
        )
        loose_math = _with_patch(
            _SELFTEST_LEGACY_INSIGHTS, ["sections", "show", 0, "math"], "NOT_A_MATH"
        )
        checks = [
            (
                "legacy-minimal",
                "ACCEPT",
                lambda: deep(_SELFTEST_LEGACY_INSIGHTS),
            ),
            ("bad-time-unit", "REJECT", lambda: deep(bad_time)),
            ("show-not-a-list", "REJECT", lambda: deep(bad_show)),
            # Documents the recon §2B looseness: the multi-metric
            # ALLOW_EXTRA branch swallows an invalid math enum, which is
            # WHY a deep ACCEPT is necessary-not-sufficient.
            ("bad-math-loose", "ACCEPT", lambda: deep(loose_math)),
        ]
        reject_class = _DEEP_REJECT
    rows: list[dict[str, object]] = []
    for name, expected, check in checks:
        verdict, error = _judge(check, reject_class, oracle)
        rows.append(
            {
                "control": name,
                "expected": expected,
                "verdict": verdict,
                "error": error,
                "ok": verdict == expected,
            }
        )
    return rows


def _summarize(results: list[dict[str, object]]) -> dict[str, int]:
    """Tally verdicts for the report header.

    Args:
        results: Per-entry result rows.

    Returns:
        ``{"accepted", "rejected", "skipped"}`` counts.
    """
    return {
        "accepted": sum(1 for r in results if r["verdict"] == "ACCEPT"),
        "rejected": sum(1 for r in results if r["verdict"] == "REJECT"),
        "skipped": sum(1 for r in results if str(r["verdict"]).startswith("SKIP")),
    }


def main(argv: list[str] | None = None) -> int:
    """Run the referee batch (or selftest) and emit the JSON report.

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        Process exit code — ``0`` all ACCEPT (skips allowed) / selftest
        controls all as expected; ``1`` any REJECT or failed control (a
        reject over corpus payloads is a REAL finding — escalate, per
        D18 PR-11); ``2`` harness crash (bad handoff, oracle import
        failure, unexpected oracle exception).
    """
    parser = argparse.ArgumentParser(
        prog="harness.py",
        description="bookmark_parser round-trip referee (design D15b).",
    )
    parser.add_argument(
        "--oracle",
        required=True,
        choices=("structural", "deep"),
        help="Which analytics-side oracle to drive.",
    )
    parser.add_argument(
        "--handoff",
        type=Path,
        default=None,
        help="Payload-handoff JSONL (required unless --selftest).",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="Replay the recon positive/negative controls instead of a batch.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Also write the JSON report to this path.",
    )
    args = parser.parse_args(argv)
    started = time.perf_counter()
    report: dict[str, object] = {
        "oracle": args.oracle,
        "mode": "selftest" if args.selftest else "batch",
        "python": sys.version.split()[0],
        "resolved_versions": _resolved_versions(args.oracle),
        "caveats": [
            "deep ACCEPT is necessary-not-sufficient: the voluptuous "
            "schema is enum-loose on math via an Any()/ALLOW_EXTRA branch "
            "(recon referee-assets.md §2B)",
            "draft-04 schemas hardcode only 2 levels of filter-group "
            "nesting; deeper trees pass unvalidated (D15b)",
        ],
    }
    try:
        if args.selftest:
            controls = run_selftest(args.oracle)
            report["controls"] = controls
            failed = sum(1 for row in controls if not row["ok"])
            report["status"] = "ok" if failed == 0 else "control_failed"
            exit_code = 0 if failed == 0 else 1
        else:
            if args.handoff is None:
                raise HarnessError("--handoff is required unless --selftest")
            entries = load_handoff(args.handoff)
            results = (
                run_structural(entries)
                if args.oracle == "structural"
                else run_deep(entries)
            )
            summary = _summarize(results)
            report.update(summary)
            report["total"] = len(results)
            report["results"] = results
            report["status"] = "ok" if summary["rejected"] == 0 else "rejected"
            exit_code = 0 if summary["rejected"] == 0 else 1
    except HarnessError as exc:
        report["status"] = "harness_crashed"
        report["error"] = str(exc)
        exit_code = 2
    report["runtime_seconds"] = round(time.perf_counter() - started, 3)
    rendered = json.dumps(report, indent=2, sort_keys=True)
    print(rendered)
    if args.out is not None:
        args.out.write_text(rendered + "\n", encoding="utf-8")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
