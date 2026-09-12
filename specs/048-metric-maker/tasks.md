---
description: "Task list for 048-metric-maker — the lego-block architect skill (consumes feature 047; no library change)"
---

# Tasks: metric-maker skill

**Input**: Design documents from `/specs/048-metric-maker/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [quickstart.md](quickstart.md)

**HARD PREREQUISITE**: **feature 047-behaviors-metrics-formulas MUST be merged/released before this feature begins.** The skill calls `ws.create_behavior` / `ws.create_metric` / `ws.create_formula` and relies on their `Create*Params` validators — all shipped by 047. Without 047 there is nothing to orchestrate and no validation safety net. The dependency is one-way: 047 has no dependency on 048. T001 below verifies the prerequisite is present before any other work starts.

**Tests**: The only executable code this feature adds is the bundled `plan_kit.py` helper, which IS unit-tested TDD-style (test FIRST, fails, then implemented). The skill body (SKILL.md + references) is verified via skill evals per the plugin convention. No new library code is added (SC-006).

**Organization**: Single PR — the skill only. No `src/mixpanel_headless/` change.

| Block | User stories | Task range |
|-------|--------------|------------|
| Setup + prerequisite check | — | T001–T002 |
| Helper script (TDD) | US2 | T003–T006 |
| SKILL.md + references (build outputs) | US1, US2, US3 | T007–T015 |
| Skill verification | US1, US2, US3 | T016–T019 |
| Final gate | — | T020–T022 |

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 — omitted for Setup, gates
- All file paths are project-relative

## Path Conventions

Plugin skill (no library change):
- Skill: `mixpanel-plugin/skills/metric-maker/`
- Tests (helper only): `tests/unit/`
- Specs: `specs/048-metric-maker/`

---

## Phase 1: Setup + prerequisite check

- [ ] T001 **Verify the feature-047 prerequisite is present.** Confirm the released `Workspace` exposes the behaviors / metrics / formulas CRUD (`python help.py Workspace.create_metric`, `python help.py CreateFormulaParams`, `python help.py search behavior` all resolve). If absent, STOP — feature 047 must be merged/released first. This is the hard gate for the whole feature.
- [ ] T002 Run `just install-hooks` (no-op if already installed) and `just check` against `main` to establish a clean baseline before any new work lands.

**Checkpoint**: 047 surface confirmed present, baseline clean.

---

## Phase 2: The `plan_kit.py` helper (TDD — the only tested code)

**Goal**: A pure-stdlib helper that emits the dry-run artifacts and NEVER writes to Mixpanel.

**Independent Test**: per spec.md US2 / SC-005 — the helper, given a kit spec, emits a recommendations `.md` (one section per block with name + definition + rationale) AND a runnable `.py` that compiles and imports `mixpanel_headless`; the helper invokes NO `create_*` call.

- [ ] T003 [US2] Add `tests/unit/test_metric_maker_plan_kit.py`: the `plan_kit.py` helper, given a kit spec (list of typed block descriptors), emits a recommendations markdown (one section per block with name + definition + rationale) AND a runnable `.py` that imports `mixpanel_headless` and calls the right `create_*`; the emitted `.py` is syntactically valid (`compile()`); NO `create_*` is invoked by the helper itself (it only writes files). Run now — MUST fail (script does not exist).
- [ ] T004 [US2] Confirm `mixpanel-plugin/skills/metric-maker/scripts/plan_kit.py` does not exist yet — confirm T003 fails for the right reason.
- [ ] T005 [US2] Create `mixpanel-plugin/skills/metric-maker/scripts/plan_kit.py` implementing the dry-run artifact emitter so T003 passes. Pure stdlib; emits `metric_maker_plan.md` + `metric_maker_plan.py`. Full docstrings, mypy --strict clean. Bundled-script path referenced via `${CLAUDE_SKILL_DIR}` in the SKILL.md.
- [ ] T006 [US2] Run T003 — passes. Run `just typecheck` over the new script.

**Checkpoint**: The artifact emitter works and provably never writes to Mixpanel.

---

## Phase 3: SKILL.md + references (build outputs)

**Goal**: Author the skill body. These references are BUILD OUTPUTS of this feature, written here — not pre-existing repo files.

- [ ] T007 [P] [US1] Write `mixpanel-plugin/skills/metric-maker/SKILL.md`. Frontmatter `name`/`description`/`allowed-tools` matches spec.md §"Proposed SKILL.md description trigger text" EXACTLY — including the reciprocal negative-routing clauses (does NOT clean up / govern the data dictionary = data-clean-up; does NOT build dashboards = dashboard-expert; defers raw querying to mixpanelyst). AK voice in any user-facing copy (lowercase-leaning, direct, no em-dashes, no AI tells). Body: terse, table-driven, progressive disclosure into `references/`. The CORE FLOW (ground → design starter kit → dry-run plan → approval pause → validate+create → verify → report IDs). DEFER API teaching to `https://mixpanel.github.io/mixpanel-headless/llms.txt` and `help.py`; do NOT re-teach the API; do NOT triplicate help.py.
- [ ] T008 [P] [US1] Write `references/lego-catalog.md`: the compression pyramid (raw events → clean events → behaviors → metrics / formulas, each compressing the layer below into business language) + the block taxonomy (custom event, analytical custom property, cohort, behavior, metric, formula) + when to reach for each + which `Workspace` method creates it + the feature-047 validator gotchas (math enum, property object, step counts, funnel_order, formula variables) cross-referenced to the 047 contracts (`specs/047-behaviors-metrics-formulas/contracts/payload-shapes.md`). Note the lineage of the consumed primitives: cohort blocks build on features 035-cohort-definition-builder / 036-cohort-behaviors; analytical custom-property blocks on feature 037-custom-properties-queries; custom-event / custom-property creation on feature 027-data-governance-crud; cohort create on feature 024-core-entity-crud.
- [ ] T009 [P] [US1] Write `references/naming-taste.md`: business-vocabulary naming rules (Power Buyers / Activated User / Weekly Active Account over jargon), the "simplify aggressively over precise-but-mysterious" rule, the publisher stance (every block is a saved, named, reusable entity with a one-line rationale — never an anonymous inline one-off), definition + one-line rationale requirement, the never-"Cohort 1" rule, and the duplicate-check-first rule.
- [ ] T010 [P] [US1] Write `references/formula-cookbook.md`: custom-property + formula patterns in the Mixpanel formula language (LET/IFS/REGEX_*, PCRE2 quirks) distilled from the mixpanelyst custom-property reference, plus formula-entity patterns (rates, ratios, per-user) mapping to feature-047's `CreateFormulaParams`. Scope to ANALYTICAL custom properties (bucketing/dimensions); explicitly send messy-string cleanup to data-clean-up.
- [ ] T011 [P] [US1] Write `references/starter-kits-by-vertical.md`: the universal archetype spine (acquisition, activation, engagement + stickiness, retention, revenue / value) as the default, then ecommerce / SaaS / content / gaming specializations, each as a coherent named kit with definitions + rationale, sized to a typical schema. Distilled from the power-tools behaviors prompt (https://github.com/mixpanel/mixpanel-power-tools, path `templates/prompts/ai-behaviors-metrics-system.txt`, schema-analysis guidelines).
- [ ] T012 [US1] Add the grounding + design workflow to SKILL.md: grounding priority order business-context-chain → user `.md`/paste → ask; mandatory first data move `schema_graph(include_density=True)` + `property_values`; recognize the universal dataset classes (identity / attribution / platform / geo / time / value) by shape; default the kit to the universal archetype spine (acquisition / activation / engagement + stickiness / retention / revenue) then specialize per vertical, omitting archetypes the data cannot support; lead block decisions with cardinality / fill-rate counts (not vibes); rank by impact, head first; check `list_*` before proposing each block.
- [ ] T013 [US2] Add the write-safety + execution workflow to SKILL.md: produce the dry-run artifact via `${CLAUDE_SKILL_DIR}/scripts/plan_kit.py`; PAUSE for one approval; on approval validate (e.g. `validate_custom_property`) → create via the released `Workspace` CRUD → re-fetch to verify → report IDs; surface the feature-047 `ValidationError`s rather than bypassing them; refuse irreversible governance ops.
- [ ] T014 [US3] Add the handoff section to SKILL.md: structured ID report grouped by type; explicit next-step handoff to dashboard-expert (metric/formula IDs) and data-clean-up (annotation/tagging); partial-failure reporting (created vs failed, no rollback); stop-at-dashboard boundary; defer raw querying to mixpanelyst.
- [ ] T015 [US1] Add the missing-prerequisite guard to SKILL.md: if the installed `Workspace` lacks `create_metric` / `create_behavior` / `create_formula` (feature 047 not installed), tell the user to upgrade `mixpanel-headless` rather than failing mid-execute.

**Checkpoint**: SKILL.md + references authored; the full ground → design → dry-run → approve → execute → verify → handoff flow documented.

---

## Phase 4: Skill verification

- [ ] T016 [US1] Skill eval (design): on a clean e-commerce fixture project, invoke the skill via the documented trigger phrases; assert every proposed block has a business name + definition + rationale, references only properties present on its events (verified against `schema_graph`), and duplicates no existing entity of the same type (SC-002).
- [ ] T017 [US2] Skill eval (no-write-before-approval): assert the skill produces `metric_maker_plan.md` + `metric_maker_plan.py`, and `list_metrics()`/`list_behaviors()`/`list_formulas()` counts are UNCHANGED before approval (SC-001). After approval, the kit is created, re-fetched/verified, IDs reported grouped by type; a deliberately-injected mid-kit failure is reported as created-vs-failed with no rollback (SC-003).
- [ ] T018 [US3] Skill eval (handoff): the final output names dashboard-expert + data-clean-up and supplies the metric/formula IDs in a machine-readable handoff (SC-003).
- [ ] T019 [US1] Trigger eval: verify the SKILL.md `description` fires on the documented metric-creation / building-block / "set up metrics" phrases and does NOT fire on raw-query phrasing (mixpanelyst), governance / "clean up" / "organize the data dictionary" / "hide noise" / "flag PII" phrasing (data-clean-up), or dashboard-building phrasing (dashboard-expert) — the reciprocal of data-clean-up's trigger eval. Use the skill-creator eval harness if available (SC-004).

**Checkpoint**: skill verified: design, dry-run/approve/execute/verify, handoff, and routing all pass.

---

## Phase 5: Final gate

- [ ] T020 [P] Confirm the PR touches NO file under `src/mixpanel_headless/` (SC-006) — this is a skill-only feature.
- [ ] T021 [P] Update `CHANGELOG.md` with an `Unreleased — metric-maker skill (048)` heading documenting the new skill and noting it requires feature 047 (behaviors / metrics / formulas CRUD).
- [ ] T022 Run `just check` end-to-end one final time. MUST be green: lint + format + typecheck (incl. the `plan_kit.py` helper) + tests + build. This is the merge gate for the PR.

**Checkpoint**: PR ready to merge. The metric-maker skill ships on top of the released feature-047 surface.

---

## Dependencies & Execution Order

### Cross-feature dependency

- **Feature 047-behaviors-metrics-formulas MUST be merged/released first.** T001 verifies it; everything else depends on T001.

### Phase dependencies

- **Setup (T001–T002)**: T001 (047 prerequisite) BLOCKS everything.
- **Helper (T003–T006)**: depends on Setup. TDD — T003 fails before T005 implements.
- **SKILL.md + references (T007–T015)**: depend on the helper existing (the SKILL.md references `plan_kit.py` via `${CLAUDE_SKILL_DIR}`).
- **Skill verification (T016–T019)**: depends on the SKILL.md + references being authored.
- **Final gate (T020–T022)**: depends on everything.

### Parallel opportunities

- Setup T002 follows T001.
- Reference files T008–T011 are [P] (independent Markdown files); SKILL.md (T007) can be drafted in parallel with them, but T012–T015 amend SKILL.md and are sequential.
- Gate tasks T020 and T021 are [P] (different files).

---

## Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps task to user story for traceability.
- **The hard prerequisite is feature 047**: do not start before it is merged/released (T001 is the gate).
- This feature adds NO library code; the PR touches no `src/mixpanel_headless/` file (SC-006).
- The only tested code is `plan_kit.py`; the skill body is eval-verified.
- The write-safety guarantee (no write before approval) is machine-checkable via the helper test (the helper never writes) plus the no-write-before-approval skill eval.
- Skill copy is AK voice (lowercase-leaning, no em-dashes, no AI tells, no Claude trailers); the spec docs are normal technical prose.
- The references and the `plan_kit.py` helper are BUILD OUTPUTS authored during implementation, not pre-existing repo files.
