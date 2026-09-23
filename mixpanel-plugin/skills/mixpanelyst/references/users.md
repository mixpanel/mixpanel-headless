# User profile queries: modes, aggregates, distribution shape, and point-in-time

This file covers the analytical choices for `ws.query_user()`: profiles versus aggregate mode, the aggregate functions, `as_of`, and inline cohorts.

Look up the exact names first:

```text
mp help Workspace.query_user
mp help Workspace.query_user.aggregate
mp help UserQueryResult
mp help CohortDefinition
mp help CohortCriteria
```

## Mode is the main choice

- `mode="aggregate"` (default) returns one statistic. It is a calculation, and it is much faster: one API call.
- `mode="profiles"` returns one row per user. It is a data extraction, with paginated requests.

In profiles mode the default `limit` is 1, so you get one profile. Set `limit=N`, or `limit=None` for all matching profiles. For a large extraction, `parallel=True` fetches pages concurrently.

`result.total` is the number of profiles in the response, not the population. For the population size, use `mode="aggregate", aggregate="count"` and read `result.value`.

## Sweep the aggregates to see the distribution shape

Do this before you build an expensive profile query. `count` tells you how many. `extremes` gives the range (minimum and maximum). `percentile` with `percentile=50` gives the median. `numeric_summary` gives the count, mean, variance, and sum of squares.

```python
import mixpanel_headless as mp

ws = mp.Workspace()
prop = "lifetime_value"   # use a real numeric profile property

for agg in ["count", "extremes", "percentile", "numeric_summary"]:
    kwargs = {"mode": "aggregate", "aggregate": agg}
    if agg != "count":
        kwargs["aggregate_property"] = prop
    if agg == "percentile":
        kwargs["percentile"] = 50   # median
    result = ws.query_user(**kwargs)
    print(f"{agg:>16}: {result.aggregate_data}")
# If the mean (numeric_summary) is much larger than the median
# (percentile 50), the distribution is right-skewed.
```

`result.value` is the scalar for an unsegmented aggregate that returns one number, such as `count`. It is `None` when `aggregate_data` is a dict, for example with `extremes` or with `segment_by`. Read `result.aggregate_data` in those cases.

## Prefer medians to averages

The same rule applies here as for insights and funnels. `aggregate="percentile", percentile=50` gives the median. `numeric_summary` gives the mean. If they are far apart, the distribution is skewed and the mean misleads.

## `as_of` shows the population at a past date

Without `as_of`, you always see the current state, so growth and churn are invisible. With `as_of="2025-01-01"`, you query profiles as they were on that date. `as_of` works in profiles mode only; the validator rejects it in aggregate mode. So a point-in-time count fetches the profiles:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
premium = mp.Filter.equals("plan", "premium")

today = ws.query_user(mode="aggregate", aggregate="count", where=premium)
past = ws.query_user(
    mode="profiles", where=premium, as_of="2025-01-01",
    properties=["plan"], limit=None, parallel=True,
)
print(f"Premium users: {past.total} (2025-01-01) -> {today.value} (today)")
```

The past query downloads every matching profile. Ask the user before you run it on a large population.

## Inline cohorts or saved cohorts

An inline cohort (`cohort=mp.CohortDefinition.all_of(...)`) defines a behavioral segment in the query. You do not need to save it in Mixpanel and delete it afterward, so exploration is much faster. Use saved cohorts (`cohort=<id>`) for production dashboards and monitoring.

```python
import mixpanel_headless as mp

ws = mp.Workspace()
power_users = mp.CohortDefinition.all_of(
    mp.CohortCriteria.did_event("Purchase", at_least=5, within_days=30),
    mp.CohortCriteria.did_not_do_event("Support Ticket", within_days=90),
)
result = ws.query_user(cohort=power_users, mode="aggregate", aggregate="count")
print(result.value)
```

`segment_by=[<cohort id>, ...]` splits an aggregate by saved cohorts.
