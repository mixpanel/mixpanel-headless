# Contract: URL Grammar

**Feature**: 045-report-links
**Surface**: `parse_report_link`, `build_slug_url`, `build_bookmark_url` in `_internal/report_links.py`
**Audience**: The implementer and the test author

This grammar is the specification for `tests/unit/test_report_links.py`. Each row is one parametrized case. The PBT file covers the round trip and the decoration invariance across all rows.

---

## 1. Normalization (before parsing)

Apply in order:

1. `strip()`.
2. If the string has no `#` but has `%23`, `urllib.parse.unquote` it once.
3. If the string has no scheme and starts with a known host (`mixpanel.com`, `eu.mixpanel.com`, `in.mixpanel.com`, `mixpanel.org`), prepend `https://`.
4. Parse with `urllib.parse.urlsplit`. Lower-case the host. Drop the port.
5. Ignore the query string.
6. Split the path on `/` and drop empty segments. This handles a trailing `/` before `#`.

If the whole string matches `SLUG_RE` before step 3, return `kind="slug"` with only `slug` and `raw` set.

## 2. Host to region

| Host | Region |
|------|--------|
| `mixpanel.com` | `us` |
| `eu.mixpanel.com` | `eu` |
| `in.mixpanel.com` | `in` |
| `mixpanel.org` | `us` (parse only; builders emit `.com`) |
| Any other host, including `api.mixpanel.com` | raise `REPORT_LINK_NOT_MIXPANEL_HOST` |

## 3. Path forms

| Path segments | Result |
|---------------|--------|
| `s`, `{code}` | `kind="short_link"`, `short_code={code}` |
| `project`, `{pid}`, `app`, `{app}` | `project_id`, `app` |
| `project`, `{pid}`, `view`, `{wid}`, `app`, `{app}` | plus `workspace_id` |
| `report`, `{pid}`, `{app}` | legacy Django path, same as above |
| `report`, `{pid}`, `view`, `{wid}`, `{app}` | legacy with workspace |
| Anything else | raise `REPORT_LINK_UNRECOGNIZED_PATH` |

`{pid}` and `{wid}` must be all digits. `{app}` must be one of `insights`, `funnels`, `retention`, `flows`, `impact`, `boards`. `report_type_hint = APP_TO_REPORT_TYPE.get(app)`, which is `None` for `boards`.

## 4. Hash forms inside an app path

Precedence is top to bottom. The first matching row wins.

| Hash | Result |
|------|--------|
| empty | raise `REPORT_LINK_EMPTY_HASH` |
| `report/{id}` | `kind="bookmark"`, `bookmark_id={id}` |
| `report/{id}/{title}` | plus `title_segment` |
| `report/{id}/{title}/~(...)` | plus `overrides_jsurl` (raw, never decoded) |
| `report/{id}/~(...)` | plus `overrides_jsurl` |
| `segmentation-report/{id}` | `kind="bookmark"` |
| `view/{id}` | `kind="bookmark"` (funnels form) |
| `id={did}&edited-bookmark={slug}` on `boards` | `kind="slug"`, `slug`, `dashboard_id` kept |
| `id={did}` on `boards` | `kind="dashboard"`, `dashboard_id` |
| exact `SLUG_RE` match | `kind="slug"` |
| starts with `~` | `kind="legacy_jsurl"` |
| anything else | raise `REPORT_LINK_UNRECOGNIZED_HASH` |

## 5. Parametrized table

| Input | kind | Fields |
|-------|------|--------|
| `EBrV5bW2u9Mw` | slug | `slug` only |
| `  EBrV5bW2u9Mw  ` | slug | same after strip |
| `https://mixpanel.com/s/AbC123` | short_link | `short_code=AbC123`, `region=us` |
| `https://eu.mixpanel.com/s/AbC123` | short_link | `region=eu` |
| `https://eu.mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw` | slug | `region=eu`, `project_id=3`, `workspace_id=75`, `app=insights`, `hint=insights` |
| `https://mixpanel.com/project/3/app/insights/#EBrV5bW2u9Mw` | slug | `project_id=3`, `workspace_id=None` |
| `https://mixpanel.com/project/3/app/insights#report/123` | bookmark | `bookmark_id=123`, `hint=insights` |
| `https://mixpanel.com/project/3/app/insights#report/123/weekly-actives` | bookmark | plus `title_segment=weekly-actives` |
| `https://mixpanel.com/project/3/app/insights#report/123/weekly-actives/~(a~1)` | bookmark | plus `overrides_jsurl=~(a~1)` |
| `https://mixpanel.com/project/3/app/funnels#view/456` | bookmark | `bookmark_id=456`, `hint=funnels` |
| `https://mixpanel.com/project/3/app/retention#report/7` | bookmark | `hint=retention` |
| `https://mixpanel.com/project/3/app/flows#report/8` | bookmark | `hint=flows` |
| `https://mixpanel.com/project/3/app/insights#segmentation-report/9` | bookmark | `bookmark_id=9`, `hint=insights` |
| `https://mixpanel.com/project/3/app/impact#report/10` | bookmark | `hint=launch-analysis` |
| `https://mixpanel.com/report/3/insights#report/123` | bookmark | legacy path, `project_id=3` |
| `https://mixpanel.com/report/3/view/75/insights#report/123` | bookmark | legacy, `workspace_id=75` |
| `in.mixpanel.com/project/3/app/insights#EBrV5bW2u9Mw` | slug | no scheme, `region=in` |
| `HTTPS://MIXPANEL.COM/project/3/app/insights#EBrV5bW2u9Mw` | slug | host lower-cased |
| `https://mixpanel.com:443/project/3/app/insights#EBrV5bW2u9Mw` | slug | port dropped |
| `https://mixpanel.com/project/3/app/insights?utm=x#EBrV5bW2u9Mw` | slug | query ignored |
| `https://mixpanel.com/project/3/app/insights%23EBrV5bW2u9Mw` | slug | `%23` unquoted |
| `https://mixpanel.org/project/3/app/insights#EBrV5bW2u9Mw` | slug | `region=us` |
| `https://mixpanel.com/project/3/app/boards#id=555` | dashboard | `dashboard_id=555` |
| `https://mixpanel.com/project/3/app/boards#id=555&edited-bookmark=EBrV5bW2u9Mw` | slug | `slug`, `dashboard_id=555` |
| `https://mixpanel.com/project/3/app/insights#~(sections~(...))` | legacy_jsurl | |
| `https://mixpanel.com/project/3/app/insights` | error | `REPORT_LINK_EMPTY_HASH` |
| `https://mixpanel.com/project/3/app/insights#` | error | `REPORT_LINK_EMPTY_HASH` |
| `https://example.com/project/3/app/insights#EBrV5bW2u9Mw` | error | `REPORT_LINK_NOT_MIXPANEL_HOST` |
| `https://api.mixpanel.com/project/3/app/insights#x` | error | `REPORT_LINK_NOT_MIXPANEL_HOST` |
| `https://mixpanel.com/settings/project/3` | error | `REPORT_LINK_UNRECOGNIZED_PATH` |
| `https://mixpanel.com/project/abc/app/insights#EBrV5bW2u9Mw` | error | `REPORT_LINK_UNRECOGNIZED_PATH` |
| `https://mixpanel.com/project/3/app/insights#foo/bar` | error | `REPORT_LINK_UNRECOGNIZED_HASH` |
| `https://mixpanel.com/project/3/app/insights#tooShort` | error | `REPORT_LINK_UNRECOGNIZED_HASH` |
| `` (empty) | error | `REPORT_LINK_UNPARSEABLE` |
| `not a url at all` | error | `REPORT_LINK_UNPARSEABLE` |

## 6. Builders

| Call | Output |
|------|--------|
| `build_slug_url(region="us", project_id=3, slug=S, report_type="insights", workspace_id=75)` | `https://mixpanel.com/project/3/view/75/app/insights#S` |
| `build_slug_url(region="eu", project_id=3, slug=S, report_type="funnels")` | `https://eu.mixpanel.com/project/3/app/insights#S` |
| `build_slug_url(region="in", project_id=3, slug=S, report_type="flows")` | `https://in.mixpanel.com/project/3/app/flows#S` |
| `build_bookmark_url(region="us", project_id=3, bookmark_id=123, report_type="insights")` | `https://mixpanel.com/project/3/app/insights#report/123` |
| `build_bookmark_url(..., report_type="funnels", workspace_id=75)` | `https://mixpanel.com/project/3/view/75/app/funnels#view/123` |
| `build_bookmark_url(..., report_type="retention")` | `.../app/retention#report/123` |
| `build_bookmark_url(..., report_type="flows")` | `.../app/flows#report/123` |
| `build_bookmark_url(..., report_type="launch-analysis")` | `.../app/impact#report/123` |
| `build_slug_url(..., report_type="boards")` | raise `RL1_UNKNOWN_REPORT_TYPE` |
| `build_slug_url(..., slug="short")` | raise `RL2_INVALID_SLUG` |
| `build_slug_url(region="jp", ...)` | raise `RL3_UNKNOWN_REGION` |

## 7. Property-based invariants

1. `generate_slug()` has length 12, every character is in `SLUG_ALPHABET`, and `is_slug` returns true.
2. `parse_report_link(build_slug_url(region, pid, slug, type, wid))` returns `kind="slug"` with `region`, `project_id`, `workspace_id`, `slug` equal to the inputs, for all three regions, all positive ints, optional workspace ids, valid slugs, and the four types.
3. Same round trip for `build_bookmark_url` across the five bookmark types, with `bookmark_id` equal and `report_type_hint` equal to the input type.
4. Decoration invariance: for any built URL, adding a trailing `/` before `#`, a `?utm=` query, an upper-case host, a missing scheme, or a `%23` in place of `#` yields an equal `ParsedReportLink` except for the `raw` field.
5. Totality: for any `st.text()` input, `parse_report_link` either returns a `ParsedReportLink` or raises `ReportLinkParseError`. It never raises anything else.
6. Every result with `kind="slug"` has `slug` set. Every `kind="bookmark"` has `bookmark_id` set. Every `kind="short_link"` has `short_code` set. Every `kind="dashboard"` has `dashboard_id` set.
7. Any string whose length is not 12, or that has a character outside `[0-9A-Za-z_-]`, is never a slug.
