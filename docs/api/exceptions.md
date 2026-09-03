# Exceptions

All library exceptions inherit from `MixpanelHeadlessError`, enabling callers to catch all library errors with a single except clause.

!!! tip "Explore on DeepWiki"
    🤖 **[Error Handling Guide →](https://deepwiki.com/mixpanel/mixpanel-headless/7.4-error-codes-and-exceptions)**

    Ask questions about specific exceptions, error recovery patterns, or debugging strategies.

## Exception Hierarchy

```
MixpanelHeadlessError
├── ConfigError
│   ├── AccountNotFoundError
│   ├── AccountExistsError
│   ├── AccountInUseError
│   ├── InvalidArgumentError
│   └── ProjectNotFoundError
├── APIError
│   ├── AuthenticationError
│   ├── RateLimitError
│   ├── QueryError
│   └── ServerError
├── OAuthError
│   └── RegionProbeError
│       └── RegionProbeNetworkError
├── WorkspaceScopeError
├── BusinessContextValidationError
├── SessionReplayError (APIError)
└── ReportLinkError
    ├── ReportLinkParseError
    ├── UnsupportedReportLinkError
    ├── ReportLinkNotFoundError
    ├── ReportLinkScopeMismatchError
    └── ShortLinkResolutionError
```

## Catching Errors

```python
import mixpanel_headless as mp

try:
    ws = mp.Workspace()
    result = ws.segmentation(event="Purchase", from_date="2025-01-01", to_date="2025-01-31")
except mp.AuthenticationError as e:
    print(f"Auth failed: {e.message}")
except mp.RateLimitError as e:
    print(f"Rate limited, retry after {e.retry_after}s")
except mp.OAuthError as e:
    print(f"OAuth error [{e.code}]: {e.message}")
except mp.WorkspaceScopeError as e:
    print(f"Workspace error [{e.code}]: {e.message}")
except mp.AccountInUseError as e:
    print(f"Account '{e.account_name}' referenced by targets: {e.referenced_by}")
except mp.MixpanelHeadlessError as e:
    print(f"Error [{e.code}]: {e.message}")
```

## Base Exception

::: mixpanel_headless.MixpanelHeadlessError
    options:
      show_root_heading: true
      show_root_toc_entry: true

## API Exceptions

::: mixpanel_headless.APIError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.AuthenticationError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.RateLimitError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.QueryError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.ServerError
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Configuration Exceptions

::: mixpanel_headless.ConfigError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.AccountNotFoundError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.AccountExistsError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.AccountInUseError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.ProjectNotFoundError
    options:
      show_root_heading: true
      show_root_toc_entry: true

### InvalidArgumentError

Raised by `accounts.login_unified` (and the CLI's `mp login`) when a public-API call combines mutually incompatible arguments. Subclass of `ConfigError`. The CLI maps this to exit code 3 (`INVALID_ARGS`) instead of the generic 1.

| `violation` | Raised When |
|-------------|-------------|
| `mutually_exclusive` | `--service-account` + `--token-env` (or equivalent kwargs) |
| `no_browser_misuse` | `--no-browser` against a non-browser auth type |
| `secret_stdin_misuse` | `--secret-stdin` against a non-SA auth type |

The `details` dict carries `violation` and (when detection ran) `detected_auth_type`. Pattern-match by class so non-CLI callers (Cowork's `auth_manager.py`, JSON consumers) can dispatch without parsing the human message.

::: mixpanel_headless.InvalidArgumentError
    options:
      show_root_heading: true
      show_root_toc_entry: true

## OAuth Exceptions

Raised during OAuth 2.0 PKCE authentication flows and the `mp login` region probe.

| Error Code | Raised When |
|------------|-------------|
| `OAUTH_TOKEN_ERROR` | Token exchange fails |
| `OAUTH_REFRESH_ERROR` | Token refresh fails (transient) |
| `OAUTH_REFRESH_REVOKED` | Refresh token rejected by IdP as `invalid_grant` (re-run `mp login --name NAME`) |
| `OAUTH_REGISTRATION_ERROR` | Dynamic client registration fails |
| `OAUTH_TIMEOUT` | Callback server times out waiting for authorization |
| `OAUTH_PORT_ERROR` | Cannot bind to a local port for the callback server |
| `OAUTH_BROWSER_ERROR` | Cannot open the authorization URL in the browser |
| `OAUTH_REGION_PROBE_FAILED` | `mp login` probed every region and none accepted the credential — see `RegionProbeError` below |
| `OAUTH_NETWORK_UNREACHABLE` | Every region probe failed at the network layer (DNS / TLS / connect refused) — see `RegionProbeNetworkError` below |

::: mixpanel_headless.OAuthError
    options:
      show_root_heading: true
      show_root_toc_entry: true

### RegionProbeError

Raised by `mp login` (and `accounts.login_unified`) when the `us → eu → in` region probe fails for every region. Subclass of `OAuthError`. The `attempts` attribute carries the full `(region, status_code, error_body)` list; status `0` indicates a network-layer failure (DNS / TLS / connect refused) — those cases raise `RegionProbeNetworkError` (subclass) so the CLI can render a different remediation hint.

```python
import mixpanel_headless as mp

try:
    mp.accounts.login_unified()
except mp.RegionProbeNetworkError as exc:
    print("Could not reach any Mixpanel region. Check connectivity.")
    for region, status, body in exc.attempts:
        print(f"  {region}: {body}")
except mp.RegionProbeError as exc:
    print("Credential not valid in any region.")
    for region, status, body in exc.attempts:
        print(f"  {region}: {status} {body}")
```

::: mixpanel_headless.RegionProbeError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.RegionProbeNetworkError
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Workspace / Organization Scope Exceptions

Raised when an auth-axis identifier (workspace or organization) cannot be resolved during App API requests.

| Error Code | Raised When |
|------------|-------------|
| `NO_WORKSPACES` | No workspaces found for the project |
| `AMBIGUOUS_WORKSPACE` | Multiple workspaces found and none is marked as default |
| `WORKSPACE_NOT_FOUND` | Specified workspace ID does not exist |
| `ORGANIZATION_AMBIGUOUS` | An org-scoped business-context call could not auto-resolve the organization (active project absent from `/me` AND >1 accessible organization). `details` carries `project_id` and `available_organizations`. Pass `organization_id=N` explicitly to bypass auto-resolution. |

::: mixpanel_headless.WorkspaceScopeError
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Business Context Exceptions

Raised by `Workspace.set_business_context()` when content exceeds the 50,000-character cap. The check runs **before** the HTTP call, so callers fail fast and don't waste a round-trip; the server enforces the same limit and would otherwise return `QueryError` (HTTP 400). See the [Business Context guide](../guide/business-context.md) for usage.

| Error Code | Raised When |
|------------|-------------|
| `BUSINESS_CONTEXT_TOO_LONG` | `len(content) > BUSINESS_CONTEXT_MAX_CHARS` (50,000) |

The `details` dict carries `length` (the actual content length) and `max` (the configured limit) for programmatic recovery.

::: mixpanel_headless.BusinessContextValidationError
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Session Replay Exceptions

Raised by the session-replay surface (`fetch_replay()`, `sign_replay()`, `stream_replay()`). `SessionReplayError` is the base — catch it to handle any replay failure. See the [Session Replay guide](../guide/session-replay.md).

| Exception | Raised When |
|-----------|-------------|
| `SessionReplayAccessError` | The project has the `SESSION_RECORDING_SENSITIVE_DATA` flag set and the caller lacks the `sensitive_data_replay` permission (HTTP 403). `details` carries `project_id`, `flag`, and `permission_required`. |
| `SignedURLExpiredError` | A signed CDN URL expired mid-fetch (~5-minute TTL) and re-signing was disabled or also failed. |
| `ReplayNotFoundError` | The replay's first CDN file returned 404 — it aged out of its retention window, was never recorded, or was deleted. |

::: mixpanel_headless.SessionReplayError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.SessionReplayAccessError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.SignedURLExpiredError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.ReplayNotFoundError
    options:
      show_root_heading: true
      show_root_toc_entry: true

## Report Link Exceptions

Raised by the report-link surface (`create_report_link()`, `resolve_report_link()`, `query_report_link()`, `saved_report_link()`). `ReportLinkError` is the base — catch it to handle any link failure. Every instance carries the parsed link parts (`kind`, `region`, `project_id`, `workspace_id`, `slug`, `bookmark_id`, `short_code`, as available) plus a `hint` in `details`. See the [Report Links guide](../guide/report-links.md).

| Exception | Codes | Raised When |
|-----------|-------|-------------|
| `ReportLinkParseError` | `REPORT_LINK_UNPARSEABLE`, `REPORT_LINK_NOT_MIXPANEL_HOST`, `REPORT_LINK_UNRECOGNIZED_PATH`, `REPORT_LINK_UNRECOGNIZED_HASH`, `REPORT_LINK_EMPTY_HASH` | The string is not a recognizable Mixpanel report link. The parser is total: this is the only error it raises. |
| `UnsupportedReportLinkError` | `UNSUPPORTED_LEGACY_HASH`, `UNSUPPORTED_DASHBOARD_LINK`, `UNSUPPORTED_REPORT_TYPE` | A legacy `~(...)` hash, a board link, or a `launch-analysis` report passed to `query_report_link`. |
| `ReportLinkNotFoundError` | `REPORT_LINK_SLUG_NOT_FOUND`, `REPORT_LINK_BOOKMARK_NOT_FOUND`, `SHORT_LINK_NOT_FOUND` | The slug, saved report, or shortlink does not exist in the active project and region. CLI exit 4. |
| `ReportLinkScopeMismatchError` | `REPORT_LINK_PROJECT_MISMATCH`, `REPORT_LINK_REGION_MISMATCH`, `REPORT_LINK_WORKSPACE_MISMATCH` | The link names another project or region, or a workspace other than the pinned session workspace. The region check runs before any HTTP call; the project and workspace checks run before the record fetch (for a shortlink, after the one redirect GET). The message names both values; `details["hint"]` names the `ws.use(...)` call and the `mp --account` / `mp --project` / `mp --workspace` flag that fixes it. |
| `ShortLinkResolutionError` | `SHORT_LINK_NO_LOCATION`, `SHORT_LINK_UNEXPECTED_RESPONSE`, `SHORT_LINK_CHAIN` | The shortlink server answered in a shape headless cannot extract a target from, or the target is another shortlink. CLI exit 1. |

Builder and input guards raise `ParamValidationError`, not a `ReportLinkError`, with `RL1_UNKNOWN_REPORT_TYPE`, `RL2_INVALID_SLUG`, `RL3_UNKNOWN_REGION`, `RL4_REPORT_TYPE_CONFLICT`, or `RL5_RESOLVED_REPORT_INCONSISTENT` (a hand-built `ResolvedReport` whose `source` and id fields disagree). A shortlink that redirects to the login page raises the existing `AuthenticationError`; a 403 on the shortlink raises `QueryError`.

::: mixpanel_headless.ReportLinkError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.ReportLinkParseError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.UnsupportedReportLinkError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.ReportLinkNotFoundError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.ReportLinkScopeMismatchError
    options:
      show_root_heading: true
      show_root_toc_entry: true

::: mixpanel_headless.ShortLinkResolutionError
    options:
      show_root_heading: true
      show_root_toc_entry: true
