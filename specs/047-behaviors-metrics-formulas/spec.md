# Feature Specification: Behaviors, Metrics & Formulas CRUD for `mixpanel-headless`

**Feature Branch**: `047-behaviors-metrics-formulas`
**Created**: 2026-06-28
**Status**: Draft
**Input**: User description: "expose behaviors / metrics / formulas CRUD on Workspace — the typed semantic-layer bindings"

## Overview

This feature extends `Workspace` with full CRUD (list / get / create / update / delete) for the three saved-entity types Mixpanel calls **behaviors**, **metrics**, and **formulas**, mirroring the existing cohort and custom-property surface (spec 024-core-entity-crud, spec 027-data-governance-crud). Pydantic v2 `Create*`/`Update*` param models bake in the validators that stop Mixpanel from 400-ing or crashing its own webapp on load. `Metric`/`Behavior`/`Formula` result types carry the round-tripped definitions with `.df` / `.to_dict()` per the existing result-type contract. New App API endpoints are plumbed through `MixpanelAPIClient` via `app_request` on two project-scoped endpoints (`/behaviors/` and the shared `/metrics/` for metrics and formulas), parsing the confirmed object-map list envelope, and `__init__.py` exports that `help.py` auto-discovers.

A raw Mixpanel project is hundreds of events and properties; the people who consume it day-to-day need a handful of clean concepts. Behaviors, metrics, and formulas ARE that compression layer: raw events → governed events (the visible surface) → behaviors (dozens of reusable user-action concepts) → metrics and formulas (a handful of governed KPIs), each layer compressing the one below into business language. This feature ships the typed, composable, reusable primitives for that layer — saved, named entities with a clear rationale, not anonymous inline one-offs — so a PM reads "Power Buyers" or "Weekly Active" instead of SDK noise. Because the layer generalizes across the universal dataset spine every Mixpanel project shares (identity, attribution, platform, geo, time, value), the same primitives serve any project.

This is the **first PR in the metric-maker chain**. It is the load-bearing primitive: the **metric-maker skill (feature 048)** is its first consumer (it calls `create_behavior` / `create_metric` / `create_formula` to assemble starter kits), but the library is independently useful to anyone scripting `mixpanel-headless` — a Python user gets full programmatic control of the semantic layer with or without the skill.

The full repo gates apply: `mypy --strict`, ruff, >=90% coverage, complete docstrings, strict TDD, `just check` green.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Create and manage a metric from Python (Priority: P1)

A data engineer wants to define a named KPI once (e.g. "Average Order Value") and reference it everywhere instead of re-deriving the aggregation in every report. They use `mixpanel-headless` to create a metric with the correct `measurement.math` and a property-object aggregand, read it back, update its description, and delete it when it is superseded.

**Why this priority**: This is the foundational primitive. Behaviors, formulas, and every downstream consumer (including feature 048) depend on the metric binding existing and refusing to emit a payload Mixpanel rejects. It is independently shippable: a Python user gets full programmatic control of the semantic layer even if no other story ships.

**Independent Test**: With a live (or recorded) project, `ws.create_metric(CreateMetricParams(...))` returns a `Metric` with a server-assigned ID; `ws.get_metric(id)` round-trips it; `ws.update_metric(id, UpdateMetricParams(description="..."))` reflects the change; `ws.delete_metric(id)` removes it; `ws.list_metrics()` no longer contains it. A `CreateMetricParams` built with `math="avg"` or a bare-string `property` raises `ValidationError` BEFORE any HTTP call.

**Acceptance Scenarios**:

1. **Given** a numeric event property `amount` on a `purchase` event, **When** the caller builds `CreateMetricParams(name="Average Order Value", math="average", property=MeasurementProperty(name="amount", type="number", resource_type="events"), steps=[BehaviorStep(name="purchase")])`, **Then** the model validates and `create_metric` POSTs a payload whose `measurement.property` is an object `{"name": "amount", "type": "number", "resourceType": "events"}`, never a bare string.
2. **Given** a caller who passes `math="avg"`, **When** `CreateMetricParams` is constructed, **Then** a `ValidationError` is raised naming the valid enum and pointing at `average` — no HTTP round-trip occurs.
3. **Given** a caller who passes a bare string for `property` (e.g. `property="amount"`), **When** `CreateMetricParams` is constructed, **Then** a `ValidationError` is raised stating the property MUST be a `MeasurementProperty` object.
4. **Given** a metric created in scenario 1, **When** `get_metric(id)` then `update_metric(id, UpdateMetricParams(name="AOV"))` then `delete_metric(id)` are called in sequence, **Then** each returns the documented type and the final `list_metrics()` omits the ID.
5. **Given** a count metric (`math="total"`), **When** `CreateMetricParams` is built without a `property`, **Then** validation passes and the emitted `measurement` omits the `property` key entirely.

---

### User Story 2 — Create and manage behaviors (simple / funnel / retention) from Python (Priority: P1)

A platform engineer wants to encode reusable user-action definitions: a "Shopping Activity" simple behavior (OR over several events), a "Checkout Funnel" funnel behavior, and a "Weekly Retention" retention behavior. They create each via `mixpanel-headless` and the library refuses any step count or funnel-order that would crash the Mixpanel query builder on load.

**Why this priority**: Behaviors are the second foundational primitive and the riskiest to get wrong (malformed steps crash the webapp, not just 400). Co-equal P1 with metrics because a metric's `definition.behavior` is itself a behavior shape; the two share the same `BehaviorStep` / step-count validators.

**Independent Test**: `create_behavior` round-trips a simple, a funnel, and a retention behavior. `CreateBehaviorParams` raises `ValidationError` for: a funnel with 1 step, a retention with 1 or 3 steps, a step missing `name`, and `funnel_order="strict"`. A retention behavior with exactly 2 steps and a funnel with >=2 steps validate.

**Acceptance Scenarios**:

1. **Given** a simple behavior over `["page view", "button click"]`, **When** `create_behavior(CreateBehaviorParams(type="simple", steps=[...]))` is called, **Then** a `Behavior` with a server ID is returned and the payload carries a non-empty `definition.behavior.behaviors` array of typed event steps.
2. **Given** a funnel behavior with a single step, **When** `CreateBehaviorParams(type="funnel", steps=[one_step])` is constructed, **Then** a `ValidationError` is raised stating funnels require >=2 steps.
3. **Given** a retention behavior with 3 steps, **When** the param model is constructed, **Then** a `ValidationError` is raised stating retention requires EXACTLY 2 steps (born + return).
4. **Given** a caller passing `funnel_order="strict"`, **When** the param model is constructed, **Then** a `ValidationError` is raised naming the valid enum (`loose`, `any`).
5. **Given** a funnel step missing a `name`, **When** the param model is constructed, **Then** a `ValidationError` is raised stating every step requires a non-empty `name`.

---

### User Story 3 — Create and manage formulas with 1:1 variable binding (Priority: P2)

An analyst wants a derived KPI like "Engagement Rate = (Active Users / Total Users) * 100" expressed as a formula over two named metrics. They build a `CreateFormulaParams` whose `referenced_metrics` array maps 1:1 (by array order) to the variables `A`, `B` used in the expression; the library refuses a formula whose variable count does not match the referenced-metrics count.

**Why this priority**: Formulas sit on top of metrics, so they ship after the metric primitive is proven. Independently valuable: an analyst gets composable derived KPIs without hand-assembling the fragile `referencedMetrics` payload.

**Independent Test**: `create_formula` round-trips a 2-variable formula. `CreateFormulaParams` raises `ValidationError` when the distinct variables in `definition` (e.g. `A`, `B`, `C`) are not contiguous-from-`A` or do not equal `len(referenced_metrics)`. A formula whose `definition="(A / B) * 100"` with exactly 2 referenced metrics validates.

**Acceptance Scenarios**:

1. **Given** `definition="(A / B) * 100"` and exactly two referenced metrics, **When** `CreateFormulaParams(...)` is constructed, **Then** validation passes and the emitted `referencedMetrics` array has length 2 in `A`, `B` order.
2. **Given** `definition="(A / B) * 100"` with only one referenced metric, **When** the param model is constructed, **Then** a `ValidationError` is raised stating variables must map 1:1 to referenced metrics.
3. **Given** `definition="(A / C) * 100"` (skipping `B`) with two referenced metrics, **When** the param model is constructed, **Then** a `ValidationError` is raised stating variables must be contiguous from `A`.
4. **Given** a formula created in scenario 1, **When** `get_formula(id)`, `update_formula(id, ...)`, `delete_formula(id)` run in sequence, **Then** each returns the documented type and the final `list_formulas()` omits the ID.

---

### Edge Cases

- **Endpoint transport (CONFIRMED)**: both the request/response BODY shapes and the transport for behaviors / metrics / formulas are confirmed against the Mixpanel backend App API (see research.md R-1, CONFIRMED). The paths are **project-scoped only** (no workspace scoping, unlike cohorts); the list-response envelope is an **object map keyed by string ID** (`{"status":"ok","results":{"<id>":{...}}}`) with **no cursor pagination**; and the three public method families map onto **two endpoints** — behaviors → `/behaviors/`, and BOTH metrics and formulas → `/metrics/` (a formula is a metric with `type="formula"`).
- **Single-item metric/formula DELETE is unsupported**: the single-item metric DELETE returns 501 NOT IMPLEMENTED (confirmed against the Mixpanel backend). Metric and formula deletion MUST therefore route through the bulk DELETE on the `/metrics/` collection path (`{"metrics":[{id}]}`). Behaviors support single-item DELETE; metrics/formulas do not. See FR-016a.
- **Type-discriminated metrics endpoint**: because formulas ride the `/metrics/` endpoint, the metric `type` field (`"metric"` vs `"formula"`) is the discriminator the client uses to route `create_formula` / `list_formulas` / `update_formula` / `delete_formula` through the metrics client methods. `list_metrics` and `list_formulas` both read the same `/metrics/` collection and partition the results by `type`.
- **`math="unique_group"` / `groupKey`**: callers asking for group-level distinct counts get a `ValidationError` directing them to `math="unique"` + a numeric `data_group_id`, because no `unique_group` math and no `groupKey` field exist.
- **Empty / missing behavior steps**: a metric or behavior with an empty `behaviors` array is rejected at construction time (it crashes the webapp on load, not just a 400).
- **Property aggregation without a property**: `math="average"` (or any property-aggregation math) without a `property` object is rejected at construction time.
- **Plain count with a stray property**: `math="total"`/`"unique"` (or any plain-count math) with a `property` set is normalized to omit the property from the emitted payload — a silent strip, not a rejection — matching the backend, which strips the property on count maths (confirmed against the Mixpanel backend). See FR-003a.
- **Rate math with a property or wrong behavior shape**: a rate math (`conversion_rate_*`, `retention_rate`) with a `property` is normalized to omit it; a `conversion_rate_*` over a non-funnel (or <2-step) behavior, or a `retention_rate` over a non-retention (or !=2-step) behavior, is rejected at construction time. See FR-003.
- **Formula referencing a non-existent metric ID**: the library cannot verify referenced metric IDs exist without a round-trip; it documents that an unknown ID surfaces as a server 400, mapped to `QueryError`.

## Requirements *(mandatory)*

### Functional Requirements

#### Metrics

- **FR-001**: `Workspace` MUST expose `list_metrics`, `get_metric`, `create_metric`, `update_metric`, `delete_metric`, mirroring the cohort CRUD *naming* shape — the `list_/get_/create_/update_/delete_` method-naming idiom and result-type contract established in spec 024-core-entity-crud and spec 027-data-governance-crud (param models in `types.py`, App API plumbing through the existing client via `app_request`). The transport differs from cohorts per FR-016/FR-016a (project-scoped, object-map list envelope, no pagination, bulk delete for metrics/formulas). The same lineage applies to the behavior (FR-006) and formula (FR-011) families.
- **FR-002**: `CreateMetricParams.math` and `UpdateMetricParams.math` MUST be a strict `Literal` enum: `total, unique, dau, wau, mau, average, median, min, max, sum, p25, p75, p90, p99, unique_values, conversion_rate_unique, conversion_rate_total, conversion_rate_session, retention_rate`. Any other value MUST raise `ValidationError` at construction time, before any HTTP call.
- **FR-003**: `measurement.property` MUST be modeled as a `MeasurementProperty` object with `name`, `type`, `resource_type` (serialized as `resourceType`). A bare string for the property MUST raise `ValidationError`. The 19 math values split into three property-presence branches, confirmed against the Mixpanel backend: (1) **property-aggregation** (`average, median, min, max, sum, p25, p75, p90, p99, unique_values`) — property REQUIRED; (2) **plain count** (`total, unique, dau, wau, mau`) — property omitted from the emitted payload (a stray property is normalized away, see FR-003a); (3) **rate** (`conversion_rate_unique, conversion_rate_total, conversion_rate_session, retention_rate`) — property FORBIDDEN (omitted from the emitted payload) AND a specific behavior shape REQUIRED: the three `conversion_rate_*` require a `funnel` behavior with >= 2 steps, `retention_rate` requires a `retention` behavior with EXACTLY 2 steps (born + return).
- **FR-003a**: For a plain-count math, a stray `property` MUST be normalized away (dropped from the emitted payload), matching the backend, which silently strips the property on count maths. This is a normalization, not a rejection.
- **FR-004**: The emitted `measurement` object MUST contain ONLY the keys `math, property, cumulative, dataGroupId, perUserAggregation, rolling, segmentMethod, multiAttribution` (omitting any unset). Unknown measurement keys MUST be impossible to emit.
- **FR-005**: A `Metric` result type MUST be returned by metric reads/writes, carrying at least `id`, `name`, `description`, and the round-tripped definition, with `.df` and `.to_dict()` per the existing result-type contract.

#### Behaviors

- **FR-006**: `Workspace` MUST expose `list_behaviors`, `get_behavior`, `create_behavior`, `update_behavior`, `delete_behavior`, following the same spec 024 / spec 027 CRUD method-naming idiom and result-type contract as the metric family (FR-001).
- **FR-007**: `CreateBehaviorParams.type` MUST be a `Literal["simple", "funnel", "retention"]`. Step-count validation MUST enforce: simple >= 1 step, funnel >= 2 steps, retention EXACTLY 2 steps. Violations MUST raise `ValidationError` at construction time.
- **FR-008**: Every `BehaviorStep` MUST carry a non-empty `name`; a step missing `name` MUST raise `ValidationError`. The emitted `definition.behavior.behaviors` array MUST never be empty.
- **FR-009**: `funnel_order` (top-level and per-step) MUST be a `Literal["loose", "any"]`. `"strict"` (or any other value) MUST raise `ValidationError`.
- **FR-010**: A `Behavior` result type MUST be returned by behavior reads/writes, carrying `id`, `name`, `description`, `type`, and the round-tripped definition, with `.df` and `.to_dict()`.

#### Formulas

- **FR-011**: `Workspace` MUST expose `list_formulas`, `get_formula`, `create_formula`, `update_formula`, `delete_formula`, following the same spec 024 / spec 027 CRUD method-naming idiom and result-type contract as the metric family (FR-001).
- **FR-012**: `CreateFormulaParams` MUST validate that the distinct variables referenced in `definition` (parsed as the uppercase tokens `A`, `B`, `C`, ...) are contiguous from `A` and that their count equals `len(referenced_metrics)`. Violations MUST raise `ValidationError` at construction time.
- **FR-013**: Each entry in `referenced_metrics` MUST emit a complete metric shape (behavior + measurement) and map to the formula variables by ARRAY ORDER (`referenced_metrics[0]` → `A`). Each `display` object MUST emit ONLY the allowed keys (`abbrev, axis, direction, hideTrendline, precision, prefix, suffix, trendline`); there is no `label` key.
- **FR-014**: A `Formula` result type MUST be returned by formula reads/writes, carrying `id`, `name`, `description`, `definition`, and the round-tripped referenced metrics, with `.df` and `.to_dict()`.

#### Cross-cutting

- **FR-015**: All new param models MUST be Pydantic v2, fully typed (`mypy --strict`), with complete docstrings (markdown code fences, not doctest), and the validators MUST be the authoritative guard that the library never emits a payload Mixpanel would 400 on or that would crash the webapp on load. They MUST follow the fail-fast construction-time validation precedent set by spec 036-cohort-behaviors and spec 037-custom-properties-queries (frozen param models, `ValidationError`/`ValueError` raised at construction before any HTTP call) and adopt the same named-validation-rule-ID convention (036's CF1/CB1/CM1, 037's CP1–CP6): metric rules M1, M2, ...; behavior rules B1, B2, ...; formula rules F1, F2, ... so each rule maps 1:1 to a unit test (SC-002) and to a stable error in `contracts/error-messages.md`.
- **FR-016**: The new App API endpoints MUST be plumbed through the existing `MixpanelAPIClient` via `app_request`, using **two project-scoped endpoints** confirmed against the Mixpanel backend (research.md R-1): `/api/app/projects/{project_id}/behaviors/` for behaviors, and `/api/app/projects/{project_id}/metrics/` for BOTH metrics and formulas (a formula is a metric with `type="formula"`). These entities are **project-scoped only** — there is NO workspace scoping and NO `WorkspaceScopeError` path (this differs from cohorts). The `list_*` methods MUST parse the confirmed **object-map list envelope** (`{"status":"ok","results":{"<id>":{...}}}`) — `results` is a map keyed by string ID, not an array — into a list of typed objects; there is NO cursor pagination for these entities (no pagination helper is used). The request/response BODY shapes and the transport are both confirmed and recorded in `contracts/`; T003 is a smoke-test verification, not a blocking confirmation gate.
- **FR-016a**: Metric and formula deletion MUST route through the **bulk DELETE** on the `/metrics/` collection path (body `{"metrics":[{id}]}`), because the single-item metric DELETE returns 501 NOT IMPLEMENTED (confirmed against the Mixpanel backend). `delete_metric(id)` and `delete_formula(id)` MUST therefore issue the bulk DELETE with a single-entry body. Behaviors support single-item DELETE (`delete_behavior(id)` hits `/behaviors/{id}/`); metrics/formulas do not. Bulk PATCH on the collection path (`{"metrics":[{id,...}]}` / `{"behaviors":[{id,...}]}`) is the confirmed bulk-update shape.
- **FR-017**: `help.py` MUST auto-discover the new `Workspace` methods and the new types (no manual help.py edits required beyond what auto-discovery covers).
- **FR-018**: All new public symbols (`Metric`, `Behavior`, `Formula`, `Create*Params`, `Update*Params`, `MeasurementProperty`, `BehaviorStep`, `ReferencedMetric`, and any enums) MUST be exported from `mixpanel_headless.__init__` and added to `__all__`. The new saved-entity result types `Metric` and `Behavior` overlap by name with the query-layer `Metric` / `CohortMetric` shapes that already exist from spec 036-cohort-behaviors (`behavior.type`, `measurement.math` show entries). This is a real naming-collision risk: FR-018 MUST reconcile the two namespaces — either keep the existing query-layer types where they live and export the new saved-entity types under distinct, unambiguous names, or otherwise guarantee no `__init__.py` export collides. The reconciliation decision is recorded in `data-model.md`.

### Key Entities

- **MeasurementProperty**: the property-aggregation aggregand. `name`, `type` (e.g. `"number"`), `resource_type` (serialized `resourceType`, e.g. `"events"`). The thing that, as a bare string, crashes the webapp; modeled as an object so it cannot be.
- **BehaviorStep**: one event step in a behavior. `name` (exact event name, required, non-empty), `type` (usually `"event"`), optional per-step `filters`, `funnel_order`. The atomic unit step-count validators count.
- **Behavior**: a saved user-action definition — `id`, `name`, `description`, `type` (`simple`/`funnel`/`retention`), and the round-tripped `definition.behavior`. Simple = OR over events; funnel = ordered conversion sequence; retention = born + return.
- **Metric**: a saved KPI — `id`, `name`, `description`, an embedded behavior (`definition.behavior`) plus a `measurement` (`math` enum + optional property object + allowed measurement keys).
- **Formula**: a saved derived KPI — `id`, `name`, `description`, a `definition` expression over variables `A`, `B`, ..., and a `referenced_metrics` array mapping 1:1 to those variables by order.
- **ReferencedMetric**: one entry in a formula's `referenced_metrics`; a complete metric shape (behavior + measurement) plus a `display` object restricted to the allowed keys.
- **Create\*Params / Update\*Params**: Pydantic v2 param models for each of the three entity types, carrying the validators that make a crashing payload unrepresentable.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A Python user can create, read, update, and delete a metric, a behavior, and a formula end-to-end against a live project, each in one method call per operation.
- **SC-002**: The library refuses, at construction time (zero HTTP round-trips), every payload class flagged (against the power-tools reference and confirmed against the Mixpanel backend) as webapp-crashing or 400-inducing: bad `math` enum (M1), property-aggregation-without-property (M2), bare-string property (M3), unknown measurement key (M4), rate-math behavior-shape mismatch (M6), empty / wrong-count behavior steps (B2), nameless step (B1), `funnel_order="strict"` (B3), and a formula whose variables do not map 1:1 to referenced metrics (F1) or whose referenced-metric `display` carries a disallowed key (F2). The two normalization rules — a stray property on a plain count (M2) and on a rate math (M5) — are asserted by tests confirming the property is dropped from the emitted payload, not raised. Verified by unit tests, one per named validation rule (M1–M6 / B1–B3 / F1–F2 per FR-015), each mapping 1:1 to a failure (or normalization) class.
- **SC-003**: The feature reaches >=90% line coverage (`just test-cov`) on the new types + workspace methods + client plumbing, and the new pure validator modules reach >=80% mutation score (`just mutate-check`).
- **SC-004**: Both the request/response BODY shapes AND the transport (project-scoped endpoint PATHS, the object-map list-response ENVELOPE, the two-endpoints-with-`type`-discriminator mapping, and the bulk-DELETE-for-metrics fact) for behaviors / metrics / formulas are confirmed against the Mixpanel backend App API and recorded in `contracts/`; `research.md` R-1 records them as CONFIRMED (no open NEEDS-CONFIRMATION). A live smoke-test round-trip (T003/T038) verifies the recorded shapes still hold; it is not a blocking confirmation gate.
- **SC-005**: `python help.py Workspace.create_metric` (and the behavior / formula equivalents) returns the documented signature + docstring + referenced types via auto-discovery, with no manual help.py edits.
- **SC-006**: The feature ships independently and delivers value (full programmatic semantic-layer CRUD) on its own; it does not depend on the metric-maker skill (feature 048) — the dependency runs the other way.
- **SC-007**: A new contributor can read the spec, the contracts, and the type docstrings, then add a fourth saved-entity binding without reverse-engineering the payload shapes again.

## Assumptions

- The App API exposes behaviors / metrics / formulas as saved entities reached through `app_request` on two **project-scoped** endpoints (`/behaviors/` and `/metrics/`, the latter shared by metrics and formulas via the `type` discriminator). The paths, the object-map list envelope, the bulk PATCH/DELETE shapes, and the single-item-metric-DELETE→501 fact are all confirmed against the Mixpanel backend (see research.md R-1, CONFIRMED); the bodies were already confirmed. These entities are project-scoped only (no workspace scoping, no cursor pagination) — a deliberate divergence from the cohort idiom.
- The validated payload constraints in [mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools), `templates/prompts/ai-behaviors-metrics-system.txt`, are authoritative for what crashes the webapp / 400s; the Pydantic validators encode them verbatim.
- `networkx`, `anytree`, and `pandas` are already core dependencies; no new install weight is added.
- Custom-event and custom-property CRUD already exist on `Workspace` from spec 027-data-governance-crud (verified); this feature adds only behaviors / metrics / formulas to the library.
- The construction-time validation precedent (frozen param models, fail-fast `ValidationError`, named validation-rule IDs) is established in spec 036-cohort-behaviors and spec 037-custom-properties-queries; this feature follows it (FR-015). The behavior step-count rules echo the cohort criteria / step validation lineage in spec 035-cohort-definition-builder.
- This is the FIRST PR in the metric-maker chain. The metric-maker skill (feature 048) is its first consumer and DEPENDS ON this feature being merged/released first; this feature has no reverse dependency on 048.
- Out of scope: the metric-maker skill itself (feature 048), dashboards (dashboard-expert), lexicon hide / annotate / tag (data-clean-up, feature 045), raw ad-hoc querying (mixpanelyst), and any irreversible governance op (merge / delete / drop-filter as an orchestrated step).
