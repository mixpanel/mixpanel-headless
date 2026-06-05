# Changelog

All notable changes to `mixpanel-headless` are recorded here. The format
loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/);
this project follows semver but is currently pre-1.0, so minor versions
may include API changes.

## Unreleased — Session Replay (044, PRs 1–3)

### Added (PR 1 — Phase 1: discovery + signed CDN access)

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
  `SignedURLExpiredError`, `ReplayNotFoundError`. CLI exit-code mapping
  added: sensitive-data → 2, replay-not-found → 4.
- New CLI commands: `mp replays list`, `mp replays events`,
  `mp replays sign` (with `--reveal-signed-urls` opt-in that emits a
  stderr warning on every invocation), `mp replays fetch [-o FILE]`.
- Depends on the undocumented `/app/projects/<id>/replays/sign[/bulk]`
  endpoint — the same endpoint Mixpanel's own MCP server uses.

### Added (PR 2 — Phase 2: analyzer + ReplayBundle)

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

### Security

- `SignedReplay.query_string` is a 5-minute bearer credential and is
  masked in `__repr__`/`__str__`. The `--reveal-signed-urls` CLI opt-in
  emits a stderr warning on every invocation (FR-008/9). The pre-merge
  security audit greps the source tree for `Signature=` / `URLPrefix=`
  / `Expires=`; no leaks were found.

### Notes

- Mobile session replays are detected by the CDN walker (first event
  lacks rrweb's `type`/`data`/`timestamp` keys) and surface as a
  forward-compat `NotImplementedError` per error-messages.md §9.
- Live integration tests (`tests/integration/test_replays_live.py`) are
  marked `@pytest.mark.live` and deselected by default; set
  `MP_LIVE_TESTS=1` plus `MP_REPLAY_FIXTURE_DISTINCT_ID` to run them
  against a fixture project.
