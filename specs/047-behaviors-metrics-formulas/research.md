# Phase 0 Research: Behaviors, Metrics & Formulas CRUD

**Feature**: 047-behaviors-metrics-formulas
**Date**: 2026-06-28
**Status**: One open NEEDS-CONFIRMATION (R-1: exact endpoint shapes). All other decisions settled.

The validated payload constraints come from [mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools) (`templates/prompts/ai-behaviors-metrics-system.txt`), which encodes the structures that make Mixpanel 400 or crash its own webapp on load. This document records the decisions, their rationale, the rejected alternatives, and the single risk that must be closed by a live call before the binding surface is frozen.

---

## R-0. Why these three entities are one feature: the compression layer

**Decision**: Treat behaviors, metrics, and formulas as the three saved-entity types of a single semantic / compression layer, shipped together, rather than as three unrelated CRUD additions.

**Rationale**: A raw Mixpanel project is hundreds of events and properties; the analysts and PMs who consume it need a handful of clean concepts. The layering is: raw events (hundreds) → governed, visible events → behaviors (dozens of reusable user-action concepts) → metrics and formulas (a handful of governed KPIs). Each layer compresses the one below into business language, and the three entity types in this feature ARE the top of that pyramid — a behavior groups events into a reusable concept, a metric is a governed calculation over a behavior, a formula composes metrics. Modeling them as one typed, composable, reusable surface (saved named entities, never anonymous inline one-offs) is what makes the layer coherent: a metric's `definition.behavior` is literally a behavior, and a formula's `referencedMetrics[i]` is literally a metric. They share the `BehaviorStep` / `MeasurementProperty` / step-count machinery, so one feature, one set of validators.

**Generalization**: the layer is dataset-agnostic. Every Mixpanel project shares the same recurring classes — identity (`distinct_id` / `user_id` / `device_id`), attribution (`utm_*`, source, medium, campaign), platform/device, geo, time, and value/revenue — and the same universal metric archetypes (acquisition, activation, engagement / DAU-WAU-MAU + stickiness, retention, revenue/value). The primitives this feature ships are exactly what a caller needs to express those archetypes on any project, which is why the surface is a library primitive and not bespoke per-customer code.

**Alternatives considered**:
- **Three separate features / PRs**: rejected — they share validators and embed one another; splitting them would duplicate the `BehaviorStep` / measurement machinery and break the embedding relationship.
- **A generic "saved entity" CRUD**: rejected for the typing/validation reasons in plan.md Complexity Tracking; the per-type Pydantic validation is the whole point.

---

## R-1. Exact App API endpoints + request/response shapes — NEEDS CONFIRMATION

**Decision (provisional)**: Behaviors, metrics, and formulas are saved entities reachable through the same `maybe_scoped_path` / `app_request` idiom cohorts already use (`/api/app/projects/{pid}/...`, workspace-scoped when a workspace is set). The build session MUST reverse-engineer the exact paths + request/response shapes from the power-tools macros AND confirm with one live call before finalizing the binding surface. The confirmed contracts are recorded in `contracts/payload-shapes.md`; the types are recorded in `data-model.md`.

**Why this is a risk**: The cohort surface is confirmed (`list_cohorts_app` → `maybe_scoped_path("cohorts")` → `/api/app/projects/{pid}/cohorts`, POST/PATCH/DELETE the same path with an `{id}` suffix). Behaviors / metrics / formulas are documented in the power-tools macros at the *payload* level but their exact *endpoint paths* and *list-response envelope* (cursor-paginated like cohorts? wrapped in a `results` key? scoped to workspace or project?) are not yet verified against a live response in this repo.

**Confirmation procedure (MUST run before freeze)**:
1. Inspect the power-tools macros that create / list behaviors, metrics, formulas; extract the candidate paths and bodies.
2. Issue one live `GET` (list) per entity type against the demo project via `ws.api.app_request(...)` and capture the real response envelope.
3. Issue one live `POST` (create) with a minimal valid body, capture the assigned-ID response, then `DELETE` to clean up.
4. Record the confirmed paths, request bodies, and response envelopes in `contracts/payload-shapes.md`. Update `data-model.md` if the response shape differs from the provisional model.

**Rationale for the idiom choice**: Cohorts, dashboards, bookmarks, feature flags, and custom properties all go through `app_request` + `maybe_scoped_path` + the cursor pagination helper. The semantic-layer entities are the same family of saved App API objects; reusing the idiom keeps one error-mapping path and one pagination path.

**Alternatives considered**:
- **Assume the cohort path shape and skip the live call**: rejected — a wrong path or envelope would ship a binding that 404s or mis-decodes; the whole point is to be the trustworthy client.
- **Wrap the power-tools HTTP layer as a sidecar**: rejected — adds a runtime dependency and a network hop for what is a direct App API call.

---

## R-2. `measurement.math` is a strict Pydantic `Literal` enum

**Decision**: Model `math` as a `Literal` with exactly the validated values: `total, unique, dau, wau, mau, average, median, min, max, sum, p25, p75, p90, p99, unique_values, conversion_rate_unique, conversion_rate_total, conversion_rate_session, retention_rate`. Any other value raises `ValidationError` at construction time.

**Rationale**: The power-tools reference states Mixpanel rejects the whole entity if `measurement.math` is anything else. The most common mistakes (`avg` for `average`, `unique_group` for group counts) are silent foot-guns; a `Literal` turns them into an immediate, local error with a message naming the right value.

**Alternatives considered**:
- **Free-form string + server-side 400**: rejected — slower failure, generic message, wastes a round-trip.
- **Auto-correct `avg` → `average`**: rejected — silent normalization violates Explicit Over Implicit; the user should learn the canonical name.

---

## R-3. `measurement.property` is a `MeasurementProperty` object, never a bare string

**Decision**: Model the aggregand as a `MeasurementProperty` dataclass/model with `name`, `type`, `resource_type` (serialized `resourceType`). A bare string is unrepresentable in the type and raises `ValidationError`. For property-aggregation math the property is REQUIRED; for plain counts it MUST be omitted from the emitted payload.

**Rationale**: The reference is explicit — a bare string like `"purchase.amount"` corrupts the metric and crashes the webapp query builder. Modeling it as an object makes the crashing form impossible to construct. The presence/absence rule (required for `average`/`sum`/percentiles, omitted for `total`/`unique`/`dau`) is a cross-field validator.

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

**Decision**: The new CRUD methods follow the cohort method shape verbatim — `list_*` (cursor-paginated via the existing helper), `get_*(id)`, `create_*(params)`, `update_*(id, params)`, `delete_*(id)` — with `params.model_dump(exclude_none=True)` bodies and `Model.model_validate(raw)` decode. The client methods follow `list_cohorts_app` / `create_cohort` shape.

**Rationale**: Consistency lowers the contributor-onboarding cost (SC-007), reuses the proven error-mapping and pagination paths, and makes the auto-discovery (`help.py`) output uniform with the rest of the surface.

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

**Naming collision**: spec 036 already introduced query-layer shapes named `Metric` / `CohortMetric` and the `behavior.type` / `measurement.math` show-entry vocabulary. The new saved-entity result types `Metric` and `Behavior` collide by name in `mixpanel_headless.__init__` exports. This is a real risk FR-018 must close: keep the existing query-layer types where they live and export the new saved-entity types under unambiguous names (or otherwise guarantee no `__init__.py` export collides). The chosen reconciliation is recorded in `data-model.md`.

**Rationale**: re-deriving validation idioms that 036/037 already proved wastes review and risks divergence; the named-rule-ID convention makes the validator table, the error catalog, and the test suite traceable to each other. The collision must be surfaced now because it changes the public export names, which are part of the contract.

**Alternatives considered**:
- **Invent a fresh validation idiom**: rejected — 036/037 are the established precedent; consistency lowers onboarding cost (SC-007).
- **Silently shadow the query-layer `Metric`**: rejected — an ambiguous re-export breaks callers who already import the query-layer type; the collision must be resolved by name.
