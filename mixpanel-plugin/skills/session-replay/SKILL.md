---
name: session-replay
description: Reads Mixpanel session replay recordings with the mixpanel_headless library. It fetches a user's sessions, turns them into action timelines and pandas DataFrames, and explains what happened on screen. Use when the user asks what a specific user did on screen, in a recording, or click by click; asks about rage clicks, dead clicks, rage taps, dead taps, error sessions, long pauses, or action timelines; wants to correlate a tracked event with on-screen behavior; gives a distinct_id or a replay ID and asks what happened in the session; or asks about iOS, Android, React Native, or Flutter recordings, screens, or taps. Do not use for aggregate analytics questions such as trends, funnels, retention, or segment counts (use mixpanelyst), or for building or editing dashboards (use dashboard-expert).
allowed-tools: Bash(${CLAUDE_PLUGIN_DATA}/venv/bin/python *) Bash(${CLAUDE_PLUGIN_DATA}/venv/bin/mp *) Bash(uv run *) Read Write Edit WebFetch(domain:mixpanel.github.io)
---

# Session replay

Session replay answers "what did this user actually do?". It gives the click-by-click story behind an analytics number. The library fetches the rrweb recordings (rrweb is the open-source format that Mixpanel uses to record sessions), runs an analyzer on them, and gives you DataFrames plus a text timeline of actions.

## Run code

The plugin keeps its own Python environment. Run the Python examples with `${CLAUDE_PLUGIN_DATA}/venv/bin/python script.py` or `${CLAUDE_PLUGIN_DATA}/venv/bin/python -c "..."`. `mp` below means `${CLAUDE_PLUGIN_DATA}/venv/bin/mp`; run it with that full path. Always write the full literal path, not a shell variable, because a variable expands to nothing and the command is denied.

If the interpreter path fails, the environment is not set up. Do not check again with `ls`, `which`, or shell variables: those commands are not allowed and prompt the user. Instead:

1. Ask the user to run `/mixpanel-headless:setup` before any analysis code.
2. For look-ups until then, run `mp --version` on its own.
3. If it shows 0.3.0 or later, run `mp help <query>` for look-ups. An older version gives wrong answers, so do not use it.

Do not run analysis code with a Python found on `PATH`, because it can hold a different library version or none at all. The one exception is a user's own project that already has mixpanel_headless (for example, a uv project), where `uv run python` works.

## Workflow

1. Fetch the sessions.
   - With a named user: call `ws.replays_for_user(distinct_id, from_date=..., to_date=...)`.
   - With replay IDs (for example, from the Mixpanel UI): call `ws.fetch_replays(replay_ids, include_mixpanel_events=True)`.
   - With neither: `ws.list_replays` needs a `distinct_id` or a list of `replay_ids`, and it refuses a date window alone. Find the candidate users first with the mixpanelyst skill (for example, the users who fired an error event). Then fetch each user's sessions.
2. Check the recording type of each replay: `replay.capture` is `"dom"` for a web recording and `"screenshot"` for a mobile or Flutter recording. If `capture == "screenshot"`, read [references/mobile.md](references/mobile.md) now, before you read any timeline.
3. Read the aggregates first (rage clicks or rage taps, errors, top targets). They count real events with real timestamps.
4. Read the timeline of the sessions that the aggregates point to.
5. Report what the user did, with timestamps and the names of the controls.

## Gotchas

- `t` in `mixpanel_df` is in Unix seconds. `t` in `actions_df` is in Unix milliseconds. Multiply the event time by 1,000 before you match events to actions.
- A timeline line that ends in `(×N)` shows the first timestamp only, so it hides how long the burst lasted. Take timing from `actions_df`, `rage_clicks()`, or `rage_taps()`.
- `rage_clicks()` counts clicks only. Mobile taps are not clicks, so it finds nothing in an iOS or Android recording. Use `rage_taps()` there.
- `ws.fetch_replay` and `ws.fetch_replays` do not join tracked events unless you pass `include_mixpanel_events=True`. `replays_for_user` joins them by default.

## Fetch the sessions

```python
import mixpanel_headless as mp

ws = mp.Workspace()

# Discovery, fetch, and the join of tracked events in one call.
bundle = ws.replays_for_user("user-42", from_date="2025-01-01", to_date="2025-01-31")

print(bundle.sessions_df)                    # one row per session
print(bundle.replays[0].capture)             # "dom" or "screenshot"
print(bundle.replays[0].summary_markdown)    # the action timeline
```

Each replay downloads its full byte stream, so `replays_for_user` fetches at most 20 replays by default. Raise `limit` only when the question needs more sessions. For a large sweep, list the replays first with `ws.list_replays(...)`, then read each one with `ws.stream_replay(...)`, which does not hold the whole stream in memory.

The result is a `ReplayBundle`. A single `Replay` from `ws.fetch_replay(replay_id)` has the same DataFrame projections. `bundle.sessions_df` has one row per session, with counts of clicks, inputs, pages, and errors. `bundle.actions_df` has one row per action. Its `description` column holds the full timeline phrase, and its `target_desc` column holds the bare element label. `bundle.mixpanel_df` holds the tracked Mixpanel events inside each session window. `bundle.elements_df` holds click counts per element, with URLs normalized so that `/boards#id=1` and `/boards#id=2` count as one page.

Filters return a new bundle and do not change the original: `where`, `filter`, `find_pattern`, `error_sessions`, `head`, and `sample`. Use `compare` to diff action frequencies between two bundles.

```python
print(bundle.top_clicks(10))      # most-clicked targets, genuine clicks only
print(bundle.rage_clicks())       # web: repeated clicks on one target in a short window
print(bundle.long_pauses())       # idle stretches between actions
errors = bundle.error_sessions()  # a new bundle: only replays with console errors
checkout = bundle.where(contains_url="/checkout", min_duration_s=60)
```

The CLI has the same surface under `mp replays`. `mp replays analyze <replay_id>` prints one timeline. `mp replays for-user <distinct_id> --from ... --to ...` does discovery and fetch in one command. The CLI `for-user` fetches up to 100 replays by default, not 20, so pass `--limit` for a quick look.

## Read a web timeline

`summary_markdown` prints one line per action as `{timestamp_seconds}: {description}`:

```text
1779693081: Navigated to https://app.example.com/boards
1779693457: Focused mp-button "hor-ellipsis"
1779693459: Clicked div in li "Refresh Data"
1779693483: Scrolled (×3)
```

- `(×N)` means N consecutive identical lines, collapsed into one. The line shows the first timestamp only, so it hides how long the run lasted. Take timing from `actions_df`.
- A real click makes both a `Focused` line and a `Clicked` line. `top_clicks()`, `rage_clicks()`, and `elements_df` leave out the focus-only actions, so each click counts once. Count clicks with these methods, not by counting timeline lines.
- `Console error: …` lines are JavaScript errors in the page. `error_sessions()` finds the replays that have them.
- Element text comes from what rrweb captured on the page (visible text, `aria-label`, `title`, `alt`). A label can be vague ("div in li") when the page has no accessible name for the element.

## Correlate a tracked event with the screen

`replays_for_user` joins the tracked Mixpanel events by default, so `bundle.mixpanel_df` shows the tracked events next to the on-screen actions. Pass `event_properties` (up to 5 property names) to bring event properties into the join. `ws.fetch_replay` and `ws.fetch_replays` do not join by default, so pass `include_mixpanel_events=True` to them. `bundle.join_mixpanel_events()` does not fetch anything: it only exposes events that the fetch already attached. For one replay that you already have, `ws.events_for_replay(replay_id)` returns its tracked events.

```python
bundle = ws.replays_for_user(
    "user-42",
    from_date="2025-01-01",
    to_date="2025-01-31",
    event_properties=["$browser", "plan"],
)
print(bundle.mixpanel_df)   # replay_id, t, event_name, properties
```

Match a tracked event to the actions near its timestamp in `actions_df`. Convert the units first (see Gotchas), or every event lands far from its actions.

## Report what you found

- State the evidence for each finding: the session, the timestamp, the control, and the count.
- Say when a finding is an inference. The analyzer infers some targets. It does not read them from the recording.
- A clean, successful flow is a valid finding. Report it as clean. Do not invent friction to make the answer look more useful, because the user will act on what you report.
- Replay explains individual sessions. It does not measure a population, so do not generalize from a handful of sessions to all users. For counts, trends, funnels, retention, or a rate across users, use the mixpanelyst skill.

## Credentials and privacy

Replay files sit behind signed CDN URLs. The query string of a signed URL is a bearer credential: anyone who has it can download the recording for about 5 minutes. `SignedReplay` masks it when printed, and the library does not log it. Keep it masked. Do not print `SignedReplay.to_dict()` or run `mp replays sign --reveal-signed-urls` unless the user asks for the raw URL, because the output can end up in logs, files, or chat history.

The timeline and the DataFrames contain page text that the recording captured, and that text can include personal data. Treat the output with the same care as the recording. Quote only what the answer needs.

A project with sensitive-data protection turned on refuses to sign replays for a caller without the matching permission. The library raises `SessionReplayAccessError`. Tell the user that the project owner must grant the permission that the error names. Another account works only if it has that permission, so do not cycle through accounts to get around the block.

## Look up the API

Do not guess method, parameter, or column names. The installed library documents itself, and its answer matches the installed version. See the look-up loop in the mixpanelyst skill. The commands used most for replay:

```text
mp help Workspace --domain "session replay"   # every replay method on Workspace
mp help ReplayBundle                          # projections, filters, aggregations
mp help Replay                                # one replay: capture, screen_path, page_path
mp help ReplayBundle.rage_taps                # parameters and output columns
mp help Workspace.replays_for_user            # the fetch call
```

For a tutorial with worked examples, fetch the guide: `WebFetch(url="https://mixpanel.github.io/mixpanel-headless/guide/session-replay/index.md")`.

## Mobile and screenshot recordings

Read [references/mobile.md](references/mobile.md) when `replay.capture == "screenshot"` (iOS, Android, React Native, and Flutter on mobile, web, and desktop). The web rules above give wrong answers for these recordings.
