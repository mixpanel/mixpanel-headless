# Phase 0 Research: metric-maker skill

**Feature**: 048-metric-maker
**Date**: 2026-06-28
**Status**: All decisions settled. The one hard external dependency (feature 047) is recorded in R-1.

This document records the skill design decisions, their rationale, and the rejected alternatives. The skill packaging follows the `mixpanelyst` / `dashboard-expert` convention; the modeling primitives it calls are delivered by feature 047.

---

## R-1. Hard dependency on feature 047-behaviors-metrics-formulas

**Decision**: metric-maker is built ON TOP OF the released behaviors / metrics / formulas CRUD from feature 047. Implementation of this feature MUST NOT begin until 047 is merged/released and `create_behavior` / `create_metric` / `create_formula` (plus their `Create*Params` validators) are on the installed `Workspace`.

**Why this is a hard dependency**: The skill's core actions are exactly those three `create_*` calls. Without 047 there is nothing for the skill to orchestrate. The skill also relies on 047's param-model validators as its safety net — every write goes through them, so the skill cannot construct a payload that 400s or crashes the webapp. If the skill shipped first, it would have to either hand-build raw payloads (re-introducing the exact bug 047 exists to prevent) or simply not work.

**Direction**: One-way. 047 is independently useful (any Python script can use the bindings) and has NO dependency on 048. The chain is 047 → 048.

**Runtime guard**: The skill MUST detect a missing prerequisite (e.g. `create_metric` absent from the installed `Workspace`) and tell the user to upgrade `mixpanel-headless`, rather than failing mid-execute (spec.md Edge Cases).

**Alternatives considered**:
- **Bundle the bindings into this skill PR**: rejected — couples an independently-useful library change to a skill on a different cadence; the library is the load-bearing primitive and lands first on its own merits (this is why the combined feature was split into 047 + 048).
- **Embed payload-shape knowledge in the skill**: rejected — duplicates the 047 validators and drifts; the skill should call the validated bindings.

---

## R-2. The skill consumes only the public surface (no new library code)

**Decision**: metric-maker uses only public `Workspace` methods: the feature-047 behavior / metric / formula CRUD, plus the already-existing `create_custom_event`, `create_custom_property`, `validate_custom_property`, `create_cohort`, `schema_graph`, `property_values`, `get_business_context_chain`. Its only bundled code is a `plan_kit.py` helper that emits the dry-run artifacts.

**Rationale**: Keeps the skill a thin orchestration layer; all the validation lives in feature 047's param models, so the skill cannot construct a crashing payload either. Defers API teaching to `help.py` + hosted docs per the plugin convention. SC-006 verifies the PR touches no `src/mixpanel_headless/` file.

**Alternatives considered**:
- **Add skill-specific helper methods to `Workspace`**: rejected — any reusable library capability belongs in the library (and would be a 047-class change), not hidden behind a skill.

---

## R-3. Dry-run-then-approve write-safety model

**Decision**: The skill always produces a reviewable artifact (recommendations `.md` + runnable `.py`), shows a summary, and pauses for one approval before any write. After approval it validates, creates, verifies by re-fetch, and reports IDs. Partial failures are reported, not rolled back.

**Rationale**: metric-maker mutates shared customer-visible Mixpanel state; the dry-run / approve / execute / verify loop is the project's standard write-safety model for such skills. The runnable `.py` doubles as an audit trail and a re-run vehicle.

**Alternatives considered**:
- **Create immediately, offer undo**: rejected — undo of a multi-entity kit is itself a destructive multi-op and some entities may already be referenced.
- **No artifact, just a chat summary**: rejected — the runnable `.py` is the reproducible, inspectable record the write-safety model requires.

---

## R-4. Ground before designing; never guess the domain

**Decision**: The skill grounds in a strict priority order — (1) `ws.get_business_context_chain()`, (2) a user-supplied `.md` / pasted text, (3) ask in conversation — and its mandatory first data move is `ws.schema_graph(include_density=True)`. Every proposed block references only properties that exist on the referenced events (checked via `.properties_for_event` / `.events_for_property` / `density_local`), with concrete values sampled via `ws.property_values(...)`.

**Rationale**: A starter kit named in business vocabulary and grounded in the real schema is the entire value proposition. Guessing the domain or referencing non-existent properties produces blocks that look right but fail or mislead. `schema_graph` is the one call that makes the design schema-valid by construction.

**Alternatives considered**:
- **Design from event names alone**: rejected — event names without property/density grounding produce blocks that reference properties that do not exist on those events.
- **Skip grounding when the use case is "obvious"**: rejected — the skill must not assume; it asks when no grounding exists.

---

## R-5. Business-vocabulary naming taste; simplify aggressively; no duplicates

**Decision**: Every proposed block gets a business-vocabulary name ("Power Buyers," "Activated User," "Weekly Active Account"), a one-sentence definition, and a one-line rationale. Implementation-jargon names ("Cohort 1," "My Custom Prop") are banned. The skill simplifies aggressively (a small coherent kit a human can hold in their head beats an exhaustive one) and checks `list_*` for an existing entity before proposing each block (reuse / rename on a name match, never a silent duplicate). Every block is a saved, named, reusable entity — the publisher stance — never an anonymous inline one-off, so a pattern that repeats becomes shared org vocabulary rather than copy-pasted query state.

**Rationale**: The thesis is "Mixpanel is for humans, not data engineers" — preconfigured, named, reusable blocks end users never have to derive. Naming taste IS the product. Duplicate avoidance keeps the Lexicon clean for the downstream data-clean-up skill. The same named, typed, composable structure is also what makes prompt-to-insight reliable for any AI grounded in the project, so the publisher stance pays off for both humans and downstream LLM consumers.

**Alternatives considered**:
- **Precise-but-mysterious names** (e.g. `evt_purchase_amount_gt0_30d`): rejected — defeats the "for humans" thesis.
- **Always propose the full taxonomy**: rejected — an exhaustive kit is noise; size to the dataset + use case.

---

## R-6. Stop at the dashboard; hand off downstream

**Decision**: metric-maker stops at the dashboard boundary. After creating the kit it emits a structured handoff (entity type → business name → server ID) and names dashboard-expert (assembly) and data-clean-up (annotation / tagging) as next steps. It defers raw ad-hoc querying to mixpanelyst, and refuses irreversible governance ops (merge / delete / drop-filter).

**Rationale**: Each skill does one thing. metric-maker designs and creates the reusable blocks; dashboard-expert assembles them into a dashboard; data-clean-up governs the Lexicon copy/visibility; mixpanelyst runs one-off analysis. The reciprocal negative-routing clauses in the SKILL.md `description` keep the four skills from misfiring on each other.

**Custom-property split (stated identically on both sides)**: metric-maker owns ANALYTICAL custom properties (bucketing continuous values, deriving dimensions); data-clean-up (045) owns CLEANUP / regex custom properties (parsing or normalizing messy string values for hygiene). A messy-string-cleanup request defers to data-clean-up; an analytical bucket/dimension request from data-clean-up defers here.

**Alternatives considered**:
- **Build the dashboard too**: rejected — dashboard assembly is dashboard-expert's job; duplicating it drifts and bloats the skill.
- **Do the Lexicon annotation too**: rejected — governance is data-clean-up's job.

---

## R-7. The bundled `plan_kit.py` helper is the only tested code

**Decision**: The skill's one piece of executable code is `scripts/plan_kit.py`, which takes a kit spec (a list of typed block descriptors) and emits `metric_maker_plan.md` (recommendations) + `metric_maker_plan.py` (runnable). It is unit-tested TDD-style: the emitted `.py` is syntactically valid (`compile()`), imports `mixpanel_headless`, and the helper itself invokes NO `create_*` call (it only writes files). The skill body (SKILL.md + references) is verified via skill evals.

**Rationale**: The repo's strict TDD applies to executable Python; a Markdown skill is verified by evals, not unit tests. Isolating the only logic in a pure, testable helper keeps the write-safety guarantee (the helper never writes to Mixpanel) machine-checkable.

**Alternatives considered**:
- **Inline the artifact-emission logic in SKILL.md prose**: rejected — un-testable and drift-prone; a helper script is testable and re-runnable.

---

## R-8. The compression pyramid + universal archetype spine (what the kit IS)

**Decision**: The kit is organized as a compression pyramid — raw events (hundreds) → clean, governed events (the visible surface) → behaviors (dozens) → metrics / formulas (a handful) — where each layer compresses the one below into business language. The default contents are the universal metric archetypes nearly every product shares: acquisition, activation, engagement (DAU/WAU/MAU plus stickiness = DAU/MAU), retention (Nth-action / cohort), and revenue / value (per-user, AOV). The skill recognizes the recurring universal dataset classes by shape (identity: `distinct_id` / `user_id` / `device_id` / `account_id`; attribution: `utm_*` / source / medium / campaign / referrer; platform/device; geo; time; value/revenue), builds the obvious archetype on the classes the dataset actually carries, then specializes per vertical (ecommerce / SaaS / content / gaming).

**Rationale**: A raw project is unusable for a PM; the value is the handful of named concepts at the top of the pyramid. Defaulting to the universal archetypes — recognized from the universal classes — is what lets the skill generalize across customers without bespoke per-dataset config, while vertical specialization keeps the kit relevant. Archetypes the data cannot support (no revenue events → no revenue metric) are omitted, never fabricated, so the kit stays schema-honest. This is a direction, not a quota: rank by impact, build on the high-traffic / high-query head first, leave the long tail for later passes.

**Cardinality discipline**: cardinality grows multiplicatively (dimensions × values), so the skill quantifies before acting — it leads block decisions with the count (visible-vs-hidden, value cardinality, fill rate from `density_local`), not vibes. A bucketing custom property is preferred over an unbounded raw dimension when the value cardinality is high.

**Alternatives considered**:
- **Bespoke kit per customer from scratch**: rejected — does not generalize; the universal archetypes recognized from universal classes are what make the skill work on nearly any dataset.
- **Always ship the full taxonomy**: rejected — exhaustive is noise; size to the dataset + use case and lead with impact.

---

## R-9. Library-spec lineage for the consumed surface

**Decision**: metric-maker consumes a surface assembled across prior library specs; it names them rather than re-describing the methods. The behavior / metric / formula CRUD comes from feature 047-behaviors-metrics-formulas (the hard dependency, R-1). `create_custom_event` / `create_custom_property` / `validate_custom_property` ship in feature 027-data-governance-crud, with the custom-property query semantics behind the analytical split in feature 037-custom-properties-queries. `create_cohort` and the entity-CRUD surface ship in feature 024-core-entity-crud, with the cohort definition / behavior primitives the kit's cohorts and behaviors build on in features 035-cohort-definition-builder and 036-cohort-behaviors. The analytical-vs-cleanup custom-property split is stated identically here and in feature 045-data-clean-up.

**Rationale**: Naming the specs by number keeps the "already-existing surface" claim traceable for a reviewer and makes the one-way 047 → 048 dependency and the 045 ↔ 048 reciprocal boundary explicit, consistent with the repo's `(spec NNN)` / `Phase NNN` cross-reference idiom.
