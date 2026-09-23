# Chart types

How to pick a chart type for each report type, and which width to give it on a dashboard (section 7 is the only width table). These are Mixpanel report settings, so the library reference does not list them.

## Contents

- [1. Decision table](#1-decision-table)
- [2. Insights chart types](#2-insights-chart-types)
- [3. Funnel chart types](#3-funnel-chart-types)
- [4. Retention chart types](#4-retention-chart-types)
- [5. Flows chart types](#5-flows-chart-types)
- [6. Math values](#6-math-values)
- [7. Width recommendations](#7-width-recommendations)
- [8. Set the chart type](#8-set-the-chart-type)

---

## 1. Decision table

| Question | Chart Type | `chartType` | `plotStyle` |
|---|---|---|---|
| Need a single headline number? | Metric | `insights-metric` | |
| Tracking something over time? | Line | `line` | |
| Comparing categories? | Bar | `bar` | |
| Showing composition over time? | Stacked Line | `line` | `stacked` |
| Showing composition across categories? | Stacked Bar | `bar` | `stacked` |
| Need detailed data? | Table | `table` | |
| Measuring conversion? | Funnel Steps | `funnel-steps` | |
| Measuring retention? | Retention Curve | `retention-curve` | |
| Exploring user paths? | Sankey | `sankey` | |

---

## 2. Insights Chart Types

| Chart Type | `chartType` | `plotStyle` | Best For |
|---|---|---|---|
| Line | `line` | `standard` | Trends over time |
| Stacked Line | `line` | `stacked` | Composition trends over time |
| Bar | `bar` | `standard` | Categorical comparisons, rankings |
| Stacked Bar | `bar` | `stacked` | Composition across categories |
| Column | `column` | `standard` | Vertical bar, fewer categories |
| Stacked Column | `column` | `stacked` | Composition across categories (vertical) |
| Pie | `pie` | | Share/proportion (max 6 segments) |
| Table | `table` | | Multi-dimensional detailed data |
| Metric | `insights-metric` | | Single KPI headline number |

### How Stacking Works

Stacked charts are not separate chart types. They use the base `chartType` (`line`, `bar`, or `column`) with `plotStyle` set to `"stacked"` in `displayOptions`:

```json
"displayOptions": {
  "chartType": "bar",
  "plotStyle": "stacked"
}
```

Do not use `bar-stacked`, `stacked-line`, or `stacked-column` as `chartType` values. They are labels in the Mixpanel UI, not API values, and the API rejects them.

Common `chartType` values (the funnel, retention, and flows tables below list more): `line`, `bar`, `column`, `pie`, `table`, `insights-metric`, `funnel-steps`, `funnel-top-paths`, `retention-curve`, `frequency-curve`

Valid `plotStyle` values: `standard` (default), `stacked`

### When to use each type

- **Line** -- Use for time series with continuous data. Not for categorical comparisons or single data points.
- **Bar** -- Use for ranking or comparing discrete categories. Not for time series (use line instead).
- **Stacked Bar/Line/Column** -- Use to show part-to-whole composition. Set `chartType` to the base type and `plotStyle` to `"stacked"`. Not when individual values matter more than composition.
- **Column** -- Use like bar but vertical; better with fewer categories. Not for many categories (labels overlap).
- **Pie** -- Use for simple share breakdowns with 2-6 segments. Not for more than 6 segments or precise comparisons.
- **Table** -- Use when exact values or multiple dimensions are needed. Not for quick visual scanning.
- **Metric** -- Use for a single KPI number (DAU, revenue, conversion rate). Not for trends or comparisons.

---

## 3. Funnel Chart Types

| Chart Type | Slug | Best For |
|---|---|---|
| Steps | `funnel-steps` | Standard funnel visualization |
| Trend | `funnel-trend` | Conversion rate over time |
| Top Paths | `funnel-top-paths` | Alternative paths through funnel |
| Frequency Line | `funnel-frequency-line` | How often users convert |
| Frequency Bar | `funnel-frequency-bar` | Conversion frequency distribution |
| Time to Convert (Line) | `funnel-ttc-line` | Duration analysis |
| Time to Convert (Bar) | `funnel-ttc-bar` | Duration distribution |
| Median TTC | `funnel-median-ttc` | Central tendency of conversion time |

---

## 4. Retention Chart Types

| Chart Type | Slug | Best For |
|---|---|---|
| Curve | `retention-curve` | Classic retention decay curve |
| Table | `retention-table` | Cohort-by-cohort retention grid |
| Trend | `retention-trend` | Retention rate over time |
| Trend Metric | `retention-trend-metric` | Single retention rate number |
| Line | `line-retention` | Retention as line chart |

---

## 5. Flows Chart Types

| Chart Type | Slug | Best For |
|---|---|---|
| Sankey | `sankey` | User journey visualization |
| Paths | `paths` | Path frequency analysis |

---

## 6. Math values

For the math values of each query method, run `mp help MathType`, `mp help FunnelMathType`, or `mp help RetentionMathType`. The templates file maps each report's math to a query.

---

## 7. Width Recommendations

| Chart Type | Width | Layout Pattern |
|---|---|---|
| Text card (section header) | 12 | Always full width |
| `insights-metric` | 3 or 4 | Pack 3-4 KPIs per row |
| `line` | 6 or 12 | 6 for paired comparison, 12 for detail |
| `line` + stacked | 12 | Composition needs space |
| `bar` | 6 or 12 | 6 for paired, 12 for many categories |
| `bar` + stacked | 12 | Needs full width for stacked segments |
| `column` | 6 or 12 | Same as bar |
| `column` + stacked | 12 | Composition needs space |
| `pie` | 6 | Pair with related chart |
| `table` | 12 | Always full width |
| `funnel-steps` | 12, or 6 for a 2-step funnel | Complex funnels need space |
| `funnel-trend` | 6 or 12 | 6 for paired, 12 for standalone |
| `funnel-top-paths` | 12 | Path detail needs space |
| `funnel-frequency-line`, `funnel-frequency-bar` | 6 | Pair with the steps chart |
| `funnel-ttc-line` | 6 or 12 | 6 for paired, 12 for standalone |
| `funnel-ttc-bar`, `funnel-median-ttc` | 6 | Pair with the steps chart |
| `retention-curve` | 12 | Full width for readability |
| `retention-table` | 12 | Full width for cohort grid |
| `retention-trend` | 6 or 12 | 6 for paired, 12 for standalone |
| `retention-trend-metric` | 3 or 4 | Same as insights-metric |
| `line-retention` | 6 or 12 | 6 for paired, 12 for standalone |
| `sankey` | 12 | Always full width |
| `paths` | 12 | Always full width |

---

## 8. Set the chart type

The chart type is `displayOptions.chartType` in the report params. The query methods set it from `mode`:

| Query | `mode` | `chartType` |
|---|---|---|
| `ws.query` | `"timeseries"` (default) | `line` |
| `ws.query` | `"total"` | `bar` |
| `ws.query` | `"table"` | `table` |
| `ws.query_funnel` | `"steps"` (default) | `funnel-steps` |
| `ws.query_funnel` | `"trends"` | `line` |
| `ws.query_retention` | `"curve"` (default) | `retention-curve` |
| `ws.query_retention` | `"trends"` | `line` |

For another chart type, change a copy of the params before you place the report:

```python
import copy
import json

import mixpanel_headless as mp
from mixpanel_headless.types import UpdateDashboardParams

ws = mp.Workspace()
result = ws.query("Login", math="dau", mode="total", last=30)

params = copy.deepcopy(result.params)
params["displayOptions"]["chartType"] = "insights-metric"

ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "report",
        "content_params": {"bookmark": {
            "name": "DAU (30d)", "type": "insights", "params": json.dumps(params),
        }},
    }
))
```

Open the report in Mixpanel once to confirm that it renders as intended.
