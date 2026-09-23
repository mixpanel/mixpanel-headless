# Exploring an unfamiliar project and finding insights

This file gives a systematic workflow for "find insights", "look around", or a project you do not know yet: map the schema, classify properties, scan segments, and check each finding across dimensions.

**Contents**

- [Step 1: Map the event schema](#step-1-map-the-event-schema)
- [Step 2: Classify the properties](#step-2-classify-the-properties)
- [Step 3: Scan for significant segments](#step-3-scan-for-significant-segments)
- [Step 4: Check a finding across dimensions](#step-4-check-a-finding-across-dimensions)
- [Step 5: Clean up messy string properties](#step-5-clean-up-messy-string-properties)

Explore first. Do not go straight to queries: a query on a property that an event does not carry returns an empty or zero result, not an error.

Look up the discovery methods with `mp help Workspace --domain discovery`.

## Step 1: Map the event schema

Start with `schema_graph()`. One call returns the whole map of events to properties, and with `include_density=True` it adds the coverage of each property (`density_local`). You learn which properties travel with which events, and how well each is populated, before you query. This is the most useful grounding step.

```python
import mixpanel_headless as mp

ws = mp.Workspace()
schema = ws.schema_graph(include_density=True)
print("events:", schema.meta["event_count"],
      "| event properties:", schema.meta["event_property_count"])

# One row per (event, property), with coverage.
print(schema.relationships_df.head(20))   # event | property | density_local

# Exact properties on each event. Use these names verbatim in queries.
for event_name in list(schema.event_to_properties)[:5]:
    print(f"\n{event_name}: {schema.properties_for_event(event_name)}")

# Properties attached to no event are usually noise. Skip them.
print("\nOrphans:", schema.orphan_properties()[:20])

# Today's most active events (real time, today only).
top = ws.top_events(limit=15)
print("\nTop today:", [(e.event, e.count) for e in top])
```

`top_events()` covers today only. For volume over a period, query the events with `ws.query(..., mode="total")`.

Then sample values for the properties that you plan to group or filter by:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
schema = ws.schema_graph(include_density=True)
for prop in schema.properties_for_event("Purchase")[:15]:   # use a real event
    print(prop, ws.property_values(prop, event="Purchase", limit=10))
```

## Step 2: Classify the properties

Infer the type of each property from its sampled values. The type decides how you use it:

- **Boolean**: values are `true` and `false`. Use it in `group_by`. These are often pre-computed behavioral flags.
- **Low-cardinality categorical** (fewer than 10 values): `platform`, `tier`, `category`. Use it in `group_by`.
- **Numeric**: the values parse as numbers: `price`, `total`, `count`. Use `math="average"` or `math="median"` with `math_property`, or `math="total"` with `math_property` for a sum.
- **High-cardinality** (more than 100 values): IDs, names. Do not use it in `group_by`. It can need cleanup with a custom property.
- **Temporal**: ISO dates or epoch values. Use it for time-based analysis.

Name patterns that signal analytical value:

- `is_*`, `has_*`, `was_*`, `post_*`: boolean flags, often pre-computed segments worth a look.
- `*_total`, `*_count`, `*_value`, `*_amount`: numeric. Aggregate with average, median, or sum.
- `*_name`, `*_type`, `*_category`, `*_tier`: categorical. Use for breakdowns.
- `*_id`, `*_uuid`: identifiers. Skip for breakdowns.

## Step 3: Scan for significant segments

For each boolean or low-cardinality property on a key event, run a breakdown against a numeric metric:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
event = "Purchase"           # use a real event
numeric_prop = "order_total" # use the key numeric metric
schema = ws.schema_graph()
candidates = [p for p in schema.properties_for_event(event)
              if not p.endswith(("_id", "_uuid"))]

for prop in candidates[:15]:
    values = ws.property_values(prop, event=event, limit=11)
    if len(set(values)) <= 10:   # an 11th value means high cardinality: skip
        result = ws.query(event, math="average", math_property=numeric_prop,
                          group_by=prop, last=90, mode="total")
        print(f"\n{numeric_prop} by {prop}:")
        print(result.df.to_string(index=False))
# Flag segments where the metric differs by more than 15% from the overall value.
```

Averages hide outliers. When a segment stands out, repeat the breakdown with `math="median"` before you report it.

## Step 4: Check a finding across dimensions

When a breakdown shows a notable difference (more than 15% between segments):

1. **Quantify.** Calculate the exact ratio between the segments.
2. **Cross-reference.** Check whether the segment differs on other metrics too.
3. **Investigate the cause.** Run funnels or retention filtered to the segment.
4. **Control for confounds.** Add a second `group_by` dimension and check that the effect holds.

```python
import mixpanel_headless as mp

ws = mp.Workspace()
event = "Purchase"   # use real names throughout

# 1. The segment that stands out.
first = ws.query(event, math="average", math_property="order_total",
                 group_by="deal_sweet_spot", last=90, mode="total")
# Example finding: deal_sweet_spot=true has a 37% higher order value.

# 2. Does it hold on both platforms?
second = ws.query(event, math="average", math_property="order_total",
                  group_by=["deal_sweet_spot", "platform"], last=90, mode="total")

# 3. Which loyalty tier reaches the sweet spot most often?
third = ws.query(event, math="unique",
                 group_by=["loyalty_tier", "deal_sweet_spot"], last=90, mode="total")
```

## Step 5: Clean up messy string properties

Some string properties have complex or unreadable values, for example campaign names from tools like Braze:

1. Sample 15 to 20 values to find the naming convention.
2. Look for structural patterns: date codes, targeting prefixes, channel suffixes, audience tags.
3. Design one regex cleanup rule for each structural element.
4. Try the formula in a query with an `InlineCustomProperty` in `group_by`.
5. When the output is clean, save it with `ws.create_custom_property(...)` and check it again as a `group_by`.

Before you write the formula, read about the formula language and its regex quirks (see the reading guide in `SKILL.md`).
