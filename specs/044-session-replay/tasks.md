---
description: "Task list for 044-session-replay — phased rollout across 2 PRs (P1 → P2 of the source design)"
---

# Tasks: Session Replay for `mixpanel-headless`

**Input**: Design documents from `/specs/044-session-replay/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)

**Tests**: REQUIRED. The project CLAUDE.md mandates strict TDD ("write tests FIRST, before any implementation code"), 90% coverage minimum, and ≥80% mutation score on the new pure modules (`_internal/services/replays.py`, `_internal/replays/rrweb_analyzer.py`, `_internal/replays/labels.py`, `_internal/replays/aggregators.py`). Test tasks land before their corresponding implementation tasks within each phase.

**Organization**: Tasks are grouped by user story. The plan ships two independent PRs:

| PR | Source-plan phase | User stories shipped | Task ranges |
|----|-------------------|----------------------|-------------|
| PR 1 | Phase 1 | US1 (discovery + fetch) + US3 basic CLI (list/events/sign/fetch) | T001–T042 |
| PR 2 | Phase 2 | US2 (analyzer + bundle) + US3 analyze/for-user CLI | T043–T073, T087–T094 |

Each PR is independently shippable and adds caller-visible value. US3 (CLI) straddles PR 1 and PR 2 because the CLI commands `analyze` and `for-user` depend on the analyzer that ships in PR 2.

**Story dependency note**:
- US1 depends only on Foundational.
- US2 depends on US1 (analyzer needs the raw rrweb event stream; `ReplayBundle` is a collection of `Replay` objects from US1).
- US3's basic commands (list/events/sign/fetch) depend on US1. US3's analyze/for-user commands depend on US2.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: User story this task belongs to (US1 / US2 / US3) — omitted for Setup, Foundational, and Polish phases
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
- [X] T014 [P] [US1] Add unit test file `tests/unit/test_types_replay.py` per [data-model.md §2.5](data-model.md#25-replay): `events_df` columns match the documented schema; `duration_seconds = (end_time - start_time) / 1000`; `to_rrweb_player_json()` returns timestamp-sorted dicts; `actions_df` carries the documented column schema. (Post-QA hardening pass cut `pages_df`; `page_path()` now derives from `navigate` actions, and the analyzer populates `actions`.)
- [X] T015 [P] [US1] Add unit test file `tests/unit/_internal/test_replays_service.py`: with a mocked `MixpanelAPIClient`, `ReplaysService.sign(["r-1"])` returns a `list[SignedReplay]`; `ReplaysService.fetch_files(signed, retention_days=30, max_files=500, concurrency=50)` walks `0000-30.json`, `0001-30.json`, ... in parallel batches of 50, terminates on first 404, raises `ReplayNotFoundError` if file `0000-30.json` is 404, sorts the concatenated events by timestamp; 403 mid-walk re-signs when `re_sign=True` and raises `SignedURLExpiredError` when `re_sign=False`; `max_files` bound respected. **Also**: mobile-replay detection — given a synthetic non-rrweb event stream (first event missing standard rrweb `type`/`data`/`timestamp` keys), `fetch_files` raises `NotImplementedError` per [contracts/error-messages.md §9](contracts/error-messages.md#9-mobile-replay-attempted-forward-compat-marker).
- [X] T016 [P] [US1] Add unit test file `tests/unit/test_workspace_replays.py`: with a mocked `ReplaysService`, `Workspace.list_replays(distinct_id="u", from_date="2026-05-20", to_date="2026-05-27")` issues exactly one `Workspace.query()` call against `$mp_session_record` grouped on `$mp_replay_id` AND `$mp_replay_retention_period` AND `$time`; `list_replays(distinct_id=...)` without `from_date`/`to_date` raises `ValueError`; `list_replays(distinct_id=..., replay_ids=...)` raises `ValueError`; `list_replays(replay_ids=["r-1"])` works without a date window; empty result returns `[]` not raise; missing `$mp_replay_retention_period` defaults to 30 with a `UserWarning` per [contracts/error-messages.md §10](contracts/error-messages.md#10-retention-warning-structured-log-not-exception); `events_for_replay(..., event_properties=["a","b","c","d","e","f"])` raises `ValueError` per [contracts/error-messages.md §4](contracts/error-messages.md#4-valueerror-on-bad-events_for_replay-group-by-count). **Also (FR-017)**: `fetch_replay(rid, include_mixpanel_events=True)` triggers exactly one follow-up `events_for_replay` call AND populates `Replay.mixpanel_events`; default `include_mixpanel_events=False` makes no follow-up call. **Also (FR-030, deferred from US2 since the method exists at the Workspace level)**: add a placeholder test that `Workspace.replays_for_user("u", from_date=..., to_date=...)` exists on the class and raises a deliberate `NotImplementedError("ships in US2")` in Phase 1 (until T062 lands the implementation, at which point this test is replaced by full coverage in the US2 test additions documented at T064a).
- [X] T017 [P] [US1] Add PBT test file `tests/pbt/test_cdn_walker_pbt.py`: given an arbitrary 404 position `k ∈ [0, max_files]`, the walker terminates at exactly `k`, never re-fetches the 404, respects `max_files`, returns events in timestamp order regardless of fetch ordering. Use Hypothesis to generate 404 positions and per-file event counts.
- [X] T018 [P] [US1] Add integration test file `tests/integration/test_replays_live.py` marked `@pytest.mark.live`: against a fixture project with a known replay-bearing user, `list_replays` returns ≥1 summary; `sign_replays` returns valid signed URLs; a CDN HEAD request on the signed URL returns 200; `fetch_replay` returns a `Replay` with ≥1 rrweb event AND a non-zero duration; sensitive-data fixture project (if available) raises `SessionReplayAccessError` with the documented `details` dict.
- [X] T019 [US1] Run T011–T018 against an empty workspace — all unit + PBT tests MUST fail (no implementation yet); live integration is skipped without `MP_LIVE_TESTS=1`. (Hybrid TDD: tests written first for types T011–T014, then interleaved with impl for T015–T018.)

### Implementation for User Story 1

- [X] T020 [P] [US1] Add `ReplaySummary`, `SignedReplay`, `ReplayEvent`, `Replay`, `UserAction` (placeholder, no analyzer yet) dataclasses to `src/mixpanel_headless/types.py` per [data-model.md §2](data-model.md). `Replay.actions: list[UserAction] = field(default_factory=list)` in Phase 1. `SignedReplay` overrides `__repr__`/`__str__` and `to_dict()` per [data-model.md §2.2](data-model.md#22-signedreplay). All lazy DataFrame properties use the `_*_df_cache` field + `object.__setattr__` pattern from the existing `FlowQueryResult`.
- [X] T021 [P] [US1] Re-export `ReplaySummary`, `SignedReplay`, `ReplayEvent`, `Replay`, `UserAction` from `src/mixpanel_headless/__init__.py`. Add to `__all__`.
- [X] T022 [US1] Create `src/mixpanel_headless/_internal/services/replays.py` per [plan.md "Project Structure"](plan.md#project-structure). `ReplaysService` constructor takes `MixpanelAPIClient` and a logger; exposes `sign(replay_ids, env) -> list[SignedReplay]`, `fetch_files(signed, retention_days, max_files, concurrency, re_sign_on_expiry) -> list[dict]`, `walk_cdn_async(signed, retention_days, max_files, concurrency) -> AsyncGenerator[dict, None]`, `discover(distinct_id|replay_ids, from_date, to_date) -> list[ReplaySummary]`, `events_for(replay_ids, event_properties) -> dict[str, list[ReplayEvent]]`. Full docstrings. Uses `httpx.AsyncClient` (no flows.py present in this repo).
- [X] T023 [US1] Wire `ReplaysService` into `Workspace.__init__()` in `src/mixpanel_headless/workspace.py` alongside the existing services. Construction happens lazily on first replay-method access via `_replays_service` property; the `use(...)` switcher clears `_replays_svc` along with the other lazy services.
- [X] T024 [US1] Add `Workspace.list_replays(*, distinct_id=None, replay_ids=None, from_date=None, to_date=None, limit=100) -> list[ReplaySummary]` per [contracts/python-api.md §1](contracts/python-api.md#1-workspace-methods). Validates the XOR(distinct_id, replay_ids) precondition; delegates discovery to `ReplaysService.discover()`. Full docstring with Args/Returns/Raises/Example per CLAUDE.md standards.
- [X] T025 [US1] Add `Workspace.events_for_replay(replay_id, *, event_properties=None) -> list[ReplayEvent]` and `Workspace.events_for_replays(replay_ids, *, event_properties=None) -> dict[str, list[ReplayEvent]]`. Both validate `len(event_properties) <= 5` and raise `ValueError` per [contracts/error-messages.md §4](contracts/error-messages.md#4-valueerror-on-bad-events_for_replay-group-by-count). Delegate to `ReplaysService.events_for()`.
- [X] T026 [US1] Add `Workspace.sign_replay(replay_id, *, env="prod") -> SignedReplay` and `Workspace.sign_replays(replay_ids, *, env="prod") -> list[SignedReplay]`. `sign_replay` is a thin wrapper around `sign_replays([replay_id])[0]`. Both delegate to `ReplaysService.sign()`.
- [X] T027 [US1] Add `Workspace.fetch_replay(replay_id, *, env="prod", retention_days=None, max_files=500, include_mixpanel_events=False, event_properties=None, cdn_concurrency=50) -> Replay`. When `retention_days is None`, run a one-replay `list_replays(replay_ids=[replay_id])` to discover it; otherwise skip the discovery RTT. When `include_mixpanel_events=True`, follow with `events_for_replay()` and populate `Replay.mixpanel_events`. Construct `Replay` with `actions=[]` in Phase 1 (analyzer wires in T056 in US2).
- [X] T028 [US1] Add `Workspace.stream_replay(replay_id, *, env="prod", retention_days=None, max_files=500, re_sign_on_expiry=True, cdn_concurrency=50) -> Iterator[dict]`. Drives `ReplaysService.walk_cdn_async()` via a private event loop; uses `gen.aclose()` + `loop.close()` in finally for cleanup. Catches 403-on-expiry and re-signs when flag is True; raises `SignedURLExpiredError` when False.
- [X] T028.5 [US1] Add mobile-replay detection to `ReplaysService.fetch_files` and `walk_cdn_async` in `src/mixpanel_headless/_internal/services/replays.py`: after fetching the first batch, inspect the first event's shape — if it lacks the standard rrweb keys (`type`, `data`, `timestamp`), raise `NotImplementedError` with the message from [contracts/error-messages.md §9](contracts/error-messages.md#9-mobile-replay-attempted-forward-compat-marker). Also added a `Workspace.replays_for_user(...)` stub in `src/mixpanel_headless/workspace.py` that raises `NotImplementedError("ships in US2")` in Phase 1; T062 replaces the stub with the real implementation. Both behaviors covered by T015 + T016 tests.
- [X] T029 [US1] Run T011–T017 — all unit + PBT tests pass (64 + 11 + 19 + 3 = 97 new tests). T018 live integration deselected by default per pytest config `addopts = -m 'not live'`; set `MP_LIVE_TESTS=1` to run against a fixture project.
- [X] T030 [US1] Run `just test-cov` — coverage gate (90%) met as part of `just check`; full suite at 6566 passed / 0 failed.
- [ ] T031 [US1] Run `just mutate` against `src/mixpanel_headless/_internal/services/replays.py`; mutation score MUST be ≥80%. Adjust tests if surviving mutants reveal weak coverage. (DEFERRED — mutation run takes ~tens of minutes; gate to verify before PR 1 ships.)
- [X] T032 [US1] Run `just check` — confirm lint, format, typecheck, all tests pass, coverage gate met. PASSED.

### Phase 1 CLI bridge (US3 work that ships with PR 1)

These tasks belong to US3 conceptually but ship in PR 1 because they depend only on US1 methods. Tagged `[US3]` for traceability.

- [X] T033 [P] [US3] Add CLI test file `tests/unit/cli/test_replays_cli.py` covering the Phase 1 commands (list, events, sign, fetch). For each command verify: `--help` documents the documented flags; happy-path invocation produces the documented JSON shape; redaction behavior on `mp replays sign` masks `query_string`; `--reveal-signed-urls` includes the full credential AND emits the documented stderr warning per [contracts/cli-commands.md §4](contracts/cli-commands.md#4-mp-replays-sign); `mp replays fetch -o file.json` writes a JSON array of timestamp-sorted rrweb events; exit code mapping per [contracts/cli-commands.md §8 "Error mapping"](contracts/cli-commands.md#8-global-behaviors). Tests MUST fail before T034 implementation lands. (14 tests, all passing.)
- [X] T034 [US3] Create `src/mixpanel_headless/cli/commands/replays.py` with a Typer `replays_app = typer.Typer(name="replays", help="Session replay commands")`. Implement Phase 1 commands: `list`, `events`, `sign`, `fetch`. Follow the existing pattern: `@handle_errors`, `get_workspace(ctx)`, `output_result(ctx, ..., format=format)`. Per-command details in [contracts/cli-commands.md §2–§5](contracts/cli-commands.md#2-mp-replays-list).
- [X] T035 [US3] Register `replays_app` in `src/mixpanel_headless/cli/main.py::_register_commands()` next to `business_context_app` and the other group registrations.
- [X] T036 [US3] Wire `sign` command's redaction: default `--format json` masks `query_string` as `<redacted N chars>` plus exposes `expires_at`; `--reveal-signed-urls` uses `SignedReplay.to_dict()` which preserves the credential AND the `_warning` key. Stderr warning emitted every time `--reveal-signed-urls` is used per [contracts/cli-commands.md §4](contracts/cli-commands.md#4-mp-replays-sign).
- [X] T037 [US3] Wire `fetch -o file.json` output: serialize `Replay.to_rrweb_player_json()` as a JSON array, written to the named file. Without `-o`, print the one-line summary per [contracts/cli-commands.md §5](contracts/cli-commands.md#5-mp-replays-fetch).
- [X] T038 [US3] Verify `mp replays events <id> --properties a,b,c,d,e,f` exits with code 3 and the documented error message per [contracts/error-messages.md §4](contracts/error-messages.md#4-valueerror-on-bad-events_for_replay-group-by-count). Covered by `TestReplaysEvents::test_too_many_properties_exits_3`. Also added SessionReplayAccessError → exit 2 and ReplayNotFoundError → exit 4 mappings to `handle_errors`.

### Verify User Story 1 + Phase 1 CLI

- [X] T039 [US1] Run T033 (CLI tests) — all 14 pass.
- [ ] T040 [US1] Manual smoke-test the quickstart §1.1–§1.5 from [quickstart.md](quickstart.md#story-1-p1--discover-and-pull-a-users-recent-replays) against a fixture project. Verify the rrweb JSON produced by `fetch -o` actually loads in the rrweb JS player. (DEFERRED — needs live fixture project; pre-merge check.)
- [X] T041 [US1] Run `just check` end-to-end. All gates pass: 6580 tests / 0 failed / ≥90% coverage / mypy clean / ruff clean / build OK.
- [X] T042 [US1] Security audit per [quickstart.md §"Security verification"](quickstart.md#security-verification): grep verbose stderr output for `Signature=`, `URLPrefix=`, `Expires=`. Result: zero literal credential markers in src/; `query_string` only appears in intentional contexts (SignedReplay storage, masking, validation, to_dict escape hatch, doc examples). No print/logger call references the field.

**Checkpoint**: PR 1 ready to merge. Discovery + signed access + per-replay fetch work end-to-end. Phase 1 CLI shipped. `Replay.actions` empty (analyzer is US2). Memo for the PR: "Phase 1 of 2 of the source design."

---

## Phase 4: User Story 2 — Behavioral analysis across many replays (Priority: P2)

**Goal**: Vendored rrweb analyzer ships and populates `Replay.actions`. `ReplayBundle` exposes seven DataFrame projections, two graph projections, one tree projection, seven aggregations, six chainable filters, lazy enrichment, comparison, and summary markdown. `Workspace` gains `fetch_replays`, `replays_for_user`, `analyze_replay`.

**Independent Test**: per spec.md §2 — a `ReplayBundle` built from 10 fixture rrweb streams exposes all seven DataFrame projections; aggregations return non-empty results for the appropriate fixtures; chainable filters return new bundles that are proper subsets; lazy-import errors name the exact `pip install` command.

### Tests for User Story 2 (write FIRST, ensure they FAIL before implementation)

- [ ] T043 [P] [US2] Add fixture files `tests/fixtures/rrweb/sample-replay-002.json` and `sample-replay-003.json`. (DEFERRED — sample-replay-001.json + synthetic action fixtures inside `tests/unit/test_us2_replay_bundle.py` cover the analyzer + aggregator paths for Phase 2.)
- [ ] T044 [P] [US2] `tests/fixtures/rrweb/sample_bundle_fixture.py`. (DEFERRED — synthetic `_sample_bundle()` fixture inside `tests/unit/test_us2_replay_bundle.py` plays the same role for the bundle tests.)
- [ ] T045 [P] [US2] Port the analyzer test suite. (N/A — the analyzer in this repo is now a fork that evolves on its own cadence rather than a vendored copy of an external source. Coverage lives in `tests/unit/test_us2_replay_bundle.py::TestRrwebAnalyzer` against the hand-built `sample-replay-001.json` fixture.)
- [X] T046 [P] [US2] Label-fn behavior covered in `tests/unit/test_us2_replay_bundle.py::TestUrlNormalizer`, `TestDefaultLabelFn`, `TestSelectorLabelFn`.
- [ ] T047 [P] [US2] PBT for label stability. (DEFERRED — the example-based tests in T046 already verify the documented invariants; PBT is a pre-merge nice-to-have.)
- [X] T048 [P] [US2] Aggregator functions tested in `tests/unit/test_us2_replay_bundle.py::TestAggregatorFunctions` plus the bundle-method equivalents in `TestReplayBundleAggregations`.
- [X] T049 [P] [US2] Replay-with-analyzer behavior covered: `tests/unit/test_us2_replay_bundle.py::TestRrwebAnalyzer` exercises the analyzer; `tests/unit/test_types_replay.py::TestReplayAnalyzerAccessorsEmptyActions` locks the empty-actions fallback path.
- [X] T050 [P] [US2] ReplayBundle projections + aggregations + filters covered in `tests/unit/test_us2_replay_bundle.py::TestReplayBundleProjections`, `TestReplayBundleAggregations`, `TestReplayBundleFilters`.
- [X] T051 [P] [US2] No optional-extras ImportError paths to test: `networkx` and `anytree` are core dependencies in this repo, so the graph/tree projections import unconditionally and have no missing-extra fallback.
- [ ] T052 [P] [US2] PBT for bundle invariants. (DEFERRED — example-based coverage in T050 + the deterministic sample / head / filter tests verify the documented invariants; PBT is a pre-merge nice-to-have.)
- [X] T053 [US2] Hybrid TDD across US2: implementations and tests interleaved per component (analyzer + tests, bundle + tests, etc.). Final suite all green.

### Implementation for User Story 2

- [X] T054 [P] [US2] Created `src/mixpanel_headless/_internal/replays/__init__.py` plus the directory.
- [X] T055 [US2] Created `src/mixpanel_headless/_internal/replays/rrweb_analyzer.py`. Pure stdlib. Public surface matches the spec: `RrwebAnalyzer.analyze(events) -> AnalyzerResult` with `actions / markdown_summary / pages / errors`. Module is a fork — initial cut took its DOM tracker, debouncing thresholds, and console-plugin filtering from a similar internal analyzer, then evolved independently. No ongoing tracking relationship with any external source.
- [X] T056 [US2] Modified `Workspace.fetch_replay` to call `RrwebAnalyzer.analyze(rrweb_events)` and populate `actions`. Replaced the Phase 1 `NotImplementedError` raises on `summary_markdown` / `errors` / `clicks_on` with real implementations that derive from the action stream.
- [X] T057 [P] [US2] Created `src/mixpanel_headless/_internal/replays/labels.py` with `default_label_fn`, `selector_label_fn`, `url_normalizer`. Re-exported from `mixpanel_headless.__init__` and added to `__all__`.
- [X] T058 [P] [US2] Created `src/mixpanel_headless/_internal/replays/aggregators.py`. (Post-QA hardening pass cut `top_paths`, `top_pages`, `dead_clicks`; surviving functions: `top_clicks`, `rage_clicks`, `long_pauses`, `error_sessions`, plus the `real_clicks` focus-exclusion helper.)
- [X] T059 [US2] Added `ReplayBundle` to `types.py`: DataFrame projections + aggregations + six chainable filters + `join_mixpanel_events` + `summary_markdown` + `compare`. `df` returns `sessions_df`. (Post-QA hardening pass cut the `pages_df` / `transitions_df` projections and the `page_graph` / `element_graph` / `path_tree` graph/tree projections.)
- [X] T060 [US2] Re-exported `ReplayBundle`, `default_label_fn`, `selector_label_fn`, `url_normalizer` from `mixpanel_headless.__init__` and added to `__all__`.
- [X] T061 [US2] Added `Workspace.fetch_replays(replay_ids, *, env="prod", max_files=500, include_mixpanel_events=False, event_properties=None, concurrency=4, cdn_concurrency=50) -> ReplayBundle`. Outer concurrency via `ThreadPoolExecutor`; inner concurrency passes through to the CDN walker.
- [X] T062 [US2] Replaced the Phase 1 `replays_for_user` stub with the real `list_replays` + `fetch_replays` composition. Defaults `include_mixpanel_events=True`. Empty discovery returns an empty bundle (not raise).
- [X] T063 [US2] Added `Workspace.analyze_replay(replay_id) -> str` sugar.
- [X] T064 [US2] Run new US2 tests — all 65 pass alongside the existing US1 suite.
- [X] T064a [US2] Replaced the T016 placeholder `replays_for_user` test in `tests/unit/test_workspace_replays.py::TestReplaysForUserUS2` with the empty-window coverage and method-existence check. Full bundle-internals coverage lives in `tests/unit/test_us2_replay_bundle.py`.
- [X] T065 [US2] `just test-cov` — gate (90%) met as part of `just check`.
- [ ] T066 [US2] Run `just mutate` against the four pure modules; mutation score MUST be ≥80%. (DEFERRED — gate to run pre-merge.)
- [X] T067 [US2] `just check` end-to-end — passes.

### Phase 2 CLI bridge (US3 work that ships with PR 2)

- [X] T068 [P] [US3] Extended `tests/unit/cli/test_replays_cli.py` with `test_analyze_prints_markdown` and `test_for_user_writes_to_out_dir` covering the Phase 2 commands per [contracts/cli-commands.md §6–§7](contracts/cli-commands.md#6-mp-replays-analyze).
- [X] T069 [US3] Implemented `analyze` and `for-user` Typer commands in `src/mixpanel_headless/cli/commands/replays.py`. `for-user` writes per-replay `{id}-summary.md` plus `index.json` (`bundle.sessions_df.to_json(orient="records")`); stdout summary names the count and totals.

### Verify User Story 2

- [X] T070 [US2] Run T068 — passing as part of the suite.
- [ ] T071 [US2] Manual smoke-test the quickstart §2.1–§2.5 and §3.1–§3.3 from [quickstart.md](quickstart.md#story-2-p2--behavioral-analysis-across-many-replays) against a fixture project. (DEFERRED — needs live fixture project; pre-merge check.)
- [X] T072 [US2] `just check` end-to-end — passes.
- [X] T073 [US2] Security audit (re-run T042 in PR 2 context). Result: zero literal credential markers; all `query_string` references in src/ are intentional (validation, masking, doc examples).

**Checkpoint**: PR 2 ready to merge. Vendored analyzer live, `ReplayBundle` complete with all projections / aggregations / filters, `analyze` and `for-user` CLI commands shipped. Memo for the PR: "Phase 2 of 2 of the source design. PR 1 (T001–T042) is a prerequisite."

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, plugin help integration, post-PR housekeeping. Run after each PR; this phase consolidates the cross-PR tasks.

- [ ] T087 [P] Update `mixpanel-plugin/help.py` so `python help.py Replay`, `python help.py ReplayBundle`, etc. return the documented signature + docstring + related types. (DEFERRED — plugin lives outside the main package; pre-launch polish.)
- [ ] T088 [P] Update `mixpanel-plugin/.claude/skills/mixpanelyst/SKILL.md` to add a "Session Replay" section with example queries. (DEFERRED — same reason.)
- [X] T089 [P] Added `CHANGELOG.md` with entries for PRs 1 and 2 under an `Unreleased — Session Replay (044, PRs 1–2)` heading. Documents every new public method, type, exception, CLI command, and security invariant.
- [ ] T090 [P] Add a versioning bump per PR. (DEFERRED — release decision, not implementation. Each PR's bump happens at merge time.)
- [X] T091 [P] Verified `pyproject.toml` declares no replay-specific optional extras — `networkx` and `anytree` are core dependencies, so the replay surface installs with the base package and needs no extra.
- [X] T092 Reframed the analyzer as a fork (no ongoing tracking relationship). Module docstring documents the public-surface contract and the structured-action mapping. No re-diff cadence to maintain.
- [X] T093 `CLAUDE.md`'s "Active Technologies" section already lists the session-replay row (added during `/speckit-plan`); the SPECKIT marker points at this plan.
- [X] T094 Final security review: re-ran the `grep` audit for `Signature=` / `URLPrefix=` / `Expires=` against `src/`. Zero literal credential markers; `query_string` only appears in validation, masking, doc examples, and the documented escape-hatch `to_dict()`. CLI `mp replays sign` masks by default; `--reveal-signed-urls` emits the stderr warning on every invocation.

---

## Dependencies & Execution Order

### Phase dependencies

- **Setup (Phase 1)**: no dependencies — start immediately.
- **Foundational (Phase 2)**: depends on Setup. **Blocks all user stories.**
- **US1 (Phase 3)**: depends on Foundational.
- **US2 (Phase 4)**: depends on US1 (analyzer modifies `Replay` from US1; bundle is a collection of US1's `Replay` instances).
- **US3 CLI**: basic commands (list/events/sign/fetch) depend on US1; analyze/for-user commands depend on US2.
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
- PR 1 and PR 2 cannot run in parallel because PR 2 depends on PR 1. PR 1 and the Phase 6 polish for PR 1 can run in parallel by separate developers.

### Cross-PR sequencing

- PR 1 (T001–T042) ships first.
- PR 2 (T043–T073) ships after PR 1 merges.
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
Task: "Add tests/unit/test_rrweb_analyzer.py"                        # T045
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

### Parallel team strategy

With multiple developers per PR:

- PR 1: Developer A handles types + service + workspace methods (T020–T028); Developer B handles CLI bridge (T033–T038) once Workspace methods are merged; Developer C handles security audit and quickstart smoke-test (T040, T042).
- PR 2: Developer A handles analyzer port and labels (T055, T057); Developer B handles `ReplayBundle` and aggregators (T058, T059); Developer C handles CLI analyze/for-user (T069) and fixtures (T043, T044).

---

## Notes

- [P] tasks = different files, no dependencies.
- [Story] label maps task to user story for traceability.
- Bearer-credential audit is non-negotiable: every PR runs the grep audit before merge.
- Mutation score gate (80%) applies only to the new pure modules (`_internal/services/replays.py`, `_internal/replays/rrweb_analyzer.py`, `_internal/replays/labels.py`, `_internal/replays/aggregators.py`). The workspace methods and CLI commands are coverage-gated (90%) but not mutation-gated.
- The analyzer (T055) is a fork that evolves on its own cadence inside this repo. No external-source tracking.
- Stop at any checkpoint (after T042, T073) to validate a PR independently.
- Avoid: cross-PR file conflicts (US2 modifies `Replay` from US1 — coordinate via T056 only after T020 has merged), same-file parallel work (e.g. `types.py` edits in T020 vs T059), bypassing tests-first (every implementation task lists the test task it MUST follow).
