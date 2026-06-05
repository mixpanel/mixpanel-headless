# Session Replay

Discover a user's [Mixpanel Session Replay](https://docs.mixpanel.com/docs/session-replay) recordings, fetch the raw rrweb event stream from the signed CDN, and project the sessions into analysis-ready pandas DataFrames plus an LLM-friendly action timeline — all without leaving Python or the shell.

!!! tip "The high-leverage type is `ReplayBundle`"
    A `ReplayBundle` is a collection of replays with cross-session projections. A single `Replay` is conceptually a bundle of size one, and the API treats them the same way — every DataFrame projection available on a bundle is available on a replay.

## When to Use It

Session replay answers "what did this user actually *do*?" — the click-by-click story behind an analytics number. Reach for it when you need to:

- Pull a specific user's recent sessions and read the timeline (`replays_for_user`).
- Correlate a tracked Mixpanel event with the on-screen actions around it (`include_mixpanel_events`).
- Rank the most-clicked elements, find rage-click bursts, or surface sessions with console errors across many replays.
- Export the raw rrweb stream to feed Mixpanel's JS player or your own tooling (`to_rrweb_player_json`).

The surface is built on the same signed-CDN endpoints Mixpanel's own MCP server uses. It does **not** persist anything to disk — signed URLs are time-bounded bearer credentials handled in process.

## Getting Started

The one-call path — discover a user's replays, fetch them, and join the Mixpanel events that fired during each session:

```python
import mixpanel_headless as mp

ws = mp.Workspace()

bundle = ws.replays_for_user(
    "user-42",
    from_date="2025-01-01",
    to_date="2025-01-31",
)

# One row per session: duration, action/click/error counts, entry/exit URL
print(bundle.sessions_df)

# The LLM-friendly action timeline for the first replay
print(bundle.replays[0].summary_markdown)
```

`replays_for_user` defaults `limit=20` (each replay materializes its full byte stream, so fetching is byte-heavy) and `include_mixpanel_events=True`. Raise `limit` deliberately, or drop to `list_replays` + `stream_replay` for large sweeps.

## Discovery

`list_replays` issues a single Insights query against `$mp_session_record` and returns lightweight `ReplaySummary` handles (no bytes fetched). Discover by user and date window, or hydrate an explicit list of IDs:

```python
# By user (from_date / to_date required)
summaries = ws.list_replays(
    distinct_id="user-42",
    from_date="2025-01-01",
    to_date="2025-01-31",
    limit=100,
)
for s in summaries:
    print(s.replay_id, s.start_time, s.retention_days)

# Or hydrate explicit replay IDs (no distinct_id needed)
summaries = ws.list_replays(replay_ids=["0190ebde-d50d-71b1-804c-ec1b4a533ef9"])
```

An empty window returns an empty list — it never raises. Each summary carries the per-replay `retention_days` (read from `$mp_replay_retention_period`, defaulting to 30 with a warning when the property is absent).

## Fetching a Single Replay

`fetch_replay` signs the replay, walks the CDN files in parallel, runs the vendored rrweb analyzer, and returns a fully-materialized `Replay`:

```python
replay = ws.fetch_replay(
    "0190ebde-d50d-71b1-804c-ec1b4a533ef9",
    include_mixpanel_events=True,   # optional Mixpanel-event join
)

print(replay.duration_seconds)          # 2769.0
print(len(replay.rrweb_events))         # raw rrweb events
print(replay.summary_markdown)          # action timeline
print(replay.page_path())               # navigation URL sequence

# Raw rrweb JSON, timestamp-sorted, ready for the rrweb JS player
player_json = replay.to_rrweb_player_json()
```

Pass `retention_days=` to skip the retention-discovery round trip when you already know it, and `distinct_id=` to stamp the owning user onto the returned `Replay` (`replays_for_user` does this for you).

### Streaming large recordings

For long sessions where you don't want the whole byte stream in memory at once, `stream_replay` yields rrweb events one batch at a time and re-signs transparently if the URL expires mid-walk:

```python
for event in ws.stream_replay("0190ebde-d50d-71b1-804c-ec1b4a533ef9"):
    process(event)
```

## DataFrame Projections

A `ReplayBundle` (and a single `Replay`) exposes long-format projections keyed by `replay_id`. `bundle.df` defaults to `sessions_df`.

| Projection | Grain | Key columns |
|---|---|---|
| `sessions_df` | one row per replay | `replay_id`, `distinct_id`, `start_time`, `end_time`, `duration_s`, `retention_days`, `n_events`, `n_actions`, `n_clicks`, `n_inputs`, `n_pages`, `n_errors`, `n_mp_events`, `entry_url`, `exit_url` |
| `actions_df` | one row per normalized action | `replay_id`, `t`, `action`, `target_node_id`, `target_desc`, `description`, `url`, `metadata` |
| `events_df` | one row per raw rrweb event | `replay_id`, `t`, `type`, `source`, `mouse_type`, `target_node_id`, `url`, `raw` |
| `mixpanel_df` | one row per Mixpanel event in the replay window | `replay_id`, `t`, `event_name`, `properties` |
| `elements_df` | one row per `(target_desc, normalized_url)` | `target_desc`, `url`, `n_clicks`, `n_unique_replays` |

```python
# Feed directly into DuckDB, or any pandas workflow
import duckdb
duckdb.from_df(bundle.actions_df).aggregate("action, count(*)", "action").show()
```

The `description` column on `actions_df` is the analyzer's full human-readable phrase (`'Clicked button "Sign in"'`, `'Scrolled'`, `'Console error: …'`); `target_desc` is the bare element label.

## The Action Timeline

`summary_markdown` renders a compact, LLM-friendly timeline — one line per action as `{timestamp_seconds}: {description}`, with consecutive duplicate actions collapsed into a `(×N)` suffix so a re-rendering data grid doesn't flood the output:

```text
1779693081: Navigated to https://app.example.com/boards
1779693457: Focused mp-button "hor-ellipsis"
1779693459: Clicked div in li "Refresh Data"
1779693483: Scrolled (×3)
```

`bundle.summary_markdown` concatenates the per-replay timelines with a totals header. The `mp replays analyze` CLI command renders the same output.

## Aggregations

Bundle-level aggregations return DataFrames (following the `FlowQueryResult` idiom):

```python
print(bundle.top_clicks(10))      # target_desc, count — genuine clicks only
print(bundle.rage_clicks(threshold=3, window_ms=1000))  # replay_id, t_start, target_desc, count
print(bundle.long_pauses(threshold_s=10))               # replay_id, t_start, duration_s
err = bundle.error_sessions()     # a NEW bundle of only the replays with console errors
```

`top_clicks` (and `elements_df`) count **genuine clicks only** — a real user click fires both a `focused` and a `clicked` interaction, and counting both would double every click, so the focus-only interactions are excluded.

## Filters and Comparison

Filters return a **new** bundle (immutable semantics) — the original is untouched, so chains stay cheap:

```python
# Sessions that visited /checkout AND lasted longer than 60s
checkout = (
    bundle
    .where(contains_url="/checkout")
    .filter(lambda r: r.duration_seconds > 60)
)

# Deterministic sample for manual review
for r in checkout.sample(n=3, seed=42).replays:
    print(r.summary_markdown[:200], "…")

# Sessions whose action labels contain a contiguous sub-sequence
matched = bundle.find_pattern(["click:button@/", "navigate:…@/checkout"])

# Diff action frequencies between two cohorts of sessions
converters = ws.replays_for_user("user-99", from_date="2025-01-01", to_date="2025-01-31")
print(bundle.compare(converters))   # action | self_count | other_count | delta
```

`where(...)` accepts `distinct_id`, `contains_url`, `has_event`, `min_duration_s`, and `max_duration_s`. `find_pattern` accepts a `label_fn=` override (see `default_label_fn` / `selector_label_fn`).

## Correlating Mixpanel Events

`mixpanel_df` is populated when you fetch with `include_mixpanel_events=True` (the default for `replays_for_user`), or lazily via `join_mixpanel_events()`. It holds the tracked Mixpanel events that fired during each replay's time window — the analytics layer alongside the action layer:

```python
bundle = ws.replays_for_user(
    "user-42", from_date="2025-01-01", to_date="2025-01-31",
    event_properties=["$browser", "plan"],   # up to 5 extra properties
)
print(bundle.mixpanel_df)   # replay_id | t | event_name | properties
```

For a single replay or an explicit ID list, use `events_for_replay(replay_id)` / `events_for_replays(replay_ids)`.

## Signed URLs and Security

Replay files live behind a time-bounded signed CDN URL (≈5-minute TTL). The query string is a **bearer credential**:

- `SignedReplay` masks the credential in `repr` and `str`, and the library **never logs it** at any level.
- `sign_replay` / `sign_replays` return the handles; `fetch_replay` signs and fetches in one step.
- A 403 indicating the project's `SESSION_RECORDING_SENSITIVE_DATA` flag raises `SessionReplayAccessError` with the missing permission in `details`. An expired URL raises `SignedURLExpiredError`; a replay absent from the CDN raises `ReplayNotFoundError`.

```python
signed = ws.sign_replay("0190ebde-d50d-71b1-804c-ec1b4a533ef9")
print(signed)   # SignedReplay(replay_id='…', url='…', query_string='<redacted N chars>', …)
```

## CLI

The `mp replays` command group mirrors the Python surface:

```bash
# Discover a user's replays (or hydrate explicit --replay-id values)
mp replays list --user user-42 --from 2025-01-01 --to 2025-01-31

# Mixpanel events during a replay's window
mp replays events --replay-id 0190ebde-d50d-71b1-804c-ec1b4a533ef9

# Sign for CDN access — redacted by default; --reveal-signed-urls opts in
mp replays sign --replay-id 0190ebde-d50d-71b1-804c-ec1b4a533ef9

# Write the raw rrweb JSON (rrweb-player compatible)
mp replays fetch 0190ebde-d50d-71b1-804c-ec1b4a533ef9 -o replay.json

# Render the markdown action timeline
mp replays analyze 0190ebde-d50d-71b1-804c-ec1b4a533ef9

# Discover + fetch + analyze in one command; write per-replay timelines to a dir
mp replays for-user user-42 --from 2025-01-01 --to 2025-01-31 \
    --include analyze --out-dir ./timelines
```

`mp replays sign --reveal-signed-urls` is the single opt-in path to emitting the full credential; it prints a stderr warning on every invocation.

## See Also

- [API Reference: Workspace → Session Replay](../api/workspace.md#session-replay)
- [API Reference: Session Replay Types](../api/types.md#session-replay-types)
- [API Reference: Session Replay Exceptions](../api/exceptions.md#session-replay-exceptions)
