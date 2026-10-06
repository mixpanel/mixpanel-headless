---
type: llm
focus: { source: file, path: checkout.py }
---

Background: in mixpanel_headless 0.4.0, a project's saved metrics are the team's own definitions. `ws.list_metrics(name_contains=..., viewable_only=True)` finds candidates, and `ws.query()` takes a chosen `SavedMetric`, its `to_ref(...)`, or `MetricRef(<id>)` by reference. A name match can be the wrong metric: a "checkout" search can find a checkout count as well as a checkout conversion rate. `SavedMetric.behavior_type` and `SavedMetric.math` (for example `"funnel"` and `"conversion_rate_unique"`) tell them apart.
PASS if the script looks for a saved metric before it defines the conversion itself, checks each candidate's definition (for example its `behavior_type` or `math`) to confirm that it measures a conversion, and selects one metric explicitly: it prefers a verified match, and when several fit it lists them and stops, or takes the id from the user. It then queries the selected metric by reference over about 12 weeks (for example `last=84` with `unit="week"`). A fallback to an inline funnel or metric when no saved metric fits is fine.
FAIL if the script only builds the conversion inline (for example `query_funnel` with hard-coded steps) and never looks for a saved metric, ignores a fitting match, or queries the first name match (for example `list_metrics(...)[0]`) without checking that it measures a conversion.
