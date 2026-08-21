# Implementation Plan: Write-Time Size-Limit Enforcement

**Branch**: `msiebert-agent-memory` (slice `047-write-time-size-limits`) | **Date**: 2026-08-20 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/047-write-time-size-limits/spec.md`
**Linear**: AIE-605

## Summary

Enforce a single per-file byte ceiling — **8 KiB (8,192 bytes), locked** — on
every Headless Memory write, on top of the AIE-603 storage foundation
(`LocalFilesystemBackend`) and the AIE-604 entry format
(`MemoryEntry`/`format.py`). The guard lives at the one choke point every
write primitive funnels through today, `LocalFilesystemBackend.write`, so it
cannot be bypassed by a different call path and is inherited automatically by
any future write primitive built on top. A new pure module,
`_internal/memory/limits.py`, holds the constant, a typed
`MemorySizeLimitError(ValueError)` carrying the rejected size and the ceiling,
and the size-check logic itself — split out exactly like `format.py` was split
from `backend.py` in 046, so the pure comparison is an isolated unit-, PBT-,
and mutmut-testable target. The check runs before any filesystem syscall, so
rejection is atomic by construction: no directory is created, no tmp file is
opened, and an existing file at the target key is left byte-for-byte
unchanged.

## Technical Context

**Language/Version**: Python 3.10+ (mypy --strict)
**Primary Dependencies**: Standard library only (`dataclasses` not required
here — this slice adds no new record type). No new third-party dependency.
Consumes the existing `_internal/io_utils.py::atomic_write_bytes` and the
AIE-603 `backend.py`/`paths.py` foundation unchanged except for the one new
guard statement in `write()`.
**Storage**: Plain files on the local filesystem under a resolved storage
root (unchanged from 045/046 — `LocalFilesystemBackend` bound to a scope
directory). This slice adds no new on-disk shape; it only bounds the size of
what may be written.
**Testing**: pytest; Hypothesis (PBT on boundary sizes — zero, one under, at,
one over, and arbitrarily-larger-than the ceiling — `_pbt` suffix); mutmut
(mutation testing on the pure `check_write_size` logic, target ≥80% per
spec SC-005).
**Target Platform**: POSIX primary; the size check itself is
platform-independent (a `len(bytes)` comparison). The enforcement point
(`LocalFilesystemBackend.write`) is the same POSIX-first implementation as
045/046.
**Project Type**: Single Python library (`mixpanel_headless`) — internal
infrastructure layer only in this slice.
**Performance Goals**: Not a hot path; the added check is a single `len()`
call and integer comparison — O(1) beyond the existing O(n) cost of holding
`data` in memory, which every caller already pays. No specific latency
target.
**Constraints**: ≥90% coverage; mutmut ≥80% on `limits.py`'s pure
`check_write_size`; mypy --strict; full Google-style docstrings; no `Any`
without justification; `limits.py` must be free of filesystem/network I/O,
matching `format.py`'s discipline.
**Scale/Scope**: One new `_internal/memory/` module (`limits.py`, ~3 symbols:
constant, exception, function) and a one-line change to
`LocalFilesystemBackend.write` in `backend.py`. Every write in practice is a
small markdown note; the ceiling is a safety bound, not an expected operating
point.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Library-First | ✅ PASS | The guard lives in the Python library (`_internal/memory/limits.py` + `backend.py`); no CLI in this slice. Tool verbs (AIE-608) inherit it automatically by delegating to `write()`. |
| II. Agent-Native Design | ✅ PASS | `MemorySizeLimitError` is a typed, catchable exception with structured `size`/`limit` int fields — no prompts, no string-matching required, matching the project's structured-error posture. |
| III. Context Window Efficiency | ✅ PASS | The ceiling itself protects context-window economy indirectly (a runaway note can't balloon into an unreadable blob); the check adds no new data the caller must read. |
| IV. Two Data Paths | ➖ N/A | Memory writes are neither a live query nor a DuckDB analysis path; orthogonal, as in 045/046. |
| V. Explicit Over Implicit | ✅ PASS | The guard NEVER silently truncates (FR-005) — an oversized write fails loudly with a typed error rather than being quietly clipped to fit. The ceiling is one explicit constant, not an inferred or configurable-by-accident value. |
| VI. Unix Philosophy | ✅ PASS | One small thing (a size guard) behind a pure seam (`limits.py`), analogous to `format.py`; composes cleanly with any future CLI's `--jq`-friendly error reporting since `size`/`limit` are plain ints. |
| VII. Secure by Default | ✅ PASS | No credentials, no new logging of content. The guard is a defense against unbounded disk growth from a single file, complementing (not duplicating) `MAX_CREDENTIAL_BYTES`'s unrelated read-side threat model. |

**Gate result: PASS** (no deviations — Complexity Tracking is empty for this slice).

## Project Structure

### Documentation (this feature)

```text
specs/047-write-time-size-limits/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/            # Phase 1 output (internal module contracts)
│   └── memory_write_size_limit.md
├── checklists/
└── tasks.md              # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/mixpanel_headless/_internal/memory/
├── __init__.py          # EDIT — export MAX_MEMORY_WRITE_BYTES, MemorySizeLimitError, check_write_size
├── paths.py             # UNCHANGED (from 045)
├── entry.py             # UNCHANGED (from 046)
├── format.py            # UNCHANGED (from 046) — this slice does not touch entry serialization
├── backend.py           # EDIT — LocalFilesystemBackend.write() calls check_write_size(data) first
└── limits.py            # NEW — MAX_MEMORY_WRITE_BYTES + MemorySizeLimitError + check_write_size (pure, PBT/mutmut target)

tests/
├── unit/
│   ├── test_memory_limits.py        # NEW — check_write_size boundary behavior, MemorySizeLimitError shape
│   └── test_memory_backend.py       # EDIT — write() rejects oversized content atomically (fresh + overwrite cases)
└── pbt/
    └── test_memory_limits_pbt.py    # NEW — Hypothesis boundary-size invariants on check_write_size
```

**Structure Decision**: Single-library layout, unchanged from 045/046. The
new pure logic is confined to one new file, `limits.py`, kept separate from
`backend.py` so the ≥80% mutmut bar applies to a small, I/O-free module — the
same pure/IO discipline 045 applied to `paths.py`/`backend.py` and 046 applied
to `format.py`/`backend.py`. `backend.py` itself changes by exactly one
guard statement in `write()`; no new integration test tier is needed beyond
the existing `test_memory_backend.py`, since the behavior under test is a
single method's raising/non-raising contract against a real temp-directory
filesystem, already the pattern that file uses today.

## Complexity Tracking

*No constitution violations — this slice introduces no deviations. Table intentionally empty.*

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| — | — | — |

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 0 (research.md) and Phase 1 (data-model.md, contracts/, quickstart.md) were drafted.*

The design that emerged — one new pure module (`limits.py`) holding a
constant, a `ValueError`-subclassed typed exception, and a single `len()`
comparison, plus a one-statement addition to the existing `write()` choke
point — introduces no new architectural surface, no new dependency, and no
new I/O path. Every gate evaluated above still holds under the concrete
design:

| Principle | Status | Post-design confirmation |
|-----------|--------|---------------------------|
| I. Library-First | ✅ PASS | `limits.py` is a plain internal module; nothing added to `cli/`. |
| II. Agent-Native Design | ✅ PASS | `MemorySizeLimitError.size`/`.limit` are the structured fields; no message-parsing required, confirmed in the contract's behavioral table. |
| III. Context Window Efficiency | ✅ PASS | No change — the guard adds no data to any read path. |
| IV. Two Data Paths | ➖ N/A | Unchanged. |
| V. Explicit Over Implicit | ✅ PASS | Confirmed by the contract's ordering guarantee (D6 in research.md): the check strictly precedes any I/O, so rejection is atomic by construction, never a partial/truncated write. |
| VI. Unix Philosophy | ✅ PASS | `limits.py` does exactly one thing; `backend.py` composes it with one call. |
| VII. Secure by Default | ✅ PASS | No credential material touched; the guard's constant is unrelated to and does not weaken `MAX_CREDENTIAL_BYTES`. |

**Gate result: PASS.** No new violations surfaced during design; Complexity
Tracking remains empty.
