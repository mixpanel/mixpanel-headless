# Implementation Plan: alert-machine — ML/stats anomaly + forecasting skill

**Branch**: `046-alert-machine` (proposed) | **Date**: 2026-06-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/046-alert-machine/spec.md`
**PR strategy**: Single PR. The skill is additive (new directory under `mixpanel-plugin/skills/`) and touches no shipping library code, so it ships as one reviewable unit. It is sliced internally into three independently-demonstrable user stories (US1 baseline generator → US2 profile-driven recipe routing → US3 deployment ergonomics) so a reviewer can validate value incrementally even within the one PR.

## Summary

Add a `alert-machine` skill to the `mixpanel-plugin/` that generates standalone, runnable anomaly-detection / forecasting Python scripts for a single Mixpanel metric. The skill grounds itself in a dataset context document, validates the metric against the live schema, clarifies the alert intent, pulls the series via the existing `Workspace.query()` timeseries path, profiles the series (length / trend / seasonality / gaps / volume / distribution), routes to the model family that fits the profile, and emits a single self-contained `.py` file with an env-first credentials block, a retargetable `METRIC` block, an explainable report, and a `0/1/2` exit-code contract wired for cron / CI / agent loops.

The deliverable is entirely documentation + templates: a `SKILL.md` (terse, table-driven, progressive disclosure), three `references/` documents (the recipe catalog, the series-profiling routing guide, the deployment contract), and a `scripts/recipes/` library of copy-paste templates — at least one per recipe family. **No `mixpanel_headless` package change.** The canonical generated-script shape is defined inline in [spec.md § Canonical generated-script shape](spec.md#canonical-generated-script-shape); this skill ships it as public, non-secret templates.

Estimated scope: ~8–12 new files, all under `mixpanel-plugin/skills/alert-machine/`. No `src/` / `tests/` / `pyproject.toml` changes.

## Technical Context

**Language/Version**: Markdown (skill content) + Python 3.10+ (recipe templates and the generated scripts they model). Templates target the same Python floor as `mixpanel_headless`.

**Primary Dependencies**:
- Reused at generation time: `mixpanel_headless` (`Workspace.query`, `get_business_context_chain`, `events`/`top_events`/`schema_graph`/`property_values`), `pandas` (ships with `mixpanel_headless`), `help.py` (plugin-root API discovery — referenced, never bundled), hosted docs (`llms.txt`).
- Bring-your-own at run time (NOT bundled, declared per recipe): `scikit-learn` (IsolationForest, Mahalanobis/PCA via numpy), `statsmodels` (STL, SARIMA, Holt-Winters, ACF, ESD), `prophet` (Prophet forecasting + residuals), `ruptures` (PELT/BinSeg changepoints), a CausalImpact implementation (`causalimpact` / `tfcausalimpact`), `numpy`/`scipy` (z-score, MAD, EWMA, Mahalanobis).

**Storage**: None. The skill persists nothing. Generated scripts hold an env-first credentials block (env preferred; inline placeholders are non-secret). The only on-disk output is the `.py` file the user explicitly asks to write.

**Testing**: This is a skill, not library code — it is exempt from the `mypy --strict` / pytest / coverage / mutation gates that apply to `src/` and `tests/`. Validation is by reviewer checklist (the spec's Success Criteria) plus a runnable smoke test of each recipe template against the public fixture project. The recipe templates are themselves the test artifacts: each must run green (given its declared deps) and honor the ergonomic FRs.

**Target Platform**: Cross-platform. The skill runs inside Claude Code; generated scripts run anywhere Python runs (developer laptop, cron host, CI runner, agent loop).

**Project Type**: Plugin skill addition. No package code. No CLI changes. No plugin manifest changes required (`plugin.json` auto-discovers skills under `mixpanel-plugin/skills/`).

**Performance Goals**:
- Generation: one conversational turn from "watch metric X, page me on a drop" to a written `.py` file, gated only on the schema-validation and series-profiling round trips (each a single `Workspace.query()` / discovery call).
- Generated script runtime: a single `Workspace.query()` timeseries fetch plus an in-process model fit — sub-second to a few seconds for a typical multi-month daily series, dominated by the one network round trip.

**Constraints**:
- ZERO changes to `src/mixpanel_headless/`, `tests/`, `pyproject.toml`, or any shipping library surface (FR-003).
- `SKILL.md` MUST NOT re-teach the `mixpanel_headless` API; defer to `help.py` and the hosted docs (FR-004). MUST NOT bundle a copy of `help.py`.
- Bundled script paths MUST use `${CLAUDE_SKILL_DIR}` (FR-005).
- Every generated script and every recipe template MUST honor the ergonomic FRs (env-first creds, single `METRIC` block, `RECENT_DAYS`, `0/1/2` exit contract, determinism, bring-your-own-deps header, degenerate-math guards).
- AK authoring voice for any shipping copy (`SKILL.md`, template docstrings): lowercase-leaning, direct, no em-dashes, no AI tells, no Co-Authored-By/Claude trailers. (The spec/plan/research/quickstart docs themselves are normal technical prose.)
- Heavy ML deps are NEVER added to `mixpanel_headless`; they stay bring-your-own per recipe.

**Scale/Scope**: Single skill, ~8–12 files. One `SKILL.md`, three references, five-or-more recipe templates (one+ per family), one quickstart smoke recipe.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Library-First | PASS (N/A library code) | The skill adds no library surface; it consumes existing public `Workspace` methods only (`query`, `get_business_context_chain`, discovery). It introduces no new package code, so there is nothing to keep library-first beyond using the public API as a consumer would. |
| II. Agent-Native | PASS | The skill's entire output is structured Python and deterministic reports. Generated scripts have no interactive prompts; they read env, fetch, compute, print, and exit with a machine-readable code. The skill itself asks clarifying questions only for genuinely ambiguous intent (FR-009), never for required-but-discoverable facts. |
| III. Context Window Efficiency | PASS | `SKILL.md` stays terse and routes into `references/` via progressive disclosure (FR-026). API discovery defers to `help.py` and `llms.txt` rather than inlining the API (FR-004). The recipe catalog is the only large surface, and it is reference-tier (read on demand), not loaded eagerly. |
| IV. Two Data Paths | PASS | Live path: the generated script fetches via `Workspace.query()`. Local path: the fetched `pandas` DataFrame feeds the open-source ML/stats ecosystem directly — the whole thesis of the skill. Both paths share the authenticated `Workspace`. |
| V. Explicit Over Implicit | PASS | Recipe selection is explicit and explained in the generated docstring (FR-012, FR-019). `RECENT_DAYS`, `RANDOM_STATE`, the `METRIC` block, and the gap/short-series policy are all surfaced at the top of the file, never hidden. The skill clarifies intent rather than guessing (FR-009). |
| VI. Unix Philosophy | PASS | Generated scripts are textbook Unix tools: read config from env, do one thing (judge one metric), print a report to stdout, exit with a meaningful code (`0`/`1`/`2`) that composes into cron, CI, and agent loops (FR-017, US3). |
| VII. Secure by Default | PASS WITH NOTE | Credentials resolve env-first (FR-014); inline template credentials are non-secret placeholders. The skill warns against committing a script that carries an inline secret (Edge Cases). No new credential persistence surface is introduced. See [Complexity Tracking](#complexity-tracking) for the inline-credentials-block justification. |

**Gate Result**: PASS. Principle VII carries a note (not a violation): the generated-script template includes an inline `CREDENTIALS` block for copy-and-run convenience (the env-first credential precedent from spec 044-session-replay), but defaults to env-first resolution and ships only non-secret placeholders. The skill explicitly warns users not to commit a populated inline block.

## Project Structure

### Documentation (this feature)

```text
specs/046-alert-machine/
├── plan.md                 # This file
├── spec.md                 # Feature specification
├── research.md             # Phase 0 output — recipe-family decisions + rejected alternatives
├── quickstart.md           # Phase 1 output — end-to-end walkthrough + per-story smoke tests
└── tasks.md                # Phase 2 output (via /speckit.tasks)
```

### Source (skill content — repository root)

```text
mixpanel-plugin/
└── skills/
    └── alert-machine/                      # NEW SKILL (entire feature footprint)
        ├── SKILL.md                        # NEW — terse, table-driven router; AK voice; ${CLAUDE_SKILL_DIR} refs
        ├── references/
        │   ├── ml-recipes.md               # NEW — the catalog: 5 families, when-to-use, model, deps, template path, output shape
        │   ├── series-profiling.md         # NEW — how to read a series (length/trend/seasonality/gaps/volume/shape) and route to a recipe
        │   └── deployment.md               # NEW — cron / GitHub Actions / agent-loop snippets + the 0/1/2 exit-code contract
        └── scripts/
            └── recipes/                    # NEW — copy-paste runnable templates, >=1 per family
                ├── baseline_isolation_forest.py   # Baseline family (also the quickstart smoke recipe)
                ├── baseline_robust_zscore.py      # Baseline family — MAD z-score / EWMA control chart
                ├── seasonal_stl_residual.py       # Seasonality-aware family — STL + residual outliers (statsmodels)
                ├── forecast_band_exit.py          # Forecasting family — Prophet/Holt-Winters forecast + prediction-interval band exit
                ├── changepoint_ruptures.py        # Changepoint family — ruptures PELT / CUSUM
                └── multivariate_causal.py         # Multivariate + causal family — Mahalanobis/PCA-residual or CausalImpact
```

**Structure Decision**: Plugin-skill layout matching the two existing skills (`mixpanelyst`, `dashboard-expert`): a `SKILL.md` at the root, a `references/` directory for progressive-disclosure depth, and a `scripts/` directory for bundled helpers. The recipe templates are the substantive deliverable and live under `scripts/recipes/`. No files are created outside `mixpanel-plugin/skills/alert-machine/` (skill source) and the spec directory (planning docs). `help.py` is referenced via the plugin root, never copied (FR-004).

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Generated scripts and recipe templates include an inline `CREDENTIALS` block (defaulting to env-first) rather than env-only | A copy-paste-and-run single file is the ergonomic that makes these detectors actually get deployed. An env-only template forces every user to set up environment plumbing before they can confirm the script even works, which kills the "copy it, change METRIC, ship it" loop. The inline block holds non-secret placeholders by default and is overridden by env at run time, so the secure path is the default and the convenience path is opt-in. This mirrors the env-first credential precedent already shipped in spec 044-session-replay's standalone-script ergonomics. | Env-only templates: rejected — they raise the activation cost of a first run. A separate config file: rejected — adds a second artifact to a deliverable whose whole point is being one self-contained file. |
| Five+ recipe templates instead of one configurable mega-detector | Each model family has genuinely different deps, fit semantics, and explainable-output shape (a forecast band is not a z-score). Folding them into one parametric script would create a deps-superset install and a tangle of conditional branches that obscures the per-recipe math. Separate templates keep each recipe readable, independently runnable, and copy-pasteable — the user takes exactly the one that fits. | One mega-detector: rejected — superset deps, conditional sprawl, and a worse copy-paste story. Two templates (one classical, one forecasting): rejected — collapses the changepoint and multivariate/causal families that solve distinct problems (regime shift vs counterfactual effect) the others cannot. |
