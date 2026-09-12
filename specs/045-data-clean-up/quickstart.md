# Quickstart: `data-clean-up`

**Feature**: 045-data-clean-up
**Audience**: New users invoking the governance skill; reviewers smoke-testing before merge.

This walkthrough exercises every user story (P1–P2) from spec.md. Treat it as the merge-gate recipe. The skill auto-fires on a governance ask; the snippets below show the Python the skill runs under the hood so reviewers can verify each step against the live `Workspace` surface.

---

## Story 1 (P1) — Clean up a noisy project end-to-end

### 1.1 Ground (mandatory first moves)

```python
import mixpanel_headless as mp

ws = mp.Workspace.use(account="acme-corp", project=1234567)

# 1. Business context first (org + project markdown stored in Mixpanel).
context = ws.get_business_context_chain()
print(context[:500] if context else "(no business context — fall back to a user .md or one question)")

# 2. Schema graph second — the whole event<->property graph + per-pairing coverage.
schema = ws.schema_graph(include_density=True)
print("events:", schema.meta["event_count"], "| event properties:", schema.meta["event_property_count"])
print(schema.relationships_df.head(20))   # event | property | density_local
```

**Expected**: the context document grounds every later description; `relationships_df` gives the per-(event, property) `density_local` the classifier judges on.

### 1.2 Sample values for KEEP candidates

```python
# Only sample what you intend to keep — rate-limit discipline.
for prop in ["platform", "utm_source", "order_total"]:
    print(prop, ws.property_values(prop, event="Purchase", limit=10))
```

**Expected**: real values feed `example_value` and the cardinality judgment (`platform` low-card → keep; `utm_source` sparse-but-valuable → keep).

### 1.3 Review the dry-run plan + the one batched question

The skill writes `governance_plan.md` and `governance_apply.py`, prints a summary, then pauses:

```
governance plan for project 1234567 (acme-corp)
  keep + annotate:  43 events, 78 properties
  hide (noise):     162 events, 240 properties
  verified set on:  43 events
  tags applied:     Monetization, Onboarding, Engagement, Retail / Commerce
  PII candidates:   4 (see PII section — separate confirmation)

confident on 281 entities. need your call on these 9:
  - event "ev_x9"            — no business context, no samples, name uninformative
  - property "ctx_flag"      — boolean, but unclear what it gates
  ...
type `approved` to execute, `cancel` to abort, or answer the 9 above to refine.
```

**Expected**: no write has happened yet. The un-inferable tail is surfaced, never guessed (FR-014). KEEP/HIDE match the taste — `browser` kept, `browser_version` hidden at equal coverage; `utm_source` kept despite sparsity.

### 1.4 Approve and execute (autonomous bulk write)

```python
from mixpanel_headless import UpdateEventDefinitionParams, UpdatePropertyDefinitionParams

# After approval the skill issues BULK updates (not N single PATCHes):
ws.bulk_update_event_definitions(entries=[
    # one entry per kept event: display_name + domain description + tags + verified=True
    # ... and one entry per hidden event: hidden=True
])
ws.bulk_update_property_definitions(entries=[
    # kept: display_name + description + example_value (+ resource_type)
    # hidden: hidden=True
])
```

**Expected**: O(1) bulk calls per entity kind (FR-018); every kept+annotated event `verified=true` (FR-016).

### 1.5 Verify by re-fetch + diff

```python
live = ws.schema_graph(include_density=True, force_refresh=True)
# diff live annotations/hidden state against the plan; report any mismatch.
```

**Expected**: live Lexicon matches the plan. Any silently-failed PATCH is reported, not glossed (FR-024). Re-running the whole skill now proposes no writes (idempotent, FR-025).

---

## Story 2 (P2) — Surface and gate PII separately

### 2.1 PII section in the plan

```
## PII candidates (separate confirmation required)
  $email         severity: high   — direct identifier
  phone_number   severity: high   — direct identifier
  ssn            severity: high   — regulated identifier
  dob            severity: medium — quasi-identifier

these are NOT actioned by the main approval. type `approve pii` to set `sensitive`,
or leave them flagged-not-actioned (awaiting privacy decision).
```

### 2.2 Decline the PII subset

```python
# Main plan approved, PII declined → PII fields untouched.
# plan records: "$email, phone_number, ssn, dob — flagged, not actioned (awaiting privacy decision)"
```

**Expected**: nothing on the PII fields changed; nothing deleted/dropped (FR-020, SC-005).

### 2.3 Approve the PII subset

```python
ws.update_property_definition(
    "$email",
    UpdatePropertyDefinitionParams(sensitive=True),
)
# or bulk_update_property_definitions for the whole approved subset
```

**Expected**: `sensitive=true` on the approved subset only; never a delete.

---

## Story 3 (P2) — Emit + run the drift-check artifact

### 3.1 Emit the artifacts

After a successful cleanup the skill writes two user-owned files to the output dir:

```
./governance/
  governance_spec.json     # snapshot: events, properties, expected coverage, annotations, hidden set
  governance_check.py      # standalone checker stamped from the bundled template
```

### 3.2 Run the checker against the just-governed project

```bash
cd ./governance
MP_USERNAME=... MP_SECRET=... MP_PROJECT_ID=1234567 MP_REGION=us \
  python governance_check.py
# no significant drift
echo $?    # 0
```

### 3.3 Inject drift, re-run

```bash
# (e.g. someone added an un-annotated event, or hid a governed keeper)
python governance_check.py
# DRIFT: new un-annotated event "promo_v2_click"
# DRIFT: governed event "Purchase" is now hidden
echo $?    # non-zero → fails cron/CI
```

**Expected**: exit 0 when the live schema matches the spec; non-zero naming each drift otherwise (FR-028, SC-007). Drops straight into cron/CI.

---

## Smoke-test script (merge gate)

```bash
# The bundled drift-checker's logic is unit-tested (no live API needed):
uv run pytest tests/unit/plugin/test_governance_check_template.py -q

# Type + lint + coverage gate on the only shipped code:
uv run mypy --strict mixpanel-plugin/skills/data-clean-up/scripts/governance_check_template.py

# Full gate (the real merge bar):
just check
```

All must be green. `just check` is the hard merge gate (tasks.md T027).

---

## Trigger verification

The skill must auto-fire on governance asks and stay out of dashboard / metric asks:

| Phrase | Expected |
|--------|----------|
| "clean up this Mixpanel project's data dictionary" | data-clean-up fires |
| "organize / set up the schema" | data-clean-up fires |
| "write display names and descriptions, hide the noise" | data-clean-up fires |
| "tag events, mark the good ones verified" | data-clean-up fires |
| "flag any PII" | data-clean-up fires |
| "build me a dashboard" | dashboard-expert fires (NOT data-clean-up) |
| "create a power-users cohort / a revenue metric" | metric-maker fires (NOT data-clean-up) |
| "show me what this user did on screen / session recording" | session-replay surface (NOT data-clean-up) |

---

## Safety verification

Before merge, confirm the SKILL.md flow makes these impossible to misread:

- The main approval and the PII approval are visibly DISTINCT gates.
- Merge / delete / drop-filter each carry an extra-explicit confirmation naming the irreversible / data-loss consequence.
- No entity with an "unknown" decision is ever written before the user answers the batched question.
- Every governance write is a BULK call; no per-entity PATCH loop in the main plan.
- The bundled script carries NO secrets in source (env-first creds).
