# Segmentation building blocks: inline custom properties, inline cohorts, and frequency

This file covers the three tools that turn raw events and properties into useful dimensions and populations: `InlineCustomProperty`, `CohortDefinition` with `CohortBreakdown` / `CohortMetric`, and `FrequencyBreakdown` / `FrequencyFilter`. It includes the measured `FrequencyFilter` trap.

**Contents**

- [Which tool to use](#which-tool-to-use)
- [Inline custom properties](#inline-custom-properties)
- [Inline cohorts](#inline-cohorts)
- [Frequency breakdowns and filters](#frequency-breakdowns-and-filters)
- [The FrequencyFilter trap, measured](#the-frequencyfilter-trap-measured)

Look up the constructors with `mp help InlineCustomProperty`, `mp help CohortCriteria`, `mp help CohortBreakdown`, `mp help CohortMetric`, `mp help FrequencyBreakdown`, and `mp help FrequencyFilter`.

## Which tool to use

Raw data is rarely ready for analysis. Each tool below works with the query engines that accept it.

- The property values are messy or need derivation: **inline custom property**.
- The population needs behavioral criteria (did X, did not do Y, a frequency threshold): **inline cohort**.
- You segment by how often users did an event, not only whether they did it: **`FrequencyBreakdown` / `FrequencyFilter`**. Pick the `unit` that matches the threshold period.
- You compare in-cohort with out-of-cohort behavior: **`CohortBreakdown`**. `include_negated=True` is the default, so you get a "Not In" segment too.
- You track a segment's size as a time series: **`CohortMetric`**. It takes saved cohort IDs only, and it works in `ws.query()` only.

## Inline custom properties

An `InlineCustomProperty` transforms data at query time. It changes nothing in the project. Use it when values are messy, need buckets, or need a new derived dimension:

- Bucket continuous values for a breakdown (revenue into Low, Medium, High).
- Clean messy strings with `IFS` or `REGEX_EXTRACT` (campaign names, UTM parameters).
- Derive a new dimension with arithmetic or date functions (profit margin, days since signup).
- Build a fallback chain across properties (display name, then username, then "unknown").

```python
import mixpanel_headless as mp

ws = mp.Workspace()

# Bucket revenue into tiers for a breakdown.
revenue_tier = mp.InlineCustomProperty(
    formula='IFS(A < 50, "Low", A < 200, "Medium", TRUE, "High")',
    inputs={"A": mp.PropertyInput("revenue", type="number")},
    property_type="string",
)
tiers = ws.query("Purchase", group_by=mp.GroupBy(property=revenue_tier),
                 last=30, mode="total")

# Derive profit margin and aggregate it.
margin = mp.InlineCustomProperty.numeric("(A - B) / A * 100", A="revenue", B="cost")
avg_margin = ws.query(mp.Metric("Purchase", math="average", property=margin), last=30)

# Clean a messy string for segmentation.
domain = mp.InlineCustomProperty(
    formula='REGEX_EXTRACT(A, "@(.+)$")',
    inputs={"A": mp.PropertyInput("email", type="string")},
    property_type="string",
)
by_domain = ws.query("Signup", group_by=mp.GroupBy(property=domain),
                     last=30, mode="total")
```

Use inline properties for exploration. When a formula proves useful, save it with `ws.create_custom_property()` and refer to it with `CustomPropertyRef(id)` in other reports.

## Inline cohorts

Every analytical question starts with "among which users?". A property filter (`where=Filter.equals(...)`) answers "users with attribute X". An inline cohort answers harder questions: "users who did X at least N times in the last D days, and did not do Y, and have property Z". Combine criteria with `CohortDefinition.all_of(...)` or `any_of(...)`:

```python
import mixpanel_headless as mp

ws = mp.Workspace()

# Power users: 5 or more purchases in 30 days, no support ticket in 90 days.
power_users = mp.CohortDefinition.all_of(
    mp.CohortCriteria.did_event("Purchase", at_least=5, within_days=30),
    mp.CohortCriteria.did_not_do_event("Support Ticket", within_days=90),
)

# As a breakdown. You do not need to save the cohort first.
logins = ws.query("Login", group_by=mp.CohortBreakdown(power_users, "Power Users"),
                  last=30)

# As a population in a user query.
count = ws.query_user(cohort=power_users, mode="aggregate", aggregate="count")

# A saved cohort's size over time, next to an event metric.
saved_cohort_id = 12345   # use a real saved cohort ID
share = ws.query(
    [mp.Metric("Login", math="unique"), mp.CohortMetric(saved_cohort_id, "Power Users")],
    formula="(B / A) * 100", formula_label="% Power Users Active", last=90,
)
```

`CohortMetric` rejects an inline `CohortDefinition` when you construct it, because the server returns an error for it. Save the cohort first if you need its size over time.

## Frequency breakdowns and filters

`FrequencyBreakdown` answers "how do users who did X once differ from users who did X ten times?". `FrequencyFilter` limits a query to users who meet a frequency threshold. Together they connect what users did with who they are.

```python
import mixpanel_headless as mp

ws = mp.Workspace()

# Login reach by purchase frequency bucket.
by_frequency = ws.query(
    "Login", math="unique",
    group_by=mp.FrequencyBreakdown("Purchase", bucket_size=3, bucket_min=0, bucket_max=15),
    last=30, mode="total",
)
# Do frequent buyers also log in more?

# Users active in March who purchased 3 or more times in that month.
repeat_buyers = ws.query(
    "Login", math="unique",
    where=mp.FrequencyFilter("Purchase", value=3),
    from_date="2026-03-01", to_date="2026-03-31", unit="month",
)
```

`FrequencyFilter` works with `ws.query()` and `ws.build_params()` only. `ws.query_flow()` does not accept it.

## The FrequencyFilter trap, measured

**The threshold counts inside each `unit` bucket, not over the date range.** With the default `unit="day"`, `FrequencyFilter("Login", value=5)` keeps only users with 5 or more logins on the same day. It returns an empty series when nobody does that, even if thousands of users logged in 5 or more times in the month. An empty result is the expected outcome for a threshold that nobody reaches inside one bucket. Do not report it as "no such users".

- Choose the `unit` that matches the period you mean: `"day"` for "N times in a day", `"month"` for "N times in a month".
- `unit="month"` over a range of several months still applies one threshold per month.
- "N times over the whole period" needs a date range that fits inside one bucket.
- `last=` is always a number of days, so pin a month with `from_date` and `to_date`.
- `date_range_value` / `date_range_unit` had no observable effect on inline filters in a 2026-09-11 probe, and their behavior is not verified. Do not use them to widen the window.
- Use `math="unique"` to count users. The default `math="total"` counts their events.

Measured on a seeded gaming dataset (10,000 users, March 2026), with `FrequencyFilter("enter dungeon", value=5)` from 2026-03-01 to 2026-03-31:

| Query | Result |
| --- | --- |
| `unit="day"` (default), default `math="total"` | Empty series. No user entered the dungeon 5 or more times on one day. |
| `unit="month"`, `math="unique"` | 2,571 of 8,281 active users: 5 or more entries anywhere in March. This matches the ground truth. The default `math="total"` would report their events instead. |
