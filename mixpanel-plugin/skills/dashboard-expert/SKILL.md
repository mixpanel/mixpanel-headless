---
name: dashboard-expert
description: >-
  Analyzes, builds, modifies, and annotates Mixpanel dashboards with the
  mixpanel_headless Python library. It reads a dashboard's layout and runs
  every report on it, creates dashboards with text cards and a grid layout,
  edits cells and rows in place, and writes data-driven explainer cards. Use
  when the user asks to analyze, summarize, explain, build, create, redesign,
  update, reorganize, or clean up a Mixpanel dashboard; asks about dashboard
  layout, rows, cell widths, text cards, or which chart type suits a board;
  or wants to turn queries into reports placed on a dashboard. Do not use for
  general analytics questions or one-off queries (use mixpanelyst), or for
  what a specific user did in a session recording (use session-replay).
allowed-tools: Bash(mp *) Bash(python3 *) Bash(python *) Bash(uv run *) Read Write WebFetch(domain:mixpanel.github.io)
---

# Dashboard Expert

Analyze, build, modify, and explain Mixpanel dashboards with `mixpanel_headless`. A dashboard is a list of rows. Each row holds one to four cells on a 12-column grid. A cell is a report (owned by this dashboard), a report link (owned by another dashboard, read-only), or a text card (HTML).

## Pick the mode

| User intent | Mode | Steps | Read first |
|---|---|---|---|
| Analyze, read, understand, audit a dashboard | **Analyze** | Read the layout, run each report, summarize by section | `references/content-and-layout.md` (analyze steps) |
| Build, create, make a new dashboard | **Build** | Check the data, plan the sections, create with rows in one call, pin | `references/report-pipeline.md` and `references/templates.md` |
| Modify, add to, fix, reorganize a dashboard | **Modify** | Read the current state, plan the changes, apply them in the fixed order | `references/content-and-layout.md` (modify steps) |
| Explain, annotate, add insights to a dashboard | **Explain** | Analyze, compute key numbers, insert explainer cards | `references/text-cards.md` |

Show the user a plan before you create or change a dashboard. A dashboard is shared team state, and a wrong layout is slow to undo.

## Quick start: analyze a dashboard

```python
import re
import mixpanel_headless as mp

ws = mp.Workspace()
dash = ws.get_dashboard(DASHBOARD_ID)
layout, contents = dash.layout, dash.contents

# Rows -> cells -> content items
for row_id in layout["order"]:
    for cell in layout["rows"][row_id]["cells"]:
        cid, ctype = str(cell["content_id"]), cell["content_type"]
        if ctype in ("report", "report-link"):
            info = contents["report"][cid]
            tag = " [linked]" if ctype == "report-link" else ""
            print(f"[{cell['width']}w] {info['name']} ({info['type']}){tag}")
        elif ctype == "text":
            md = contents["text"][cid].get("markdown", "")
            header = " [SECTION]" if re.search(r"<h2[\s>]", md, re.I) else ""
            print(f"[{cell['width']}w] TEXT{header}: {md[:60]}")

# Run each report -> DataFrame
for cid, info in contents.get("report", {}).items():
    btype, bid = info["type"], info["id"]
    if btype == "flows":
        result = ws.query_saved_flows(bid)
    elif btype == "funnels":
        # Without dates, a saved funnel runs over the last 30 days.
        result = ws.query_saved_report(
            bid, bookmark_type="funnels", from_date="2026-06-01", to_date="2026-08-31"
        )
    else:
        result = ws.query_saved_report(bid, bookmark_type=btype)
    print(f"{info['name']}: {len(result.df)} rows, columns={list(result.df.columns)}")
```

## Quick start: build a dashboard

```python
import json
import mixpanel_headless as mp
from mixpanel_headless.types import CreateDashboardParams, DashboardRow, DashboardRowContent

ws = mp.Workspace()
dau = ws.query("Login", math="dau", last=90)
signups = ws.query("Sign Up", math="total", last=90)


def text(html):
    return DashboardRowContent(content_type="text", content_params={"markdown": html})


def report(name, btype, result):
    return DashboardRowContent(
        content_type="report",
        content_params={"bookmark": {
            "name": name, "type": btype, "params": json.dumps(result.params),
        }},
    )


dashboard = ws.create_dashboard(CreateDashboardParams(
    title="Product Health",
    description="Core metrics.",
    rows=[
        DashboardRow(contents=[text("<h2>Product Health</h2><p>Core metrics, last 90 days.</p>")]),
        DashboardRow(contents=[
            report("DAU (90d)", "insights", dau),
            report("Signups (90d)", "insights", signups),
        ]),
    ],
))
ws.pin_dashboard(dashboard.id)  # new dashboards are not visible to the team until pinned
```

`rows` places every cell in one call, and the cells in a row share the 12 columns evenly. Check each result before you add it: skip a report whose `result.df` is empty, because an empty chart on a shared board looks like a bug.

## Mode steps in short

**Analyze.** Read the structure (quick start above). Group cells into sections: a text card with an `<h2>` starts a section. Run every report and extract the key numbers for its type. Look for links between reports, for example a DAU trend against a retention curve. Present an overview, a section-by-section summary, cross-report findings, and suggestions.

**Build.** Check that each candidate event has volume. Pick a template from `references/templates.md` and map its placeholders to real events. Present the plan. Query each metric, then create the dashboard with `rows` in one call. Pin it. Open it and confirm every report renders.

**Modify.** Read the current state first and show it to the user. Classify each change. Apply the changes in the order in gotcha 3. Read the dashboard again between layout changes, because row and cell IDs change.

**Explain.** Run the analyze steps. For each report, compute the latest value and the change against a baseline from `result.df`. Insert a short explainer card under the chart it explains. The card patterns and the HTML rules are in `references/text-cards.md`.

## Gotchas

These 14 rules come from failures against the live Mixpanel API. The library does not check most of them for you.

1. **Send `content` and `layout` together to place a cell in an existing row.** Put both in one `UpdateDashboardParams`. With `content` alone, the new cell goes to a new full-width row at the bottom.
2. **Redistribute widths when you add to a row.** A row with N cells gets N+1 cells of width `12 // (N + 1)`, because the widths in a row must sum to 12.
3. **Apply updates in this order:** metadata, cell creates, row reorder (`rows_order`), cell updates, cell deletes, row deletes. A reorder before a create fails with an unknown row ID, and an early delete can leave gaps.
4. **`per_user` needs `math_property`.** Without it, the query raises `BookmarkValidationError` before any network call. The same is true for `math="average"`, `"median"`, and the percentiles.
5. **`CreateBookmarkParams(dashboard_id=...)` does not place the report.** It only sets metadata. Place a report with an inline `bookmark` content action or with `rows`.
6. **`add_report_to_dashboard()` clones the report.** The copy gets a "Duplicate of ..." name and a new content ID. Prefer `rows` or an inline content action.
7. **The GET layout and the PATCH layout differ.** GET returns `order` and `rows` as a dict keyed by row ID. PATCH takes `rows_order` and `rows` as a list with an `id` on each row. A patch with `order` does not reorder anything.
8. **Leave `version` out of a layout PATCH.** GET returns `"version": "2.0.0"`, and the API rejects a patch that sends it back.
9. **Remove newlines from text card HTML.** Call `.replace("\n", "").strip()` before you send it. With newlines, the editor in Mixpanel parses the HTML as markdown and garbles it.
10. **Stay inside the limits:** title 255 characters, description 400, text card 2,000 (keep it under 500), 4 cells per row, 30 rows per dashboard.
11. **An update cannot change `content_type`.** To turn a text card into a report, delete the cell, then create a new one.
12. **Report-link cells are read-only.** A `report-link` cell shows a report that another dashboard owns. You can run it, but you cannot edit its params from this dashboard.
13. **Pin a new dashboard.** A new dashboard is not visible to the team until you call `ws.pin_dashboard(dashboard.id)`.
14. **The `markdown` field takes HTML only.** Markdown syntax such as `# Heading` or `**bold**` shows as literal text. Use `<h2>` and `<strong>`.

## Look up the API before you write code

The installed library documents itself, so do not guess a method name, a parameter, or a type field. Verify any signature with `mp help Workspace.<method>`, for example `mp help Workspace.update_dashboard`. Other useful look-ups:

- `mp help Workspace --domain dashboards` lists every dashboard method.
- `mp help Workspace --domain reports` lists the saved-report (bookmark) methods.
- `mp help CreateDashboardParams` and `mp help DashboardRow` show the fields and a worked example.

The full look-up loop is in the mixpanelyst skill. If `mp` is not on `PATH`, use `python3 -m mixpanel_headless help <query>`.

## Report links

To read a report URL that the user pasted, call `ws.resolve_report_link(link)`. It returns the params and the report type, and `ws.query_report_link(link)` runs it. To give the user a URL for a report on a dashboard, call `ws.saved_report_link(bookmark_id, report_type="funnels")` with the report's type.

## Reading guide

Read a reference only when its condition is true. Each file stands alone.

| Read | When |
|---|---|
| [references/content-and-layout.md](references/content-and-layout.md) | Before you analyze or modify a dashboard, and before any `update_dashboard` call that adds, moves, resizes, or deletes a cell or row. It covers content actions, the grid, the PATCH format, operation order, report-link semantics, time filters, and duplication. |
| [references/text-cards.md](references/text-cards.md) | Before you write or change a text card, and in Explain mode. It covers the allowed HTML, the whitespace rule, and card patterns. |
| [references/report-pipeline.md](references/report-pipeline.md) | Before you build a dashboard, or when you turn query results from any engine into reports on a dashboard. It covers the build steps and the query-to-report path for insights, funnels, retention, and flows. |
| [references/templates.md](references/templates.md) | When you plan a new dashboard or a new section. For layout and templates, read this file: it has nine dashboard templates with rows, widths, heights, text, and report specifications. |
| [references/chart-types.md](references/chart-types.md) | When you pick or check a chart type, or pick a width for a chart. |
