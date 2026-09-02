# Tasks: Report Links

**Input**: Design documents from `/specs/045-report-links/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ (python-api.md, cli-commands.md, url-grammar.md, error-messages.md), quickstart.md

**Tests**: Included. The project enforces strict TDD (see `CLAUDE.md`). In every phase, write the test task first, confirm it fails, then do the implementation task. Run `just check` at the end of every phase.

**Organization**: Tasks are grouped by user story. User Story 5 (saved-report link helper) runs before User Story 4 (CLI `--link` flags), because US4 calls the helper. Both are P3.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on an incomplete task)
- **[Story]**: Which user story this task belongs to (US1 to US5)
- Every task names an exact file path

## Path Conventions

Single project. Source in `src/mixpanel_headless/`, tests in `tests/`, docs in `docs/`. All paths below are relative to the repository root.

---

## Phase 1: Setup

**Purpose**: Confirm a green baseline on the feature branch. No new files.

- [X] T001 Confirm branch `045-report-links` is checked out and `just check` passes with no changes, so every later failure is attributable to this feature
- [X] T002 [P] Read the four pattern test files named in research.md R14 (`tests/unit/test_exceptions_session_replay.py`, `tests/unit/test_api_client_bookmarks.py`, `tests/unit/test_workspace_bookmarks.py`, `tests/integration/cli/test_bookmark_commands.py`) and note the fixture and mock conventions to copy

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The exception family, the pure URL module, the public types, the exports, and the CLI exit-code branches. Every user story depends on these.

**⚠️ CRITICAL**: No user story work can begin until this phase is complete.

### Exceptions

- [X] T003 Write `tests/unit/test_exceptions_report_links.py`: hierarchy (`ReportLinkError` subclasses `MixpanelHeadlessError`; the five subclasses subclass `ReportLinkError`), default codes per data-model.md §7, `to_dict()` shape, `details` carries parsed fields and `hint`, the fixed message texts in contracts/error-messages.md §1 to §6, and that `RL1_UNKNOWN_REPORT_TYPE`, `RL2_INVALID_SLUG`, `RL3_UNKNOWN_REGION`, `RL4_REPORT_TYPE_CONFLICT` are in `CODED_GUARD_REGISTRY`
- [X] T004 Add `ReportLinkError`, `ReportLinkParseError`, `UnsupportedReportLinkError`, `ReportLinkNotFoundError`, `ReportLinkScopeMismatchError`, `ShortLinkResolutionError` to `src/mixpanel_headless/exceptions.py` after the 044 session-replay block, with `_DEFAULT_CODE` values from data-model.md §7 and full docstrings; add the four `RL*` codes to `CODED_GUARD_REGISTRY`

### Pure URL module

- [X] T005 [P] Write `tests/unit/test_report_links.py`: one parametrized case per row of contracts/url-grammar.md §5 (parse table) and §6 (builders), plus `is_slug` positive and negative cases, `web_host` for the three regions and an unknown region, and `generate_slug` with an injected deterministic `choice`
- [X] T006 [P] Write `tests/unit/test_report_links_pbt.py` with Hypothesis: the seven invariants in contracts/url-grammar.md §7 (slug alphabet and length, slug-URL round trip over regions, project ids, optional workspace ids, slugs, and four types; bookmark-URL round trip over five types; decoration invariance; totality over `st.text()`; id fields set per kind; non-slug strings). Use the profiles registered in `tests/conftest.py`
- [X] T007 Implement `src/mixpanel_headless/_internal/report_links.py`: constants from data-model.md §8, `ParsedReportLink` frozen dataclass, `web_host`, `is_slug`, `generate_slug`, `parse_report_link` per contracts/url-grammar.md §1 to §4, `build_slug_url`, `build_bookmark_url`. Stdlib only. Full docstrings. Builders raise `ParamValidationError` with the `RL1` to `RL3` codes

### Public types and exports

- [X] T008 [P] Write type tests in `tests/unit/test_types_report_links.py`: `BookmarkUrl` parses a server record with `type` alias and an embedded `bookmark`; `ReportLink.to_dict()` and `__str__`; `ResolvedReport.to_dict()` serializes `bookmark` with `model_dump(mode="json", by_alias=True)` and passes `None` through; frozen dataclasses reject assignment
- [X] T009 Add `ReportLinkType`, `BookmarkUrl`, `ReportLink`, `ResolvedReport`, `ReportLinkQueryResult` to `src/mixpanel_headless/types.py` per data-model.md §2 to §6, with full docstrings
- [X] T010 Export the five types and the six exception classes from `src/mixpanel_headless/__init__.py` under a `# Report links (AIE-561/562)` comment group; add them to `__all__`

### CLI error mapping

- [X] T011 [P] Add exit-code tests to `tests/integration/cli/test_report_link_commands.py` (create the file): a command decorated with `handle_errors` that raises each of `ReportLinkNotFoundError` (exit 4), `ReportLinkParseError` (exit 3, prints `hint`), `UnsupportedReportLinkError` (3), `ReportLinkScopeMismatchError` (3), `ShortLinkResolutionError` (1), and `BookmarkValidationError` (exit 3, one line per error). Use the fixture style of `tests/integration/cli/test_bookmark_commands.py`
- [X] T012 Add six `except` branches to `handle_errors` in `src/mixpanel_headless/cli/utils.py` before the generic `except MixpanelHeadlessError`, per contracts/cli-commands.md §4: the five report-link classes, plus `BookmarkValidationError` exiting 3 with one line per validation error; print `error: {message}` and `hint: {details["hint"]}` when present
- [X] T013 Run `just check`. Fix any lint, format, mypy, or coverage failure in the Phase 2 files

**Checkpoint**: The pure module, types, exceptions, and exit codes are done. Stories can start.

---

## Phase 3: User Story 1 - Share a headless query as a report link (Priority: P1) 🎯 MVP

**Goal**: `ws.create_report_link(params_or_result)` stores an unsaved report and returns a `ReportLink` whose URL opens the same query in the browser. `mp reports link` exposes it.

**Independent Test**: Build params with `ws.build_params("Login", last=7)`, create a link, open the URL in a browser. The Insights editor shows `Login` over 7 days.

### Tests for User Story 1

- [X] T014 [P] [US1] Write `tests/unit/test_api_client_bookmark_urls.py` (create the file) with `httpx.MockTransport`, copying the fixture in `tests/unit/test_api_client_bookmarks.py`: `create_bookmark_url` POSTs to `/api/app/projects/{pid}/bookmark-urls/`, the body contains `slug`, `type`, `params` and optional `name`, `description`, `bookmark_id`, the body never contains `workspace_id`, the path stays project-scoped after `set_workspace_id(789)`, the `results` envelope is unwrapped, and a non-dict result raises
- [X] T015 [P] [US1] Write `tests/unit/test_workspace_report_links.py` (create the file) using `_TEST_SESSION` and `MagicMock(spec=MixpanelAPIClient)` from `tests/unit/test_workspace_bookmarks.py`: create from a dict defaults to `insights`; create from each of `QueryResult`, `FunnelQueryResult`, `RetentionQueryResult`, `FlowQueryResult` infers the type; a contradicting `report_type` raises `RL4_REPORT_TYPE_CONFLICT` with `create_bookmark_url.assert_not_called()`; validation failure raises `BookmarkValidationError` before POST; `validate=False` skips validation; workspace precedence (explicit, pinned, `resolve_workspace_id`, `WorkspaceScopeError` falls back to `None`); URL shape per type and region; `created_at` copied from the response; `name` and `description` forwarded

### Implementation for User Story 1

- [X] T016 [US1] Add `create_bookmark_url(body)` to `src/mixpanel_headless/_internal/api_client.py` per contracts/python-api.md §2, next to `get_bookmark`; full docstring
- [X] T017 [US1] Add `_report_link_workspace_id(explicit)` and `create_report_link(...)` to `src/mixpanel_headless/workspace.py` per contracts/python-api.md §1, reusing `_validate_bookmark_params_schema` the same way `create_bookmark` does; import the pure module builders; full docstrings with a markdown-fenced example
- [X] T018 [US1] Add CLI tests to `tests/integration/cli/test_report_link_commands.py` with `patch("mixpanel_headless.cli.commands.reports.get_workspace", return_value=mock_workspace)`: `mp reports link --params JSON` prints `ReportLink.to_dict()`; `--params-file`; stdin with `-`; stdin when not a TTY and no option; `-f plain` prints only the URL; `--type`, `--name`, `--description`, `--workspace-id`, `--bookmark-id`, `--no-validate` reach `create_report_link`; invalid JSON exits 3; both `--params` and `--params-file` exits 3
- [X] T019 [US1] Implement the `link` command in `src/mixpanel_headless/cli/commands/reports.py` per contracts/cli-commands.md §1, reusing `validate_json_object` from `src/mixpanel_headless/cli/validators.py` and `output_result` from `src/mixpanel_headless/cli/utils.py`; `--help` includes an example
- [X] T020 [US1] Run `just check`. Fix failures in the US1 files

**Checkpoint**: Link creation works from Python and the CLI. This is the MVP.

---

## Phase 4: User Story 2 - Resolve a report link to its query and run it (Priority: P1)

**Goal**: `ws.resolve_report_link(link)` turns a full URL, a bare slug, or a saved-report URL into a `ResolvedReport`. `ws.query_report_link(link_or_resolved)` runs it. `mp reports resolve [--run]` exposes both. Shortlinks are User Story 3.

**Independent Test**: Create a link with US1. Resolve it. `resolved.params` equals the input params and `resolved.report_type` is `insights`. Run it. The result is a `QueryResult`.

### Tests for User Story 2

- [X] T021 [P] [US2] Add to `tests/unit/test_api_client_bookmark_urls.py`: `get_bookmark_url(slug)` GETs `/api/app/projects/{pid}/bookmark-urls/{slug}/`, stays project-scoped after `set_workspace_id(789)`, returns the unwrapped dict, and maps a 404 `QueryError` to `ReportLinkNotFoundError` with code `REPORT_LINK_SLUG_NOT_FOUND` and the slug in `details`; a 500 passes through as `ServerError`
- [X] T022 [P] [US2] Add to `tests/unit/test_workspace_report_links.py`, patching `_live_query_service` with `MagicMock(spec=LiveQueryService)`: resolve a bare slug; resolve a full URL with `wid`; resolve a project-only URL uses the pinned workspace, else `None`; resolve a slug record with an embedded `bookmark`; resolve a bookmark URL takes `report_type` from `Bookmark.bookmark_type` not the URL hint; a bookmark URL with `overrides_jsurl` logs a warning and returns base params; project mismatch raises `REPORT_LINK_PROJECT_MISMATCH` with no client call; region mismatch raises `REPORT_LINK_REGION_MISMATCH` with no client call; dashboard raises `UNSUPPORTED_DASHBOARD_LINK`; legacy hash raises `UNSUPPORTED_LEGACY_HASH`; unknown slug raises `ReportLinkNotFoundError`; unknown bookmark raises `ReportLinkNotFoundError(REPORT_LINK_BOOKMARK_NOT_FOUND)`; `url` is the canonical rebuilt URL; `input` is the raw string
- [X] T023 [P] [US2] Add to `tests/unit/test_workspace_report_links.py`: `query_report_link` dispatches `insights` to `query`, `funnels` to `query_funnel`, `retention` to `query_retention`, `flows` to `query_flow`, each with `int(project.id)`; flows `mode` derives from `params["chartType"]` when valid, else `sankey`, and an explicit `mode` wins; `launch-analysis` raises `UNSUPPORTED_REPORT_TYPE`; a `ResolvedReport` input causes no `get_bookmark_url` or `get_bookmark` call; a `str` input resolves first

### Implementation for User Story 2

- [X] T024 [US2] Add `get_bookmark_url(slug)` to `src/mixpanel_headless/_internal/api_client.py` per contracts/python-api.md §2, with the 404 mapping; full docstring
- [X] T025 [US2] Add `resolve_report_link(link)` to `src/mixpanel_headless/workspace.py` per contracts/python-api.md §1 steps 1 and 3 to 8, including the step-6 mapping of a 404 `QueryError` from `get_bookmark` to `ReportLinkNotFoundError(REPORT_LINK_BOOKMARK_NOT_FOUND)` (leave a clear `short_link` branch that raises `UnsupportedReportLinkError` for now; US3 replaces it); messages from contracts/error-messages.md §2 to §4; full docstring
- [X] T026 [US2] Add `query_report_link(link, *, mode=None)` to `src/mixpanel_headless/workspace.py` per contracts/python-api.md §1; full docstring with an example
- [X] T027 [US2] Add CLI tests to `tests/integration/cli/test_report_link_commands.py`: `mp reports resolve LINK` prints `ResolvedReport.to_dict()`; `--jq .params` works; `--run` calls `query_report_link` and prints through `present_result`; `--run --mode paths` forwards `mode`; a `ReportLinkScopeMismatchError` from the workspace exits 3 with both project ids in stderr; a `ReportLinkNotFoundError` exits 4; an `UnsupportedReportLinkError` for a legacy hash exits 3 with the browser hint
- [X] T028 [US2] Implement the `resolve` command in `src/mixpanel_headless/cli/commands/reports.py` per contracts/cli-commands.md §2; `--help` includes an example that quotes the URL because of `#`
- [X] T029 [US2] Run `just check`. Fix failures in the US2 files

**Checkpoint**: Both P1 stories work. A link created by US1 round-trips through US2.

---

## Phase 5: User Story 3 - Resolve a shortlink (Priority: P2)

**Goal**: `resolve_report_link("https://mixpanel.com/s/{code}")` follows one redirect with headless credentials and then resolves the target.

**Independent Test**: With a mocked transport, a 302 to a full report URL yields the same `ResolvedReport` as resolving that URL directly, with `expanded_url` set.

### Tests for User Story 3

- [X] T030 [P] [US3] Add to `tests/unit/test_api_client_bookmark_urls.py` for `resolve_short_link(code)`: the handler sees exactly one request to `https://mixpanel.com/s/{code}` (redirects are not followed); the request carries an `Authorization` header; 302 with an absolute `Location` returns it; a relative `Location` is joined against the request URL; 302 to `/login?next=...` raises `AuthenticationError`; 200 HTML with `window.location.href="<json-escaped url>"` returns the decoded URL; 200 without the script raises `SHORT_LINK_UNEXPECTED_RESPONSE`; 3xx without `Location` raises `SHORT_LINK_NO_LOCATION`; 401 raises `AuthenticationError`; 404 raises `ReportLinkNotFoundError(SHORT_LINK_NOT_FOUND)`; 429 raises `RateLimitError`; 503 raises `ServerError`; `httpx.ConnectError` raises `MixpanelHeadlessError` with code `HTTP_ERROR`; the EU session hits `eu.mixpanel.com`; no log record at any level contains the Authorization value (use `caplog`)
- [X] T031 [P] [US3] Add to `tests/unit/test_workspace_report_links.py`: a shortlink resolves to the same `ResolvedReport` as its target plus `expanded_url` and `input`; a shortlink whose target is another shortlink raises `SHORT_LINK_CHAIN`; a shortlink whose target is a dashboard raises `UNSUPPORTED_DASHBOARD_LINK`; a shortlink target in another project raises `REPORT_LINK_PROJECT_MISMATCH` before any record fetch

### Implementation for User Story 3

- [X] T032 [US3] Add `resolve_short_link(code)` to `src/mixpanel_headless/_internal/api_client.py` per contracts/python-api.md §2 and research.md R7: `_ensure_client().get(..., follow_redirects=False, timeout=DEFAULT_APP_TIMEOUT_S)`, explicit handling of every response row; full docstring
- [X] T033 [US3] Replace the placeholder `short_link` branch in `resolve_report_link` in `src/mixpanel_headless/workspace.py` with the real flow (contracts/python-api.md §1 step 2): call `resolve_short_link`, re-parse, raise `SHORT_LINK_CHAIN` on a second shortlink, keep `expanded_url`
- [X] T034 [US3] Add CLI tests to `tests/integration/cli/test_report_link_commands.py`: `mp reports resolve 'https://mixpanel.com/s/AbC'` prints the resolved report with `expanded_url`; an `AuthenticationError` from a login redirect exits 2; a `ShortLinkResolutionError` exits 1
- [X] T035 [US3] Run `just check`. Fix failures in the US3 files

**Checkpoint**: Shortlinks resolve. All network paths for resolution are covered.

---

## Phase 6: User Story 5 - Build a link to a saved report without a network call (Priority: P3)

**Goal**: `ws.saved_report_link(bookmark_id, report_type=..., workspace_id=...)` returns the web URL for a saved report. Pure. US4 depends on it.

**Independent Test**: `ws.saved_report_link(123, report_type="funnels")` returns `https://mixpanel.com/project/{pid}/app/funnels#view/123` for a US session with no pinned workspace.

### Tests for User Story 5

- [X] T036 [P] [US5] Add to `tests/unit/test_workspace_report_links.py`: URL shape for each of the five `BookmarkType` values; the singular `"funnel"` normalizes to `"funnels"`; workspace precedence is explicit, then pinned, then omitted; `resolve_workspace_id` is never called (assert on a mock); an EU session uses `eu.mixpanel.com`; an unknown type raises `RL1_UNKNOWN_REPORT_TYPE`; the client mock records zero calls

### Implementation for User Story 5

- [X] T037 [US5] Add `saved_report_link(...)` to `src/mixpanel_headless/workspace.py` per contracts/python-api.md §1 and research.md R10; full docstring
- [X] T038 [US5] Run `just check`. Fix failures in the US5 files

**Checkpoint**: The pure helper is done.

---

## Phase 7: User Story 4 - Add a link to existing CLI query output (Priority: P3)

**Goal**: An opt-in `--link` flag on `mp query segmentation`, `funnel`, `saved-report`, and `flows` adds `report_url` to the output. The flag never fails the query.

**Independent Test**: `mp query saved-report 123 --link --jq .report_url` prints a URL that opens that saved report. `mp query segmentation -e Login --from D --to D` output is unchanged without `--link`.

### Tests for User Story 4

- [X] T039 [P] [US4] Add CLI tests to `tests/integration/cli/test_report_link_commands.py` with `patch("mixpanel_headless.cli.commands.query.get_workspace", ...)`: `query segmentation --link` calls `build_params(event, from_date=, to_date=, unit=, group_by=on)` and `create_report_link`, and the output has `report_url`; with `--where` it prints the stderr warning from contracts/error-messages.md §7 and omits `report_url`, exit 0; with a non-bare `--on` such as `defined(properties["x"])` it warns and omits; `--on 'Plan Type'` and `--on '$city'` are bare and produce a link; when `create_report_link` raises `MixpanelHeadlessError` it warns and still prints the result, exit 0; without `--link` the output dict has no `report_url` key
- [X] T040 [P] [US4] Add CLI tests to `tests/integration/cli/test_report_link_commands.py`: `query funnel 456 --link` adds `report_url` from `saved_report_link(456, report_type="funnels")`; `query saved-report 123 --link` passes `result.report_type` (including `"funnel"`) through; `query flows 8 --link` uses `report_type="flows"`; none of the three calls `create_report_link`

### Implementation for User Story 4

- [X] T041 [US4] Add the `--link` option to `query_segmentation` in `src/mixpanel_headless/cli/commands/query.py` per contracts/cli-commands.md §3: bare-`--on` detection per the token list in contracts/cli-commands.md §3 (keep the list as one module-level tuple so the test in T039 can import it), the two warnings, the `MixpanelHeadlessError` guard, and `report_url` insertion; `--help` states the approximation
- [X] T042 [US4] Add the `--link` option to `query_funnel`, `query_saved_report`, and `query_flows` in `src/mixpanel_headless/cli/commands/query.py`, each calling `ws.saved_report_link(...)` and adding `report_url`
- [X] T043 [US4] Run `just check`. Fix failures in the US4 files

**Checkpoint**: All five user stories work independently.

---

## Phase 8: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, agent context files, release notes, live verification, and quality gates.

### Documentation

- [X] T044 [P] Write `docs/guide/report-links.md`: what a slug is, create from a result and from params, resolve a URL, a slug, and a shortlink, run a resolved report, the `--link` flags, the scope-mismatch fix, the legacy-hash hint, the segmentation approximation, and the Out of Scope list from spec.md
- [X] T045 [P] Add the guide to `mkdocs.yml` in the three places `guide/session-replay.md` appears (nav, the two description lists); add a cross-link paragraph to `docs/guide/live-analytics.md`
- [X] T046 [P] Document the four `Workspace` methods in `docs/api/workspace.md` and the exception family in `docs/api/exceptions.md`
- [X] T047 [P] Document `mp reports link`, `mp reports resolve`, and the four `--link` flags in `docs/cli/commands.md` (inspect its flat layout first)
- [X] T048 [P] Add a feature bullet and the two new `mp reports` verbs to `README.md`; add a `## Unreleased` section to `CHANGELOG.md` above `## 0.2.2` that names the new methods, commands, types, and exceptions

### Agent context files

- [X] T049 [P] Add the four `Workspace` methods to the method table in `src/mixpanel_headless/CLAUDE.md`
- [X] T050 [P] Add `report_links.py` to the module table in `src/mixpanel_headless/_internal/CLAUDE.md`
- [X] T051 [P] Add the new exceptions to the exit-code table in `src/mixpanel_headless/cli/CLAUDE.md` and the two commands plus `--link` flags to `src/mixpanel_headless/cli/commands/CLAUDE.md`
- [X] T052 [P] Add a "share a query as a link" snippet to `mixpanel-plugin/skills/mixpanelyst/SKILL.md` and one line about resolving a report link to `mixpanel-plugin/skills/dashboard-expert/SKILL.md`

### Live verification and quality gates

- [X] T053 Write `tests/integration/test_report_links_live.py`, gated like `tests/integration/test_replays_live.py` (`pytest.mark.live` plus `skipif(MP_LIVE_TESTS != "1")`): the seven cases in quickstart.md Part 2, with the shortlink case gated on `MP_TEST_SHORT_LINK`
- [X] T054 Run quickstart.md Part 2 with `MP_LIVE_TESTS=1` against a service-account account and against one OAuth account type; record the results in the PR description — done 2026-09-02 against the `oauth_browser` account `mixpanel-3` (project 1297132): 6 passed, 1 skipped (no `MP_TEST_SHORT_LINK`). No service-account account is configured on this machine, so the SA run is still open.
- [X] T055 Run quickstart.md Part 3 in a browser for all four report types. If a Funnels or Retention slug opens as an empty Insights report, change `SLUG_APP_FOR_TYPE` in `src/mixpanel_headless/_internal/report_links.py` to one app per type, update the builder rows in `tests/unit/test_report_links.py`, and rerun `just test -k report_links` — browser check done 2026-09-02: all four slug types open as the correct report type under the MCP app mapping, so `SLUG_APP_FOR_TYPE` stays as is. The saved-report link opened the right report; its "no data" banner comes from the report's own query (headless returns zero series for it too).
- [X] T056 Run `uv run mutmut run --paths-to-mutate src/mixpanel_headless/_internal/report_links.py` and `just mutate-results`; add tests until the score is at or above 80 percent — mutmut 3.5 takes a mutant-name prefix, not `--paths-to-mutate`: `PYTEST_ADDOPTS="-k 'report_link or bookmark_url' -p no:cacheprovider" uv run mutmut run "mixpanel_headless._internal.report_links*"`. Result 2026-09-02: first run 83.4 percent (371 killed, 74 survived, 18 timeouts); after survivor-targeted tests 93.3 percent (432 killed, 31 survived, 0 timeouts)
- [X] T057 Run quickstart.md Part 4 (credential grep) and confirm no Authorization text in any output or log — grep exit 1 (zero hits) on the live run output
- [X] T058 Run `just check` one final time. Confirm coverage is at or above 90 percent — passed 2026-09-02; total coverage 92 percent

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies.
- **Foundational (Phase 2)**: Depends on Phase 1. Blocks every user story.
- **US1 (Phase 3)**: Depends on Phase 2. No dependency on other stories.
- **US2 (Phase 4)**: Depends on Phase 2. Independently testable with mocks. The live round trip uses a US1 link.
- **US3 (Phase 5)**: Depends on Phase 2 and on US2, because a shortlink resolves into the US2 flow.
- **US5 (Phase 6)**: Depends on Phase 2 only.
- **US4 (Phase 7)**: Depends on Phase 2, US1 (`create_report_link` for segmentation), and US5 (`saved_report_link`).
- **Polish (Phase 8)**: Depends on every story the team chose to ship.

### Within Each User Story

- Test tasks come first and must fail before the implementation task starts.
- Client method, then `Workspace` method, then CLI command.
- `just check` closes every phase.

### Shared-file constraints

These files are touched in more than one phase, so tasks on them are sequential, never `[P]` across phases:

- `src/mixpanel_headless/workspace.py`: T017, T025, T026, T033, T037
- `src/mixpanel_headless/_internal/api_client.py`: T016, T024, T032
- `src/mixpanel_headless/cli/commands/reports.py`: T019, T028
- `tests/unit/test_workspace_report_links.py`: T015, T022, T023, T031, T036
- `tests/unit/test_api_client_bookmark_urls.py`: T014, T021, T030
- `tests/integration/cli/test_report_link_commands.py`: T011, T018, T027, T034, T039, T040

### Parallel Opportunities

- Phase 2: T005, T006, T008, T011 are independent test files and can be written together. T003 must precede T004. T007 needs T004 (it raises `ParamValidationError` with registered codes) and T005/T006.
- Phase 3: T014 and T015 in parallel. Then T016, T017, T018, T019 in order.
- Phase 4: T021, T022, T023 in parallel. Then T024 to T028 in order.
- Phase 5: T030 and T031 in parallel. Then T032 to T034 in order.
- Phase 6 and Phase 3 can run in parallel after Phase 2, because US5 touches only `workspace.py` and its test file. Coordinate the `workspace.py` merge.
- Phase 8: T044 to T052 are all independent files and can run together.

---

## Parallel Example: Phase 2

```bash
# Write the four independent test files together:
Task: "Write tests/unit/test_report_links.py (grammar table + builders)"
Task: "Write tests/unit/test_report_links_pbt.py (seven invariants)"
Task: "Write tests/unit/test_types_report_links.py"
Task: "Add exit-code tests to tests/integration/cli/test_report_link_commands.py"
```

## Parallel Example: User Story 1

```bash
# Write both test files together:
Task: "Write tests/unit/test_api_client_bookmark_urls.py (create_bookmark_url)"
Task: "Write tests/unit/test_workspace_report_links.py (create_report_link)"

# Then implement in order:
Task: "Add create_bookmark_url to src/mixpanel_headless/_internal/api_client.py"
Task: "Add create_report_link to src/mixpanel_headless/workspace.py"
Task: "Implement mp reports link in src/mixpanel_headless/cli/commands/reports.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1 and Phase 2.
2. Complete Phase 3 (US1).
3. **STOP and VALIDATE**: create a link from Python, open it in a browser, confirm the query. This alone closes AIE-561.

### Incremental Delivery

1. Phase 2 done: the pure parser is unit-tested and the exceptions exist.
2. Add US1: link creation. Demo. Closes AIE-561.
3. Add US2: resolve and run. Demo. Closes AIE-562 for full URLs and slugs.
4. Add US3: shortlinks. Demo.
5. Add US5 then US4: saved-report links and the `--link` flags.
6. Phase 8: docs, live checks, mutation score, release notes.

### Single PR

The plan ships one PR. Commit at every checkpoint so the review can follow the phases. The pure module commit should be reviewable in isolation.

---

## Notes

- Every task names its file. Every user-story task carries its `[USn]` label.
- `[P]` tasks touch different files and depend on no incomplete task.
- Confirm each test fails before you write the implementation.
- Every new class, method, and function needs a full docstring, including private helpers and test functions.
- Never suppress stderr when you run `mp` commands during verification.
