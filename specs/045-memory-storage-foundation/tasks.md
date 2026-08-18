---
description: "Task list for Memory Storage Foundation & Two-Tree Scoping (AIE-603)"
---

# Tasks: Memory Storage Foundation & Two-Tree Scoping

**Input**: Design documents from `/specs/045-memory-storage-foundation/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/memory_backend.md

**Tests**: REQUIRED. This project enforces strict TDD (see CLAUDE.md + constitution) — tests are written FIRST and must FAIL before implementation. Hypothesis PBT and mutmut ≥80% on the pure modules are part of the Definition of Done.

**Organization**: Grouped by user story. Note the layering reality: the pure `paths.py` and the shared `storage_root.py` are prerequisites for every story, so they live in the Foundational phase; each story phase then adds the behavior and the story-specific verification on top.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 / US4 (maps to spec.md user stories)

## Path Conventions

Single Python library. Source under `src/mixpanel_headless/`, tests under `tests/{unit,pbt,integration}/`.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the module and test scaffolding for the slice.

- [X] T001 [P] Create the memory package skeleton: `src/mixpanel_headless/_internal/memory/__init__.py` (package marker + internal export placeholders) and empty stub modules `src/mixpanel_headless/_internal/memory/paths.py` and `src/mixpanel_headless/_internal/memory/backend.py`, each with a module docstring only.
- [X] T002 [P] Create the empty shared-root stub module `src/mixpanel_headless/_internal/storage_root.py` with a module docstring only.
- [X] T003 [P] Create failing-test file scaffolds (imports + `pytest`/`hypothesis` boilerplate, no assertions yet): `tests/unit/test_storage_root.py`, `tests/unit/test_memory_paths.py`, `tests/unit/test_memory_backend.py`, `tests/pbt/test_memory_paths_pbt.py`, `tests/integration/test_memory_scoping.py`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The shared storage root and the pure path/validation logic that EVERY user story depends on.

**⚠️ CRITICAL**: No user-story work can begin until this phase is complete. Follow TDD within each pair — write the failing test, then implement.

### Shared storage root (blocks US1, US2, US3, US4)

- [X] T004 [US3] Write failing tests in `tests/unit/test_storage_root.py`: `storage_root()` returns `$MP_OAUTH_STORAGE_DIR` when set, `~/.mp` when unset, and re-resolves at call time (change the env var between two calls, monkeypatched `$HOME`). Confirm they FAIL.
- [X] T005 Implement `storage_root()` in `src/mixpanel_headless/_internal/storage_root.py` (call-time resolution, full Google-style docstring), moving the logic out of `auth/storage.py::_storage_root`.
- [X] T006 Edit `src/mixpanel_headless/_internal/auth/storage.py` to make `_storage_root` delegate to `storage_root()` (thin re-export/alias for backward compat), then run the existing auth suite (`just test -k storage`) to confirm no regressions.

### Pure path & validation logic (blocks US1, US2 — the PBT/mutmut target)

- [X] T007 [P] Write failing unit tests in `tests/unit/test_memory_paths.py`: `validate_account_name` (accept `^[a-zA-Z0-9_-]{1,64}$`, reject others), `validate_project_id` (accept `^\d{1,20}$` returned opaque, reject `12ab`/empty/`../etc`/21-digit), `user_memory_dir`/`project_memory_dir` produce `<root>/accounts/{name}/memory` and `<root>/projects/{id}/memory`, and `resolve_key` joins in-tree and raises `ValueError` on `..`-escape / absolute / empty keys. Confirm they FAIL.
- [X] T008 [P] Write failing property-based tests in `tests/pbt/test_memory_paths_pbt.py` (Hypothesis, `_pbt` suffix): for any valid id/name + any non-escaping key, `resolve_key(scope_dir, key)` is always under `scope_dir`; any key containing an escaping `..` always raises; any invalid id/name always raises regardless of key; `resolve_key` is deterministic/idempotent for fixed inputs. Confirm they FAIL.
- [X] T009 Implement `src/mixpanel_headless/_internal/memory/paths.py` — `validate_account_name`, `validate_project_id` (new `^\d{1,20}$`, opaque), `user_memory_dir`, `project_memory_dir`, `resolve_key` — all pure and I/O-free with `root` injected. Make T007 + T008 pass.

**Checkpoint**: Shared root + pure path logic complete and fully tested. Backend and story work can begin.

---

## Phase 3: User Story 1 - Durable notes separated by scope (Priority: P1) 🎯 MVP

**Goal**: A `LocalFilesystemBackend` that stores and retrieves opaque bytes under a scope directory, with the two trees physically separate.

**Independent Test**: Write different bytes to the same relative key in a user scope and a project scope; read each back and confirm independence and distinct on-disk locations.

### Tests for User Story 1 ⚠️ (write first, must FAIL)

- [X] T010 [P] [US1] Write failing unit tests in `tests/unit/test_memory_backend.py` for the happy path: `write` then `read` round-trips exact bytes; `read` of an absent key returns `None`; `list()` returns sorted keys and `[]` for an absent scope; `delete` removes a present key and is a no-op for an absent key; `write` creates the scope directory on demand. Use a `tmp_path` scope dir.
- [X] T011 [P] [US1] Write failing integration test in `tests/integration/test_memory_scoping.py`: with `$MP_OAUTH_STORAGE_DIR` at `tmp_path`, writing `notes.md` to `user_memory_dir("personal")` and to `project_memory_dir("3713224")` yields two independent values at the two expected paths.

### Implementation for User Story 1

- [X] T012 [US1] Implement `LocalFilesystemBackend.__init__`, `write`, `read`, `list`, `delete` in `src/mixpanel_headless/_internal/memory/backend.py`: `write` via `io_utils.atomic_write_bytes(path, data, mode=0o600)` after ensuring `scope_dir` exists using the `os.umask(0o077)` + `mkdir(parents=True, exist_ok=True)` pattern; `read` returns `None` when the path is absent; `list` globs the scope dir returning sorted relative keys; `delete` is `unlink(missing_ok=True)`. Route all key handling through `resolve_key`. Make T010 + T011 pass.

**Checkpoint**: MVP — two separated, addressable trees with working byte storage.

---

## Phase 4: User Story 2 - Safe, predictable addressing (Priority: P1)

**Goal**: Every hostile identifier or key is rejected before touching disk, and symlinked note paths are refused on read.

**Independent Test**: Feed the battery of hostile ids/names/keys and a symlinked note path; confirm each is rejected/refused with nothing resolving outside the scope tree.

### Tests for User Story 2 ⚠️ (write first, must FAIL)

- [X] T013 [P] [US2] Add failing tests to `tests/unit/test_memory_backend.py`: `read`/`write`/`delete` raise `ValueError` for empty, absolute, and `..`-escaping keys (before any disk write occurs — assert no file created); constructing a scope dir via `project_memory_dir` with an invalid id raises `ValueError`.
- [X] T014 [P] [US2] Add a failing test to `tests/unit/test_memory_backend.py`: a `read` whose target path is a symlink raises `CredentialPathError` (create a symlink under `tmp_path` and point a key at it), asserting the symlink is refused not followed.

### Implementation for User Story 2

- [X] T015 [US2] Wire validation + symlink refusal into `backend.py`: ensure every op validates its key via `resolve_key` first, and `read` calls `io_utils.reject_if_symlink(path)` before reading. Confirm reads deliberately do NOT enforce owner-only mode or a size cap (add a test-covered case: a `0o644` note file still reads successfully). Make T013 + T014 pass.

**Checkpoint**: Addressing is safe end-to-end; US1 + US2 both independently testable.

---

## Phase 5: User Story 3 - Hermetic, relocatable storage root (Priority: P2)

**Goal**: All memory artifacts honor the storage-root override at call time; nothing leaks to the real home directory.

**Independent Test**: Point the override at a temp dir, perform writes/reads, confirm containment under that dir and zero artifacts under real `$HOME`.

### Tests for User Story 3 ⚠️ (write first, must FAIL)

- [X] T016 [P] [US3] Add a failing containment test to `tests/integration/test_memory_scoping.py`: with `$MP_OAUTH_STORAGE_DIR` at `tmp_path` and a separate fake `$HOME`, a full write→read→list cycle places every file under `tmp_path/{accounts,projects}/.../memory/` and creates nothing under the fake `$HOME`.

### Implementation for User Story 3

- [X] T017 [US3] Confirm the backend + path helpers resolve the root through `storage_root()` at call time (no import-time capture); adjust `backend.py`/`paths.py` call sites if any captured the root early. Make T016 pass. (Largely verification — the root plumbing lands in Phase 2.)

**Checkpoint**: Substrate is hermetically testable; the coverage/mutation bars are now reachable.

---

## Phase 6: User Story 4 - A backend seam ready for a future team home (Priority: P2)

**Goal**: A content-agnostic `MemoryBackend` protocol that callers depend on, so AIE-620 can swap the implementation without caller changes.

**Independent Test**: Exercise read/write/list/delete purely through the protocol type against `LocalFilesystemBackend`; substitute a trivial in-memory fake and confirm a protocol-typed caller needs no changes.

### Tests for User Story 4 ⚠️ (write first, must FAIL)

- [X] T018 [P] [US4] Add a failing conformance test to `tests/unit/test_memory_backend.py`: a helper typed against `MemoryBackend` performs a write/read/list/delete sequence and passes for both `LocalFilesystemBackend` and a minimal in-memory fake implementing the same protocol.

### Implementation for User Story 4

- [X] T019 [US4] Define the `MemoryBackend` `Protocol` (`read`/`write`/`list`/`delete`) in `src/mixpanel_headless/_internal/memory/backend.py` per `contracts/memory_backend.md`, declare `LocalFilesystemBackend` as conforming, and export both plus the path helpers from `memory/__init__.py`. Make T018 pass.

**Checkpoint**: The seam is real (exercised through the abstract type), ready for the team backend.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Meet the Definition of Done.

- [X] T020 [P] Ensure full Google-style docstrings (Summary/Args/Returns/Raises/Example where behavior isn't obvious) on every new class, method, and function in `storage_root.py`, `memory/paths.py`, `memory/backend.py`, and `memory/__init__.py`.
- [X] T021 Run `just typecheck` (mypy --strict) and resolve any `Any`/annotation gaps in the new modules.
- [X] T022 Run `just test-cov` and confirm ≥90% coverage; add unit cases for any uncovered branches (corrupt/absent paths, Windows `hasattr` fallbacks if reachable).
- [ ] T023 (DEFERRED — needs full-codebase mutmut run) Run `just mutate` and `just mutate-check`; confirm ≥80% kill rate on `memory/paths.py`. Note: mutmut's copy model can't be scoped to individual files (narrowing `paths_to_mutate` breaks the `mutants/` package copy), so this runs as part of the normal full-suite mutation pass in CI. Evidence pending: `paths.py` has 100% branch coverage from parametrized unit tests + Hypothesis PBT on every accept/reject/containment path.
- [X] T024 Run `just check` (lint + fmt-check + typecheck + test-cov + build) and the `quickstart.md` snippets; fix any drift between the quickstart examples and the shipped signatures.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories. Within it, storage-root (T004–T006) and pure-paths (T007–T009) are independent tracks and may run in parallel.
- **US1 (Phase 3)**: Depends on Phase 2 (needs `paths.py`). MVP.
- **US2 (Phase 4)**: Depends on Phase 2 + the `backend.py` skeleton from US1 (T012). Adds validation/symlink tests on the same file.
- **US3 (Phase 5)**: Depends on Phase 2 (root plumbing) + a backend to exercise (US1).
- **US4 (Phase 6)**: Depends on `backend.py` existing (US1); formalizes the protocol.
- **Polish (Phase 7)**: Depends on all desired stories.

### User Story Dependencies

- US1 (P1) is the MVP and the base the others verify against.
- US2, US3, US4 all build on the US1 `backend.py` file, so their implementation tasks touch a shared file and are **not** freely parallel with each other (sequence US1 → US2 → US3 → US4, or coordinate edits to `backend.py`).

### Within Each Story

- Tests are written FIRST and must FAIL before implementation (strict TDD).
- Pure logic (Phase 2) before the backend (Phase 3+).

### Parallel Opportunities

- Phase 1: T001, T002, T003 in parallel (distinct files).
- Phase 2: the storage-root track (T004→T006) and the pure-paths track (T007+T008→T009) in parallel; T007 and T008 in parallel (distinct test files).
- Test-authoring tasks marked [P] across a story touch distinct files and can be written in parallel, but implementation tasks on `backend.py` serialize.

---

## Implementation Strategy

### MVP First

1. Phase 1 (Setup) → Phase 2 (Foundational: shared root + pure paths, fully tested) → Phase 3 (US1 backend).
2. **STOP and VALIDATE**: two separated trees storing/retrieving bytes hermetically. That is the demonstrable MVP.

### Incremental Delivery

US1 (storage) → US2 (safety) → US3 (hermetic root, mostly verification) → US4 (protocol seam) → Polish (coverage, mutation, docs, `just check`). Each phase leaves the substrate green and independently testable.

---

## Notes

- All new production code lives under `_internal/` — nothing is added to the public `mixpanel_headless` surface in this slice (tool verbs are AIE-608).
- The one intentional divergence from the ticket's "reuse `read_credential_text`" anchor — the lighter memory read — is realized in T015 and its `0o644`-still-reads test.
- Commit after each task or logical pair. Do not advance a phase while its tests are red for the wrong reason.
