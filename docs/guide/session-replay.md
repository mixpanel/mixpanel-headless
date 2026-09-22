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
- Read mobile app sessions (iOS, Android, React Native, Flutter) as screens, taps, and rage-tap bursts (see [Mobile and Screenshot Replays](#mobile-and-screenshot-replays)).

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

## Mobile and Screenshot Replays

The iOS (`swift-sr`), Android (`android-sr`), React Native, and Flutter SDKs record sessions differently from the JavaScript SDK. They have no DOM to record. Each screen goes into the stream as a screenshot image. When the SDK has wireframes turned on, each screen also goes in as a *wireframe*: a flat list of the screen's elements (role, text, and bounds). Flutter makes screenshot recordings on every target: mobile, web, and desktop.

The analyzer reads these recordings too. The same `fetch_replay`, `replays_for_user`, and `mp replays analyze` calls work, with no options to set.

### Detecting a screenshot recording

`Replay.capture` tells you which kind of recording you have:

- `"screenshot"` — the stream has at least one `mp_wireframe` event, or it has Meta events and none of them carries a page URL (`href`). Every mobile and Flutter SDK sends Meta events without `href`.
- `"dom"` — every other replay, including a replay with no Meta event. Web replays give the same output as before.

The analyzer decides the recording type once, before it reads the events. So a touch that comes before the first wireframe (common on iOS) is still read as a mobile tap.

```python
replay = ws.fetch_replay("a436a4ec-076b-4a14-851c-b6a80f7c6fdc")

print(replay.capture)          # "screenshot"
print(replay.has_wireframes)   # True
print(replay.screen_path())    # ["Home", "Settings"]
print(replay.page_path())      # [] — screenshot recordings have no URLs
```

`has_wireframes` is `False` for a screenshot recording made with wireframes turned off. That replay still gives taps, scrolls, and clicks, but no screens, and every tap target is a bare point.

### Reading the timeline

A screenshot recording gives four kinds of timeline lines:

```text
1789482332: Wireframe: Home [16,38,54,27] | text [363,27,48,48] | This is home Fragment [8,88,395,27] | button:View Jokes (Compose) [98,155,215,48] | …
1789482352: Tapped at (383, 51)
1789482353: Wireframe: Settings [72,38,76,27] | image [0,24,56,56] | button:Re-initialize Session Replay [16,100,379,40] | Current Status: [16,168,94,20] | Initialized ✓ [16,192,76,20] | text [363,27,48,48]
1789482354: Tapped at (182, 142)
```

(The first `Wireframe:` line is cut short here; the analyzer prints every element.)

**`Wireframe:` lines** (action `"screen"`) show one screen. Elements are separated by `|`, in the order the SDK sent them:

- A bare label is a text element: `Home`.
- `role:label` is any other role: `button:Save`, `input:Email`, `image`, `switch`. The roles seen in real recordings are `text`, `image`, `button`, `input`, and `switch` (React Native).
- An element with no label shows its role only: `text [363,27,48,48]` is an unlabeled text element, usually an icon.
- `[x,y,w,h]` is the element's rect in logical pixels, from the top-left corner. An element with no usable bounds has no rect.

A label is cut at 50 characters with `…`, and a `|` inside a label becomes `/` so the separator stays clear. Masked text has no label: iOS omits it and Android sends `null`.

**Screens are keyframes, not a continuous record.** The analyzer keeps the screen that was showing when each gesture started, and up to two screens after the gesture ended. Consecutive identical screens appear once. A replay with no gestures shows its first and last screen. This keeps animation frames out of the timeline, but it also means that something can happen between two screens without a line of its own.

**`Tapped at (x, y)`** (action `"touch_start"`, `metadata["interaction"] == "tapped"`) is a touch that moved 10 px or less before the finger lifted. **`Scrolled`** (action `"scroll"`) is a touch that moved farther. A touch that the system cancelled gives no line. The analyzer classifies each touch when the finger lifts, so the tap timestamp is the lift time.

**`Clicked at (x, y)`** (action `"click"`) is a mouse click in a Flutter web or desktop recording. These clicks count in `top_clicks()`, `rage_clicks()`, and `n_clicks`, the same as web clicks. Mobile taps do not: they are `touch_start` actions.

Consecutive identical lines collapse into `(×N)`, as they do for web replays. Seven taps at one point become `Tapped at (257, 638) (×7)`. The collapsed line shows the timestamp of the first tap only, so it hides how long the burst lasted. Use `rage_taps()` (below) for real burst timing.

### What a tap hit

The description always shows the point. The structured action says which element the point hit. The analyzer hit tests each tap and click against the screen that was showing at finger-down:

1. Elements whose rect contains the point are candidates. A non-text role (a button or an input) wins over a text element, and then the smallest rect wins. `metadata["attribution"]` is `"bounds"`.
2. With no containing rect, the nearest element within 8 px wins. Real taps often land just outside a button edge. `metadata["attribution"]` is `"bounds_slop"`.
3. With no element near the point, `target_desc` is the point, `"(x, y)"`, and there is no `metadata["hit"]`.

`target_desc` names the hit element: the bare label for text, `role:label` for other roles, or `role [x,y,w,h]` for an element with no label. `metadata["hit"]` holds the element's `role`, `text`, and `bounds`.

```python
for a in replay.actions:
    if a.action == "touch_start":
        print(a.description, "→", a.target_desc, a.metadata.get("attribution"))
# Tapped at (383, 51) → text [363,27,48,48] bounds
# Tapped at (182, 142) → button:Re-initialize Session Replay bounds_slop
```

Rects can overlap, so a hit is an inference, not a fact the SDK sent.

To rank tapped elements across mobile replays, group the tap actions yourself:

```python
taps = bundle.actions_df.query("action == 'touch_start'")
print(taps.groupby("target_desc").size().sort_values(ascending=False).head(10))
```

### Screen headings and fingerprints

The SDKs send no screen name. For each `"screen"` action, `target_desc` is an **approximate heading**: the label of the top-most labeled text element on screen (smallest `y`, then smallest `x`). A screen with no labeled text, for example a fully masked one, gets `"(screen)"`. The heading can be a clock, a back button label, or the same title on several different screens. Treat it as a hint, not an identity.

`metadata["fingerprint"]` is a short hash of the rendered `Wireframe:` line, so identical screens share it. Use the fingerprint to count screen visits, and the heading to label them. Screen metadata also holds `elements` (the parsed element list), `viewport`, `scale`, and `element_count`.

`ReplayBundle.screens_df` has one row per screen: `replay_id`, `t`, `heading`, `fingerprint`, `element_count`, and `description`.

```python
visits = (
    bundle.screens_df
    .groupby("fingerprint")
    .agg(heading=("heading", "first"), visits=("replay_id", "size"))
    .sort_values("visits", ascending=False)
)
print(visits.head(3))
```

`default_label_fn` gives screen labels such as `screen:Home@(no-url)`, so `find_pattern` works on mobile sequences too.

### Coordinate scaling

Tap points use the coordinate space of the Meta event. Some Android SDK builds send wireframe bounds in physical pixels (for example, a 1080-wide viewport on a 411-wide screen). When the wireframe `viewport` width differs from the Meta width by more than 5%, the analyzer multiplies the bounds by `meta_width / viewport_width` before it hit tests. `metadata["scale"]` records the factor (`1.0` when the spaces match), and `metadata["elements"]` holds the scaled bounds. The `Wireframe:` description keeps the raw bounds. An element whose rect is fully outside the screen width gets `"offscreen": True`, and the heading and the hit test ignore it.

### Rage and dead taps

`ReplayBundle.rage_taps()` finds bursts of taps near one point in screenshot recordings:

```python
print(bundle.rage_taps())   # threshold=3, window_ms=2000, radius_px=24, grace_ms=1000
#    replay_id        t_start          t_end  ...    y  count  kind
# 0  81cf456f…  1789663316578  1789663317798  ...  638     20  rage
# 1  81cf456f…  1789663335106  1789663336038  ...  368     33  rage
# 2  81cf456f…  1789663345601  1789663346674  ...  678     39  dead
```

A burst is `threshold` or more finger-downs within `window_ms` of the first one and within `radius_px` of its point. The method counts finger-downs from `rrweb_events` (touch starts, plus clicks in Flutter web and desktop), not the `Tapped` lines. When fingers overlap in a fast burst, many finger-downs produce only a few classified taps. In the example above, 20 finger-downs produce only 8 `Tapped` lines.

Each burst is classified by the screen changes from its first finger-down to `grace_ms` after its last one:

- **`"dead"`** — the screen never changed. The control did nothing.
- **`"rage"`** — the screen changed once or a few times while the user kept tapping.
- **Intentional, not reported** — the screen changed for each tap, or for all taps but one. A quantity stepper or a carousel works this way.

The columns are `replay_id`, `t_start`, `t_end` (Unix ms), `target_desc` (the hit-test target at the first finger-down), `x` and `y` (the first finger-down point), `count`, and `kind`. Web replays give no rows: use `rage_clicks()` for them.

### Limits

- **Headings are approximate.** Two different screens can share a heading, and one screen can get a different heading after a small change. Use the fingerprint for identity.
- **Masked text is gone.** A masked label is not in the recording, so a masked screen has only roles and rects, and its heading is `"(screen)"`.
- **Some screens are mid-animation.** An "after" screen can be a frame from the middle of a transition. Its elements can have negative `x` or sit past the right edge.
- **`(×N)` hides the time span.** A collapsed line shows the first timestamp only. Use `rage_taps()` or `actions_df` for real timing.
- **No URLs.** `url` is `None`, `page_path()` is empty, and `where(contains_url=...)` matches nothing. Use `screen_path()` instead.

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

!!! warning "DOM text can carry PII"
    The analyzer's `target_desc` and `description` fields surface text that
    rrweb captured from the page — `aria-label`, `title`, `alt`, and visible
    element text. If a recorded page rendered personal data (e.g. a
    `"Welcome, Jane Doe"` heading), that text lands in `actions_df`, the
    markdown timelines, and anything you build from them (logs, files, LLM
    context). The library faithfully reflects what rrweb recorded — it does
    not scrub content — so treat analyzer output with the same care as the
    underlying recording, and rely on Mixpanel's recording-side masking to
    keep sensitive fields out of the capture in the first place.

## CLI

The `mp replays` command group mirrors the Python surface:

```bash
# Discover a user's replays (or hydrate explicit --replay-id values)
mp replays list --user user-42 --from 2025-01-01 --to 2025-01-31

# Mixpanel events during a replay's window
mp replays events 0190ebde-d50d-71b1-804c-ec1b4a533ef9

# Sign for CDN access — redacted by default; --reveal-signed-urls opts in
mp replays sign 0190ebde-d50d-71b1-804c-ec1b4a533ef9

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
