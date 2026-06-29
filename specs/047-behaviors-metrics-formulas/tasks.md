---
description: "Task list for 047-behaviors-metrics-formulas — the typed library bindings (behaviors / metrics / formulas CRUD on Workspace)"
---

# Tasks: Behaviors, Metrics & Formulas CRUD

**Input**: Design documents from `/specs/047-behaviors-metrics-formulas/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: REQUIRED. The project CLAUDE.md mandates strict TDD ("write tests FIRST, before any implementation code"), 90% coverage minimum, and >=80% mutation score on the new pure validator code (the param-model validators in `types.py`). Every test task lands and FAILS before its implementation task.

**Organization**: Single PR — the typed library bindings. This is the FIRST PR in the metric-maker chain; the metric-maker skill (feature 048) consumes this surface and ships as a separate PR after this merges. Nothing here depends on 048.

| Block | User stories | Task range |
|-------|--------------|------------|
| Setup | — | T001–T002 |
| Foundational (endpoint confirmation + shared types) | US1/US2/US3 prereq | T003–T009 |
| Metrics | US1 | T010–T019 |
| Behaviors | US2 | T020–T028 |
| Formulas | US3 | T029–T037 |
| Library gate + final gate | — | T038–T044 |

**Story dependency note**:
- US1 (metrics), US2 (behaviors), US3 (formulas) all depend on Foundational (shared `MeasurementProperty`, `BehaviorStep`, `MeasurementMath`, and confirmed endpoint shapes). A metric embeds a behavior, so US1 reuses US2's `BehaviorStep`; a formula embeds metrics, so US3 reuses US1's measurement machinery — implement metrics+behaviors before formulas.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1 / US2 / US3 — omitted for Setup, Foundational, gates
- All file paths are project-relative

## Path Conventions

Single project (Library):
- Source: `src/mixpanel_headless/`
- Tests: `tests/unit/`, `tests/pbt/`, `tests/integration/`
- Specs: `specs/047-behaviors-metrics-formulas/`

---

## Phase 1: Setup (Shared Infrastructure)

- [ ] T001 Run `just install-hooks` from the repo root to ensure the pre-commit hook is installed (per CLAUDE.md "First-time setup"). No-op if already installed.
- [ ] T002 [P] Run `just check` against `main` to establish a clean baseline (lint + format + typecheck + tests + build) before any new work lands. Record the pass/coverage numbers.

**Checkpoint**: Dev environment ready, baseline clean.

---

## Phase 2: Foundational — endpoint confirmation + shared value types (Blocking)

**Purpose**: Close the NEEDS-CONFIRMATION risk (research.md R-1) and add the shared types every entity family depends on. **CRITICAL: T003 MUST complete before any client-plumbing task (T015, T025, T034) so those tasks code against confirmed shapes.**

- [ ] T003 Reverse-engineer + CONFIRM the App API endpoints. Inspect the power-tools macros that create/list behaviors, metrics, formulas in [mixpanel/mixpanel-power-tools](https://github.com/mixpanel/mixpanel-power-tools) (`templates/prompts/ai-behaviors-metrics-system.txt` for the body shapes, plus the create/list macros in that repo); then make ONE live call per entity type via `ws.api.app_request(...)` against the demo project (GET list, POST create minimal, DELETE cleanup). Record the confirmed paths, list-response envelope, and create-response shape in [contracts/payload-shapes.md §0](contracts/payload-shapes.md). Update [data-model.md §7](data-model.md) if the response envelope differs from the provisional model. This is the gate that unblocks all client plumbing.
- [ ] T004 [P] Add unit test file `tests/unit/test_types_measurement_property.py`: `MeasurementProperty` serializes `resource_type` → `resourceType`; a bare string is unrepresentable; `type`/`resource_type` Literals reject bad values. Run now — MUST fail.
- [ ] T005 [P] Add unit test file `tests/unit/test_types_behavior_step.py`: `BehaviorStep` rejects empty/whitespace `name`; serializes `filters_determiner` → `filtersDeterminer`, `funnel_order` → `funnelOrder`. Run now — MUST fail.
- [ ] T006 [P] Add PBT test file `tests/pbt/test_metric_math_pbt.py` skeleton asserting the `MeasurementMath` enum closure (any non-member string rejected; every member accepted). Run now — MUST fail (type not yet defined).
- [ ] T007 Add `MeasurementMath` Literal, `MeasurementProperty`, and `BehaviorStep` to `src/mixpanel_headless/types.py` per [data-model.md §2](data-model.md). Pydantic v2, full docstrings (markdown fences), `by_alias` serialization for the camelCase keys.
- [ ] T008 [P] Re-export `MeasurementMath`, `MeasurementProperty`, `BehaviorStep` from `src/mixpanel_headless/__init__.py`; add to `__all__`.
- [ ] T009 Run T004–T006 — they MUST now pass. Run `just typecheck` to confirm mypy --strict on the new shared types.

**Checkpoint**: Endpoint shapes confirmed, shared types live. The three entity families can begin.

---

## Phase 3: User Story 1 — Metrics (Priority: P1) 🎯 MVP

**Goal**: Full metric CRUD on `Workspace` with construction-time validators that refuse bad math, bare-string property, and property-presence mismatches.

**Independent Test**: per spec.md US1 — create/get/update/delete a metric round-trips; bad math and bare-string property raise `ValidationError` with zero HTTP.

### Tests for US1 (write FIRST, ensure they FAIL)

- [ ] T010 [P] [US1] Add `tests/unit/test_types_metric.py` per [data-model.md §4](data-model.md): `CreateMetricParams` validates the `math` enum; property-aggregation math requires `property`; plain count omits it; bare-string `property` raises; emitted `measurement` contains only the allowed keys ([contracts/payload-shapes.md §1](contracts/payload-shapes.md)); `UpdateMetricParams` all-optional; `Metric.model_validate` round-trip; `.to_dict()`/`.df`.
- [ ] T011 [P] [US1] Extend `tests/pbt/test_metric_math_pbt.py`: property-presence invariant — for every property-aggregation math, omitting property raises; for every plain count, supplying property raises (or normalizes per the chosen contract rule).
- [ ] T012 [P] [US1] Add `tests/unit/_internal/test_api_client_semantic_layer.py` (metrics section): with a mocked httpx response, `MixpanelAPIClient.create_metric(body)` POSTs to the confirmed metrics path with the body shape from [contracts/payload-shapes.md §5](contracts/payload-shapes.md); `list_metrics_app()` decodes the confirmed envelope; 400 → `QueryError`, 404 → `QueryError`, 5xx → `ServerError`.
- [ ] T013 [P] [US1] Add `tests/unit/test_workspace_metrics.py`: with a mocked client, the 5 `Workspace` metric methods call the right client method with `params.model_dump(exclude_none=True, by_alias=True)` and decode via `Metric.model_validate`; `delete_metric` returns None.
- [ ] T014 [US1] Run T010–T013 — all MUST fail (no implementation yet).

### Implementation for US1

- [ ] T015 [US1] Add the metrics client methods to `src/mixpanel_headless/_internal/api_client.py` (`list_metrics_app`, `get_metric`, `create_metric`, `update_metric`, `delete_metric`) via `maybe_scoped_path` + `app_request` + the pagination helper, mirroring `list_cohorts_app`/`create_cohort`. Use the confirmed paths from T003.
- [ ] T016 [US1] Add `Metric`, `CreateMetricParams`, `UpdateMetricParams` to `src/mixpanel_headless/types.py` per [data-model.md §4](data-model.md) with the math-enum, property-object, and property-presence validators. Full docstrings.
- [ ] T017 [US1] Add `list_metrics`, `get_metric`, `create_metric`, `update_metric`, `delete_metric` to `src/mixpanel_headless/workspace.py` mirroring the cohort methods ([contracts/python-api.md §1](contracts/python-api.md)). Full Args/Returns/Raises/Example docstrings.
- [ ] T018 [US1] Re-export `Metric`, `CreateMetricParams`, `UpdateMetricParams` from `__init__.py`; add to `__all__`.
- [ ] T019 [US1] Run T010–T013 — all pass. Run `just typecheck`.

**Checkpoint**: Metric CRUD works end-to-end (mocked). MVP slice complete.

---

## Phase 4: User Story 2 — Behaviors (Priority: P1)

**Goal**: Full behavior CRUD with step-count + funnel_order validators.

**Independent Test**: per spec.md US2 — simple/funnel/retention round-trip; funnel<2, retention!=2, nameless step, funnel_order="strict" all raise `ValidationError`.

### Tests for US2 (write FIRST, ensure they FAIL)

- [ ] T020 [P] [US2] Add `tests/unit/test_types_behavior.py` per [data-model.md §3](data-model.md): step-count rules (simple>=1, funnel>=2, retention==2); nameless step rejected; `funnel_order` ∈ {loose, any}; emitted `definition.behavior.behaviors` non-empty and shaped per [contracts/payload-shapes.md §2–§4](contracts/payload-shapes.md); `UpdateBehaviorParams` all-optional; `Behavior` round-trip.
- [ ] T021 [P] [US2] Add `tests/pbt/test_behavior_steps_pbt.py`: for randomly generated step lists, funnel validates iff len>=2, retention iff len==2, simple iff len>=1.
- [ ] T022 [P] [US2] Extend `tests/unit/_internal/test_api_client_semantic_layer.py` (behaviors section): create/list/get/update/delete hit the confirmed behavior paths; error mapping per [contracts/error-messages.md §8](contracts/error-messages.md).
- [ ] T023 [P] [US2] Add `tests/unit/test_workspace_behaviors.py`: the 5 `Workspace` behavior methods delegate correctly (mocked client).
- [ ] T024 [US2] Run T020–T023 — all MUST fail.

### Implementation for US2

- [ ] T025 [US2] Add the behaviors client methods to `api_client.py` (confirmed paths from T003).
- [ ] T026 [US2] Add `Behavior`, `CreateBehaviorParams`, `UpdateBehaviorParams` to `types.py` with the step-count + funnel_order + nameless-step validators per [data-model.md §3](data-model.md) and [contracts/error-messages.md §4–§5](contracts/error-messages.md).
- [ ] T027 [US2] Add the 5 behavior methods to `workspace.py`; re-export the 3 types from `__init__.py` and add to `__all__`.
- [ ] T028 [US2] Run T020–T023 — all pass. `just typecheck`.

**Checkpoint**: Behavior CRUD works end-to-end (mocked).

---

## Phase 5: User Story 3 — Formulas (Priority: P2)

**Goal**: Full formula CRUD with variable↔referencedMetrics 1:1 validation. Depends on US1 (referenced metrics reuse the measurement machinery).

**Independent Test**: per spec.md US3 — 2-variable formula round-trips; variable/metric-count mismatch and non-contiguous variables raise `ValidationError`.

### Tests for US3 (write FIRST, ensure they FAIL)

- [ ] T029 [P] [US3] Add `tests/unit/test_types_formula.py` per [data-model.md §5](data-model.md): variable extraction from `definition`; contiguity-from-A; count == len(referenced_metrics); `ReferencedMetric.display` rejects disallowed keys (e.g. `label`) per [contracts/error-messages.md §7](contracts/error-messages.md); emitted `referencedMetrics` order matches A,B,...; `Formula` round-trip.
- [ ] T030 [P] [US3] Add `tests/pbt/test_formula_variables_pbt.py`: for a definition referencing variable set S and n referenced metrics, params validate iff S == {A..A+n-1}.
- [ ] T031 [P] [US3] Extend `tests/unit/_internal/test_api_client_semantic_layer.py` (formulas section): create/list/get/update/delete hit the confirmed formula paths; body matches [contracts/payload-shapes.md §6](contracts/payload-shapes.md).
- [ ] T032 [P] [US3] Add `tests/unit/test_workspace_formulas.py`: the 5 `Workspace` formula methods delegate correctly (mocked client).
- [ ] T033 [US3] Run T029–T032 — all MUST fail.

### Implementation for US3

- [ ] T034 [US3] Add the formulas client methods to `api_client.py` (confirmed paths from T003).
- [ ] T035 [US3] Add `Formula`, `ReferencedMetric`, `CreateFormulaParams`, `UpdateFormulaParams` to `types.py` with the variable-mapping + display-key validators per [data-model.md §5](data-model.md) and [research.md R-5](research.md).
- [ ] T036 [US3] Add the 5 formula methods to `workspace.py`; re-export `Formula`, `ReferencedMetric`, `CreateFormulaParams`, `UpdateFormulaParams` from `__init__.py` and add to `__all__`.
- [ ] T037 [US3] Run T029–T032 — all pass. `just typecheck`.

**Checkpoint**: Formula CRUD works end-to-end (mocked).

---

## Phase 6: Library gate + final gate

- [ ] T038 Add the live integration test `tests/integration/test_semantic_layer_live.py` marked `@pytest.mark.live`: round-trip create/get/update/delete for a metric, a behavior, and a formula against the fixture project; confirms the endpoint shapes match T003. Deselected by default; runs with `MP_LIVE_TESTS=1`.
- [ ] T039 Run `just test-cov` — coverage gate (90%) met on the new types + workspace methods + client plumbing.
- [ ] T040 Run `just mutate` against the new validator code in `src/mixpanel_headless/types.py` (the metric/behavior/formula param models); mutation score MUST be >=80%. Strengthen tests if surviving mutants reveal gaps.
- [ ] T041 [P] Update `CHANGELOG.md` with an `Unreleased — behaviors / metrics / formulas (047)` heading documenting the 15 new `Workspace` methods, the new types/enums, and the validator guarantees.
- [ ] T042 [P] Confirm `help.py` auto-discovers the new methods/types (`python help.py Workspace.create_metric`, `python help.py CreateFormulaParams`, `python help.py search behavior`) — no manual help.py edits needed (SC-005).
- [ ] T043 Update `CLAUDE.md` "Active Technologies" with the 047 row and point the SPECKIT marker at this plan; update `src/mixpanel_headless/CLAUDE.md` Workspace-methods list with a "Semantic Layer — Behaviors/Metrics/Formulas" group.
- [ ] T044 Run `just check` end-to-end one final time (the `just check` equivalent of CI). MUST be green: lint + format + typecheck + tests + >=90% coverage + build. This is the merge gate for the PR. **The endpoint shapes MUST be recorded in contracts/payload-shapes.md §0 before this gate passes.**

**Checkpoint**: PR ready to merge. The library bindings are shippable on their own and unblock the metric-maker skill (feature 048).

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup**: no dependencies — start immediately.
- **Foundational**: depends on Setup. T003 (endpoint confirmation) BLOCKS all client plumbing.
- **US1 metrics / US2 behaviors**: depend on Foundational. Co-equal P1.
- **US3 formulas**: depends on US1 (referenced metrics reuse the measurement machinery).
- **Library gate + final gate**: depend on US1+US2+US3.

### Within each user story

- Tests written and FAILING before implementation.
- Shared types (Foundational) before per-family types.
- Client plumbing before workspace methods (workspace methods call the client).
- `__init__` exports after the types exist.
- `just check` green at each phase gate.

### Parallel opportunities

- Setup T002 is [P].
- Foundational test tasks T004–T006 are [P]; T007 is sequential (single `types.py` edit).
- Within each family the test tasks (e.g. T010–T013) are [P]; the implementation tasks touch shared files (`types.py`, `workspace.py`, `api_client.py`) and are mostly sequential to avoid same-file conflicts.
- US1 and US2 can be worked in parallel by two developers AFTER Foundational, but both edit `types.py`/`workspace.py`/`api_client.py` — coordinate the merges (append-only sections minimize conflict).
- Gate tasks T041 and T042 are [P] (different files).

---

## Implementation strategy

### MVP first (metrics only)

1. Setup + Foundational (incl. T003 endpoint confirmation).
2. US1 metrics (T010–T019).
3. **STOP and validate**: round-trip a metric live, confirm validators refuse bad payloads.

This MVP gives a Python user programmatic metric CRUD with crash-proof validation.

### Incremental delivery

- US1 metrics → US2 behaviors → US3 formulas → library gate → ship the bindings.
- The metric-maker skill (feature 048) builds on top of this in a separate PR.

### Parallel team strategy

- Developer A does Foundational + metrics; Developer B does behaviors once Foundational lands; either does formulas after metrics.

---

## Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps task to user story for traceability.
- The construction-time validation guarantee (SC-002) is non-negotiable: every "refuse a crashing payload" behavior has a unit test that asserts NO HTTP round-trip occurs.
- Mutation gate (80%) applies to the new validator code in `types.py`; workspace methods and client plumbing are coverage-gated (90%) but not mutation-gated.
- The endpoint-confirmation task (T003) is the single biggest risk; do it first and record the result before writing client plumbing.
- This feature has NO dependency on feature 048 (the metric-maker skill); the dependency runs the other way.
- Avoid: same-file parallel edits to `types.py`/`workspace.py`/`api_client.py`; writing client plumbing before T003 confirms the shapes.
