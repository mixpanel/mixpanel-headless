# Funnel queries: windows, counting, order, and time

This file covers the analytical choices for `ws.query_funnel()`: the conversion window, the counting math, step order, exclusions, per-step filters, and how to read time-to-convert.

**Contents**

- [The conversion window is the main choice](#the-conversion-window-is-the-main-choice)
- [Counting math and re-entry](#counting-math-and-re-entry)
- [Time to convert](#time-to-convert)
- [Step order](#step-order)
- [Hold a property constant](#hold-a-property-constant)
- [Exclusions](#exclusions)
- [Per-step filters and global filters](#per-step-filters-and-global-filters)
- [Session windows](#session-windows)
- [Result shape](#result-shape)

Look up the exact names first:

```text
mp help Workspace.query_funnel
mp help Workspace.query_funnel.math   # allowed FunnelMathType values
mp help FunnelStep
mp help Exclusion
mp help HoldingConstant
mp help FunnelQueryResult
```

## The conversion window is the main choice

The conversion window is the maximum time a user has to finish the funnel, counted from the first step. It changes every other metric: the conversion rate, the time to convert, and each segment comparison. The default is 14 days.

Match the window to the journey. A short journey (order food, add to cart) needs hours, not days. A long journey (onboarding, a subscription purchase) needs days or weeks. When you are not sure, sweep:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
steps = ["View Item", "Add to Cart", "Purchase"]   # use real event names

for window, unit in [(14, "day"), (7, "day"), (1, "day"), (12, "hour"), (6, "hour")]:
    result = ws.query_funnel(
        steps, last=90, conversion_window=window, conversion_window_unit=unit
    )
    final = result.df.iloc[-1]
    hours = final["avg_time_from_start"] / 3600
    print(f"{window}{unit}: conv={final['overall_conv_ratio']:.3f} avg time={hours:.1f}h")
# Look for where conversion stabilizes and where time gaps appear.
```

When you compare segments, try at least two or three windows. A difference that you cannot see at 14 days can be large at 6 hours. Tight windows remove noise and show which segment finishes faster.

Each unit has a maximum window (for example 12 months, 52 weeks, 367 days, 12 sessions). The validator rejects a larger value before the query runs.

## Counting math and re-entry

The math changes what "conversion" means:

- `conversion_rate_unique` (default): unique users who finished. There is no re-entry: a user gets the first attempt in the window only.
- `conversion_rate_total`: total completions. One user can count more than one time.
- `conversion_rate_session`: sessions that finished. It needs `conversion_window_unit="session"`.

To count more than one attempt per user, set `reentry_mode` (see `mp help FunnelReentryMode`). `"optimized"` picks the best completion path. The default is `None`, which lets the server decide.

The property math values (`average`, `median`, `min`, `max`, `p25` … `p99`) aggregate a numeric property that you name in `math_property`. They are not time-to-convert statistics, and they raise an error without `math_property`.

## Time to convert

The result gives time as averages only: `avg_time` (from the previous step) and `avg_time_from_start` (from the first step), both in seconds. An average includes outliers: one slow user makes it larger, and one fast user makes it smaller. Tell the user that the times are means, not medians. To compare speed with less noise, compare segments at tight windows:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
steps = ["View Item", "Add to Cart", "Purchase"]   # use real event names

ios = ws.query_funnel(
    steps, where=mp.Filter.equals("platform", "iOS"),
    last=90, conversion_window=6, conversion_window_unit="hour",
)
android = ws.query_funnel(
    steps, where=mp.Filter.equals("platform", "Android"),
    last=90, conversion_window=6, conversion_window_unit="hour",
)
print(ios.df[["step", "event", "avg_time_from_start"]])
print(android.df[["step", "event", "avg_time_from_start"]])
```

## Step order

`order="loose"` (default) requires the steps in sequence, but allows other events between them. `order="any"` requires all steps in any order: a user who does C, then B, then A converts. A loose funnel measures a sequential workflow. An any-order funnel measures how broadly users adopt a set of features. When you are not sure, run both:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
steps = ["View Item", "Add to Cart", "Purchase"]   # use real event names

for order in ["loose", "any"]:
    result = ws.query_funnel(steps, last=90, order=order)
    print(f"order={order}: {result.overall_conversion_rate:.3f}")
# If "any" is much higher than "loose", users reach the goal but not
# by the designed path. This often points to a UX problem.
```

`FunnelStep(..., order=...)` sets the order for one step.

## Hold a property constant

`holding_constant="platform"` (or `"device_id"`) counts a user as converting only when the property has the same value at every step. A user who signs up on iOS and buys on Android does not convert. Use it to separate single-device from cross-device conversion. The maximum is 3 properties. Use `HoldingConstant(..., resource_type="people")` for a user-profile property.

## Exclusions

`exclusions=["Logout"]` removes users who did the excluded event between funnel steps. They leave the funnel completely. Use exclusions for support escalations, churn signals, or any action that spoils the conversion path. To limit the step range, use `Exclusion("Logout", from_step=0, to_step=2)`. Step numbers are 0-indexed and inclusive. `to_step=None` means the last step.

## Per-step filters and global filters

`FunnelStep("Purchase", filters=[mp.Filter.greater_than("amount", 50)])` limits which Purchase events count. It does not filter the other steps. A global `where` filters all steps. Filter the population with `where`. Filter the definition of one step with per-step filters.

## Session windows

`conversion_window_unit="session"` keeps the whole funnel inside one session. It shows in-session conversion, separate from users who spread a journey across days. The window then counts sessions, and the maximum is 12. The default window of 14 is too large, so set `conversion_window` too:

```python
import mixpanel_headless as mp

ws = mp.Workspace()
result = ws.query_funnel(
    ["View Item", "Add to Cart", "Purchase"],   # use real event names
    conversion_window=1,
    conversion_window_unit="session",
    math="conversion_rate_session",
    last=30,
)
print(result.overall_conversion_rate)
```

## Result shape

`result.df` has one row per step: `step` (1-based), `event`, `count`, `step_conv_ratio`, `overall_conv_ratio`, `avg_time`, `avg_time_from_start`. `result.overall_conversion_rate` is the final step's `overall_conv_ratio`, from 0.0 to 1.0.
