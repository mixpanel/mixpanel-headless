---
description: "Task list for Write-Time Size-Limit Enforcement (AIE-605)"
---

# Tasks: Write-Time Size-Limit Enforcement

**Input**: Design documents from `/specs/047-write-time-size-limits/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/memory_write_size_limit.md

**Tests**: REQUIRED. This project enforces strict TDD (see CLAUDE.md + constitution) — tests are written FIRST and must FAIL before implementation. Hypothesis PBT and mutmut ≥80% on the pure `check_write_size` logic are part of the Definition of Done (SC-005).

**Organization**: Grouped by user story. Layering reality: `limits.py` (the constant + `MemorySizeLimitError` + `check_write_size`) is the single pure module every story depends on, so it lives in the Foundational phase alongside its unit + PBT tests; US1 and US2 then each add one guard call site (`backend.py`) plus story-specific assertions against the same, already-tested pure logic; US3 is a verification-only phase confirming the single-choke-point property, since the design gives it no separate code to write.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 (maps to spec.md user stories)

## Path Conventions

Single Python library. Source under `src/mixpanel_headless/`, tests under `tests/{unit,pbt}/`. No integration tier — this slice performs its filesystem verification through the existing `test_memory_backend.py` unit-test tier (real temp-directory filesystem, no network).

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the module and test scaffolding for the slice.

- [ ] T001 [P] Create an empty stub module with a module docstring only: `src/mixpanel_headless/_internal/memory/limits.py`.
- [ ] T002 [P] Create failing-test file scaffolds (imports + `pytest`/`hypothesis` boilerplate, no assertions yet): `tests/unit/test_memory_limits.py`, `tests/pbt/test_memory_limits_pbt.py`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The pure size-check primitive every story and every write primitive depends on — `MAX_MEMORY_WRITE_BYTES`, `MemorySizeLimitError`, `check_write_size`. No guard can be wired into `backend.py` before this exists and is proven correct in isolation.

**⚠️ CRITICAL**: No story work can begin until this phase is complete. Follow TDD — write the failing test, then implement.

- [ ] T003 Write failing unit tests in `tests/unit/test_memory_limits.py`: `MAX_MEMORY_WRITE_BYTES == 8_192`; `check_write_size(b"")` returns `None` (zero-byte); `check_write_size(data)` returns `None` for `len(data)` one byte under the ceiling and for `len(data)` exactly at the ceiling (inclusive); `check_write_size(data)` raises `MemorySizeLimitError` for `len(data)` one byte over the ceiling and for a far-larger payload; `MemorySizeLimitError` is a `ValueError` subclass; a raised instance carries `.size == len(data)` and `.limit == MAX_MEMORY_WRITE_BYTES`; `str(err)` names both the size and the limit values. Confirm they FAIL.
- [ ] T004 Write a failing property-based test in `tests/pbt/test_memory_limits_pbt.py` (Hypothesis, `_pbt` suffix): for byte-lengths drawn from a strategy spanning zero, arbitrary sizes under the ceiling, exactly-at the ceiling, and arbitrarily larger than the ceiling, `check_write_size` returns `None` iff `len(data) <= MAX_MEMORY_WRITE_BYTES`, and every raised `MemorySizeLimitError` satisfies `size > limit == MAX_MEMORY_WRITE_BYTES` and `size == len(data)`. Confirm it FAILS.
- [ ] T005 Implement `src/mixpanel_headless/_internal/memory/limits.py`: `MAX_MEMORY_WRITE_BYTES: int = 8_192`; `MemorySizeLimitError(ValueError)` with `size: int` and `limit: int` fields set in `__init__` and a message naming both; `check_write_size(data: bytes) -> None` comparing `len(data)` against `MAX_MEMORY_WRITE_BYTES` and raising `MemorySizeLimitError(size=len(data), limit=MAX_MEMORY_WRITE_BYTES)` when it is exceeded, else returning `None`. Full Google-style docstrings on all three symbols. Make T003 + T004 pass.

**Checkpoint**: The pure size-check primitive exists and is proven correct in isolation (unit + PBT). Wiring it into the write path can now begin.

---

## Phase 3: User Story 1 - A write at or under the limit succeeds unchanged (Priority: P1) 🎯 MVP

**Goal**: Wiring `check_write_size` into `LocalFilesystemBackend.write` does not change behavior for any write at or under the ceiling — content at, under, and zero bytes still writes and reads back byte-identical.

**Independent Test**: Write a note under the ceiling, then at exactly the ceiling, then zero-byte, through `LocalFilesystemBackend.write`; confirm all three succeed and `read()` returns byte-identical content.

### Tests for User Story 1 ⚠️ (write first, must FAIL)

- [ ] T006 [US1] Add failing unit tests to `tests/unit/test_memory_backend.py`: `LocalFilesystemBackend.write` followed by `read` round-trips byte-identical content for a payload one byte under `MAX_MEMORY_WRITE_BYTES`, for a payload exactly at `MAX_MEMORY_WRITE_BYTES`, and for zero-byte content — each against a fresh key with no pre-existing file. Confirm they FAIL only insofar as the import of `limits` is exercised (behavior should already pass once T007 lands; write the assertions now so the checkpoint is provable end-to-end).

### Implementation for User Story 1

- [ ] T007 [US1] Edit `LocalFilesystemBackend.write` in `src/mixpanel_headless/_internal/memory/backend.py`: import `check_write_size` from `mixpanel_headless._internal.memory.limits` and call `check_write_size(data)` as the first statement of `write()`, before `self._resolve(key)`. Update the method's docstring `Raises` section to list `MemorySizeLimitError`. Make T006 pass.

**Checkpoint**: MVP — normal-sized and boundary-sized writes are provably unaffected by the new guard.

---

## Phase 4: User Story 2 - A write over the limit is rejected, atomically (Priority: P1)

**Goal**: A write whose content exceeds the ceiling raises `MemorySizeLimitError` before any byte reaches disk — for a fresh key (no file created) and for an existing key (existing file left byte-for-byte unchanged, no tmp file left behind).

**Independent Test**: Attempt an over-ceiling write against a backend with no pre-existing file at the key, and against a backend with an existing file at the key; assert both raise `MemorySizeLimitError` naming the size and the limit, and that no file is created/modified in either case.

### Tests for User Story 2 ⚠️ (write first, must FAIL)

- [ ] T008 [US2] Add failing unit tests to `tests/unit/test_memory_backend.py`: `LocalFilesystemBackend.write(key, data)` with `len(data) == MAX_MEMORY_WRITE_BYTES + 1` raises `MemorySizeLimitError` with `.size` and `.limit` set correctly, and no file exists at `key` afterward, when `key` has no pre-existing file (assert the scope directory itself is not created if it didn't exist, per the contract's "`self._ensure_dir` is never reached"). Confirm they FAIL.
- [ ] T009 [US2] Add failing unit tests to `tests/unit/test_memory_backend.py`: given an existing file at `key` with known content, `write(key, oversized_data)` raises `MemorySizeLimitError` and a subsequent `read(key)` returns the original content byte-for-byte unchanged; assert no `.tmp.*` file is left behind in the scope directory after the raise. Confirm they FAIL.

### Implementation for User Story 2

- [ ] T010 [US2] Verify T008 + T009 pass against the T007 guard placement in `src/mixpanel_headless/_internal/memory/backend.py` with no further code change (the check precedes `_resolve`/`_ensure_dir`/`atomic_write_bytes` by construction — see `contracts/memory_write_size_limit.md`'s ordering guarantee). If either test fails, correct the statement ordering in `write()` so `check_write_size(data)` remains strictly first.

**Checkpoint**: Oversized writes are rejected atomically in both the fresh-key and overwrite cases; existing content is provably untouched.

---

## Phase 5: User Story 3 - The ceiling is enforced consistently across every write primitive (Priority: P2)

**Goal**: Confirm the guard has exactly one source of truth and one enforcement point today, so no write primitive can define a divergent limit or bypass the check (FR-008, SC-004).

**Independent Test**: Confirm `LocalFilesystemBackend.write` is the sole implementation of `MemoryBackend.write` in the codebase, that it is the only call site of `atomic_write_bytes` for memory content, and that `check_write_size`/`MAX_MEMORY_WRITE_BYTES` are referenced from exactly one module.

### Tests for User Story 3 ⚠️ (write first, must FAIL)

- [ ] T011 [US3] Add a failing unit test to `tests/unit/test_memory_backend.py` asserting `LocalFilesystemBackend.write` raises `MemorySizeLimitError` referencing the exact same `MAX_MEMORY_WRITE_BYTES` value imported directly from `mixpanel_headless._internal.memory.limits` — i.e. the backend's raised `.limit` and the module constant are identical, not independently defined or copied. Confirm it FAILS before T007/T010 land (or is already covered — if T006–T010 fully satisfy this, note that here and skip re-asserting).

### Implementation for User Story 3

- [ ] T012 [US3] No new production code: confirm via the existing test suite (T003–T011) and a manual read of `src/mixpanel_headless/_internal/memory/backend.py` that `check_write_size` is called exactly once, at the top of `write()`, and that no other module defines a competing size constant. Document nothing further — this story is fully discharged by the single choke point established in Phase 3/4.

**Checkpoint**: The single-choke-point guarantee is verified; a future write primitive built on top of `backend.write()` inherits the guard automatically (FR-008 acceptance scenario 2 is structural, not independently testable without a second primitive that does not yet exist).

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Meet the Definition of Done.

- [ ] T013 [P] Export `MAX_MEMORY_WRITE_BYTES`, `MemorySizeLimitError`, and `check_write_size` from `src/mixpanel_headless/_internal/memory/__init__.py`.
- [ ] T014 [P] Ensure full Google-style docstrings (Summary/Args/Returns/Raises/Example where behavior isn't obvious) on every new/edited symbol in `memory/limits.py` and the edited `write()` method in `memory/backend.py`.
- [ ] T015 Run `just typecheck` (mypy --strict) and resolve any `Any`/annotation gaps in `limits.py` and the `backend.py` edit.
- [ ] T016 Run `just test-cov` and confirm ≥90% coverage; add unit cases for any uncovered branch in `limits.py` or the new `backend.py` guard path.
- [ ] T017 Run `just mutate` and `just mutate-check`; confirm ≥80% kill rate on `memory/limits.py`'s `check_write_size`. Evidence: boundary coverage from parametrized unit tests (T003) + Hypothesis PBT (T004) on every accept/reject path.
- [ ] T018 Run `just check` (lint + fmt-check + typecheck + test-cov + build) and the `quickstart.md` snippets; fix any drift between the quickstart examples and the shipped signatures.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories (`backend.py`'s guard needs `check_write_size` + `MemorySizeLimitError` to exist and be correct first).
- **US1 (Phase 3)**: Depends on Phase 2. MVP.
- **US2 (Phase 4)**: Depends on US1 (the guard call site in `backend.py` from T007 is the same site US2's rejection tests exercise).
- **US3 (Phase 5)**: Depends on US1 + US2 (verifies the single choke point they established; adds no new call site).
- **Polish (Phase 6)**: Depends on all desired stories.

### User Story Dependencies

- US1 (P1) is the MVP: the guard is wired in and proven not to disturb legitimate writes.
- US2 (P1) extends the exact same `backend.py` edit from US1 with the rejection-path assertions; not a separate code change, so it is sequenced directly after US1 rather than parallel.
- US3 (P2) is verification-only against the artifacts of US1/US2; it has no independent implementation task.

### Within Each Story

- Tests are written FIRST and must FAIL before implementation (strict TDD).
- Foundational `limits.py` (Phase 2) before any `backend.py` edit (Phase 3+).

### Parallel Opportunities

- Phase 1: T001, T002 in parallel (distinct files).
- Phase 6: T013, T014 in parallel (distinct files: `__init__.py` vs. docstrings across `limits.py`/`backend.py`).
- Because this slice touches exactly two source files (`limits.py`, `backend.py`) and the guard is a single call site, most implementation tasks are inherently sequential rather than parallel — this is a small, single-choke-point feature, not a multi-component one.

---

## Implementation Strategy

### MVP First

1. Phase 1 (Setup) → Phase 2 (Foundational: `limits.py` fully tested in isolation) → Phase 3 (US1: guard wired in, legitimate writes unaffected).
2. **STOP and VALIDATE**: writes at, under, and at zero bytes still round-trip byte-identical through `LocalFilesystemBackend`. That is the demonstrable MVP.

### Incremental Delivery

Foundational (`limits.py`) → US1 (guard wired, no regression) → US2 (rejection + atomicity proven) → US3 (single-choke-point verification) → Polish (coverage, mutation, docs, `just check`). Each phase leaves the module green and independently testable.

---

## Notes

- All new production code lives under `_internal/memory/` — nothing is added to the public `mixpanel_headless` surface in this slice (public exposure is AIE-608).
- This slice performs no new filesystem primitive; `test_memory_backend.py`'s existing temp-directory pattern (no mocking) is reused for the atomicity assertions in US2.
- Commit after each task or logical pair. Do not advance a phase while its tests are red for the wrong reason.
