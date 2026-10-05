# Changelog

All notable changes to `mixpanel-headless` are recorded here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver but is currently pre-1.0, so minor versions
may include API changes.

## Unreleased

### Added

- **Saved metrics and saved behaviors: list, read, and delete.**
  `Workspace.list_metrics(*, metric_type=None, verified=None,
  name_contains=None, viewable_only=False)`, `get_metric(metric_id)`,
  `delete_metric(metric_id)`, and `delete_metrics(metric_ids)` cover all
  three metric kinds (behavior metric, formula, warehouse metric), which
  the server keeps in one project-scoped collection.
  `list_behaviors(*, behavior_type=None, name_contains=None)`,
  `get_behavior(behavior_id)`, `delete_behavior(behavior_id)`, and
  `delete_behaviors(behavior_ids)` cover saved behaviors (simple, funnel,
  retention). The server has no pagination or filters, so the filter
  arguments apply locally to the one list response, and the list calls
  wait at least 120 seconds for it. `list_metrics()` returns the full
  server list by default, which includes metrics that the caller cannot
  view (`can_view` is `False`); `viewable_only=True` drops them.
- Deletes go through the bulk routes only: the single-metric delete route
  answers 501, and the single-behavior delete route skips the permission
  check. `delete_metric` and `delete_behavior` read the entity first, so
  an unknown id raises instead of passing silently. An unknown metric id
  raises `ParamValidationError` with the new code
  `SM5_NOT_FOUND_FOR_DELETE`; the server answers the read of an unknown
  behavior id with a 500 (`ServerError`). `delete_metrics` and
  `delete_behaviors` send one bulk request, and the server skips unknown
  ids.
- The server's bulk delete lets a project superadmin delete metrics and
  behaviors that other users own. The delete methods refuse, before any
  delete, a target whose `can_update_basic` flag is false for the caller:
  `ParamValidationError` with the new codes `SM6_DELETE_NOT_PERMITTED` and
  `BH4_DELETE_NOT_PERMITTED`. The bulk methods read the list once and
  refuse the whole request, naming every refused id. `force=True` (CLI:
  `--force`) deletes anyway.
- New result types `SavedMetric` and `SavedBehavior`, plus `MetricDisplay`
  and `MetricGoal`. Reads are open: any `type`, any `math`, and unknown
  keys parse and survive `model_dump()`. Typed accessors (`behavior_type`,
  `math`, `formula_expression`, `referenced_metric_ids`, `display`,
  `goals`) return `None` or an empty list for a shape they do not know,
  and never raise. `created_by`, `owned_by`, and `last_verified_by` reuse
  `CohortCreator`, which has the same `{id, name, email}` shape.
- CLI: `mp metrics list|get|delete` and `mp behaviors list|get|delete`.
  `list` takes `--type`, `--name-contains`, and, for metrics,
  `--verified/--no-verified` and `--viewable-only`; the table view shows
  `can_view`. `delete` takes one or more ids: one id reads first, several
  ids go in one bulk request. `delete` takes `--force` to pass the
  permission guard.
- `mp help` gains the "saved metrics" and "saved behaviors" domains, and a
  new guide page, "Saved Metrics and Behaviors".
- `MixpanelAPIClient.app_request` takes a per-call `timeout`.
- `MetricRef` queries a saved metric by id. `Workspace.query()` and
  `build_params()` accept it anywhere they accept a `Metric`. The params
  keep the reference (`{"type", "id", "overrides"}`), so the server expands
  the saved definition at query time, and a report or report link built
  from the params follows later edits to the saved metric. Typed fields
  (`label`, `math`, `property`, `per_user`, `percentile_value`,
  `segment_method`, `funnel_order`, `step_index`, `bucket_index`,
  `hidden`) become `overrides` at their wire paths, and a raw `overrides`
  dict merges last. A `filters` override is
  refused (`MR1_FILTER_OVERRIDE`), because the server merges override lists
  item by item; use report-level `where=` or an inline `Metric` instead.
  A `SavedMetric` works in the same places, and `SavedMetric.to_ref()`
  makes the reference with overrides. The typed fields follow the inline
  `Metric` rules where they contradict each other
  (`V3_PER_USER_INCOMPATIBLE`, `V14_METRIC_REJECTS_PROPERTY`); a field
  that the saved definition or the raw `overrides` can supply (a property,
  a per-user aggregation, a percentile value) is not required.
  `SavedMetric.to_ref(math="percentile")` without a percentile value in
  the arguments or the raw overrides is refused when the stored
  measurement has none (`V26_PERCENTILE_REQUIRES_VALUE`), because a saved
  metric holds its definition. The raw `overrides` are stored as a read-only
  copy.
- A query-level `math`, `math_property`, `per_user`, or `percentile_value`
  in a query that has saved-metric references and no plain event name is
  refused (`V29_QUERY_MEASUREMENT_IGNORED`): no event would use it. Set it
  on the reference, for example `MetricRef(id, math="unique")`.
- `BehaviorRef` runs a saved behavior by id. `query_funnel()` and
  `build_funnel_params()` take it in place of the step list, and
  `query_retention()` and `build_retention_params()` take it in place of
  the born and return events. A `SavedBehavior` works in the same places,
  and `SavedBehavior.to_ref()` makes the reference. The engines refuse a behavior of the wrong
  type (`F13_BEHAVIOR_REF_TYPE`, `R14_BEHAVIOR_REF_TYPE`) and any behavior
  setting that the saved behavior owns (`F14_BEHAVIOR_REF_SETTINGS`,
  `R15_BEHAVIOR_REF_SETTINGS`).
- A query that pairs a warehouse metric reference with `group_by` or
  `where` logs a `V28_WAREHOUSE_BREAKDOWN` warning: the server gives a
  warehouse metric no breakdown and no filter. The warning needs the
  warehouse kind on the reference (`MetricRef(id, type="warehouse")` or
  `SavedMetric.to_ref()`); a bare `MetricRef(id)` keeps the default kind.
- The bookmark validators accept saved-metric references: a show clause
  with an `id` and no `behavior`, a `type: "warehouse"` clause with an
  `id`, and formula operands in `referencedMetrics`. New codes:
  `B27_INVALID_REFERENCE_ID`, `B28_WAREHOUSE_MISSING_ID`, and
  `B29_OPERAND_MISSING_TYPE`. A saved-formula reference clause gets the
  positive-id check too. The bookmark schema check gains the warehouse
  show clause.
- `Metric` counts more than one event as one series: pass a list of
  event names and custom events, or a `SimpleBehavior` (optional series
  name, per-event filters through `FunnelStep`). Unique users are counted
  once across the events. Metric filters apply to every event.
- `CustomEventRef(id)` queries a saved custom event by ID, alone or as one
  of the events of a metric. The guide documents the `"$custom_event:<id>"`
  name for funnel steps and retention events, and that the display name
  of a custom event returns zero rows.
- `FunnelMetric` and `RetentionMetric`, over `FunnelBehavior` and
  `RetentionBehavior`, put funnel and retention measurements in
  `Workspace.query()` and `build_params()`, next to other metrics. The
  behaviors use the parameter names and defaults of `query_funnel()` and
  `query_retention()`, and their rules keep the same error codes. For a
  math that needs a property, an empty or whitespace-only property name
  counts as no property (`F10_MATH_MISSING_PROPERTY` for a funnel metric,
  `BH3_PROPERTY_MATH` for a retention metric).
- `Formula(expression, label=None, metrics=[...])` holds its own
  operands (`FormulaOperand`): the letters name the operands, and the
  formula can be the whole query. New error codes: `FM2_UNKNOWN_LETTER`,
  `FM3_NESTED_FORMULA`, `FM4_SYNTAX`, `FM5_UPPER_E`; an expression with no
  letter gets `V16_FORMULA_SYNTAX`. The formula stores its operands as a
  tuple copy, so a later change to the list passed in does not change the
  operands that the checks ran on.
- New error codes for behaviors and inline metrics: `BH1_STEP_COUNT`,
  `BH2_EMPTY_EVENT`, `BH3_PROPERTY_MATH`, `MT3_FILTERS_WITH_BEHAVIOR`,
  `CE1_INVALID_ID` (a custom event id is a positive integer, never a
  bool), `MT4_INVALID_INDEX` (`FunnelMetric.step_index` and
  `RetentionMetric.bucket_index` are integers >= 0, never a bool), and
  `MT5_INVALID_EVENT_TYPE`. A list of events in a `Metric` takes event
  names and `CustomEventRef` items only. A `FunnelStep` there would lose
  the `Metric` filters, so it goes in a `SimpleBehavior`, which keeps the
  filters of each step. The construction check and the query check both
  refuse any other item. The
  query checks for event names (`V17_EMPTY_EVENT`, `V22_*`) run on each
  name inside a list of events or a `SimpleBehavior`, and on formula
  operands, whose inline cohort definitions and step filters get the
  top-level checks too.
- Saved behaviors and saved metrics inside inline values: a `BehaviorRef`
  is the behavior of a `Metric` (type `simple`), a `FunnelMetric` (type
  `funnel`), or a `RetentionMetric` (type `retention`); another type raises
  the new code `BH5_BEHAVIOR_REF_TYPE`. A `MetricRef` is an operand of a
  `Formula` with its own operands, written as `{"type", "id"}`; a
  reference to a saved formula raises `FM3_NESTED_FORMULA`, a warehouse
  metric reference raises `FM7_WAREHOUSE_OPERAND` (the server accepts only
  behavior metrics as operands), and an operand reference with an override
  raises `MR2_OPERAND_OVERRIDE`.
- **Saved metrics and saved behaviors: create and update.**
  `Workspace.create_metric(params, *, validate=True)`,
  `update_metric(metric_id, params, *, validate=True)`,
  `bulk_update_metrics(entries, *, validate=True)`,
  `create_behavior(params, *, validate=True)`, and
  `update_behavior(behavior_id, params, *, validate=True)`, with the params
  models `CreateMetricParams`, `UpdateMetricParams`,
  `BulkUpdateMetricEntry`, `CreateBehaviorParams`, and
  `UpdateBehaviorParams`. The kind of a saved metric comes from its
  definition: a `Metric` or `CohortMetric` saves the `behavior` and
  `measurement` of the show clause that `Workspace.query` writes for it, so
  a saved metric queries the same way as its inline twin. New definition
  values `WarehouseMetric` (its `aggregation` and `sync_interval` default
  to `None`: a create then writes the server defaults `"none"` and
  `"hourly"`, because the server stores the request as sent, and an update
  keeps the stored values, so an update of the SQL alone keeps a stored
  `"sum"` and `"daily"`), `RawMetricDefinition`, and
  `RawBehaviorDefinition` (a wire definition dict, for example one that a
  get returned), the `MetricDefinition` alias, and the `Literal` aliases
  `WarehouseAggregation` and `WarehouseSyncInterval`.
  `SavedMetric.to_raw_definition()` returns a stored metric as a
  `RawMetricDefinition`, with its kind and warehouse source, for a copy;
  a legacy `behavior` kind becomes `metric`, and an unknown kind raises
  `SM4_SCHEMA`.
- The server checks a create against its JSON Schema but stores an update
  as sent, so every write runs the same client-side checks before any
  request, with new `ParamValidationError` codes: `SM1_EMPTY_NAME`,
  `SM2_NAME_TOO_LONG` (the server fails with a 500 over 255 characters),
  `SM3_KIND_CHANGE` (a new definition must keep the stored kind and
  warehouse source), `SM4_SCHEMA` (a mirror of the server POST schema
  names the failing field path; `validate=False` skips it), and
  `FM6_OPERAND_ATTRIBUTION` (a saved formula operand cannot set a segment
  method or an attribution model). The server drops `owned_by` and
  `verified` from a create, so `create_metric` sets them in a second
  request; the two requests are not atomic. When the second request fails,
  `create_metric` raises `MixpanelHeadlessError` with code
  `CREATE_FOLLOW_UP_FAILED`: its message and `details["metric_id"]` give
  the id of the created metric, and the error of the second request is
  chained. A create answer without a metric id raises
  `ResponseValidationError` before the second request. An update with new
  display or goals but no definition reads the metric and sends its full
  definition back, because the server replaces a definition in full. The
  new display merges into the stored one (or into the display of a new
  definition that has one): the keys that the caller sets replace the
  stored ones, a key set to `None` is removed, and the other keys stay.
  New goals replace the stored goals in full. A create that the server's
  schema refuses raises `QueryError` (400) with a short message: the
  failure and its schema location, without the HTML-escaped copy of the
  request that the server appends. The full body stays in `response_body`.
  The CLI prints only the short message for such a 400, not the server's
  copy of the request. Only a body with every field of
  the server's schema refusal (`status`, `error`, and `details` with
  `path`, `schema`, and `data`) counts; another 400 keeps its server
  message and the usual CLI output. An error of `mp metrics
  create|update|verify|delete` or `mp behaviors create|update|delete` (for
  example a 409 duplicate name or a 403) never prints the request params
  or body, which hold the definition and, for a warehouse metric, its SQL;
  the exception keeps them for Python callers.
- Saved definitions from the typed values: `CreateMetricParams` takes a
  `FunnelMetric`, a `RetentionMetric`, a `Metric` over several events, and
  a `Formula` with its own operands (a `MetricRef` operand stays a
  reference), compiled by the same builders as `Workspace.query`.
  `CreateBehaviorParams` takes a `SimpleBehavior`, `FunnelBehavior`, or
  `RetentionBehavior` (new alias `BehaviorDefinition`); the saved
  definition never holds a name. A `Formula` without operands raises the
  new code `SM7_FORMULA_WITHOUT_OPERANDS`. The saved definition of a typed
  value holds no legacy behavior `filter` key: the server reads past it at
  query time, but its create schema rejects it. Stored definitions carry
  such legacy keys (for example a behavior `filter`, legacy funnel step
  keys, and the `id` and `type` of a measurement), so a create removes
  them from a `RawMetricDefinition` or `RawBehaviorDefinition`, with or
  without `validate`, and a copy of a stored metric or behavior works (in
  Python and through `mp metrics create` / `mp behaviors create
  --definition-file`). In a definition compiled from a typed value,
  `SM4_SCHEMA` refuses them, because one there means a builder bug. An
  update sends them as given.
- `Workspace.query` and `build_params` refuse a `WarehouseMetric` with the
  new code `MR3_WAREHOUSE_INLINE`: the server runs warehouse SQL only by
  saved id, so a warehouse metric is saved first and queried by reference.
- CLI: `mp metrics query ID` runs a saved metric by reference.
- CLI: `mp metrics create|update|verify` and `mp behaviors create|update`.
  `--definition-file FILE|-` takes the wire definition that `get` prints,
  so get, edit, and update is a round trip. `mp metrics verify` names on
  stderr the ids that the server skipped. Before any request, `update`
  exits 3 when no option to change is given, and `mp metrics update`
  exits 3 when `--kind` or `--warehouse-source-id` comes without
  `--definition-file`.
- `MetricDisplay` gains the write side of the server model: the
  experiment sizing keys `minimumDetectableEffect`, `oneSided`, and `power`
  are accepted by the bookmark schema check too. `MetricGoal.id` is
  optional; a new goal gets a UUID on write, `date` and `datetime`
  checkpoints are written as naive ISO timestamps, and the deprecated goal
  keys `unit` and `direction` are never written.
- Plugin: repository tests guard the skills. Every Python block must
  parse, every `ws.<method>()` call must name a real method and real
  keyword arguments, and each skill must stay inside its size budget.
- Plugin: a behavior eval suite (`claude plugin eval`) lives in
  `mixpanel-plugin/evals/`.

### Changed

- `query_retention()` and `build_retention_params()`: `return_event` now
  defaults to `None`, so a `BehaviorRef` can stand alone. Event retention
  still needs it; a missing `return_event` gives `R2_EMPTY_RETURN_EVENT`
  instead of a `TypeError`.
- A `Formula` without operands whose expression passes the
  `V16_FORMULA_SYNTAX` and `V19_FORMULA_BOUNDS` checks but is outside
  the server formula grammar (for example `A ^ -B`) is now refused with
  `FM4_SYNTAX` before the request, not by the server.
- `query_funnel()` and `query_retention()` refuse a step or event that
  holds more than one event (a list or a `SimpleBehavior`) with a message
  that names custom events as the fix. The funnel code stays
  `F2_EMPTY_STEP_EVENT`; the retention codes are `R1_EMPTY_BORN_EVENT`
  and `R2_EMPTY_RETURN_EVENT`.
- Plugin: the skills now use the library's built-in reference for every
  API fact. The bundled `help.py` script is removed; skills look up
  signatures, types, and allowed values with `mp help <query>` (or
  `mp.help()` in Python), so the answers match the installed library.
  Copied method lists, type fields, and enum values leave the skill text.
- Plugin: the `mixpanelyst` skill is restructured into a short entry file
  (workflow, gotchas, the look-up loop) plus one reference file per query
  engine and topic, loaded only when a question needs it.
- Plugin: a new `session-replay` skill takes over session recording
  analysis for web and mobile (rage clicks, rage taps, dead clicks,
  errors, action timelines) from `mixpanelyst`.
- Plugin: `/mixpanel-headless:auth` moves from a command to a skill, with
  `auth_manager.py` beside it. The invocation does not change, and the
  skill now also loads on its own when credentials are missing or failing.
- Plugin: the `dashboard-expert` references are reorganized by topic
  (content and layout, text cards, report pipeline, chart types,
  templates).
- Plugin: the plugin now runs code in its own Python environment. The
  setup skill creates it at `~/.claude/plugins/data/mixpanel-headless-<source>/venv`
  (with `uv` when available, otherwise `python3 -m venv`) and installs
  `mixpanel-headless>=0.3.0` and the analysis packages there, never into
  the system or user Python. Running setup again upgrades the
  environment, and setup checks that `mp help` works. The skills run
  that environment's `python` and `mp`, and the environment survives
  plugin updates. To run your own scripts with it, use the `python` path
  that setup prints, or install `mixpanel-headless` in your own project.
  Setup ignores the uv settings of the project you run it from, so a
  project's uv configuration does not change the plugin install.
- Plugin: the analysis skills pre-approve only the plugin environment's
  `python` and `mp`, `uv run`, file reads, writes, and edits, and fetches
  from the documentation site. For look-ups before setup, they also
  pre-approve two read-only commands of an `mp` on your `PATH`:
  `mp --version` and `mp help`. They no longer pre-approve any other
  `python`, `python3`, or `mp` command on your `PATH`.
- Plugin: skill descriptions say when to use each skill and when to use
  another one.
- Plugin: the plugin no longer documents or checks the Cowork bridge.
  The setup skill no longer detects it, the auth skill no longer has a
  bridge status command, and the Cowork quick start guide is removed.
- Plugin: the manifest description and keywords describe the new skill
  set, and the plugin README and guides use `mp help` in place of the
  script.

### Fixed

- **`RateLimitError.retry_after` is capped at one hour.** When a request
  still got HTTP 429 after its last retry, the error reported the server's
  `Retry-After` value as sent, with no upper bound. Code that follows the
  documented `time.sleep(e.retry_after or 60)` pattern could be told to wait
  for days. A value with hundreds of digits also crashed the retry loop with
  `OverflowError` before any retry ran. Mixpanel rate limits over a rolling
  one-hour window, so every retry path (queries, App API calls, event export,
  shortlink resolution, and App API pagination) now reports at most 3600
  seconds. Values of an hour or less are reported unchanged. The client's own
  wait between retries is still capped at 60 seconds.
- Plugin: examples and parameter names that no longer matched the
  library are corrected (for example, `query_user()` takes `where=`, not
  `filters=`).
- Docs: the report link examples in `Workspace.create_report_link`, the
  report links guide, and the `Workspace` API page called
  `mp.Metric.total("Login")`, which does not exist. They now use
  `mp.Metric("Login", math="total")`.
- An error response whose body has a `message` key and no usable `error`
  key now puts the server's `message` text in the exception message, and
  the CLI prints it. Before, the exception held only the generic text (for
  example, `Server error: 500`), and the server's support text and Error
  ID were lost. When both keys are present, `error` wins.
- `Workspace.query_user(where=...)` now accepts the date filters
  (`Filter.on`, `not_on`, `before`, `since`, `date_between`,
  `date_not_between`, `in_the_last`, `not_in_the_last`, `in_the_next`)
  and `Filter.at_least`, `at_most`, and `not_between`. Before, these
  failed with `Unsupported filter operator`. Absolute dates are whole
  days in the project timezone, as in Insights. Relative dates are
  rolling windows measured from the server's clock when the query runs,
  not calendar days, so a count near the start of the window can differ
  from Insights; a window can span at most 50 years.
- `Filter.starts_with`, `ends_with`, and `list_contains` still cannot be
  used in `query_user(where=...)`, because the Engage profile selector
  has no form for them. They now fail with a `ParamValidationError`
  (code `ES14_NO_SELECTOR_EQUIVALENT`, wrapped in
  `BookmarkValidationError`) whose message names the constructor and a
  workaround. New codes `ES15` to `ES20` reject a malformed value on a
  directly constructed date, relative-date, `at_least`, or `at_most`
  `Filter`. A directly constructed date range with its first day after
  its last day fails with `FD2_DATE_ORDER`, as the `Filter.date_between`
  and `Filter.date_not_between` factories do.
- `query_user(where=...)` no longer accepts `True` or `False` as the
  number in a number comparison (`greater_than`, `less_than`, `at_least`,
  `at_most`, `between`, `not_between`). Before, the selector compared the
  property with `True` or `False`. Now the filter fails with the
  operator's number code.
- `QueryResult.df` now flattens a `group_by` with two or more properties.
  Before, it read only one level of nesting: segment values landed in the
  `date` column and `count` held nested dicts. Each property now gets its
  own column, named from `result.headers` (or `segment_1` .. `segment_N`
  when a name does not fit). Rollup rows are kept, with `$overall` in
  each column below the level they summarize. A single `group_by` still
  gives one `segment` column.

## 0.3.0 — 2026-09-22

Minor release: built-in API help and mobile session replays. A
top-level `mp.help()` function, a structured `mp.reference` module, and an
`mp help` CLI command provide offline API reference for the whole public
surface. All three need no credentials and touch no config file. The replay
analyzer now reads mobile and other screenshot-based recordings (iOS,
Android, React Native, Flutter): taps, scrolls, wireframe screens, and a new
`rage_taps()` aggregator. `__all__` loses ten duplicate entries.

### Added

- **`mixpanel_headless.help(query=None, *, format="text", file=None,
  hints=True, domain=None)`.** Prints reference text for any public name
  and returns `None`, like the builtin. Accepts the string grammar
  (`"Workspace.query"`, `"Workspace.query.events"`, `"Filter"`,
  `"MathType"`, `"accounts"`, `"types"`, `"exceptions"`,
  `"search cohort"`) and object forms (`mp.help(mp.Filter)`,
  `mp.help(ws.query)`, `mp.help(mp)`). `domain=` filters the `Workspace`
  listing to one of 32 domains. A miss prints one `No help entry for 'X'.
  Did you mean: ...?` line and the first search hits instead of raising.
  Import the package with an alias (`import mixpanel_headless as mp`); `from mixpanel_headless import
  help` shadows the Python builtin.
- **`mixpanel_headless.reference`** — structured access behind `help()`:
  `describe(query, *, hints=, domain=) -> HelpEntry`,
  `search(term, *, limit=) -> SearchResult`,
  `render(entry, format) -> str`, and `clear_cache()`. Result types are
  frozen `slots=True` dataclasses with `to_dict()`: `HelpEntry`,
  `DocSections`, `SignatureDoc`, `ParamDoc`, `FieldDoc`, `MemberDoc`,
  `Group`, `UsageDoc`, `Hint`, `SearchResult`, `SearchHit`, plus the
  `ExportKind`, `MemberKind`, `HelpKind`, and `HelpFormat` literals. All
  eleven result types are also root exports (`mp.HelpEntry`, ...), so
  `mp help HelpEntry` describes them. Every export kind has a view:
  Literal aliases show their allowed values and the `Workspace` methods
  that accept them; modules list their `__all__`; exceptions show their
  subclass tree; private fields are hidden and factory classmethods are
  listed under Construction. The inventory comes from `__all__` and is
  cached per process. C-level members inherited through a framework base
  (`FeatureFlagStatus.maketrans` from `str`, `HelpLookupError.with_traceback`
  from `BaseException`) are a plain miss on every supported Python version,
  not an error; inherited Python callables such as
  `CreateDashboardParams.model_dump` resolve.
- **`mp help [QUERY...] [-f text|markdown|json] [--jq EXPR] [--domain NAME]
  [--no-hints]`.** No auth: the command ignores `-a / -p / -w / -t` and never
  builds a `Workspace`. The default format is `text` (unlike entity
  commands, whose default is `json`); `--jq` requires `-f json`. Exit codes:
  0 found, or a search with hits; 2 for an option value the parser rejects;
  3 on stderr for `--jq` without `-f json`, a bare `search` with no term,
  or a `--domain` that is unknown, ambiguous, or given with anything other
  than the `Workspace` query (`mp help search cohort --domain dashboards`
  and `mp help --domain dashboards` both exit 3 with the same message as
  `mp help Filter --domain dashboards`); 4 for a miss or a search with
  zero hits, with the miss line and search view on stdout. Under `-f json`,
  `--jq` filters the miss object and the empty search object the same way
  it filters a hit (`mp help Nope -f json --jq .error` prints one JSON
  string and still exits 4). `python3 -m mixpanel_headless help ...` runs
  the same command where `mp` is not on `PATH`. Output goes through
  `typer.echo`, so literal `[property]` / `[method]` tags survive.
- **`HelpLookupError`** (`MixpanelHeadlessError`, not `APIError`) — raised
  by `reference.describe()` on a miss and by `reference.search()` for an
  empty term. Carries `query`, `suggestions`, and `hits`; `details` and
  `to_dict()` include the hits as dicts. The CLI maps it to
  `ExitCode.NOT_FOUND` (4).
- **`HelpDomainError`** (`HelpLookupError` subclass, code `HELP_BAD_DOMAIN`)
  — raised by `reference.describe()` when `domain=` names no registered
  `Workspace` domain, matches several titles, or is given with a query other
  than `Workspace`. Carries `query`, `domain`, `domains`, and `reason`
  (`unknown`, `ambiguous`, `not_workspace`; the `HelpDomainReason` literal).
  `help()` re-raises it instead of printing a miss; the CLI prints the
  message and one `Domains:` line on stderr and exits 3.
- Rendered signatures print the `*` and `/` markers of `inspect.signature`,
  so keyword-only and positional-only parameters read as they are declared
  (`mp help Workspace.segmentation` shows `*,` after `event`). `ParamDoc.kind`
  carries the same fact in JSON: `positional_only`, `positional_or_keyword`,
  `var_positional`, `keyword_only`, or `var_keyword`.
- Type hints resolve one name at a time, so a single annotation that cannot
  be evaluated (a `TYPE_CHECKING`-only import on a private field) no longer
  blanks the allowed values of every other field on the class;
  `FlowQueryResult.mode` lists its values.
- `MemberDoc.depth` carries the nesting level of an exception subclass tree,
  and names no longer carry leading spaces in JSON. `HelpEntry.domain` holds
  the registry domain title of a `Workspace` method and `HelpEntry.value` the
  `repr` of a constant, so JSON consumers no longer read those facts out of
  `groups`, `bases`, or `values`. `ParamDoc.annotation` is `null` when the
  source has none.
- Every exported Literal, Union, and Annotated alias and every constant
  without a docstring of its own (`MathType`, `TimeUnit`, `Region`, `Account`,
  `PropertySpec`, `BUSINESS_CONTEXT_MAX_CHARS`, ...) carries a one-line
  description, so `mp help <Alias>` and every row of `mp help types` show a
  summary.
- Every `Workspace` domain (feature flags, experiments, annotations,
  webhooks, and alerts included) yields a hosted-docs hint, so every
  `Workspace.<method>` entry ends with a `Tip:` pointer.
- Docs: new [Built-in Help guide](docs/guide/built-in-help.md) and
  [API page](docs/api/help.md); both are listed in `llms.txt`.
- **New action label `"screen"`.** A wireframe screen snapshot from a
  mobile or other screenshot-based recording. `UserAction.action` is a
  closed `Literal`, so an exhaustive `match` over it needs a new case.
  - `description` is the screen as one line:
    `Wireframe: <label> [x,y,w,h] | role:label [x,y,w,h] | …`.
  - `target_desc` is an approximate heading: the label of the top-most
    labeled text element (text clipped above the top edge is skipped), or
    `"(screen)"` when there is none. The SDKs send no screen name, and the
    heading can be a back-button label.
  - `metadata` holds `elements` (role, text, bounds, and the offscreen and
    background flags),
    `viewport`, `scale`, `fingerprint` (identical screens share it), and
    `element_count`. Some SDK builds send bounds in physical pixels; when
    the payload viewport width differs from the Meta width by more than
    5%, the structured bounds are scaled into the touch coordinate space.
    The description keeps the raw bounds. A viewport or Meta width that
    would give a zero division or an infinite value applies no scale.
- **Screenshot recordings in the analyzer.** A replay with any
  `mp_wireframe` event, or with Meta events that carry no page URL, is a
  screenshot recording. In such a recording:
  - Touches go through a gesture state machine. Finger travel of 10 px or
    less is a tap (`Tapped at (x, y)`, action `touch_start`); more is a
    scroll (`Scrolled`, action `scroll`). A cancelled touch emits nothing.
    A gesture whose lift-off never arrives is a tap at its finger-down,
    or a scroll when its drag already passed 10 px; like a lift-off, it
    arms the "after" screens, so screens between overlapping touches are
    sampled.
  - A mouse click (Flutter web and desktop) is `Clicked at (x, y)`, action
    `click`, so `rage_clicks()` and `top_clicks()` see it.
  - Wireframe screens are sampled around each gesture (the screen before
    it and up to two screens after it), so animation frames do not flood
    the timeline. Consecutive identical screens appear once.
  - Taps and clicks are hit tested against the screen that was current at
    finger-down. `target_desc` names the element (`button:Save`, a bare
    label for text, or `role [x,y,w,h]` for an unlabeled icon), and
    `metadata` gains `hit` and `attribution` (`"bounds"`, or
    `"bounds_slop"` for a near miss within 8 px). A background layer (a
    rect that crosses both side edges, such as the blur behind a tab bar)
    is never hit. Without a hit the target is `"(x, y)"`. The description
    always shows the point only.
- **`Replay.capture`** (`"dom"` or `"screenshot"`), **`Replay.has_wireframes`**,
  and **`Replay.screen_path()`** (screen headings in order: the mobile form
  of `page_path()`).
- **`ReplayBundle.screens_df`** — one row per screen: `replay_id`, `t`,
  `heading`, `fingerprint`, `element_count`, `description`.
- **`ReplayBundle.rage_taps(threshold=3, window_ms=2000, radius_px=24,
  grace_ms=1000)`** — bursts of finger-downs near one point in screenshot
  recordings. Finger-downs are counted from `rrweb_events`, because a fast
  burst with overlapping fingers produces far fewer classified taps.
  Each burst is classified per interval: the gaps between consecutive
  finger-downs, plus the `grace_ms` window after the last one. `kind` is
  `"dead"` when no interval has a screen change. A burst where every gap
  between finger-downs has a change (a quantity stepper) is intentional
  and is not reported. Anything else is `"rage"`, for example a navigation
  that arrives only after the burst. A screen that changes on its own (a
  live clock) counts as a change. Columns: `replay_id`, `t_start`, `t_end`, `target_desc`,
  `x`, `y`, `count`, `kind`.

### Changed

- **Ten duplicate names removed from `__all__`.** `MathType`,
  `PerUserAggregation`, `FunnelMathType`, `RetentionAlignment`,
  `RetentionMode`, `RetentionMathType`, `CustomPropertyType`,
  `FilterOperator`, `FilterPropertyType`, and `FilterDateUnit` were each
  listed twice. Every name is still exported once; there is no behavior
  change.
- **Well-formed web replays are unchanged.** A replay whose Meta events carry a page
  URL, or that has no Meta event at all, is a DOM recording and gives the
  same actions and markdown as 0.2.3. The committed web goldens are
  byte-identical.
- `UserAction.target_node_id` is always an int or None: a bool node id
  gives None, and an integral float id (`28.0`) gives `28`.
- The markdown timeline now renders from the structured action list,
  sorted by timestamp. For web replays the text is the same.
- The analyzer drops an action with a timestamp of zero or less instead of
  raising `ParamValidationError`, so one bad event no longer fails a whole
  `fetch_replay`. Malformed wireframe input (wrong types, non-finite
  numbers) degrades instead of raising.
- An unusable rrweb timestamp reads as 0 everywhere, instead of raising.
  A usable timestamp is a finite number above 0 and no later than
  9999-12-31T23:59:59.999Z (253402300799999 ms); a string, None, a bool,
  NaN, infinity, or a larger number such as `1e30` is unusable. This
  applies in the analyzer (the action is dropped), `Replay.events_df`
  (`t` is 0), `Replay.to_rrweb_player_json()` (it sorts first), the CDN
  walk, and `fetch_replay` (the window uses the usable timestamps; with
  none, it raises `ReplayNotFoundError`). The CDN
  walk and the analyzer also skip entries that are not dicts, and the
  walk's format check reads the first dict entry, so one damaged leading
  entry no longer aborts a replay.
- `UnsupportedReplayFormatError` no longer says that mobile replays are
  unsupported. It now means the bytes are not rrweb-shaped (an unknown or
  damaged format). The CLI message changes to match.

### Notes

- Plugin: the `mixpanelyst` skill gains guidance for mobile and
  screenshot replays (call `rage_taps()` first, use `screen_path()` and
  `screens_df` for screen flow, read `metadata["hit"]` for tap targets)
  and triggers on questions about rage taps on mobile.
- Plugin: the `mixpanelyst` skill still uses its bundled help script; the
  next plugin release switches it to `mp help` / `mp.help()`, requires
  `mixpanel-headless>=0.3.0`, and moves the manifest version to `0.3.0`.
  The manifest stays at `0.2.3` in this release.

## 0.2.3 — 2026-09-14

Patch release: report links (create, resolve, and run a Mixpanel report
URL from headless params), `MP_API_BASE_URL` single-host routing, a
`limit=` parameter plus `run_*_params` on the query methods, `Filter`
operator validation on direct construction, a CLI exit-code change for
`BookmarkValidationError`, and the plugin manifest catches up to the
library version.

### Added

- **`MP_API_BASE_URL` — route every API family at one alternate host.** When
  set (trailing slash tolerated; read per request, not at import), the
  per-region `ENDPOINTS` lookup is bypassed and the four families resolve to
  path prefixes on that single base: `query` → `{base}/api/query`, `export` →
  `{base}/api/2.0`, `engage` → `{base}/api/query/engage`, `app` →
  `{base}/api/app`. The `mp` CLI inherits it with no flag. App-vs-Query
  timeout selection and pinned `workspace_id` injection key off the family,
  so they behave identically under the override. `mp login`'s region probe
  collapses to one probe at the base (region label from `MP_REGION` when
  valid, else `us`). Plain `http://` bases are accepted and intended for
  local / headless deployments only. `MP_REGION` remains required and
  meaningful for non-URL uses. Optional `MP_APP_BASE_URL` re-homes only the
  App API family at `{app_base}/api/app`. With both unset, behaviour is
  byte-identical to before. (#235)
- **`limit=` on the query methods, plus `run_*_params`.** `query()`,
  `query_funnel()`, and `query_retention()` accept `limit=` (1 to 50000,
  default 3000) to raise the segment cap for
  high-cardinality breakdowns; check `result.meta["is_segmentation_limit_hit"]`
  to see whether the result was still truncated. New `run_params()`,
  `run_funnel_params()`, `run_retention_params()`, `run_flow_params()`,
  and `run_user_params()` execute a params dict that the matching
  `build_*_params()` produced (or one written by hand) and return the same
  result type as the typed query method, so params the typed builder
  cannot express can still run. (#225)
- **Report links** (045, AIE-561 / AIE-562, #223). Share a headless query as a
  Mixpanel report URL and resolve a report URL back into runnable params.
  - `Workspace.create_report_link(params_or_result, *, report_type=, name=,
    description=, workspace_id=, bookmark_id=, validate=)` stores an unsaved
    report under a 12-character slug and returns a `ReportLink`.
  - `Workspace.resolve_report_link(link)` accepts a full URL, a bare slug, or a
    `https://mixpanel.com/s/{code}` shortlink and returns a `ResolvedReport`
    with the raw params. A region mismatch fails before any HTTP call; project
    and pinned-workspace mismatches fail before the record fetch.
  - `Workspace.query_report_link(link_or_resolved, *, mode=)` runs the params
    through `query` / `query_funnel` / `query_retention` / `query_flow`,
    under exactly the scope the report records (the URL `wid`, else the pin
    at resolve time, else project-wide); the current pin is never injected,
    so a pin cleared or set after resolve time cannot change the data view. A
    `ResolvedReport` whose recorded region or project differs from the
    active session, or whose recorded workspace differs from the pinned
    session workspace, is rejected before any query. The four
    `LiveQueryService` inline methods and `MixpanelAPIClient.insights_query`
    / `arb_funnels_query` accept an optional `workspace_id` that wins over
    the pin, and `inject_workspace_id=False` to run project-wide.
  - `Workspace.saved_report_link(bookmark_id, *, report_type=, workspace_id=)`
    builds a saved-report URL with no network call.
  - CLI: `mp reports link` and `mp reports resolve [--run] [--mode]`, plus an
    opt-in `--link` flag on `mp query segmentation`, `funnel`, `saved-report`,
    and `flows` that adds `report_url` to the output. A link failure never
    fails the query: `report_url` is `null` and `report_url_error` holds the
    reason.
  - Types: `ReportLinkType`, `BookmarkUrl`, `ReportLink`, `ResolvedReport`,
    `ReportLinkQueryResult`.
  - Exceptions: `ReportLinkError` and its subclasses `ReportLinkParseError`,
    `UnsupportedReportLinkError`, `ReportLinkNotFoundError`,
    `ReportLinkScopeMismatchError`, `ShortLinkResolutionError`; every
    instance carries a `hint` in `details`. Builder and input guard codes
    `RL1_UNKNOWN_REPORT_TYPE`, `RL2_INVALID_SLUG`, `RL3_UNKNOWN_REGION`,
    `RL4_REPORT_TYPE_CONFLICT`, `RL5_RESOLVED_REPORT_INCONSISTENT`,
    `RL6_INVALID_ID` (raised as `ParamValidationError`).
  - CLI exit codes: `ReportLinkNotFoundError` → 4; `ReportLinkParseError`,
    `UnsupportedReportLinkError`, and `ReportLinkScopeMismatchError` → 3;
    `ShortLinkResolutionError` → 1. The CLI prints `details["hint"]` on a
    `hint:` line for all of them.

### Changed

- **`BookmarkValidationError` now exits the CLI with code 3, not 1.** The
  class is raised by about 15 pre-existing commands (`mp reports create`,
  `mp reports update`, the dashboard verbs, and others) when params fail the
  client-side schema check. `handle_errors` now prints
  `error: params failed schema validation` plus one line per
  `severity="error"` item and exits with `INVALID_ARGS` (3). Scripts that
  test for exit code 1 on those commands must be updated. (#223)
- Plugin: the manifest version is now `0.2.3`, in step with the library.
  It stayed at `0.2.1` through the `0.2.2` release.

### Fixed

- **`Filter(...)` built positionally no longer serializes an unvalidated
  operator.** `Filter("gold", "greater_than", 10, "number")` used to emit
  `"filterOperator": "greater_than"` verbatim and fail server-side with HTTP
  400 (`Unsupported operator for filter_type number`). `Filter.__post_init__`
  now validates `_operator` against the `FilterOperator` literal and raises
  `ValueError` immediately — naming the bad operator, listing the valid wire
  operators, and pointing at the factory methods — instead of surfacing a
  generic `QueryError` one HTTP round trip later. The factory-method spellings
  are accepted as aliases and normalized to the wire operator
  (`"greater_than"` → `"is greater than"`, `"is_set"` → `"is set"`,
  `"not_between"` → `"not between"`, `"in_the_last"` → `"was in the"`, and so
  on for every public `Filter` classmethod), so the positional call now
  produces byte-identical output to the equivalent factory. The two
  segmentation-`where` spellings that pre-date the literal, `"is equal to"`
  and `"between"`, stay constructible as aliases of `"equals"` and
  `"is between"` (same `==` / `><` segfilter output). On a `boolean`
  property, `equals` / `does not equal` with a `True` / `False` value collapse
  to `true` / `false` with `filterValue: null`, matching `Filter.is_true()` /
  `Filter.is_false()`; any other operator on a boolean property is rejected,
  and `true` / `false` (however spelled) reject any non-`None` value. A
  boolean `InlineCustomProperty` is governed by the same rules (the inline
  type wins, as in `build_filter_entry`). Non-string operators raise the same
  `ValueError` rather than `TypeError`. The `_operator` field is typed as the
  new `FilterOperatorInput` literal (wire operators plus aliases) so the
  positional call type-checks; the stored value is always canonical.
  Already-valid input is never rewritten. The `Filter` docstring no longer
  claims the class is "never instantiated directly". (#236)

### Documentation

- `FrequencyFilter` now documents that the query engine evaluates its
  threshold **per query time bucket** (`unit`), not over the whole report
  date range. With the default `unit="day"`, `FrequencyFilter("Login",
  value=5)` keeps only users who logged in 5+ times on a single day and
  returns an empty series when nobody does, even if thousands did so across
  the month; choose the `unit` that matches the threshold period
  (`"month"` for "N times in a month"). The `Workspace.query(where=...)`
  docstring, the query
  guide, and the mixpanelyst skill carry the same warning. The
  `date_range_value` / `date_range_unit` parameters are documented as having
  no observable effect on inline insights filters in a 2026-09-11 probe
  (unverified against platform fixtures); they are unchanged on the wire.
  (#234)
- Plugin: dead reference links in the setup skill are fixed. (#230)

## 0.2.2 — 2026-09-01

Patch release: `schema_graph()` on large projects, query-engine bookmark
correctness, retry/error-path hardening, and a storage env-var rename.

### Changed

- The storage-root environment variable is now `MP_STORAGE_DIR`. The old
  name `MP_OAUTH_STORAGE_DIR` still works as a deprecated alias and loses
  when both are set. (#216)

### Fixed

- `schema_graph()` no longer times out on very large projects.
  Relationship edges now come from the query API's per-event property
  gather (the same surface the Lexicon UI uses), and client timeouts are
  route-aware so they outlast the server-side deadlines instead of
  pre-empting them. (#215)
- Query-engine bookmark fixes: frequency-filter clauses now emit the
  platform-native shape (the previous shape drew a server 500);
  `data_group_id` is string-coerced in group clauses and emitted as the
  contract's `globalDataGroupId` at the sections level; a `TypeError` in
  the sensitive-data 403 sniff is fixed; OAuth bearer tokens are redacted
  from error-detail payloads. (#208)
    - Upgrade note: on 0.2.1 every `Workspace.query(where=FrequencyFilter(...))`
      call fails with a server 5xx (`ServerError: Server error: An unknown
      error occurred.`) because the query engine cannot evaluate the old
      clause shape. The failure gives no hint at its cause and there is no
      client-side workaround; upgrade to `mixpanel-headless>=0.2.2`.
- Retry and error paths hardened: negative, non-finite, or garbage
  `Retry-After` values fall back to exponential backoff and are capped at
  the 60s ceiling; a JSON-null `results` page is treated as empty and a
  non-list `results` raises a typed error instead of mis-iterating; blank
  error bodies no longer produce empty exception messages; 401 and App
  API errors now carry request context for parity with the query paths.
  (#206)
- Plugin: the setup skill name no longer contains a colon, which made the
  skill fail to load. (#218)

## 0.2.1 — 2026-08-13

Patch release: workspace-scoped Query API correctness and fresh-install
fixes.

### Fixed

- Query API requests now inject the pinned `workspace_id`, so data view
  filters apply to segmentation/funnels/retention and other live queries
  when a workspace is selected. (#199)
- Declare the `click` dependency explicitly so fresh installs work, and
  stop the plugin setup skill from executing `mp login` on the user's
  behalf. (#200)

## 0.2.0 — 2026-06-05

Headline feature: **session replay (044)** — discovery, signing, CDN fetch,
an rrweb analyzer, and DataFrame-shaped bundle analytics. This release also
sunsets JQL (breaking) and folds in `schema_graph()`, workspace
auto-resolution, and Lexicon enrichments merged since 0.1.1.

### Added

- `Workspace.list_replays(distinct_id|replay_ids, from_date, to_date, limit)`
  — discover replays for a user, or hydrate explicit IDs.
- `Workspace.sign_replay(id)` / `Workspace.sign_replays(ids, env)` —
  sign replay IDs for CDN access via the
  `/app/projects/<id>/replays/sign[/bulk]` endpoint.
- `Workspace.fetch_replay(id, env, retention_days, max_files,
  include_mixpanel_events, event_properties, cdn_concurrency)` — sign +
  parallel CDN walk + return a fully materialized `Replay`.
- `Workspace.stream_replay(id, …)` — sync iterator wrapping the async
  CDN walker; re-signs on expiry by default.
- `Workspace.events_for_replay(id, event_properties)` and
  `Workspace.events_for_replays(ids, event_properties)` — Mixpanel
  events that overlap a replay's time window.
- New result types: `ReplaySummary`, `SignedReplay` (with
  `query_string` masked in `__repr__`/`__str__` per FR-008/9),
  `ReplayEvent`, `UserAction`, `Replay`.
- New exceptions: `SessionReplayError` (base) plus
  `SessionReplayAccessError` (sensitive-data 403),
  `SignedURLExpiredError`, `ReplayNotFoundError`, and
  `UnsupportedReplayFormatError` (mobile / non-rrweb bytes). CLI
  exit-code mapping added: sensitive-data → 2, replay-not-found → 4,
  unsupported-format → 1.
- New CLI commands: `mp replays list`, `mp replays events`,
  `mp replays sign` (with `--reveal-signed-urls` opt-in that emits a
  stderr warning on every invocation), `mp replays fetch [-o FILE]`.
- Depends on the undocumented `/app/projects/<id>/replays/sign[/bulk]`
  endpoint — the same endpoint Mixpanel's own MCP server uses.
- `Workspace.fetch_replays(ids, …)` — parallel multi-replay fetch
  returning a `ReplayBundle`.
- `Workspace.replays_for_user(distinct_id, from_date, to_date, …)` —
  composition of `list_replays` + `fetch_replays`; defaults
  `include_mixpanel_events=True`.
- `Workspace.analyze_replay(id)` — sugar for
  `fetch_replay(id).summary_markdown`.
- `RrwebAnalyzer` (`_internal/replays/rrweb_analyzer.py`) — rrweb
  event-stream analyzer producing normalized `UserAction` records +
  markdown timeline. Handles click / input / scroll / navigate /
  select / console_error event families with per-source debouncing
  (scroll / input / selection at 1s each), plus a DOM tracker with
  ancestor traversal and descriptive-attrs extraction for
  human-readable target descriptions. Pure stdlib.
- `ReplayBundle` (`types.py`): five DataFrame projections
  (`sessions_df`, `actions_df`, `events_df`, `mixpanel_df`,
  `elements_df`); three aggregations (`top_clicks`, `rage_clicks`,
  `long_pauses`); six chainable filters (`filter`, `where`,
  `find_pattern`, `error_sessions`, `head`, `sample`);
  `join_mixpanel_events`, `summary_markdown`, `compare`.
- Label functions: `default_label_fn`, `selector_label_fn`,
  `url_normalizer` (public `replay_labels.py`, re-exported from the
  top-level package). The URL normalizer collapses numeric / hex path
  segments to `:id` so parameterized URLs aggregate cleanly across users.
- Module-level aggregators (`_internal/replays/aggregators.py`)
  re-exposed via `ReplayBundle` methods.
- New CLI commands: `mp replays analyze` (markdown timeline /
  `--format json` for action list) and `mp replays for-user
  --include analyze --out-dir DIR` (the Mixpanel-events join is on by
  default; opt out with `--no-mixpanel-events`).
- `Workspace.schema_graph()` — full Lexicon graph with event↔property
  relationships (#190).

### Changed

- `activity_feed()` streams via the `stream/bookmark` endpoint instead of
  `stream/query` (#187).
- The workspace axis auto-resolves from the cached `/me` response, with a
  project-metadata fallback, so workspace-scoped calls work without an
  explicit `MP_WORKSPACE_ID` (#188).
- Lexicon definitions now persist `display_name` and `example_value` (#189).
- Hard 429s surface a rate-limit-increase form to collect lead info (#192).

### Removed

- **JQL support removed (breaking).** All JQL query functionality has been
  sunset (#185).

### Security

- `SignedReplay.query_string` is a 5-minute bearer credential and is
  masked in `__repr__`/`__str__`. The `--reveal-signed-urls` CLI opt-in
  emits a stderr warning on every invocation (FR-008/9). The pre-merge
  security audit greps the source tree for `Signature=` / `URLPrefix=`
  / `Expires=`; no leaks were found.

### Notes

- Mobile session replays are detected by the CDN walker (first event
  lacks rrweb's `type`/`data`/`timestamp` keys) and surface as a
  typed `UnsupportedReplayFormatError` (a `SessionReplayError`) per
  error-messages.md §9 — the CLI maps it to a clean message + exit 1
  instead of leaking a traceback.
- Live integration tests (`tests/integration/test_replays_live.py`) are
  marked `@pytest.mark.live` and deselected by default; set
  `MP_LIVE_TESTS=1` plus `MP_REPLAY_FIXTURE_DISTINCT_ID` to run them
  against a fixture project.
