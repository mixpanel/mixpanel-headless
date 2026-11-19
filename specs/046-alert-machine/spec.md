# Feature Specification: alert-machine — ML/stats anomaly + forecasting skill

**Feature Branch**: `046-alert-machine`
**Created**: 2026-06-28
**Status**: Draft
**Input**: User description: "An ML/stats skill that joins Mixpanel real-time data with the open-source Python ML ecosystem to generate standalone, runnable anomaly-detection / forecasting scripts the user owns. NO library change."

## Overview

`alert-machine` is a **skill** (not a library feature). It ships under `mixpanel-plugin/skills/alert-machine/` and contributes **zero** changes to the `mixpanel_headless` Python package. Its single deliverable is a standalone, self-contained, runnable `.py` file the user owns: a custom anomaly detector or forecaster for one Mixpanel metric.

The thesis: **headless hands you a clean pandas DataFrame; from there every tool in the Python ecosystem just works — deterministic math, no LLM guessing at numbers.** The skill's job is to clarify the alert intent, pull the series via the existing `Workspace.query()` timeseries path, **profile** the series, **select** the model family that fits that profile (rather than reaching for a naive z-score every time), and **generate** a single-file script with an explainable report and exit codes wired for cron / CI / self-healing agent loops.

The skill does **not** touch the native `ws.create_alert` entity. It is a pure ML-script generator. The native-alert surface and this skill are complementary: native alerts live inside Mixpanel and fire on Mixpanel's thresholds; alert-machine scripts run anywhere Python runs and apply arbitrary statistics the native surface cannot express.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Generate a working baseline anomaly detector for one metric (Priority: P1)

A data engineer or analyst watches one number (signups, revenue, error volume, DAU) and wants a script that pages them when it moves abnormally. They do not want to hand-roll the credentials block, the fetch, the feature engineering, or the exit-code contract. They describe the metric and the alert intent in conversation; the skill profiles the series, picks a baseline detector, and writes a single `.py` file they can run immediately and drop into cron.

**Why this priority**: This is the headline use case and the MVP. Without it the skill delivers nothing. A baseline detector (IsolationForest / robust z-score / EWMA) covers the majority of "just tell me when this number looks weird" requests and is independently shippable. The canonical script shape this story generalizes is defined inline in this spec ([§ Canonical generated-script shape](#canonical-generated-script-shape)); the same shape ships as runnable recipe templates under `scripts/recipes/`.

**Independent Test**: Given a metric name, a project, and an alert intent ("page me when daily signups drop abnormally"), the skill produces a `.py` file that: (1) resolves credentials env-first; (2) calls `ws.query(METRIC, ..., mode="timeseries")`; (3) builds an engineered feature frame; (4) fits a baseline model; (5) prints an explainable report naming each flagged day with value-vs-expected and direction; (6) exits `0` when the trailing `RECENT_DAYS` window is clean, `1` when a recent anomaly fires, `2` when no data is returned. Running the generated script against a fixture project produces a deterministic verdict on repeated runs.

**Acceptance Scenarios**:

1. **Given** a metric with a flat, non-seasonal daily series, **When** the skill profiles it, **Then** it selects a baseline recipe (IsolationForest, robust/MAD z-score, or EWMA control chart) and states in the generated script's docstring why that family fits.
2. **Given** the user has not provided credentials inline, **When** the generated script runs, **Then** it resolves credentials in the order shell env > sibling `.env` > inline `CREDENTIALS` block, never overwriting an already-set environment variable.
3. **Given** the generated script runs against a window containing a sharp recent drop, **When** it completes, **Then** stdout names the offending day(s) with value, rolling expectation, delta, z-score, and direction (`SPIKE` / `DROP`), and the process exits `1`.
4. **Given** the generated script runs against a window with no anomalies in the trailing `RECENT_DAYS` days, **When** it completes, **Then** it exits `0`.
5. **Given** the configured metric/window returns no rows, **When** the generated script runs, **Then** it prints a clear "no data" message and exits `2` (distinct from the `0` clean and `1` anomaly codes).
6. **Given** the same generated script run twice on the same data, **When** both runs complete, **Then** the verdict is identical (determinism via `random_state` / fixed seeds).

---

### User Story 2 — Pick the model family from the series profile, not blindly (Priority: P2)

An analyst monitoring a metric with strong weekly seasonality (a Sunday dip is normal; a Sunday spike is not) does not want a naive z-score firing every weekend. They want the skill to recognize the seasonality and reach for a seasonality-aware or forecasting recipe instead. The skill profiles the series (length, trend, seasonality via ACF/STL, gaps, volume, distribution shape) and routes to the recipe that fits, explaining the routing decision in the generated script. The stance is profile-then-model: a spike, a drop, a permanent level shift, and a forecast-band exit are different questions, and a real signal is seasonality-aware and regime-aware rather than a naive threshold.

**Why this priority**: This is the high-leverage differentiator — the difference between "another z-score wrapper" and "an ML engineer who reads the series first." It is independently shippable on top of US1: it adds the profiling step and the seasonality-aware + forecasting recipe families, reusing US1's generator scaffold (credentials, fetch, report, exit codes).

**Independent Test**: Given a series with a strong 7-day seasonal component, the skill's profiling step reports `seasonality=weekly` and routes to a seasonality-aware recipe (STL + residual outliers, S-H-ESD, or Prophet-residual). Given a series with a clear trend and the user asks "alert me when actuals exit the expected band," the skill routes to a forecasting recipe (Prophet / SARIMA / Holt-Winters) that emits a forecast WITH prediction intervals and flags band exits. The generated script in each case names the chosen model, the deps that recipe needs, and the profile features that drove the choice.

**Acceptance Scenarios**:

1. **Given** a weekly-seasonal traffic series, **When** the skill profiles it, **Then** the profile reports a detectable seasonal period and the generated script uses a seasonality-aware recipe — NOT a naive z-score — and says so in its docstring.
2. **Given** the user asks for "expected vs actual" / "alert when it leaves the band," **When** the skill routes, **Then** it selects a forecasting recipe that produces a forecast with prediction intervals and the explainable report reads like "expected 12.4k +/- 1.1k, got 7.2k; DROP; band exit."
3. **Given** a series with a permanent level shift partway through, **When** the user asks to catch regime changes (not point spikes), **Then** the skill routes to a changepoint recipe (ruptures PELT/BinSeg, CUSUM, or BOCPD) rather than an outlier detector.
4. **Given** the user wants to know whether a release/campaign actually moved a metric, **When** the skill routes, **Then** it selects a multivariate/causal recipe (Mahalanobis / PCA-residual across correlated metrics, or CausalImpact for counterfactual estimation) and the report frames the result as effect-vs-counterfactual.
5. **Given** any recipe is selected, **When** the script is generated, **Then** its header names the exact `pip` / `uv` install line for that recipe's deps (e.g. `pip install mixpanel_headless statsmodels`) and those deps are NOT assumed to ship with `mixpanel_headless`.

---

### User Story 3 — Deploy the generated script in cron / CI / an agent loop (Priority: P3)

An SRE or platform engineer wants the generated detector to run unattended: a cron entry that pages on non-zero exit, a CI job that fails the build when a metric regresses, or a self-healing agent loop that opens a ticket on exit `1`. They need a documented exit-code contract, a configurable trailing window, an env-first credentials story (so secrets stay in the deployment environment, not the file), and a single retargetable `METRIC` block so the same scaffold watches a different number with a one-line edit.

**Why this priority**: Deployment ergonomics are independently valuable — same generated script, different runtime surface. This story is the documentation + reference layer (`references/deployment.md`) plus the FRs that bake the contract into every generated script. It ships on top of US1's exit-code wiring.

**Independent Test**: The skill's `references/deployment.md` documents the exit-code contract (`0` clean / `1` recent anomaly / `2` no data) and provides copy-paste cron, GitHub Actions, and agent-loop snippets. Every generated script (from US1 and US2) honors that exact contract and exposes `RECENT_DAYS` and a single `METRIC` block at the top of the file. A reviewer can take any generated script, set credentials via environment variables only (no file edit), and run it green in a clean container.

**Acceptance Scenarios**:

1. **Given** a generated script and a cron entry from `references/deployment.md`, **When** the metric is clean, **Then** cron sees exit `0` and does nothing; **when** a recent anomaly fires, cron sees exit `1` and triggers the paging command.
2. **Given** a generated script run inside CI with credentials supplied only as environment variables, **When** the metric regresses, **Then** the job fails (non-zero exit) and the explainable report appears in the build log.
3. **Given** a user wants to widen the alert window, **When** they edit `RECENT_DAYS` at the top of the file, **Then** the trailing-window check changes with no other edits required.
4. **Given** a user wants to watch a different metric, **When** they edit the single `METRIC` block, **Then** the script retargets with no changes to the model, report, or exit-code logic.

---

### Edge Cases

- **Short series**: fewer data points than the chosen model needs (e.g. <2 full seasonal periods for STL, <30 points for a stable rolling baseline). The skill MUST detect this in profiling and either down-select to a recipe that tolerates short series (robust z-score, EWMA) or emit a generated script that exits `2` with a "series too short for reliable detection" message rather than fitting an unstable model.
- **Gaps in the series**: missing days break rolling windows and seasonal decomposition. The generated script MUST make the gap-handling policy explicit (reindex to a complete date range and forward/zero-fill, or drop) and document which it chose.
- **Heavy missing deps**: the recipe's ML libraries (statsmodels, prophet, ruptures, sklearn) are NOT bundled with `mixpanel_headless`. The generated script MUST fail fast with a clear message naming the exact `pip install` line when an import is missing — never a raw `ModuleNotFoundError` traceback as the only signal.
- **All-anomaly degenerate fit**: a contamination/threshold set so loose that every point flags. The generated report MUST surface the flagged fraction so the user can spot a misconfigured detector.
- **Flat series (zero variance)**: a constant metric makes z-scores divide by zero. The generated script MUST guard against zero standard deviation (replace `0` divisor) and report "no variation."
- **Timezone / normalization**: Mixpanel timeseries dates carry timezone info; the generated script MUST normalize to naive midnight dates before windowing so the trailing-window math is unambiguous.
- **Ambiguous intent**: the user says "alert me" without saying what counts as an anomaly. The skill MUST ask which alert shape they mean (spike, drop, regime shift, forecast-band exit, multivariate divergence) before generating, rather than guessing.
- **Credential leakage**: the inline `CREDENTIALS` block in a generated script holds a real secret if the user pastes one. The skill MUST default to env-first resolution and MUST warn the user not to commit a script carrying an inline secret.
- **Non-daily cadence**: a metric naturally bucketed hourly or weekly. The generated `METRIC` block MUST expose the `unit` so the cadence matches the metric, and the profiling/seasonality logic MUST account for the chosen unit.

## Requirements *(mandatory)*

### Functional Requirements

#### Skill packaging & triggering

- **FR-001**: The skill MUST live at `mixpanel-plugin/skills/alert-machine/` with a `SKILL.md` (YAML frontmatter: `name`, `description`, `allowed-tools`), a `references/` directory, and a `scripts/recipes/` directory of copy-paste templates.
- **FR-002**: The `SKILL.md` `description` MUST auto-trigger on anomaly detection, alerting, forecasting, monitoring a metric, detecting spikes/drops, changepoints, seasonality, "alert me when," custom math on a Mixpanel metric, and applying ML/stats to analytics. (Concrete proposed string in [§ Proposed SKILL.md description](#proposed-skillmd-description).)
- **FR-003**: The skill MUST NOT modify the `mixpanel_headless` Python package (`src/`), its tests (`tests/`), `pyproject.toml`, or any shipping library surface. Its only repo footprint is under `mixpanel-plugin/skills/alert-machine/`.
- **FR-004**: The `SKILL.md` MUST NOT re-teach the whole `mixpanel_headless` API. It MUST defer API discovery to `help.py` (via the plugin root / `${CLAUDE_SKILL_DIR}`) and to the hosted docs (`WebFetch https://mixpanel.github.io/mixpanel-headless/llms.txt`). The skill MUST NOT bundle its own copy of `help.py`.
- **FR-005**: Bundled script paths referenced from `SKILL.md` MUST use the `${CLAUDE_SKILL_DIR}` interpolation, matching the existing skills' convention.

#### Context & schema grounding

- **FR-006**: Before generating, the skill MUST ground itself in a dataset context document, in priority order: (1) `ws.get_business_context_chain()` (org + project markdown already stored in Mixpanel), (2) a user-supplied `.md` file or pasted text, (3) ask in conversation.
- **FR-007**: The skill MUST validate the metric exists before generating, using the discovery surface (`ws.events()`, `ws.top_events()`, and `ws.schema_graph()` / `ws.property_values()` for any numeric `math_property`) so it never generates a script that queries a non-existent event or property. The `schema_graph()` lexicon-plus-relationships surface is the same one the governance specs lean on; the timeseries fetch (FR-010) comes from the typed Insights query path (Phase 029).
- **FR-008**: When the metric uses a numeric `math_property` (sum/average), the skill MUST confirm the property exists on the event and carries numeric values (via `ws.property_values(prop, event=...)`) before wiring it into the generated `METRIC` block.

#### Core generation flow

- **FR-009**: The skill MUST clarify the alert intent before generating — which anomaly shape applies (spike, drop, regime shift, forecast-band exit, multivariate divergence) — and MUST NOT guess when the intent is unstated. The shapes are distinct questions, not interchangeable thresholds: a spike, a drop, a level shift, and a band exit each route to a different model family. When the metric is a friction surface (an error / fail / cancel / timeout / retry event, or a step whose volume sits far below its logical predecessor), a sustained rise is the alert-worthy direction, and the skill SHOULD default the intent accordingly while still confirming.
- **FR-010**: The skill MUST pull the metric series via the existing `Workspace.query()` typed Insights timeseries path (`mode="timeseries"`, Phase 029 / spec 029-insights-query-api), reading the raw `result.series` nested dict (NOT a lossy single-level projection).
- **FR-011**: The skill MUST profile the series before selecting a model, computing at minimum: length (point count), trend presence, seasonality (via ACF and/or STL), cardinality/volume, gap structure, and distribution shape.
- **FR-012**: The skill MUST select the model family from the profile (documented routing in the skill's `references/series-profiling.md`), NOT default to a single detector. A weekly-seasonal series MUST route to a seasonality-aware or forecasting recipe rather than a naive z-score.
- **FR-013**: The skill MUST generate a single, self-contained `.py` file (one file per alert) the user owns, containing: an env-first credentials block, the fetch, feature engineering, the chosen model, an explainable report, exit-code wiring, determinism, and a bring-your-own-deps install header.

#### Generated-script ergonomics (every generated script MUST satisfy)

- **FR-014**: The generated script MUST resolve credentials env-first: shell env > sibling `.env` > inline `CREDENTIALS` block, never overwriting an already-set environment variable.
- **FR-015**: The generated script MUST expose a single, clearly delimited `METRIC` block (event name, `math`, optional `math_property`, date window, `unit`) so retargeting is a one-line edit.
- **FR-016**: The generated script MUST expose a configurable `RECENT_DAYS` trailing window that controls the recent-anomaly check.
- **FR-017**: The generated script MUST exit `0` when the trailing `RECENT_DAYS` window is clean, `1` when a recent anomaly fires, and `2` when the query returns no data. This exit-code contract MUST be identical across every recipe.
- **FR-018**: The generated script MUST be deterministic: identical input data yields an identical verdict (fixed `random_state` / seeds wherever the chosen model has stochastic components).
- **FR-019**: The generated script MUST print an explainable report: for each flagged point, the observed value, the model's expectation (rolling mean, forecast point, or band center), the delta, a normalized score (z-score or equivalent), and the direction (`SPIKE` / `DROP` / `SHIFT` / `BAND_EXIT` as applicable). Forecasting recipes MUST render the prediction interval ("expected X +/- Y, got Z").
- **FR-020**: The generated script MUST carry a bring-your-own-deps install header naming the EXACT deps that recipe needs (`pip` and/or `uv`), because the heavy ML libraries are NOT bundled with `mixpanel_headless`.
- **FR-021**: The generated script MUST fail fast with a clear, actionable message naming the missing `pip install` line when a recipe dependency import fails — never surface a bare `ModuleNotFoundError` as the only signal.
- **FR-022**: The generated script MUST guard the degenerate-math edge cases: zero-variance series (zero-divisor guard), gaps (explicit reindex/fill policy), short series (down-select or exit `2`), and timezone normalization to naive midnight dates.

#### Recipe library

- **FR-023**: The skill MUST ship a cataloged recipe library covering five families: **Baseline** (IsolationForest, robust/MAD z-score, EWMA control charts), **Seasonality-aware** (STL + residual outliers, Seasonal-Hybrid ESD, Prophet-residual flagging), **Forecasting + expectation bands** (Prophet, SARIMA, Holt-Winters/ETS — forecast with prediction intervals, band-exit alerting, N-day-ahead, expected-vs-actual explanations), **Changepoint** (ruptures PELT/BinSeg, CUSUM, Bayesian online changepoint / BOCPD), and **Multivariate + causal** (Mahalanobis / PCA-residual, multivariate IsolationForest, CausalImpact counterfactual).
- **FR-024**: Each recipe in the catalog MUST document: when-to-use (which series profile it fits), the model, the deps, the copy-paste template path under `scripts/recipes/`, and the shape of its explainable output.
- **FR-025**: Each recipe family MUST have at least one copy-paste template `.py` under `mixpanel-plugin/skills/alert-machine/scripts/recipes/` that is itself runnable (subject to its declared deps being installed) and honors every generated-script ergonomic FR (FR-014 through FR-022).
- **FR-026**: The recipe templates MUST be the substantive deliverable: the catalog (`references/ml-recipes.md`) plus the per-recipe templates carry the ML knowledge, while `SKILL.md` stays terse and routes into them via progressive disclosure.

#### Scope boundaries

- **FR-027**: The skill MUST NOT create, read, update, or delete any native Mixpanel alert entity. The native alert CRUD surface (`ws.create_alert` / `list_alerts` / `update_alert` / `delete_alert` and the `mp alerts` command) shipped under the core entity-CRUD line (spec 024-core-entity-crud) and is explicitly out of scope here. It MUST NOT touch dashboards or data-governance entities (the data-clean-up skill, spec 045, owns governance; the metric-maker skill, spec 048, owns saved metrics/cohorts).
- **FR-028**: The skill writes NO Mixpanel state of any kind. Its only side effect is emitting `.py` files the user owns; therefore it needs no write-safety approval gate.

### Key Entities

- **Generated alert script**: a standalone, self-contained, runnable `.py` file the user owns. Sections: module docstring (what it watches, why this recipe, how to run), bring-your-own-deps install header, env-first `CREDENTIALS` block, single `METRIC` block, detector knobs (including `RECENT_DAYS`, `RANDOM_STATE`), `build_workspace()`, `fetch_timeseries()`, the recipe's `detect`/`forecast` function, `report()`, and `main()` with the `0/1/2` exit contract.
- **Series profile**: the structured read of the metric series — length, trend, seasonality (period + strength), gap structure, volume, distribution shape — that drives recipe selection. Not persisted; computed in-conversation and/or inside the generated script's profiling step.
- **Recipe**: a catalog entry pairing a series profile to a model family, deps, a template path, and an explainable-output shape. Five families (baseline, seasonality-aware, forecasting, changepoint, multivariate/causal).
- **Exit-code contract**: the `0` clean / `1` recent anomaly / `2` no data convention, identical across all recipes, that makes generated scripts drop-in for cron / CI / agent loops.
- **Context document**: the dataset grounding (business-context chain, user-supplied `.md`, or conversation) the skill reads before generating, so the script watches a metric that exists and is framed in the org's language.

### Canonical generated-script shape

Every generated script and every recipe template follows one fixed section order, defined here so the contract is self-contained (no external file is normative for it):

1. **Module docstring** — what it watches, why this recipe (the profile feature that drove the choice), how to run, the exit-code legend.
2. **Bring-your-own-deps install header** — the exact `pip` / `uv` line for that recipe's deps.
3. **Env-first `CREDENTIALS` block** — shell env > sibling `.env` > inline non-secret placeholders; never overwrite a set env var.
4. **Single `METRIC` block** — event name, `math`, optional `math_property`, `FROM_DATE` / `TO_DATE`, `unit`.
5. **Detector knobs** — `RECENT_DAYS`, `RANDOM_STATE` / seeds, recipe-specific thresholds.
6. **`build_workspace()` / `fetch_timeseries()`** — authenticated `Workspace`, then `query(..., mode="timeseries")` reading `result.series`.
7. **The recipe's `detect` / `forecast` function** — with a fail-fast import guard naming the missing dep.
8. **`report()`** — the explainable per-flag output.
9. **`main()`** — the `0` clean / `1` recent anomaly / `2` no data exit contract.

This shape generalizes to nearly any single-metric Mixpanel timeseries; the only per-recipe variation is the model in step 7 and the deps in step 2.

### Key conventions vs library specs

`alert-machine` is a **skill**, a different artifact class from the library specs (024–037, 029). It ships only under `mixpanel-plugin/skills/alert-machine/` and contributes zero `src/` / `tests/` / `pyproject.toml` change, so the strict library gates (TDD, `mypy --strict`, ≥90% coverage, full docstrings) do NOT apply to the markdown assets. Only the bundled recipe templates carry runnable verification: each must run green against the fixture project (given its declared deps) and pass the reviewer checklist. The markdown (`SKILL.md`, `references/`) is reviewed for taste and correctness, matching the precedent set by the `mixpanelyst` and `dashboard-expert` skills rather than the library-spec gate model.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can describe a metric and an alert intent in one conversational turn and receive a runnable `.py` file that executes against a fixture project and produces a verdict, with no manual editing of the fetch, model, report, or exit-code logic.
- **SC-002**: A generated baseline script run twice on identical data produces an identical verdict and identical flagged-point set (determinism), verified by a byte-identical stdout diff modulo timestamps.
- **SC-003**: For a series with a strong weekly seasonal component, the skill selects a seasonality-aware or forecasting recipe (NOT a naive z-score) in at least 9 of 10 trials, and the generated script's docstring names the seasonality as the reason.
- **SC-004**: Every recipe template under `scripts/recipes/` honors the exit-code contract (`0`/`1`/`2`) and exposes `RECENT_DAYS` plus a single `METRIC` block, verified by inspection against a checklist.
- **SC-005**: Every generated script and every recipe template carries a bring-your-own-deps install header naming the exact deps; a clean container with only `mixpanel_headless` installed surfaces a clear "pip install X" message (not a bare traceback) when a recipe dep is missing.
- **SC-006**: The skill never modifies the `mixpanel_headless` package: a `git diff --stat` after a generation session shows changes only under `mixpanel-plugin/skills/alert-machine/` (for skill development) and the user's chosen output path (for the generated script).
- **SC-007**: A reviewer can deploy any generated script in cron, CI, and an agent loop using only the snippets in `references/deployment.md`, supplying credentials via environment variables only (no file edit), and observe the correct exit code drive each surface.
- **SC-008**: The skill validates the metric against the live schema before generating; in a trial where the user names a non-existent event, the skill surfaces the mismatch and the closest real event names rather than generating a script that returns empty.
- **SC-009**: A new contributor can read `references/ml-recipes.md` and `references/series-profiling.md` and add a sixth recipe (template + catalog entry + routing rule) without touching `SKILL.md`'s core flow.

## Assumptions

- The existing `Workspace.query()` typed Insights timeseries path (Phase 029 / spec 029-insights-query-api) returns a `result.series` nested dict suitable for building a daily/weekly/hourly DataFrame. The discovery surface the schema-validation step uses (`events`, `top_events`, `schema_graph`, `property_values`) ships with the existing library. No library changes are needed.
- `pandas` ships with `mixpanel_headless`; the heavy ML libraries (`scikit-learn`, `statsmodels`, `prophet`, `ruptures`, and CausalImpact implementations) do NOT, and are the user's responsibility to install per the recipe's declared deps.
- `ws.get_business_context_chain()` is available and returns org + project markdown when the project has business context set; when it is empty, the skill falls back to a user-supplied `.md` or conversation.
- The skill targets web/standard event metrics expressible through `Workspace.query()`; metrics requiring funnel/retention/flow engines are out of scope for the generated detector (the series must be a single timeseries).
- Determinism is achievable for the chosen recipes by fixing `random_state` / seeds; recipes with inherently non-deterministic fits (if any) are excluded from the catalog or pinned to a deterministic configuration.
- The skill is for single-metric (and, for the multivariate family, small correlated-metric-set) detection, not for fleet-scale monitoring of thousands of metrics; large-scale orchestration is the user's deployment concern, addressed by the exit-code contract rather than by the skill.
- The canonical ergonomic shape is defined inline in this spec ([§ Canonical generated-script shape](#canonical-generated-script-shape)); the public recipe templates under `scripts/recipes/` are the normative instances, shipping with non-secret placeholder credentials.
- Native Mixpanel alert CRUD (`create_alert` / `list_alerts` / `update_alert` / `delete_alert`, the `mp alerts` command) shipped under spec 024-core-entity-crud and is out of scope; dashboards and data-governance writes (specs 045 and 048's territory plus the 027 governance surface) are likewise out of scope. This skill is a pure ML-script generator that writes no Mixpanel state.
- Env-first credential resolution (`MP_USERNAME` / `MP_SECRET` / `MP_PROJECT_ID` / `MP_REGION` per CLAUDE.md) and the standalone-script ergonomic match the most recent skill-adjacent feature (spec 044-session-replay), which also runs read-only against Mixpanel with no new on-disk persistence.

## Proposed SKILL.md description

The `description` field in `mixpanel-plugin/skills/alert-machine/SKILL.md` frontmatter (the auto-trigger surface) is proposed as:

> This skill should be used when the user wants to detect anomalies, set up alerting, forecast a metric, monitor a number over time, detect spikes or drops, find changepoints or regime shifts, handle seasonality, watch a friction or error signal, says "alert me when" a Mixpanel metric does something, wants custom math or statistics applied to a Mixpanel metric, or wants to apply machine learning / time-series methods to product analytics. it profiles the series first and picks the model that fits rather than reaching for a naive z-score every time — a spike, a drop, a level shift, and a forecast-band exit are different questions. generates a standalone, runnable python anomaly-detection or forecasting script (the user owns it) that pulls the series via mixpanel_headless, profiles it, routes to the family that fits (baseline, seasonality-aware, forecasting bands, changepoint, or multivariate/causal), and emits a deterministic, explainable report with cron/CI-ready 0/1/2 exit codes. does NOT create native Mixpanel alerts, build dashboards (use dashboard-expert), clean up the schema or lexicon (use data-clean-up, spec 045), or define saved metrics/behaviors/cohorts (use metric-maker, spec 048) — it writes no Mixpanel state, only a script you run yourself.

`allowed-tools`: `Bash Read Write WebFetch`
