# Phase 0 Research: Behaviors, Metrics & Formulas CRUD

**Feature**: 047-behaviors-metrics-formulas
**Date**: 2026-06-28
**Status**: All decisions settled. R-1 (transport — endpoint paths + list-response envelope) is now CONFIRMED against the Mixpanel backend App API; the request/response BODY shapes were already confirmed. No open NEEDS-CONFIRMATION risks remain.

The validated payload constraints come from [mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools) (`templates/prompts/ai-behaviors-metrics-system.txt`), which encodes the structures that make Mixpanel 400 or crash its own webapp on load. This document records the decisions, their rationale, and the rejected alternatives; both the bodies and the transport are confirmed against the Mixpanel backend.

---

## R-0. Why these three entities are one feature: the compression layer

**Decision**: Treat behaviors, metrics, and formulas as the three saved-entity types of a single semantic / compression layer, shipped together, rather than as three unrelated CRUD additions.

**Rationale**: A raw Mixpanel project is hundreds of events and properties; the analysts and PMs who consume it need a handful of clean concepts. The layering is: raw events (hundreds) → governed, visible events → behaviors (dozens of reusable user-action concepts) → metrics and formulas (a handful of governed KPIs). Each layer compresses the one below into business language, and the three entity types in this feature ARE the top of that pyramid — a behavior groups events into a reusable concept, a metric is a governed calculation over a behavior, a formula composes metrics. Modeling them as one typed, composable, reusable surface (saved named entities, never anonymous inline one-offs) is what makes the layer coherent: a metric's `definition.behavior` is literally a behavior, and a formula's `referencedMetrics[i]` is literally a metric. They share the `BehaviorStep` / `MeasurementProperty` / step-count machinery, so one feature, one set of validators.

**Generalization**: the layer is dataset-agnostic. Every Mixpanel project shares the same recurring classes — identity (`distinct_id` / `user_id` / `device_id`), attribution (`utm_*`, source, medium, campaign), platform/device, geo, time, and value/revenue — and the same universal metric archetypes (acquisition, activation, engagement / DAU-WAU-MAU + stickiness, retention, revenue/value). The primitives this feature ships are exactly what a caller needs to express those archetypes on any project, which is why the surface is a library primitive and not bespoke per-customer code.

**Alternatives considered**:
- **Three separate features / PRs**: rejected — they share validators and embed one another; splitting them would duplicate the `BehaviorStep` / measurement machinery and break the embedding relationship.
- **A generic "saved entity" CRUD**: rejected for the typing/validation reasons in plan.md Complexity Tracking; the per-type Pydantic validation is the whole point.

---

## R-1. App API endpoint paths + list envelope — CONFIRMED

**Decision (CONFIRMED against the Mixpanel backend App API)**: Behaviors, metrics, and formulas are saved entities reached through `app_request` on **project-scoped** paths. There is **NO workspace scoping** for these entities — the paths are `/api/app/projects/{project_id}/...` only (unlike cohorts, which carry a workspace-scoped idiom). The exact paths, methods, list envelope, and the formulas-ride-the-metrics-endpoint fact below are all confirmed; the request/response BODY shapes were already confirmed (recorded in `contracts/payload-shapes.md §1–§6`).

**Confirmed transport**:
- **Behaviors** — collection `/api/app/projects/{project_id}/behaviors/`: GET (list), POST (create; body is a single behavior OR `{"behaviors": [...]}`), PATCH (bulk update, body `{"behaviors": [{id, ...}]}`), DELETE (bulk delete, body `{"behaviors": [{id}]}`). Single-item `/api/app/projects/{project_id}/behaviors/{behavior_id}/`: GET, PATCH, DELETE.
- **Metrics** — collection `/api/app/projects/{project_id}/metrics/`: GET (list), POST (create), PATCH (bulk update, body `{"metrics": [{id, ...}]}`), DELETE (bulk delete, body `{"metrics": [{id}]}`). Single-item `/api/app/projects/{project_id}/metrics/{metric_id}/`: GET, PATCH. **Single-item DELETE returns 501 NOT IMPLEMENTED** — metric (and formula) deletion MUST go through the bulk DELETE on the collection path.
- **Formulas are NOT a separate endpoint.** A formula IS a metric with `type="formula"`; it is created, listed, updated, and deleted via the SAME `/metrics/` endpoint. The metric `type` field discriminates: `"metric"` (behavior-backed metric) or `"formula"` (formula-backed). So the library's three public method families map onto **TWO endpoints**: behaviors → `/behaviors/`, and BOTH metrics and formulas → `/metrics/` (discriminated by `type`).

**Confirmed list-response envelope**: `{"status": "ok", "results": {"<id>": {<entity>}, ...}}`. `results` is an **OBJECT MAP KEYED BY STRING ID**, NOT an array, and there is **NO cursor pagination / `page_info`**. The `list_*` methods parse the map's values into a list of typed objects — no pagination helper is needed for these entities (this differs from cohorts).

**Confirmed scoping**: project-scoped only. No `WorkspaceScopeError` path applies to these entities; a project is sufficient.

**Why R-1 is now closed (no blocking gate)**: the cohort surface uses a workspace-scoped idiom + cursor pagination; these entities deliberately do NOT. The transport above is confirmed against the Mixpanel backend, so the binding surface can be frozen without a blocking reverse-engineer step. T003 is therefore a smoke-test verification (one live round-trip per family to confirm the recorded shapes still hold), not a blocking reverse-engineer gate.

**Rationale for the idiom choice**: `app_request` carries the one error-mapping path the rest of the App API surface uses. The semantic-layer entities reuse that single path; they skip the cohort workspace-scoped idiom (project-only) and the cursor pagination helper (object-map list, no pages).

**Alternatives considered**:
- **Assume the cohort workspace-scoped path + cursor pagination**: rejected — these entities are project-scoped and return an object map, so the cohort idiom would 404 (wrong scope) or mis-decode (wrong envelope).
- **Model formulas as a separate `/formulas/` endpoint**: rejected — confirmed against the backend, a formula is a metric with `type="formula"` on the same `/metrics/` endpoint; a separate endpoint would 404.
- **Single-item DELETE for metrics**: rejected — confirmed to return 501; metric/formula deletion routes through the bulk DELETE.

---

## R-2. `measurement.math` is a strict Pydantic `Literal` enum

**Decision**: Model `math` as a `Literal` with exactly the validated values: `total, unique, dau, wau, mau, average, median, min, max, sum, p25, p75, p90, p99, unique_values, conversion_rate_unique, conversion_rate_total, conversion_rate_session, retention_rate`. Any other value raises `ValidationError` at construction time.

**Rationale**: The power-tools reference states Mixpanel rejects the whole entity if `measurement.math` is anything else. The most common mistakes (`avg` for `average`, `unique_group` for group counts) are silent foot-guns; a `Literal` turns them into an immediate, local error with a message naming the right value.

**Alternatives considered**:
- **Free-form string + server-side 400**: rejected — slower failure, generic message, wastes a round-trip.
- **Auto-correct `avg` → `average`**: rejected — silent normalization violates Explicit Over Implicit; the user should learn the canonical name.

---

## R-3. `measurement.property` is a `MeasurementProperty` object, never a bare string

**Decision**: Model the aggregand as a `MeasurementProperty` dataclass/model with `name`, `type`, `resource_type` (serialized `resourceType`). A bare string is unrepresentable in the type and raises `ValidationError`. Property presence splits into THREE branches, confirmed against the Mixpanel backend: (1) property-aggregation math (`average`/`median`/`min`/`max`/`sum`/`p25`/`p75`/`p90`/`p99`/`unique_values`) — property REQUIRED; (2) plain counts (`total`/`unique`/`dau`/`wau`/`mau`) — property omitted from the emitted payload, and a stray property is silently stripped (the backend itself strips it on count maths) rather than rejected; (3) rate maths (`conversion_rate_unique`/`conversion_rate_total`/`conversion_rate_session`/`retention_rate`) — property FORBIDDEN (omitted), AND a behavior shape REQUIRED: the three `conversion_rate_*` require a funnel behavior with >= 2 steps, `retention_rate` requires a retention behavior with EXACTLY 2 steps. Real backend payloads emit `"property": null` for all four rate maths.

**Rationale**: The reference is explicit — a bare string like `"purchase.amount"` corrupts the metric and crashes the webapp query builder. Modeling it as an object makes the crashing form impossible to construct. The three-branch presence rule (required for aggregations, omitted/stripped for counts, forbidden-plus-behavior-shape for rates) is a cross-field validator, and the rate branch's behavior-shape requirement is confirmed against the backend (retention validation requires exactly 2 behaviors; conversion rates require a funnel).

**Alternatives considered**:
- **Accept `str | MeasurementProperty` and coerce strings**: rejected — coercion would hide the exact bug the reference warns about; the str form must be a hard error.
- **Always include property, set null for counts**: rejected — the reference says counts MUST omit property; emitting `property: null` risks the same query-builder corruption.

---

## R-4. Behavior step-count and `funnelOrder` validators

**Decision**: `CreateBehaviorParams` enforces step counts by type — simple >=1, funnel >=2, retention EXACTLY 2 — and `funnel_order` is a `Literal["loose", "any"]`. Every `BehaviorStep` requires a non-empty `name`. All violations raise `ValidationError` at construction time. The same `BehaviorStep` + step-count machinery validates the embedded behavior inside a metric.

**Rationale**: The reference states malformed / short steps crash the webapp *on load* (worse than a 400), and that `funnelOrder` is a strict `loose|any` enum with no `strict`. Retention with !=2 steps crashes the query builder. These are exactly the invariants a typed param model should own.

**Alternatives considered**:
- **Validate only at the API layer**: rejected — the failure mode is a webapp crash, not a clean API error, so client-side construction-time validation is the only safe guard.
- **Allow `strict` and let the server reject**: rejected — `strict` is not valid; representing it invites the bug.

---

## R-5. Formula variable ↔ referencedMetrics 1:1 mapping

**Decision**: `CreateFormulaParams` parses the uppercase variable tokens (`A`, `B`, `C`, ...) out of `definition`, requires them contiguous-from-`A`, and requires their distinct count to equal `len(referenced_metrics)`. `referenced_metrics[i]` maps to the i-th variable by array order. Each `display` object emits only the allowed keys (`abbrev, axis, direction, hideTrendline, precision, prefix, suffix, trendline`); there is no `label` key.

**Rationale**: The reference states the variable count MUST equal `referencedMetrics.length`, contiguous from `A`, and that `display` has no `label` field (a `label` key 400s). A regex extracting `[A-Z]` tokens, deduped and sorted, gives the variable set; comparing it to `["A", "B", ...][:n]` enforces contiguity.

**Edge note**: variable extraction must avoid matching uppercase letters inside function names (none exist in the simple `+ - * /` formula grammar the reference allows, but the validator restricts to standalone single-letter tokens to be safe).

**Alternatives considered**:
- **Trust the caller's variable list**: rejected — the whole feature is refusing to emit crashing payloads.
- **Allow non-contiguous variables (A, C)**: rejected — the reference requires contiguity; a gap means a referenced metric has no variable, which breaks the formula.

---

## R-6. Mirror the cohort / custom-property surface exactly

**Decision**: The new CRUD methods follow the cohort method *naming* shape — `list_*`, `get_*(id)`, `create_*(params)`, `update_*(id, params)`, `delete_*(id)` — with `params.model_dump(exclude_none=True)` bodies and `Model.model_validate(raw)` decode. The transport differs from cohorts in three confirmed ways (R-1): the paths are project-scoped (no workspace scoping), `list_*` parses the object-map list envelope into a list (no cursor pagination helper), and metric/formula deletion goes through the bulk DELETE (single-item metric DELETE returns 501). Formulas route through the metrics endpoint with `type="formula"`, so `create_formula` / `list_formulas` / `update_formula` / `delete_formula` are the metrics client methods discriminated by `type`.

**`exclude_none` exception — `ReferencedMetric`**: the universal `exclude_none=True` rule has exactly one documented exception. Confirmed against the Mixpanel backend, a saved formula stores each `referencedMetrics[i]` measurement block with its nullable keys (`property`, `rolling`, `perUserAggregation`) as EXPLICIT NULLS and `cumulative` as an explicit boolean (`false`). To round-trip a formula the library MUST emit those explicit nulls, so `ReferencedMetric` carries a custom Pydantic v2 serializer (a `@model_serializer`, or a per-call `model_dump(by_alias=True)` WITHOUT `exclude_none`) that keeps the nulls; the enclosing `CreateFormulaParams` keeps `exclude_none=True` for its own top-level keys. This is recorded in [data-model.md §7.3](data-model.md) and the matching wire shape is [contracts/payload-shapes.md §6](contracts/payload-shapes.md). (`exclude_none` is still correct on response paths; the explicit nulls are authoritative for the stored/sent formula payload.)

**Rationale**: Consistency lowers the contributor-onboarding cost (SC-007), reuses the proven error-mapping and pagination paths, and makes the auto-discovery (`help.py`) output uniform with the rest of the surface. The single `ReferencedMetric` exception is required by the confirmed backend contract — omitting the nulls would not round-trip.

**Alternatives considered**:
- **A fluent builder API**: rejected — inconsistent with the rest of the repo; the Pydantic param model is already the builder.

---

## R-7. First consumer is the metric-maker skill (feature 048)

**Decision**: This feature ships as a standalone library PR. Its first consumer is the metric-maker skill (feature 048), which calls `create_behavior` / `create_metric` / `create_formula` to assemble starter kits. The skill adds no library code; all the validation lives in this feature's param models, so the skill cannot construct a crashing payload either.

**Rationale**: Keeping the bindings standalone means anyone scripting `mixpanel-headless` gets the semantic layer immediately, and the skill becomes a thin orchestration layer over a validated surface. The dependency runs one way only: 048 depends on 047, never the reverse.

**Alternatives considered**:
- **Bundle the bindings into the skill PR**: rejected — couples an independently-useful library change to a skill that ships on a different cadence; the library is the load-bearing primitive and should land first on its own merits.

---

## R-8. Validation precedent and the `Metric` / `Behavior` naming collision

**Decision**: Re-use, rather than re-derive, the construction-time validation precedent already in the repo, and resolve the result-type naming collision explicitly before export.

Spec 036-cohort-behaviors and spec 037-custom-properties-queries already establish the pattern this feature needs: frozen Pydantic param models that fail fast with `ValidationError` / `ValueError` at construction time before any HTTP call, with named validation-rule IDs (036's CF1/CB1/CM1, 037's CP1–CP6) that each map 1:1 to a unit test. This feature adopts the identical pattern and the same ID convention — metric rules M1, M2, ...; behavior rules B1, B2, ...; formula rules F1, F2, ... — so SC-002's "one unit test per failure class" maps 1:1 to a rule, exactly as 036/037 do. The behavior step-count rules also echo the step / criteria validation lineage in spec 035-cohort-definition-builder.

**Naming collision**: spec 036 already introduced query-layer shapes named `Metric` / `CohortMetric` and the `behavior.type` / `measurement.math` show-entry vocabulary. The new saved-entity result types `Metric` and `Behavior` collide by name in `mixpanel_headless.__init__` exports. Because formulas ride the metrics endpoint (R-1) and "metric" is the entity the query layer already exports, the resolved direction is to keep the existing query-layer types where they live and export the new saved-entity result types under unambiguous, saved-entity-prefixed names (e.g. `SavedMetric` / `SavedBehavior`) so neither shadows an existing public symbol; the `Create*Params` / `Update*Params` names do not collide and stay as written. The exact exported names are locked at FR-018 / T018 / T036 time once the live `__all__` is inspected; this stays a reconciliation note (no export may shadow an existing public symbol) and is recorded in `data-model.md`.

**Rationale**: re-deriving validation idioms that 036/037 already proved wastes review and risks divergence; the named-rule-ID convention makes the validator table, the error catalog, and the test suite traceable to each other. The collision must be surfaced now because it changes the public export names, which are part of the contract.

**Alternatives considered**:
- **Invent a fresh validation idiom**: rejected — 036/037 are the established precedent; consistency lowers onboarding cost (SC-007).
- **Silently shadow the query-layer `Metric`**: rejected — an ambiguous re-export breaks callers who already import the query-layer type; the collision must be resolved by name.
