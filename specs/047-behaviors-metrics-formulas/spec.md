# Feature Specification: Behaviors, Metrics & Formulas CRUD for `mixpanel-headless`

**Feature Branch**: `047-behaviors-metrics-formulas`
**Created**: 2026-06-28
**Status**: Draft
**Input**: User description: "expose behaviors / metrics / formulas CRUD on Workspace — the typed semantic-layer bindings"

## Overview

This feature extends `Workspace` with full CRUD (list / get / create / update / delete) for the three saved-entity types Mixpanel calls **behaviors**, **metrics**, and **formulas**, mirroring the existing cohort and custom-property surface (spec 024-core-entity-crud, spec 027-data-governance-crud). Pydantic v2 `Create*`/`Update*` param models bake in the validators that stop Mixpanel from 400-ing or crashing its own webapp on load. `Metric`/`Behavior`/`Formula` result types carry the round-tripped definitions with `.df` / `.to_dict()` per the existing result-type contract. New App API endpoints are plumbed through `MixpanelAPIClient` using the `maybe_scoped_path` / `app_request` / pagination idiom cohorts already use (spec 024 / spec 027), and `__init__.py` exports that `help.py` auto-discovers.

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

- **Unconfirmed endpoint shapes**: the App API endpoints + request/response shapes for behaviors / metrics / formulas are reverse-engineered from the power-tools macros ([mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools)) and MUST be confirmed with one live call before the binding surface is finalized (see research.md R-1, NEEDS-CONFIRMATION). If a shape differs, the param models stay the same and only the client plumbing changes.
- **`math="unique_group"` / `groupKey`**: callers asking for group-level distinct counts get a `ValidationError` directing them to `math="unique"` + a numeric `data_group_id`, because no `unique_group` math and no `groupKey` field exist.
- **Empty / missing behavior steps**: a metric or behavior with an empty `behaviors` array is rejected at construction time (it crashes the webapp on load, not just a 400).
- **Property aggregation without a property**: `math="average"` (or any property-aggregation math) without a `property` object is rejected at construction time.
- **Plain count with a stray property**: `math="total"`/`"unique"` with a `property` set is normalized to omit the property (or rejected) per the power-tools contract.
- **Formula referencing a non-existent metric ID**: the library cannot verify referenced metric IDs exist without a round-trip; it documents that an unknown ID surfaces as a server 400, mapped to `QueryError`.

## Requirements *(mandatory)*

### Functional Requirements

#### Metrics

- **FR-001**: `Workspace` MUST expose `list_metrics`, `get_metric`, `create_metric`, `update_metric`, `delete_metric`, mirroring the cohort CRUD shape — the `list_/get_/create_/update_/delete_` + `bulk_*` method-naming idiom and result-type contract established in spec 024-core-entity-crud and spec 027-data-governance-crud (param models in `types.py`, App API plumbing through the existing client + pagination helper). The same lineage applies to the behavior (FR-006) and formula (FR-011) families.
- **FR-002**: `CreateMetricParams.math` and `UpdateMetricParams.math` MUST be a strict `Literal` enum: `total, unique, dau, wau, mau, average, median, min, max, sum, p25, p75, p90, p99, unique_values, conversion_rate_unique, conversion_rate_total, conversion_rate_session, retention_rate`. Any other value MUST raise `ValidationError` at construction time, before any HTTP call.
- **FR-003**: `measurement.property` MUST be modeled as a `MeasurementProperty` object with `name`, `type`, `resource_type` (serialized as `resourceType`). A bare string for the property MUST raise `ValidationError`. For property-aggregation math (`average, median, min, max, sum, p25, p75, p90, p99, unique_values`) the property is REQUIRED; for plain counts (`total, unique, dau, wau, mau`) the property MUST be omitted from the emitted payload.
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
- **FR-016**: The new App API endpoints MUST be plumbed through the existing `MixpanelAPIClient` using the `maybe_scoped_path` / `app_request` / cursor-pagination idiom already used by cohorts and the custom-event / custom-property CRUD that shipped in spec 024-core-entity-crud and spec 027-data-governance-crud (workspace-scoped, `WorkspaceScopeError` when unset). The exact endpoint paths + request/response shapes MUST be confirmed by one live call and recorded in `contracts/` before the surface is finalized.
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
- **SC-002**: The library refuses, at construction time (zero HTTP round-trips), every payload class the power-tools reference ([mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools), `templates/prompts/ai-behaviors-metrics-system.txt`) flags as webapp-crashing or 400-inducing: bad `math` enum, bare-string property, property-aggregation-without-property, empty / wrong-count behavior steps, `funnel_order="strict"`, and a formula whose variables do not map 1:1 to referenced metrics. Verified by unit tests, one per named validation rule (M*/B*/F* per FR-015), mapping 1:1 to a failure class.
- **SC-003**: The feature reaches >=90% line coverage (`just test-cov`) on the new types + workspace methods + client plumbing, and the new pure validator modules reach >=80% mutation score (`just mutate-check`).
- **SC-004**: The exact App API endpoint paths and request/response shapes for behaviors / metrics / formulas are confirmed by one live call and recorded in `contracts/` before the binding surface is frozen; `research.md` records the NEEDS-CONFIRMATION risk explicitly.
- **SC-005**: `python help.py Workspace.create_metric` (and the behavior / formula equivalents) returns the documented signature + docstring + referenced types via auto-discovery, with no manual help.py edits.
- **SC-006**: The feature ships independently and delivers value (full programmatic semantic-layer CRUD) on its own; it does not depend on the metric-maker skill (feature 048) — the dependency runs the other way.
- **SC-007**: A new contributor can read the spec, the contracts, and the type docstrings, then add a fourth saved-entity binding without reverse-engineering the payload shapes again.

## Assumptions

- The App API exposes behaviors / metrics / formulas as saved entities reachable through the same `maybe_scoped_path` / `app_request` idiom cohorts use (spec 024 / spec 027). The exact paths are reverse-engineered from the power-tools macros and confirmed by one live call before freeze (see research.md R-1). If a shape changes, the surface to update is small (one client section + the param-model serializers).
- The validated payload constraints in [mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools), `templates/prompts/ai-behaviors-metrics-system.txt`, are authoritative for what crashes the webapp / 400s; the Pydantic validators encode them verbatim.
- `networkx`, `anytree`, and `pandas` are already core dependencies; no new install weight is added.
- Custom-event and custom-property CRUD already exist on `Workspace` from spec 027-data-governance-crud (verified); this feature adds only behaviors / metrics / formulas to the library.
- The construction-time validation precedent (frozen param models, fail-fast `ValidationError`, named validation-rule IDs) is established in spec 036-cohort-behaviors and spec 037-custom-properties-queries; this feature follows it (FR-015). The behavior step-count rules echo the cohort criteria / step validation lineage in spec 035-cohort-definition-builder.
- This is the FIRST PR in the metric-maker chain. The metric-maker skill (feature 048) is its first consumer and DEPENDS ON this feature being merged/released first; this feature has no reverse dependency on 048.
- Out of scope: the metric-maker skill itself (feature 048), dashboards (dashboard-expert), lexicon hide / annotate / tag (data-clean-up, feature 045), raw ad-hoc querying (mixpanelyst), and any irreversible governance op (merge / delete / drop-filter as an orchestrated step).
