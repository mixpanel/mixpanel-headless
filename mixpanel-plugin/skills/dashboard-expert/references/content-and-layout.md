# Dashboard content and layout

How to read a dashboard, change its cells and rows, and keep the layout valid. The method signatures and type fields come from the library: run `mp help Workspace --domain dashboards`, `mp help UpdateDashboardParams`, or `mp help Dashboard`. This file covers the API behavior that the signatures do not tell you.

## Contents

- [1. Analyze steps](#1-analyze-steps)
- [2. Modify steps](#2-modify-steps)
- [3. Content actions](#3-content-actions)
- [4. Grid and layout](#4-grid-and-layout)
- [5. Combined content and layout PATCH](#5-combined-content-and-layout-patch)
- [6. Operation order and new rows](#6-operation-order-and-new-rows)
- [7. Report cells and report-link cells](#7-report-cells-and-report-link-cells)
- [8. Time filters, filters, and breakdowns](#8-time-filters-filters-and-breakdowns)
- [9. Duplicate, pin, favorite, delete](#9-duplicate-pin-favorite-delete)

```python
import copy
import datetime
import json
import re

import mixpanel_headless as mp
from mixpanel_headless.types import CreateDashboardParams, UpdateDashboardParams

ws = mp.Workspace()
end = datetime.date.today()
start = end - datetime.timedelta(days=90)  # date range for saved funnels
```

---

## 1. Analyze steps

### 1.1 Read the structure

`ws.get_dashboard(dashboard_id)` returns a `Dashboard` with two dicts:

- `dash.layout["order"]`: the row IDs, top to bottom.
- `dash.layout["rows"][row_id]["cells"]`: the cells of a row, each with `content_id`, `content_type`, and `width`.
- `dash.contents["report"][str(content_id)]`: report metadata with `id` (the bookmark ID), `name`, `type`, `params`, and `description`.
- `dash.contents["text"][str(content_id)]`: a text card with `markdown`.

The content ID in a cell is an integer. The keys of `contents` are strings, so convert with `str()`.

```python
dash = ws.get_dashboard(dashboard_id)
layout, contents = dash.layout, dash.contents

rows = []
for row_id in layout["order"]:
    row = layout["rows"][row_id]
    cells = []
    for cell in row["cells"]:
        cid, ctype = str(cell["content_id"]), cell["content_type"]
        if ctype in ("report", "report-link"):
            info = contents["report"][cid]
            raw = info.get("params") or {}
            params = json.loads(raw) if isinstance(raw, str) else raw
            cells.append({
                "type": ctype,
                "name": info.get("name", ""),
                "report_type": info.get("type", "insights"),
                "bookmark_id": info["id"],
                "width": cell["width"],
                "is_owned": ctype == "report",
                "params": params,
            })
        elif ctype == "text":
            md = contents["text"].get(cid, {}).get("markdown", "")
            cells.append({
                "type": "text",
                "markdown": md,
                "is_section_header": bool(re.search(r"<h2[\s>]", md, re.I)),
                "width": cell["width"],
            })
    rows.append({"row_id": row_id, "height": row.get("height", 0), "cells": cells})
```

A text card with an `<h2>` starts a section. Group the reports under the last section header above them. You need these groups to answer "add a report to the Retention section" and to summarize by section.

`params` in `contents["report"]` can be a JSON string. Parse it with `json.loads()` before you read it.

### 1.2 Read a report definition

For the full query definition, read the bookmark:

```python
bookmark = ws.get_bookmark(bookmark_id)
params = bookmark.params  # insights format shown below
```

Useful keys in insights params:

| Key | Holds |
|---|---|
| `params["sections"]["show"]` | Metrics: event names and math |
| `params["sections"]["group"]` | Breakdown properties |
| `params["sections"]["filter"]` | Active filters |
| `params["sections"]["time"]` | Date range |
| `params["displayOptions"]["chartType"]` | Chart type |

### 1.3 Run the reports

```python
for row in rows:
    for cell in row["cells"]:
        if cell["type"] == "text":
            continue
        bid, btype = cell["bookmark_id"], cell["report_type"]
        if btype == "flows":
            result = ws.query_saved_flows(bid)
        elif btype == "funnels":
            result = ws.query_saved_report(
                bid, bookmark_type="funnels", from_date=start.isoformat(), to_date=end.isoformat()
            )
        else:
            result = ws.query_saved_report(bid, bookmark_type=btype)
        df = result.df
```

Saved flows have their own method, `query_saved_flows`. A saved funnel without `from_date` and `to_date` runs over the last 30 days, not over the range saved in the report. Pass the dates you want and state them in the summary.

Key numbers to extract by type:

| Type | Extract |
|---|---|
| insights | Total, average, latest value, minimum, maximum, trend direction |
| funnels | Step names, step counts, step and overall conversion |
| retention | Day 1, day 7, day 30 rates; where the curve flattens |
| flows | Top paths, conversion, main drop-off points |

For a week-over-week trend on a daily insights series, compare `df.iloc[-1]` with `df.iloc[-8]`.

### 1.4 Present the analysis

1. Overview: title, purpose, number of sections and reports.
2. Section by section: what each section measures and its key numbers.
3. Cross-report findings: correlations, anomalies, contradictions.
4. Suggestions: missing metrics, better chart types, layout fixes.

### 1.5 Several dashboards

```python
all_reports = {}
for did in [1001, 1002, 1003]:
    dash = ws.get_dashboard(did)
    for cid, info in dash.contents.get("report", {}).items():
        bid, btype = info["id"], info["type"]
        try:
            if btype == "flows":
                result = ws.query_saved_flows(bid)
            else:
                result = ws.query_saved_report(bid, bookmark_type=btype)
            all_reports[f"{dash.title} / {info['name']}"] = result.df
        except Exception as exc:
            print(f"Skipped {info['name']}: {exc}")
# Join the frames on the date index, then compare or correlate them.
```

Look for these patterns across dashboards:

- Correlated metrics, for example DAU and feature adoption move together.
- Divergent signals, for example signups rise but retention falls.
- Complementary data, for example one board's KPI explained by another board's funnel.
- Gaps: a metric that a text card mentions but no report shows.

---

## 2. Modify steps

1. **Read the current state.** Run the analyze steps 1.1 and 1.2. Show the user the sections and cells before you change anything.
2. **Plan the changes.** Classify each change as metadata, cell create, row reorder, cell update, cell delete, or row delete. Sort them into the order in section 6.1.
3. **Apply the changes.** Use the content actions in section 3 and the layout PATCH in sections 4 and 5. Read the dashboard again after each layout change, because row and cell IDs change.

| Change | How |
|---|---|
| Add a cell at the bottom | Content action `create` alone (section 3) |
| Add a cell to an existing row | Content action and layout in one PATCH (section 5) |
| Add a cell in a new row at a position | Create it, find its new row ID, then reorder (section 6.2) |
| Move or resize cells, reorder rows | Layout PATCH (section 4.3) |
| Change a text card | Content action `update`, or `ws.update_text_card` |
| Change a report into a text card, or back | Delete the cell, then create a new one |
| Rename the dashboard | `UpdateDashboardParams(title=...)` in its own PATCH |

---

## 3. Content actions

A content action goes in the `content` field of `UpdateDashboardParams`. It is a dict with `action`, `content_type`, and fields for that action.

| `action` | Use |
|---|---|
| `create` | Add a report or a text card |
| `update` | Change a cell in place (same `content_type` only) |
| `delete` | Remove a cell |
| `duplicate` | Copy a cell on the same dashboard |
| `undelete` | Restore a deleted cell |
| `move` | Move a cell; prefer a layout PATCH, which is explicit |

`content_type` is `"report"` or `"text"`. The `content_id` is the numeric ID from the layout cell.

### 3.1 Create a report inline (preferred)

```python
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "report",
        "content_params": {
            "bookmark": {
                "name": "Daily Active Users",
                "type": "insights",
                "params": json.dumps(result.params),
                "description": "DAU over the last 90 days.",
            }
        },
    }
))
```

This makes the report on the dashboard in one call. It makes no separate bookmark and no "Duplicate of ..." name. `type` is `"insights"`, `"funnels"`, `"retention"`, or `"flows"`. `params` must be a JSON string, so wrap it in `json.dumps()`.

### 3.2 Create a report from an existing bookmark

```python
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "report",
        "content_params": {"source_bookmark_id": bookmark_id},
    }
))
```

This clones the bookmark, like `ws.add_report_to_dashboard()`. The clone gets a new content ID. Read the returned `Dashboard` to find it, and do not assume it equals the bookmark ID.

### 3.3 Create, update, and delete a text card

```python
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "text",
        "content_params": {"markdown": "<h2>Retention</h2><p>Do new users come back?</p>"},
    }
))

ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "update",
        "content_type": "text",
        "content_id": text_card_id,
        "content_params": {"markdown": "<h2>Retention</h2><p>Updated text.</p>"},
    }
))

ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={"action": "delete", "content_type": "text", "content_id": text_card_id}
))
```

A created cell goes to a new full-width row at the bottom. Move it with a layout PATCH, or send the layout in the same call (section 5).

### 3.4 Duplicate and undelete

```python
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={"action": "duplicate", "content_type": "report", "content_id": content_id}
))
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={"action": "undelete", "content_type": "report", "content_id": content_id}
))
```

### 3.5 Change the type of a cell

An `update` cannot change `content_type`. Delete the old cell, then create the new one:

```python
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={"action": "delete", "content_type": "text", "content_id": old_text_id}
))
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "report",
        "content_params": {"bookmark": {
            "name": "Signups", "type": "insights", "params": json.dumps(result.params),
        }},
    }
))
```

---

## 4. Grid and layout

### 4.1 Grid rules

| Rule | Value |
|---|---|
| Columns per row | 12; the widths in a row sum to exactly 12 |
| Cells per row | 1 to 4 |
| Rows per dashboard | 30 at most |
| Standard widths | 3 (quarter), 4 (third), 6 (half), 12 (full) |
| Nested dashboards | 2 levels at most, and only where a feature flag enables them |

Valid width sets: `3+3+3+3`, `4+4+4`, `6+6`, `12`, `8+4`, `6+3+3`. A section header text card is always full width (12).

| Row | Height (px) |
|---|---|
| Text only | 0 (auto height) |
| KPI row | 336 |
| Two charts (6 + 6) | 418 |
| One full-width chart | 500 |
| Full-width funnel or table | 588 |

The heights are guidelines. Users can resize rows in Mixpanel.

### 4.2 Layout from GET

```json
{
  "version": "2.0.0",
  "order": ["row-abc-123", "row-def-456"],
  "rows": {
    "row-abc-123": {
      "height": 0,
      "cells": [{"id": "cell-aaa-111", "width": 12, "content_id": 90001, "content_type": "text"}]
    },
    "row-def-456": {
      "height": 336,
      "cells": [
        {"id": "cell-bbb-222", "width": 6, "content_id": 90002, "content_type": "report"},
        {"id": "cell-ccc-333", "width": 6, "content_id": 90003, "content_type": "report"}
      ]
    }
  }
}
```

Row and cell IDs are generated by Mixpanel. Read them from GET; do not invent them.

### 4.3 Layout PATCH format

A layout PATCH differs from the GET shape in three ways:

| GET response | PATCH payload |
|---|---|
| `"order"` | `"rows_order"` |
| `"rows"` is a dict keyed by row ID | `"rows"` is a list, with `"id"` on each row |
| Includes `"version"` | Leave `"version"` out; the API rejects it |

```python
dash = ws.get_dashboard(dashboard_id)
layout = dash.layout

row_ids = list(layout["order"])  # keep the order, or rearrange it here
rows_list = [
    {
        "id": row_id,
        "height": layout["rows"][row_id].get("height", 0),
        "cells": layout["rows"][row_id].get("cells", []),
    }
    for row_id in row_ids
]

ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    layout={"rows_order": row_ids, "rows": rows_list}
))
```

---

## 5. Combined content and layout PATCH

To add a cell to a specific existing row, send `content` and `layout` in the same `UpdateDashboardParams`. The new cell carries a `temp_id` in the layout, and the API links it to the created content. Give every cell in the row the same new width.

```python
dash = ws.get_dashboard(dashboard_id)
layout = copy.deepcopy(dash.layout)
target_row = layout["rows"][target_row_id]

cell_width = 12 // (len(target_row["cells"]) + 1)
for cell in target_row["cells"]:
    cell["width"] = cell_width
target_row["cells"].append({"temp_id": "-1", "width": cell_width})

ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "report",
        "content_params": {"bookmark": {
            "name": "New Report", "type": "insights", "params": json.dumps(result.params),
        }},
    },
    layout={
        "rows_order": layout["order"],
        "rows": [{"id": row_id, **layout["rows"][row_id]} for row_id in layout["order"]],
    },
))
```

A row holds four cells at most, so the target row must have three cells or fewer before the call.

---

## 6. Operation order and new rows

### 6.1 Order of operations

When one request from the user needs several changes, apply them in this order:

1. Metadata (title, description), in its own PATCH.
2. Cell creates.
3. Row reorder (`rows_order`), after the creates, so the new row IDs exist.
4. Cell updates.
5. Cell deletes.
6. Row deletes, last.

A reorder before the create fails with an unknown row ID. A delete before a create can leave gaps in the layout. Read the dashboard again between layout changes.

### 6.2 Find the ID of a new row

A created cell gets a new row with a real ID. Compare the row sets before and after to find it, then use that ID in `rows_order`:

```python
before_rows = set(ws.get_dashboard(dashboard_id).layout["rows"].keys())
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    content={
        "action": "create",
        "content_type": "text",
        "content_params": {"markdown": "<h2>New Section</h2>"},
    }
))
layout = ws.get_dashboard(dashboard_id).layout
new_row_id = (set(layout["rows"].keys()) - before_rows).pop()

order = [r for r in layout["order"] if r != new_row_id]
order.insert(2, new_row_id)  # third row from the top
ws.update_dashboard(dashboard_id, UpdateDashboardParams(
    layout={
        "rows_order": order,
        "rows": [{"id": r, **layout["rows"][r]} for r in order],
    }
))
```

---

## 7. Report cells and report-link cells

| `content_type` | Owner | Editable here |
|---|---|---|
| `"report"` | This dashboard | Yes: params, name, description |
| `"report-link"` | Another dashboard | No: read-only reference |

Check `content_type` before you plan an edit. An edit to the params of a report link fails. `ws.update_report_link()` changes only the link type, not the report. To change the report itself, edit it on the dashboard that owns it, or add an owned copy with an inline create.

You can run a report-link cell like any report: its metadata is in `contents["report"]`.

For a URL to a report on a dashboard, call `ws.saved_report_link(bookmark_id, report_type=...)` with the report's type. It builds the URL locally and makes no network call.

---

## 8. Time filters, filters, and breakdowns

A dashboard-level time filter overrides the date range of each report on the dashboard. Set it with `time_filter` at creation or in an update.

```python
last_30_days = {
    "dateRange": {"type": "in the last", "window": {"unit": "day", "value": 30}},
    "displayText": "Last 30 days",
}
since_date = {
    "dateRange": {"type": "since", "from_date": "2026-01-01"},
    "displayText": "Since Jan 1, 2026",
}
between_dates = {
    "dateRange": {"type": "between", "from_date": "2026-01-01", "to": "2026-03-31"},
    "displayText": "Jan 1 - Mar 31, 2026",
}

dashboard = ws.create_dashboard(CreateDashboardParams(
    title="Rolling 30-Day Metrics", time_filter=last_30_days
))
ws.update_dashboard(dashboard.id, UpdateDashboardParams(time_filter=between_dates))
ws.update_dashboard(dashboard.id, UpdateDashboardParams(time_filter={}))  # remove it
```

The window `unit` is `"day"`, `"week"`, or `"month"`. The end-date key in a `between` range is `to`, not `to_date`.

`filters` and `breakdowns` apply to every report on the dashboard. Users usually set them in the Mixpanel UI. Read them to understand the scope of a dashboard, and send them back unchanged when you update other fields:

```python
dash = ws.get_dashboard(dashboard_id)
print(dash.filters, dash.breakdowns, dash.time_filter)
```

---

## 9. Duplicate, pin, favorite, delete

```python
copy_of = ws.create_dashboard(CreateDashboardParams(
    title="Product Health (Copy)", duplicate=existing_dashboard_id
))
```

`duplicate` copies all reports, text cards, and the layout. The copy has its own ID and its own content IDs.

| Call | Effect |
|---|---|
| `ws.pin_dashboard(dashboard_id)` | Shows the dashboard at the top of the list for all project members. A new dashboard needs this to be visible to the team. |
| `ws.unpin_dashboard(dashboard_id)` | Removes the pin |
| `ws.favorite_dashboard(dashboard_id)` | Adds it to the current user's favorites only |
| `ws.unfavorite_dashboard(dashboard_id)` | Removes the favorite |
| `ws.delete_dashboard(dashboard_id)` | Deletes it permanently |
| `ws.bulk_delete_dashboards([...])` | Deletes several in one call |

Ask the user before a delete, because the delete is permanent.
