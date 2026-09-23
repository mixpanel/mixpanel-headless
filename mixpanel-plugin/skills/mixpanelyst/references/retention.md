# Retention queries: the cohort bucketing triple and the counting choice

This file covers the analytical choices for `ws.query_retention()`: `retention_unit`, `alignment`, `bucket_sizes`, the counting math, and the modes that inflate retention.

Look up the exact names first:

```text
mp help Workspace.query_retention
mp help RetentionMathType
mp help RetentionUnboundedMode
mp help RetentionQueryResult
```

## Three parameters define the retention model

`retention_unit`, `alignment`, and `bucket_sizes` together define the model. They have the same role as the conversion window in a funnel. A change to any one of them changes every metric after it.

- `retention_unit` groups users into cohorts: `day`, `week` (default), or `month`.
- `alignment` sets where each cohort's clock starts. `birth` (default) starts it at each user's own born event. `interval_start` snaps it to calendar boundaries.
- `bucket_sizes` sets the measurement points, in units of `retention_unit`. The values must be positive and ascending. The default is uniform buckets.

## Match the unit to the product's usage cadence

A daily product (social, messaging) needs `retention_unit="day"`. A weekly product (task management, fitness) needs `"week"`. A monthly product (subscriptions, B2B SaaS) needs `"month"`. When you are not sure, sweep:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
born, ret = "Signup", "Login"   # use real event names

for unit in ["day", "week", "month"]:
    result = ws.query_retention(born, ret, retention_unit=unit, last=90)
    rates = result.average.get("rates", [])
    bucket_1 = rates[1] if len(rates) > 1 else None
    print(f"{unit:>6}: bucket 1 retention = {bucket_1}")
# The unit with the highest bucket-1 retention shows the natural cadence.
```

`result.average` is a dict with `first` (cohort size), `counts`, and `rates`. Index 0 is the born bucket, so its rate is always 1.0. Use index 1 and later.

For milestone retention (day 1, 3, 7, 14, 30), use daily units with custom buckets:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
result = ws.query_retention(
    "Signup", "Login",              # use real event names
    retention_unit="day",
    bucket_sizes=[1, 3, 7, 14, 30],
    last=90,
)
print(result.average)
# Day 1 = activation, day 7 = habit formation, day 30 = long-term retention.
```

Alignment can move the result a lot. Compare both:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
for alignment in ["birth", "interval_start"]:
    result = ws.query_retention(
        "Signup", "Login", retention_unit="week", alignment=alignment, last=90
    )
    print(f"alignment={alignment}: rates={result.average.get('rates', [])[:5]}")
```

## Unbounded modes inflate retention

`unbounded_mode` controls how Mixpanel counts a return in later buckets. The default is `None`, which lets the server decide.

- `carry_forward` credits a return to the buckets after it. A user who returns only on day 30 counts as retained in every bucket from day 30 on.
- `carry_back` credits a return to earlier buckets. It inflates the early buckets.

Both answer "did the user ever come back?". Both distort a standard retention curve. `consecutive_forward` is the fourth value; see `mp help RetentionUnboundedMode`.

## Cumulative retention hides gaps

`retention_cumulative=True` makes each bucket include all earlier buckets, so the curve only goes up. It hides whether users who returned in week 1 also returned in week 2. Standard (non-cumulative) retention shows re-engagement and real habit formation.

## The counting math changes the question

- `retention_rate` (default): the percentage of the cohort that returned.
- `unique`: the number of users who returned.
- `total`: the number of return events, not users. A user who logs in 5 times in bucket 1 counts as 5. Use it to measure intensity.
- `average`: the library accepts it, but `query_retention()` has no `math_property` parameter, so you cannot name a property to average. Confirm what it returns on your data before you report it.

## Other rules

- `unit` (the date aggregation) accepts `day`, `week`, or `month`. `hour` is not supported for retention.
- `last=` is always a number of days.

## Result shape

`result.df` columns: `cohort_date`, `bucket`, `count`, `rate`. With `group_by`, a `segment` column comes first. The DataFrame holds one row per cohort date and bucket. It has no overall row. Use `result.average` for the average across cohorts, and `result.segment_averages` for each segment.
