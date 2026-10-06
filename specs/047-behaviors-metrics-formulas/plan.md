# Implementation Plan: Behaviors, Metrics & Formulas CRUD

**Branch**: `047-behaviors-metrics-formulas` (proposed) | **Date**: 2026-06-28 | **Spec**: [spec.md](spec.md)
**PR strategy**: Single PR — the typed library bindings for behaviors / metrics / formulas. This is the **first PR in the metric-maker chain**: it lands on its own, is independently shippable and reviewable, and unblocks the metric-maker skill (feature 048), which consumes this surface. Nothing in this PR depends on 048.

## Summary

Add Mixpanel's modeling / semantic layer to `mixpanel-headless` as a typed library surface: extend `Workspace` with full CRUD for the three saved-entity types Mixpanel calls **behaviors**, **metrics**, and **formulas**, mirroring the existing cohort / custom-property *method-naming* surface. Pydantic v2 `Create*`/`Update*` param models + `Metric`/`Behavior`/`Formula` result types in `types.py`, methods on `workspace.py`, App API plumbing through `MixpanelAPIClient` via `app_request` on two project-scoped endpoints (`/behaviors/` and the shared `/metrics/` for metrics + formulas, discriminated by `type`; object-map list envelope, no pagination — confirmed, research.md R-1), and `__init__.py` exports that `help.py` auto-discovers.

The load-bearing decision is that the param-model validators are the authoritative guard that the library can never emit a payload Mixpanel would 400 on or that would crash the webapp on load. The validated constraints come from [mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools) (`templates/prompts/ai-behaviors-metrics-system.txt`) and are baked in as Pydantic validators: the `measurement.math` strict enum, the `measurement.property` object requirement, behavior step-count rules (simple >=1, funnel >=2, retention ==2), `funnelOrder` loose|any only, and the formula 1:1 variable↔referencedMetrics mapping. The validators follow the fail-fast construction-time + named-rule-ID precedent from spec 036-cohort-behaviors / spec 037-custom-properties-queries (see spec.md FR-015).

This feature is independently useful to anyone scripting `mixpanel-headless` (full programmatic semantic-layer CRUD). The **metric-maker skill (feature 048)** is its first consumer — it calls `create_behavior` / `create_metric` / `create_formula` to assemble starter kits — but ships separately as its own PR after this one merges.

Estimated scope: ~1,300 LoC across ~4 modified source files plus new tests.

## Technical Context

**Language/Version**: Python 3.10+ (mypy --strict compliant).

**Primary Dependencies**:
- Reused: Pydantic v2 (param models + validators), httpx (HTTP client), pandas (result `.df`), Typer/Rich (no new CLI in this feature), Hypothesis (PBT), mutmut (mutation testing).
- New: none. No new runtime dependencies; the validators are pure stdlib + Pydantic.

**Storage**: None. These are remote App API entities; the feature persists nothing to `~/.mp`.

**Testing**: pytest (unit + integration); Hypothesis PBT for the math-enum / step-count / formula-variable validators; mutmut on the new pure validator modules. Integration tests gated on a live fixture project (the demo project or equivalent) to smoke-test the confirmed endpoint shapes and round-trip CRUD.

**Target Platform**: Cross-platform. No platform-specific code paths.

**Project Type**: Library feature addition. No CLI commands added; the semantic layer is a Python surface.

**Performance Goals**:
- Each CRUD method is a single App API round-trip; `list_*` parses the object-map list envelope (no cursor pagination for these entities).
- Param-model validation is in-process and sub-millisecond; it MUST run before any HTTP call.

**Constraints**:
- mypy --strict, zero `Any` lacking explicit justification.
- ruff format / check passes with zero violations.
- 90% test coverage minimum (CI fails below).
- 80% mutation score on the new validator modules.
- The library MUST NOT be able to emit a payload that violates the power-tools constraints; validators are the gate.
- The request/response BODY shapes AND the transport (project-scoped endpoint PATHS, the object-map list-response ENVELOPE, the two-endpoints-with-`type`-discriminator mapping, the bulk-DELETE-for-metrics fact) are confirmed against the Mixpanel backend App API (research.md R-1, CONFIRMED).

**Scale/Scope**:
- ~4 modified files (`types.py`, `workspace.py`, `_internal/api_client.py`, `__init__.py`) + new tests, ~1,300 LoC including tests.

## Dependency position in the metric-maker chain

| Feature | Role | Relationship |
|---------|------|--------------|
| **047-behaviors-metrics-formulas** (this) | The typed library bindings | Ships FIRST, on its own. No dependency on 048. |
| **048-metric-maker** | The lego-block architect skill | DEPENDS ON this feature; it calls `create_behavior` / `create_metric` / `create_formula`. Cannot begin until 047 is merged/released. |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Library-First | PASS | The semantic layer is a public `Workspace` surface (15 new methods); all public methods have type hints and docstrings. |
| II. Agent-Native | PASS | Library methods are non-interactive and return structured types. |
| III. Context Window Efficiency | PASS | Result types expose `.df`/`.to_dict()` for compact projections; no full-payload dumps required to use the surface. `help.py` auto-discovery keeps API docs out of the prompt. |
| IV. Two Data Paths | PASS | Live path: CRUD via the App API. Local path: result types expose `.df` for inspection in pandas / DuckDB. Both share the authenticated `Workspace`. |
| V. Explicit Over Implicit | PASS | Plain-count metrics omit `property` explicitly; property-aggregation math requires it explicitly. No silent normalization that hides a modeling choice (the one normalization — stripping a stray property off a count metric — is documented). |
| VI. Unix Philosophy | PASS | Each CRUD method does one thing; callers compose them. |
| VII. Secure by Default | PASS | The bindings are non-interactive primitives that map server failures to the existing exception hierarchy; no new credential surface. Writes are explicit single-entity calls. |

**Gate Result**: PASS. No violations. See [Complexity Tracking](#complexity-tracking) for the one design choice that warrants a recorded rationale (three CRUD families rather than one generic surface).

## Project Structure

### Documentation (this feature)

```text
specs/047-behaviors-metrics-formulas/
├── plan.md                       # This file
├── spec.md                       # Feature specification
├── research.md                   # Phase 0 output — endpoint contract (R-1 CONFIRMED) + design decisions
├── data-model.md                 # Phase 1 output — param models, result types, validators
├── quickstart.md                 # Library walkthrough (US1–US3)
└── contracts/                    # Phase 1 output
    ├── python-api.md             # Workspace methods + result types + param models
    ├── payload-shapes.md         # behaviors / metrics / formulas request/response shapes (the confirmed contracts)
    └── error-messages.md         # Stable validator + API error catalog
```

### Source Code (repository root)

```text
src/mixpanel_headless/
├── workspace.py                  # MODIFIED — +15 methods:
│                                 #   list/get/create/update/delete_behavior
│                                 #   list/get/create/update/delete_metric
│                                 #   list/get/create/update/delete_formula
├── types.py                      # MODIFIED — new param + result types:
│                                 #   MeasurementProperty, BehaviorStep,
│                                 #   Behavior, CreateBehaviorParams, UpdateBehaviorParams,
│                                 #   Metric, CreateMetricParams, UpdateMetricParams,
│                                 #   Formula, ReferencedMetric, CreateFormulaParams, UpdateFormulaParams,
│                                 #   MeasurementMath enum
├── __init__.py                   # MODIFIED — export the new public symbols, extend __all__
└── _internal/
    └── api_client.py             # MODIFIED — two project-scoped App API endpoints via app_request:
                                  #   /behaviors/ (behaviors) and /metrics/ (metrics AND formulas,
                                  #   discriminated by type); object-map list parse, no pagination;
                                  #   bulk DELETE for metrics/formulas (single-item metric DELETE → 501)

tests/
├── unit/
│   ├── test_types_metric.py            # NEW — CreateMetricParams/UpdateMetricParams/Metric, math enum, property object
│   ├── test_types_behavior.py          # NEW — CreateBehaviorParams/UpdateBehaviorParams/Behavior, step counts, funnel_order
│   ├── test_types_formula.py           # NEW — CreateFormulaParams/UpdateFormulaParams/Formula, variable mapping
│   ├── test_workspace_metrics.py       # NEW — Workspace metric CRUD (mocked client)
│   ├── test_workspace_behaviors.py     # NEW — Workspace behavior CRUD (mocked client)
│   ├── test_workspace_formulas.py      # NEW — Workspace formula CRUD (mocked client)
│   └── _internal/
│       └── test_api_client_semantic_layer.py  # NEW — endpoint paths, request shapes, response decode
├── pbt/
│   ├── test_metric_math_pbt.py         # NEW — math enum + property-presence invariants
│   ├── test_behavior_steps_pbt.py      # NEW — step-count invariants across simple/funnel/retention
│   └── test_formula_variables_pbt.py   # NEW — variable↔referencedMetrics 1:1 invariant
└── integration/
    └── test_semantic_layer_live.py     # NEW — @pytest.mark.live: round-trip CRUD against a fixture project
```

**Structure Decision**: Single-project Python library layout (Option 1) — the feature extends three existing surfaces (`workspace.py`, `types.py`, `_internal/api_client.py`) plus `__init__.py`, exactly mirroring how cohorts and custom properties are wired. No new internal subpackage is needed; the validators live on the Pydantic models in `types.py`.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

| Choice | Why Needed | Simpler Alternative Rejected Because |
|--------|------------|-------------------------------------|
| Three near-identical CRUD method families (behaviors / metrics / formulas) instead of one generic saved-entity CRUD | Each entity type has a distinct payload shape and distinct validators (a metric embeds a behavior + measurement; a formula embeds referenced metrics; a behavior is the base shape). A generic CRUD would push the type discrimination into stringly-typed kwargs and lose the per-type Pydantic validation that is the whole point of the feature. | One generic `create_saved_entity(type, payload)`: rejected — defeats mypy --strict typing and the construction-time validation guarantee (SC-002); callers would hand-build crashing payloads again. Mirroring the existing cohort surface (one explicit method family per entity) is the established repo pattern. |

## Story → gate mapping

| User story | Gate |
|------------|------|
| US1 (metrics) | math-enum + property-object + property-presence validators green; metric CRUD round-trips (mocked). |
| US2 (behaviors) | step-count + funnel_order + nameless-step validators green; behavior CRUD round-trips (mocked). |
| US3 (formulas) | variable↔referencedMetrics 1:1 + display-key validators green; formula CRUD round-trips (mocked). |
| All three | live smoke-test verifies the confirmed endpoint shapes (research.md R-1 CONFIRMED); >=90% cov; >=80% mutation on validators; `just check` green. |
