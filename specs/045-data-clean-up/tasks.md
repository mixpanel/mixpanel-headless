---
description: "Task list for 045-data-clean-up — a single-PR governance skill (Markdown assets + one TDD'd drift-check script)"
---

# Tasks: `data-clean-up` — a Mixpanel governance skill

**Input**: Design documents from `/specs/045-data-clean-up/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [quickstart.md](quickstart.md)

**Tests**: REQUIRED for the one piece of shipped code. The project CLAUDE.md mandates strict TDD ("write tests FIRST, before any implementation code"), 90% coverage minimum, complete docstrings, and a green `just check`. The ONLY shipped code is `mixpanel-plugin/skills/data-clean-up/scripts/governance_check_template.py`; its drift-detection logic is written test-first (T010–T012 before T013–T016). The Markdown skill assets (SKILL.md + references) are taste/trigger reviewed, not unit-tested, but they have explicit authoring + review tasks and a trigger-eval task.

**Organization**: One PR. Tasks are grouped by user story so each story is independently reviewable. Because this is a skill, "implementation" of US1/US2 is largely authoring the SKILL.md flow + reference docs that encode the behavior; US3 carries the only TDD'd code.

| PR | User stories shipped | Task range |
|----|----------------------|------------|
| PR 1 | US1 (cleanup flow + taste) + US2 (PII gating) + US3 (drift-check + bundled tested script) | T001–T040 |

**Story dependency note**:
- US1 (cleanup flow) depends only on Foundational (skill scaffold + grounding/taste references).
- US2 (PII gating) layers a PII section + separate-confirmation rule onto US1's plan/approve flow.
- US3 (drift-check) depends on US1 having defined `governance_spec.json` shape; the bundled script + its tests are independent of US1/US2 prose and can be built in parallel.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story this task belongs to (US1 / US2 / US3) — omitted for Setup, Foundational, and Polish
- All file paths are absolute or repo-relative as noted

## Path Conventions

- Skill assets: `mixpanel-plugin/skills/data-clean-up/`
- Bundled script: `mixpanel-plugin/skills/data-clean-up/scripts/`
- Tests for the bundled script: `tests/unit/plugin/`
- Fixtures: `tests/fixtures/governance/`
- Specs: `specs/045-data-clean-up/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Establish a clean baseline and the plugin-test plumbing the bundled script needs.

- [ ] T001 Run `just check` against `main` to establish a clean baseline (lint + format + typecheck + tests + coverage + build all green) before any new work lands. Record the pass counts.
- [ ] T002 [P] Create the skill directory tree: `mixpanel-plugin/skills/data-clean-up/{references,scripts}/`. Confirm it sits alongside the existing `skills/mixpanelyst/` and `skills/dashboard-expert/`.
- [ ] T003 Establish `tests/unit/plugin/` and wire the bundled script into the project's coverage + mypy scope so `governance_check_template.py` is type-checked and coverage-counted by `just check`. If a `conftest.py` path-insert or coverage `source` entry is needed for `mixpanel-plugin/skills/data-clean-up/scripts/` to be importable, add it here. Run `just check` again to confirm the plumbing change is green and the (still-absent) script does not break collection.

**Checkpoint**: Skill scaffold exists; plugin-script test path is importable and gated.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Capture the grounding order, the keep/hide taste, and the annotation rules in `references/` — the load-bearing judgment every user story reads. These must exist before the SKILL.md flow can reference them.

**⚠️ CRITICAL**: T004–T007 MUST land before US1's SKILL.md flow (T013+) can cite them.

- [ ] T004 [P] Author `mixpanel-plugin/skills/data-clean-up/references/governance-taste.md` — distilled from [research.md §R-2b, §R-2c, §R-3, §R-3b](research.md). MUST include verbatim: the universal dataset-spine classes (identity / attribution / platform / geo / time / value) and their per-class default treatment (§R-2b); the five-axis evidence base — coverage, value distribution + cardinality, type consistency, casing inconsistency, numeric-stored-as-string (§R-2c); the four guiding principles (less-visible-is-better soft target <50 events / <100 props; coverage is a signal not a gate; KEEP-iff triad; judgment-not-threshold); the KEEP list and HIDE list; ALL FOUR worked examples (browser vs browser_version at equal coverage; granularity discrimination on `*_version`/`*_ms`/raw variants; utm_source sparse-but-keep; soft-target-is-a-direction); and the P0/P1/P2 head-first ordering with the count-led / back-of-napkin framing (§R-3b). AK voice for any user-facing copy (lowercase-leaning, direct, no em-dashes, no AI tells).
- [ ] T005 [P] Author `mixpanel-plugin/skills/data-clean-up/references/display-name-and-annotation-rules.md` — from [research.md §R-4](research.md): display-name derivation (snake/camel/ALL_CAPS → Title Case; `ios_` → "(iOS)" suffix; feature grouping with ":"); description grounding rule (domain-specific, never a generic stub) with a worked good-vs-bad example; `example_value` sourcing from `property_values`; the batched-tail rule ("confident on N, need your call on M"); tag vocabulary (plain domain categories, no emoji, only on described entities); `verified` and `sensitive` semantics.
- [ ] T006 [P] Author `mixpanel-plugin/skills/data-clean-up/references/drift-check.md` — from [research.md §R-9](research.md): the `governance_spec.json` shape (events, properties, expected coverage, annotations, hidden set); the five drift classes (new un-annotated entity, dropped governed entity, rename, coverage shift, re-appeared noise); the exit-code contract (0 = clean, non-zero = significant drift); and how the skill stamps a project-specific `governance_check.py` from the bundled template.
- [ ] T007 Cross-check the three references against the FRs: every FR-004a..FR-008a and FR-005..FR-029 behavior (including the spine recognition FR-004a, the evidence base FR-004b, the P0/P1/P2 ordering FR-006a, and the data-quality defects FR-008a) is described in at least one reference. Note any gap in a checklist comment at the top of `governance-taste.md`.

**Checkpoint**: The judgment is captured. SKILL.md authoring can begin.

---

## Phase 3: User Story 1 — Clean up a noisy project end-to-end (Priority: P1) 🎯 MVP

**Goal**: A terse, table-driven `SKILL.md` that, on a governance ask, runs the 8-step flow: ground (business-context + schema_graph + sample) → classify every entity per the taste → compute the plan → batch the un-inferable tail into one question → write the dry-run artifact pair → pause for one approval → execute the bulk write autonomously → verify by re-fetch + diff (+ optionally seed business-context).

**Independent Test**: per spec.md §1 — pointed at a project with business context + a noisy schema, the skill produces a `governance_plan.md` whose KEEP/HIDE/ANNOTATE/TAG decisions match the taste, surfaces exactly the un-inferable entities as a batched question, and after one approval issues `bulk_update_*` calls that a re-fetch confirms.

### SKILL.md authoring (the flow that encodes US1 behavior)

- [ ] T008 [P] [US1] Draft the `SKILL.md` frontmatter: `name: data-clean-up`; `description:` exactly the proposed trigger string from [spec.md FR-033](spec.md) (auto-fires on clean up / organize / set up / data dictionary / Lexicon cleanup / display names / hide noise / tag events / verify / flag PII; defers dashboards → dashboard-expert, metrics → metric-maker); `allowed-tools: Bash Read Write WebFetch`.
- [ ] T009 [US1] Author the `SKILL.md` body matching the house style of `skills/mixpanelyst/SKILL.md` and `skills/dashboard-expert/SKILL.md` (terse, table-driven, progressive disclosure). It MUST contain: a mode/flow table for the 8-step flow; the mandatory grounding order (FR-001/FR-002/FR-003) with the exact `ws.get_business_context_chain()` then `ws.schema_graph(include_density=True)` first moves; pointers to the three references for taste, naming, and drift; the write-safety gate (dry-run pair → one approval → bulk execute → verify); the API-discovery note that defers to `${CLAUDE_SKILL_DIR}`-relative `help.py` and `WebFetch https://mixpanel.github.io/mixpanel-headless/llms.txt` (and does NOT bundle help.py); and an explicit out-of-scope line (no dashboards, no metrics/cohorts). Keep it under the size of `dashboard-expert/SKILL.md`.

### Verify User Story 1

- [ ] T010 [US1] Walk the SKILL.md flow by hand against the quickstart §1 narrative (dry, no live project): confirm every numbered step maps to a documented `Workspace` method that exists per `help.py` (`get_business_context_chain`, `schema_graph`, `property_values`, `bulk_update_event_definitions`, `bulk_update_property_definitions`, `update_property_definition`, `list/create_lexicon_tag`, `set_business_context`). Flag any method name the skill cites that `help.py` does not resolve.
- [ ] T011 [US1] Confirm the SKILL.md encodes: bulk-not-single writes (FR-018), verified-on-kept-and-annotated (FR-016), tags-only-on-described (FR-017), no-silent-guess / batched tail (FR-014), and idempotent re-run (FR-025). Each must be a discoverable line in SKILL.md or a cited reference.

**Checkpoint**: US1 cleanup flow authored and self-consistent with the live API surface.

---

## Phase 4: User Story 2 — Surface and gate PII without auto-deleting (Priority: P2)

**Goal**: The plan grows a dedicated PII section with severity; PII `sensitive`/hide rides a SEPARATE confirmation distinct from the main approval; nothing is ever auto-deleted/dropped/merged.

**Independent Test**: per spec.md §2 — pointed at a schema with `$email`/`phone_number`/`ssn`/`dob`, the plan has a `## PII candidates` section with severity; approving the main plan but declining the PII subset leaves PII untouched; approving the subset sets `sensitive` and never deletes.

### Implementation for User Story 2 (authoring)

- [ ] T012 [P] [US2] Extend `references/display-name-and-annotation-rules.md` (or a focused `## PII` block in SKILL.md) with: the PII-name detection set (`$email`, `$phone`, `phone_number`, `ssn`, `address`, `dob`, `$first_name`, `$last_name`, `full_name`); the severity rubric; the rule that `sensitive`/hide require a SEPARATE confirmation from the main approval (FR-020, FR-023); and the absolute "never auto-delete / auto-drop / auto-merge" rule.
- [ ] T013 [US2] In SKILL.md, add the PII step to the flow: detect during classification, render a `## PII candidates` section in `governance_plan.md`, surface it for a distinct confirmation, action `sensitive` only on the approved subset, record declined PII as "flagged, not actioned (awaiting privacy decision)".

### Verify User Story 2

- [ ] T014 [US2] Confirm the SKILL.md + reference make it impossible to read the flow and conclude PII is auto-actioned: the main-approval and PII-approval are visibly distinct gates, and merge/delete/drop-filter carry their own extra-explicit confirmation naming the irreversible/data-loss consequence (FR-023).

**Checkpoint**: US1 + US2 flows coherent; PII is gated and never auto-actioned.

---

## Phase 5: User Story 3 — Emit a re-runnable drift-check artifact (Priority: P2)

**Goal**: Ship the ONLY tested code: `governance_check_template.py` — a standalone, env-first, schema_graph-vs-spec drift checker that exits non-zero on significant drift. The skill stamps a project-specific `governance_check.py` from it after a cleanup, alongside `governance_spec.json`.

**Independent Test**: per spec.md §3 — the bundled template's drift logic, run against fixture (spec, live) pairs, exits 0 on the clean pair and non-zero on the drifted pair, naming each injected drift class; the emitted checker round-trips against a just-governed project.

### Tests for User Story 3 (write FIRST, ensure they FAIL before implementation) ⚠️

- [ ] T015 [P] [US3] Create fixtures in `tests/fixtures/governance/`: `governance_spec_sample.json` (a governed snapshot — events + properties + expected per-(event,property) coverage + annotations + hidden set), `live_schema_clean.json` (matches the spec exactly → zero drift), and `live_schema_drifted.json` (each drift class injected: one new un-annotated event, one dropped governed/verified event, one renamed entity, one coverage shift beyond threshold, one re-appeared-noise hidden→visible). Document each injected drift in a top-of-file comment.
- [ ] T016 [P] [US3] Write `tests/unit/plugin/test_governance_check_template.py` (test-first; MUST FAIL — no implementation yet). Cover: clean pair → `detect_drift(spec, live)` returns empty + the script exits 0; drifted pair → returns one finding per injected class, each naming the offending entity, + the script exits non-zero; the coverage-shift threshold boundary (just-under = no drift, just-over = drift); each public function has a docstring-tested example. Use the project's established unit-test patterns (read a neighbor test file first for fixture/mocking conventions). Run now — they MUST fail.

### Implementation for User Story 3

- [ ] T017 [US3] Implement `mixpanel-plugin/skills/data-clean-up/scripts/governance_check_template.py` to pass T016. The shape (defined inline, no private-file dependency): inline `# /// script` (or pip-header) dependency note; env-first credentials (`MP_USERNAME`/`MP_SECRET`/`MP_PROJECT_ID`/`MP_REGION` per CLAUDE.md) with inline fallbacks and no secrets in source; load `governance_spec.json`; fetch live via `ws.schema_graph(include_density=True)`; a pure `detect_drift(spec: dict, live: dict) -> list[DriftFinding]` function (the unit-tested core, no I/O); a `main()` that fetches, diffs, prints a report, and `sys.exit`s non-zero on significant drift. Full Google-style docstrings on every function with markdown-fenced examples (NOT doctest `>>>`). mypy --strict clean, no unjustified `Any`.
- [ ] T018 [US3] Run T016 — all tests now pass. Run `mypy --strict` on the template — clean.
- [ ] T019 [US3] In `references/drift-check.md`, document how the skill stamps `governance_check.py` from the template after a cleanup (substitute project id / region / spec path), and that both `governance_spec.json` and `governance_check.py` are written to the user's chosen output directory and owned by the user (cron/CI), not committed.

### Verify User Story 3

- [ ] T020 [US3] Run `just test-cov` scoped to the new test file — confirm ≥90% line coverage on `governance_check_template.py` (the `detect_drift` core and `main` paths). Add tests for any uncovered branch (e.g. missing-spec-file error path).
- [ ] T021 [US3] Confirm the template carries no secrets in source (env-first), and that running it with no env vars and no inline creds fails with a clear actionable message rather than a traceback.

**Checkpoint**: The drift-checker ships, fully tested and type-checked; the skill knows how to stamp it.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Trigger accuracy, optional business-context seeding, and the final gate.

- [ ] T022 [P] In SKILL.md, document the optional `ws.set_business_context()` seed-back step (FR-030) as a write under the same approval gate (only on explicit user approval after the schema is learned).
- [ ] T023 [P] Trigger eval: verify the `description` auto-fires on the spec's trigger phrases ("clean up this project", "organize the schema", "set up the data dictionary", "Lexicon cleanup", "write display names", "hide the noise", "tag events", "mark verified", "flag PII") AND does NOT fire on pure dashboard / metric-creation asks (those must route to `dashboard-expert` / `metric-maker`). Use the skill-creator eval harness if available; otherwise record a manual phrase/expected-fire table in the PR description. Tune the `description` if any phrase misfires.
- [ ] T024 [P] Confirm `mixpanel-plugin/.claude-plugin/plugin.json` needs no change (skills auto-discover from `skills/`); if a manifest skill list exists, add `data-clean-up`.
- [ ] T025 [P] Run `quickstart.md` end-to-end against a fixture/demo project (dry where live creds are unavailable): produce a `governance_plan.md`, approve, execute, verify by re-fetch, emit `governance_spec.json` + `governance_check.py`, then run the emitted checker (exits 0), inject a drift, re-run (exits non-zero). Record results.
- [ ] T026 Author voice + AI-tell pass on every shipped Markdown string (SKILL.md description + any user-facing copy): lowercase-leaning, direct, no em-dashes, no "Generated with Claude" / Co-Authored-By trailers, no AI tells. Spec/plan/research prose stays normal technical prose.
- [ ] T027 **FINAL GATE**: run the `just check` equivalent (lint + `ruff format --check` + `mypy --strict` + `test-cov` ≥90% + build) and confirm it is GREEN with the new template + tests included. This is the merge gate; the PR does not open until it passes. Record the final pass/skip/coverage counts.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup. **Blocks the SKILL.md authoring** (US1/US2 cite the references).
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)**: depends on US1 (layers PII onto US1's plan/approve flow).
- **US3 (Phase 5)**: depends only on the `governance_spec.json` shape defined in T006/drift-check.md; the bundled script + tests are otherwise independent and can run in parallel with US1/US2 authoring.
- **Polish (Phase 6)**: depends on all stories; T027 is the final gate.

### Within each user story

- For the bundled script (US3): tests (T015, T016) MUST be written and FAIL before implementation (T017).
- References before the SKILL.md that cites them.
- SKILL.md flow before its verify tasks.
- `just check` MUST pass at the end (T027) before opening the PR.

### Parallel opportunities

- Setup T002 is [P].
- Foundational T004/T005/T006 are [P] (three different reference files).
- US3 fixtures (T015) and tests (T016) are [P] with each other and with US1/US2 prose authoring.
- Polish T022/T023/T024/T025 are [P].

---

## Parallel example: Foundational references

```bash
# Three reference docs, three files, no shared state:
Task: "Author references/governance-taste.md"                       # T004
Task: "Author references/display-name-and-annotation-rules.md"      # T005
Task: "Author references/drift-check.md"                            # T006
```

## Parallel example: User Story 3 (the tested code)

```bash
# Fixtures and failing tests first, in parallel:
Task: "Create tests/fixtures/governance/{spec,clean,drifted}.json" # T015
Task: "Write tests/unit/plugin/test_governance_check_template.py"  # T016
# then implement to green:
Task: "Implement scripts/governance_check_template.py"             # T017
```

---

## Implementation strategy

### MVP first (US1 only)

1. Phase 1 Setup.
2. Phase 2 Foundational (the taste + naming + drift references).
3. Phase 3 US1 (SKILL.md cleanup flow).
4. **STOP and validate**: walk the quickstart §1 flow; confirm every cited method resolves in `help.py`.

This MVP gives a working cleanup flow grounded in the taste, behind one approval, with bulk writes and verify — value delivered even if PII gating and the drift-checker never ship.

### Incremental delivery

- US1 → curated Lexicon behind one approval.
- US2 → PII surfaced and separately gated.
- US3 → durable drift-check the user owns; the only tested code.

### Notes

- The ONLY code under the strict gates is `governance_check_template.py`; everything else is reviewed Markdown.
- Bulk-write, no-auto-delete, no-silent-guess, and separate-PII-gate are non-negotiable review checks on the SKILL.md.
- Do NOT bundle a copy of `help.py`; reference it via `${CLAUDE_SKILL_DIR}` / hosted docs.
- T027 (`just check` green) is the hard merge gate.
