# Phase 0 Research: `data-clean-up`

**Feature**: 045-data-clean-up
**Date**: 2026-06-28
**Status**: Complete — no NEEDS CLARIFICATION markers in plan.md remain.

This document records the load-bearing decisions for the governance skill, their rationale, and the rejected alternatives — and, most importantly, captures the **keep/hide taste with worked examples** that is the heart of the skill. The taste section here is the source of truth; `references/governance-taste.md` is the shipped, skill-loadable copy distilled from it.

Public prior art (so reviewers can audit without re-deriving): the power-tools `ai-rename-entities-system.txt` and `ai-show-hide-system.txt` system prompts in `https://github.com/mixpanel/mixpanel-power-tools` (repo-relative `templates/prompts/ai-rename-entities-system.txt`, `templates/prompts/ai-show-hide-system.txt`). The skill also leans on two existing library specs as the underlying CRUD it orchestrates: spec 027-data-governance-crud (event/property definition CRUD, bulk updates, lexicon tags, drop filters, custom properties, custom events) and spec 028-schema-governance (the `run_audit` / anomaly audit surface).

---

## R-1. Ground before classifying — business context first, schema second, samples third

**Decision**: The skill's mandatory grounding order is (1) `ws.get_business_context_chain()`, (2) `ws.schema_graph(include_density=True)`, (3) `ws.property_values(prop, event=...)` for KEEP candidates only. No classification happens before (1) and (2) return.

**Rationale**:
- Descriptions and tags are only "specific and domain-aware" (FR-012) if the skill knows the business. Business context stored in Mixpanel is the cheapest, most authoritative source — the org/project markdown was written for exactly this grounding purpose.
- `schema_graph(include_density=True)` is one call that returns the whole event↔property graph plus per-pairing coverage, replacing dozens of `properties()` / `property_values()` round trips. It is the single most useful grounding move (mirrors the `mixpanelyst` "best first move" guidance).
- Sampling values is needed for `example_value` and cardinality judgment, but is rate-limit-expensive, so it is bounded to KEEP candidates rather than the whole schema.

**Alternatives considered**:
- **Classify from names alone**: rejected — names lie (`data`, `value`, `param1`) and miss domain meaning; produces generic stubs.
- **Enumerate `property_values` for every property**: rejected — rate-limit nuke (the Invisible Woman's #1 failure mode). Sample only what you intend to keep.
- **Skip business context, ask the user everything**: rejected — chatty, ignores context already stored in Mixpanel.

---

## R-2. Coverage (`density_local`) is a signal, not a gate — judge per (event, property) pairing

**Decision**: The skill judges KEEP/HIDE per `(event, property)` pairing using `density_local`, treating Mixpanel data as semi-structured (each event has its own schema). High pairing density is usually necessary but never sufficient for KEEP; low density never forces HIDE.

**Rationale**:
- Mixpanel is semi-structured: a property present on 2% of events globally may be present on 100% of the events that matter. Global presence is the wrong unit.
- `density_local` from `schema_graph` gives exactly the per-pairing coverage needed. The classification is "is this property well-covered on the events where it should appear, and is it meaningful there?"
- The power-tools `ai-show-hide` prompt (`https://github.com/mixpanel/mixpanel-power-tools`, `templates/prompts/ai-show-hide-system.txt`) already learned this: "high count but zero usage" hides; "low count but meaningful action" keeps. Coverage is one input among several.

**Alternatives considered**:
- **Global coverage threshold (hide < X%)**: rejected — hides sparse-but-valuable attribution props; keeps high-coverage noise.
- **Keep everything with any coverage**: rejected — defeats the whole "<50 visible events" goal.

---

## R-2b. Recognize the universal dataset spine — classify by shape, not by bespoke config

**Decision**: before reasoning case-by-case, the skill matches every event and property against the recurring classes that show up in nearly every Mixpanel dataset, and treats each class consistently. The spine is: **identity** (`distinct_id`, `user_id`, `device_id`, `account_id`, `customer_id`, `session_id`), **attribution** (`utm_*`, `source`, `medium`, `campaign`, `referrer`), **platform/device** (`platform`, `$os`, `$browser`, `$device`, `app_version`), **geo** (`$country_code`, `$region`, `$city`), **time** (event time + recency-derived fields), and **value/revenue** (`revenue`, `price`, `order_total`, durations, counts). Identity / attribution / platform / geo / value classes default to KEEP-and-name; granular technical variants within a class (`*_version`, raw user-agent, viewport, raw epoch) default to HIDE behind the clean parent.

**Rationale**:
- Shape-based recognition is what lets one skill generalize across customers without per-project rules. The same six classes recur whether the project is commerce, SaaS, content, or gaming; recognizing them by name/shape means the obvious keepers are named and the obvious noise is hidden the same way every time.
- It also de-risks the silent killers: attribution props are sparse-but-valuable (R-3 worked example #3), identity props are high-cardinality-but-KEEP, and the per-class default keeps the classifier from mis-hiding either.

**Alternatives considered**:
- **Per-project bespoke keep/hide lists**: rejected — does not generalize; reproduces the manual-curation cost the skill removes.
- **Treat every property uniformly by coverage/cardinality**: rejected — mis-hides sparse attribution and mis-keeps granular technical variants; the class is the missing signal.

---

## R-2c. Profile the evidence base before any decision — coverage + value-distribution + data-quality

**Decision**: every KEEP/HIDE/annotate decision is evidence-backed, profiled along five axes the existing surface already exposes: (1) **fill rate / coverage** per `(event, property)` from `schema_graph(include_density=True)` `density_local`; (2) **value distribution + cardinality** from `ws.property_values(prop, event=...)` (top distinct values + frequencies → categorical vs unbounded); (3) **type consistency** (the same property typed differently across events is a defect to flag, not silently keep); (4) **casing / naming inconsistency** (same concept in different casing → keep the higher-volume canonical, hide the variant); (5) **numeric-stored-as-string** (a string property whose sampled values always parse as numbers is a high-value, low-risk typecast candidate to flag). Coverage stays a SIGNAL, not a GATE (R-2).

**Rationale**:
- Decisions stated as "hide, 0.2% fill, 4 distinct values, all `null`/empty" are auditable; vibes are not. The evidence is cheap — one `schema_graph` call plus bounded `property_values` sampling on KEEP candidates — and it is the same data the drift-checker later snapshots.
- Value distribution is what separates a low-cardinality segmentation key (KEEP) from an unbounded id / free-text blob (HIDE), and what surfaces always-null and numeric-stored-as-string traps the coverage number alone hides.

**Alternatives considered**:
- **Decide from names + coverage only**: rejected — misses always-null, type-inconsistency, and numeric-string defects that names don't reveal.
- **Full `property_values` sweep of every property**: rejected — rate-limit nuke (R-1); sample only KEEP candidates.

---

## R-3. The keep/hide taste (THE HEART) — captured with worked examples

This is the judgment the skill exists to encode. It is deliberately a set of worked examples, not a threshold table, because every threshold has a counterexample.

### Guiding principles

1. **Less visible is better.** Soft target: fewer than 50 visible events, fewer than 100 visible properties. Drive TOWARD it. NEVER hide a high-usage / high-value entity just to hit the number. The target is a direction, not a cap.
2. **Coverage is a SIGNAL, not a GATE.** High `density_local` is usually necessary but not sufficient. Judge per `(event, property)` pairing.
3. **KEEP iff** the entity is well-covered on the events that matter **AND** low/medium cardinality **AND** business-meaningful per the context doc. All three, judged together.
4. **It is judgment, grounded in the context doc, not a threshold.**

### KEEP when

- Business-critical events: `Purchase`, `Sign Up`, `Login`, `Checkout`, `Add to Cart`, subscription changes — anything the context doc treats as a conversion or core engagement moment.
- Segmentation dimensions a PM would slice by: `platform`, `country`, `plan_type`, `product_category`, `campaign`, high-level `browser` / `os` / `device`.
- Numeric metrics for aggregation: `revenue`, `price`, `order_total`, durations, counts.
- Identifiers that enable single-user analysis despite high cardinality: `email`, `user_id`, `distinct_id`, `customer_id`, `session_id` (keep visible; flag PII separately).
- High-value sparse props: `utm_source`, `utm_medium`, `utm_campaign`, attribution / referrer props — even at low coverage, because they label paid-vs-organic traffic.

### HIDE when

- SDK / Mixpanel internals: `$mp_*`, `mp_*` prefixes, `$insert_id`, `$mp_api_endpoint`, `$mp_event_size`, `$mp_session_record`, `$import`, `$geo_source`.
- IDs/UUIDs/tokens/hashes/checksums, request/trace/correlation IDs, raw JSON / base64 blobs (that are NOT the primary user identifier).
- Near-zero coverage on every event where it appears AND no business meaning.
- Dead / never-queried entities (zero usage, and the name signals no value).
- Debug / test / dev: names containing `_debug`, `_test`, `_internal`, `_temp`, `_dev`; starting with `test_`, `debug_`, `dev_`.
- Vague names: `data`, `value`, `param1`, `param2`, `temp`, `tmp`, `flag`, `event`, `action`, `update`.
- Granular variants when a clean parent exists (see worked example #2).

### Worked example #1 — high coverage does NOT justify keep

`browser_version` appears on **every** event (`density_local` ≈ 1.0). Naive coverage-based classification keeps it. **WRONG.** `browser_version` is granular SDK noise no PM segments by → **HIDE**.

`browser` appears at the **same** coverage (≈ 1.0). It is a business-meaningful segmentation dimension ("how do Chrome users convert vs Safari?") → **KEEP**, with a description and a sampled `example_value` (`Chrome`).

> The lesson: two properties at identical coverage get opposite decisions. Coverage did not decide it; meaning did.

### Worked example #2 — granularity discrimination

A schema carries `app_version`, `app_version_ms`, and `app_version_raw` (a raw string variant), all at high coverage.

- KEEP `app_version` — the high-level dimension a PM uses to compare release adoption.
- HIDE `app_version_ms` — a millisecond-precision variant; noise.
- HIDE `app_version_raw` — the unparsed string variant; the clean parent supersedes it.

> The rule: keep the high-level dimension, hide its `*_version` / `*_ms` / raw-string descendants when a clean parent is kept.

### Worked example #3 — low coverage does NOT justify hide

`utm_source` appears on only ~3% of events (sparse — it is only set on first-touch / campaign-attributed sessions). Naive coverage-based classification hides it. **WRONG.** `utm_source` labels traffic as paid-vs-organic — high analytical value despite sparsity → **KEEP**, with a description grounded in the context doc's acquisition story and a sampled `example_value`.

> The lesson: sparsity is not noise when the property carries scarce, high-value signal.

### Worked example #4 — the soft target is a direction, not a cap

A project has 220 events. The skill drives toward <50 visible by hiding the ~170 obvious-noise events. But if the 55th-most-useful event is a genuinely business-critical low-frequency event (`account_deleted`, `subscription_cancelled`), it stays VISIBLE even though that pushes visible-count past 50. The number yields to value.

**Rationale for capturing as examples, not thresholds**: every threshold ("hide < 1% coverage", "keep top 50 by volume") has the counterexamples above. The skill must reason from meaning + context + coverage together. The worked examples teach the reasoning; a threshold table would mis-teach it.

**Alternatives considered**:
- **A pure threshold table (coverage / volume cutoffs)**: rejected — every cutoff has a documented counterexample; produces confidently-wrong classifications.
- **Defer all keep/hide to the user**: rejected — defeats the skill; the whole point is encoded judgment with a batched question list only for the genuine tail.

---

## R-3b. Transitional architecture — act on the head first, ordered P0/P1/P2

**Decision**: cleanup is gradual and impact-ranked, not all-at-once. The skill ranks entities by recent volume (and, where the surface exposes it, query/report usage), then acts on the high-traffic / high-query **head** first and leaves the long tail for a later round. The plan presents decisions in priority order: **P0** the highest-leverage, lowest-risk governance wins (hide obvious SDK/debug/vague noise; name + describe the top-volume keepers; flag numeric-stored-as-string and always-null defects); **P1** the next tier (tag described entities, hide granular variants behind kept parents, casing-duplicate merges); **P2** the long tail (low-volume survivors, tighter second-pass hides). The `<50 events / <100 properties` target is a direction the head-first pass moves toward, never a quota that forces a low-value entity out (R-3 #4).

**Back-of-napkin discipline**: every hide/keep decision leads with the count, not a vibe. Cardinality grows multiplicatively (dimensions × distinct values), so the skill states the numbers — hidden vs visible counts, per-class coverage tier, value cardinality — before acting, and quantifies the win ("hiding 162 noise events takes the visible surface from 220 to 58"). The plan summary is a count table, not prose.

**Rationale**:
- Ship value now. A noisy 220-event project becomes usable the moment its top keepers are named and its obvious noise is hidden; the long tail can wait for a later round once real usage signals mature (R-8 idempotent re-runs make rounds cheap). Boiling the ocean on round one is slower and riskier with no extra payoff.
- P0/P1/P2 ordering makes the plan reviewable: a reviewer reads the high-leverage decisions first and can approve the head without auditing every tail entity.

**Alternatives considered**:
- **Govern every entity in one exhaustive pass**: rejected — slow, high-review-cost, and the tail's value-per-decision is low; the head delivers most of the benefit.
- **Order the plan alphabetically / by name**: rejected — buries the high-leverage decisions; volume order is what makes the head obvious.

---

## R-3c. The skill orchestrates 027/028 CRUD — it adds no governance API of its own

**Decision**: every governance write this skill issues lands through the already-shipped surface from **spec 027-data-governance-crud** (event/property definition `get_/update_/bulk_update_`, lexicon tags `list/create/update/delete_lexicon_tag`, drop filters `list_drop_filters`, custom-event and custom-property CRUD) and reads health from **spec 028-schema-governance** (`run_audit` and the anomaly surface). The skill is judgment + sequencing over that CRUD; it adds no new `src/` method.

**Rationale**:
- Keeps the library lean (Library-First): the curation lives in a skill, the mutations live in 027/028 where they are typed, validated, and tested. The cleanup/regex custom properties the skill may create use 027's `create_custom_property` / `validate_custom_property`; their query semantics are governed by spec 037-custom-properties-queries. Analytical custom properties (bucketing, derived dimensions) belong to spec 048-metric-maker, not here.

**Alternatives considered**:
- **Add governance helpers to `src/`**: rejected — duplicates 027/028; the skill is the right home for orchestration judgment.

---

## R-4. No entity left bare — annotation rules

**Decision**: Every KEPT entity gets a `display_name` (auto-derived) and a domain-grounded `description`; KEPT properties also get a sampled `example_value`. The un-inferable tail is batched into ONE question.

**Display-name derivation** (full rules in `references/display-name-and-annotation-rules.md`):
- `snake_case` / `camelCase` / `ALL_CAPS` → Title Case (`order_total` → "Order Total", `completeQuest` → "Complete Quest", `SUBSCRIPTION_CREATED` → "Subscription Created").
- Platform prefixes become suffixes: `ios_purchase` → "Purchase (iOS)".
- Feature grouping rendered with `:` — `checkout_payment_failed` → "Checkout: Payment Failed".

**Description rule**: specific + customer-domain-aware, grounded in the context doc. A good description names the role the entity plays in the business — e.g. `Started Workout` → "a member started a class. the core engagement event and primary funnel conversion step." NEVER a generic stub ("A user did X").

**example_value rule**: sourced from `ws.property_values(prop, event=...)`, never invented — a real sampled value (e.g. `Order Total` → `1445`, `Browser` → `Chrome`).

**Batched-tail rule**: entities Claude genuinely cannot classify from context + name + samples go in ONE list surfaced with the plan ("confident on N entities, need your call on these M: …"). The user answers once; the skill fills and executes. NEVER silently ship a guess.

**Rationale**: an un-annotated Lexicon is the problem the skill solves; leaving any kept entity bare reproduces it. Auto-derivation handles the 90% case; the batched question handles the genuine tail without chattiness.

**Alternatives considered**:
- **Annotate only the top-N events**: rejected — leaves the long tail bare, the exact rot the skill fights.
- **Ask per ambiguous entity as they arise**: rejected — chatty; the house style is ONE batched question.
- **Invent example values**: rejected — misleads the PM reading the Lexicon; sample real values.

---

## R-5. Governance fields and the `verified` blessing

**Decision**: drive `display_name`, `description`, `example_value`, `hidden`, `tags`, `verified`, `sensitive` via the existing `UpdateEventDefinitionParams` / `UpdatePropertyDefinitionParams`. Set `verified=true` on events the skill KEPT and fully annotated.

**Rationale**:
- `verified` is Mixpanel's "this entity is curated and blessed" signal. Setting it on kept+annotated events makes the curation legible to every analyst and to the drift checker (a kept event losing `verified` is drift).
- `dropped` / `merged` exist but `merged` is irreversible — it collapses the source's history into the survivor — so it never rides the main approval; it requires extra-explicit confirmation.

**Alternatives considered**:
- **Set `verified` on everything kept regardless of annotation completeness**: rejected — `verified` should mean "named, described, and blessed," not merely "not hidden."
- **Use `merged` freely in the main plan**: rejected — irreversible; must be its own gated decision.

---

## R-6. Tags are plain domain categories, no emoji, only on described entities

**Decision**: tags are plain strings derived from the data + context doc (`Monetization`, `Onboarding`, `Engagement`, `Retail / Commerce`, …). No emoji. Only tag entities that already carry a description.

**Rationale**:
- Tags are a navigation aid for humans; emoji add noise and break filtering / search.
- Tagging an un-described entity is backwards — the description is the primary curation; the tag decorates it. Tag by functional category (`Workout`, `Monetization`) only alongside a description.

**Alternatives considered**:
- **Emoji-prefixed tags for visual grouping**: rejected — noise, fragile.
- **Auto-tag everything by keyword regardless of description**: rejected — tags an un-curated entity, inverting the priority.

---

## R-7. PII — detect, surface with severity, gate separately, never auto-delete

**Decision**: detect PII-shaped names (`$email`, `$phone`, `phone_number`, `ssn`, `address`, `dob`, `$first_name`, `$last_name`, `full_name`); surface them in a dedicated plan section with severity; set `sensitive`/hide ONLY on an explicit PII-subset approval separate from the main plan; NEVER auto-delete/drop.

**Rationale**:
- PII handling is a privacy-team decision, not an analytics decision (the Invisible Woman is explicit: "You don't auto-delete or auto-hide PII"). The skill surfaces candidates; a human decides.
- `sensitive` and hide change how the data is treated; that is high-stakes and deserves its own confirmation distinct from the bulk annotate/hide.

**Alternatives considered**:
- **Auto-set `sensitive` on detection**: rejected — usurps a privacy decision; could surprise the customer.
- **Hide PII silently as part of the main plan**: rejected — buries a high-stakes change in a bulk approval.

---

## R-8. Write-safety — dry-run artifact pair, one approval, autonomous execute, verify by diff

**Decision**: ground → classify → plan → write `governance_plan.md` + `governance_apply.py` → print summary → PAUSE for one main approval → execute bulk write autonomously → re-fetch + diff → report. Irreversible ops (merge, delete, drop-filter, PII subset) get extra-explicit confirmation. Idempotent on re-run.

**Rationale**:
- The Lexicon is shared, customer-visible state referenced by every report; a wrong bulk write degrades every analyst's experience. The dry-run artifact makes the change auditable BEFORE it lands.
- Two artifacts: the `.md` is for human review; the `.py` is the exact runnable plan (so the change is reproducible and reviewable as code). This mirrors the Invisible Woman's "blueprint then execute" and the hello-world spec-check's snapshot-then-apply-then-restore discipline.
- Verify-by-diff catches partial bulk failures — the skill never claims success it did not confirm.
- One approval (not per-entity) respects the "execute the bulk write autonomously" requirement; chattiness is reserved for the single batched question and the gate.

**Alternatives considered**:
- **Apply directly, show a diff after**: rejected — the customer-visible change has already landed; no pre-flight review.
- **Prompt per entity**: rejected — unusably chatty for a 200-entity schema.
- **Trust the bulk response, skip the re-fetch**: rejected — partial failures would be reported as success.

---

## R-9. Drift-check — a bundled, tested template the skill stamps out

**Decision**: ship `governance_check_template.py` under `skills/data-clean-up/scripts/`, self-contained: inline pip header, env-first credentials (`MP_USERNAME` / `MP_SECRET` / `MP_PROJECT_ID` / `MP_REGION` per CLAUDE.md), a pure `detect_drift(spec, live)` core with no I/O, and a `main()` that reads `governance_spec.json`, fetches live `schema_graph`, diffs, and exits non-zero on significant drift. The skill stamps a project-specific `governance_check.py` from it after a cleanup. The template is the ONLY shipped code and is fully unit-tested. (A private hello-world drift-check script informed the shape, but is non-shipping prior art only; the contract above is defined inline here, not by reference to any private file.)

**Drift classes detected**: new un-annotated events/properties; dropped governed entities (a kept/verified entity now hidden, dropped, or absent); renamed entities; coverage shifts beyond a threshold; re-appeared noise (a hidden entity now visible).

**Rationale**:
- A hand-written-each-time checker is untested and quality-variable — the exact regression the feature fights. A bundled, type-checked, unit-tested template guarantees correctness by construction.
- Env-first creds + inline pip header make the emitted `governance_check.py` runnable standalone in cron/CI, outside this repo, with no secrets in source.
- Non-zero exit on drift is the Unix contract that lets it drop into CI.

**Alternatives considered**:
- **Skill writes the checker freehand each run**: rejected — no test guarantee; logic can silently be wrong.
- **Add the checker as a `Workspace` method**: rejected — it is a user-owned cron/CI artifact, not part of the query/CRUD library surface; keeping it a template keeps the library lean and the artifact self-contained.

---

## R-10. Packaging & triggering — terse SKILL.md, progressive disclosure, defer API discovery

**Decision**: `SKILL.md` is terse and table-driven; depth lives in three `references/` docs; API discovery defers to `help.py` + hosted docs (no bundled `help.py` copy); `allowed-tools: Bash Read Write WebFetch`. The trigger `description` fires on governance / data-dictionary intents and explicitly defers dashboards/metrics to the sibling skills.

**Rationale**:
- Matches the established `mixpanelyst` / `dashboard-expert` house style — the maintainer reviews against that bar.
- `help.py` is the canonical, always-current API surface; duplicating signatures in `SKILL.md` would rot. Triplicating the 32KB `help.py` across skills is explicitly disallowed.
- The trigger must catch "clean up / organize / set up a project", "data dictionary", "Lexicon", "display names", "hide noise", "tag events", "verify", "flag PII" — and must NOT poach dashboard/metric asks.

**Alternatives considered**:
- **Fat SKILL.md with the full API**: rejected — context bloat, rots against the library, violates the convention.
- **Bundle `help.py` per skill**: rejected — explicitly disallowed (triplicates 32KB); reference it via the plugin root / hosted docs.
