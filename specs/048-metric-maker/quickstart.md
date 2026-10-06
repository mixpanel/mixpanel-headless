# Quickstart: metric-maker skill

**Feature**: 048-metric-maker
**Audience**: Users of the metric-maker skill; reviewers smoke-testing before merge.

This walkthrough exercises every user story (US1–US3) from spec.md. Treat it as the merge-gate recipe.

**Prerequisite**: feature 047-behaviors-metrics-formulas must be merged/released — the skill calls `create_behavior` / `create_metric` / `create_formula`, which ship there. Confirm with `python help.py Workspace.create_metric` before running.

---

### US1 + US2 — Ground, design a starter kit, dry-run then approve

```
# In a Claude Code session against a Mixpanel project:
> set up metrics for my e-commerce app so my team can build dashboards
  without touching raw events
```

The metric-maker skill:

1. Grounds: `ws.get_business_context_chain()` → (fallback) a supplied `.md` → (fallback) asks.
2. First data move: `ws.schema_graph(include_density=True)`; samples values with `ws.property_values(...)`.
3. Designs a coherent starter kit on the universal archetype spine (acquisition / activation / engagement + stickiness / retention / revenue), specialized for ecommerce and sized to the dataset, e.g.:
   - **custom event** "Completed Purchase" — purchase with amount > 0
   - **analytical custom property** "Order Value Tier" — buckets `amount` into Low/Mid/High
   - **cohort** "Power Buyers" — purchased 5+ times in 30d
   - **behavior** "Checkout Funnel" — view cart → checkout → purchase
   - **metric** "Average Order Value" — average of `amount` on purchase
   - **formula** "Repeat Purchase Rate" — repeat buyers / all buyers * 100
4. Writes the dry-run artifact:
   ```
   ./metric_maker_plan.md   # recommendations: each block, definition, one-line rationale
   ./metric_maker_plan.py   # runnable script that would create them
   ```
5. Shows a summary and PAUSES:
   ```
   Proposed starter kit: 1 custom event, 1 custom property, 1 cohort, 1 behavior,
   2 metrics, 1 formula. No Mixpanel entities created yet. Approve to create, or
   refine first (e.g. "drop the cohort, add a refund metric").
   ```

Refine in conversation, then approve. The skill validates (e.g. `validate_custom_property`), creates via the released `Workspace` CRUD, re-fetches to verify, and reports IDs.

### US3 — Handoff to downstream skills

After creation:

```
Created starter kit:
  custom_event       Completed Purchase     id 88123
  custom_property    Order Value Tier       id 4471
  cohort             Power Buyers           id 990017
  behavior           Checkout Funnel        id 55021
  metric             Average Order Value    id 55022
  metric             Repeat Buyers          id 55023
  formula            Repeat Purchase Rate   id 55024

Next:
  - dashboard-expert: build a dashboard from metrics 55022/55023 and formula 55024
  - data-clean-up: annotate / tag these new entities in Lexicon
```

---

## Write-safety verification (merge gate)

Before each merge, confirm the skill writes nothing before approval:

```
# Dry run a kit and confirm zero entities created until approval.
# 1. Invoke the skill, let it produce the plan artifacts.
# 2. Diff list_metrics()/list_behaviors()/list_formulas() before and after the
#    dry-run: counts MUST be unchanged.
# 3. Only after explicit approval do the counts increase.
```

## plan_kit.py helper verification (merge gate)

```bash
# The helper emits both artifacts and writes nothing to Mixpanel.
uv run python -m pytest tests/unit/test_metric_maker_plan_kit.py -q
# - asserts metric_maker_plan.md has one section per block (name + definition + rationale)
# - asserts metric_maker_plan.py compiles (compile()) and imports mixpanel_headless
# - asserts the helper invokes NO create_* call
```

## Trigger verification (merge gate)

Confirm the SKILL.md `description` fires on metric-creation phrasing and stays quiet on the sibling skills' territory:

```
# FIRES (metric-maker):
#   "create a power-users cohort", "set up metrics for my app",
#   "define a revenue metric", "build me reusable building blocks"
# DOES NOT FIRE (routes elsewhere):
#   "clean up / organize the data dictionary", "hide the SDK noise", "flag PII"  -> data-clean-up
#   "build me a dashboard"                                                        -> dashboard-expert
#   "run a funnel query for last week"                                            -> mixpanelyst
```

---

## Out of scope here

- Any library change — that is feature 047-behaviors-metrics-formulas (the CRUD this skill calls).
- Dashboards — dashboard-expert.
- Lexicon hide / annotate / tag — data-clean-up.
- Raw ad-hoc querying — mixpanelyst.
