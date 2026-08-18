---
description: "Task list for Markdown Entry Format & Confidence Labels (AIE-604)"
---

# Tasks: Markdown Entry Format & Confidence Labels

**Input**: Design documents from `/specs/046-markdown-format-confidence-labels/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/memory_entry_format.md

**Tests**: REQUIRED. This project enforces strict TDD (see CLAUDE.md + constitution) — tests are written FIRST and must FAIL before implementation. Hypothesis PBT and mutmut ≥80% on the pure modules are part of the Definition of Done.

**Organization**: Grouped by user story. Layering reality: `entry.py` (the label set + `MemoryEntry`) is a prerequisite for `format.py` (serialize/parse) and for every story, so it lives in the Foundational phase; each story phase then adds behavior and story-specific verification on top of the shared `format.py` / `entry.py` files.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 / US4 (maps to spec.md user stories)

## Path Conventions

Single Python library. Source under `src/mixpanel_headless/`, tests under `tests/{unit,pbt}/`. No integration tier — this slice performs no filesystem or network I/O.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the module and test scaffolding for the slice.

- [X] T001 [P] Create empty stub modules with a module docstring only: `src/mixpanel_headless/_internal/memory/entry.py` and `src/mixpanel_headless/_internal/memory/format.py`.
- [X] T002 [P] Create failing-test file scaffolds (imports + `pytest`/`hypothesis` boilerplate, no assertions yet): `tests/unit/test_memory_entry.py`, `tests/unit/test_memory_format.py`, `tests/pbt/test_memory_format_pbt.py`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The confidence-label set and the immutable `MemoryEntry` that EVERY story depends on. `format.serialize`/`parse` cannot exist without it.

**⚠️ CRITICAL**: No story work can begin until this phase is complete. Follow TDD — write the failing test, then implement.

- [X] T003 Write failing unit tests in `tests/unit/test_memory_entry.py`: `CONFIDENCE_LABELS` equals `("Confirmed", "Inferred", "Observed", "Predicted")` in that order; `MemoryEntry(label, body)` constructs for each of the four labels and stores `body` verbatim; `MemoryEntry` is frozen (assigning `entry.body` raises `FrozenInstanceError`); `MemoryEntry("Bogus", "x")` raises `ValueError`; empty `body` is accepted. Confirm they FAIL.
- [X] T004 Implement `src/mixpanel_headless/_internal/memory/entry.py`: the `ConfidenceLabel` `Literal`, the `CONFIDENCE_LABELS` tuple (single source of truth, descending trust), and the frozen `@dataclass MemoryEntry` with `confidence`/`body` fields and a `__post_init__` that raises `ValueError` when `confidence not in CONFIDENCE_LABELS`. Full Google-style docstrings. Make T003 pass. (Note: `to_dict` is deliberately deferred to US4.)

**Checkpoint**: The label set + immutable entry exist and are validated. Format and story work can begin.

---

## Phase 3: User Story 1 - Label a note and read it back (Priority: P1) 🎯 MVP

**Goal**: `serialize` renders an entry to front-matter+body text and `parse` recovers a byte-identical entry, for every confidence label.

**Independent Test**: Build an entry with each of the four labels and a body, `serialize` then `parse`, assert the recovered label and body are identical.

### Tests for User Story 1 ⚠️ (write first, must FAIL)

- [X] T005 [US1] Write failing unit tests in `tests/unit/test_memory_format.py`: `serialize(MemoryEntry("Confirmed", body))` starts with `"---\nconfidence: Confirmed\n---\n"` and ends with `body`; `parse(serialize(e)) == e` for each of the four labels; the serialized text's leading region is a `---`-fenced block naming the label. Confirm they FAIL.

### Implementation for User Story 1

- [X] T006 [US1] Implement `serialize` and `parse` in `src/mixpanel_headless/_internal/memory/format.py`: `serialize` emits `f"---\nconfidence: {entry.confidence}\n---\n{entry.body}"`; `parse` strips the opening `---\n` fence, consumes front-matter lines up to the first line equal to `---`, reads the single `confidence: <value>` line (whitespace-trim the value, match case-sensitively against `CONFIDENCE_LABELS`), and takes everything after the closing fence's newline as the body via index arithmetic (not split/join). Define `MemoryFormatError(ValueError)` in the same module. Make T005 pass. (Malformed-input branches are fleshed out in US3; body-edge fidelity in US2.)

**Checkpoint**: MVP — an entry round-trips through text with its label intact.

---

## Phase 4: User Story 2 - Free-form body, no schema imposed (Priority: P1)

**Goal**: The body is carried byte-for-byte through a round-trip, including content that itself contains `---` lines.

**Independent Test**: Round-trip bodies containing `---` lines, blank lines, unicode, trailing whitespace, and empty content; assert the body is byte-identical.

### Tests for User Story 2 ⚠️ (write first, must FAIL)

- [X] T007 [P] [US2] Add failing unit tests to `tests/unit/test_memory_format.py`: round-trip a body containing an interior `---` line (`"before\n---\nafter"`), a body that starts with `---`, an empty body, a body with unicode + trailing whitespace, and a body with leading/trailing blank lines — asserting the parsed body equals the original in every case and interior `---` is NOT treated as a fence. Confirm they FAIL.
- [X] T008 [P] [US2] Write failing property-based tests in `tests/pbt/test_memory_format_pbt.py` (Hypothesis, `_pbt` suffix): for any `label ∈ CONFIDENCE_LABELS` and arbitrary text `body` (drawn from a strategy that includes `---`, newlines, unicode, and empty strings), `parse(serialize(MemoryEntry(label, body))) == MemoryEntry(label, body)` with byte-identical body; a successful `parse` always yields `confidence ∈ CONFIDENCE_LABELS`; `serialize`/`parse` are deterministic for fixed inputs. Confirm they FAIL.

### Implementation for User Story 2

- [X] T009 [US2] Harden `parse` in `format.py` so body extraction preserves trailing newlines and interior `---` exactly (index-based slice from just after the closing fence). Make T007 + T008 pass. (Likely already satisfied by the T006 implementation; this task locks it under property tests and fixes any edge that the PBT surfaces.)

**Checkpoint**: Body fidelity is proven across arbitrary inputs; US1 + US2 both independently testable.

---

## Phase 5: User Story 3 - Reject malformed or unlabeled input (Priority: P2)

**Goal**: Missing fences, missing/extra front-matter keys, and unknown labels raise `MemoryFormatError` — never a defaulted or partial entry.

**Independent Test**: Feed text with no front-matter, an unterminated block, a missing `confidence` key, an extra key, and an unknown label; assert each raises with a message naming the defect.

### Tests for User Story 3 ⚠️ (write first, must FAIL)

- [X] T010 [P] [US3] Add failing unit tests to `tests/unit/test_memory_format.py`: `parse` raises `MemoryFormatError` for (a) text with no opening `---` fence, (b) an opening fence with no closing `---`, (c) front-matter omitting `confidence`, (d) front-matter with an extra key alongside `confidence`, (e) a `confidence` value outside the four labels, and (f) an empty/blank `confidence` value. Assert `MemoryFormatError` is a `ValueError` subclass and the message names the specific problem. Confirm they FAIL.
- [X] T011 [P] [US3] Add a failing property-based test to `tests/pbt/test_memory_format_pbt.py`: any front-matter whose `confidence` value is drawn from a strategy of strings NOT in `CONFIDENCE_LABELS` always raises `MemoryFormatError` (never returns an entry). Confirm it FAILS.

### Implementation for User Story 3

- [X] T012 [US3] Flesh out `parse`'s validation branches in `format.py`: distinct, message-bearing `MemoryFormatError` raises for missing opening fence, unterminated front-matter, missing `confidence` key, unexpected extra keys, and unknown/blank label value. Make T010 + T011 pass.

**Checkpoint**: Malformed input fails loudly and specifically; no silent defaulting path exists.

---

## Phase 6: User Story 4 - Serialize an entry for CLI / `--jq` (Priority: P3)

**Goal**: `MemoryEntry.to_dict()` yields a JSON-serializable mapping so entries flow through the existing CLI formatters and `--jq` later.

**Independent Test**: Call `to_dict()` on an entry and assert it is a plain mapping of the label + body that serializes to JSON with no custom encoder.

### Tests for User Story 4 ⚠️ (write first, must FAIL)

- [X] T013 [P] [US4] Add failing unit tests to `tests/unit/test_memory_entry.py`: `MemoryEntry("Inferred", "text").to_dict() == {"confidence": "Inferred", "body": "text"}`; `json.dumps(entry.to_dict())` succeeds with no custom encoder; the returned dict contains exactly the `confidence` and `body` keys. Confirm they FAIL.

### Implementation for User Story 4

- [X] T014 [US4] Implement `MemoryEntry.to_dict()` in `entry.py` returning `{"confidence": self.confidence, "body": self.body}` (typed `dict[str, str]`), with a full docstring. Make T013 pass.

**Checkpoint**: Entries are renderable as structured output, ready for the eventual CLI surface.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Meet the Definition of Done.

- [X] T015 [P] Export `ConfidenceLabel`, `CONFIDENCE_LABELS`, `MemoryEntry`, `serialize`, `parse`, and `MemoryFormatError` from `src/mixpanel_headless/_internal/memory/__init__.py`.
- [X] T016 [P] Ensure full Google-style docstrings (Summary/Args/Returns/Raises/Example where behavior isn't obvious) on every new class, method, and function in `memory/entry.py` and `memory/format.py`.
- [X] T017 Run `just typecheck` (mypy --strict) and resolve any `Any`/annotation gaps in the new modules (the `Literal` label + narrowing in `parse` are the likely friction points).
- [X] T018 Run `just test-cov` and confirm ≥90% coverage; add unit cases for any uncovered branch in `format.py`/`entry.py`.
- [ ] T019 (DEFERRED — needs full-codebase mutmut run) Run `just mutate` and `just mutate-check`; confirm ≥80% kill rate on `memory/format.py` and `memory/entry.py`. Note: mutmut's copy model can't be scoped to individual files, so this runs as part of the normal full-suite mutation pass. Evidence pending: both modules have branch coverage from parametrized unit tests + Hypothesis PBT on every accept/reject/round-trip path.
- [X] T020 Run `just check` (lint + fmt-check + typecheck + test-cov + build) and the `quickstart.md` snippets; fix any drift between the quickstart examples and the shipped signatures.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately.
- **Foundational (Phase 2)**: Depends on Setup. BLOCKS all user stories (`format` needs `MemoryEntry` + `CONFIDENCE_LABELS`).
- **US1 (Phase 3)**: Depends on Phase 2. MVP.
- **US2 (Phase 4)**: Depends on US1 (`serialize`/`parse` exist); hardens body fidelity on the same `format.py`.
- **US3 (Phase 5)**: Depends on US1 (`parse` exists); adds validation branches on the same `format.py`.
- **US4 (Phase 6)**: Depends on Phase 2 (`MemoryEntry` exists); adds `to_dict` on `entry.py`. Independent of the `format.py` stories.
- **Polish (Phase 7)**: Depends on all desired stories.

### User Story Dependencies

- US1 (P1) is the MVP and the base US2/US3 verify against.
- US2 and US3 both extend the US1 `parse`/`format.py`, so their implementation tasks touch a shared file and are **not** freely parallel with each other (sequence US1 → US2 → US3, or coordinate edits to `format.py`).
- US4 (P3) touches only `entry.py` and can proceed in parallel with the `format.py` stories once Phase 2 is done.

### Within Each Story

- Tests are written FIRST and must FAIL before implementation (strict TDD).
- Foundational `entry.py` before `format.py` (Phase 3+).

### Parallel Opportunities

- Phase 1: T001, T002 in parallel (distinct files).
- Phase 6 (US4) can run in parallel with Phases 4–5 (US2/US3) — different file (`entry.py` vs `format.py`).
- Test-authoring tasks marked [P] across stories touch distinct concerns and can be written in parallel; implementation tasks on `format.py` serialize (US1 → US2 → US3).

---

## Implementation Strategy

### MVP First

1. Phase 1 (Setup) → Phase 2 (Foundational: label set + entry, fully tested) → Phase 3 (US1 serialize/parse round-trip).
2. **STOP and VALIDATE**: an entry round-trips through text with its label intact. That is the demonstrable MVP.

### Incremental Delivery

US1 (round-trip) → US2 (body fidelity + PBT) → US3 (loud rejection) → US4 (`to_dict`) → Polish (coverage, mutation, docs, `just check`). Each phase leaves the module green and independently testable.

---

## Notes

- All new production code lives under `_internal/memory/` — nothing is added to the public `mixpanel_headless` surface in this slice (public exposure of the types is AIE-608).
- The slice performs no filesystem or network I/O; there is no integration-test tier and no backend byte-store change.
- Commit after each task or logical pair. Do not advance a phase while its tests are red for the wrong reason.
