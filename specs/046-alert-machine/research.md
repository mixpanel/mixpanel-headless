# Phase 0 Research: alert-machine

**Feature**: 046-alert-machine
**Date**: 2026-06-28
**Status**: Complete — no NEEDS CLARIFICATION markers remain in plan.md.

This document records the load-bearing decisions for the skill: why it generates scripts instead of mutating native alerts, how it routes a series to a model family, and which recipes belong in the catalog. The canonical generated-script shape is defined in the spec ([spec.md § Canonical generated-script shape](spec.md#canonical-generated-script-shape)); this research generalizes it and catalogs the model families. Rejected alternatives are recorded so reviewers can audit without re-deriving.

> Prior art (private, non-shipping): an internal single-file anomaly detector validated the env-first-creds / single-METRIC-block / `0`-`1`-`2`-exit ergonomic end to end. That file lives in untracked work and is NOT a repo artifact or a normative reference; the contract it inspired is restated in full in the spec and below so this package is self-contained for any contributor or CI reviewer.

---

## R-1. Generate owned scripts, do not wrap native alerts

**Decision**: The skill's only deliverable is a standalone `.py` file the user owns. It does NOT call `ws.create_alert` or any native Mixpanel alert CRUD.

**Rationale**:
- Native Mixpanel alerts fire on Mixpanel's built-in thresholds. They cannot express STL residual flagging, a Prophet prediction-interval band exit, a PELT changepoint, or a CausalImpact counterfactual. The whole value of this skill is the math the native surface cannot do.
- A script the user owns runs anywhere Python runs — laptop, cron host, CI runner, agent loop — and integrates with the user's paging/ticketing via a plain exit code. That is a strictly larger deployment surface than a Mixpanel-internal alert.
- Writing no Mixpanel state means no write-safety approval gate, no irreversible-op confirmation, no re-fetch-and-diff verification. The skill is read-only against Mixpanel and emit-only against the local filesystem. This is the simplest possible safety model.

**Alternatives considered**:
- **Create native alerts via `ws.create_alert`**: rejected — cannot express the ML/stats the skill exists to provide; also pulls in the write-safety machinery for no benefit.
- **Hybrid (native alert + sidecar script)**: rejected — two artifacts, two failure modes, two surfaces to keep in sync, for a marginal gain over the script alone.

---

## R-2. Profile the series before picking a model

**Decision**: The skill computes a series profile (length, trend, seasonality via ACF/STL, gaps, volume, distribution shape) and routes to a model family from that profile. It does not default to a single detector. This is the skill's core POV: a real anomaly signal is seasonality-aware and regime-aware, not a naive threshold, and a spike, a drop, a level shift, and a forecast-band exit are genuinely different questions that need different models.

**Rationale**:
- A naive z-score on a weekly-seasonal traffic series fires every Sunday. A Sunday dip is not an anomaly; firing on it is a false positive factory. Recognizing the seasonality and routing to a seasonality-aware recipe is the difference between a useful detector and noise.
- The profile features map cleanly to families: seasonality present → seasonality-aware or forecasting; clear trend + "expected vs actual" intent → forecasting bands; permanent level shift + "regime change" intent → changepoint; correlated metric set + "did the release move it" intent → multivariate/causal; none of the above → baseline.
- This routing generalizes across datasets because it keys off series *shape*, not customer-specific event names: nearly any Mixpanel metric is one of flat / trended / seasonal / regime-shifting / part-of-a-correlated-set, so the same five-family map fits projects the skill has never seen. The profile is the dataset-agnostic interface.
- Profiling is cheap (it runs on the same series the detector will use) and it makes the recipe choice explainable in the generated script's docstring — the user sees why this model was chosen.

**Alternatives considered**:
- **Always IsolationForest** (a common one-size default): rejected as the universal answer — great baseline, wrong for seasonal/trended/regime-shift/causal questions. Kept as the baseline family's anchor recipe.
- **Let the user pick the model**: rejected as the default — most users know the alert intent (spike/drop/regime/band/causal) but not the model family. The skill maps intent + profile → model so the user does not have to know statsmodels from ruptures.
- **Try every recipe and ensemble**: rejected — superset deps, slow, opaque, and harder to explain than a single well-chosen model.

---

## R-3. Recipe families and their anchor recipes

**Decision**: Catalog five families. Each ships at least one runnable template.

| Family | When (profile + intent) | Anchor recipe(s) | Deps (bring-your-own) | Explainable output |
|--------|-------------------------|------------------|-----------------------|--------------------|
| **Baseline** | short / flat / non-seasonal; "is this number weird" | IsolationForest; robust/MAD z-score; EWMA control chart | `scikit-learn` (IForest) or `numpy`/`scipy` (z/MAD/EWMA) | per-day value vs rolling expected, delta, z, SPIKE/DROP |
| **Seasonality-aware** | detectable seasonal period; "weekends are normal, surprises are not" | STL + residual outliers; Seasonal-Hybrid ESD; Prophet-residual | `statsmodels` (STL/ESD) or `prophet` | residual vs seasonal baseline; "vs same-weekday expectation" |
| **Forecasting + bands** | trend and/or seasonality; "alert when actual exits the expected band" | Prophet; SARIMA; Holt-Winters/ETS | `prophet` or `statsmodels` | "expected X +/- Y, got Z; BAND_EXIT"; N-day-ahead forecast |
| **Changepoint** | permanent level/regime shift; "catch the shift, not the spike" | ruptures PELT/BinSeg; CUSUM; BOCPD | `ruptures` or `numpy` (CUSUM) | changepoint date(s), pre/post level, magnitude, SHIFT |
| **Multivariate + causal** | correlated metric set; "did the release/campaign actually move it" | Mahalanobis / PCA-residual; multivariate IsolationForest; CausalImpact | `scikit-learn`/`numpy` or `causalimpact` | per-day Mahalanobis distance; or effect-vs-counterfactual with credible interval |

**Rationale**:
- The five families cover the distinct questions analysts actually ask: point outlier, seasonal outlier, expectation-band exit, regime shift, and causal effect. Each is a genuinely different computation with a different explainable shape.
- Within each family, multiple recipes are listed so the skill can down-select on deps (e.g. STL via statsmodels when the user already has it, Prophet otherwise) and on series length (EWMA/MAD for short series, IForest for richer ones).
- Anchoring on widely-used, deterministic-configurable libraries (sklearn, statsmodels, ruptures, prophet) keeps the templates maintainable and the math auditable.

**Alternatives considered**:
- **A single "best" library (e.g. only Prophet)**: rejected — Prophet is overkill for a flat series and underfit for a regime shift; no single library spans all five questions well.
- **A custom in-house detector**: rejected — duplicates battle-tested open-source math, drifts, and adds maintenance with no upside over the thesis ("the ecosystem just works").

---

## R-4. Determinism is a hard requirement

**Decision**: Every recipe is configured for determinism — fixed `random_state` for sklearn models, fixed seeds where applicable, deterministic solver settings for statsmodels/ruptures. Identical input data yields an identical verdict.

**Rationale**:
- The generated scripts run in CI and self-healing agent loops. A non-deterministic verdict turns the build flaky and the agent loop unstable.
- Determinism makes the "run it twice, get the same answer" smoke test a meaningful merge gate (SC-002).
- All chosen anchor recipes have a deterministic configuration; recipes that cannot be pinned deterministically are excluded from the catalog.

**Alternatives considered**:
- **Accept stochastic fits, document the variance**: rejected — flaky CI and unstable agent loops are a worse outcome than constraining the recipe configuration.

---

## R-5. The 0/1/2 exit-code contract is identical across recipes

**Decision**: Every generated script exits `0` (trailing `RECENT_DAYS` window clean), `1` (recent anomaly fired), or `2` (no data returned). The contract is identical regardless of recipe.

**Rationale**:
- A uniform contract is what makes the generated scripts drop-in for cron, CI, and agent loops without per-recipe special-casing. The deployment snippets in `references/deployment.md` work for any recipe.
- Separating "no data" (`2`) from "clean" (`0`) and "anomaly" (`1`) lets a deployment distinguish a genuine all-clear from a broken query / empty window — different operational responses.
- The contract is a deliberate ergonomic stance, not an incidental choice: a uniform `0/1/2` exit is what makes determinism testable and the deployment snippets recipe-agnostic. Generalizing it across recipes costs nothing and buys uniformity.

**Alternatives considered**:
- **Boolean exit (`0`/`1` only)**: rejected — conflates "no data" with "clean," hiding broken queries.
- **Rich exit codes per anomaly type**: rejected — over-engineered; the explainable stdout report already carries the type, and cron/CI only branch on zero/non-zero plus the distinct "no data" code.

---

## R-6. Bring-your-own deps; never add ML libraries to mixpanel_headless

**Decision**: The heavy ML libraries (sklearn, statsmodels, prophet, ruptures, CausalImpact) are NOT added to `mixpanel_headless`. Each recipe declares its exact deps in a `pip`/`uv` install header, and each generated script fails fast with a clear "pip install X" message when an import is missing.

**Rationale**:
- `mixpanel_headless` is a query/analytics client; bundling prophet (with its compiled Stan backend) or tensorflow-based CausalImpact would bloat the install for every user, most of whom never run a detector.
- `pandas` already ships with `mixpanel_headless`, so the data-handoff works out of the box; the model layer is the user's choice and the user's install.
- A fail-fast import guard naming the exact install line turns a cryptic `ModuleNotFoundError` into an actionable one-liner — the canonical generated-script shape bakes this in for every recipe.

**Alternatives considered**:
- **Add the ML libs as optional extras on `mixpanel_headless`**: rejected — that IS a library change (touches `pyproject.toml`), which this feature explicitly forbids (FR-003); it also couples release cadences.
- **Bundle a minimal pure-numpy detector and call it done**: rejected — abandons the seasonality/forecasting/causal families that are the skill's differentiator.

---

## R-7. Ground in context before generating

**Decision**: The skill reads a dataset context document in priority order — `ws.get_business_context_chain()` (org + project markdown in Mixpanel), then a user-supplied `.md`/pasted text, then conversation — and validates the metric against the live schema before generating.

**Rationale**:
- Grounding in business context frames the metric in the org's language and catches "watch signups" when the event is actually called `Sign Up Completed`.
- Schema validation (`ws.events()`, `ws.top_events()`, `ws.schema_graph()`, `ws.property_values()`) before generation prevents the most common silent failure: a script that queries a non-existent event and returns empty forever.
- The priority order prefers the source of truth already stored in Mixpanel, falling back gracefully when it is empty.

**Alternatives considered**:
- **Generate first, validate at run time**: rejected — surfaces the typo only when the user runs the script and gets `exit 2` forever, instead of in-conversation with the closest real event names.
- **Skip grounding, trust the user's metric name verbatim**: rejected — guarantees silent-empty scripts for any name mismatch.

---

## R-8. SKILL.md stays terse; the recipes carry the knowledge

**Decision**: `SKILL.md` is a terse, table-driven router (intent → family, family → template path) with progressive disclosure into `references/`. The ML knowledge lives in `references/ml-recipes.md` + `references/series-profiling.md` and the templates. `SKILL.md` does NOT re-teach the `mixpanel_headless` API (defers to `help.py` + `llms.txt`).

**Rationale**:
- Matches the established pattern in `mixpanelyst` and `dashboard-expert`: terse top, deep references, scripts via `${CLAUDE_SKILL_DIR}`.
- Keeps the always-loaded surface small (Context Window Efficiency), loading the heavy catalog only when the skill actually routes a request.
- Avoids triplicating the 32KB `help.py` or the API reference across skills; one canonical discovery path.

**Alternatives considered**:
- **One big self-contained SKILL.md with the whole catalog inline**: rejected — bloats the always-loaded context and duplicates the references.
- **Re-teach the query API in this skill**: rejected — `help.py` and `llms.txt` are the canonical, live, single source; duplicating drifts.

---

## R-9. Friction signals get a default direction; intent still confirmed

**Decision**: When the metric is a friction surface, the skill biases the default alert intent toward "a sustained rise is bad," while still confirming the intent before generating (FR-009). A metric is recognized as friction by name-pattern signature — the event name contains `error` / `fail` / `invalid` / `reject` / `timeout` / `cancel` / `retry` / `block`, or a negative prefix (`un` / `dis` / `abort`) — or by *implied* friction, where a step's volume sits far below its logical predecessor.

**Rationale**:
- Friction events have an obvious asymmetric direction: more errors is the alert, fewer is fine. Defaulting to that direction is a better starting point than asking the user to spell out "alert on the up side" for an event literally named `*_error`.
- The name-pattern signature is dataset-agnostic: it keys off universal naming conventions, not a customer-specific taxonomy, so it generalizes to any project without bespoke config.
- Friction worth alerting on is measured by *users affected and trend*, not raw count — so a friction-shaped metric leans toward a `unique` math and toward the seasonality-aware / forecasting families (a slow worsening trend matters more than a single noisy day). The skill states this in the generated docstring.
- This is a default, not a lock-in. The skill still confirms (FR-009) because a `retry` event can be a healthy recovery signal in some products.

**Alternatives considered**:
- **Treat every metric symmetrically**: rejected — wastes a clarification round on the common, unambiguous friction case and risks generating a spike-only detector for an error metric where the drop side is meaningless.
- **Hard-code the direction for friction names**: rejected — too rigid; a `cancel` event can be a deliberate user action worth watching in both directions. Default, then confirm.

---

## R-10. Native alert CRUD is a separate, existing surface — do not overlap

**Decision**: The "generate owned scripts, do not wrap native alerts" boundary (R-1) is made concrete by naming where the native surface lives: `ws.create_alert` / `list_alerts` / `update_alert` / `delete_alert` and the `mp alerts` command shipped under spec 024-core-entity-crud. This skill touches none of it.

**Rationale**:
- A reviewer can confirm non-overlap by pointing at spec 024's alert CRUD and observing that this skill's footprint (`mixpanel-plugin/skills/alert-machine/`) never imports or calls those methods.
- Keeping the boundary explicit prevents future drift where a "helpful" addition starts mirroring detector verdicts into native alerts, which would re-introduce the write-safety machinery R-1 deliberately avoids.

**Alternatives considered**:
- **Leave the boundary as prose only**: rejected — naming the owning spec (024) makes the scope auditable rather than aspirational.
