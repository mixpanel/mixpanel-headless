# Changelog

All notable changes to `mixpanel-headless` are recorded here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver but is currently pre-1.0, so minor versions
may include API changes.

## 0.4.0 — 2026-09-22

Minor release: session replays from the iOS, Android, React Native, and
Flutter SDKs. The rrweb analyzer now reads screenshot-based recordings:
wireframe screens, touch gestures, and Flutter web and desktop clicks.
One new action label, `"screen"`, joins the closed `UserAction.action`
set. Web replays give the same output as before.

### Added

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
    or a scroll when its drag already passed 10 px.
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

- **Well-formed web replays are unchanged.** A replay whose Meta events carry a page
  URL, or that has no Meta event at all, is a DOM recording and gives the
  same actions and markdown as 0.3.0. The committed web goldens are
  byte-identical.
- `UserAction.target_node_id` is always an int or None: a bool node id
  gives None, and an integral float id (`28.0`) gives `28`.
- The markdown timeline now renders from the structured action list,
  sorted by timestamp. For web replays the text is the same.
- The analyzer drops an action with a timestamp of zero or less instead of
  raising `ParamValidationError`, so one bad event no longer fails a whole
  `fetch_replay`. Malformed wireframe input (wrong types, non-finite
  numbers) degrades instead of raising.
- `UnsupportedReplayFormatError` no longer says that mobile replays are
  unsupported. It now means the bytes are not rrweb-shaped (an unknown or
  damaged format). The CLI message changes to match.

## 0.3.0 — 2026-09-21

Minor release: built-in API help. A top-level `mp.help()` function,
a structured `mp.reference` module, and an `mp help` CLI command provide
offline API reference for the whole public surface. All three need no
credentials and touch no config file. `__all__` loses ten duplicate
entries.

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

### Changed

- **Ten duplicate names removed from `__all__`.** `MathType`,
  `PerUserAggregation`, `FunnelMathType`, `RetentionAlignment`,
  `RetentionMode`, `RetentionMathType`, `CustomPropertyType`,
  `FilterOperator`, `FilterPropertyType`, and `FilterDateUnit` were each
  listed twice. Every name is still exported once; there is no behavior
  change.

### Notes

- Plugin: this release does not change the Claude Code plugin. The
  `mixpanelyst` skill still uses its bundled help script; the next plugin
  release switches it to `mp help` / `mp.help()` and requires
  `mixpanel-headless>=0.3.0`.

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
