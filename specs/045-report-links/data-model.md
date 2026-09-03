# Data Model: Report Links

**Feature**: 045-report-links | **Date**: 2026-09-02

This file describes every new type, its fields, its validation rules, and its relationships. Signatures for methods live in [contracts/python-api.md](contracts/python-api.md).

## Entity map

```text
query params (dict) ──create_report_link──▶ ReportLink ──url──▶ browser
                                              │
                                              ▼ (server stores)
                                        BookmarkUrl record
                                              ▲
link string ──parse_report_link──▶ ParsedReportLink ──resolve_report_link──▶ ResolvedReport ──query_report_link──▶ typed result
                                       │                                          │
                                       └─ kind=bookmark ─────── get_bookmark ─────┘ (Bookmark, existing)
```

## 1. `ParsedReportLink` (internal, frozen dataclass)

Module: `_internal/report_links.py`. Pure data. Never exported.

| Field | Type | Notes |
|-------|------|-------|
| `kind` | `Literal["slug", "bookmark", "short_link", "dashboard", "legacy_jsurl"]` | What the link points at |
| `raw` | `str` | The input after `strip()` |
| `host` | `str \| None` | Lower-case, no port. `None` for a bare slug |
| `region` | `Literal["us", "eu", "in"] \| None` | From the host. `mixpanel.org` maps to `us` |
| `project_id` | `int \| None` | From `/project/{pid}/` or legacy `/report/{pid}/` |
| `workspace_id` | `int \| None` | From `/view/{wid}/` |
| `app` | `str \| None` | `insights`, `funnels`, `retention`, `flows`, `impact`, `boards` |
| `report_type_hint` | `str \| None` | `APP_TO_REPORT_TYPE[app]`. The server type is authoritative |
| `slug` | `str \| None` | Set when `kind == "slug"` |
| `bookmark_id` | `int \| None` | Set when `kind == "bookmark"` |
| `dashboard_id` | `int \| None` | Set for `boards#id=` links, kept when an `edited-bookmark` slug is also present |
| `short_code` | `str \| None` | Set when `kind == "short_link"` |
| `title_segment` | `str \| None` | The kebab title after `#report/{id}/` |
| `overrides_jsurl` | `str \| None` | The raw `~(...)` tail after a bookmark hash. Never decoded |

**Invariants** (enforced by PBT):
- `kind == "slug"` implies `slug` is set and `is_slug(slug)` is true.
- `kind == "bookmark"` implies `bookmark_id` is set.
- `kind == "short_link"` implies `short_code` and `region` are set.
- `kind == "dashboard"` implies `dashboard_id` is set.
- A bare slug has `host`, `region`, `project_id`, and `workspace_id` all `None`.

## 2. `ReportLinkType` (public type alias)

```python
ReportLinkType = Literal["insights", "funnels", "retention", "flows"]
```

The four types the `bookmark-urls` endpoint accepts. `launch-analysis` is a valid `BookmarkType` for saved-report URLs but not for slug records.

## 3. `BookmarkUrl` (public Pydantic model)

The server record for an unsaved report. Config: `frozen=True, extra="allow", populate_by_name=True`, the same as `Bookmark`.

| Field | Type | Alias | Notes |
|-------|------|-------|-------|
| `slug` | `str` | | 12 characters |
| `bookmark_type` | `str` | `type` | `insights`, `funnels`, `retention`, or `flows` |
| `params` | `dict[str, Any]` | | Default empty dict |
| `name` | `str \| None` | | |
| `description` | `str \| None` | | |
| `overrides` | `dict[str, Any] \| None` | | For example `originDashboard`. Surfaced, never merged |
| `project_id` | `int \| None` | | |
| `user_id` | `int \| None` | | Creator |
| `created_at` | `str \| None` | | ISO timestamp from the server |
| `bookmark_id` | `int \| None` | | Present only when the server did not expand it |
| `bookmark` | `Bookmark \| None` | | The server replaces `bookmark_id` with the full saved report when one exists |

**Validation**: Pydantic. Unknown keys are kept under `extra`.

## 4. `ReportLink` (public frozen dataclass)

The result of `create_report_link`.

| Field | Type | Default | Notes |
|-------|------|---------|-------|
| `url` | `str` | | From `build_slug_url` |
| `slug` | `str` | | |
| `report_type` | `ReportLinkType` | | |
| `project_id` | `int` | | |
| `workspace_id` | `int \| None` | | `None` when the URL is project-only |
| `name` | `str` | `""` | |
| `description` | `str` | `""` | |
| `bookmark_id` | `int \| None` | `None` | |
| `created_at` | `str \| None` | `None` | From the server response |

Methods: `to_dict() -> dict[str, Any]` returns every field. `__str__` returns `url`.

## 5. `ResolvedReport` (public frozen dataclass)

The result of `resolve_report_link`. The input to `query_report_link`.

| Field | Type | Notes |
|-------|------|-------|
| `source` | `Literal["slug", "bookmark"]` | Which record type was fetched |
| `report_type` | `str` | Server `type` for a slug, `Bookmark.bookmark_type` for a bookmark. May be `launch-analysis` |
| `params` | `dict[str, Any]` | The raw parameters. Never merged with overrides |
| `project_id` | `int` | |
| `workspace_id` | `int \| None` | URL `wid`, else the session pin, else `None` |
| `region` | `str` | Session region |
| `url` | `str` | Canonical rebuilt URL from `build_slug_url` or `build_bookmark_url` |
| `input` | `str` | What the caller passed |
| `expanded_url` | `str \| None` | The shortlink target, else `None` |
| `slug` | `str \| None` | |
| `bookmark_id` | `int \| None` | |
| `bookmark` | `Bookmark \| None` | Set for a bookmark link, or for a slug record with an embedded bookmark |
| `name` | `str \| None` | |
| `description` | `str \| None` | |
| `overrides` | `dict[str, Any] \| None` | Slug record overrides |

Methods: `to_dict() -> dict[str, Any]`. The `bookmark` field serializes with `model_dump(mode="json", by_alias=True)`.

## 6. `ReportLinkQueryResult` (public type alias)

```python
ReportLinkQueryResult = QueryResult | FunnelQueryResult | RetentionQueryResult | FlowQueryResult
```

The return type of `query_report_link`. Callers narrow by `isinstance` or by `ResolvedReport.report_type`.

## 7. Exceptions

All new classes live in `exceptions.py` after the 044 session-replay block.

| Class | Base | Default code | Other codes |
|-------|------|--------------|-------------|
| `ReportLinkError` | `MixpanelHeadlessError` | `REPORT_LINK_ERROR` | |
| `ReportLinkParseError` | `ReportLinkError` | `REPORT_LINK_UNPARSEABLE` | `REPORT_LINK_NOT_MIXPANEL_HOST`, `REPORT_LINK_UNRECOGNIZED_PATH`, `REPORT_LINK_UNRECOGNIZED_HASH`, `REPORT_LINK_EMPTY_HASH` |
| `UnsupportedReportLinkError` | `ReportLinkError` | `UNSUPPORTED_REPORT_LINK` | `UNSUPPORTED_LEGACY_HASH`, `UNSUPPORTED_DASHBOARD_LINK`, `UNSUPPORTED_REPORT_TYPE` |
| `ReportLinkNotFoundError` | `ReportLinkError` | `REPORT_LINK_NOT_FOUND` | `REPORT_LINK_SLUG_NOT_FOUND`, `REPORT_LINK_BOOKMARK_NOT_FOUND`, `SHORT_LINK_NOT_FOUND` |
| `ReportLinkScopeMismatchError` | `ReportLinkError` | `REPORT_LINK_SCOPE_MISMATCH` | `REPORT_LINK_PROJECT_MISMATCH`, `REPORT_LINK_REGION_MISMATCH` |
| `ShortLinkResolutionError` | `ReportLinkError` | `SHORT_LINK_RESOLUTION_ERROR` | `SHORT_LINK_NO_LOCATION`, `SHORT_LINK_UNEXPECTED_RESPONSE`, `SHORT_LINK_CHAIN` |

`details` always carries the parsed fields (`kind`, `region`, `project_id`, `slug`, `bookmark_id`, `short_code`, as available) plus a `hint` string when one exists.

Builder guards raised as `ParamValidationError` and registered in `CODED_GUARD_REGISTRY`:

| Code | Raised by | Condition |
|------|-----------|-----------|
| `RL1_UNKNOWN_REPORT_TYPE` | `build_slug_url`, `build_bookmark_url`, `saved_report_link` | type not in the relevant table |
| `RL2_INVALID_SLUG` | `build_slug_url` | `is_slug(slug)` is false |
| `RL3_UNKNOWN_REGION` | `web_host`, both builders | region not in `WEB_HOSTS` |
| `RL4_REPORT_TYPE_CONFLICT` | `create_report_link` | explicit `report_type` contradicts the result class |
| `RL5_RESOLVED_REPORT_INCONSISTENT` | `ResolvedReport.__post_init__` | `source="slug"` without `slug`, or `source="bookmark"` without `bookmark_id` (PR #223 review) |
| `RL6_INVALID_ID` | both builders, `saved_report_link` | a zero or negative project, workspace, or bookmark id; the parser reads ASCII digit runs only, so such a URL would not round-trip (PR #223 review) |

## 8. Constants (pure module)

| Name | Value |
|------|-------|
| `SLUG_ALPHABET` | `123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz` |
| `SLUG_LENGTH` | `12` |
| `SLUG_RE` | `^[0-9a-zA-Z_-]{12}$` (the server regex, wider than the mint alphabet) |
| `WEB_HOSTS` | `{"us": "mixpanel.com", "eu": "eu.mixpanel.com", "in": "in.mixpanel.com"}` |
| `SLUG_APP_FOR_TYPE` | `{"insights": "insights", "funnels": "insights", "retention": "insights", "flows": "flows"}` |
| `BOOKMARK_HASH_FOR_TYPE` | `{"insights": "insights#report/{id}", "funnels": "funnels#view/{id}", "retention": "retention#report/{id}", "flows": "flows#report/{id}", "launch-analysis": "impact#report/{id}"}` |
| `APP_TO_REPORT_TYPE` | `{"insights": "insights", "funnels": "funnels", "retention": "retention", "flows": "flows", "impact": "launch-analysis"}` |

## 9. State and lifecycle

There is no client-side state. A slug record is created once and never updated or deleted by headless. `Workspace` methods read the session at call time, so `ws.use(project=...)` between calls changes the scope of the next call.
