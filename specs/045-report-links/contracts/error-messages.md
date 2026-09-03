# Contract: Error Messages

**Feature**: 045-report-links
**Surface**: `ReportLinkError` family, builder guard codes, CLI stderr text
**Audience**: The implementer, the test author, and anyone who parses stderr

Messages below are stable. Tests assert on them. Placeholders in braces are filled at raise time. Every error's `details` dict carries the parsed link fields that are available (`kind`, `region`, `project_id`, `workspace_id`, `slug`, `bookmark_id`, `short_code`) plus `hint` when listed.

---

## 1. Parse errors (`ReportLinkParseError`, exit 3)

| Code | Message | Hint |
|------|---------|------|
| `REPORT_LINK_UNPARSEABLE` | `Could not parse report link: {raw!r}` | `Pass a full Mixpanel report URL, a shortlink (https://mixpanel.com/s/...), or a 12-character slug.` |
| `REPORT_LINK_NOT_MIXPANEL_HOST` | `Report link host {host!r} is not a Mixpanel web host.` | `Expected mixpanel.com, eu.mixpanel.com, or in.mixpanel.com.` |
| `REPORT_LINK_UNRECOGNIZED_PATH` | `Report link path {path!r} is not a report, dashboard, or shortlink path.` | `Expected /project/{{id}}/app/{{app}}#..., /project/{{id}}/view/{{wid}}/app/{{app}}#..., or /s/{{code}}.` |
| `REPORT_LINK_UNRECOGNIZED_HASH` | `Report link hash {hash!r} is not a slug, a saved report, or a dashboard reference.` | `Expected a 12-character slug, report/{{id}}, view/{{id}}, or id={{dashboard_id}}.` |
| `REPORT_LINK_EMPTY_HASH` | `Report link has no fragment after '#'. It points at the {app} app but not at a report.` | `Open the report in the browser and copy the full URL including the part after '#'.` |

## 2. Unsupported (`UnsupportedReportLinkError`, exit 3)

| Code | Message | Hint |
|------|---------|------|
| `UNSUPPORTED_LEGACY_HASH` | `This link uses the legacy JSURL hash format, which mixpanel-headless cannot decode.` | `Open it in a browser (the app re-mints a shareable link on load) and copy the new URL.` |
| `UNSUPPORTED_DASHBOARD_LINK` | `This link points at dashboard {dashboard_id}, not at a single report.` | `Use ws.get_dashboard({dashboard_id}) (CLI: mp dashboards get {dashboard_id}) to list its reports, then resolve one report link.` |
| `UNSUPPORTED_REPORT_TYPE` | `Report type {report_type!r} cannot be run through mixpanel-headless.` | `Supported types are insights, funnels, retention, and flows.` |

## 3. Not found (`ReportLinkNotFoundError`, exit 4)

| Code | Message |
|------|---------|
| `REPORT_LINK_SLUG_NOT_FOUND` | `No unsaved report found for slug {slug} in project {project_id} ({region}). A slug is only readable in the project and region that created it.` |
| `REPORT_LINK_BOOKMARK_NOT_FOUND` | `No saved report found with id {bookmark_id} in project {project_id} ({region}).` With a pinned session workspace the lookup is workspace-scoped, so the message ends ` under the pinned workspace {session_workspace_id}.` and `details["session_workspace_id"]` is set. |
| `SHORT_LINK_NOT_FOUND` | `Shortlink /s/{short_code} does not exist on {host}.` |

Each carries a `hint` in `details` (post-review): switch to the project / region / workspace that owns the record, or check the id. The CLI prints it on a `hint:` line.

## 4. Scope mismatch (`ReportLinkScopeMismatchError`, exit 3)

| Code | Message | Hint (`details["hint"]`) |
|------|---------|--------------------------|
| `REPORT_LINK_PROJECT_MISMATCH` | `Report link belongs to project {link_project_id} but the active session is project {session_project_id}.` | `Switch with ws.use(project="{link_project_id}") (CLI: mp --project {link_project_id} ...) and retry.` |
| `REPORT_LINK_REGION_MISMATCH` | `Report link is on the {link_region} region but the active account is on {session_region}.` | `Switch to an account on the {link_region} region with ws.use(account="<name>") (CLI: mp --account <name> ...) and retry.` |
| `REPORT_LINK_WORKSPACE_MISMATCH` | `Report link belongs to workspace {link_workspace_id} but the active session is pinned to workspace {session_workspace_id}.` Applies only when the session has a pinned workspace and the link (or `ResolvedReport`) names one. Added from PR #223 review. | `Switch with ws.use(workspace={link_workspace_id}) (CLI: mp --workspace {link_workspace_id} ...) and retry.` |

The message states the mismatch; the hint states the fix (split in the second PR #223 review round, so the CLI `hint:` line is not a repeat of the message). The region check fires before any HTTP call, for shortlinks too. The project and workspace checks fire before the record fetch; for a shortlink that is after the one redirect GET, because the target is not known before it.

## 5. Shortlink resolution (`ShortLinkResolutionError`, exit 1)

| Code | Message | Hint |
|------|---------|------|
| `SHORT_LINK_NO_LOCATION` | `Shortlink /s/{short_code} returned HTTP {status} without a Location header.` | `Open the shortlink in a browser and copy the full URL.` |
| `SHORT_LINK_UNEXPECTED_RESPONSE` | `Shortlink /s/{short_code} returned HTTP {status} with a body mixpanel-headless does not recognize.` | same |
| `SHORT_LINK_CHAIN` | `Shortlink /s/{short_code} redirects to another shortlink ({target}). mixpanel-headless follows one redirect only.` | `Resolve the target shortlink directly.` |

A redirect to `/login?next=...` does not use this class. It raises the existing `AuthenticationError` with message `Shortlink /s/{short_code} requires authentication; the server redirected to the login page.`

## 6. Builder guards (`ParamValidationError`, registered in `CODED_GUARD_REGISTRY`)

| Code | Message |
|------|---------|
| `RL1_UNKNOWN_REPORT_TYPE` | `Unknown report type {report_type!r}. Expected one of: {allowed}.` |
| `RL2_INVALID_SLUG` | `Invalid slug {slug!r}. A slug is exactly 12 characters from [0-9A-Za-z_-].` |
| `RL3_UNKNOWN_REGION` | `Unknown region {region!r}. Expected one of: us, eu, in.` |
| `RL4_REPORT_TYPE_CONFLICT` | `report_type={given!r} contradicts the {result_class} result, which is {inferred!r}. Omit report_type or pass a plain params dict.` |

## 7. CLI stderr warnings (exit 0)

| Situation | Text |
|-----------|------|
| `segmentation --link` with `--where` | `warning: --link is not supported with --where; link omitted` |
| `segmentation --link` with a non-bare `--on` | `warning: --link supports a bare property name for --on only; link omitted` |
| any `MixpanelHeadlessError` during `--link` creation | `warning: could not create report link: {message}` |
| bookmark link with an overrides tail | `warning: ignoring URL overrides {overrides_jsurl!r}; running the saved report's base params` |

## 8. Log lines

| Level | When | Text |
|-------|------|------|
| debug | `_report_link_workspace_id` falls back | `report link: no workspace resolved for project {pid}; emitting project-only URL` |
| warning | bookmark link with overrides tail | same text as the CLI warning above |

No log line at any level includes the Authorization header, the auth token, or the full request headers.
