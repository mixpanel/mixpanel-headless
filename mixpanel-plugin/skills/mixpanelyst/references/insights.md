# Insights queries: math, per-user aggregation, and the unit of analysis

This file covers the analytical choices for `ws.query()`: which math to use, what `per_user` does, and the defaults that change a result without a warning.

**Contents**

- [Math is the main choice](#math-is-the-main-choice)
- [Prefer medians to averages](#prefer-medians-to-averages)
- [Per-user aggregation changes the unit of analysis](#per-user-aggregation-changes-the-unit-of-analysis)
- [Sweep the math to see an event from several angles](#sweep-the-math-to-see-an-event-from-several-angles)
- [Defaults and rules that change a result](#defaults-and-rules-that-change-a-result)
- [Result shape](#result-shape)

Look up the exact names first:

```text
mp help Workspace.query
mp help Workspace.query.math        # allowed MathType values
mp help PerUserAggregation
mp help Metric
```

## Math is the main choice

The `math` parameter decides what you count. The wrong math answers a different question, and the query still succeeds. Match math to the business question:

| Question | Math |
| --- | --- |
| How much activity (intensity)? | `total` (event count) |
| How many people (adoption, reach)? | `unique` |
| How engaged over time? | `dau`, `wau`, `mau` |
| What is a typical value of a property? | `median`, `p25` … `p99`, or `percentile` with `percentile_value` |
| What is the mean value of a property? | `average` |
| What is the sum of a property (revenue)? | `total` with `math_property` |

There is no `sum` math. To add up a numeric property, use `math="total"` with `math_property`. Without a property, `total` counts events. With a property, it sums the property.

`math="percentile"` needs `percentile_value` (for example `95`). The fixed percentiles `p25`, `p75`, `p90`, `p99` need no extra value.

## Prefer medians to averages

An average includes outliers. One extreme value moves the whole metric. Use `math="median"` (or `percentile` with `percentile_value=50`) to see the typical value. If the mean and the median are far apart, the distribution is skewed and the mean misleads.

## Per-user aggregation changes the unit of analysis

`per_user` is a two-stage calculation. First Mixpanel aggregates each user's events. Then it applies `math` across users. `per_user="average"` with `math="average"` gives the average of each user's average. This is not the global average: a user with 1,000 events and a user with 2 events count the same.

This is often the correct choice, because it stops power users from dominating the metric. But it changes the result a lot, so compare both:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
event = "Purchase"      # use a real event name
prop = "order_total"    # use a real numeric property

global_avg = ws.query(event, math="average", math_property=prop, last=30, mode="total")
per_user_avg = ws.query(
    event, math="average", math_property=prop, per_user="average", last=30, mode="total"
)
print(f"Global avg:   {global_avg.df['count'].iloc[0]:.2f}")
print(f"Per-user avg: {per_user_avg.df['count'].iloc[0]:.2f}")
# A large gap means that power users skew the global average.
```

Rules the validator enforces before any network call:

- `per_user` requires `math_property`.
- `per_user` does not work with `unique`, `dau`, `wau`, or `mau`.
- `math="histogram"` requires `per_user`.

## Sweep the math to see an event from several angles

```python
import mixpanel_headless as mp

ws = mp.Workspace()
event = "Purchase"      # use a real event name
prop = "order_total"    # use a real numeric property

sweeps = [
    ("events", {"math": "total"}),
    ("users", {"math": "unique"}),
    ("daily users", {"math": "dau"}),
    ("mean value", {"math": "average", "math_property": prop}),
    ("median value", {"math": "median", "math_property": prop}),
    ("sum of value", {"math": "total", "math_property": prop}),
]
for label, kwargs in sweeps:
    result = ws.query(event, last=30, mode="total", **kwargs)
    print(f"{label:>13}: {result.df['count'].iloc[0]:>14,.2f}")
```

## Defaults and rules that change a result

- **`math_property` with count math is an error.** A top-level `math_property` with `unique`, `dau`, `wau`, or `mau` raises `BookmarkValidationError` before the query runs. The same applies to `Metric(..., property=...)`. Only `total` accepts a property as an option.
- **`CohortMetric` ignores math.** For a `CohortMetric` entry, `math`, `math_property`, and `per_user` have no effect. Cohort size is always a count of unique users.
- **`rolling` reduces the number of points.** A 30-day rolling window over 59 days gives 30 points, not 59. There is no warning.
- **`rolling` and `cumulative` are mutually exclusive.**
- **`unit` has no effect when `mode="total"`.** A total is one number for the whole range.
- **`last=` is always a number of days**, whatever the `unit`. To query a calendar month, use `from_date` and `to_date`.
- **A breakdown is capped.** The default segment cap is 3,000. For a high-cardinality `group_by`, raise `limit` and check `result.meta["is_segmentation_limit_hit"]`.
- **A formula needs two or more events.** `formula="(B / A) * 100"` refers to events by their position (A, B, C …).

## Result shape

`result.df` has these columns:

- Timeseries: `date`, `event`, `count`.
- Total: `event`, `count`.
- With `group_by`: a `segment` column is added.

Confirm with `mp help QueryResult`.
