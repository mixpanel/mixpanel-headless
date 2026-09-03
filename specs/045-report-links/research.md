# Research: Report Links

**Feature**: 045-report-links | **Date**: 2026-09-02

This file records every design decision with its rationale and the alternatives considered. The Technical Context in `plan.md` had no `NEEDS CLARIFICATION` markers, because the source design in `context/report-links-plan.md` was verified against the Mixpanel `analytics` monorepo on 2026-09-02. The decisions below consolidate that verification and the codebase checks made during planning.

## R1. What the hash in an unsaved-report URL is

**Decision**: Treat the 12-character hash as a server-stored slug. Look it up with `GET /api/app/projects/{pid}/bookmark-urls/{slug}/`. Never try to decode it offline.

**Rationale**: The Mixpanel web app mints the slug client-side and stores the full bookmark params under it. The server regex is `^[a-zA-Z0-9_-]{12}$`. The alphabet is `123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz`. There is no encoding to reverse. Source: `webapp/app_api/projects/bookmark_urls/views.py` and `utils.py`.

**Alternatives considered**:
- Decode the hash locally. Rejected, because it is a random key, not an encoding.
- Decode the legacy `~(...)` JSURL hash. Rejected for v1. The frontend still accepts it, but a browser load re-mints a slug, which gives the user a free upgrade path.

## R2. How to create an unsaved report

**Decision**: `POST /api/app/projects/{pid}/bookmark-urls/` with body `{slug, type, params, name?, description?, bookmark_id?}`. Generate the slug client-side with `secrets.choice` over the Mixpanel alphabet. Never send `workspace_id`.

**Rationale**: This is exactly what the web app and the Mixpanel MCP server do. The server strips `workspace_id` from the body, so sending it is noise. `type` is one of `insights | funnels | retention | flows`. Auth is `@auth_required(["user_details"])`, which both service-account Basic auth and OAuth Bearer satisfy.

**Alternatives considered**:
- Create a real saved bookmark and link to it. Rejected, because it pollutes the saved-report list and the customer asked for unsaved links.
- Let the server mint the slug. Rejected, because the endpoint requires the slug in the body.

## R3. Which app segment a created URL uses

**Decision**: Follow the Mixpanel MCP server. `insights`, `funnels`, and `retention` link to `/app/insights#{slug}`. `flows` links to `/app/flows#{slug}`. Keep the mapping in one table, `SLUG_APP_FOR_TYPE`.

**Rationale**: `mixpanel_mcp/mcp_server/api/reports.py` does this on every `Run-Query` call and it works in production. The report editor reads `type` from the slug record.

**Alternatives considered**:
- One app per type (`/app/funnels#{slug}`). Kept as the fallback. If live QA shows the Insights app does not switch type, change the table. The PBT round trip covers the change.

**Open item for Phase E**: confirm in a browser that a Funnels slug under `/app/insights` opens as a funnel.

## R4. Workspace segment in a created URL

**Decision**: Order of precedence is the explicit `workspace_id` argument, then the pinned session workspace, then `Workspace.resolve_workspace_id()`. If resolution raises `WorkspaceScopeError`, emit a project-only URL and log at debug.

**Rationale**: The `/view/{wid}` segment is frontend routing only. The server ignores it. A project-only URL still opens, so a missing workspace must not fail link creation. `resolve_workspace_id()` already exists on `Workspace` and uses the cached `/me` data.

**Alternatives considered**:
- Always require a workspace. Rejected, because it fails for projects without data views.
- Never include a workspace. Rejected, because multi-workspace projects open the wrong view.

## R5. Parameter validation before POST

**Decision**: Call `Workspace._validate_bookmark_params_schema(params, report_type)`. If any returned `ValidationError` has severity `error`, raise `BookmarkValidationError(errors)`. Log warnings. `validate=False` skips the call.

**Rationale**: This is the exact path `create_bookmark` uses (checked at `workspace.py` around line 5300). The helper returns a list; the caller decides to raise. Reusing it keeps one schema for saved and unsaved reports.

**Alternatives considered**:
- No validation. Rejected, because a bad record produces a link that opens a broken editor with no client-side signal.

## R6. Parser totality and error surface

**Decision**: `parse_report_link` returns a `ParsedReportLink` for every recognizable Mixpanel URL, including dashboards and legacy JSURL hashes. It raises `ReportLinkParseError` only for input it cannot recognize, with one code per failure: `REPORT_LINK_UNPARSEABLE`, `REPORT_LINK_NOT_MIXPANEL_HOST`, `REPORT_LINK_UNRECOGNIZED_PATH`, `REPORT_LINK_UNRECOGNIZED_HASH`, `REPORT_LINK_EMPTY_HASH`. `resolve_report_link` rejects unsupported kinds with `UnsupportedReportLinkError`.

**Rationale**: A total parser is property-testable with `st.text()`. Separating "recognized but unsupported" from "not recognized" gives the user a specific hint in each case.

**Alternatives considered**:
- Parser raises on dashboards and legacy hashes. Rejected, because the parse result is useful data for the error message.

## R7. Shortlink resolution transport

**Decision**: `resolve_short_link` uses `self._ensure_client().get(url, headers=self._request_headers({"Authorization": self._get_auth_header()}), follow_redirects=False, timeout=DEFAULT_APP_TIMEOUT_S)`. It handles 3xx, 200 HTML, 401, 404, 429, and 5xx explicitly. It does not go through `_execute_with_retry` or `_handle_response`.

**Rationale**: `_handle_response` calls `raise_for_status()` for 3xx (checked at `api_client.py` line 714), so the redirect would become an error. The `/s/{code}` view is a plain Django view under `webapp/base/views.py::short`. Django middleware authenticates Basic and Bearer headers on it, so headless credentials work. For targets over 2048 characters the server returns 200 HTML with `window.location.href="<json-string>"`, so the client must handle both shapes. Unauthenticated requests get a 302 to `/login?next=...`, which must map to `AuthenticationError` and never be treated as the target.

**Alternatives considered**:
- `follow_redirects=True`. Rejected, because the client would then load the full web app HTML and lose the `Location` value.
- Reuse `_execute_with_retry` with a custom handler. Rejected, because the retry loop assumes JSON App API semantics.

## R8. Project and region scope checks

**Decision**: Before any HTTP call, compare the parsed region against `session.region` and the parsed project against `int(project.id)`. A mismatch raises `ReportLinkScopeMismatchError` with codes `REPORT_LINK_REGION_MISMATCH` or `REPORT_LINK_PROJECT_MISMATCH`. A bare slug skips both checks.

**Rationale**: The server returns 404 on a project mismatch, which looks like "slug not found" and is not actionable. Slugs are stored per region cluster, so a region mismatch also 404s. A local check gives the user the fix: `ws.use(project="3")` or `mp --project 3 ...`.

**Alternatives considered**:
- Auto-switch project. Rejected. The constitution forbids silent cross-axis fallback.

## R9. Where `query_report_link` lives

**Decision**: On `Workspace`. It accepts a `str` or a `ResolvedReport`. Dispatch on `report_type` to `LiveQueryService.query`, `query_funnel`, `query_retention`, or `query_flow` with `int(project.id)`.

**Rationale**: All four service methods take `(bookmark_params, project_id)` (checked at `live_query.py` lines 1126 to 1275). `query_flow` also takes `mode`. Result dataclasses in this project hold no workspace reference, so a `.run()` method on `ResolvedReport` would break the pattern set by `query_saved_report`.

**Flows mode derivation**: when `mode` is `None`, read `params["chartType"]`. If it is one of `sankey`, `paths`, or `tree`, use it. Else use `sankey`.

## R10. Saved-report link type mapping

**Decision**: `saved_report_link` accepts `BookmarkType` plus the singular `"funnel"`, and normalizes `"funnel"` to `"funnels"` before it looks up `BOOKMARK_HASH_FOR_TYPE`.

**Rationale**: `SavedReportResult.report_type` returns `SavedReportType = Literal["insights", "retention", "funnel", "flows"]` (checked at `types.py` line 249). The CLI `--link` on `mp query saved-report` passes that value through. Without normalization, every saved funnel link would raise `RL1_UNKNOWN_REPORT_TYPE`.

**Alternatives considered**:
- Change `SavedReportType` to `"funnels"`. Rejected, because it is a public type and a breaking change.

## R11. Exception family placement

**Decision**: `ReportLinkError(MixpanelHeadlessError)` is the base. Subclasses: `ReportLinkParseError`, `UnsupportedReportLinkError`, `ReportLinkNotFoundError`, `ReportLinkScopeMismatchError`, `ShortLinkResolutionError`. The four builder guard codes `RL1_UNKNOWN_REPORT_TYPE`, `RL2_INVALID_SLUG`, `RL3_UNKNOWN_REGION`, `RL4_REPORT_TYPE_CONFLICT` are raised as `ParamValidationError` and registered in `CODED_GUARD_REGISTRY`.

**Rationale**: The 044 session-replay family subclasses `APIError` because every failure there carries HTTP context. Report-link failures are mostly local (parse, scope, unsupported), so `MixpanelHeadlessError` is the right base. The `CODED_GUARD_REGISTRY` test enforces that every coded guard is registered.

**Alternatives considered**:
- Subclass `APIError`. Rejected for the reason above. `ReportLinkNotFoundError` wraps the HTTP 404 in `details` instead.

## R12. CLI exit-code mapping

**Decision**: In `handle_errors`, insert branches before the generic `except MixpanelHeadlessError`:
- `ReportLinkNotFoundError` exits `NOT_FOUND` (4).
- `ReportLinkParseError`, `UnsupportedReportLinkError`, `ReportLinkScopeMismatchError` exit `INVALID_ARGS` (3), and print `details["hint"]` when present.
- `ShortLinkResolutionError` exits `GENERAL_ERROR` (1).
- `AuthenticationError` from a login redirect already exits `AUTH_ERROR` (2).

**Rationale**: This matches the constitution's exit-code table and the 044 pattern of catching specific classes before the generic branch.

## R13. `--link` on `mp query segmentation`

**Decision**: Build Insights params with `ws.build_params(event, from_date=, to_date=, unit=, group_by=on)` and call `create_report_link`. Do this only when `--where` is absent and `--on` is a bare property name. Otherwise print a stderr warning and omit `report_url`. Any `MixpanelHeadlessError` from link creation prints a stderr warning and never fails the query.

**Rationale**: The legacy segmentation `--where` expression is a Mixpanel filter string that has no clean mapping to Insights filter params without the decompiler that is out of scope. The bare-property case covers the common breakdown. The query must never fail because of a convenience flag.

**Alternatives considered**:
- `--link` on `mp query retention`. Rejected. The legacy `--interval` and `--intervals` options do not map to Insights retention buckets.

## R14. Test patterns to copy

| Layer | Pattern file | What to copy |
|-------|--------------|--------------|
| Exceptions | `tests/unit/test_exceptions_session_replay.py` | hierarchy, default codes, `to_dict`, fixed message texts |
| API client | `tests/unit/test_api_client_bookmarks.py` | `httpx.MockTransport` handler, session fixture, `set_workspace_id` |
| Workspace | `tests/unit/test_workspace_bookmarks.py` | `_TEST_SESSION`, `MagicMock(spec=MixpanelAPIClient)`, patched `_live_query_service` |
| CLI | `tests/integration/cli/test_bookmark_commands.py` | `CliRunner`, `patch(".../reports.get_workspace")` |
| Live | `tests/integration/test_replays_live.py` | `pytest.mark.live` plus `skipif(MP_LIVE_TESTS != "1")` |
| PBT | `tests/conftest.py` profiles | `default`, `dev`, `ci` Hypothesis profiles |
