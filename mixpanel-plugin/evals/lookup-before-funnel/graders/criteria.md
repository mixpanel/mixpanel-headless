---
type: llm
focus: { source: file, path: funnel_median.py }
---

Background: in mixpanel_headless, funnel `math="median"` (and the other property math values) aggregates a numeric property named in `math_property`; it is not time to convert, and it raises an error without `math_property`. The funnel result reports time to convert only as means (`avg_time`, `avg_time_from_start`, in seconds). So a funnel query alone cannot return a median time to convert.
PASS if the script breaks the result down by a platform property over the last 90 days (for example `last=90`), does not pass `math="median"` to `query_funnel` without a `math_property` as if it were time to convert, and handles the median honestly: it either states in the script (comment, docstring, or printed note) that funnel times are means and reports `avg_time_from_start` with that caveat, or computes a real median another valid way (for example per-user Signup-to-Purchase gaps from raw events).
FAIL if the script calls `query_funnel(..., math="median")` with no `math_property` and treats the result as time to convert, if the platform breakdown or the 90-day range is missing, or if it presents a mean as a median without saying so.
