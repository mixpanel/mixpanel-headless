# Changelog

All notable changes to `mixpanel-headless` are recorded here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver but is currently pre-1.0, so minor versions
may include API changes.

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
