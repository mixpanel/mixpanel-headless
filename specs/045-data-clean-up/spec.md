# Feature Specification: `data-clean-up` — a Mixpanel governance skill

**Feature Branch**: `045-data-clean-up`
**Created**: 2026-06-28
**Status**: Draft
**Input**: User description: "a governance / data-dictionary skill that grounds itself in a project's business context + schema, then classifies every event and property, drives the full Lexicon governance surface (display names, descriptions, example values, hide, tags, verified, sensitive), batches the un-inferable tail into one question, ships behind a single approval gate, verifies by re-fetch + diff, and emits a re-runnable drift-check artifact."

## Overview

`data-clean-up` is a Claude Code **skill** (it ships under `mixpanel-plugin/skills/data-clean-up/`), not a library change. It packages the judgment of a governance / data-dictionary expert — the "Invisible Woman" lineage whose core belief is **"Mixpanel is for humans, not data engineers."** A non-technical PM reading a governed Lexicon should see business concepts (`Completed Purchase`, `Power Buyers`, `Onboarding Complete`), not SDK noise (`$mp_session_record`, `browser_version`, `param1`).

The skill calls the already-shipped `Workspace` governance surface (`schema_graph`, `property_values`, `get_business_context_chain`, `get/update_event_definition`, `bulk_update_event_definitions`, `get/update_property_definition`, `bulk_update_property_definitions`, `list/create/update/delete_lexicon_tag`, `set_business_context`, `run_audit`, `list_drop_filters`). The governance write surface it orchestrates ships in **spec 027-data-governance-crud** (event/property definition CRUD, bulk updates, lexicon tags, drop filters, custom properties, custom events) and the audit/anomaly surface in **spec 028-schema-governance** (`run_audit`); this skill sequences those calls, it does not reimplement them. It adds **no new Python in `src/`**. The only NEW shipped code is one bundled, self-contained drift-check script template under `skills/data-clean-up/scripts/`, fully tested.

The skill recognizes the universal dataset spine that recurs across nearly every Mixpanel project — identity, attribution, platform/device, geo, time, and value/revenue classes — by shape, so the obvious keepers get named and the obvious noise gets hidden the same way on any customer without bespoke config. Every decision is evidence-backed (coverage + value distribution + data-quality profiling) and impact-ordered: act on the high-traffic head first (P0), tag and de-dup next (P1), sweep the long tail later (P2), each decision led by the count, never a vibe.

The skill mutates **shared, customer-visible Mixpanel state** (the Lexicon is referenced by every report and every analyst), so it follows a strict write-safety model: ground → classify → plan → **reviewable dry-run artifact** (a recommendations `.md` AND a runnable `.py`) → summary → **PAUSE for one approval** → execute the bulk write autonomously → verify by re-fetch + diff → emit the drift-check artifacts → optionally seed business-context back.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Clean up a noisy project's Lexicon end-to-end (Priority: P1)

A customer-success engineer or PM points the skill at a freshly-loaded Mixpanel project whose Lexicon is full of raw SDK noise and un-annotated events. They say "clean up this project's data dictionary." The skill grounds itself in the project's business context and schema, recognizes the universal dataset spine (identity / attribution / platform / geo / time / value) by shape, profiles each entity's evidence (coverage, value distribution, data-quality defects), classifies every event and property, computes a complete governance plan impact-ordered P0/P1/P2 (what to keep, what to hide, what to name and describe, what to tag, what looks like PII) acting on the high-traffic head first, surfaces the plan as a reviewable count-led artifact plus a single batched question list for the entities it genuinely cannot infer, waits for one approval, then executes the whole governance write autonomously and verifies it landed.

**Why this priority**: This is the headline use case and the MVP. Without it the skill delivers nothing. It is independently shippable: a project goes from "raw firehose" to "curated, human-readable tracking plan behind one approval" in a single session, even if nothing else in this spec ever ships.

**Independent Test**: Point the skill at a project that has business context stored and a schema with obvious noise (`$mp_*` props, `browser_version`, a debug event, vague `data` props) plus obvious keepers (`Purchase`, `platform`, `utm_source`). The skill produces a `governance_plan.md` whose KEEP/HIDE/ANNOTATE/TAG/PII decisions match the taste rules; it surfaces exactly the un-inferable entities as a batched question list; after one approval it issues the `bulk_update_*` calls; a re-fetch shows the live Lexicon matches the plan.

**Acceptance Scenarios**:

1. **Given** a project with org + project business context stored in Mixpanel, **When** the skill starts, **Then** its first data move is `ws.get_business_context_chain()` and its second is `ws.schema_graph(include_density=True)`; it never issues a governance write before both have returned.
2. **Given** a schema containing `$mp_session_record`, `browser_version`, `param1`, and a `signup_debug` event, **When** the skill classifies, **Then** all four are marked HIDE with a stated reason (SDK internal / granular variant / vague name / debug), and none is auto-deleted.
3. **Given** a schema containing `Purchase` (high volume) and `utm_source` (sparse coverage), **When** the skill classifies, **Then** `Purchase` is KEEP+verified and `utm_source` is KEEP despite low coverage, each with a domain-grounded description and (for `utm_source`) a sampled `example_value`.
4. **Given** 12 entities the skill cannot confidently classify from context + names + samples, **When** the dry-run plan is presented, **Then** the plan states "confident on N entities, need your call on these 12" and lists each with the specific ambiguity — and the skill does NOT write until the user answers.
5. **Given** an approved plan, **When** the skill executes, **Then** it issues `bulk_update_event_definitions` and `bulk_update_property_definitions` (not N single PATCHes), and every KEPT-and-fully-annotated event is marked `verified=true`.
6. **Given** a completed execution, **When** the skill verifies, **Then** it re-fetches the affected definitions, diffs live-vs-plan, and reports any entity whose live state does not match the plan (e.g. a PATCH that silently failed).
7. **Given** the same project run a second time with no schema changes, **When** the skill grounds and classifies, **Then** it reports the Lexicon is already governed and proposes no redundant writes (idempotent).

---

### User Story 2 — Surface and gate PII without ever auto-deleting (Priority: P2)

A privacy-conscious operator wants the cleanup to find PII-shaped fields and flag them, but never silently change retention-affecting state. The skill detects PII-shaped names, surfaces them in the plan with a severity, and only sets `sensitive` (or hides) on explicit approval. It never auto-deletes and never drops data.

**Why this priority**: PII handling is a distinct, high-stakes slice that is valuable on its own and is separable from the bulk annotate/hide flow. It rides the same approval gate but adds an extra-explicit confirmation for the PII subset.

**Independent Test**: Point the skill at a schema containing `$email`, `phone_number`, `ssn`, and `dob`. The plan contains a dedicated PII section listing all four with a severity rating; none is changed during the main execute unless the user explicitly approves the PII subset; `sensitive` is set only on the approved subset; nothing is deleted.

**Acceptance Scenarios**:

1. **Given** a schema with `$email`, `phone_number`, `ssn`, `dob`, **When** the skill classifies, **Then** all four appear in a `## PII candidates` section with severity, and none is set `sensitive` or hidden without an explicit PII-subset approval distinct from the main plan approval.
2. **Given** the user approves the main plan but NOT the PII subset, **When** the skill executes, **Then** the PII fields are left untouched and the plan records them as "flagged, not actioned (awaiting privacy decision)."
3. **Given** the user approves the PII subset, **When** the skill executes, **Then** it sets `sensitive=true` on the approved fields via `update_property_definition` / `bulk_update_property_definitions` and NEVER calls a delete.

---

### User Story 3 — Emit a re-runnable drift-check artifact the user owns (Priority: P2)

After a successful cleanup, the operator wants a way to catch the Lexicon rotting again — new un-annotated events sneaking in, governed entities disappearing, noise reappearing — without re-running the whole skill. The skill emits two artifacts the user owns: a `governance_spec.json` snapshot of the governed schema, and a standalone `governance_check.py` that on each run diffs the live schema against the spec and exits non-zero on significant drift, so it drops straight into cron or CI.

**Why this priority**: The drift-check makes the cleanup durable instead of a one-shot. It is independently valuable (a user could hand-write a spec and use the checker) and is separable from the cleanup execution.

**Independent Test**: After a cleanup, the skill writes `governance_spec.json` and a self-contained `governance_check.py` (pip header, env-first creds). Running the checker against the just-governed project exits 0. Mutating the live Lexicon (add an un-annotated event, hide a governed keeper) and re-running exits non-zero with a report naming the drift.

**Acceptance Scenarios**:

1. **Given** a completed cleanup, **When** the skill finishes, **Then** it writes `governance_spec.json` (events, properties, expected coverage, annotations, hidden set) and `governance_check.py` to the user's chosen output directory.
2. **Given** the emitted `governance_check.py` and an unchanged project, **When** the user runs it, **Then** it exits 0 and reports "no significant drift."
3. **Given** a new un-annotated event has appeared in the live schema since the snapshot, **When** the checker runs, **Then** it exits non-zero and names the new un-annotated event as drift.
4. **Given** a previously-governed (kept, verified) event has been hidden or dropped in the live schema, **When** the checker runs, **Then** it exits non-zero and names the dropped governed entity.
5. **Given** the bundled `governance_check_template.py`, **When** the project test suite runs, **Then** the template imports, type-checks under `mypy --strict`, and its drift-detection logic is unit-tested against fixture spec/live pairs.

---

### Edge Cases

- **No business context stored**: `get_business_context_chain()` returns empty → the skill falls back to a user-supplied `.md` file or pasted text; if neither is offered it asks one grounding question in conversation before classifying. It never classifies blind.
- **Empty / tiny schema**: `schema_graph()` returns 0 events → the skill reports "nothing to govern" and exits without writing.
- **Already-governed project**: every event already has display_name + description + correct hidden state → the skill proposes no writes and says so (US1 #7).
- **High coverage but noise**: `browser_version` is on every event (density_local ≈ 1.0) yet is noise → HIDE. Coverage alone never forces KEEP (see research.md / governance-taste.md worked examples).
- **Low coverage but high value**: `utm_source` / attribution props are sparse yet label paid-vs-organic traffic → KEEP. Low coverage never forces HIDE.
- **Granularity collision**: a clean parent (`browser`, `app_version`) coexists with granular variants (`browser_version`, `app_version_ms`, raw-string variant) → KEEP the parent, HIDE the variants.
- **Un-inferable tail**: an entity Claude genuinely cannot classify from context + name + samples → it goes in the ONE batched question list, never silently guessed. Never ship a guess.
- **Ambiguous mutate vs. read intent**: if the user's ask is exploratory ("what's in this project?") rather than a cleanup, the skill summarizes health and does NOT write — it defers governance to an explicit cleanup ask.
- **Merge requested**: merge is irreversible → it gets an extra-explicit confirmation distinct from the main approval, and the plan states "merge collapses the source's history into the survivor; not reversible."
- **Drop-filter requested**: a drop filter changes incoming data → extra-explicit confirmation; surfaced via `list_drop_filters()` context but never created without naming the data-loss consequence.
- **PATCH partial failure mid-bulk**: a bulk update returns a partial success → the verify step's re-fetch + diff catches the un-applied entities and the skill reports them rather than claiming full success.
- **Tagging an un-described entity**: the skill only tags entities that already carry a description (tags decorate curated entities, they do not substitute for annotation).
- **Approval declined**: the user says no at the gate → the skill writes nothing, leaves the dry-run artifacts on disk, and ends cleanly.
- **Scope confusion with sibling skills**: a request to build a dashboard or create a metric/cohort is out of scope → defer to `dashboard-expert` / `metric-maker`. `data-clean-up` only annotates entities others create.

## Requirements *(mandatory)*

### Functional Requirements

#### Grounding (mandatory first moves)

- **FR-001**: The skill MUST establish a context document before classifying, in this priority order: (1) `ws.get_business_context_chain()` (org + project markdown already stored in Mixpanel); (2) a user-supplied `.md` file or pasted text; (3) one batched grounding question in conversation. It MUST NOT classify without grounding.
- **FR-002**: The skill's mandatory FIRST data move on any cleanup is `ws.schema_graph(include_density=True)`, which returns the whole event↔property graph plus per-(event, property) coverage (`density_local`) and exposes `.properties_for_event(e)`, `.events_for_property(p)`, `.orphan_properties()`.
- **FR-003**: The skill MUST sample concrete values via `ws.property_values(prop, event=...)` for any property it intends to KEEP and annotate, to source a real `example_value` and to judge cardinality.
- **FR-004**: The skill MUST treat schema as semi-structured — judging KEEP/HIDE per `(event, property)` pairing using `density_local`, not by global presence of a property name.

#### Universal-spine recognition + evidence base

- **FR-004a**: The skill MUST first match every event and property against the universal dataset-spine classes — identity (`distinct_id`/`user_id`/`device_id`/`account_id`/`customer_id`/`session_id`), attribution (`utm_*`/`source`/`medium`/`campaign`/`referrer`), platform/device (`platform`/`$os`/`$browser`/`$device`/`app_version`), geo (`$country_code`/`$region`/`$city`), time, and value/revenue (`revenue`/`price`/`order_total`/durations/counts) — and treat each class consistently (KEEP-and-name the business-meaningful members; HIDE granular technical variants behind the clean parent). This shape-based recognition is what lets the skill generalize across customers without per-project config.
- **FR-004b**: Before judging any entity the skill MUST assemble its evidence base along five axes from the existing surface: coverage (`density_local`), value distribution + cardinality (`property_values` top values + frequencies), type consistency across events, casing/naming inconsistency, and numeric-stored-as-string. Each KEEP/HIDE reason MUST cite the evidence (e.g. "0.2% fill, 4 distinct values, all null"), never a bare assertion.

#### Classification taste (the heart of the skill)

- **FR-005**: For every event, every event-property, and every user-property the skill MUST produce a KEEP-or-HIDE decision with a stated reason. No entity is left unclassified.
- **FR-006**: The skill MUST drive toward a soft target of fewer than 50 visible events and fewer than 100 visible properties ("less visible is better"), but MUST NEVER hide a high-usage / high-value entity solely to hit the number. Coverage and the target are SIGNALS, not GATES.
- **FR-006a**: The skill MUST rank entities by recent volume (and query/report usage where exposed) and present the plan impact-ordered as P0 (highest-leverage, lowest-risk wins: hide obvious noise, name the top-volume keepers, flag numeric-string / always-null defects), P1 (tag described entities, hide granular variants behind kept parents, casing-duplicate merges), and P2 (the low-volume long tail). It MUST act on the high-traffic head first and MAY defer the tail to a later round; idempotent re-runs (FR-025) make rounds cheap. Every hide/keep decision MUST lead with the count (hidden vs visible, cardinality), and the plan summary MUST be a count table, not prose.
- **FR-007**: The skill MUST KEEP an entity iff it is well-covered on the events that matter AND low/medium cardinality AND business-meaningful per the context document — judged together, never on a single threshold.
- **FR-008**: The skill MUST HIDE: SDK `$`/`mp_`/`$mp_`-prefixed internals; IDs/UUIDs/tokens/hashes; near-zero-coverage entities; dead/never-queried entities; debug/test/dev entities; vague names (`data`, `value`, `param1`); and granular variants when a clean parent exists.
- **FR-008a**: The skill MUST surface data-quality defects found while profiling — a property typed differently across events, a numeric-stored-as-string property (a high-value low-risk typecast candidate), an always-null / near-empty property, and casing/naming duplicates of one concept — in the plan with the evidence. For casing duplicates it keeps the higher-volume canonical and hides the variant; the rest are flagged for the user (this skill does not silently retype data).
- **FR-009**: The skill MUST apply the worked-example nuances verbatim from `references/governance-taste.md`: high coverage alone does NOT justify KEEP (`browser_version` is everywhere but is noise → HIDE; `browser` at the same coverage is meaningful → KEEP); keep the high-level dimension and hide its `*_version` / `*_ms` / raw-string variants; low coverage does NOT justify HIDE for high-value sparse props (`utm_*` / attribution → KEEP).

#### Annotation (no entity left bare)

- **FR-010**: No entity the skill KEEPS may remain un-named or un-described. Every KEPT entity MUST receive a `display_name` and a `description`.
- **FR-011**: `display_name` MUST be auto-derived from the raw name: `snake_case` / `camelCase` / `ALL_CAPS` → Title Case; platform prefixes like `ios_` → an `(iOS)` suffix; feature grouping rendered with `:` (e.g. `checkout:payment`). Rules live in `references/display-name-and-annotation-rules.md`.
- **FR-012**: Descriptions MUST be specific and grounded in the customer domain (from the context document) — NEVER a generic stub like "A user did X."
- **FR-013**: `example_value` (for properties) MUST come from sampling `ws.property_values()`, not be invented.
- **FR-014**: The genuinely un-inferable tail MUST be collected into ONE batched question list surfaced WITH the dry-run plan, phrased "confident on N entities, need your call on these M: …". The user answers once; the skill fills the answers and executes. The skill MUST NEVER silently ship a guess.

#### Governance fields driven

- **FR-015**: The skill MUST drive these Lexicon fields via the existing `UpdateEventDefinitionParams` / `UpdatePropertyDefinitionParams`: `display_name`, `description`, `example_value` (properties), `hidden`, `tags`, `verified` (events), `sensitive` (PII, properties). `dropped` / `merged` are available but `merged` is irreversible and requires extra-explicit confirmation.
- **FR-016**: `verified=true` MUST be set on events the skill KEPT and fully annotated — it is the "blessed" signal that the entity is curated.
- **FR-017**: Tags MUST be plain domain-category strings (NO emoji) derived from the data + context document (e.g. `Monetization`, `Onboarding`, `Engagement`). The skill MUST only tag entities that already carry a description.
- **FR-018**: All KEEP+annotate and HIDE writes MUST be issued as bulk operations (`bulk_update_event_definitions`, `bulk_update_property_definitions` from spec 027-data-governance-crud) — not N single PATCHes — for the main plan execution.

#### PII handling

- **FR-019**: The skill MUST detect PII-shaped names (`$email`, `$phone`, `phone_number`, `ssn`, `address`, `dob`, `$first_name`, `$last_name`, `full_name`) and surface them in a dedicated plan section WITH a severity rating.
- **FR-020**: The skill MUST set `sensitive` (or hide) on PII ONLY on an explicit PII-subset approval, distinct from the main plan approval. It MUST NEVER auto-delete or auto-drop PII.

#### Write-safety model

- **FR-021**: Before any write the skill MUST produce a reviewable dry-run artifact pair: a recommendations `governance_plan.md` AND a runnable `governance_apply.py`, then print a summary, then PAUSE for exactly one approval for the main plan.
- **FR-022**: Conversation MUST be able to refine the plan before approval; refinement regenerates the artifacts and re-prompts.
- **FR-023**: Irreversible operations (`merge`, delete, drop-filter, and the PII `sensitive`/hide subset) MUST get an extra-explicit confirmation separate from the main approval and MUST name the irreversible / data-affecting consequence.
- **FR-024**: After approval the skill MUST execute the bulk write autonomously (no per-entity prompting) and then verify by re-fetching the affected definitions and diffing live-vs-plan, reporting any mismatch.
- **FR-025**: The skill MUST be idempotent: re-running against an already-governed, unchanged schema proposes no writes and says so.

#### Drift-check deliverable

- **FR-026**: After a successful cleanup the skill MUST emit `governance_spec.json` — a snapshot of the governed schema: events, properties, expected per-(event, property) coverage, annotations (display_name / description / example_value / tags), and the hidden set.
- **FR-027**: The skill MUST emit `governance_check.py` — a standalone, self-contained script (inline pip header, env-first credentials read from `MP_USERNAME` / `MP_SECRET` / `MP_PROJECT_ID` / `MP_REGION` per CLAUDE.md, no secrets in source) that on each run diffs the live schema against `governance_spec.json` and flags significant drift: new un-annotated events/properties, dropped governed entities, renamed entities, coverage shifts beyond a threshold, re-appeared noise.
- **FR-028**: `governance_check.py` MUST exit non-zero on significant drift so it drops into cron/CI, and exit zero when the live schema still matches the spec.
- **FR-029**: A `governance_check_template.py` MUST be bundled under `skills/data-clean-up/scripts/`, with the drift-check shape defined inline: an inline pip header, env-first credentials (`MP_USERNAME` / `MP_SECRET` / `MP_PROJECT_ID` / `MP_REGION`), a pure `detect_drift(spec, live) -> list[DriftFinding]` core with no I/O, and a `main()` that loads the spec, fetches live `schema_graph`, diffs, prints a report, and exits non-zero on significant drift. It MUST type-check under `mypy --strict`, carry complete docstrings, and have its `detect_drift` logic unit-tested against fixture spec/live pairs (this is the ONE piece of NEW shipped code with its own tests).

#### Optional business-context seeding

- **FR-030**: After learning the schema, the skill MAY seed business-context back via `ws.set_business_context()` — but ONLY on explicit user approval, treated as a write under the same gate.

#### Skill packaging & triggering

- **FR-031**: The skill MUST live at `mixpanel-plugin/skills/data-clean-up/` with `SKILL.md` (frontmatter: `name`, `description`, `allowed-tools`), a `references/` directory (`governance-taste.md`, `display-name-and-annotation-rules.md`, `drift-check.md`), and a `scripts/` directory (`governance_check_template.py`).
- **FR-032**: `SKILL.md` MUST be terse and table-driven with progressive disclosure into `references/` — matching the house style of `skills/mixpanelyst/SKILL.md` and `skills/dashboard-expert/SKILL.md`. It MUST NOT re-teach the whole `mixpanel_headless` API; it MUST defer to the hosted docs (`WebFetch https://mixpanel.github.io/mixpanel-headless/llms.txt`) and to `help.py` as the canonical API-discovery tool. It MUST NOT bundle a copy of `help.py`; bundled script paths use `${CLAUDE_SKILL_DIR}` interpolation.
- **FR-033**: The `SKILL.md` `description` MUST auto-fire on governance / data-dictionary intents. Proposed string:

  > curate a mixpanel project's lexicon so it reads like a tracking plan for humans, not a firehose. use when the user wants to clean up, organize, or set up a mixpanel project or schema; govern the data dictionary; write display names, descriptions, or example values; hide sdk noise; tag events; mark events verified; flag pii (sensitive); or audit lexicon health. grounds in business context and schema_graph, recognizes the universal dataset spine (identity / attribution / platform / geo / value) by shape, profiles coverage and value distribution as evidence, classifies every event and property keep vs hide, acts on the high-traffic head first, batches the ambiguous tail into one question, ships behind a single approval gate, verifies by re-fetch, and emits a re-runnable drift-check script. does not build dashboards (use dashboard-expert), does not create metrics/cohorts/behaviors (use metric-maker), and does not analyze session recordings (use the session-replay surface).

- **FR-034**: `allowed-tools` MUST be the minimal set the skill needs: `Bash Read Write WebFetch` (Bash to run Python against `mixpanel_headless` and `help.py`; Read/Write for artifacts; WebFetch for hosted docs). It MUST NOT request tools it does not use.

### Key Entities

- **Context document**: the grounding markdown for the project (from `get_business_context_chain`, a user file, or conversation). Drives every description and tag.
- **Schema graph**: `ws.schema_graph(include_density=True)` result — the event↔property graph with per-pairing `density_local`. The classification substrate.
- **Governance decision**: per-entity record — `{name, kind (event|event_property|user_property), decision (keep|hide), display_name, description, example_value?, tags?, verified?, sensitive?, reason, confidence}`. The atomic unit of the plan.
- **Governance plan**: the full set of decisions + the batched un-inferable question list + the PII section, rendered as `governance_plan.md` and `governance_apply.py`.
- **Governance spec** (`governance_spec.json`): the post-cleanup snapshot — events, properties, expected coverage, annotations, hidden set. Input to the drift checker.
- **Drift report**: the output of `governance_check.py` — added un-annotated entities, dropped governed entities, renames, coverage shifts, re-appeared noise; with a non-zero exit on significant drift.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: From a single "clean up this project" instruction, the skill takes a noisy project to a curated Lexicon (every KEPT entity named + described, noise hidden, keepers verified) behind exactly ONE main approval, with at most one batched question round for the un-inferable tail.
- **SC-002**: After execution, 100% of KEPT events carry a non-empty `display_name` AND a non-empty, non-generic `description`, and are marked `verified=true`; 100% of KEPT properties carry `display_name` + `description` + a sampled `example_value`. Verified by the re-fetch diff.
- **SC-003**: Every governance write is a bulk call; the skill issues O(1) bulk calls per entity kind for the main plan, not O(N) single PATCHes (measured by counting API calls in a mocked run).
- **SC-004**: No entity is ever silently guessed: every entity the skill could not infer appears in the batched question list, and no write touches an entity whose decision was "unknown" until the user answered. Verified against a fixture with deliberately ambiguous entities.
- **SC-005**: The skill never auto-deletes, auto-drops, or auto-merges. PII `sensitive`/hide changes happen only on an explicit, separate confirmation. Verified by a fixture run that approves the main plan but declines the PII subset — PII fields are untouched.
- **SC-006**: The taste rules hold on the worked examples: `browser_version` → HIDE and `browser` → KEEP at equal coverage; `utm_source` → KEEP despite sparse coverage; granular `*_version`/`*_ms` variants hidden when a clean parent is kept. Verified against the governance-taste fixture schema.
- **SC-007**: The emitted `governance_check.py` exits 0 against the just-governed project and non-zero after an injected drift (new un-annotated event OR a hidden governed keeper), naming the offending entity. Verified by the bundled template's unit tests against fixture spec/live pairs.
- **SC-008**: The bundled `governance_check_template.py` passes `just check` (mypy --strict, ruff, ≥90% coverage on its own logic, complete docstrings). The skill itself adds no other `src/` code and breaks no existing gate.
- **SC-009**: The `SKILL.md` description auto-fires on the trigger phrases ("clean up", "organize", "set up", "data dictionary", "Lexicon cleanup", "display names", "hide noise", "tag events", "verify", "flag PII") and does NOT fire on pure dashboard / metric-creation asks (those route to the sibling skills). Verified by a skill-trigger eval.
- **SC-010**: A new contributor can read `SKILL.md` + the three references and run a full cleanup on a fixture project without reading the library source, relying only on `help.py` and the hosted docs for API specifics.

## Assumptions

- The `Workspace` governance surface named in this spec already exists and is stable, shipped under spec 027-data-governance-crud (the Lexicon event/property definition CRUD, `bulk_update_*`, lexicon tags, drop filters, custom-property and custom-event CRUD) and spec 028-schema-governance (`run_audit` and the anomaly surface): `schema_graph(include_density=True)`, `property_values`, `get_business_context_chain`, `set_business_context`, `get/update_event_definition`, `bulk_update_event_definitions`, `get/update_property_definition`, `bulk_update_property_definitions`, `list/create/update/delete_lexicon_tag`, `run_audit`, `list_drop_filters`. `UpdateEventDefinitionParams` exposes `display_name`, `description`, `hidden`, `dropped`, `merged`, `verified`, `tags`; `UpdatePropertyDefinitionParams` exposes `display_name`, `description`, `example_value`, `hidden`, `dropped`, `sensitive`, `resource_type`. This skill adds NO new library methods — it orchestrates the 027/028 CRUD.
- `schema_graph(include_density=True)` returns per-(event, property) `density_local` coverage and the `.properties_for_event` / `.events_for_property` / `.orphan_properties` accessors. The skill judges per pairing, not per global property name.
- Business context, when present, is stored in Mixpanel and reachable via `get_business_context_chain()`. When absent the skill degrades to a user file or one grounding question; it never classifies blind.
- The skill is the curator of Lexicon copy and visibility only. Building dashboards is `dashboard-expert`; creating metrics/cohorts/behaviors is `metric-maker` (the sibling skill, spec 048-metric-maker, which depends on the behaviors/metrics/formulas library in spec 047-behaviors-metrics-formulas); `data-clean-up` annotates entities those skills create but does not create them.
- Custom-property ownership is split and the two skills state it identically: `data-clean-up` owns CLEANUP / regex custom properties (parsing or normalizing messy string values for hygiene); `metric-maker` (spec 048-metric-maker) owns ANALYTICAL custom properties (bucketing continuous values, deriving dimensions). When the user asks for an analytical bucket/dimension, `data-clean-up` defers to `metric-maker`; when the user asks to clean up a messy string value, `metric-maker` defers to `data-clean-up`. The underlying `create_custom_property` / `validate_custom_property` CRUD ships in spec 027-data-governance-crud; the custom-property query semantics are governed by spec 037-custom-properties-queries.
- Session-replay asks (`$mp_session_record` is flagged here as SDK noise to hide; analyzing what a user did on screen is a different capability) route to the session-replay surface in spec 044-session-replay, not this skill.
- The drift-check artifacts are owned and run by the user (cron/CI), outside this repo. Only the `governance_check_template.py` ships in the repo and carries tests.
- The plugin's `help.py` and hosted docs (`https://mixpanel.github.io/mixpanel-headless/llms.txt`) are the canonical API-discovery surface; `SKILL.md` defers to them rather than duplicating signatures.
- Strict TDD, `mypy --strict`, ruff, ≥90% coverage, and complete docstrings apply to the one bundled script (`governance_check_template.py`) and its tests. The Markdown skill assets (`SKILL.md`, references) are reviewed for taste fidelity and trigger accuracy, not unit-tested.
- "Less visible is better" is a soft target (<50 visible events, <100 visible properties), never a hard cap; the skill drives toward it but never sacrifices a high-value entity to hit it.
