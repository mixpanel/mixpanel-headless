# Feature Specification: metric-maker skill for `mixpanel-headless`

**Feature Branch**: `048-metric-maker`
**Created**: 2026-06-28
**Status**: Draft
**Input**: User description: "ship the lego-block architect skill that designs reusable named building blocks for end users on top of the released behaviors / metrics / formulas surface"

## Overview

metric-maker is a Claude Code skill — the "lego-block architect." Given business context, the project schema, and a use case, it designs a coherent **starter kit** of reusable, business-vocabulary-named building blocks (custom events, ANALYTICAL custom properties = bucketing / derived dimensions, cohorts, behaviors, metrics, formulas), writes a dry-run plan artifact, pauses for one approval, then validates and creates the entities and reports their IDs so downstream skills (dashboard-expert, data-clean-up) can consume them.

The thesis: **most Mixpanel end users should never touch raw events.** Give them preconfigured, named, reusable blocks. Mixpanel is for humans, not data engineers.

The skill operates on a **compression / layer pyramid**: a raw project is hundreds of events and properties, but a PM needs a handful of named concepts. The layers, each compressing the one below into business language, are: raw events (hundreds) → clean, governed events (the visible surface) → behaviors (dozens) → metrics / formulas (a handful). metric-maker builds the upper layers — behaviors, metrics, formulas, plus the analytical custom properties and cohorts they reference — so end users see "Power Buyers" / "Activated User" / "Weekly Active" rather than raw SDK noise. The same named structure is what makes downstream prompt-to-insight reliable for any AI consuming the project, so the layer is grounding context as much as a human convenience.

This feature introduces **no new library code**. It consumes the released `Workspace` surface — the behaviors / metrics / formulas CRUD shipped in **feature 047-behaviors-metrics-formulas** — plus the already-existing custom-property semantics from **feature 037-custom-properties-queries** and the cohort-definition / cohort-behavior primitives from **features 035-cohort-definition-builder and 036-cohort-behaviors**, surfaced through `create_custom_event`, `create_custom_property`, `validate_custom_property`, `create_cohort`, `schema_graph`, `property_values`, and `get_business_context_chain` (`create_custom_event` / `create_custom_property` / `validate_custom_property` ship in **feature 027-data-governance-crud**; `create_cohort` in **feature 024-core-entity-crud**). Its only bundled code is a `plan_kit.py` helper that emits the dry-run artifacts.

The skill is packaged at `mixpanel-plugin/skills/metric-maker/` (SKILL.md + `references/`). It STOPS at the dashboard boundary: it hands the created IDs to dashboard-expert (for assembly) and to data-clean-up (for annotation / tagging).

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Ground in the project and design a coherent starter kit (Priority: P1)

A product manager onboarding a new Mixpanel project says "set up metrics for my e-commerce app so my team can build dashboards without touching raw events." The metric-maker skill grounds itself (business context + `schema_graph`), then designs a coherent starter kit sized to the dataset and use case — named in business vocabulary ("Power Buyers," "Activated User," "Average Order Value"), each block with a one-sentence definition and a one-line rationale tying it to the use case, every block referencing only properties that actually exist on the referenced events. The default spine is the set of metric archetypes nearly every product shares — acquisition, activation, engagement (DAU/WAU/MAU plus stickiness = DAU/MAU), retention (Nth-action / cohort), and revenue / value (per-user, AOV) — recognized from the universal dataset classes the schema almost always carries (identity, attribution, platform/device, geo, time, value/revenue); the skill then specializes per vertical (ecommerce / SaaS / content / gaming).

**Why this priority**: This is the design core of the skill and the reason it exists. Without grounded, well-named, schema-valid block design there is nothing to approve or create. Independently testable: even with no auto-execute, the design output (a vetted modeling plan) is the deliverable.

**Independent Test**: Given a project with a clear e-commerce schema and no existing semantic-layer entities, invoking the skill produces a proposed kit where every block has a business-vocabulary name (never "Cohort 1" / "My Custom Prop"), a one-sentence definition, and a one-line rationale; every proposed block references only properties present on its events (verified against `schema_graph`); and no proposed block duplicates an existing entity of the same type.

**Acceptance Scenarios**:

1. **Given** a project with business context stored in Mixpanel, **When** the skill grounds, **Then** it reads `ws.get_business_context_chain()` first; if that returns nothing it falls back to a user-supplied `.md` / pasted text; if neither exists it ASKS in conversation rather than guessing the domain.
2. **Given** a grounded project, **When** the skill designs the kit, **Then** its mandatory first data move is `ws.schema_graph(include_density=True)` and it grounds every proposed block in properties that actually exist on the referenced events (using `.properties_for_event`, `.events_for_property`, `density_local`), sampling concrete values via `ws.property_values(...)`.
3. **Given** a grounded project, **When** the skill designs a kit, **Then** every proposed entity has a business-vocabulary name (never "Cohort 1" / "My Custom Prop"), a one-sentence definition, and a one-line rationale tying it to the use case.
4. **Given** the project already has a cohort named "Power Users," **When** the skill designs a kit, **Then** it detects the existing entity (via the relevant `list_*` method) and does not propose a duplicate — it reuses or renames.
5. **Given** a use case and a dataset, **When** the skill sizes the kit, **Then** the kit size follows the dataset and use case (NOT a fixed count) and spans the full modeling layer where appropriate: custom events, analytical custom properties, cohorts, behaviors, metrics, formulas.
6. **Given** a grounded project, **When** the skill chooses what to build, **Then** it starts from the universal metric archetypes (acquisition, activation, engagement + stickiness, retention, revenue / value) as the default spine, then specializes by the vertical it inferred from the schema; archetypes the dataset cannot support (no revenue events → no revenue metric) are omitted rather than faked.

---

### User Story 2 — Dry-run, approve, execute, verify (Priority: P1)

After the kit is designed, the skill writes a reviewable plan artifact (a recommendations `.md` AND a runnable `.py`), shows a summary, and PAUSES for one approval before creating anything in Mixpanel. The user may refine the plan in conversation before approving. On approval the skill validates each entity where a validator exists, creates them, re-fetches to verify, and reports the created IDs grouped by type.

**Why this priority**: This is the write-safety contract. metric-maker mutates shared customer-visible Mixpanel state, so a single explicit approval gate before any write is non-negotiable. Independently testable: the no-write-before-approval guarantee is verifiable by diffing `list_*` counts.

**Independent Test**: Given a designed kit, the skill writes `metric_maker_plan.md` + `metric_maker_plan.py`, shows a chat summary that explicitly pauses for approval, and `list_metrics()`/`list_behaviors()`/`list_formulas()` counts are UNCHANGED before approval. After approval the kit is created, re-fetched/verified, and IDs are reported grouped by type; a deliberately-injected mid-kit failure is reported as created-vs-failed with no rollback.

**Acceptance Scenarios**:

1. **Given** a designed kit, **When** the skill reports to the user, **Then** it writes a recommendations `.md` (each block with name + definition + rationale) AND a runnable `.py`, shows a summary, and explicitly asks for one approval before any write; no `create_*` call has run.
2. **Given** the user refines the plan in conversation ("drop the gaming cohort, add a refund metric"), **When** they then approve, **Then** the executed kit reflects the refinements.
3. **Given** approval is granted, **When** the skill executes, **Then** it validates each entity (e.g. `validate_custom_property`) before creating, creates the entities, re-fetches to verify, and reports the created IDs grouped by type.
4. **Given** entity N of a kit fails to create after approval, **When** the skill handles the failure, **Then** it reports which entities were created (with IDs) and which failed, and does NOT roll back already-created entities (they are independently useful).
5. **Given** the user asks for an irreversible governance op (merge / delete / drop-filter), **When** the skill considers it, **Then** it refuses and defers (those belong to data-clean-up); it never performs them as a kit step.

---

### User Story 3 — Hand off created entity IDs to downstream skills (Priority: P2)

After the starter kit is created, the user says "now build me a dashboard from these." metric-maker stops at the dashboard boundary: it reports the created entity IDs in a structured handoff so dashboard-expert can assemble a dashboard and data-clean-up can annotate / tag the new entities.

**Why this priority**: The cross-skill contract is what makes the kit useful, but it is additive on top of US2 (a kit with no handoff is still a created kit). Independently testable via the structured ID report.

**Independent Test**: After execution, the skill emits a structured handoff block (entity type → name → ID) and explicitly names dashboard-expert (for assembly) and data-clean-up (for annotation / tagging) as the next steps. The handoff is machine-readable enough that a subsequent dashboard-expert invocation can consume the metric IDs directly.

**Acceptance Scenarios**:

1. **Given** a created kit, **When** the skill finishes, **Then** it prints a handoff listing each created entity's type, business name, and server ID.
2. **Given** the handoff, **When** the user asks to build a dashboard, **Then** the skill defers to dashboard-expert and supplies the metric / formula IDs rather than building the dashboard itself.
3. **Given** the handoff, **When** the user asks to hide / tag / annotate the new entities, **Then** the skill defers to data-clean-up rather than doing lexicon governance itself.
4. **Given** any request to do raw ad-hoc querying, **When** the skill considers it, **Then** it defers to mixpanelyst — metric-maker composes saved building blocks, it does not run one-off queries.

---

### Edge Cases

- **Library prerequisite missing**: if the behaviors / metrics / formulas CRUD from feature 047 is not present on the installed `mixpanel-headless` (`create_metric` / `create_behavior` / `create_formula` absent), the skill MUST detect this and tell the user to upgrade rather than failing mid-execute. The skill cannot function without 047.
- **Skill grounding unavailable**: if `get_business_context_chain()` returns nothing and the user supplies no `.md` and no pasted text, the skill ASKS in conversation rather than guessing the domain.
- **Skill duplicate detection**: before proposing a block the skill lists existing entities of that type; an exact-or-near name match means reuse / rename, never a silent duplicate.
- **Irreversible downstream ops**: metric-maker never merges / deletes / drops-filter; those belong to data-clean-up. If the user asks for them, the skill defers.
- **Partial-failure mid-execute**: if entity N of a kit fails to create after approval, the skill reports which entities were created (with IDs) and which failed, and does NOT roll back already-created entities (they are independently useful).
- **Analytical vs cleanup custom properties**: the split is stated identically on both sides. metric-maker owns ANALYTICAL custom properties (bucketing continuous values, deriving dimensions); data-clean-up (045) owns CLEANUP / regex custom properties (parsing or normalizing messy string values for hygiene). A messy-string-cleanup request defers to data-clean-up; an analytical bucket/dimension request from data-clean-up defers here.
- **Validator failure surfaced from 047**: a block the user insists on that the 047 param models reject (bad math, bare-string property, wrong step count, non-contiguous formula variables) surfaces the `ValidationError` from the released library; the skill explains the constraint and proposes a corrected block rather than hand-building a crashing payload.

## Requirements *(mandatory)*

### Functional Requirements

#### Grounding and design

- **FR-001**: The skill MUST ground itself in this priority order before designing: (1) `ws.get_business_context_chain()` (org + project markdown stored in Mixpanel), (2) a user-supplied `.md` file or pasted text, (3) ask in conversation. It MUST NOT guess the domain when no grounding exists.
- **FR-002**: The skill's mandatory first data move MUST be `ws.schema_graph(include_density=True)`, using `.properties_for_event(e)`, `.events_for_property(p)`, `.orphan_properties()`, and `density_local` to ground every proposed block in properties that actually exist on the referenced events; concrete values MUST be sampled via `ws.property_values(prop, event=...)`.
- **FR-003**: The skill MUST design a COHERENT STARTER KIT sized to the dataset and use case (NOT a fixed count). The kit scope is the full modeling layer: custom events, analytical custom properties (bucketing / dimension-deriving, NOT messy-string cleanup), cohorts, behaviors, metrics, formulas. The kit MUST follow the compression pyramid — clean events → behaviors → metrics / formulas — so each block compresses the layer below into business language rather than exposing raw events.
- **FR-004**: The skill MUST default the kit to the universal metric archetypes — acquisition, activation, engagement (DAU/WAU/MAU + stickiness), retention, revenue / value — recognizing the recurring universal dataset classes (identity, attribution, platform/device, geo, time, value/revenue) by shape so the spine generalizes across datasets, then MUST specialize per vertical (ecommerce / SaaS / content / gaming). It MUST omit an archetype the dataset cannot support rather than fabricate it.
- **FR-005**: Every proposed block MUST have a business-vocabulary name (e.g. "Power Buyers," "Activated User," "Weekly Active Account"), a one-sentence definition, and a one-line rationale. Implementation-jargon names ("Cohort 1," "My Custom Prop") MUST NOT be used. Every block MUST be a saved, named, reusable entity (the publisher stance), never an anonymous inline one-off.
- **FR-006**: Before proposing a block the skill MUST check for existing entities of that type (via the relevant `list_*` method) and avoid duplicates (reuse or rename on a name match).
- **FR-007**: The skill MUST favor simplicity: simplify aggressively over precise-but-mysterious; prefer a small coherent kit a human can hold in their head over an exhaustive one. It MUST rank by impact and act on the high-traffic / high-query head first rather than attempting the whole long tail in one pass.

#### Write-safety and execution

- **FR-008**: The skill MUST follow the write-safety model: produce a dry-run plan as a reviewable artifact (a recommendations `.md` AND a runnable `.py`), show a summary, and PAUSE for ONE approval before any Mixpanel write. Conversation MAY refine the plan before approval.
- **FR-009**: On approval, the skill MUST validate each entity where a validator exists (e.g. `validate_custom_property`) before creating, then create the entities autonomously via the released `Workspace` CRUD, then verify by re-fetching, then report the created IDs grouped by type.
- **FR-010**: On partial failure mid-execute, the skill MUST report which entities were created (with IDs) and which failed, and MUST NOT roll back already-created entities.
- **FR-011**: The skill MUST NOT perform irreversible governance ops (merge, delete, drop-filter) and MUST NOT do lexicon hide / annotate / tag (those belong to data-clean-up); if asked, it defers.
- **FR-012**: The skill MUST surface, not bypass, the construction-time `ValidationError`s raised by the feature-047 param models; on a rejected block it explains the constraint and proposes a corrected block rather than hand-building a crashing payload.

#### Handoff and scope

- **FR-013**: The skill MUST emit a structured handoff (entity type → business name → server ID) and explicitly name dashboard-expert (dashboard assembly) and data-clean-up (annotation / tagging) as next steps. It MUST stop at the dashboard boundary and not build dashboards itself.
- **FR-014**: The skill MUST NOT do raw ad-hoc querying (that is mixpanelyst's job); it composes saved building blocks.

#### Packaging

- **FR-015**: The skill MUST be packaged at `mixpanel-plugin/skills/metric-maker/` with a `SKILL.md` plus a `references/` directory containing `lego-catalog.md`, `naming-taste.md`, `formula-cookbook.md`, and `starter-kits-by-vertical.md`, plus a `scripts/plan_kit.py` helper. (These references and the helper are BUILD OUTPUTS of this feature, authored during implementation — not pre-existing repo files.)
- **FR-016**: The SKILL.md MUST follow the existing house style (terse, table-driven, progressive disclosure into `references/`), MUST NOT re-teach the whole `mixpanel_headless` API (defer to the hosted docs `https://mixpanel.github.io/mixpanel-headless/llms.txt` and to `help.py` as the canonical API-discovery tool), MUST NOT triplicate `help.py`, and MUST reference bundled scripts via `${CLAUDE_SKILL_DIR}`.
- **FR-017**: The SKILL.md `description` frontmatter MUST auto-fire on: creating metrics / behaviors / formulas / custom events / custom properties / cohorts, reusable building blocks, the semantic / metrics layer, KPI definitions, "set up metrics," and making analysis easier for end users; AND it MUST carry the reciprocal negative-routing clauses (does NOT clean up / govern the data dictionary = data-clean-up; does NOT build dashboards = dashboard-expert; defers raw querying to mixpanelyst). The exact string is fixed in §"Proposed SKILL.md description trigger text" below.

### Key Entities

- **StarterKit (conceptual)**: a coherent set of reusable blocks (custom events, analytical custom properties, cohorts, behaviors, metrics, formulas) sized to the dataset + use case, each named in business vocabulary with a definition and rationale. Exists as the dry-run artifact, not a library type.
- **Block (conceptual)**: one proposed entity in the kit — a type (custom event / analytical custom property / cohort / behavior / metric / formula), a business-vocabulary name, a one-sentence definition, a one-line rationale, and the `Workspace` `create_*` call that would build it.
- **Dry-run artifact**: the pair `metric_maker_plan.md` (recommendations, human-readable) + `metric_maker_plan.py` (runnable script that would create the kit). Written by the `plan_kit.py` helper; the gate the single approval acts on.
- **Handoff**: a structured post-execution report (entity type → business name → server ID) naming dashboard-expert and data-clean-up as next steps.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: On a clean e-commerce project, the skill auto-fires on the documented trigger phrases and produces a dry-run plan (recommendations `.md` + runnable `.py`) with business-vocabulary names and per-block rationale, and creates ZERO Mixpanel entities before the user approves. Verified by a skill eval.
- **SC-002**: For a grounded project, every block the skill proposes references only properties that actually exist on the referenced events (verified against `schema_graph`), and no proposed block duplicates an existing entity of the same type.
- **SC-003**: After approval, the skill creates the kit, verifies by re-fetch, and reports created IDs grouped by type with an explicit handoff to dashboard-expert and data-clean-up; on partial failure it reports created vs failed without rolling back. Verified by a skill eval.
- **SC-004**: The SKILL.md `description` auto-fires on the documented metric-creation / building-block / "set up metrics" phrases and does NOT fire on raw-query phrasing (mixpanelyst), governance / "clean up" / "organize the data dictionary" / "hide noise" / "flag PII" phrasing (data-clean-up), or dashboard-building phrasing (dashboard-expert). Verified by a trigger eval (the reciprocal of data-clean-up's trigger eval in feature 045).
- **SC-005**: The bundled `plan_kit.py` helper, given a kit spec, emits a recommendations markdown (one section per block with name + definition + rationale) AND a runnable `.py` that is syntactically valid (`compile()`) and imports `mixpanel_headless`, and the helper itself invokes NO `create_*` call (it only writes files). Verified by a unit test.
- **SC-006**: The skill introduces NO new library code — it consumes only the released feature-047 surface plus the existing custom-event / custom-property CRUD (feature 027), cohort CRUD (feature 024), `schema_graph`, `property_values`, business-context, and `validate_custom_property`. Verified by the absence of any `src/mixpanel_headless/` change in the PR.
- **SC-007**: A new contributor can read the spec and the `references/` and add a new starter-kit vertical (e.g. fintech) without touching library code or reverse-engineering payload shapes (the validators live in feature 047).

## Assumptions

- **DEPENDS ON feature 047-behaviors-metrics-formulas being merged/released first.** The skill calls `ws.create_behavior`, `ws.create_metric`, and `ws.create_formula` — those methods (and the `Create*Params` param models that guard them) ship in feature 047. This feature (048) CANNOT begin implementation until 047 is merged and the behaviors / metrics / formulas CRUD is on the installed `Workspace`. The dependency is one-way: 047 has no dependency on 048.
- The skill consumes only the public `Workspace` surface: the feature-047 behavior / metric / formula CRUD plus the already-existing `create_custom_event`, `create_custom_property`, `validate_custom_property`, `create_cohort`, `schema_graph`, `property_values`, and `get_business_context_chain`. The underlying surface ships across prior specs: `create_custom_event` / `create_custom_property` / `validate_custom_property` in **feature 027-data-governance-crud** (custom-property query semantics in **feature 037-custom-properties-queries**); `create_cohort` and the entity-CRUD surface in **feature 024-core-entity-crud** (cohort definition / behavior primitives in **features 035-cohort-definition-builder and 036-cohort-behaviors**). It adds no new library code.
- All payload-shape validation lives in the feature-047 param models; the skill cannot construct a crashing payload because every write goes through those validated bindings.
- The plugin packaging convention (SKILL.md + `references/` + `scripts/`, `${CLAUDE_SKILL_DIR}` for bundled paths, defer API teaching to `help.py` + hosted docs) is the same one `mixpanelyst` and `dashboard-expert` follow. This is a skill, not a library spec: the only code under the library gate model (TDD, mypy --strict, coverage) is the bundled `plan_kit.py` script; the markdown assets (SKILL.md + `references/`) are reviewed for taste and verified via skill evals.
- The analytical-vs-cleanup custom-property split is stated identically here and in **feature 045-data-clean-up**: metric-maker (048) owns ANALYTICAL custom properties (bucketing continuous values, deriving dimensions); data-clean-up (045) owns CLEANUP / regex custom properties (parsing or normalizing messy string values for hygiene). The two skills defer to each other across this boundary.
- Out of scope: any library change (that is feature 047), dashboards (dashboard-expert), lexicon hide / annotate / tag (data-clean-up = 045), raw ad-hoc querying (mixpanelyst), messy-string-cleanup custom properties (data-clean-up = 045), and any irreversible governance op (merge / delete / drop-filter as a kit step).

## Proposed SKILL.md description trigger text

```yaml
name: metric-maker
description: >-
  designs reusable, business-vocabulary-named mixpanel building blocks so end
  users never touch raw events. mixpanel is for humans, not data engineers: it
  compresses raw events into clean events, behaviors, and metrics / formulas a
  pm can hold in their head. use when the user asks to create metrics,
  behaviors, formulas, custom events, analytical custom properties, or cohorts;
  to set up a semantic / metrics layer or kpi definitions; to define reusable
  building blocks; or to "set up metrics" / make analysis easier for their team.
  grounds in business context + schema, proposes a coherent starter kit built on
  the universal archetypes (acquisition, activation, engagement, retention,
  revenue) then specialized per vertical, pauses for approval, then creates the
  entities and hands their ids to dashboard-expert and data-clean-up. stops at
  the dashboard; defers raw querying to mixpanelyst. does NOT clean up / organize
  / govern the data dictionary, write display names or descriptions, hide noise,
  tag, or flag pii (that is data-clean-up), and does NOT build dashboards (that
  is dashboard-expert).
allowed-tools: Bash Read Write WebFetch
```
