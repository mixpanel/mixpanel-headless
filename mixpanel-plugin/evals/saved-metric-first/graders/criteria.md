---
type: llm
focus: { source: file, path: checkout.py }
---

Background: in mixpanel_headless 0.4.0, a project's saved metrics are the team's own definitions. `ws.list_metrics(name_contains=..., verified=...)` finds them, and `ws.query()` takes a found `SavedMetric`, its `to_ref(...)`, or `MetricRef(<id>)` by reference.
PASS if the script looks for a saved metric before it defines the conversion itself: it calls `list_metrics` (or `get_metric` with an id that the user supplies) with a name filter such as "checkout", and it queries a found metric by reference over about 12 weeks (for example `last=84` with `unit="week"`). A fallback to an inline funnel or metric when no saved metric matches is fine, and so is a step that asks the user to choose among several matches.
FAIL if the script only builds the conversion inline (for example `query_funnel` with hard-coded steps) and never looks for a saved metric, or if it looks for one but then ignores a match.
