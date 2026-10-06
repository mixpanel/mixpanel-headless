# Managing Mixpanel entities: rules the method list does not tell you

This file covers the rules for creating, updating, and deleting Mixpanel entities (dashboards, reports, cohorts, saved metrics, saved behaviors, feature flags, experiments, alerts, annotations, webhooks, Lexicon and other data governance objects) through the App API.

## Find the methods

List one area at a time. `mp help` alone prints every domain name.

```text
mp help Workspace --domain "dashboards"
mp help Workspace --domain "reports"          # saved reports are "bookmarks" in method names
mp help Workspace --domain "cohorts"
mp help Workspace --domain "saved metrics"
mp help Workspace --domain "saved behaviors"
mp help Workspace --domain "feature flags"
mp help Workspace --domain "experiments"
mp help Workspace --domain "alerts"
mp help Workspace --domain "annotations"
mp help Workspace --domain "webhooks"
mp help Workspace --domain "lexicon governance"
mp help Workspace --domain "custom properties"
mp help Workspace --domain "custom events"
mp help Workspace --domain "lookup tables"
mp help Workspace --domain "drop filters"
mp help Workspace --domain "schema registry"
mp help Workspace --domain "deletion requests"
mp help search bulk                           # every bulk method
```

Other data governance domains: `lexicon schemas`, `schema enforcement`, `data audit`, `volume anomalies`, `tracking and history`. Then read one method with `mp help Workspace.<method>` and its params type (for example `mp help CreateDashboardParams`) before you call it.

## Entity methods are workspace-scoped

App API entity methods run against one workspace (a data view) in the project. If you do not set one, the library picks one on the first call: the global view first, then "All Project Data", then the default view. If it cannot find one, it raises `WorkspaceScopeError`. Saved metrics and saved behaviors are the exception: they belong to the project, so a workspace does not change them.

When the project has several workspaces and the user means a specific one, pin it first: `ws.use(workspace=<id>)`, or set `MP_WORKSPACE_ID`. `ws.workspaces()` lists them, and `ws.resolve_workspace_id()` shows the one in use. A wrong workspace puts the entity where the user will not find it.

## Rules

- **To share a query, make a report link, not a saved report.** `ws.create_report_link(result)` gives a URL and saves nothing that the user must clean up.
- **A saved report needs a dashboard.** `create_bookmark()` raises before any request if `CreateBookmarkParams.dashboard_id` is not set. Build the report JSON with the matching `ws.build_*_params()` method, or reuse `result.params` from a query.
- **Some updates replace the whole object.** `update_feature_flag()` is a full replacement (PUT): send the complete configuration, not only the changed fields. Read the method's docstring to see if an update merges or replaces.
- **Deletes are immediate.** A delete sends the request at once, and the library asks no question. Before any delete, bulk delete, or bulk update, list the exact objects that will change, show the list to the user, and get a confirmation.
- **Duplicate is a server-side copy.** `duplicate_feature_flag()` and `duplicate_experiment()` create a new object. `duplicate_experiment()` needs a `name` in `DuplicateExperimentParams`, because the API returns an empty body without one. Read the copy back (`get_*`) and check it before you enable or launch it.
- **Data deletion requests are permanent in effect.** Use `preview_deletion_filters()` first, and make sure that the user understands the scope.
- **Check before you create.** Search the existing entities (`list_*`) first, so that you do not create a duplicate with the same name.

## Saved metrics and saved behaviors

A saved metric is the team's definition of a number, and reports, boards, alerts, and experiments use it by id. So a change to it reaches every report that uses it.

- **Search before you create.** A second active metric with the same name fails with a 409. To save a metric that you already query inline, pass the same `Metric`, `Formula`, `FunnelMetric`, or `RetentionMetric` value as the definition, so that the saved metric gives the same numbers.
- **A new metric is private.** In a project with sharing on, a metric that `create_metric` makes is visible only to its creator, and the API cannot share it. Tell the user to share it in Mixpanel.
- **Set `verified` only when the user asks.** It marks the metric as the team's trusted definition.
- **An owner or a verified flag goes in a second request.** If that request fails, the metric exists without them, and the error code is `CREATE_FOLLOW_UP_FAILED`. Its `details["metric_id"]` names the new metric: set the values with `update_metric`, or delete the metric.
- **A new definition replaces the stored one in full.** The library reads the metric first and keeps its display and goals, but an edit in Mixpanel between the read and the write is lost. Show the user the old and the new definition before you update. A change of kind (for example from a metric to a formula) is refused.
- **To copy a metric, create from `to_raw_definition()`.** `ws.create_metric(mp.CreateMetricParams(name="...", definition=source.to_raw_definition()))` keeps the kind and, for a warehouse metric, the warehouse source.
- **The library refuses to delete a row that the account cannot edit.** A superadmin's delete would remove another user's metric, so the library checks `can_update_basic` first. Pass `force=True` only when the user confirms that they mean to delete another user's metric or behavior.
- **A delete breaks the links.** Reports that use a deleted metric keep a copy of its definition but stop following it. The bulk deletes skip unknown ids with no error, so list the rows again after a bulk delete.
