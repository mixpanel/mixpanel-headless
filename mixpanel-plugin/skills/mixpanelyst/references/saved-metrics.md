# Saved metrics and saved behaviors: use the team's definitions

This file covers how to find a project's saved metrics and saved behaviors, how to query them by reference, and when to build a metric inline instead. For creates, updates, and deletes, read the entity rules that the skill links.

**Contents**

- [Saved first, inline second](#saved-first-inline-second)
- [Find the saved metrics](#find-the-saved-metrics)
- [Read the definition before you trust the name](#read-the-definition-before-you-trust-the-name)
- [Query a saved metric by reference](#query-a-saved-metric-by-reference)
- [Saved behaviors in funnels and retention](#saved-behaviors-in-funnels-and-retention)
- [Formulas over saved metrics](#formulas-over-saved-metrics)
- [Rules that change a result](#rules-that-change-a-result)

Look up the exact names first:

```text
mp help Workspace --domain "saved metrics"
mp help Workspace --domain "saved behaviors"
mp help SavedMetric
mp help MetricRef
mp help BehaviorRef
```

## Saved first, inline second

A saved metric is the team's agreed definition of a number: the events, the filters, and the math, often with an owner and a verified flag. Reports, boards, alerts, and experiments in Mixpanel use it by id. When the user asks for a business number such as activation, conversion, revenue, or active users, look for a saved metric first. Reason: an inline rebuild can differ in one filter or one math setting, and then your number does not match the number that the team sees in Mixpanel.

1. Search the saved metrics by name. Prefer a verified metric.
2. Read the definition of each candidate, and confirm that it answers the question.
3. Query the metric by reference. Tell the user which saved metric you used, by name and id.
4. If no saved metric fits, build the metric inline, and say that the project has no saved definition for it.

Build inline when the user gives their own definition, or asks how a different definition changes the number.

## Find the saved metrics

`ws.list_metrics()` fetches every saved metric of the project in one request. Its filter arguments apply locally to that response. On a large project the request can take more than 30 seconds, so call it once per script and reuse the list.

```python
import mixpanel_headless as mp

ws = mp.Workspace()

candidates = ws.list_metrics(name_contains="activation", viewable_only=True)
for m in sorted(candidates, key=lambda m: not m.verified):
    print(m.id, m.type, m.verified, m.name, m.math)
```

- Without `viewable_only=True`, the list also holds metrics that the account cannot view (`can_view` is false).
- `type` names the kind: `metric` (what users did plus how to count it), `formula`, or `warehouse` (SQL against a warehouse source).
- When several metrics match, show the candidates to the user and ask which one they mean. Do not pick one by name alone.

`ws.list_behaviors()` finds saved behaviors the same way.

## Read the definition before you trust the name

A name says what the owner meant, not what the metric counts. Check the definition before you report a number from it:

```python
m = ws.get_metric(88999)      # use a real id from the list
print(m.type, m.behavior_type, m.math, m.formula_expression)
print(m.definition)           # the stored definition
```

- `math` says what the metric counts: people (`unique`), events (`total`), or a property value.
- `behavior_type` says what users did, for example one event (`event`), any of several events (`simple`), a funnel, or a retention pair.
- For a formula, `formula_expression` and `referenced_metric_ids` name the operands.
- In your answer, say which metric you used and what it counts.

## Query a saved metric by reference

Pass the `SavedMetric` to `ws.query()` wherever a `Metric` goes. When you know the id only, pass `mp.MetricRef(<id>)`.

```python
activation = ws.get_metric(88999)     # use a real id
weekly = ws.query(activation, last=56, unit="week")
print(weekly.df)

# A report-level change for this query only (an override)
first_time = ws.query(activation.to_ref(segment_method="first"), group_by="$os", last=56)
```

- An override changes the saved definition for one query only. Run `mp help MetricRef` for the list of overrides.
- A filter is not an override. To narrow a saved metric, use report-level `where=`, which applies to every metric in the query. Or build the metric inline with its own `filters`.
- The series takes the saved name, with no math suffix such as `[Total Events]`.
- A report link made from the result keeps the reference, so the link follows later edits to the saved metric, as a report in Mixpanel does. Tell the user this when you share it.

## Saved behaviors in funnels and retention

A saved behavior is a reusable "what users did" with no counting rule: a funnel, a retention pair, or a group of events. Pass a saved funnel behavior to `ws.query_funnel()` in place of the steps, and a saved retention behavior to `ws.query_retention()` in place of the events:

```python
checkout = ws.get_behavior(3120)      # a saved funnel behavior; use a real id
result = ws.query_funnel(checkout, last=90)
```

The saved behavior owns its steps, window, and order. So leave the engine arguments that change them, such as `conversion_window` or `retention_unit`, at their defaults. A funnel query needs a `funnel` behavior, and a retention query needs a `retention` behavior.

## Formulas over saved metrics

`mp.Formula(expression, metrics=[...])` holds its own operands, so a ratio of two saved metrics is one query:

```python
ratio = ws.query(
    mp.Formula(
        "A / B",
        label="Purchases per signup",
        metrics=[mp.MetricRef(88999), mp.MetricRef(89001)],
    )
)
```

An operand takes no override. An operand cannot be a saved formula or a warehouse metric, because the server accepts only behavior metrics as operands.

## Rules that change a result

- **A warehouse metric runs only by saved id, with no breakdown and no filter.** A query that pairs it with `group_by` or `where` still runs, but the warehouse series ignores them. The library logs a warning.
- **A legacy row (`type` is `behavior`) does not run by reference.** Read its definition, and build the metric inline.
- **Saved metrics belong to the project, not to a workspace.** A pinned workspace does not change the list. An OAuth token needs the `metrics` and `behaviors` scopes.
