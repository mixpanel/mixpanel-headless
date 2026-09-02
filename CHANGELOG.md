# Changelog

All notable changes to `mixpanel-headless` are recorded here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver but is currently pre-1.0, so minor versions
may include API changes.

## Unreleased

### Added

- **Report links** (045, AIE-561 / AIE-562). Share a headless query as a
  Mixpanel report URL and resolve a report URL back into runnable params.
  - `Workspace.create_report_link(params_or_result, *, report_type=, name=,
    description=, workspace_id=, bookmark_id=, validate=)` stores an unsaved
    report under a 12-character slug and returns a `ReportLink`.
  - `Workspace.resolve_report_link(link)` accepts a full URL, a bare slug, or a
    `https://mixpanel.com/s/{code}` shortlink and returns a `ResolvedReport`
    with the raw params. Project and region mismatches fail before any HTTP
    call.
  - `Workspace.query_report_link(link_or_resolved, *, mode=)` runs the params
    through `query` / `query_funnel` / `query_retention` / `query_flow`. A
    `ResolvedReport` whose recorded region or project differs from the
    active session, or whose recorded workspace differs from the pinned
    session workspace, is rejected before any query.
  - `Workspace.saved_report_link(bookmark_id, *, report_type=, workspace_id=)`
    builds a saved-report URL with no network call.
  - CLI: `mp reports link` and `mp reports resolve [--run] [--mode]`, plus an
    opt-in `--link` flag on `mp query segmentation`, `funnel`, `saved-report`,
    and `flows` that adds `report_url` to the output.
  - Types: `ReportLinkType`, `BookmarkUrl`, `ReportLink`, `ResolvedReport`,
    `ReportLinkQueryResult`.
  - Exceptions: `ReportLinkError` and its subclasses `ReportLinkParseError`,
    `UnsupportedReportLinkError`, `ReportLinkNotFoundError`,
    `ReportLinkScopeMismatchError`, `ShortLinkResolutionError`; builder guard
    codes `RL1_UNKNOWN_REPORT_TYPE`, `RL2_INVALID_SLUG`, `RL3_UNKNOWN_REGION`,
    `RL4_REPORT_TYPE_CONFLICT`.
  - CLI exit codes: `ReportLinkNotFoundError` → 4; `ReportLinkParseError`,
    `UnsupportedReportLinkError`, `ReportLinkScopeMismatchError`, and
    `BookmarkValidationError` → 3; `ShortLinkResolutionError` → 1.

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
