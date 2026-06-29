---
description: "Task list for 046-alert-machine — single PR, sliced into US1 (baseline generator) -> US2 (profile-driven routing) -> US3 (deployment ergonomics)"
---

# Tasks: alert-machine — ML/stats anomaly + forecasting skill

**Input**: Design documents from `/specs/046-alert-machine/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [quickstart.md](quickstart.md)

**Tests**: This feature is a **skill**, not library code, so it is exempt from the `src/` mypy/pytest/coverage/mutation gates. The recipe templates ARE the test artifacts: each must run green (given its declared deps) against the public fixture project AND pass the reviewer checklist in [quickstart.md "Reviewer checklist"](quickstart.md#reviewer-checklist-merge-gate). Following the project's TDD discipline in spirit, every recipe family's **acceptance check is written first** (as a checklist row + a smoke invocation) and the template is then built until it passes that check. The final gate task (T030) runs the full quickstart merge-gate against `main`.

**Organization**: One PR. Tasks are grouped by user story so a reviewer can validate value incrementally:

| Slice | User story shipped | Task range |
|-------|--------------------|------------|
| Setup | scaffolding | T001–T004 |
| Foundational | shared template contract + SKILL.md skeleton | T005–T009 |
| US1 | baseline generator (P1, MVP) | T010–T015 |
| US2 | profile-driven recipe routing (P2) | T016–T024 |
| US3 | deployment ergonomics (P3) | T025–T028 |
| Polish + gate | review + merge gate | T029–T030 |

**Story dependency note**:
- US1 depends only on Foundational (the shared template contract).
- US2 depends on US1 (its recipes reuse the US1 generator scaffold — credentials, fetch, report, exit codes — and add profiling + routing).
- US3 depends on US1 (it documents and validates the exit-code contract US1 establishes).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story this task belongs to (US1 / US2 / US3) — omitted for Setup, Foundational, Polish
- All paths are project-relative

## Path Conventions

Skill source: `mixpanel-plugin/skills/alert-machine/`
Specs: `specs/046-alert-machine/`
No `src/` / `tests/` / `pyproject.toml` changes (FR-003).

---

## Phase 1: Setup (scaffolding)

**Purpose**: Create the skill directory tree and confirm the no-library-change constraint.

- [ ] T001 Create the skill directory tree: `mixpanel-plugin/skills/alert-machine/`, `.../references/`, `.../scripts/recipes/`.
- [ ] T002 [P] Read the two existing skills (`mixpanel-plugin/skills/mixpanelyst/SKILL.md`, `.../dashboard-expert/SKILL.md`) and `mixpanel-plugin/.claude-plugin/plugin.json` to lock the frontmatter conventions, `${CLAUDE_SKILL_DIR}` usage, and progressive-disclosure style before authoring.
- [ ] T003 [P] Transcribe the canonical section order (docstring, deps header, env-first creds, METRIC block, knobs, build_workspace/fetch/detect/report/main, 0/1/2 exit) from [spec.md § Canonical generated-script shape](spec.md#canonical-generated-script-shape) into a working note for the template contract (T005). The shape is fully specified in-repo; no external or private file is needed.
- [ ] T004 Establish a clean baseline: `git status` shows no `src/` / `tests/` / `pyproject.toml` changes are required by this feature; confirm the entire footprint will live under `mixpanel-plugin/skills/alert-machine/`.

**Checkpoint**: Directory tree exists, conventions and the canonical generated-script shape understood.

---

## Phase 2: Foundational (shared template contract — BLOCKS all recipes)

**Purpose**: Define the shared generated-script contract every recipe must honor, and stub the SKILL.md so the router exists before recipes are filled in.

**⚠️ CRITICAL**: T005–T009 MUST land before any recipe template (US1/US2). Every recipe is an instance of the T005 contract; writing recipes before the contract risks divergent exit-code / credentials / determinism behavior.

- [ ] T005 Author the shared generated-script contract section inside `mixpanel-plugin/skills/alert-machine/references/ml-recipes.md` (top of file): the mandatory section order, the env-first credentials policy (FR-014), the single `METRIC` block (FR-015), `RECENT_DAYS` (FR-016), the `0/1/2` exit-code contract (FR-017), determinism (FR-018), the explainable-report shape (FR-019), the bring-your-own-deps header (FR-020), the fail-fast import guard (FR-021), and the degenerate-math guards (FR-022). This is the spec every template is checked against.
- [ ] T006 [P] Write the reviewer-checklist acceptance criteria into `references/ml-recipes.md` (mirroring [quickstart.md "Reviewer checklist"](quickstart.md#reviewer-checklist-merge-gate)) so each recipe has a written pass/fail check BEFORE it is built (TDD-in-spirit: check first, template second).
- [ ] T007 Author `mixpanel-plugin/skills/alert-machine/SKILL.md` skeleton: frontmatter (`name: alert-machine`; `description:` = the exact auto-trigger string from [spec.md § Proposed SKILL.md description](spec.md#proposed-skillmd-description); `allowed-tools: Bash Read Write WebFetch`), plus the terse core-flow router (intent → family table, ground → validate → clarify → profile → route → generate). Defer API discovery to `help.py` + `llms.txt` (FR-004); use `${CLAUDE_SKILL_DIR}` for any bundled-script reference (FR-005). AK voice.
- [ ] T008 [P] Author `references/series-profiling.md`: how to compute the profile (length, trend, seasonality via ACF/STL, gaps, volume, distribution shape) and the routing rules from profile + intent → recipe family (FR-011, FR-012; per [research.md R-2, R-3](research.md#r-2-profile-the-series-before-picking-a-model)).
- [ ] T009 [P] Author the context + schema grounding section in `SKILL.md`: the priority order `get_business_context_chain()` > user `.md` > conversation (FR-006), and the pre-generation metric/property validation via `events()`/`top_events()`/`schema_graph()`/`property_values()` (FR-007, FR-008).

**Checkpoint**: The template contract, the router, the profiling guide, and the grounding rules exist. Recipes can now be built against a written acceptance check.

---

## Phase 3: User Story 1 — Baseline generator (Priority: P1) 🎯 MVP

**Goal**: The skill generates a runnable baseline anomaly detector (IsolationForest / robust z-score / EWMA) for a flat/non-seasonal metric, honoring the full template contract.

**Independent Test**: per spec.md §1 — describe a metric + a "drop" intent; receive a `.py` that resolves creds env-first, fetches via `Workspace.query(mode="timeseries")`, fits a baseline model, prints an explainable report, and exits `0`/`1`/`2`. Two runs on the same data agree (determinism).

### Acceptance check first (write the check, then the template)

- [ ] T010 [US1] Write the baseline-family catalog entry in `references/ml-recipes.md` (when-to-use, model, deps, template path, explainable-output shape) AND its checklist row — so the template's pass/fail bar is defined before it is built (FR-023, FR-024).

### Implementation for User Story 1

- [ ] T011 [P] [US1] Author `scripts/recipes/baseline_isolation_forest.py` — the canonical generated-script shape (spec § Canonical generated-script shape) as a public template: non-secret placeholder credentials, env-first resolution, single `METRIC` block, `RECENT_DAYS`/`RANDOM_STATE` knobs, IsolationForest over engineered features (value, pct_change, rolling z), explainable SPIKE/DROP report, `0/1/2` exit, `pip install mixpanel_headless scikit-learn` header, fail-fast import guard, zero-variance + gap + short-series + tz-normalization guards (FR-013 through FR-025).
- [ ] T012 [P] [US1] Author `scripts/recipes/baseline_robust_zscore.py` — the no-sklearn baseline: MAD/robust z-score and EWMA control chart in pure `numpy`/`scipy`, same contract, `pip install mixpanel_headless scipy` header. Covers short series where IForest is unstable.
- [ ] T013 [US1] Verify T011 against its checklist row (T006/T010): run it against the fixture project, confirm exit code ∈ {0,1,2}, confirm the explainable report renders, and confirm two runs agree (determinism, SC-002).
- [ ] T014 [US1] Verify T012 against the checklist the same way; confirm it runs with NO sklearn installed (only `mixpanel_headless` + scipy), proving the bring-your-own-deps story for a sklearn-free path.
- [ ] T015 [US1] Wire the baseline family into the `SKILL.md` router table (intent "is this number weird" / flat series → baseline; link the two templates via `${CLAUDE_SKILL_DIR}`).

**Checkpoint**: MVP. The skill can ground, validate, clarify, profile (flat), and generate a working baseline detector that drops into cron/CI. Demonstrable on its own.

---

## Phase 4: User Story 2 — Profile-driven recipe routing (Priority: P2)

**Goal**: The skill reads the series profile and routes to the family that fits — seasonality-aware, forecasting bands, changepoint, or multivariate/causal — never a naive z-score on a seasonal series. Each family ships a runnable template.

**Independent Test**: per spec.md §2 — a weekly-seasonal series routes to a seasonality-aware/forecasting recipe (not z-score) and the docstring names the seasonality as the reason; "expected vs actual" routes to a forecasting band; "regime shift" routes to changepoint; "did the release move it" routes to multivariate/causal; each generated script names its exact deps.

### Acceptance checks first

- [ ] T016 [P] [US2] Write the seasonality-aware, forecasting, changepoint, and multivariate/causal catalog entries in `references/ml-recipes.md` (when-to-use, model, deps, template path, explainable-output shape) AND their checklist rows (FR-023, FR-024) — before the templates are built.

### Implementation for User Story 2

- [ ] T017 [P] [US2] Author `scripts/recipes/seasonal_stl_residual.py` — STL decomposition (statsmodels) + residual outlier flagging; docstring states the weekly-seasonal rationale; `pip install mixpanel_headless statsmodels` header; honors the full template contract; report frames each flag as residual-vs-seasonal-baseline.
- [ ] T018 [P] [US2] Author `scripts/recipes/forecast_band_exit.py` — a forecasting recipe (Prophet or Holt-Winters/ETS) producing a forecast WITH prediction intervals; flags actuals that exit the band; report reads "expected X +/- Y, got Z; BAND_EXIT"; supports an N-day-ahead forecast; deps header names the chosen forecaster.
- [ ] T019 [P] [US2] Author `scripts/recipes/changepoint_ruptures.py` — ruptures PELT/BinSeg (and a pure-numpy CUSUM fallback) for permanent level/regime shifts; report names changepoint date(s), pre/post level, magnitude, SHIFT direction; `pip install mixpanel_headless ruptures` header.
- [ ] T020 [P] [US2] Author `scripts/recipes/multivariate_causal.py` — Mahalanobis/PCA-residual across a small correlated metric set (sklearn/numpy) AND a CausalImpact counterfactual path for "did the release move it"; report frames the result as per-day distance or effect-vs-counterfactual with a credible interval; deps header names the path's deps.
- [ ] T021 [US2] Verify T017–T020 against their checklist rows: each runs against the fixture project (with its declared deps installed), honors the `0/1/2` contract, is deterministic, and renders its family-specific explainable report.
- [ ] T022 [US2] Verify the routing in `references/series-profiling.md` end-to-end: a synthetic weekly-seasonal series routes to seasonal/forecasting (NOT baseline z-score) and the generated docstring cites the ACF/STL seasonality (SC-003).
- [ ] T023 [US2] Confirm fail-fast import guards on every US2 template: with only `mixpanel_headless` installed, each prints a clear "pip install X" line (not a bare `ModuleNotFoundError`) for its missing dep (FR-021, SC-005).
- [ ] T024 [US2] Wire all four US2 families into the `SKILL.md` router table with their intent triggers and `${CLAUDE_SKILL_DIR}` template links; cross-link `references/ml-recipes.md` and `references/series-profiling.md`.

**Checkpoint**: The skill routes by profile across all five families. The differentiator (not-just-a-z-score) is demonstrable.

---

## Phase 5: User Story 3 — Deployment ergonomics (Priority: P3)

**Goal**: The exit-code contract is documented and every template honors it; cron / CI / agent-loop snippets are copy-paste; `RECENT_DAYS` and the `METRIC` block are the only edits needed to tune or retarget.

**Independent Test**: per spec.md §3 — `references/deployment.md` documents `0/1/2` and provides cron, GitHub Actions, and agent-loop snippets; any template runs green in a clean container with credentials supplied via env only; editing `RECENT_DAYS` / `METRIC` tunes/retargets with no other edits.

- [ ] T025 [US3] Author `references/deployment.md`: the `0/1/2` exit-code contract (clean / recent anomaly / no data) plus copy-paste cron, GitHub Actions, and self-healing-agent-loop snippets (per [quickstart.md §3](quickstart.md#story-3-p2p3--deploy-in-cron--ci--an-agent-loop)).
- [ ] T026 [US3] Verify env-only deployment: run a US1 template in a clean environment supplying credentials ONLY via environment variables (no inline-block edit); confirm it runs green and the inline placeholders are never read (FR-014, SC-007).
- [ ] T027 [US3] Verify retarget/tune: edit `RECENT_DAYS` and confirm the trailing-window check changes; edit the single `METRIC` block (e.g. to `Purchase` / `sum` / `REVENUE`) and confirm the script retargets with no model/report/exit changes (FR-015, FR-016).
- [ ] T028 [US3] Link `references/deployment.md` from `SKILL.md` and confirm the exit-code contract text in `deployment.md` matches `ml-recipes.md` verbatim (single source of truth for the contract).

**Checkpoint**: Generated scripts are deployable in cron, CI, and agent loops straight from the references.

---

## Phase 6: Polish & merge gate

**Purpose**: Final review and the merge-gate run.

- [ ] T029 [P] Security + voice audit: run the [quickstart.md "Security verification"](quickstart.md#security-verification) grep over `scripts/recipes/` (no inline secrets; non-secret placeholders only); confirm `SKILL.md` and all template docstrings use AK voice (lowercase-leaning, no em-dashes, no AI tells, no Claude trailer).
- [ ] T030 **Final gate**: run the full [quickstart.md "Reviewer checklist" and "Smoke-test script"](quickstart.md#smoke-test-script-merge-gate) against `main`. Confirm: every recipe template honors the `0/1/2` contract, exposes `RECENT_DAYS` + a single `METRIC` block, resolves creds env-first, carries an exact deps header, fails fast on missing deps, is deterministic, and guards the degenerate-math cases; `SKILL.md` frontmatter is correct and terse; bundled paths use `${CLAUDE_SKILL_DIR}`; `help.py` is referenced not copied; and `git diff --stat` shows changes ONLY under `mixpanel-plugin/skills/alert-machine/` (SC-006). This is the equivalent of `just check` for a skill-only feature: it MUST be green before the PR opens.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup. **Blocks all recipes** — the template contract (T005) is the spec every recipe is checked against.
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)**: depends on US1 (reuses the US1 generator scaffold; adds profiling + the four non-baseline families).
- **US3 (Phase 5)**: depends on US1 (documents/validates the exit-code contract US1 establishes); US2 templates also benefit but US3 can validate against US1 alone.
- **Polish + gate (Phase 6)**: depends on all desired stories being complete.

### Within each user story

- The acceptance check (catalog entry + checklist row) is written BEFORE the template it gates (TDD-in-spirit: check first, template second).
- The template contract (T005) before any template.
- Templates before they are wired into the `SKILL.md` router.
- Each template is verified against its checklist row before the story closes.

### Parallel opportunities

- Setup tasks T002, T003 are [P] (independent reads).
- Foundational tasks T006, T008, T009 are [P] (different files / sections) once T005 lands.
- Within US1: the two baseline templates T011, T012 are [P] (different files).
- Within US2: the catalog entries (T016) gate, then the four family templates T017–T020 are all [P] (different files).
- Polish T029 is [P] with the final gate prep.

---

## Parallel example: User Story 2 recipe templates

```bash
# After T016 lands the catalog entries + checklist rows, build the four families in parallel:
Task: "Author scripts/recipes/seasonal_stl_residual.py"       # T017
Task: "Author scripts/recipes/forecast_band_exit.py"          # T018
Task: "Author scripts/recipes/changepoint_ruptures.py"        # T019
Task: "Author scripts/recipes/multivariate_causal.py"         # T020
```

---

## Implementation strategy

### MVP first (US1 only)

1. Phase 1 Setup.
2. Phase 2 Foundational (template contract + SKILL.md skeleton + profiling/grounding).
3. Phase 3 US1 (baseline generator).
4. **STOP and validate**: smoke-test the quickstart §1 (P1 story) against the fixture project; confirm determinism and the exit-code contract.

This MVP gives users a working baseline detector that drops into cron/CI — real value without the seasonality/forecasting/causal families.

### Incremental delivery (within the one PR)

- US1 → baseline detector, deployable.
- US2 → profile-driven routing across all five families (the differentiator).
- US3 → documented deployment contract + tune/retarget validation.

### Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps task to user story for traceability.
- The recipe templates ARE the test artifacts; their checklist rows ARE the tests, written first.
- No `src/` / `tests/` / `pyproject.toml` edits — the final gate (T030) enforces this via `git diff --stat`.
- AK voice on all shipping copy (`SKILL.md`, template docstrings); the spec/plan/research/quickstart docs are normal technical prose.
- Stop at the US1 checkpoint to validate the MVP independently before building US2/US3.
