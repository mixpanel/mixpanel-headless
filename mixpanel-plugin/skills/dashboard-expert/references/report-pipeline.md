# Report pipeline: from query to dashboard

How to build a dashboard, and how to turn a query result from any engine into a report on a dashboard. Every typed query returns a result with a `.params` dict. That dict is the report definition that Mixpanel stores, so you never write report JSON by hand.

For the signature of a query method, run `mp help Workspace.query_funnel` (or `query`, `query_retention`, `query_flow`). For one parameter and its allowed values, run `mp help Workspace.query_retention.retention_unit`.

## Contents

- [1. Build steps](#1-build-steps)
- [2. The pipeline](#2-the-pipeline)
- [3. One example per engine](#3-one-example-per-engine)
- [4. Saved reports (bookmarks)](#4-saved-reports-bookmarks)
- [5. Common mistakes](#5-common-mistakes)
- [6. End to end: one report from each engine](#6-end-to-end-one-report-from-each-engine)

```python
import datetime
import json

import mixpanel_headless as mp
from mixpanel_headless.types import (
    CreateBookmarkParams,
    CreateDashboardParams,
    DashboardRow,
    DashboardRowContent,
)

ws = mp.Workspace()
end = datetime.date.today().isoformat()
start = (datetime.date.today() - datetime.timedelta(days=90)).isoformat()


def text(html):
    """A text card for CreateDashboardParams rows."""
    return DashboardRowContent(content_type="text", content_params={"markdown": html})


def report(name, btype, result, description=None):
    """An inline report for CreateDashboardParams rows."""
    bookmark = {"name": name, "type": btype, "params": json.dumps(result.params)}
    if description:
        bookmark["description"] = description
    return DashboardRowContent(content_type="report", content_params={"bookmark": bookmark})
```

---

## 1. Build steps

### 1.1 Check the data

Build reports only for events that have volume. An empty chart on a shared dashboard looks broken and hides the real gap.

```python
for t in ws.top_events(limit=15):
    print(f"{t.event}: {t.count:,} ({t.percent_change:+.1%})")

for event in candidate_events:
    result = ws.query(event, last=90)
    print(f"{event}: {result.df['count'].sum():,.0f} in 90 days")

props = ws.properties(event="Purchase")
values = ws.property_values("platform", event="Purchase", limit=20)
```

`top_events` counts today only. Use `ws.query` over the dashboard's time range to decide whether an event has enough volume.

### 1.2 Plan the structure

Pick a dashboard template (the reading guide in `SKILL.md` names the file) and map its placeholder events to real events. Present the plan to the user before you build. A plan has:

- a title and a description (255 and 400 characters at most);
- an intro text card and one section header per section;
- the reports in each section, with the engine, the math, and the chart type;
- the widths of each row (they sum to 12, with at most 4 cells).

### 1.3 Query and create

Query every metric first. Then create the dashboard with all rows in one call.

```python
dau = ws.query("Login", math="dau", last=90)
signups = ws.query("Sign Up", last=90)
revenue = ws.query("Purchase", math="total", math_property="amount", last=90)
funnel = ws.query_funnel(["Sign Up", "Onboarding Done", "First Purchase"], last=90)

dashboard = ws.create_dashboard(CreateDashboardParams(
    title="Product Health",
    description="Key metrics for product health.",
    rows=[
        DashboardRow(contents=[text("<h2>Product Health</h2><p>Updated daily. Last 90 days.</p>")]),
        DashboardRow(contents=[
            report("DAU (90d)", "insights", dau),
            report("Signups (90d)", "insights", signups),
            report("Revenue (90d)", "insights", revenue),
        ]),
        DashboardRow(contents=[text("<h2>Conversion</h2><p>From signup to first purchase.</p>")]),
        DashboardRow(contents=[report("Signup Funnel", "funnels", funnel)]),
    ],
))
```

If one query fails, put a text card in its place and keep the build going. The user sees what is missing and why:

```python
row_items = []
for event in ["Sign Up", "Login", "Purchase"]:
    try:
        result = ws.query(event, last=90)
        row_items.append(report(f"{event} Trend", "insights", result))
    except Exception as exc:
        row_items.append(text(f"<p><strong>Not built:</strong> {event}: {exc}</p>"))
```

### 1.4 Finish

1. Pin the dashboard: `ws.pin_dashboard(dashboard.id)`. A new dashboard is not visible to the team until it is pinned.
2. Favorite it for the current user if asked: `ws.favorite_dashboard(dashboard.id)`.
3. Add explainer cards if the user wants insights on the board.
4. Adjust row heights with a layout PATCH if the defaults do not fit.

### 1.5 Verify

Read the dashboard back with `ws.get_dashboard(dashboard.id)`. Check that the row count, the cell widths, and the text cards match the plan. Run each report once to confirm that it returns data. Give the user the dashboard ID and title.

---

## 2. The pipeline

Every engine follows the same steps:

1. **Query**: call the typed query method.
2. **Inspect**: check `result.df`. Skip the report if it is empty.
3. **Place**: add the report to a dashboard inline, with `rows` at creation or with a content action later. `params` goes in as `json.dumps(result.params)`.

Inline placement is the default. It makes one report, owned by the dashboard, in one call. It makes no separate saved report and no "Duplicate of ..." copy.

| Engine | Query method | Report `type` | Default chart |
|---|---|---|---|
| Insights | `ws.query()` | `"insights"` | `line`; `bar` with `mode="total"`; `table` with `mode="table"` |
| Funnels | `ws.query_funnel()` | `"funnels"` | `funnel-steps`; `line` with `mode="trends"` |
| Retention | `ws.query_retention()` | `"retention"` | `retention-curve`; `line` with `mode="trends"` |
| Flows | `ws.query_flow()` | `"flows"` | `sankey` |

The report type is plural: `"funnels"` and `"flows"`, not `"funnel"` or `"flow"`.

---

## 3. One example per engine

### 3.1 Insights

```python
result = ws.query("Login", math="dau", group_by="platform", last=90)
print(result.df.describe())
item = report("DAU by Platform (90d)", "insights", result, "Daily active users by platform.")
```

### 3.2 Funnels

```python
result = ws.query_funnel(
    ["Page View", "Signup Started", "Signup Completed", "First Action"],
    from_date=start,
    to_date=end,
)
print(result.df)
print(f"Overall conversion: {result.overall_conversion_rate:.1%}")
item = report("Signup Funnel", "funnels", result)
```

### 3.3 Retention

```python
result = ws.query_retention(
    "Sign Up",
    "Login",
    retention_unit="day",
    from_date=start,
    to_date=end,
)
print(result.df.head())
item = report("New User Retention", "retention", result)
```

`retention_unit` defaults to `"week"`. Set it on purpose, because the unit changes what "day 1" means on the chart.

### 3.4 Flows

```python
result = ws.query_flow("Sign Up", forward=5, count_type="unique", last=30)
print(result.df.head())
item = report("After Signup", "flows", result)
```

### 3.5 Add a report to an existing dashboard

```python
from mixpanel_headless.types import UpdateDashboardParams

ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "report",
        "content_params": {"bookmark": {
            "name": "Daily Active Users",
            "type": "insights",
            "params": json.dumps(result.params),
        }},
    }
))
```

The report goes to a new full-width row at the bottom. To place it in an existing row, send the layout in the same call.

---

## 4. Saved reports (bookmarks)

Mixpanel requires every saved report to belong to a dashboard, so `CreateBookmarkParams` needs `dashboard_id`. The library raises an error before any request when it is missing. Make a saved report only when the user asks for one, for example to share it on its own.

```python
bookmark = ws.create_bookmark(CreateBookmarkParams(
    name="DAU by Platform (90d)",
    bookmark_type="insights",
    params=result.params,
    description="Daily active users by platform.",
    dashboard_id=dashboard.id,
))
url = ws.saved_report_link(bookmark.id, report_type="insights")
```

Three things differ from inline placement:

- `CreateBookmarkParams.params` takes the dict itself. Only the inline `bookmark` dict needs `json.dumps()`.
- `CreateBookmarkParams.dashboard_id` is required, but it does not place the report on the dashboard. Place a report with an inline bookmark content action or with `rows`.
- `ws.add_report_to_dashboard(dashboard_id, bookmark.id)` puts a clone on the dashboard, named "Duplicate of ...". The saved report and the clone are then two separate reports.

For a link that opens a query in Mixpanel without a saved report, use `ws.create_report_link(result)`. The mixpanelyst skill covers report links.

---

## 5. Common mistakes

| Mistake | Fix |
|---|---|
| `"type": "funnel"` or `"flow"` | Use `"funnels"` and `"flows"` |
| `"params": result.params` in an inline `bookmark` dict | `"params": json.dumps(result.params)` |
| `CreateBookmarkParams(dashboard_id=...)` alone, as a way to place the report | Place the report inline, or call `add_report_to_dashboard` (a clone) |
| A report saved without a look at `result.df` | Check `result.df.empty` first |
| Parameter names from other APIs | Look them up with `mp help Workspace.<method>` |

Parameter names that agents often guess wrong:

```text
ws.query_funnel(events=[...])        -> the first parameter is steps
ws.query_flow(from_event=..., steps=5) -> use event and forward
ws.query_retention(retention_type=...) -> use alignment ("birth" or "interval_start")
ws.property_values(property=...)     -> the first parameter is property_name
```

---

## 6. End to end: one report from each engine

```python
dau = ws.query("Login", math="dau", last=30)
funnel = ws.query_funnel(["Sign Up", "Onboarding Done", "First Action"], last=90)
retention = ws.query_retention("Sign Up", "Login", last=90)
flows = ws.query_flow("Sign Up", forward=5, last=30)

candidates = [
    ("Daily Active Users", "insights", dau),
    ("Signup Funnel", "funnels", funnel),
    ("New User Retention", "retention", retention),
    ("After Signup", "flows", flows),
]
items = []
for name, btype, result in candidates:
    if result.df.empty:
        print(f"Skipped {name}: no data")
        continue
    items.append(report(name, btype, result))

dashboard = ws.create_dashboard(CreateDashboardParams(
    title="Product Overview",
    description="One report from each analysis engine.",
    rows=[
        DashboardRow(contents=[text("<h2>Product Overview</h2><p>Last 30 to 90 days.</p>")]),
        DashboardRow(contents=items[:2]),
        DashboardRow(contents=items[2:]),
    ],
))
ws.pin_dashboard(dashboard.id)
print(f"Dashboard created: {dashboard.id}")
```

If a skip leaves a row empty, drop that row from `rows`. `DashboardRow` does not check the number of cells, so keep each row between one and four cells yourself.
