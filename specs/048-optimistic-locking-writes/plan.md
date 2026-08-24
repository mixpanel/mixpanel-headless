# Implementation Plan: Optimistic-Locking Concurrency for Memory Writes

**Branch**: `msiebert-agent-memory` (slice `048-optimistic-locking-writes`) | **Date**: 2026-08-21 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/048-optimistic-locking-writes/spec.md`
**Linear**: AIE-606

## Summary

Guard the Headless Memory read-modify-write cycle against concurrent
writers with an optimistic-locking primitive, on top of the AIE-603 storage
foundation (`LocalFilesystemBackend`), the AIE-604 entry format
(`MemoryEntry`/`format.py`), and the AIE-605 write-time size guard
(`limits.py`/`check_write_size`). A new pure module,
`_internal/memory/locking.py`, holds a whole-file `sha256` content
fingerprint (with a type-distinct absence sentinel), a common
`MemoryLockingError` base plus two sibling typed errors —
`MemoryConflictError` for a single attempt's stale-fingerprint detection and
`MemoryConflictRetriesExhaustedError` for the retrying helper's bounded-
budget exhaustion — and the retry-policy constants (5 total attempts,
full-jitter backoff, base 10-20 ms). Two new methods land on
`LocalFilesystemBackend` (`read_with_fingerprint`, `write_if_match`) plus one
new module-level helper (`write_with_retry`) that composes them into an
automatic read-mutate-write-retry loop. The change is purely additive: the
existing unguarded `write()` method, its guarantees, and the AIE-605 size
guard it already calls are untouched — every new symbol is a new call path
layered alongside them, not a replacement.

## Technical Context

**Language/Version**: Python 3.10+ (mypy --strict)
**Primary Dependencies**: Standard library only — `hashlib` (whole-file
`sha256`), `random` (full-jitter backoff delay), `time` (sleeping between
retry attempts). No new third-party dependency. Consumes the existing
`_internal/io_utils.py::atomic_write_bytes`, the AIE-603
`backend.py`/`paths.py` foundation, and the AIE-605 `limits.py`'s
`check_write_size`/`MAX_MEMORY_WRITE_BYTES` — all unchanged.
**Storage**: Plain files on the local filesystem under a resolved storage
root (unchanged from 045/046/047 — `LocalFilesystemBackend` bound to a scope
directory). This slice adds no new on-disk shape and no new persisted
metadata; the content fingerprint is computed in-memory per attempt and
never written to disk.
**Testing**: pytest; Hypothesis (PBT on fingerprint equality/inequality
across arbitrary byte payloads, on the backoff-delay distribution, and — the
slice's required concurrency invariant, SC-002/SC-003/SC-005 — on
interleaved read/write/retry sequences that must always either succeed
within budget or raise the exhaustion error, never hang; `_pbt` suffix);
mutmut (mutation testing on the pure fingerprint/retry-decision logic in
`locking.py`, target ≥80% per spec SC-005).
**Target Platform**: POSIX primary; the fingerprint and retry-decision
logic is platform-independent (`hashlib.sha256` + comparisons + a bounded
`random.random()` call). The enforcement points (`read_with_fingerprint`,
`write_if_match`) are the same POSIX-first implementation as 045/046/047's
`read`/`write`.
**Project Type**: Single Python library (`mixpanel_headless`) — internal
infrastructure layer only in this slice.
**Performance Goals**: Not a hot path. An uncontested guarded write costs
one extra `sha256` over data already resident in memory (O(n) in payload
size, bounded by the AIE-605 8 KiB ceiling, so effectively O(1) in practice)
plus the existing read/write cost. A contended write costs at most 5
attempts x (one `sha256` + a bounded `[0, 15ms)` sleep) — worst-case
additional latency well under 100ms, and only on the rare contended path.
**Constraints**: ≥90% coverage; mutmut ≥80% on `locking.py`'s pure
`fingerprint_of`/`next_backoff_delay`/error-construction logic; mypy
--strict; full Google-style docstrings; no `Any` without justification;
`locking.py` must be free of filesystem/network I/O apart from `time.sleep`
(the one intentional exception, isolated to `write_with_retry`'s loop body,
not to any function `mutmut`/PBT targets for pure logic), matching
`limits.py`'s discipline.
**Scale/Scope**: One new `_internal/memory/` module (`locking.py`, ~8
symbols: `Fingerprint` alias, 2 constants, `fingerprint_of`,
`next_backoff_delay`, 2 exception classes, `write_with_retry`) and two new
methods added to `LocalFilesystemBackend` in `backend.py`
(`read_with_fingerprint`, `write_if_match`) plus one new method added to the
`MemoryBackend` protocol for each. Every guarded write in practice targets
the same small markdown notes AIE-605 already bounds; contention is
expected to be rare (an agent session and a background curator, or two
agent sessions, colliding within milliseconds), not the common case.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Library-First | ✅ PASS | The guard lives in the Python library (`_internal/memory/locking.py` + additive `backend.py` methods); no CLI in this slice. Tool verbs (AIE-608) inherit it automatically by delegating to `write_with_retry`/`write_if_match`. |
| II. Agent-Native Design | ✅ PASS | `MemoryConflictError` and `MemoryConflictRetriesExhaustedError` are typed, catchable exceptions with structured `key`/`expected`/`actual`/`attempts`/`last_conflict` fields — no prompts, no string-matching required, matching the project's structured-error posture and the `MemorySizeLimitError` precedent. |
| III. Context Window Efficiency | ✅ PASS | The guard adds no new data an agent must read; a caller of `write_with_retry` sees only success or one typed exception, never a growing retry log it has to parse. |
| IV. Two Data Paths | ➖ N/A | Memory writes are neither a live query nor a DuckDB analysis path; orthogonal, as in 045/046/047. |
| V. Explicit Over Implicit | ✅ PASS | A conflict is NEVER silently resolved by picking a winner arbitrarily or discarding a writer's intent without signal (FR-003); the retrying helper's behavior — bounded attempts, jittered delay, a named exhaustion error — is fully explicit, named constants, not inferred or configurable-by-accident. |
| VI. Unix Philosophy | ✅ PASS | One small thing (fingerprint compare + bounded retry) behind a pure seam (`locking.py`), analogous to `limits.py`; composes cleanly with the existing `write()`/`check_write_size` chain rather than duplicating either. |
| VII. Secure by Default | ✅ PASS | No credentials, no new logging of content (fingerprints are hash digests, not raw bytes, and error messages avoid embedding raw digest bytes per the data-model's message convention). The guard is a correctness feature (lost-update prevention), unrelated to and non-weakening of the AIE-605 size guard or the symlink/owner-only-mode read-side protections. |

**Gate result: PASS** (no deviations — Complexity Tracking is empty for this slice).

## Project Structure

### Documentation (this feature)

```text
specs/048-optimistic-locking-writes/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md         # Phase 1 output
├── contracts/            # Phase 1 output (internal module contracts)
│   └── locking_optimistic_write.md
├── checklists/
└── tasks.md              # Phase 2 output (/speckit.tasks — NOT created here)
```

### Source Code (repository root)

```text
src/mixpanel_headless/_internal/memory/
├── __init__.py          # EDIT — export Fingerprint, MAX_MEMORY_WRITE_ATTEMPTS,
│                         #   RETRY_BACKOFF_BASE_SECONDS, MemoryLockingError,
│                         #   MemoryConflictError,
│                         #   MemoryConflictRetriesExhaustedError, fingerprint_of,
│                         #   next_backoff_delay, write_with_retry
├── paths.py             # UNCHANGED (from 045)
├── entry.py             # UNCHANGED (from 046)
├── format.py            # UNCHANGED (from 046)
├── limits.py            # UNCHANGED (from 047) — consumed as-is by write_if_match
├── backend.py           # EDIT — LocalFilesystemBackend gains read_with_fingerprint()
│                         #   and write_if_match(); MemoryBackend protocol gains
│                         #   the same two method signatures. Existing write()/read()
│                         #   are untouched.
└── locking.py            # NEW — Fingerprint, constants, fingerprint_of,
                          #   next_backoff_delay, MemoryLockingError,
                          #   MemoryConflictError,
                          #   MemoryConflictRetriesExhaustedError, write_with_retry
                          #   (pure except the one time.sleep in the retry loop;
                          #   PBT/mutmut target for everything else)

tests/
├── unit/
│   ├── test_memory_locking.py       # NEW — fingerprint_of, next_backoff_delay,
│   │                                 #   error shapes, write_with_retry orchestration
│   └── test_memory_backend.py       # EDIT — read_with_fingerprint / write_if_match
│                                     #   round-trip, conflict, and atomicity cases
└── pbt/
    ├── test_memory_locking_pbt.py    # NEW — fingerprint equality/inequality invariants,
    │                                 #   backoff-delay distribution bounds
    └── test_memory_locking_concurrency_pbt.py  # NEW — the SC-002/SC-003/SC-005
                                       #   "retry eventually succeeds or exhausts,
                                       #   never hangs" invariant across randomized
                                       #   interleavings
```

**Structure Decision**: Single-library layout, unchanged from 045/046/047.
The new pure logic is confined to one new file, `locking.py`, kept separate
from `backend.py` so the ≥80% mutmut bar applies to a small, mostly-I/O-free
module — the same pure/IO discipline 045 applied to `paths.py`/`backend.py`,
046 applied to `format.py`/`backend.py`, and 047 applied to
`limits.py`/`backend.py`. `backend.py` itself changes by adding exactly two
new methods that compose already-tested pure pieces
(`fingerprint_of`, `check_write_size`, `atomic_write_bytes`); the existing
`write()`/`read()` methods and their tests are untouched. A new concurrency-
focused PBT test file is added alongside the boundary-style PBT file,
because this slice's Definition of Done (SC-002/SC-003/SC-005) specifically
requires locking an interleaving invariant that a purely example-based test
would only spot-check.

## Complexity Tracking

*No constitution violations — this slice introduces no deviations. Table intentionally empty.*

| Deviation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|--------------------------------------|
| — | — | — |

## Post-Design Constitution Re-Check

*Re-evaluated after Phase 0 (research.md) and Phase 1 (data-model.md, contracts/, quickstart.md) were drafted.*

The design that emerged — one new pure-plus-one-sleep module (`locking.py`)
holding a fingerprint type, two typed exceptions, retry-policy constants,
and a small orchestration function, plus two new additive methods on
`LocalFilesystemBackend` — introduces no new architectural surface beyond
what 047 already established for `limits.py`, no new dependency, and no new
on-disk persistence. Every gate evaluated above still holds under the
concrete design:

| Principle | Status | Post-design confirmation |
|-----------|--------|---------------------------|
| I. Library-First | ✅ PASS | `locking.py` is a plain internal module; nothing added to `cli/`. |
| II. Agent-Native Design | ✅ PASS | `MemoryConflictError.key/.expected/.actual` and `MemoryConflictRetriesExhaustedError.key/.attempts/.last_conflict` are the structured fields, confirmed in the contract's behavioral tables. |
| III. Context Window Efficiency | ✅ PASS | No change — `write_with_retry` returns `None` on success or raises one exception; no growing log or trace is surfaced to a caller. |
| IV. Two Data Paths | ➖ N/A | Unchanged. |
| V. Explicit Over Implicit | ✅ PASS | Confirmed by the contract's ordering guarantee (D6 in research.md): fingerprint check strictly precedes the size check, which strictly precedes any I/O, so both rejection paths are atomic by construction, never a silent overwrite or a partial write. |
| VI. Unix Philosophy | ✅ PASS | `locking.py` does exactly one thing (detect + retry a stale write); `backend.py` composes it with two small new methods. |
| VII. Secure by Default | ✅ PASS | No credential material touched; fingerprints are `sha256` digests, not raw content, and error messages avoid embedding raw digest bytes. |

**Gate result: PASS.** No new violations surfaced during design; Complexity
Tracking remains empty.
