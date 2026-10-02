# Saved Metrics and Behaviors

List, read, and delete the saved metrics and saved behaviors of a Mixpanel project, from Python and from the `mp metrics` and `mp behaviors` CLI groups.

!!! info "Saved versus inline"
    A **saved metric** is a project entity: it has a numeric id, a name, an optional owner, a verified flag, and goals. The web app uses it by reference in Insights, Funnels, Retention, Experiments, Metric Trees, alerts, and boards, so a change to the saved metric reaches every report that refers to it.

    The query types `mp.Metric`, `mp.Formula`, and `mp.CohortMetric` are **inline** values: they exist only for the duration of one query and have no id. This page covers the saved entities.

!!! note "Prerequisites"
    Saved metrics and saved behaviors require **authentication** (service account or OAuth). Both collections are **project-scoped**: they do not need a workspace ID, and a pinned workspace does not change which rows you see. An OAuth token needs the `metrics` and `behaviors` scopes.

## The three metric kinds

One server collection holds three kinds of saved metric. `SavedMetric.type` names the kind:

| `type` | Kind | Definition shape |
|---|---|---|
| `metric` | Behavior metric: what users did plus how to count it | `{behavior, measurement, display?, goals?}` |
| `formula` | Saved formula over other metrics | `{formula: {definition, referencedMetrics}, measurement?, display?, goals?}` |
| `warehouse` | Warehouse metric: a SQL query against a warehouse source | `{query, metricType, aggregation?, syncInterval?, ...}` |

Old rows can have `type: "behavior"`. The library parses every row, whatever its `type`, and keeps keys that it does not model (see [Open reads](#open-reads)).

A behavior metric's `behavior.type` can be `event`, `simple` (more than one event), `funnel`, `retention`, `cohort`, or `people`. A formula's operands can be inline metrics or references to other saved metrics, written `{"type": "metric", "id": N}`.

## The three behavior types

A **saved behavior** is a reusable "what users did" with no counting rule. It lives in a separate collection, with its own permissions. `SavedBehavior.type` names the type:

| `type` | What it describes |
|---|---|
| `simple` | One or more events, with optional filters |
| `funnel` | Ordered steps, a conversion window, exclusions |
| `retention` | A born event and a returning event |

The definition of a saved behavior holds one key, `behavior`, in the show-clause shape of the web app.

## List

The server has no pagination, no filters, and no search. One request fetches every active row, and the filter arguments apply locally to that response. On a large project the request can take more than 30 seconds, so the list calls use a read timeout of at least 120 seconds.

=== "Python"

    ```python
    import mixpanel_headless as mp

    ws = mp.Workspace()

    # Every saved metric, all kinds
    metrics = ws.list_metrics()

    # Local filters
    formulas = ws.list_metrics(metric_type="formula")
    governed = ws.list_metrics(verified=True)
    revenue = ws.list_metrics(name_contains="revenue")        # case-insensitive
    mine = ws.list_metrics(viewable_only=True)                # drop can_view false

    for m in governed:
        print(m.id, m.type, m.name, m.math, m.owned_by)

    # Saved behaviors
    funnels = ws.list_behaviors(behavior_type="funnel")
    checkout = ws.list_behaviors(name_contains="checkout")
    ```

=== "CLI"

    ```bash
    mp metrics list
    mp metrics list --type formula
    mp metrics list --verified              # --no-verified for unverified only
    mp metrics list --name-contains revenue --viewable-only
    mp metrics list --format table          # id, name, type, verified, can_view, modified

    mp behaviors list --type funnel
    mp behaviors list --name-contains checkout --format table
    ```

!!! warning "The list includes metrics that you cannot view"
    The server returns every active metric of the project, also the ones that the caller cannot view, and it sends their full definitions. For those rows `SavedMetric.can_view` is `False`. `list_metrics()` returns what the server returns; pass `viewable_only=True` (CLI: `--viewable-only`) for the web app's view.

## Get

=== "Python"

    ```python
    metric = ws.get_metric(104700)
    metric.type                  # "metric", "formula", or "warehouse"
    metric.definition            # the stored definition, as a dict

    # Typed accessors (None or [] for a shape they do not know; they never raise)
    metric.behavior_type         # "event", "simple", "funnel", ...
    metric.math                  # "unique", "total", "sessions", ...
    metric.formula_expression    # "A / B * 100" for a saved formula
    metric.referenced_metric_ids # saved metrics that a formula uses by id
    metric.display               # MetricDisplay: prefix, suffix, precision, ...
    metric.goals                 # list[MetricGoal]

    behavior = ws.get_behavior(3001)
    behavior.behavior_type       # "funnel"
    behavior.definition["behavior"]
    ```

=== "CLI"

    ```bash
    mp metrics get 104700
    mp metrics get 104700 --jq '.definition'
    mp behaviors get 3001
    ```

`get_metric` raises `QueryError` with `status_code == 404` for an unknown or deleted id. The server does not answer an unknown behavior id with 404: `get_behavior` raises `ServerError` (500) instead.

## Query by reference

A saved metric runs in a query by id. Pass a `SavedMetric` to `ws.query()` or `ws.build_params()` anywhere a `Metric` goes, or pass the reference it makes with `to_ref()`:

```python
import mixpanel_headless as mp

# The verified metrics of the project, side by side
verified = ws.list_metrics(verified=True)
result = ws.query(verified[:3], from_date="2026-09-01", to_date="2026-09-28")

# One metric with a report-level change (an override)
signup_rate = ws.get_metric(88999)
result = ws.query(signup_rate.to_ref(segment_method="first"), group_by="$os")

# A reference by id alone, without reading the metric first
result = ws.query(mp.MetricRef(88999), last=30)
```

The params keep the reference as `{"type": ..., "id": ..., "overrides": ...}`. The server replaces it with the saved definition at query time. So a report or a report link built from the params follows later edits to the saved metric, as a report built in the web app does.

The keyword arguments of `to_ref()` are the typed overrides of `MetricRef` (`label`, `math`, `property`, `per_user`, `percentile_value`, `segment_method`, `funnel_order`, `step_index`, `bucket_index`, `hidden`, and a raw `overrides` dict). They change the saved definition for one query only. Filters are not an override: the server merges override lists item by item, so the library refuses a `filters` override (`MR1_FILTER_OVERRIDE`). Use report-level `where=` instead, or send the metric inline. A legacy row (`type: "behavior"`) does not run by reference (`MR5_INVALID_TYPE`).

A saved behavior runs in the funnel and retention engines in place of the steps or the events:

```python
checkout = ws.get_behavior(3120)                 # a saved funnel behavior
result = ws.query_funnel(checkout, last=90)       # or checkout.to_ref()

onboarding = ws.get_behavior(4410)               # a saved retention behavior
result = ws.query_retention(onboarding)
```

The saved behavior owns its steps and settings, so the engine arguments that change them (for example `conversion_window` or `retention_unit`) must keep their defaults. The engines check the behavior type: a funnel query needs a `funnel` behavior, and a retention query needs a `retention` behavior.

Saved behaviors and saved metrics also work inside inline values. A `BehaviorRef` is the behavior of a `Metric` (type `simple`), a `FunnelMetric` (type `funnel`), or a `RetentionMetric` (type `retention`); another type raises `BH5_BEHAVIOR_REF_TYPE`. A `MetricRef` is an operand of a `Formula` that holds its own operands:

```python
# A saved funnel as one metric, next to an event
result = ws.query([
    mp.Metric("Checkout", math="unique"),
    mp.FunnelMetric(mp.BehaviorRef(3120, "funnel"), label="Checkout conversion"),
])

# A ratio of two saved metrics
result = ws.query(
    mp.Formula("A / B", label="Ratio", metrics=[mp.MetricRef(88999), mp.MetricRef(89001)])
)
```

A `MetricRef` operand takes no override: the server ignores overrides on an operand, so the library refuses them (`MR2_OPERAND_OVERRIDE`). A saved formula is not an operand (`FM3_NESTED_FORMULA`), and neither is a warehouse metric (`FM7_WAREHOUSE_OPERAND`): the server accepts only behavior metrics as operands, so run a warehouse metric alone by reference.

A reference changes the result labels: the series takes the saved name, with no math suffix such as `[Total Events]`. See [Insights Queries — Saved Metrics by Reference](query.md#saved-metrics-by-reference) for the override table, warehouse metrics, and every rule.

## Delete

The server's single-metric delete route answers 501, and its single-behavior delete route skips the permission check. So the library deletes through the **bulk** routes only. A delete is a soft delete on the server: the row leaves the lists, and reports that refer to it keep a copy of the definition but lose the link.

The bulk routes skip ids that do not name an active row, with no error. The single-id methods read the entity first, so a typo in an id raises instead of passing silently:

| Method | Requests | Unknown id |
|---|---|---|
| `delete_metric(id)` | GET, then bulk DELETE | `ParamValidationError` with code `SM5_NOT_FOUND_FOR_DELETE`; nothing is deleted |
| `delete_metrics(ids)` | List read, then one bulk DELETE | Skipped by the server, no error |
| `delete_behavior(id)` | GET, then bulk DELETE | `ServerError` (the server answers the read with 500); nothing is deleted |
| `delete_behaviors(ids)` | List read, then one bulk DELETE | Skipped by the server, no error |

!!! warning "Superadmins can delete other users' metrics and behaviors"
    The server's bulk delete lets a project superadmin delete metrics and behaviors that other users own, even when the row's `can_update_basic` flag is false for that account. So the library refuses, before any delete, a target whose `can_update_basic` is false: `ParamValidationError` with code `SM6_DELETE_NOT_PERMITTED` (metrics) or `BH4_DELETE_NOT_PERMITTED` (behaviors). The single-id methods check the row they read; the bulk methods read the list once and refuse the whole request, naming every refused id. A row without the flag is not refused, and ids that the list does not hold are left to the server, which skips them. Pass `force=True` (CLI: `--force`) to delete anyway; `force` skips the list read of the bulk methods, and the single-id methods still read the row to confirm that it exists.

=== "Python"

    ```python
    ws.delete_metric(104700)
    ws.delete_metric(118228, force=True)    # a metric that another user owns

    stale = ws.list_metrics(name_contains="[old]")
    ws.delete_metrics([m.id for m in stale])

    ws.delete_behavior(3001)
    ws.delete_behaviors([3002, 3003])
    ```

=== "CLI"

    ```bash
    mp metrics delete 104700              # one id: read first, then delete
    mp metrics delete 104700 118228       # several ids: list read, then one bulk request
    mp metrics delete 118228 --force      # delete a metric that your account cannot edit
    mp behaviors delete 3001
    ```

The CLI does not ask for confirmation. It prints its message on stderr, so stdout stays empty for scripts.

A delete raises `QueryError` with `status_code == 403` when the caller cannot edit one of the rows. A warehouse metric also needs the warehouse-sources write permission.

## Sharing and visibility

In a project with sharing on, a metric or behavior that someone creates is private to its creator until they share it. The permission flags on each row tell you what the caller can do:

| Field | Meaning |
|---|---|
| `can_view` | The caller can view the row |
| `can_update_basic` | The caller can edit the name and definition |
| `can_share` | The caller can share the row |
| `is_visible` | The row is visible to the caller |
| `is_locked` | The row is locked against edits |

Projects without sharing add more flags (for example `can_update_restricted`). The models keep them as unknown keys: read them with `metric.model_extra`.

## Open reads

`SavedMetric` and `SavedBehavior` accept any `type`, any `math`, and keys that they do not model, because stored rows include shapes that no strict model accepts: legacy kinds, deprecated display and goal keys (`chartType`, goal `unit` and `direction`), and maths outside the documented list. `model_dump()` returns every key the server sent. The typed accessors return `None` or an empty list for a shape they do not know.

## Next Steps

- [API Reference — Workspace](../api/workspace.md) — Method signatures and docstrings
- [API Reference — Types](../api/types.md) — `SavedMetric`, `SavedBehavior`, `MetricDisplay`, `MetricGoal`
- [Insights Queries](query.md) — Inline metrics, formulas, and saved metrics by reference
- [Entity Management](entity-management.md) — Dashboards, reports, cohorts, and other entities
