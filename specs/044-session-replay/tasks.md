---
description: "Task list for 044-session-replay — phased rollout across 3 PRs (P1 → P2 → P3 of the source design)"
---

# Tasks: Session Replay for `mixpanel-headless`

**Input**: Design documents from `/specs/044-session-replay/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: REQUIRED. The project CLAUDE.md mandates strict TDD ("write tests FIRST, before any implementation code"), 90% coverage minimum, and ≥80% mutation score on the new pure modules (`_internal/services/replays.py`, `_internal/replays/rrweb_analyzer.py`, `_internal/replays/labels.py`, `_internal/replays/aggregators.py`). Test tasks land before their corresponding implementation tasks within each phase.

**Organization**: Tasks are grouped by user story. The plan ships three independent PRs:

| PR | Source-plan phase | User stories shipped | Task ranges |
|----|-------------------|----------------------|-------------|
| PR 1 | Phase 1 | US1 (discovery + fetch) + US3 basic CLI (list/events/sign/fetch) | T001–T042, T080–T088 |
| PR 2 | Phase 2 | US2 (analyzer + bundle) + US3 analyze/for-user CLI | T043–T079, T089–T093 |
| PR 3 | Phase 3 | US4 (pm4py + tslearn extras) | T094–T108 |

Each PR is independently shippable and adds caller-visible value. US3 (CLI) straddles PR 1 and PR 2 because the CLI commands `analyze` and `for-user` depend on the analyzer that ships in PR 2.

**Story dependency note**:
- US1 depends only on Foundational.
- US2 depends on US1 (analyzer needs the raw rrweb event stream; `ReplayBundle` is a collection of `Replay` objects from US1).
- US3's basic commands (list/events/sign/fetch) depend on US1. US3's analyze/for-user commands depend on US2.
- US4 depends on US2 (`event_log()` and `cluster()` operate on the bundle).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story this task belongs to (US1 / US2 / US3 / US4) — omitted for Setup, Foundational, and Polish phases
- All file paths are project-relative

## Path Conventions

Single project (Library + CLI):
- Source: `src/mixpanel_headless/`
- Tests: `tests/unit/`, `tests/pbt/`, `tests/integration/`, `tests/fixtures/`
- Specs: `specs/044-session-replay/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify the dev environment is ready. Minimal — the 042 architecture provides the scaffolding.

- [X] T001 Run `just install-hooks` from the repo root to ensure the pre-commit hook is installed (per project CLAUDE.md "First-time setup after cloning"). No-op if already installed.
- [X] T002 [P] Run `just check` against `main` to establish a clean baseline (verifies lint + format + typecheck + tests + build pass before any new work lands). Result: 6442 pass / 1 skipped / 92.08% coverage / build succeeded.

**Checkpoint**: Dev environment ready, baseline clean.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Add the exception hierarchy, the `MixpanelAPIClient.sign_replays()` method, and the 403→`SessionReplayAccessError` mapping that every user story will use. Also add the test rrweb fixture used by Phase 1 tests.

**⚠️ CRITICAL**: T003–T010 MUST land before any US1 implementation task. US1 cannot raise the right errors or hit the signing endpoint without these.

- [X] T003 Add 4 new exception classes to `src/mixpanel_headless/exceptions.py` per [contracts/python-api.md §3](contracts/python-api.md#3-exception-hierarchy) and [contracts/error-messages.md §1–§3](contracts/error-messages.md): `SessionReplayError(APIError)`, `SessionReplayAccessError(SessionReplayError)`, `SignedURLExpiredError(SessionReplayError)`, `ReplayNotFoundError(SessionReplayError)`. Full Google-style docstrings. Override `to_dict()` on each to preserve `details` keys (`project_id`, `flag`, `replay_id`, `retention_days`, `signed_at`, `expired_at`, `cdn_url_prefix` as applicable).
- [X] T004 [P] Re-export the 4 new exceptions from `src/mixpanel_headless/__init__.py`. Add to `__all__`.
- [X] T005 Add a unit test file `tests/unit/test_exceptions_session_replay.py`: each new exception subclasses `APIError` via `SessionReplayError`; each preserves `details` through `to_dict()` round-trip; error messages match the catalog in [contracts/error-messages.md](contracts/error-messages.md) verbatim.
- [X] T006 [P] Add a unit test file `tests/unit/_internal/test_api_client_sign_replays.py`: with a mocked httpx response, `MixpanelAPIClient.sign_replays(["r-1", "r-2"], env="prod")` POSTs to `/app/projects/{project_id}/replays/sign/bulk` with body `{"replays": [{"replay_id": "r-1", "replay_env": "prod"}, {"replay_id": "r-2", "replay_env": "prod"}]}`; a 403 with body containing `SESSION_RECORDING_SENSITIVE_DATA` maps to `SessionReplayAccessError` with `details={"project_id": ..., "flag": "SESSION_RECORDING_SENSITIVE_DATA", "permission_required": "sensitive_data_replay"}`; other 4xx/5xx pass through as the existing `APIError`/`ServerError`. Run them now — they MUST fail.
- [X] T007 Add `MixpanelAPIClient.sign_replays(replay_ids: list[str], env: Literal["prod", "dev"] = "prod") -> list[SignedReplayResponse]` to `src/mixpanel_headless/_internal/api_client.py`. Returns the raw decoded response objects; conversion to `SignedReplay` is done in `ReplaysService` (T020). Full docstring naming the endpoint, request shape, and the sensitive-data 403 mapping. Wire the 403 detection into the existing `_handle_response()` (or equivalent) so the mapping fires on any sign-related call.
- [X] T008 [P] Create `tests/fixtures/rrweb/sample-replay-001.json` — minimal rrweb event stream: login + one click + navigation. Hand-construct ~20 events using the rrweb-types event shape (DomContentLoaded, Meta, FullSnapshot, IncrementalSnapshot with MouseInteraction `click`, Meta navigate). Add a README.md in `tests/fixtures/rrweb/` documenting the fixture purpose and event shape.
- [X] T009 [P] Run `just typecheck` after T003/T004/T007 to confirm mypy --strict passes against the new exception types and api_client method signature.
- [X] T010 Run the foundational tests (T005, T006) — they MUST now pass after T003/T004/T007 land. Result: 27/27 pass, mypy clean.

**Checkpoint**: Exception hierarchy live, API client wired for signing. US1 can begin.

---

## Phase 3: User Story 1 — Discover and pull a user's recent replays (Priority: P1) 🎯 MVP

**Goal**: Workspace can list a user's replays, sign them, and pull raw rrweb bytes either buffered (`fetch_replay`) or streamed (`stream_replay`). Single-replay `Replay` is materialized with raw events; `actions` stays empty (analyzer ships in US2).

**Independent Test**: per spec.md §1 — given a known active `distinct_id` and a 7-day window, `Workspace.list_replays` returns ≥1 summary; `sign_replay` produces a valid signed URL; `fetch_replay` returns a `Replay` with at least one rrweb event; sensitive-data project raises `SessionReplayAccessError`; older replay missing `$mp_replay_retention_period` returns `retention_days=30` with a warning.

### Tests for User Story 1 (write FIRST, ensure they FAIL before implementation)

- [X] T011 [P] [US1] Add unit test file `tests/unit/test_types_replay_summary.py` per [data-model.md §2.1](data-model.md#21-replaysummary): construction validation (replay_id non-empty, project_id > 0, retention_days ∈ {1,7,30,90}); `to_dict()` round-trip; `ResultWithDataFrame.df` returns a single-row DataFrame with the documented columns.
- [X] T012 [P] [US1] Add unit test file `tests/unit/test_types_signed_replay.py` per [data-model.md §2.2](data-model.md#22-signedreplay): `__repr__` and `__str__` mask `query_string` as `"<redacted N chars>"`; `expires_at == signed_at + 300`; `is_expired` boundary at 300s; `to_dict()` preserves the full credential AND includes the `_warning` key; validation rules (url trailing slash, env ∈ {"prod","dev"}). Verify NO substring of `query_string` leaks into `repr(sr)` or `str(sr)`.
- [X] T013 [P] [US1] Add unit test file `tests/unit/test_types_replay_event.py` per [data-model.md §2.4](data-model.md#24-replayevent): construction validation, DataFrame projection columns.
- [X] T014 [P] [US1] Add unit test file `tests/unit/test_types_replay.py` per [data-model.md §2.5](data-model.md#25-replay): `events_df` columns match the documented schema; `pages_df` derived from Meta events in `rrweb_events`; `duration_seconds = (end_time - start_time) / 1000`; `to_rrweb_player_json()` returns timestamp-sorted dicts; Phase 1: `actions == []` AND `actions_df` returns an empty DataFrame with the documented column schema; analyzer-dependent accessors (`summary_markdown`, `errors`, `clicks_on`) raise `NotImplementedError("analyzer ships in Phase 2")`.
- [ ] T015 [P] [US1] Add unit test file `tests/unit/_internal/test_replays_service.py`: with a mocked `MixpanelAPIClient`, `ReplaysService.sign(["r-1"])` returns a `list[SignedReplay]`; `ReplaysService.fetch_files(signed, retention_days=30, max_files=500, concurrency=50)` walks `0000-30.json`, `0001-30.json`, ... in parallel batches of 50, terminates on first 404, raises `ReplayNotFoundError` if file `0000-30.json` is 404, sorts the concatenated events by timestamp; 403 mid-walk re-signs when `re_sign=True` and raises `SignedURLExpiredError` when `re_sign=False`; `max_files` bound respected. **Also**: mobile-replay detection — given a synthetic non-rrweb event stream (first event missing standard rrweb `type`/`data`/`timestamp` keys), `fetch_files` raises `NotImplementedError` per [contracts/error-messages.md §9](contracts/error-messages.md#9-mobile-replay-attempted-forward-compat-marker).
- [ ] T016 [P] [US1] Add unit test file `tests/unit/test_workspace_replays.py`: with a mocked `ReplaysService`, `Workspace.list_replays(distinct_id="u", from_date="2026-05-20", to_date="2026-05-27")` issues exactly one `Workspace.query()` call against `$mp_session_record` grouped on `$mp_replay_id` AND `$mp_replay_retention_period` AND `$time`; `list_replays(distinct_id=...)` without `from_date`/`to_date` raises `ValueError`; `list_replays(distinct_id=..., replay_ids=...)` raises `ValueError`; `list_replays(replay_ids=["r-1"])` works without a date window; empty result returns `[]` not raise; missing `$mp_replay_retention_period` defaults to 30 with a `UserWarning` per [contracts/error-messages.md §10](contracts/error-messages.md#10-retention-warning-structured-log-not-exception); `events_for_replay(..., event_properties=["a","b","c","d","e","f"])` raises `ValueError` per [contracts/error-messages.md §4](contracts/error-messages.md#4-valueerror-on-bad-events_for_replay-group-by-count). **Also (FR-017)**: `fetch_replay(rid, include_mixpanel_events=True)` triggers exactly one follow-up `events_for_replay` call AND populates `Replay.mixpanel_events`; default `include_mixpanel_events=False` makes no follow-up call. **Also (FR-030, deferred from US2 since the method exists at the Workspace level)**: add a placeholder test that `Workspace.replays_for_user("u", from_date=..., to_date=...)` exists on the class and raises a deliberate `NotImplementedError("ships in US2")` in Phase 1 (until T062 lands the implementation, at which point this test is replaced by full coverage in the US2 test additions documented at T064a).
- [ ] T017 [P] [US1] Add PBT test file `tests/pbt/test_cdn_walker_pbt.py`: given an arbitrary 404 position `k ∈ [0, max_files]`, the walker terminates at exactly `k`, never re-fetches the 404, respects `max_files`, returns events in timestamp order regardless of fetch ordering. Use Hypothesis to generate 404 positions and per-file event counts.
- [ ] T018 [P] [US1] Add integration test file `tests/integration/test_replays_live.py` marked `@pytest.mark.live`: against a fixture project with a known replay-bearing user, `list_replays` returns ≥1 summary; `sign_replays` returns valid signed URLs; a CDN HEAD request on the signed URL returns 200; `fetch_replay` returns a `Replay` with ≥1 rrweb event AND a non-zero duration; sensitive-data fixture project (if available) raises `SessionReplayAccessError` with the documented `details` dict.
- [ ] T019 [US1] Run T011–T018 against an empty workspace — all unit + PBT tests MUST fail (no implementation yet); live integration is skipped without `MP_LIVE_TESTS=1`.

### Implementation for User Story 1

- [X] T020 [P] [US1] Add `ReplaySummary`, `SignedReplay`, `ReplayEvent`, `Replay`, `UserAction` (placeholder, no analyzer yet) dataclasses to `src/mixpanel_headless/types.py` per [data-model.md §2](data-model.md). `Replay.actions: list[UserAction] = field(default_factory=list)` in Phase 1. `SignedReplay` overrides `__repr__`/`__str__` and `to_dict()` per [data-model.md §2.2](data-model.md#22-signedreplay). All lazy DataFrame properties use the `_*_df_cache` field + `object.__setattr__` pattern from the existing `FlowQueryResult`.
- [X] T021 [P] [US1] Re-export `ReplaySummary`, `SignedReplay`, `ReplayEvent`, `Replay`, `UserAction` from `src/mixpanel_headless/__init__.py`. Add to `__all__`.
- [ ] T022 [US1] Create `src/mixpanel_headless/_internal/services/replays.py` per [plan.md "Project Structure"](plan.md#project-structure). `ReplaysService` constructor takes `MixpanelAPIClient` and a logger; exposes `sign(replay_ids, env) -> list[SignedReplay]`, `fetch_files(signed, retention_days, max_files, concurrency, re_sign_on_expiry) -> list[dict]`, `walk_cdn_async(signed, retention_days, max_files, concurrency) -> AsyncIterator[dict]`, `discover(distinct_id|replay_ids, from_date, to_date) -> list[ReplaySummary]`, `events_for(replay_ids, event_properties) -> dict[str, list[ReplayEvent]]`. Full docstrings. Internally uses `httpx.AsyncClient` (or threaded `concurrent.futures` matching existing project convention — match the pattern used by `_internal/services/flows.py` if present, else use httpx async).
- [ ] T023 [US1] Wire `ReplaysService` into `Workspace.__init__()` in `src/mixpanel_headless/workspace.py` alongside the existing services (look for the `self._services` dict or equivalent — match the existing pattern). Construction happens lazily on first replay-method access to avoid paying for it in non-replay sessions.
- [ ] T024 [US1] Add `Workspace.list_replays(*, distinct_id=None, replay_ids=None, from_date=None, to_date=None, limit=100) -> list[ReplaySummary]` per [contracts/python-api.md §1](contracts/python-api.md#1-workspace-methods). Validates the XOR(distinct_id, replay_ids) precondition; delegates discovery to `ReplaysService.discover()`. Full docstring with Args/Returns/Raises/Example per CLAUDE.md standards.
- [ ] T025 [US1] Add `Workspace.events_for_replay(replay_id, *, event_properties=None) -> list[ReplayEvent]` and `Workspace.events_for_replays(replay_ids, *, event_properties=None) -> dict[str, list[ReplayEvent]]`. Both validate `len(event_properties) <= 5` and raise `ValueError` per [contracts/error-messages.md §4](contracts/error-messages.md#4-valueerror-on-bad-events_for_replay-group-by-count). Delegate to `ReplaysService.events_for()`.
- [ ] T026 [US1] Add `Workspace.sign_replay(replay_id, *, env="prod") -> SignedReplay` and `Workspace.sign_replays(replay_ids, *, env="prod") -> list[SignedReplay]`. `sign_replay` is a thin wrapper around `sign_replays([replay_id])[0]`. Both delegate to `ReplaysService.sign()`.
- [ ] T027 [US1] Add `Workspace.fetch_replay(replay_id, *, env="prod", retention_days=None, max_files=500, include_mixpanel_events=False, event_properties=None, cdn_concurrency=50) -> Replay`. When `retention_days is None`, run a one-replay `list_replays(replay_ids=[replay_id])` to discover it; otherwise skip the discovery RTT. When `include_mixpanel_events=True`, follow with `events_for_replay()` and populate `Replay.mixpanel_events`. Construct `Replay` with `actions=[]` in Phase 1 (analyzer wires in T056 in US2).
- [ ] T028 [US1] Add `Workspace.stream_replay(replay_id, *, env="prod", retention_days=None, max_files=500, re_sign_on_expiry=True, cdn_concurrency=50) -> Iterator[dict]`. Wraps `ReplaysService.walk_cdn_async()` and converts to a sync iterator (use `asyncio.run` or the project's existing sync wrapper pattern). Catch 403-on-expiry and re-sign when flag is True; raise `SignedURLExpiredError` when False.
- [ ] T028.5 [US1] Add mobile-replay detection to `ReplaysService.fetch_files` and `walk_cdn_async` in `src/mixpanel_headless/_internal/services/replays.py`: after fetching the first batch, inspect the first event's shape — if it lacks the standard rrweb keys (`type`, `data`, `timestamp`) or carries a known mobile marker, raise `NotImplementedError` with the message from [contracts/error-messages.md §9](contracts/error-messages.md#9-mobile-replay-attempted-forward-compat-marker). Also add a `Workspace.replays_for_user(...)` stub in `src/mixpanel_headless/workspace.py` that raises `NotImplementedError("ships in US2")` in Phase 1; T062 replaces the stub with the real implementation. Both behaviors are tested by T015 (mobile) and T016 (`replays_for_user` stub).
- [ ] T029 [US1] Run T011–T017 — all unit + PBT tests MUST now pass. Run T018 with `MP_LIVE_TESTS=1` against a known fixture project — MUST pass.
- [ ] T030 [US1] Run `just test-cov` — coverage on the new files (`_internal/services/replays.py`, the new dataclass code in `types.py`, the new methods in `workspace.py`) MUST be ≥90%.
- [ ] T031 [US1] Run `just mutate` against `src/mixpanel_headless/_internal/services/replays.py`; mutation score MUST be ≥80%. Adjust tests if surviving mutants reveal weak coverage.
- [ ] T032 [US1] Run `just check` — confirm lint, format, typecheck, all tests pass, coverage gate met.

### Phase 1 CLI bridge (US3 work that ships with PR 1)

These tasks belong to US3 conceptually but ship in PR 1 because they depend only on US1 methods. Tagged `[US3]` for traceability.

- [ ] T033 [P] [US3] Add CLI test file `tests/unit/cli/test_replays_cli.py` covering the Phase 1 commands (list, events, sign, fetch). For each command verify: `--help` documents the documented flags; happy-path invocation produces the documented JSON shape; redaction behavior on `mp replays sign` masks `query_string`; `--reveal-signed-urls` includes the full credential AND emits the documented stderr warning per [contracts/cli-commands.md §4](contracts/cli-commands.md#4-mp-replays-sign); `mp replays fetch -o file.json` writes a JSON array of timestamp-sorted rrweb events; exit code mapping per [contracts/cli-commands.md §8 "Error mapping"](contracts/cli-commands.md#8-global-behaviors). Tests MUST fail before T034 implementation lands.
- [ ] T034 [US3] Create `src/mixpanel_headless/cli/commands/replays.py` with a Typer `replays_app = typer.Typer(name="replays", help="Session replay commands")`. Implement Phase 1 commands: `list`, `events`, `sign`, `fetch`. Follow the existing pattern: `@handle_errors`, `get_workspace(ctx)`, `output_result(ctx, ..., format=format)`. Per-command details in [contracts/cli-commands.md §2–§5](contracts/cli-commands.md#2-mp-replays-list).
- [ ] T035 [US3] Register `replays_app` in `src/mixpanel_headless/cli/main.py::_register_commands()` (or equivalent — find the place where existing groups like `dashboards_app`, `cohorts_app` are registered and append). Add `mp replays` to the CLI overview help text if one exists.
- [ ] T036 [US3] Wire `sign` command's redaction: default `--format json` and `--format jsonl` use `SignedReplay.__repr__`-style masking for `query_string`; `--reveal-signed-urls` uses `SignedReplay.to_dict()` which preserves the credential AND the `_warning` key. Emit the documented stderr warning every time `--reveal-signed-urls` is used per [contracts/cli-commands.md §4](contracts/cli-commands.md#4-mp-replays-sign).
- [ ] T037 [US3] Wire `fetch -o file.json` output: serialize `Replay.to_rrweb_player_json()` as a JSON array, written to the named file. Without `-o`, print the one-line summary per [contracts/cli-commands.md §5](contracts/cli-commands.md#5-mp-replays-fetch).
- [ ] T038 [US3] Verify `mp replays events <id> --properties a,b,c,d,e,f` exits with code 3 and the documented error message per [contracts/error-messages.md §4](contracts/error-messages.md#4-valueerror-on-bad-events_for_replay-group-by-count) — comes for free via `handle_errors` if T025 raises `ValueError` correctly.

### Verify User Story 1 + Phase 1 CLI

- [ ] T039 [US1] Run T033 (CLI tests) — all MUST pass.
- [ ] T040 [US1] Manual smoke-test the quickstart §1.1–§1.5 from [quickstart.md](quickstart.md#story-1-p1--discover-and-pull-a-users-recent-replays) against a fixture project. Verify the rrweb JSON produced by `fetch -o` actually loads in the rrweb JS player.
- [ ] T041 [US1] Run `just check` end-to-end. All gates pass.
- [ ] T042 [US1] Security audit per [quickstart.md §"Security verification"](quickstart.md#security-verification): grep verbose stderr output for `Signature=`, `URLPrefix=`, `Expires=`. MUST report no leaks.

**Checkpoint**: PR 1 ready to merge. Discovery + signed access + per-replay fetch work end-to-end. Phase 1 CLI shipped. `Replay.actions` empty (analyzer is US2). Memo for the PR: "Phase 1 of 3 of the source design."

---

## Phase 4: User Story 2 — Behavioral analysis across many replays (Priority: P2)

**Goal**: Vendored rrweb analyzer ships and populates `Replay.actions`. `ReplayBundle` exposes seven DataFrame projections, two graph projections, one tree projection, seven aggregations, six chainable filters, lazy enrichment, comparison, and summary markdown. `Workspace` gains `fetch_replays`, `replays_for_user`, `analyze_replay`.

**Independent Test**: per spec.md §2 — a `ReplayBundle` built from 10 fixture rrweb streams exposes all seven DataFrame projections; aggregations return non-empty results for the appropriate fixtures; chainable filters return new bundles that are proper subsets; lazy-import errors name the exact `pip install` command.

### Tests for User Story 2 (write FIRST, ensure they FAIL before implementation)

- [ ] T043 [P] [US2] Add fixture files: `tests/fixtures/rrweb/sample-replay-002.json` (multi-page: 5+ navigations, mixed interactions including inputs and scrolls); `tests/fixtures/rrweb/sample-replay-003.json` (pathological: console errors, rage clicks, dead clicks, long pauses). Document each fixture's expected aggregations in a comment block at the top of the file or in `tests/fixtures/rrweb/README.md`.
- [ ] T044 [P] [US2] Create `tests/fixtures/rrweb/sample_bundle_fixture.py` (note: `.py` not `.json`) exporting a `build_sample_bundle() -> ReplayBundle` function that constructs a deterministic 10-replay bundle from the three sample JSON streams (replay 1×4, replay 2×3, replay 3×3 — adjusting timestamps so each replay is distinct). The bundle's exact contents are the reference for all PBT and aggregation tests.
- [ ] T045 [P] [US2] Port `test_rrweb_analyzer.py` from `analytics/backend/replays/test_rrweb_analyzer.py` into `tests/unit/test_rrweb_analyzer.py`. Adjust imports to `mixpanel_headless._internal.replays.rrweb_analyzer`. Verify all upstream test cases pass: DOM tracker invariants, every IncrementalSource handled, debounce behavior, markdown output format. Skip any tests that depend on monorepo-specific fixtures.
- [ ] T046 [P] [US2] Add unit test file `tests/unit/test_replay_labels.py` per [contracts/python-api.md §4](contracts/python-api.md#4-label-functions): `default_label_fn(action)` produces `f"{action.action}:{tag}@{normalized_url}"`; URL normalization strips query strings and replaces numeric path segments with `:id`; `selector_label_fn("data-testid")` uses the attribute when present, falls back to default when absent; `url_normalizer("/users/12345/profile?ref=x") == "/users/:id/profile"`.
- [ ] T047 [P] [US2] Add PBT test file `tests/pbt/test_replay_labels_pbt.py`: label stability across DOM perturbations. Hypothesis generates pairs of `UserAction` instances differing only in metadata keys not used by the label; `default_label_fn(a) == default_label_fn(a')` MUST hold. Same invariant for `selector_label_fn(...)`.
- [ ] T048 [P] [US2] Add unit test file `tests/unit/test_replay_aggregators.py` covering the aggregator functions (`top_paths`, `top_clicks`, `top_pages`, `dead_clicks`, `rage_clicks`, `long_pauses`, `error_sessions`): each returns the expected DataFrame schema; rage_click threshold and window respected; dead_click window respected; pause threshold respected. Use the fixture bundle from T044.
- [ ] T049 [P] [US2] Add unit test file `tests/unit/test_types_replay_with_analyzer.py`: after the analyzer is wired (T056), `Replay.actions` is non-empty for the sample fixtures; `Replay.actions_df` columns match [data-model.md §2.5](data-model.md#25-replay); `summary_markdown` returns non-empty markdown; `errors` returns rows matching the `console_error` action; `clicks_on(predicate)` filters as documented; `to_rrweb_player_json()` already covered in T014.
- [ ] T050 [P] [US2] Add unit test file `tests/unit/test_types_replay_bundle.py` per [data-model.md §2.6](data-model.md#26-replaybundle): seven DataFrame projections present with documented columns and grain (one row per replay for `sessions_df`; long format for `actions_df`, `events_df`, `mixpanel_df`, `pages_df`; aggregated for `elements_df`, `transitions_df`); `df` defaults to `sessions_df`; `page_graph` / `element_graph` are `networkx.DiGraph` with the documented node and edge attributes; `path_tree` is an `anytree.AnyNode` with the synthetic Start root; `event_log()` returns a DataFrame with `case:concept:name`, `concept:name`, `time:timestamp` columns (pm4py-absent path; pm4py path covered in US4); all seven aggregations return the documented DataFrame shapes; all six chainable filters return new `ReplayBundle` instances that are proper subsets and leave the original unchanged; `join_mixpanel_events()` populates `mixpanel_df` on the returned bundle; `summary_markdown` returns non-empty markdown; `compare(other)` returns an action-frequency diff DataFrame.
- [ ] T051 [P] [US2] Add unit test file `tests/unit/test_types_replay_bundle_imports.py`: with networkx not importable (mock `sys.modules`), `bundle.page_graph`, `bundle.element_graph`, `bundle.path_tree` raise `ImportError` with the exact `pip install` message documented in [contracts/error-messages.md §6](contracts/error-messages.md#6-importerror-on-missing-optional-extras). Same for anytree on `path_tree`. (pm4py and tslearn covered in US4.)
- [ ] T052 [P] [US2] Add PBT test file `tests/pbt/test_types_replay_bundle_pbt.py` covering the 9 invariants in [data-model.md §5](data-model.md#5-invariants-verified-by-pbt): sessions cardinality, actions sum, filter subset, filter↔where equivalence, head bound, sample bound, sample determinism, immutability, label stability. Hypothesis strategy: generate arbitrary `Replay` instances with synthetic action streams, build a bundle, verify each invariant.
- [ ] T053 [US2] Run T045–T052 with empty implementation files in place — all MUST fail.

### Implementation for User Story 2

- [ ] T054 [P] [US2] Create `src/mixpanel_headless/_internal/replays/__init__.py` (empty) and the directory structure per [plan.md "Project Structure"](plan.md#project-structure).
- [ ] T055 [US2] VENDOR `src/mixpanel_headless/_internal/replays/rrweb_analyzer.py` from `analytics/backend/replays/rrweb_analyzer.py` (~600 LoC). Module docstring MUST include: (1) the upstream source path and the source-commit sha at vendoring time, (2) the divergence policy ("re-diff quarterly against upstream"), (3) the rationale linking to [research.md §R-6](research.md). Adjust imports to remove monorepo-specific dependencies; pure stdlib only (no `numpy`, `pydantic`, `httpx`). The public surface is `RrwebAnalyzer.analyze(events: list[dict]) -> AnalyzerResult` returning `actions: list[UserAction]`, `markdown_summary: str`, `pages: list[PageVisit]`, `errors: list[ConsoleError]`.
- [ ] T056 [US2] Modify `Replay` construction in `Workspace.fetch_replay` (T027) to call `RrwebAnalyzer.analyze(rrweb_events)` and populate `actions`, plus drive `summary_markdown` / `errors` / `pages_df` from the analyzer's structured output. Remove the Phase 1 `NotImplementedError` raises on `summary_markdown`, `errors`, `clicks_on` in `Replay` (T020).
- [ ] T057 [P] [US2] Create `src/mixpanel_headless/_internal/replays/labels.py` with `default_label_fn(action: UserAction) -> str`, `selector_label_fn(attr: str = "data-testid") -> Callable[[UserAction], str]`, `url_normalizer(url: str) -> str`. Full docstrings naming the design intent (process-mining stability) and linking to [research.md §R-7](research.md). Re-export from `mixpanel_headless.types` and add to `__all__`.
- [ ] T058 [P] [US2] Create `src/mixpanel_headless/_internal/replays/aggregators.py` with module-level functions `top_paths(bundle, n, label_fn)`, `top_clicks(bundle, n)`, `top_pages(bundle, n)`, `dead_clicks(bundle, window_ms)`, `rage_clicks(bundle, threshold, window_ms)`, `long_pauses(bundle, threshold_s)`, `error_sessions(bundle)`. Each returns a `pd.DataFrame`. `error_sessions` returns a list of replay IDs that the bundle wrapper translates into a filtered bundle (see T059).
- [ ] T059 [US2] Add `ReplayBundle` dataclass to `src/mixpanel_headless/types.py` per [data-model.md §2.6](data-model.md#26-replaybundle). All seven DataFrame projections + graph/tree projections + event_log + aggregations + chainable filters + `join_mixpanel_events` + `summary_markdown` + `compare` + `cluster` (which raises `ImportError` with the documented message until US4 wires `tslearn`). Inherit from `ResultWithDataFrame`. `df` returns `sessions_df`. Lazy `page_graph` / `element_graph` / `path_tree` import their packages inside the property body per [contracts/error-messages.md §6](contracts/error-messages.md#6-importerror-on-missing-optional-extras). `event_log()` returns a DataFrame in this phase (pm4py wrapping is US4).
- [ ] T060 [US2] Re-export `ReplayBundle` and the label functions from `src/mixpanel_headless/__init__.py`. Add to `__all__`.
- [ ] T061 [US2] Add `Workspace.fetch_replays(replay_ids, *, env="prod", max_files=500, include_mixpanel_events=False, event_properties=None, concurrency=4, cdn_concurrency=50) -> ReplayBundle` per [contracts/python-api.md §1 "Phase 2: Bundle"](contracts/python-api.md#phase-2-bundle). Outer concurrency `concurrency` (default 4) for replay-level parallelism; inner concurrency `cdn_concurrency` (default 50) for per-replay CDN walks. Constructs the bundle with `computed_at=datetime.now(timezone.utc).isoformat()` and `project_id` from the workspace.
- [ ] T062 [US2] Add `Workspace.replays_for_user(distinct_id, *, from_date, to_date, limit=100, include_mixpanel_events=True, event_properties=None) -> ReplayBundle`. Composes `list_replays` + `fetch_replays`. Defaults `include_mixpanel_events=True` per [contracts/python-api.md §1](contracts/python-api.md#1-workspace-methods).
- [ ] T063 [US2] Add `Workspace.analyze_replay(replay_id) -> str`. Sugar for `self.fetch_replay(replay_id).summary_markdown`.
- [ ] T064 [US2] Run T045–T052 — all MUST now pass.
- [ ] T064a [US2] Replace the T016 placeholder `replays_for_user` test (the Phase 1 `NotImplementedError` assertion) with full unit coverage in `tests/unit/test_workspace_replays.py`: with a mocked `ReplaysService`, `replays_for_user("u", from_date="2026-05-20", to_date="2026-05-27")` composes one `list_replays` + one `fetch_replays` call; default `include_mixpanel_events=True` produces a bundle with `mixpanel_df` populated on every replay; `limit` caps `len(bundle.replays)`; `event_properties` validation matches `events_for_replay` (raises `ValueError` on >5). Verify the test that previously asserted `NotImplementedError` is removed, not just commented out.
- [ ] T065 [US2] Run `just test-cov` — coverage on `_internal/replays/rrweb_analyzer.py`, `_internal/replays/labels.py`, `_internal/replays/aggregators.py`, and the new `ReplayBundle` code in `types.py` MUST be ≥90%.
- [ ] T066 [US2] Run `just mutate` against the four new pure modules; mutation score MUST be ≥80% on each. Add tests for any surviving mutants until the gate passes.
- [ ] T067 [US2] Run `just check` end-to-end.

### Phase 2 CLI bridge (US3 work that ships with PR 2)

- [ ] T068 [P] [US3] Extend `tests/unit/cli/test_replays_cli.py` (created in T033) with `analyze` and `for-user` command tests per [contracts/cli-commands.md §6–§7](contracts/cli-commands.md#6-mp-replays-analyze): `analyze` prints markdown to stdout by default and JSON action list with `--format json`; `for-user --include analyze --include events --out-dir DIR` writes per-replay markdown + `index.json`; exit code mapping. Tests MUST fail before T069 lands.
- [ ] T069 [US3] Implement `analyze` and `for-user` Typer commands in `src/mixpanel_headless/cli/commands/replays.py` per [contracts/cli-commands.md §6–§7](contracts/cli-commands.md#6-mp-replays-analyze). `for-user` writes one `{replay_id}-summary.md` per replay plus an `index.json` (which is `bundle.sessions_df.to_json(orient="records")`). One-line stdout summary at the end naming the count and total activity.

### Verify User Story 2

- [ ] T070 [US2] Run T068 — all MUST pass.
- [ ] T071 [US2] Manual smoke-test the quickstart §2.1–§2.5 and §3.1–§3.3 from [quickstart.md](quickstart.md#story-2-p2--behavioral-analysis-across-many-replays) against a fixture project.
- [ ] T072 [US2] Run `just check` end-to-end.
- [ ] T073 [US2] Security audit (re-run T042 in PR 2 context). No bearer-credential leaks in any new command path.

**Checkpoint**: PR 2 ready to merge. Vendored analyzer live, `ReplayBundle` complete with all projections / aggregations / filters, `analyze` and `for-user` CLI commands shipped. Memo for the PR: "Phase 2 of 3 of the source design. PR 1 (T001–T042) is a prerequisite."

---

## Phase 5: User Story 4 — Process mining and ML clustering (Priority: P3, gated on demand)

**Goal**: pm4py and tslearn adapters ship behind optional extras. `bundle.event_log()` returns a pm4py `EventLog` when pm4py is installed; falls back to DataFrame when absent. `bundle.cluster(n)` works when tslearn is installed; raises `ImportError` with the install command when absent.

**Independent Test**: per spec.md §4 — pm4py-absent path returns the DataFrame; pm4py-present path returns an `EventLog`; custom `label_fn` produces every label; `tslearn`-present `cluster()` returns a bundle whose replays have `cluster_label`.

**⚠️ DECISION GATE**: Ship Phase 5 only if user demand materializes after PR 2 lands. If no pull, defer indefinitely. (Per [research.md §R-12](research.md).)

### Tests for User Story 4 (write FIRST, ensure they FAIL before implementation)

- [ ] T074 [P] [US4] Add unit test file `tests/unit/test_pm4py_adapter.py` marked `@pytest.mark.skipif(not has_pm4py(), reason="requires pm4py")`: `bundle.event_log()` returns a `pm4py.objects.log.obj.EventLog`; column renaming follows the XES standard (`case:concept:name`, `concept:name`, `time:timestamp`); a custom `label_fn` is the sole source of activity labels; the returned EventLog is directly usable in `pm4py.discover_petri_net_inductive`.
- [ ] T075 [P] [US4] Add unit test file `tests/unit/test_ml_adapter.py` marked `@pytest.mark.skipif(not has_tslearn(), reason="requires tslearn")`: `bundle.cluster(n=3, features="actions")` returns a new bundle whose replays each carry a `cluster_label` in `{0, 1, 2}`; `features="pages"` works against `pages_df`; reproducibility (seed parameter passed through).
- [ ] T076 [P] [US4] Extend `tests/unit/test_types_replay_bundle_imports.py` (T051) with: pm4py-absent → `event_log()` returns a DataFrame (no ImportError); tslearn-absent → `cluster()` raises `ImportError` with exact message per [contracts/error-messages.md §6](contracts/error-messages.md#6-importerror-on-missing-optional-extras).
- [ ] T077 [US4] Run T074–T076 — all MUST fail (no extras installed yet, no adapter code).

### Implementation for User Story 4

- [ ] T078 [P] [US4] Add the three optional extras to `pyproject.toml` per [contracts/python-api.md §6 "Phase 3"](contracts/python-api.md#6-phase-boundaries-python-api) and [research.md §R-9](research.md): `replay-mining = ["pm4py>=2.7"]`, `replay-ml = ["tslearn>=0.6"]`, `replay-all = ["mixpanel-headless[replay-mining,replay-ml]", "networkx>=3", "anytree>=2"]`. Re-run `uv sync --all-extras` and verify `just check` still passes.
- [ ] T079 [P] [US4] Create `src/mixpanel_headless/_internal/replays/pm4py_adapter.py` with `wrap_event_log_dataframe(df: pd.DataFrame) -> "pm4py.objects.log.obj.EventLog"`. Lazy-imports pm4py inside the function body. Module docstring documents the fallback contract (returns the DataFrame unchanged if pm4py is absent and the caller passed `allow_dataframe_fallback=True`; raises ImportError otherwise — though the public `bundle.event_log()` only calls this on the pm4py-present path).
- [ ] T080 [P] [US4] Create `src/mixpanel_headless/_internal/replays/ml_adapter.py` with `cluster_bundle(bundle: ReplayBundle, n: int, features: Literal["actions", "pages"], seed: int | None = None) -> ReplayBundle`. Uses `tslearn.clustering.TimeSeriesKMeans` with DTW metric. Lazy-imports tslearn inside the function body. Returns a new bundle whose replays carry a `cluster_label` attribute (set via `dataclasses.replace`).
- [ ] T081 [US4] Wire `pm4py_adapter` into `ReplayBundle.event_log()` in `src/mixpanel_headless/types.py`: when pm4py is importable, call `wrap_event_log_dataframe(df)` and return the EventLog; otherwise return the DataFrame.
- [ ] T082 [US4] Wire `ml_adapter` into `ReplayBundle.cluster()` in `src/mixpanel_headless/types.py`: delegate to `ml_adapter.cluster_bundle()`. Catch `ImportError` from inside the adapter and re-raise with the documented message per [contracts/error-messages.md §6](contracts/error-messages.md#6-importerror-on-missing-optional-extras).
- [ ] T083 [US4] Install the extras locally (`uv pip install pm4py tslearn`) and run T074–T076 — all MUST now pass.

### Verify User Story 4

- [ ] T084 [US4] Run the full test matrix: (a) clean env (no extras) — `just test`; (b) with `replay-mining` — `uv pip install pm4py && just test`; (c) with `replay-ml` — `uv pip install tslearn && just test`; (d) all extras — `just test`. Each combination MUST pass; the gated tests MUST run only when their package is present.
- [ ] T085 [US4] Manual smoke-test quickstart §4.1–§4.3 from [quickstart.md](quickstart.md#story-4-p3--process-mining-and-ml-clustering).
- [ ] T086 [US4] Run `just check` end-to-end.

**Checkpoint**: PR 3 ready to merge. Optional extras live; pm4py and tslearn integrations work. Memo for the PR: "Phase 3 of 3 of the source design. PRs 1 and 2 are prerequisites."

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, plugin help integration, post-PR housekeeping. Run after each PR; this phase consolidates the cross-PR tasks.

- [ ] T087 [P] Update `mixpanel-plugin/help.py` so `python help.py Replay`, `python help.py ReplayBundle`, `python help.py SignedReplay`, `python help.py Workspace.list_replays`, `python help.py Workspace.fetch_replay`, etc. return the documented signature + docstring + related types. Verify by running each command after PR 2 lands.
- [ ] T088 [P] Update `mixpanel-plugin/.claude/skills/mixpanelyst/SKILL.md` (or the equivalent skill file) to add a "Session Replay" section with example queries: "Show me what user X did in the last week", "Find all sessions where users clicked the upgrade button but did not complete checkout", "What is the most common path users take through onboarding?" Each example invokes `replays_for_user` or `ReplayBundle.find_pattern`.
- [ ] T089 [P] Add a CHANGELOG.md entry for each PR:
  - PR 1: "Added discovery, signed CDN access, and per-replay fetch for session replays (`Workspace.list_replays`, `sign_replay(s)`, `fetch_replay`, `stream_replay`; `mp replays list/events/sign/fetch`). Depends on undocumented `/app/projects/<id>/replays/sign[/bulk]` endpoint."
  - PR 2: "Added vendored rrweb analyzer and `ReplayBundle` cross-session aggregations (`Workspace.fetch_replays`, `replays_for_user`, `analyze_replay`; `mp replays analyze` and `for-user`). Adds `[replay-all]` optional extra for networkx + anytree."
  - PR 3 (if it ships): "Added optional pm4py and tslearn integration for process mining and session clustering (`ReplayBundle.event_log()` returns pm4py `EventLog`; `ReplayBundle.cluster()` works). New extras: `[replay-mining]`, `[replay-ml]`."
- [ ] T090 [P] Add a versioning bump per PR: PR 1 minor bump (new public methods), PR 2 minor bump, PR 3 minor bump.
- [ ] T091 [P] Verify `pyproject.toml` `[project.optional-dependencies]` includes all three extras (`replay-mining`, `replay-ml`, `replay-all`) after PR 3.
- [ ] T092 Schedule a quarterly diff between the vendored `_internal/replays/rrweb_analyzer.py` and the upstream `analytics/backend/replays/rrweb_analyzer.py`. Document the cadence in the module docstring (`# Next upstream diff due: YYYY-Q$N`) and create a recurring reminder in the team's project tracker.
- [ ] T093 Update `CLAUDE.md`'s "Active Technologies" section if needed after each PR lands (the SPECKIT marker already points at this plan; the technology summary line was added during `/speckit-plan`).
- [ ] T094 Final security review: run the `grep` audit from [quickstart.md "Security verification"](quickstart.md#security-verification) against every transcript produced during integration testing. No `Signature=`, `URLPrefix=`, or `Expires=` substrings outside the explicit `--reveal-signed-urls` opt-in path.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup. **Blocks all user stories.**
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)**: depends on US1 (analyzer modifies `Replay` from US1; bundle is a collection of US1's `Replay` instances).
- **US3 CLI**: basic commands (list/events/sign/fetch) depend on US1; analyze/for-user commands depend on US2.
- **US4 (Phase 5)**: depends on US2 (`event_log()` and `cluster()` operate on the bundle).
- **Polish (Phase 6)**: ongoing across PRs.

### Within each user story

- Tests MUST be written and FAIL before implementation lands.
- Models / types before services.
- Services before workspace methods.
- Workspace methods before CLI commands.
- `just check` MUST pass at the end of each story before opening the PR.

### Parallel opportunities

- All Foundational tasks marked [P] (T004, T006, T008, T009) can run in parallel.
- Within US1: all unit-test tasks T011–T017 are [P]; the implementation tasks T020–T028 mostly sequential (types → service → workspace methods); the CLI bridge tasks T033–T038 are sequential within themselves but the test-writing T033 is [P] with implementation work happening in parallel by a CLI developer once the Phase 1 Workspace methods (T024–T028) land.
- Within US2: fixture and label test tasks T043–T048 are [P]; T049–T052 are [P]; implementation T054–T058 are mostly [P] (different files); T059–T063 sequential (bundle type → workspace methods that return bundles).
- Within US4: T074–T076 [P]; T078–T080 [P]; T081–T082 sequential (both modify `types.py`).
- PR 1 and PR 3 cannot run in parallel because PR 3 depends on PR 2 which depends on PR 1. PR 1 and the Phase 6 polish for PR 1 can run in parallel by separate developers.

### Cross-PR sequencing

- PR 1 (T001–T042) ships first.
- PR 2 (T043–T073) ships after PR 1 merges.
- PR 3 (T074–T086) ships after PR 2 merges AND user demand materializes.
- Phase 6 polish runs alongside each PR.

---

## Parallel example: User Story 1 tests

```bash
# Launch all US1 unit tests in parallel (5 tasks, 5 files):
Task: "Add unit test file tests/unit/test_types_replay_summary.py"   # T011
Task: "Add unit test file tests/unit/test_types_signed_replay.py"    # T012
Task: "Add unit test file tests/unit/test_types_replay_event.py"     # T013
Task: "Add unit test file tests/unit/test_types_replay.py"           # T014
Task: "Add unit test file tests/unit/_internal/test_replays_service.py"  # T015
Task: "Add unit test file tests/unit/test_workspace_replays.py"      # T016
Task: "Add PBT test file tests/pbt/test_cdn_walker_pbt.py"           # T017
Task: "Add integration test file tests/integration/test_replays_live.py"  # T018
```

## Parallel example: User Story 2 fixtures + label work

```bash
# Launch fixture and label work in parallel (independent files):
Task: "Create tests/fixtures/rrweb/sample-replay-002.json"           # T043
Task: "Create tests/fixtures/rrweb/sample-replay-003.json"           # T043 (continued)
Task: "Create tests/fixtures/rrweb/sample_bundle_fixture.py"         # T044
Task: "Port tests/unit/test_rrweb_analyzer.py from upstream"         # T045
Task: "Add tests/unit/test_replay_labels.py"                         # T046
Task: "Add tests/pbt/test_replay_labels_pbt.py"                      # T047
```

---

## Implementation strategy

### MVP first (PR 1 only)

1. Phase 1 Setup.
2. Phase 2 Foundational.
3. Phase 3 US1 + Phase 1 CLI bridge (T033–T042 within US3).
4. **STOP and validate**: smoke-test the quickstart §1 (P1 story) against a real fixture project. Audit for credential leaks.
5. Ship PR 1.

This MVP gives users raw rrweb bytes for the rrweb JS player and the basic CLI. Real value delivered without the analyzer.

### Incremental delivery

- PR 1 → users can pull raw bytes, sign URLs, list replays.
- PR 2 → users get normalized actions, bundle analysis, `analyze` and `for-user` CLI commands.
- PR 3 (gated) → users get pm4py process mining and tslearn clustering.

### Parallel team strategy

With multiple developers per PR:

- PR 1: Developer A handles types + service + workspace methods (T020–T028); Developer B handles CLI bridge (T033–T038) once Workspace methods are merged; Developer C handles security audit and quickstart smoke-test (T040, T042).
- PR 2: Developer A handles analyzer port and labels (T055, T057); Developer B handles `ReplayBundle` and aggregators (T058, T059); Developer C handles CLI analyze/for-user (T069) and fixtures (T043, T044).
- PR 3: One developer end-to-end is sufficient (small surface area).

---

## Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps task to user story for traceability.
- Bearer-credential audit is non-negotiable: every PR runs the grep audit before merge.
- Mutation score gate (80%) applies only to the new pure modules (`_internal/services/replays.py`, `_internal/replays/rrweb_analyzer.py`, `_internal/replays/labels.py`, `_internal/replays/aggregators.py`). The workspace methods and CLI commands are coverage-gated (90%) but not mutation-gated.
- The vendored analyzer (T055) is a one-time port. Subsequent upstream changes are picked up via the quarterly diff (T092), not automated sync.
- `Workspace.cluster()` and `event_log()` pm4py path do NOT require US4 to ship — US2 lands them with the fallback path (DataFrame return, ImportError on cluster). US4 only wires the present-pm4py / present-tslearn upgrade paths.
- Stop at any checkpoint (after T042, T073, T086) to validate a PR independently.
- Avoid: cross-PR file conflicts (US2 modifies `Replay` from US1 — coordinate via T056 only after T020 has merged), same-file parallel work (e.g. `types.py` edits in T020 vs T059), bypassing tests-first (every implementation task lists the test task it MUST follow).
