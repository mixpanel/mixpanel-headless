# Quickstart: Behaviors, Metrics & Formulas

**Feature**: 047-behaviors-metrics-formulas
**Audience**: New users of the semantic-layer bindings; reviewers smoke-testing before merge.

This walkthrough exercises every user story (US1–US3) from spec.md. Treat it as the merge-gate recipe.

---

### US1 — Create and manage a metric

```python
import mixpanel_headless as mp
from mixpanel_headless import (
    CreateMetricParams, UpdateMetricParams, MeasurementProperty, BehaviorStep,
)

ws = mp.Workspace.use(account="acme-corp", project=3713224)

# Property-aggregation metric: Average Order Value
aov = ws.create_metric(CreateMetricParams(
    name="Average Order Value",
    description="Mean purchase amount per order.",
    math="average",
    property=MeasurementProperty(name="amount", type="number", resource_type="events"),
    steps=[BehaviorStep(name="purchase")],
))
print(aov.id, aov.name)

# Plain count metric: omit property
dau = ws.create_metric(CreateMetricParams(
    name="Daily Active Users",
    math="dau",
    steps=[BehaviorStep(name="$mp_anything_event")],
))

# Read / update / delete
fetched = ws.get_metric(aov.id)
ws.update_metric(aov.id, UpdateMetricParams(name="AOV"))
ws.delete_metric(aov.id)
assert aov.id not in {m.id for m in ws.list_metrics()}
```

**Validation refusals (no HTTP):**

```python
# Bad math enum
CreateMetricParams(name="x", math="avg", steps=[BehaviorStep(name="purchase")])
# raises ValidationError: "avg" is not valid; did you mean "average"?

# Bare-string property
CreateMetricParams(name="x", math="average", property="amount",
                   steps=[BehaviorStep(name="purchase")])
# raises ValidationError: property must be a MeasurementProperty object, not a string

# Property-aggregation without property
CreateMetricParams(name="x", math="sum", steps=[BehaviorStep(name="purchase")])
# raises ValidationError: math="sum" requires a property object
```

### US2 — Create and manage behaviors

```python
from mixpanel_headless import CreateBehaviorParams, BehaviorStep

# Simple (OR over events)
ws.create_behavior(CreateBehaviorParams(
    name="Shopping Activity", type="simple",
    steps=[BehaviorStep(name="view product"), BehaviorStep(name="add to cart")],
))

# Funnel (>= 2 steps, loose|any only)
ws.create_behavior(CreateBehaviorParams(
    name="Checkout Funnel", type="funnel", funnel_order="loose",
    conversion_window_unit="day", conversion_window_duration=7,
    steps=[BehaviorStep(name="view cart"), BehaviorStep(name="checkout"),
           BehaviorStep(name="purchase")],
))

# Retention (EXACTLY 2 steps: born + return)
ws.create_behavior(CreateBehaviorParams(
    name="Weekly Retention", type="retention", retention_unit="day",
    steps=[BehaviorStep(name="$mp_anything_event"),
           BehaviorStep(name="$mp_anything_event")],
))
```

**Validation refusals (no HTTP):**

```python
CreateBehaviorParams(name="x", type="funnel", steps=[BehaviorStep(name="a")])
# raises ValidationError: funnel behaviors require >= 2 steps

CreateBehaviorParams(name="x", type="retention",
                     steps=[BehaviorStep(name="a"), BehaviorStep(name="b"), BehaviorStep(name="c")])
# raises ValidationError: retention behaviors require EXACTLY 2 steps

CreateBehaviorParams(name="x", type="funnel", funnel_order="strict",
                     steps=[BehaviorStep(name="a"), BehaviorStep(name="b")])
# raises ValidationError: funnel_order must be "loose" or "any"
```

### US3 — Create and manage formulas

```python
from mixpanel_headless import CreateFormulaParams, ReferencedMetric

eng = ws.create_formula(CreateFormulaParams(
    name="Engagement Rate",
    description="Active users as a percentage of total users.",
    definition="(A / B) * 100",
    referenced_metrics=[
        ReferencedMetric(name="user session", math="unique"),   # A
        ReferencedMetric(name="signup", math="unique"),         # B
    ],
))
print(eng.id, eng.definition)
ws.delete_formula(eng.id)
```

**Validation refusals (no HTTP):**

```python
CreateFormulaParams(name="x", definition="(A / B) * 100",
                    referenced_metrics=[ReferencedMetric(name="a", math="unique")])
# raises ValidationError: definition uses 2 variables but 1 referenced_metric given

CreateFormulaParams(name="x", definition="(A / C) * 100",
                    referenced_metrics=[ReferencedMetric(name="a", math="unique"),
                                        ReferencedMetric(name="b", math="unique")])
# raises ValidationError: variables must be contiguous from A (got A, C)
```

### help.py discovery (no manual edits)

```bash
python help.py Workspace.create_metric     # signature + docstring + referenced types
python help.py CreateBehaviorParams         # fields + construction patterns
python help.py Formula                       # result type fields
python help.py search behavior               # fuzzy search across the new surface
```

---

## Smoke-test script (merge gate)

```bash
# Smoke test (after the bindings land)
uv run python -c "
import mixpanel_headless as mp
from mixpanel_headless import CreateMetricParams, MeasurementProperty, BehaviorStep
ws = mp.Workspace.use()
m = ws.create_metric(CreateMetricParams(
    name='smoke AOV', math='average',
    property=MeasurementProperty(name='amount', type='number', resource_type='events'),
    steps=[BehaviorStep(name='purchase')]))
assert m.id
assert ws.get_metric(m.id).name == 'smoke AOV'
ws.delete_metric(m.id)
print('OK: metric round-trip')
"

# Validation gate (no HTTP)
uv run python -c "
from mixpanel_headless import CreateMetricParams, BehaviorStep
try:
    CreateMetricParams(name='x', math='avg', steps=[BehaviorStep(name='purchase')])
    print('LEAK: bad math accepted'); raise SystemExit(1)
except Exception:
    print('OK: bad math refused at construction time')
"
```

---

## Performance verification

| Operation | Target | Measurement |
|-----------|--------|-------------|
| `create_metric` / `create_behavior` / `create_formula` | 1 round-trip | single POST |
| `list_*` (paginated) | linear in pages | cursor pagination helper |
| param-model validation | < 1 ms, 0 round-trips | construction-time only |

---

## Downstream consumer

The metric-maker skill (feature 048) is the first consumer of this surface — it calls `create_behavior` / `create_metric` / `create_formula` to assemble starter kits. That skill ships as a separate PR after this feature merges; nothing here depends on it.
