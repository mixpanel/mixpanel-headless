# Saved Metrics and Behaviors

List, read, create, update, and delete the saved metrics and saved behaviors of a Mixpanel project, from Python and from the `mp metrics` and `mp behaviors` CLI groups.

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

## Create

A saved metric takes its kind from its definition; you never write the wire `type`:

| Definition value | Kind |
|---|---|
| `mp.Metric(...)`, including a list of events or a `SimpleBehavior` | `metric` (the `behavior` and `measurement` of its show clause) |
| `mp.CohortMetric(...)` | `metric` (a cohort size metric) |
| `mp.FunnelMetric(...)`, `mp.RetentionMetric(...)` | `metric` (a funnel or retention measurement; the behavior can be a `BehaviorRef`) |
| `mp.Formula(expression, metrics=[...])` | `formula` (the operands are saved inside it; a `MetricRef` operand stays a reference) |
| `mp.WarehouseMetric(source_id, sql, metric_type, ...)` | `warehouse` |
| `mp.RawMetricDefinition(kind, definition, warehouse_source_id=None)` | the kind it names |

The typed values go through the same builders as `ws.query()`, so a saved metric queries the same way as its inline twin. A `Formula` without `metrics` names the other metrics of a query by letter, so it cannot be saved (`SM7_FORMULA_WITHOUT_OPERANDS`). `RawMetricDefinition` takes a wire definition dict, for example the `definition` of a metric that `get_metric` returned; `SavedMetric.to_raw_definition()` builds that value with the kind and, for a warehouse metric, the source. Use it for shapes that no typed value covers, such as profile metrics.

A saved behavior takes a `SimpleBehavior`, a `FunnelBehavior`, a `RetentionBehavior`, or a `RawBehaviorDefinition`; its wire type comes from the value. The saved definition never holds a `name`: the saved behavior's own name labels it.

=== "Python"

    ```python
    from datetime import date

    # Promote an inline metric to a saved metric
    saved = ws.create_metric(mp.CreateMetricParams(
        name="Weekly buyers",
        definition=mp.Metric("Purchase", math="unique"),
        description="Unique users who bought.",
        display=mp.MetricDisplay(suffix=" users", precision=0),
        goals=[mp.MetricGoal(label="Q4", checkpoints=[(date(2026, 12, 31), 5000)])],
        owned_by=12345,        # user id
        verified=True,
    ))

    # A saved formula over an inline metric and a saved metric
    ws.create_metric(mp.CreateMetricParams(
        name="Purchases per signup",
        definition=mp.Formula(
            "A / B",
            metrics=[mp.Metric("Purchase", math="unique"), mp.MetricRef(104700)],
        ),
    ))

    # A funnel metric
    ws.create_metric(mp.CreateMetricParams(
        name="Checkout conversion",
        definition=mp.FunnelMetric(mp.FunnelBehavior(["View Cart", "Purchase"])),
    ))

    # A warehouse metric (the source id is in the project's warehouse sources)
    ws.create_metric(mp.CreateMetricParams(
        name="Daily revenue",
        definition=mp.WarehouseMetric(
            55, "SELECT day, revenue FROM finance.daily_revenue", "timeseries",
            time_column="day", value_column="revenue",
            aggregation="last_value", sync_interval="daily",
        ),
    ))

    # Copy a metric: read it, then create from its stored definition.
    # to_raw_definition() carries the kind and, for a warehouse metric, the
    # source that the server keeps outside the definition.
    source = ws.get_metric(118228)
    ws.create_metric(mp.CreateMetricParams(
        name=f"{source.name} (copy)",
        definition=source.to_raw_definition(),
    ))

    # A saved behavior, then a funnel metric over it
    checkout = ws.create_behavior(mp.CreateBehaviorParams(
        name="Checkout",
        behavior=mp.FunnelBehavior(["View Cart", "Checkout", "Purchase"], conversion_window=7),
    ))
    ws.create_metric(mp.CreateMetricParams(
        name="Checkout conversion (saved funnel)",
        definition=mp.FunnelMetric(checkout.to_ref()),
    ))
    ```

=== "CLI"

    ```bash
    # The definition file is the `definition` object that `get` prints
    mp metrics get 118228 --jq .definition > definition.json
    mp metrics create --name "Signup conversion (copy)" --definition-file definition.json

    # A warehouse metric keeps its source outside the definition: pass it again
    mp metrics get 120001 --jq .definition > wh.json
    mp metrics create --name "Daily revenue (copy)" --definition-file wh.json \
        --warehouse-source-id "$(mp metrics get 120001 --jq .warehouse_source_id)"

    # --kind is inferred (formula block, then query, then metric); stdin works too
    cat definition.json | mp metrics create --name "From stdin" --definition-file -
    mp metrics create --name "Revenue" --definition-file wh.json --warehouse-source-id 55 \
        --owner-id 12345 --verified

    mp behaviors get 3001 --jq .definition | mp behaviors create --name "Checkout (copy)" --definition-file -
    ```

`owned_by` and `verified` go in a second request, because the server drops them from a create. The two requests are not atomic: if the second one fails, the metric exists without the owner or the verified flag, the log names its id, and the error propagates. `verified=False` sends nothing, because a new metric is unverified.

## Update

The server checks a create against its JSON Schema, but it stores an update as sent, with no check. So `update_metric` and `update_behavior` run the same client-side checks as the create methods before any request (see [What the library checks](#what-the-library-checks)).

=== "Python"

    ```python
    # Metadata: one request, no read
    ws.update_metric(104700, mp.UpdateMetricParams(description="Unique buyers per week."))

    # Presentation: reads the metric, then sends its full definition with the change
    ws.update_metric(104700, mp.UpdateMetricParams(display=mp.MetricDisplay(precision=1)))
    ws.update_metric(104700, mp.UpdateMetricParams(goals=[]))   # remove the goals

    # A new definition: reads the metric first and refuses a change of kind
    ws.update_metric(104700, mp.UpdateMetricParams(
        definition=mp.Metric("Purchase", math="unique", segment_method="first"),
    ))

    # Owner and verified
    ws.update_metric(104700, mp.UpdateMetricParams(owned_by=12345, verified=True))

    # Verify many metrics in one request
    ws.bulk_update_metrics([mp.BulkUpdateMetricEntry(id=i, verified=True) for i in (1, 2, 3)])

    ws.update_behavior(3001, mp.UpdateBehaviorParams(verified=True))
    ```

=== "CLI"

    ```bash
    mp metrics update 104700 --description "Unique buyers per week." --verified
    mp metrics get 104700 --jq .definition > definition.json   # edit, then:
    mp metrics update 104700 --definition-file definition.json
    mp metrics verify 1 2 3                  # --unverify clears the flag
    mp behaviors update 3001 --name "Checkout v2" --no-verified
    ```

A new definition replaces the stored one in full, because that is what the server does. It keeps the stored `display` and `goals` unless the params or the new definition set them. The read and the update are not atomic: an edit in the web app between them is overwritten. A failed read raises; the library never guesses the stored definition.

`bulk_update_metrics` reads each metric that gets a new definition, then sends one request. The server skips ids that do not name a metric of the project, with no error; `mp metrics verify` names the skipped ids on stderr.

`verified=True` stamps the verification time again on each call; `verified=False` clears the flag. An owner cannot be removed once set.

## Run a saved metric

`ws.query()` runs a saved metric by reference (see [Query by reference](#query-by-reference)). From the shell, `mp metrics query ID` reads the metric to learn its kind, then runs it:

```bash
mp metrics query 104700 --from 2024-09-01 --to 2024-09-30 --unit week
mp metrics query 104700 --last 90 --group-by '$os' --format table
```

A `WarehouseMetric` is a definition, not a query value: the server runs warehouse SQL only by saved id, so `ws.query()` refuses it (`MR3_WAREHOUSE_INLINE`). Save it with `create_metric`, then query the reference.

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

In a project with sharing on, a metric or behavior that someone creates is private to its creator until they share it. The create API cannot set sharing, so a metric that `create_metric` makes is private to the account that made it; share it in the web app. The permission flags on each row tell you what the caller can do:

| Field | Meaning |
|---|---|
| `can_view` | The caller can view the row |
| `can_update_basic` | The caller can edit the name and definition |
| `can_share` | The caller can share the row |
| `is_visible` | The row is visible to the caller |
| `is_locked` | The row is locked against edits |

Projects without sharing add more flags (for example `can_update_restricted`). The models keep them as unknown keys: read them with `metric.model_extra`.

## What the library checks

The server has several traps. The write methods handle them before any request, with a registry code on each refusal (`ParamValidationError.code`):

| Code | Rule |
|---|---|
| `SM1_EMPTY_NAME` | The name is not empty (names are stripped). |
| `SM2_NAME_TOO_LONG` | The name and the description have at most 255 characters. The server fails with a 500 on a longer value. |
| `SM3_KIND_CHANGE` | A new definition keeps the kind of the stored metric (or the type of the stored behavior) and the warehouse source. The server ignores a new kind but stores the new definition, which would leave a definition that does not match its kind. |
| `SM4_SCHEMA` | The definition passes a mirror of the server's POST schema. The error names the field path, because the server's own 400 message can name the wrong cause. On a create it also refuses the legacy keys (for example a behavior's `filter`) that the server reads past at query time but leaves out of its create schema. This applies to every definition, raw or compiled from a typed value. An update sends them as given, because stored definitions carry them. `validate=False` (CLI: `--no-validate`) skips this check, the legacy-key refusal included; the server then answers a failing create with a 400. |
| `SM7_FORMULA_WITHOUT_OPERANDS` | A saved formula holds its own operands (`Formula(expression, metrics=[...])`). |
| `FM6_OPERAND_ATTRIBUTION` | No operand of a saved formula sets a segment method or an attribution model. The query engine drops or rejects them, and the web app refuses to save such a formula. Set attribution on the formula's own measurement instead. |

Other traps the library handles for you:

- `owned_by` and `verified` are dropped by a create, so the library sends them in a second request.
- The server answers every get, create, and update with a map keyed by id; the library unwraps it.
- A warehouse definition always holds `aggregation` and `syncInterval`, because the server stores the request as sent and fills in no defaults.
- A behavior description is omitted when it is `None`, because the behavior schema does not accept `null`.
- The saved definition of a typed value holds no legacy behavior `filter` key, although the query builders write one for funnel and retention behaviors. The server reads past it at query time, and a create rejects it.

Server errors keep the library-wide mapping: a duplicate active name gives `QueryError` with `status_code == 409`; the pricing-plan gate ("Cannot save metric with your current plan") and a missing permission give 403, whose body can have an empty error. A create that the server's schema refuses gives `QueryError` with `status_code == 400`. The server's text holds an HTML-escaped copy of the whole request, so the library shortens the message to the failure and its schema location, and keeps the full body in `QueryError.response_body`. The CLI prints only the short message, because the server's copy of the request can hold a warehouse metric's SQL. For the same reason, no error of an `mp metrics` or `mp behaviors` write command prints the request params or body; `QueryError.request_body` keeps them for Python callers.

## Open reads

`SavedMetric` and `SavedBehavior` accept any `type`, any `math`, and keys that they do not model, because stored rows include shapes that no strict model accepts: legacy kinds, deprecated display and goal keys (`chartType`, goal `unit` and `direction`), and maths outside the documented list. `model_dump()` returns every key the server sent. The typed accessors return `None` or an empty list for a shape they do not know.

## Next Steps

- [API Reference — Workspace](../api/workspace.md) — Method signatures and docstrings
- [API Reference — Types](../api/types.md) — `SavedMetric`, `SavedBehavior`, the create and update params, `WarehouseMetric`, `RawMetricDefinition`, `RawBehaviorDefinition`, `MetricDisplay`, `MetricGoal`
- [Insights Queries](query.md) — Inline metrics, formulas, and saved metrics by reference
- [Entity Management](entity-management.md) — Dashboards, reports, cohorts, and other entities
