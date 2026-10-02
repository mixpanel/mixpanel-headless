# Implementation Plan: metric-maker skill

**Branch**: `048-metric-maker` (proposed) | **Date**: 2026-06-28 | **Spec**: [spec.md](spec.md)
**PR strategy**: Single PR — the metric-maker skill only. No library change. **This PR DEPENDS ON feature 047-behaviors-metrics-formulas being merged/released first**: the skill calls `ws.create_behavior` / `ws.create_metric` / `ws.create_formula`, which ship in 047. This PR cannot land (or be meaningfully exercised) until 047 is on the installed `Workspace`.

## Summary

Ship `mixpanel-plugin/skills/metric-maker/` — the "lego-block architect." It grounds in business context + `schema_graph`, designs a coherent starter kit of reusable, business-vocabulary-named blocks sized to the dataset + use case (custom events, analytical custom properties, cohorts, behaviors, metrics, formulas), writes a dry-run plan artifact (recommendations `.md` + runnable `.py`), pauses for one approval, validates + creates via the released `Workspace` CRUD, verifies by re-fetch, and hands the created IDs to dashboard-expert (assembly) and data-clean-up (annotation / tagging).

The skill introduces **no new library code**. Every write goes through the validated feature-047 param models, so the skill cannot construct a crashing payload. Its only bundled code is a `plan_kit.py` helper that emits the dry-run artifacts (and is itself unit-tested TDD-style).

Estimated scope: ~6 new skill files (SKILL.md + 4 references + 1 helper script), ~600 LoC, all under `mixpanel-plugin/skills/metric-maker/`.

## Dependency: feature 047 must land first

**This feature DEPENDS ON feature 047-behaviors-metrics-formulas.** The skill's core actions — `create_behavior`, `create_metric`, `create_formula` — and the param models that guard them (`CreateBehaviorParams`, `CreateMetricParams`, `CreateFormulaParams`, `MeasurementProperty`, `BehaviorStep`, `ReferencedMetric`) are delivered by 047. Concretely:

| What 048 calls | Shipped by |
|----------------|------------|
| `ws.create_behavior` / `ws.create_metric` / `ws.create_formula` (+ list/get/update/delete) | feature 047 |
| `Create*Params` validators that refuse crashing payloads | feature 047 |
| `ws.create_custom_event` / `ws.create_custom_property` / `ws.validate_custom_property` / `ws.create_cohort` | already on `Workspace` (pre-047) |
| `ws.schema_graph` / `ws.property_values` / `ws.get_business_context_chain` | already on `Workspace` (pre-047) |

Implementation of 048 MUST NOT begin until 047 is merged/released. The dependency is one-way: 047 has no dependency on 048. `tasks.md` records this as a hard prerequisite (T001).

## Technical Context

**Language/Version**: This is a Claude Code skill (Markdown SKILL.md + `references/` + one helper script). The helper script (`plan_kit.py`) is Python 3.10+ (mypy --strict compliant). No packaged library Python is added.

**Primary Dependencies**:
- Consumed (not added): the released `mixpanel_headless` public surface — feature-047 behaviors / metrics / formulas CRUD plus the existing custom-event / custom-property / cohort CRUD, `schema_graph`, `property_values`, `validate_custom_property`, `get_business_context_chain`.
- New: none. The `plan_kit.py` helper is pure stdlib. No new runtime dependencies.

**Storage**: None persisted to `~/.mp`. The skill writes dry-run artifacts (a recommendations `.md` + a runnable `.py`) to the working directory.

**Testing**: The bundled `plan_kit.py` helper is unit-tested TDD-style (pytest; mypy --strict on the script). The skill itself is verified via skill evals (trigger eval + behavior eval) per the plugin convention.

**Target Platform**: Cross-platform. No platform-specific code paths.

**Project Type**: Plugin skill addition. No library or CLI change; the skill is a consumer of the released `Workspace` surface.

**Performance Goals**:
- Grounding is a small bounded number of read calls (`get_business_context_chain`, one `schema_graph`, a handful of `property_values` samples).
- The dry-run artifact is written locally with zero Mixpanel writes; execution is one `create_*` round-trip per block.

**Constraints**:
- No write before the single approval gate (the write-safety model).
- No new library code (SC-006): the PR touches no file under `src/mixpanel_headless/`.
- The `plan_kit.py` helper passes mypy --strict, ruff, and has full docstrings.
- SKILL.md copy is AK voice (lowercase-leaning, direct, no em-dashes, no AI tells, no Claude trailers); the spec docs are normal technical prose.

**Scale/Scope**:
- ~6 new skill files (SKILL.md + 4 references + 1 helper script), ~600 LoC.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Library-First | PASS | The skill is a thin consumer of the public `Workspace` surface; it adds no library code. All the modeling primitives live in feature 047. |
| II. Agent-Native | PASS | The skill's only interaction is the single approval gate before a destructive bulk write, which is the documented write-safety model, not an arbitrary prompt. |
| III. Context Window Efficiency | PASS | The skill defers API teaching to `help.py` + hosted docs (no API re-teaching in SKILL.md). The dry-run artifact is the LLM-context-friendly projection; full schema dumps are not pasted into context. |
| IV. Two Data Paths | PASS | Live path: CRUD via the released App API bindings. Local path: the dry-run `.py` is an inspectable artifact; result reads expose `.df`. |
| V. Explicit Over Implicit | PASS | The skill never writes without approval. It surfaces the feature-047 `ValidationError`s rather than silently coercing a bad block. |
| VI. Unix Philosophy | PASS | The skill composes single-purpose `create_*` methods; the dry-run `.py` is a runnable, inspectable artifact, not a black box. |
| VII. Secure by Default | PASS WITH JUSTIFICATION | The skill mutates shared customer-visible Mixpanel state, so it gates every write behind one explicit approval and verifies by re-fetch. It refuses irreversible ops (merge / delete / drop-filter as kit steps). See [Complexity Tracking](#complexity-tracking) for the partial-failure no-rollback justification. |

**Gate Result**: PASS. Principle VII needs the no-rollback justification because, after approval, a mid-kit failure leaves already-created entities in place (they are independently useful and rolling them back would be a second destructive op). No actual violations.

## Project Structure

### Documentation (this feature)

```text
specs/048-metric-maker/
├── plan.md                       # This file
├── spec.md                       # Feature specification
├── research.md                   # Phase 0 output — skill design decisions + 047 dependency
└── quickstart.md                 # Skill walkthrough (US1–US3)
```

No `data-model.md` and no `contracts/`: this feature introduces no new types. It consumes feature 047's released surface plus the existing `create_custom_event` / `create_custom_property` / `create_cohort`.

### Source Code (repository root)

```text
mixpanel-plugin/skills/metric-maker/    # NEW SKILL (the only code this feature adds)
├── SKILL.md                            # trigger description + the lego-block workflow
├── references/
│   ├── lego-catalog.md                 # the block taxonomy + when to reach for each
│   ├── naming-taste.md                 # business-vocabulary naming rules
│   ├── formula-cookbook.md             # custom-property + formula patterns (Mixpanel formula language)
│   └── starter-kits-by-vertical.md     # ecommerce / SaaS / content / gaming kits
└── scripts/
    └── plan_kit.py                     # NEW per-skill helper — emits the dry-run recommendations .md + runnable .py

tests/
└── unit/
    └── test_metric_maker_plan_kit.py   # NEW — unit tests for the plan_kit.py helper (the only tested code)
```

**Structure Decision**: Plugin-skill layout — one new skill directory under the existing `mixpanel-plugin/skills/` root, following the `mixpanelyst` / `dashboard-expert` packaging convention (SKILL.md + `references/` + `scripts/`). The references and the helper are build outputs authored during implementation, not pre-existing files. No `src/mixpanel_headless/` change (SC-006).

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| Partial-failure mid-execute leaves already-created kit entities in place (no rollback) | After the single approval, the skill creates N independent entities. If entity K fails, entities 1..K-1 are already valid, independently useful Mixpanel objects. Rolling them back is itself a destructive op the user did not approve, and re-running the kit with the failures fixed is cheaper than re-creating everything. | Auto-rollback on any failure: rejected — turns one failure into N+1 destructive ops, can fail mid-rollback leaving a worse state, and discards entities the user would have kept. Reporting created-vs-failed and letting the user decide is the safer default. |

## Story → gate mapping

| User story | Gate |
|------------|------|
| US1 (ground + design) | grounding priority order encoded; `schema_graph(include_density=True)` is the mandatory first data move; every block business-named with definition + rationale; duplicate check before each block. |
| US2 (dry-run → approve → execute → verify) | `plan_kit.py` emits both artifacts and is unit-tested; no write before approval (counts unchanged); validate → create → re-fetch → report IDs; partial failure reported, no rollback. |
| US3 (handoff) | structured ID report; explicit handoff to dashboard-expert + data-clean-up; raw querying deferred to mixpanelyst. |
| All three | skill eval green; trigger eval green (fires on metric-creation phrasing, not on data-clean-up / dashboard-expert / mixpanelyst phrasing); SKILL.md follows house style; no `src/mixpanel_headless/` change. |
