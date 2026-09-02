# Contract: Python API

**Feature**: 045-report-links
**Surface**: `mixpanel_headless` public exports plus the private client and pure module
**Audience**: Developers who use `mixpanel-headless` as a library, and the implementer

Shapes of the returned types are in [../data-model.md](../data-model.md). Stable error texts are in [error-messages.md](error-messages.md).

---

## 1. `Workspace` methods

### `create_report_link`

```python
def create_report_link(
    self,
    params: dict[str, Any] | QueryResult | FunnelQueryResult | RetentionQueryResult | FlowQueryResult,
    *,
    report_type: ReportLinkType | None = None,
    name: str = "",
    description: str = "",
    workspace_id: int | None = None,
    bookmark_id: int | None = None,
    validate: bool = True,
) -> ReportLink:
```

Behavior:
1. If `params` is a typed result, take `result.params` and infer `report_type`: `QueryResult` is `insights`, `FunnelQueryResult` is `funnels`, `RetentionQueryResult` is `retention`, `FlowQueryResult` is `flows`. If the caller also passed `report_type` and it differs, raise `ParamValidationError("RL4_REPORT_TYPE_CONFLICT")`.
2. If `params` is a dict and `report_type` is `None`, use `insights`.
3. If `validate`, run `_validate_bookmark_params_schema(params, report_type)`. Any severity `error` raises `BookmarkValidationError`.
4. Generate a slug with `generate_slug()`.
5. Resolve the workspace with `_report_link_workspace_id(workspace_id)`.
6. `POST` through `MixpanelAPIClient.create_bookmark_url` with `{slug, type, params}` plus `name`, `description`, `bookmark_id` when set.
7. Return `ReportLink` with `url = build_slug_url(...)` and `created_at` from the response.

Raises: `ParamValidationError`, `BookmarkValidationError`, `QueryError`, `AuthenticationError`, `RateLimitError`, `ServerError`.

### `resolve_report_link`

```python
def resolve_report_link(self, link: str) -> ResolvedReport:
```

Behavior:
1. `parsed = parse_report_link(link)`.
2. If `parsed.kind == "short_link"`, call `client.resolve_short_link(code)`, then parse the target. If the target is also a short link, raise `ShortLinkResolutionError("SHORT_LINK_CHAIN")`. Keep the target as `expanded_url`.
3. If `kind == "dashboard"`, raise `UnsupportedReportLinkError("UNSUPPORTED_DASHBOARD_LINK")`. If `kind == "legacy_jsurl"`, raise `UnsupportedReportLinkError("UNSUPPORTED_LEGACY_HASH")`.
4. If `parsed.region` is set and differs from `self.session.region`, raise `ReportLinkScopeMismatchError("REPORT_LINK_REGION_MISMATCH")`. If `parsed.project_id` is set and differs from `int(self.project.id)`, raise `ReportLinkScopeMismatchError("REPORT_LINK_PROJECT_MISMATCH")`. A bare slug skips both.
5. If `kind == "slug"`, fetch with `client.get_bookmark_url(slug)` and build `BookmarkUrl`. `report_type` is the record `type`. `bookmark` is the embedded bookmark when present.
6. If `kind == "bookmark"`, fetch with `self.get_bookmark(bookmark_id)`. `report_type` is `bookmark.bookmark_type`. If `parsed.overrides_jsurl` is set, log a warning that overrides are ignored.
7. `workspace_id` is `parsed.workspace_id`, else the pinned session workspace, else `None`. Never call `resolve_workspace_id()` here.
8. Rebuild `url` with `build_slug_url` or `build_bookmark_url`.

Raises: `ReportLinkParseError`, `UnsupportedReportLinkError`, `ReportLinkScopeMismatchError`, `ReportLinkNotFoundError`, `ShortLinkResolutionError`, `AuthenticationError`, `RateLimitError`, `ServerError`, `QueryError`.

### `query_report_link`

```python
def query_report_link(
    self,
    link: str | ResolvedReport,
    *,
    mode: Literal["sankey", "paths", "tree"] | None = None,
) -> ReportLinkQueryResult:
```

Behavior:
1. If `link` is a `str`, call `resolve_report_link`. If it is a `ResolvedReport`, use it as is. No second fetch.
2. Dispatch on `report_type` with `pid = int(self.project.id)`:
   - `insights` calls `LiveQueryService.query(params, pid)`.
   - `funnels` calls `query_funnel(params, pid)`.
   - `retention` calls `query_retention(params, pid)`.
   - `flows` calls `query_flow(params, pid, mode=derived)`. `derived` is `mode` when given, else `params["chartType"]` when it is one of `sankey`, `paths`, `tree`, else `sankey`.
   - Any other type raises `UnsupportedReportLinkError("UNSUPPORTED_REPORT_TYPE")`.

Raises: everything `resolve_report_link` raises, plus `UnsupportedReportLinkError` and the query engine errors.

### `saved_report_link`

```python
def saved_report_link(
    self,
    bookmark_id: int,
    *,
    report_type: BookmarkType | Literal["funnel"] = "insights",
    workspace_id: int | None = None,
) -> str:
```

Behavior: pure. Normalize `"funnel"` to `"funnels"`. Workspace is the explicit argument, else the pinned session workspace, else `None`. Never calls `resolve_workspace_id()`. Returns `build_bookmark_url(region=self.session.region, project_id=int(self.project.id), bookmark_id=..., report_type=..., workspace_id=...)`.

Raises: `ParamValidationError` with `RL1_UNKNOWN_REPORT_TYPE` or `RL3_UNKNOWN_REGION`.

### `_report_link_workspace_id` (private helper)

```python
def _report_link_workspace_id(self, explicit: int | None) -> int | None:
```

Returns `explicit` when set, else the pinned session workspace, else `self.resolve_workspace_id()`. On `WorkspaceScopeError`, logs at debug and returns `None`.

---

## 2. `MixpanelAPIClient` methods

### `create_bookmark_url`

```python
def create_bookmark_url(self, body: dict[str, Any]) -> dict[str, Any]:
```

`app_request("POST", f"/projects/{pid}/bookmark-urls/", json_body=body)`. Body keys: `slug`, `type`, `params`, optional `name`, `description`, `bookmark_id`. Never contains `workspace_id`. Returns the unwrapped `results` dict. Asserts a dict like `get_bookmark`. Errors pass through.

### `get_bookmark_url`

```python
def get_bookmark_url(self, slug: str) -> dict[str, Any]:
```

`app_request("GET", f"/projects/{pid}/bookmark-urls/{slug}/")`. Always project-scoped, even when a workspace is pinned. Does not use `maybe_scoped_path`. A `QueryError` with status 404 becomes `ReportLinkNotFoundError("REPORT_LINK_SLUG_NOT_FOUND")`. Other errors pass through.

### `resolve_short_link`

```python
def resolve_short_link(self, code: str) -> str:
```

Request: `self._ensure_client().get(f"https://{web_host(self.region)}/s/{code}", headers=self._request_headers({"Authorization": self._get_auth_header()}), follow_redirects=False, timeout=DEFAULT_APP_TIMEOUT_S)`.

| Response | Result |
|----------|--------|
| 301, 302, 303, 307, 308 with `Location` | Return `Location`, `urljoin`-ed against the request URL when relative. If the `Location` path starts with `/login`, raise `AuthenticationError`. |
| 3xx without `Location` | `ShortLinkResolutionError("SHORT_LINK_NO_LOCATION")` |
| 200 with `window.location.href="..."` in the body | `json.loads` the quoted string and return it. Regex: `window\.location\.href\s*=\s*("(?:[^"\\]|\\.)*")` |
| 200 without that script | `ShortLinkResolutionError("SHORT_LINK_UNEXPECTED_RESPONSE")` |
| 401 | `AuthenticationError` |
| 404 | `ReportLinkNotFoundError("SHORT_LINK_NOT_FOUND")` |
| 429 | `RateLimitError` |
| 5xx | `ServerError` |
| `httpx.HTTPError` | `MixpanelHeadlessError(code="HTTP_ERROR")` |

The Authorization header is never logged.

---

## 3. Pure module `_internal/report_links.py`

```python
def web_host(region: str) -> str
def is_slug(value: str) -> bool
def generate_slug(*, choice: Callable[[str], str] = secrets.choice) -> str
def parse_report_link(value: str) -> ParsedReportLink
def build_slug_url(*, region: str, project_id: int, slug: str, report_type: str, workspace_id: int | None = None) -> str
def build_bookmark_url(*, region: str, project_id: int, bookmark_id: int, report_type: str, workspace_id: int | None = None) -> str
```

- `generate_slug` draws 12 characters from `SLUG_ALPHABET` with the injected `choice`, so tests can make it deterministic.
- `build_slug_url` returns `https://{host}/project/{pid}/view/{wid}/app/{SLUG_APP_FOR_TYPE[type]}#{slug}`, or omits `/view/{wid}` when `workspace_id` is `None`.
- `build_bookmark_url` returns `https://{host}/project/{pid}[/view/{wid}]/app/{BOOKMARK_HASH_FOR_TYPE[type].format(id=bookmark_id)}`.
- The grammar for `parse_report_link` is in [url-grammar.md](url-grammar.md).

---

## 4. Public exports (`__init__.py`)

Under a `# Report links (AIE-561/562)` comment group:

```python
ReportLinkType, BookmarkUrl, ReportLink, ResolvedReport, ReportLinkQueryResult,
ReportLinkError, ReportLinkParseError, UnsupportedReportLinkError,
ReportLinkNotFoundError, ReportLinkScopeMismatchError, ShortLinkResolutionError,
```

`ParsedReportLink` and the pure functions stay private. The `help.py` script in the plugin picks up the new `Workspace` methods automatically.

---

## 5. Usage examples

```python
import mixpanel_headless as mp

ws = mp.Workspace()

# Create a link from a query result
result = ws.query(mp.Metric.total("Login"), last=7)
link = ws.create_report_link(result, name="Logins, last 7 days")
print(link.url)

# Create a link from raw params
params = ws.build_params("Login", last=7)
link = ws.create_report_link(params)

# Resolve and run
resolved = ws.resolve_report_link("https://mixpanel.com/project/3/view/75/app/insights#EBrV5bW2u9Mw")
resolved.report_type   # "insights"
resolved.params        # raw dict
df = ws.query_report_link(resolved).df

# One call
df = ws.query_report_link("EBrV5bW2u9Mw").df

# Saved report link, no network
ws.saved_report_link(123, report_type="funnels")
```
