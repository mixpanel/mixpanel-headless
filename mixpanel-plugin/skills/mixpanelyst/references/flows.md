# Flow queries: cardinality, windows, counting, and path noise

This file covers the analytical choices for `ws.query_flow()`: `cardinality`, the conversion window, `count_type`, `collapse_repeated`, hidden events versus exclusions, and the three modes.

Look up the exact names first:

```text
mp help Workspace.query_flow
mp help FlowStep
mp help FlowQueryResult
mp help FlowQueryResult.top_transitions
```

## Cardinality controls signal and noise

`cardinality` is the number of top paths to show at each step (default 3). It is the most important flow parameter. A low value (2 or 3) shows the dominant paths: the main story. A high value (10 or more) shows edge cases and niche journeys. Start low to find the narrative. Then raise it to find the exceptions.

## The conversion window matters for flows too

The concept is the same as for funnels. A session window (`conversion_window_unit="session"`) shows behavior inside one visit. A calendar window shows journeys over several days. A tight window isolates deliberate workflows. A wide window also catches exploratory wandering. The default is 7 days.

## Sweep before you choose

```python
import mixpanel_headless as mp

ws = mp.Workspace()
event = "Login"   # use a real anchor event

# Cardinality: low = clear narrative, high = complete but noisy.
for card in [2, 3, 5, 10]:
    result = ws.query_flow(event, forward=3, cardinality=card, last=30)
    print(f"\ncardinality={card}")
    for src, dst, count in result.top_transitions(3):
        print(f"  {src} -> {dst}: {count}")

# Counting: unique = how many people, total = how much activity.
for count_type in ["unique", "total"]:
    result = ws.query_flow(event, forward=3, count_type=count_type, last=30)
    for step, info in result.drop_off_summary().items():
        print(f"{count_type} {step}: {info['rate']:.0%} drop-off")

# Session counting needs a session window.
result = ws.query_flow(
    event, forward=3, count_type="session",
    conversion_window=1, conversion_window_unit="session", last=30,
)

# Repeats: compare raw behavior with simplified intent.
for collapse in [False, True]:
    result = ws.query_flow(
        event, forward=3, collapse_repeated=collapse, cardinality=5, last=30
    )
    print(f"\ncollapse_repeated={collapse}")
    for src, dst, count in result.top_transitions(3):
        print(f"  {src} -> {dst}: {count}")
```

`top_transitions()` returns `(source, target, count)` tuples. Each node name has the form `"{event}@{step}"`, for example `"Login@0"`. `drop_off_summary()` returns a dict keyed by step (`"step_0"` …), with `total`, `dropoff`, and `rate`.

## Counting is a modeling choice

`count_type="unique"` (default) answers "how many people?". `"total"` answers "how much activity?". `"session"` answers "how many visits?", and it requires `conversion_window_unit="session"`.

## `collapse_repeated` changes what a path is

With `False` (default), A→A→A→B is a different path from A→B, so repeated clicks look like separate journeys. With `True`, Mixpanel merges consecutive duplicates. This shows intent instead of noise. Look at both: the raw behavior and the simplified intent.

## Hidden events and exclusions are different

- `hidden_events` removes events from the display. They still affect the path structure and the counts. Use it to remove clutter, for example page views that occur everywhere.
- `exclusions` is expected to be a stronger operation: it removes the users who did those events, not only the events. The library docstring says only "exclude from flow paths", so this is not confirmed. Use it to remove spoiled journeys, for example users who churned in the middle of the flow. Before you report numbers that depend on the difference, run the query both ways and compare the counts.

Unlike funnel exclusions, flow `exclusions` takes plain event names only.

## Three modes show different stories

- `sankey` (default): aggregate flow structure and bottlenecks. Where do most users go?
- `paths`: exact user journeys in sequence. What are the top complete paths?
- `tree`: branch points. Where do users diverge? `result.anytree` gives the tree roots.

Use all three on the same data to build a complete picture. `result.graph` is a NetworkX directed graph of the sankey data.

## Other rules

- `FrequencyFilter` does not work in `query_flow()`. It fails with an unclear error. Use `where` with `Filter` values only.
- `forward` and `reverse` set the default number of steps after and before each anchor. `FlowStep` overrides them for one anchor.
