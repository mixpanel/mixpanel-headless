# Implementation Plan: Report Links

**Branch**: `045-report-links` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/045-report-links/spec.md`
**Source design**: [`context/report-links-plan.md`](../../context/report-links-plan.md). The source design holds the verified Mixpanel server behavior and the fine-grained file layout. This plan distills it into Spec Kit shape. Where the two differ, this plan wins.
**Linear**: AIE-561 (create links), AIE-562 (resolve links)
**PR strategy**: One PR. The feature is small enough to review as one unit. The pure URL module lands first inside that PR so reviewers can read it in isolation.

## Summary

Add report links to `mixpanel-headless`. A user turns a headless query into a shareable link to an unsaved Mixpanel report. A user also turns a report link, a bare slug, or a shortlink back into raw query parameters, and runs those parameters through the existing typed query engines.

The technical approach has four layers.

1. A pure, stdlib-only module `_internal/report_links.py` parses and builds Mixpanel report URLs and generates slugs. It makes no network calls and is fully property-testable.
2. Three new methods on `MixpanelAPIClient` call the `bookmark-urls` App API endpoints and follow one shortlink redirect.
3. Four new methods on `Workspace` compose the two layers with the existing parameter validation, bookmark reader, and `LiveQueryService`.
4. Two new CLI commands under `mp reports` and an opt-in `--link` flag on four `mp query` commands.

Resolve returns raw parameters plus a run method. A typed decompile into `Metric` and `Filter` objects is a separate follow-up feature.

Estimated scope: about 1,600 lines across 9 new files and 17 modified files, tests included.

## Technical Context

**Language/Version**: Python 3.10+ (mypy --strict compliant)

**Primary Dependencies**: All reused. `httpx` (HTTP), Pydantic v2 (the `BookmarkUrl` model), Typer and Rich (CLI), pandas (query results), Hypothesis (property tests), mutmut (mutation tests). The pure module imports only `re`, `secrets`, `dataclasses`, `typing`, and `urllib.parse`. No new third-party dependency.

**Storage**: None on the client. The Mixpanel server stores unsaved-report records per project and region. Headless persists nothing new to disk.

**Testing**: pytest for unit and integration tests. Hypothesis for the URL round trip, decoration invariance, parser totality, and slug alphabet invariants. `httpx.MockTransport` for the API client. A live test module gated on `MP_LIVE_TESTS=1`, the same gate as `tests/integration/test_replays_live.py`. mutmut on `_internal/report_links.py` with a target of 80 percent.

**Target Platform**: Cross-platform (macOS, Linux, Windows). No platform-specific paths.

**Project Type**: Library and CLI feature addition. The `mixpanel-plugin/` skills call `Workspace` and pick up the new methods. Two SKILL.md files gain a short snippet each.

**Performance Goals**:
- `create_report_link` makes exactly one App API POST. Workspace auto-resolution, when no workspace is pinned or passed, may add a lookup call before it (post-review correction).
- `resolve_report_link` makes at most two HTTP calls: one optional shortlink GET and one record GET.
- `saved_report_link` and `parse_report_link` make zero network calls and finish in under 1 millisecond.
- `query_report_link` on a `ResolvedReport` makes exactly one query call and no record fetch.

**Constraints**:
- mypy --strict, zero `Any` without justification.
- ruff format and ruff check pass with zero violations.
- Project coverage stays at or above 90 percent.
- Mutation score on `_internal/report_links.py` at or above 80 percent.
- The Authorization header never appears in a log line, an error message, or CLI output.
- A region mismatch fails before any HTTP call. Project and workspace mismatches fail before the record fetch; for a shortlink that is after the one redirect GET (post-review correction).
- The shortlink GET must not follow redirects, because `_handle_response` raises on 3xx.

**Scale/Scope**:
- New source: 1 module in `_internal/`, about 300 lines.
- Modified source: `exceptions.py`, `types.py`, `__init__.py`, `api_client.py`, `workspace.py`, `cli/commands/reports.py`, `cli/commands/query.py`, `cli/utils.py`.
- New tests: 7 files. New docs: 1 guide page.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Library-First | PASS | `mp reports link` and `mp reports resolve` delegate to `Workspace.create_report_link`, `resolve_report_link`, and `query_report_link`. The `--link` flags delegate to `create_report_link` and `saved_report_link`. The CLI does I/O and formatting only. Every new public symbol has type hints and a docstring. |
| II. Agent-Native | PASS | No prompts. Output is JSON, JSONL, table, CSV, or plain through the existing formatters. Warnings go to stderr. Exit codes follow the `ExitCode` enum: 1 for shortlink extraction failures, 2 for auth, 3 for parse, unsupported, and scope errors, 4 for not found, 5 for rate limit. |
| III. Context Window Efficiency | PASS | `ReportLink.to_dict()` is a handful of scalar fields. `ResolvedReport.to_dict()` returns the parameters once. `--format plain` prints the bare URL only. No raw HTML or redirect bodies reach stdout. |
| IV. Two Data Paths | PASS | The resolved parameters feed the live query engines directly. The typed results carry `.df`, so the local DuckDB path works unchanged. Both paths share the `Workspace` session. |
| V. Explicit Over Implicit | PASS | Link creation is an explicit call and an opt-in CLI flag that defaults to off. Validation is on by default and off only with `validate=False`. No silent cross-project fallback: a mismatch raises. Slug records are created, never overwritten. Overrides are surfaced as data, never merged. |
| VI. Unix Philosophy | PASS | `mp reports link ... -f plain` prints one URL for shell capture. `mp reports link` reads parameters from stdin. `mp reports resolve --jq .params` composes with jq. Shortlink creation is left to the browser, because the server requires a session there. |
| VII. Secure by Default | PASS | The shortlink GET sends the auth header through `_request_headers` and never logs it. `httpx` transport logs are not enabled by the library. No credential appears in `details` of any error. A login redirect maps to `AuthenticationError` with the redirect path only. |

**Gate Result**: PASS. No violations. No Complexity Tracking entries needed.

**Post-design re-check (after Phase 1)**: PASS. The contracts in `contracts/` add no interactive path, no new credential surface, and no implicit state change.

## Project Structure

### Documentation (this feature)

```text
specs/045-report-links/
├── plan.md                  # This file
├── spec.md                  # Feature specification
├── research.md              # Phase 0: decisions with rationale and alternatives
├── data-model.md            # Phase 1: entities, fields, validation, relationships
├── quickstart.md            # Phase 1: end-to-end validation guide
├── contracts/               # Phase 1
│   ├── python-api.md        # Workspace methods, client methods, types, exceptions
│   ├── cli-commands.md      # mp reports link / resolve, --link flags, exit codes
│   ├── url-grammar.md       # Parse table and build rules for the pure module
│   └── error-messages.md    # Stable message texts and codes
├── checklists/
│   └── requirements.md      # Spec quality checklist
└── tasks.md                 # Phase 2 output (/speckit-tasks, not created here)
```

### Source Code (repository root)

```text
src/mixpanel_headless/
├── __init__.py                          # MODIFIED: export the report-link group
├── exceptions.py                        # MODIFIED: ReportLinkError family + RL1..RL4 guard codes
├── types.py                             # MODIFIED: ReportLinkType, BookmarkUrl, ReportLink, ResolvedReport, ReportLinkQueryResult
├── workspace.py                         # MODIFIED: create_report_link, resolve_report_link, query_report_link, saved_report_link, _report_link_workspace_id
├── CLAUDE.md                            # MODIFIED: method table
├── _internal/
│   ├── report_links.py                  # NEW: pure parse/build/slug module
│   ├── api_client.py                    # MODIFIED: create_bookmark_url, get_bookmark_url, resolve_short_link
│   └── CLAUDE.md                        # MODIFIED: module table
└── cli/
    ├── utils.py                         # MODIFIED: handle_errors branches for the new family
    ├── CLAUDE.md                        # MODIFIED: exit-code table
    └── commands/
        ├── reports.py                   # MODIFIED: `link` and `resolve` commands
        ├── query.py                     # MODIFIED: --link on segmentation, funnel, saved-report, flows
        └── CLAUDE.md                    # MODIFIED: command table

tests/
├── unit/
│   ├── test_exceptions_report_links.py  # NEW
│   ├── test_report_links.py             # NEW: parametrized grammar table + builders
│   ├── test_report_links_pbt.py         # NEW: Hypothesis invariants
│   ├── test_api_client_bookmark_urls.py # NEW: MockTransport
│   └── test_workspace_report_links.py   # NEW: mocked client + mocked LiveQueryService
└── integration/
    ├── cli/test_report_link_commands.py # NEW: CliRunner
    └── test_report_links_live.py        # NEW: gated on MP_LIVE_TESTS=1

docs/
├── guide/report-links.md                # NEW
├── guide/live-analytics.md              # MODIFIED: cross-link
├── api/workspace.md                     # MODIFIED
├── api/exceptions.md                    # MODIFIED
└── cli/commands.md                      # MODIFIED

mkdocs.yml, README.md, CHANGELOG.md      # MODIFIED
mixpanel-plugin/skills/mixpanelyst/SKILL.md        # MODIFIED: "share a query as a link" snippet
mixpanel-plugin/skills/dashboard-expert/SKILL.md   # MODIFIED: one line
```

**Structure Decision**: Single project. The feature follows the existing layered layout: pure logic in `_internal/`, network in `api_client.py`, composition in `workspace.py`, I/O in `cli/`. No new package or service module is needed. The pure module lives beside `_internal/pagination.py` rather than under `_internal/query/`, because it is not a query builder.

## Design Decisions

The full list with rationale and alternatives is in [research.md](research.md). The short form:

1. **The slug URL app segment follows the Mixpanel MCP server.** Insights, Funnels, and Retention slugs link under `/app/insights#{slug}`. Flows slugs link under `/app/flows#{slug}`. One table, one line to change.
2. **Workspace ID precedence** for a created URL is explicit argument, then pinned session workspace, then `resolve_workspace_id()`. A `WorkspaceScopeError` falls back to a project-only URL.
3. **Validate before POST** with `_validate_bookmark_params_schema`. Severity `error` raises `BookmarkValidationError`, the same as `create_bookmark`.
4. **The parser is total.** It returns a `ParsedReportLink` for every recognizable Mixpanel URL. It raises `ReportLinkParseError` only for unrecognizable input. The resolver rejects unsupported kinds.
5. **Legacy JSURL hashes are detected, not decoded.**
6. **The shortlink GET bypasses `_execute_with_retry`** and uses `follow_redirects=False`.
7. **A region mismatch fails before any HTTP call; project and workspace mismatches fail before the record fetch** (for a shortlink, after the one redirect GET).
8. **`query_report_link` lives on `Workspace`.** Result dataclasses hold no workspace reference.
9. **Shortlink creation is out of scope.**
10. **Saved-report type mapping.** `SavedReportResult.report_type` yields `"funnel"`, but the URL table uses `"funnels"`. `saved_report_link` accepts both and normalizes.

## Implementation Order

Strict TDD. Each step is tests, then code, then `just check`. The `/speckit-tasks` command expands these into tasks.

| Phase | Step | Output |
|-------|------|--------|
| A | Exception tests, then the exception family and guard codes | `exceptions.py`, `test_exceptions_report_links.py` |
| A | Grammar table tests and PBT, then the pure module | `_internal/report_links.py`, `test_report_links.py`, `test_report_links_pbt.py` |
| B | Client tests with `MockTransport`, then types and the three client methods | `types.py`, `api_client.py`, `test_api_client_bookmark_urls.py` |
| C | Workspace tests with mocked client and service, then the four methods | `workspace.py`, `test_workspace_report_links.py` |
| D | CLI tests with `CliRunner`, then commands, `--link` flags, and `handle_errors` branches | `reports.py`, `query.py`, `cli/utils.py`, `test_report_link_commands.py` |
| E | Docs, CLAUDE.md tables, README, CHANGELOG, SKILL.md snippets, live test, mutation run | `docs/guide/report-links.md` and the modified files above |

## Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| The Insights app does not switch type from a Funnels or Retention slug record | Funnels and Retention links open as an empty Insights report | Live QA in Phase E. The fix is one line in `SLUG_APP_FOR_TYPE`, covered by the PBT round trip. |
| `bookmark-urls` rejects OAuth browser or static tokens | Link creation fails for two of three account types | The live test runs against each account type. Headless DCR clients request all scopes. |
| `build_flow_params()` output fails `FlowsBookmarkParams` validation | Flows link creation raises before POST | The live test creates a Flows link. `validate=False` is the documented escape hatch. |
| Legacy segmentation and Insights engines differ at edges | The `--link` on segmentation shows a slightly different result | The docstring and guide state that the link is an approximation of event, dates, unit, and breakdown. |
| Shortlink server changes its long-URL HTML shape | Extraction returns `SHORT_LINK_UNEXPECTED_RESPONSE` | The regex is narrow and tested. The error message tells the user to open the shortlink in a browser. |

## Complexity Tracking

No constitution violations. This section is intentionally empty.
