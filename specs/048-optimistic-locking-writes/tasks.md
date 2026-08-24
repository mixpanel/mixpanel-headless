---
description: "Task list for Optimistic-Locking Concurrency for Memory Writes (AIE-606)"
---

# Tasks: Optimistic-Locking Concurrency for Memory Writes

**Input**: Design documents from `/specs/048-optimistic-locking-writes/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/locking_optimistic_write.md

**Tests**: REQUIRED. This project enforces strict TDD (see CLAUDE.md +
constitution) — tests are written FIRST and must FAIL before
implementation. Hypothesis PBT (boundary/distribution AND the required
concurrency/retry invariant) and mutmut ≥80% on the pure fingerprint/retry-
decision logic in `locking.py` are part of the Definition of Done (SC-005).

**Organization**: Grouped by user story. Layering reality: `locking.py`
(the `Fingerprint` type, retry-policy constants, `fingerprint_of`,
`next_backoff_delay`, both error types) is the single pure module every
story depends on, so it lives in the Foundational phase alongside its unit
+ PBT tests. US1 then wires the two new `backend.py` methods
(`read_with_fingerprint`, `write_if_match`) for the uncontested path. US2
adds the conflict-detection assertions against that same wiring (no new
production code beyond what US1 already needed to be correct). US3 adds
`write_with_retry` itself — the only story with a genuinely new
orchestration function — plus the concurrency PBT that is this slice's
signature testing requirement.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 (maps to spec.md user stories)

## Path Conventions

Single Python library. Source under `src/mixpanel_headless/`, tests under
`tests/{unit,pbt}/`. No integration tier — this slice performs its
filesystem verification through the existing `test_memory_backend.py`
unit-test tier (real temp-directory filesystem, no network) plus one new
concurrency-flavored PBT file that still runs against a real temp directory
within a single test process (threads or manual interleaving), not a real
multi-process race.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the module and test scaffolding for the slice.

- [ ] T001 [P] Create an empty stub module with a module docstring only: `src/mixpanel_headless/_internal/memory/locking.py`.
- [ ] T002 [P] Create failing-test file scaffolds (imports + `pytest`/`hypothesis` boilerplate, no assertions yet): `tests/unit/test_memory_locking.py`, `tests/pbt/test_memory_locking_pbt.py`, `tests/pbt/test_memory_locking_concurrency_pbt.py`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The pure fingerprint/error/retry-policy primitives every story
and every guarded method depends on — `Fingerprint`,
`MAX_MEMORY_WRITE_ATTEMPTS`, `RETRY_BACKOFF_BASE_SECONDS`, `fingerprint_of`,
`next_backoff_delay`, `MemoryLockingError`, `MemoryConflictError`,
`MemoryConflictRetriesExhaustedError`. No `backend.py` guard can be wired in
before this exists and is proven correct in isolation.

**⚠️ CRITICAL**: No story work can begin until this phase is complete. Follow TDD — write the failing test, then implement.

- [ ] T003 Write failing unit tests in `tests/unit/test_memory_locking.py`: `MAX_MEMORY_WRITE_ATTEMPTS == 5`; `fingerprint_of(None) is None`; `fingerprint_of(b"")` returns a 32-byte digest not equal to `fingerprint_of(None)`; `fingerprint_of(data)` is deterministic (`fingerprint_of(data) == fingerprint_of(data)` for the same bytes) and equals `hashlib.sha256(data).digest()`; two different byte payloads produce different fingerprints (spot cases, not exhaustive — PBT owns exhaustiveness); `MemoryLockingError` is a direct `Exception` subclass and is never raised directly; `MemoryConflictError(key, expected, actual)` is a `MemoryLockingError` subclass with `.key`/`.expected`/`.actual` set; `MemoryConflictRetriesExhaustedError(key, attempts, last_conflict)` is a `MemoryLockingError` subclass, is NOT a `MemoryConflictError` instance, and has `.key`/`.attempts`/`.last_conflict` set. Confirm they FAIL.
- [ ] T004 [P] Write a failing property-based test in `tests/pbt/test_memory_locking_pbt.py` (Hypothesis, `_pbt` suffix): for arbitrary byte payloads, `fingerprint_of(data) == fingerprint_of(data)` (determinism) and, for two independently-drawn distinct payloads, `fingerprint_of(a) != fingerprint_of(b)` with overwhelming probability (standard sha256 collision-freedom assumption — assert inequality, do not attempt to prove collision resistance); `fingerprint_of(None) != fingerprint_of(data)` for every drawn `data` including `b""`. A second property: for many repeated calls, `next_backoff_delay()` always returns a value in `[0, RETRY_BACKOFF_BASE_SECONDS)`. Confirm it FAILS.
- [ ] T005 Implement `src/mixpanel_headless/_internal/memory/locking.py`: `Fingerprint = bytes | None` type alias; `MAX_MEMORY_WRITE_ATTEMPTS: Final[int] = 5`; `RETRY_BACKOFF_BASE_SECONDS: Final[float] = 0.015`; `fingerprint_of(data: bytes | None) -> Fingerprint` (returns `None` for `None`, else `hashlib.sha256(data).digest()`); `next_backoff_delay() -> float` (returns `random.random() * RETRY_BACKOFF_BASE_SECONDS`); `MemoryLockingError(Exception)` as the common base, never raised directly; `MemoryConflictError(MemoryLockingError)` with `key: str`, `expected: Fingerprint`, `actual: Fingerprint` fields set in `__init__` and a message naming the key; `MemoryConflictRetriesExhaustedError(MemoryLockingError)` with `key: str`, `attempts: int`, `last_conflict: MemoryConflictError` fields set in `__init__` and a message naming the key and attempt count. Full Google-style docstrings on every symbol. Make T003 + T004 pass.

**Checkpoint**: The pure fingerprint/error/retry-policy primitives exist and are proven correct in isolation (unit + PBT). Wiring the guarded methods into the backend can now begin.

---

## Phase 3: User Story 1 - An uncontested write succeeds exactly as it does today (Priority: P1) 🎯 MVP

**Goal**: Wiring `read_with_fingerprint` and `write_if_match` into
`LocalFilesystemBackend` does not change behavior for any write with no
concurrent writer — content still writes and reads back byte-identical, the
AIE-605 size guard still applies unchanged, and no retry or sleep occurs.

**Independent Test**: Perform a guarded write via `read_with_fingerprint` +
`write_if_match` against a fresh key and against an existing key, with no
intervening writer, and confirm both succeed on the first call with no
exception and read back byte-identical; separately confirm an oversized
mutation still raises `MemorySizeLimitError` unchanged.

### Tests for User Story 1 ⚠️ (write first, must FAIL)

- [ ] T006 [US1] Add failing unit tests to `tests/unit/test_memory_backend.py`: `read_with_fingerprint(key)` on an absent key returns `(None, None)`; on an existing key holding `data`, returns `(data, fingerprint_of(data))`; `write_if_match(key, data, expected=fingerprint)` with `fingerprint` matching the key's current state succeeds and a subsequent `read()` returns `data` byte-identical, for both a fresh key and an existing key being overwritten; `write_if_match(key, oversized_data, expected=...)` with a payload one byte over `MAX_MEMORY_WRITE_BYTES` raises `MemorySizeLimitError` (not `MemoryConflictError`) when the fingerprint matches, unchanged from the AIE-605 behavior. Confirm they FAIL.

### Implementation for User Story 1

- [ ] T007 [US1] Add `read_with_fingerprint(self, key: str) -> tuple[bytes | None, Fingerprint]` and `write_if_match(self, key: str, data: bytes, *, expected: Fingerprint) -> None` to `LocalFilesystemBackend` in `src/mixpanel_headless/_internal/memory/backend.py`, importing `Fingerprint`, `fingerprint_of`, `MemoryConflictError` from `mixpanel_headless._internal.memory.locking`. `write_if_match` computes the current fingerprint via a fresh `read()`, compares to `expected`, raises `MemoryConflictError` on mismatch, otherwise delegates to the existing `check_write_size` + atomic-write sequence (or calls `write()` directly) unchanged. Add both method signatures to the `MemoryBackend` protocol with matching docstrings (`Raises` sections listing `MemoryConflictError`/`MemorySizeLimitError`/`ValueError`/`OSError` as appropriate). Make T006 pass.

**Checkpoint**: MVP — an uncontested guarded write is provably identical in outcome to today's `write()`, plus the new fingerprint check that never fires when there is no contention.

---

## Phase 4: User Story 2 - A conflicting concurrent write is detected before any byte reaches disk (Priority: P1)

**Goal**: `write_if_match` raises `MemoryConflictError` — never silently
overwriting — whenever the fingerprint captured at read time no longer
matches current on-disk state at commit time, for both the
absent-then-created and existing-then-changed/deleted cases, leaving the
intervening writer's content completely unmodified.

**Independent Test**: Capture a fingerprint via `read_with_fingerprint`,
have a second call commit different content to the same key via
`write_if_match` or `write`, then attempt to commit the first fingerprint's
stale expectation; assert `MemoryConflictError` is raised and that the
second writer's content is byte-for-byte unchanged afterward, for a
create-vs-create race, a modify-vs-modify race, and a modify-vs-delete race.

### Tests for User Story 2 ⚠️ (write first, must FAIL)

- [ ] T008 [US2] Add failing unit tests to `tests/unit/test_memory_backend.py`: given `expected = fingerprint_of(None)` (caller believes the key is absent) and another writer has since created the key via `write`, `write_if_match(key, data, expected=expected)` raises `MemoryConflictError` with `.actual` equal to the intervening writer's fingerprint, and the intervening writer's content is unchanged by the raise. Confirm it FAILS.
- [ ] T009 [US2] Add failing unit tests to `tests/unit/test_memory_backend.py`: given `expected` captured from an existing key's content, and another writer has since (a) overwritten the key with different content, or (b) deleted the key, `write_if_match(key, data, expected=expected)` raises `MemoryConflictError` in both cases (case (b)'s `.actual` is `None`), and in both cases a subsequent `read(key)` returns exactly what the intervening writer left behind (the new content in case (a), `None` in case (b)) — never the stale caller's `data`, never a partial write, no `.tmp.*` file left behind. Confirm they FAIL.

### Implementation for User Story 2

- [ ] T010 [US2] Verify T008 + T009 pass against the T007 method bodies in `src/mixpanel_headless/_internal/memory/backend.py` with no further code change (the fingerprint re-check precedes any I/O by construction — see `contracts/locking_optimistic_write.md`'s ordering guarantee). If either test fails, correct the check/compare ordering in `write_if_match` so the fingerprint comparison remains strictly before `check_write_size`/`atomic_write_bytes`.

**Checkpoint**: Every conflict shape (create-vs-create, modify-vs-modify, modify-vs-delete) is provably detected and provably leaves the winning writer's content untouched.

---

## Phase 5: User Story 3 - A detected conflict is retried automatically within a bounded budget (Priority: P1)

**Goal**: `write_with_retry` composes `read_with_fingerprint` +
caller-supplied `mutate` + `write_if_match` into an automatic retry loop
bounded by `MAX_MEMORY_WRITE_ATTEMPTS`, with a jittered delay between
attempts, raising `MemoryConflictRetriesExhaustedError` only when every
attempt in the budget conflicts, and never catching or retrying
`MemorySizeLimitError`.

**Independent Test**: Arrange exactly one intervening write between
`write_with_retry`'s first read and its first `write_if_match` call, and
confirm it succeeds within budget, re-invoking `mutate` against the fresh
content. Separately, arrange every attempt to collide and confirm
`MemoryConflictRetriesExhaustedError` is raised after exactly
`MAX_MEMORY_WRITE_ATTEMPTS` attempts. Separately, confirm an oversized
`mutate` output propagates `MemorySizeLimitError` immediately without
retry.

### Tests for User Story 3 ⚠️ (write first, must FAIL)

- [ ] T011 [US3] Add failing unit tests to `tests/unit/test_memory_locking.py` (using a real `LocalFilesystemBackend` against a temp dir, per the project's existing no-mocking pattern for this module): `write_with_retry(backend, key, mutate)` with no intervening writer succeeds, invokes `mutate` exactly once, and performs no `time.sleep` (assert via a monkeypatched `locking.next_backoff_delay` that is never called, or via elapsed-time assertion with a generous bound). Confirm it FAILS.
- [ ] T012 [US3] Add a failing unit test to `tests/unit/test_memory_locking.py`: a `mutate`/harness combination that commits an intervening write on the mutation's first invocation causes `write_with_retry` to be called exactly twice, succeed on the second `write_if_match` call, and read back content built from the intervening writer's committed bytes (not the stale pre-race bytes). Confirm it FAILS.
- [ ] T013 [US3] Add a failing unit test to `tests/unit/test_memory_locking.py`: a harness that always commits an intervening write before every `mutate` invocation causes `write_with_retry` to raise `MemoryConflictRetriesExhaustedError` with `.attempts == MAX_MEMORY_WRITE_ATTEMPTS` and `.last_conflict` set to a `MemoryConflictError`, after exactly `MAX_MEMORY_WRITE_ATTEMPTS` calls to `mutate`, and that no content is committed to the key beyond what the intervening harness itself wrote. Confirm it FAILS.
- [ ] T014 [US3] Add a failing unit test to `tests/unit/test_memory_locking.py`: a `mutate` that returns content one byte over `MAX_MEMORY_WRITE_BYTES` on its first invocation, with no contention at all, causes `write_with_retry` to raise `MemorySizeLimitError` immediately, `mutate` is invoked exactly once, and no `MemoryConflictRetriesExhaustedError` is ever raised or wrapped around it. Confirm it FAILS.
- [ ] T015 [P] [US3] Write a failing concurrency-flavored property-based test in `tests/pbt/test_memory_locking_concurrency_pbt.py` (Hypothesis, `_pbt` suffix, locking SC-002/SC-003/SC-005's invariant): for randomized interleavings of 0 to `MAX_MEMORY_WRITE_ATTEMPTS - 1` intervening writes landing at randomized points relative to `write_with_retry`'s attempts, the call either (a) succeeds within budget with final on-disk content equal to some deterministic function of the sequence of intervening writes and the final `mutate` invocation, or (b) raises `MemoryConflictRetriesExhaustedError` — and the test asserts the call always terminates (no hang) and never raises anything else undeclared. Confirm it FAILS.

### Implementation for User Story 3

- [ ] T016 [US3] Implement `write_with_retry(backend: MemoryBackend, key: str, mutate: Callable[[bytes | None], bytes]) -> None` in `src/mixpanel_headless/_internal/memory/locking.py`: loop up to `MAX_MEMORY_WRITE_ATTEMPTS` times; each iteration calls `backend.read_with_fingerprint(key)`, computes `mutate(current)`, calls `backend.write_if_match(key, new_data, expected=fingerprint)`; on success return; on `MemoryConflictError`, if attempts remain sleep `time.sleep(next_backoff_delay())` and continue, else raise `MemoryConflictRetriesExhaustedError(key, MAX_MEMORY_WRITE_ATTEMPTS, last_conflict=<the final MemoryConflictError>)`; `MemorySizeLimitError` is never caught — it propagates from whichever attempt raised it. Full Google-style docstring including the caller-mutation re-invocation contract (research.md D7). Make T011-T015 pass.

**Checkpoint**: The retrying helper is proven to succeed within budget under a single collision, to exhaust correctly under persistent collision, to never conflate a size violation with a conflict, and — via the concurrency PBT — to never hang across randomized interleavings.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Meet the Definition of Done.

- [ ] T017 [P] Export `Fingerprint`, `MAX_MEMORY_WRITE_ATTEMPTS`, `RETRY_BACKOFF_BASE_SECONDS`, `fingerprint_of`, `next_backoff_delay`, `MemoryLockingError`, `MemoryConflictError`, `MemoryConflictRetriesExhaustedError`, `write_with_retry` from `src/mixpanel_headless/_internal/memory/__init__.py`.
- [ ] T018 [P] Ensure full Google-style docstrings (Summary/Args/Returns/Raises/Example where behavior isn't obvious) on every new/edited symbol in `memory/locking.py` and the two new methods in `memory/backend.py` (`read_with_fingerprint`, `write_if_match`) plus the corresponding `MemoryBackend` protocol entries.
- [ ] T019 Run `just typecheck` (mypy --strict) and resolve any `Any`/annotation gaps in `locking.py` and the `backend.py` additions.
- [ ] T020 Run `just test-cov` and confirm ≥90% coverage; add unit cases for any uncovered branch in `locking.py` or the new `backend.py` methods.
- [ ] T021 Run `just mutate` and `just mutate-check`; confirm ≥80% kill rate on `memory/locking.py`'s pure logic (`fingerprint_of`, `next_backoff_delay`, the error `__init__` bodies, and the loop's branch conditions in `write_with_retry` excluding the literal `time.sleep` call). Evidence: boundary/equality coverage from parametrized unit tests (T003, T011-T014) + Hypothesis PBT (T004, T015) on every accept/conflict/exhaustion path.
- [ ] T022 Run `just check` (lint + fmt-check + typecheck + test-cov + build) and the `quickstart.md` snippets; fix any drift between the quickstart examples and the shipped signatures.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories (`backend.py`'s new methods need `Fingerprint`, `fingerprint_of`, and `MemoryConflictError` to exist and be correct first).
- **US1 (Phase 3)**: Depends on Phase 2. MVP.
- **US2 (Phase 4)**: Depends on US1 (the method bodies in `backend.py` from T007 are the same code US2's conflict-detection tests exercise).
- **US3 (Phase 5)**: Depends on US1 + US2 (composes `read_with_fingerprint` + `write_if_match` into the new `write_with_retry`; needs both to already be correct).
- **Polish (Phase 6)**: Depends on all desired stories.

### User Story Dependencies

- US1 (P1) is the MVP: the two guarded methods exist and are proven not to disturb an uncontested write.
- US2 (P1) extends the exact same `backend.py` methods from US1 with the conflict-detection assertions; not a separate code change, so it is sequenced directly after US1 rather than in parallel.
- US3 (P1) is the only story with genuinely new production code (`write_with_retry`); it depends on both US1 and US2 being correct, since it calls the exact methods they wired and verified.

### Within Each Story

- Tests are written FIRST and must FAIL before implementation (strict TDD).
- Foundational `locking.py` (Phase 2) before any `backend.py` edit (Phase 3+).
- Within US3: the four unit tests (T011-T014) and the concurrency PBT (T015) can be written in parallel with each other (different assertions, same new file) before T016's single implementation task makes all of them pass together.

### Parallel Opportunities

- Phase 1: T001, T002 in parallel (distinct files).
- Phase 2: T004 can be written in parallel with T003 (distinct test files) before T005 implements against both.
- Phase 5: T015 [P] can be written in parallel with T011-T014 (distinct test file, same underlying `write_with_retry` target).
- Phase 6: T017, T018 in parallel (distinct files: `__init__.py` vs. docstrings across `locking.py`/`backend.py`).
- Because this slice touches exactly two source files (`locking.py`, `backend.py`) and every method composes the same small set of already-tested pieces, most implementation tasks are inherently sequential rather than parallel — this is a small, tightly-layered feature, not a multi-component one.

---

## Implementation Strategy

### MVP First

1. Phase 1 (Setup) → Phase 2 (Foundational: `locking.py`'s fingerprint/error/policy primitives fully tested in isolation) → Phase 3 (US1: guarded methods wired in, uncontested writes unaffected).
2. **STOP and VALIDATE**: an uncontested guarded write round-trips byte-identical through `LocalFilesystemBackend`, exactly like the unguarded `write()` path, with the AIE-605 size guard still firing unchanged for an oversized payload. That is the demonstrable MVP.

### Incremental Delivery

Foundational (`locking.py`) → US1 (guarded methods wired, no regression) →
US2 (conflict detection + atomicity proven across all three conflict
shapes) → US3 (`write_with_retry` composes them with bounded retry + jitter,
proven via unit tests and the required concurrency PBT) → Polish (coverage,
mutation, docs, `just check`). Each phase leaves the module green and
independently testable.

---

## Notes

- All new production code lives under `_internal/memory/` — nothing is
  added to the public `mixpanel_headless` surface in this slice (public
  exposure is AIE-608).
- This slice performs no new filesystem primitive beyond what
  `read()`/`write()` already provide; `test_memory_backend.py`'s existing
  temp-directory pattern (no mocking) is reused for the conflict-detection
  and atomicity assertions in US2, and `write_with_retry`'s tests use the
  same real-backend-against-temp-dir pattern with a harness that commits an
  intervening write from inside the `mutate` callback (or a small
  test-local helper) rather than real OS-level threads, since the
  invariant under test is the retry *logic*, not OS thread-scheduling
  behavior.
- The concurrency PBT (T015) is explicitly required by this slice's Success
  Criteria (SC-002, SC-003, SC-005) — do not treat it as optional polish;
  it is the test that locks "retry eventually succeeds or exhausts, never
  hangs" as a property rather than a handful of examples.
- Commit after each task or logical pair. Do not advance a phase while its
  tests are red for the wrong reason.
