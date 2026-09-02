# Report Links

Turn a headless query into a shareable Mixpanel URL, or turn a Mixpanel report URL back into the query behind it and run it — from Python or the `mp` CLI.

!!! tip "Two directions, one round trip each"
    `create_report_link` makes one App API call and returns a URL. `resolve_report_link` makes at most two (one for a shortlink, one for the record) and returns the raw params. `saved_report_link` makes none.

## What a slug is

When you open a report in the Mixpanel web app the URL ends in a 12-character hash such as `https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw`. That hash is a **slug**: a lookup key for an **unsaved report** that Mixpanel stores on the server, per project and per region. It is not an encoded query, so nothing can decode it offline — headless reads the record back through the App API instead.

A **saved report** (a bookmark) has a numeric id and a different hash form, for example `#report/123` or, for funnels, `#view/123`. A **shortlink** looks like `https://mixpanel.com/s/AbC123` and redirects to one of the two forms above.

## Create a link

From a typed result — the report type is inferred from the result class:

```python
import mixpanel_headless as mp

ws = mp.Workspace()

result = ws.query(mp.Metric.total("Login"), last=7)
link = ws.create_report_link(result, name="Logins, last 7 days")
print(link.url)
# https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw
```

From raw params, without running the query first:

```python
params = ws.build_params("Login", last=7)
link = ws.create_report_link(params)                    # insights by default

funnel = ws.build_funnel_params([mp.FunnelStep("Login"), mp.FunnelStep("Purchase")], last=30)
link = ws.create_report_link(funnel, report_type="funnels")
```

`ReportLink` carries `url`, `slug`, `report_type`, `project_id`, `workspace_id`, `name`, `description`, `bookmark_id`, and `created_at`. `str(link)` is the URL.

Notes:

- Params are validated against the bookmark schema before the upload. Pass `validate=False` to skip the check.
- The `/view/{wid}` segment comes from an explicit `workspace_id`, then the pinned session workspace, then auto-resolution. If nothing resolves, the URL is project-only and still opens.
- An explicit `report_type` that contradicts the result class raises `ParamValidationError` (`RL4_REPORT_TYPE_CONFLICT`) before any network call.

From the CLI:

```bash
mp reports link --params-file params.json --name "Logins"
cat params.json | mp reports link -f plain            # prints only the URL
mp reports link --params '{"sections": {...}}' --type funnels --jq .url
```

## Resolve a link

`resolve_report_link` accepts a full URL, a bare slug, or a shortlink:

```python
r = ws.resolve_report_link("https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw")
r.report_type   # "insights"  (from the server record, not the URL)
r.params        # the raw params dict
r.url           # the canonical URL, rebuilt from the record

ws.resolve_report_link("EBrV5bW2u9Mw")                  # bare slug, active project
ws.resolve_report_link("https://mixpanel.com/s/AbC123")  # shortlink, followed once
ws.resolve_report_link("https://mixpanel.com/project/3/app/insights#report/123")  # saved report
```

`ResolvedReport` carries `source` (`slug` or `bookmark`), `report_type`, `params`, `project_id`, `workspace_id`, `region`, `url`, `input`, `expanded_url` (the shortlink target), `slug`, `bookmark_id`, `bookmark`, `name`, `description`, and `overrides`. Stored overrides are surfaced as data; they are never merged into `params`.

The Mixpanel server canonicalizes params when it stores them. The record you read back is the web app's internal form: it adds defaults such as `displayOptions.primaryYAxisOptions`, `behavior.behaviors`, and `executedMigrations`; for Insights it rewrites `behavior.type` from `event` to `simple`, may replace an auto-captured event name such as `$mp_web_page_view` with its display name `[Auto] Page View`, and drops `filtersDeterminer`. The canonical params run through `query_report_link` without change, but do not expect byte-equality with what you sent.

For a saved-report link the type comes from the bookmark itself, so a `/app/insights#report/123` link whose bookmark is a funnel resolves as `funnels`. A trailing `~(...)` override segment on a saved-report link is ignored with a warning; the base params are returned.

From the CLI — quote the URL, because `#` starts a shell comment:

```bash
mp reports resolve 'https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw'
mp reports resolve EBrV5bW2u9Mw --jq .params
```

## Run a resolved report

`query_report_link` dispatches on the report type to `query`, `query_funnel`, `query_retention`, or `query_flow` and returns the matching typed result:

```python
df = ws.query_report_link(r).df                 # already resolved: no second fetch
df = ws.query_report_link("EBrV5bW2u9Mw").df    # resolve and run in one call

resolved = ws.resolve_report_link(url)
if resolved.report_type == "flows":
    result = ws.query_report_link(resolved, mode="paths")   # else mode comes from params["chartType"]
```

A `launch-analysis` report resolves but cannot be run; `query_report_link` raises `UnsupportedReportLinkError` (`UNSUPPORTED_REPORT_TYPE`).

A `ResolvedReport` remembers the region, project, and workspace it was resolved in. If you keep one across `ws.use(project=...)` or `ws.use(workspace=...)`, or hand it to a Workspace on another project, `query_report_link` raises `ReportLinkScopeMismatchError` before it runs anything, the same check `resolve_report_link` applies to a URL. The workspace part applies only when the session has a pinned workspace and the report records one.

```bash
mp reports resolve 'https://mixpanel.com/s/AbC123' --run -f csv
mp reports resolve 'https://mixpanel.com/project/3/app/flows#report/8' --run --mode paths
```

## `--link` on query commands

Four `mp query` commands take an opt-in `--link` flag that adds a `report_url` key to the output. Without the flag the output is unchanged.

| Command | What `--link` does |
|---------|--------------------|
| `mp query segmentation -e EVENT --from D --to D [-u UNIT] [--on PROP] --link` | Builds Insights params for the same event, dates, unit, and breakdown, creates an unsaved report, and adds its URL. One network call. |
| `mp query funnel FUNNEL_ID ... --link` | Adds the saved funnel's URL. No network call. |
| `mp query saved-report ID --link` | Adds the saved report's URL, using the detected report type. No network call. |
| `mp query flows ID --link` | Adds the saved flows report's URL. No network call. |

```bash
mp query saved-report 123 --link --jq .report_url
mp query segmentation -e Login --from 2026-08-01 --to 2026-08-31 --link --jq .report_url
```

!!! note "The segmentation link is an approximation"
    The legacy segmentation endpoint and the Insights engine can differ at the edges. The link reproduces the event, the dates, the unit, and a **bare** breakdown property such as `--on country` or `--on 'Plan Type'`. With `--where`, or with an expression in `--on`, the command prints a warning on stderr and omits `report_url`. A link failure never fails the query: the result still prints and the exit code stays 0.

## Saved-report links without a network call

```python
ws.saved_report_link(123)                              # insights: .../app/insights#report/123
ws.saved_report_link(456, report_type="funnels")       # .../app/funnels#view/456
ws.saved_report_link(8, report_type="flows", workspace_id=75)
```

The singular `"funnel"` that `SavedReportResult.report_type` reports is accepted and normalized to `"funnels"`.

## When resolution fails

| Situation | Exception / code | What to do |
|-----------|------------------|------------|
| The link names another project | `ReportLinkScopeMismatchError` / `REPORT_LINK_PROJECT_MISMATCH` | Switch: `ws.use(project="3")` or `mp --project 3 ...`. No network call was made. |
| The link host is another region | `ReportLinkScopeMismatchError` / `REPORT_LINK_REGION_MISMATCH` | Use an account for that region: `mp --account NAME ...`. No network call was made. |
| The link names a workspace and your session is pinned to a different one | `ReportLinkScopeMismatchError` / `REPORT_LINK_WORKSPACE_MISMATCH` | Switch: `ws.use(workspace=75)` or `mp --workspace 75 ...`. Query requests carry the pinned workspace, so a different data view would change the results. Unpinned sessions accept any link. |
| The hash starts with `~(` | `UnsupportedReportLinkError` / `UNSUPPORTED_LEGACY_HASH` | Open the link in a browser. The app re-issues a slug on load; copy the new URL. |
| The link is a board | `UnsupportedReportLinkError` / `UNSUPPORTED_DASHBOARD_LINK` | `ws.get_dashboard(ID)` lists its reports; resolve one report link. A board URL that carries `edited-bookmark=<slug>` resolves that slug. |
| The slug is unknown here | `ReportLinkNotFoundError` / `REPORT_LINK_SLUG_NOT_FOUND` | A slug is readable only in the project and region that created it. |
| The shortlink redirects to another shortlink | `ShortLinkResolutionError` / `SHORT_LINK_CHAIN` | Resolve the target shortlink directly. Headless follows one redirect only. |
| The shortlink redirects to the login page | `AuthenticationError` | The credentials cannot see the shortlink. |

Every error in the family subclasses `ReportLinkError` and carries the parsed link parts plus a `hint` in `details`. CLI exit codes: not found 4; parse, unsupported, and scope errors 3; auth 2; shortlink extraction 1.

The parser tolerates surrounding whitespace, a trailing slash before `#`, a query string, an upper-case host, a missing scheme, a percent-encoded `#`, the legacy `/report/{pid}/` path form, and `mixpanel.org`.

## Out of scope

- Typed decompile of params into `Metric` / `Filter` / `GroupBy` objects (follow-up feature).
- Decode of legacy `~(...)` JSURL hashes.
- Creation of shortlinks. The Mixpanel server allows this only from a browser session.
- `--link` on `mp query retention` and on the other legacy query commands.
- Merge of stored overrides into params.
- Any change to how saved reports are created or edited.

## Next Steps

- [Typed Queries](query.md) — build the params you want to share
- [Live Analytics](live-analytics.md) — the legacy query commands that gained `--link`
- [Exceptions](../api/exceptions.md#report-link-exceptions) — the `ReportLinkError` family
