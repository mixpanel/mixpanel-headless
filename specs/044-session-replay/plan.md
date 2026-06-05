# Implementation Plan: Session Replay for `mixpanel-headless`

**Branch**: `044-session-replay` (proposed) | **Date**: 2026-05-27 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/044-session-replay/spec.md`
**Source design**: [`context/session-replay-plan.md`](../../context/session-replay-plan.md) — the original detailed design draft. This plan distills it into spec-kit shape; the source remains authoritative for fine-grained file layout, vendoring decisions, and PR-shape rationale.
**PR strategy**: Phased. Phase 1 (discovery + signed CDN access + `Replay`) ships as one PR. Phase 2 (vendored rrweb analyzer + `ReplayBundle`) ships as a second PR. Each phase is independently shippable and adds value on its own.

## Summary

Add a first-class session replay surface to `mixpanel-headless` covering discovery via the existing Insights query path, signed CDN access to raw rrweb recording files via Mixpanel's `/app/projects/<id>/replays/sign[/bulk]` endpoints (used today by Mixpanel's own MCP server), a vendored rrweb analyzer that converts raw event streams into normalized user-action timelines, and two typed result classes (`Replay` for single sessions, `ReplayBundle` for collections) that mirror the existing `FlowQueryResult` idiom with long-format pandas DataFrames keyed by `replay_id`. A new `mp replays` CLI group exposes `list`, `events`, `sign`, `fetch`, `analyze`, and `for-user` commands. (The graph/tree/path-mining projections from the original draft were cut after live QA showed they produce empty or degenerate output on real SPA sessions.)

The technical approach treats a replay as an event log (timestamped activities keyed by a case ID) so the data shape aligns with every PyData library that touches sequential data (`pandas`, `duckdb`). `ReplayBundle` is the high-leverage type; a `Replay` is conceptually a bundle of size 1, and the API treats them that way.

Estimated scope: ~2,700 LoC across ~23 new or modified files. Two phases. Total ~3 weeks of focused work.

## Technical Context

**Language/Version**: Python 3.10+ (mypy --strict compliant)

**Primary Dependencies**:
- Reused: `httpx` (HTTP client and CDN fetcher), Pydantic v2 (validation), pandas (DataFrames), Typer (CLI), Rich (output), Hypothesis (PBT), mutmut (mutation testing).
- New (vendored, no third-party install): rrweb analyzer ported from `analytics/backend/replays/rrweb_analyzer.py` (~600 LoC, pure stdlib).

**Storage**: None. Signed URLs are time-bounded bearer credentials; the library does not persist them. No new disk artifacts beyond what `httpx` already handles in-process.

**Testing**: pytest (unit + integration); Hypothesis PBT for label-fn stability, file-numbering walker, and DataFrame projection invariants; mutmut on the vendored analyzer + new query builders + labels module. Integration tests gated on a known replay-bearing fixture project (Mixpanel Labs internal project ID `3713224` or equivalent).

**Target Platform**: Cross-platform (macOS, Linux, Windows). No platform-specific code paths. Filesystem permissions inherit the existing 042 redesign (`0o600` token files, `0o700` parent dirs) — the replay feature adds no new on-disk credential surface.

**Project Type**: Library + CLI feature addition. No plugin changes; the `mixpanel-plugin/` skills already call into `Workspace` and pick up the new methods automatically.

**Performance Goals**:
- `list_replays(distinct_id, from_date, to_date)` ≤ 1 round trip for any date range up to 90 days (single Insights call).
- `sign_replays(ids)` ≤ 1 round trip for up to 1000 replay IDs (the MCP server caps at 20 for LLM-context reasons; headless can comfortably batch 100+).
- `fetch_replay(replay_id)` parallel CDN fetch with concurrency 50, terminates on first 404; a 30 MB replay completes in under 5 s on a typical broadband connection.
- `stream_replay(replay_id)` first event yielded within 1 s of call (signed URL + first file fetch).
- `Replay.actions_df` materialization ≤ 200 ms for a 30 MB replay.
- `ReplayBundle.actions_df` materialization ≤ 100 ms per replay in the bundle (linear scaling, cached after first access).

**Constraints**:
- mypy --strict, zero `Any` lacking explicit justification.
- ruff format / check passes with zero violations.
- 90% test coverage minimum (CI fails below).
- 80% mutation score on `_internal/services/replays.py`, `_internal/replays/rrweb_analyzer.py`, `replay_labels.py`, `_internal/replays/aggregators.py`.
- Signed-URL `query_string` MUST NOT appear in any log line at any level. `__repr__` of `SignedReplay` MUST mask the field. Reviewer audit: grep transcript for any leak.
- Vendored analyzer MUST remain pure-Python (no native deps) so it works in every environment `mixpanel-headless` already supports.

**Scale/Scope**:
- Phase 1: ~5 new files + 4 modified, ~1,200 LoC including tests.
- Phase 2: ~4 new files (vendored analyzer, labels, aggregators, ReplayBundle expansion), ~1,500 LoC.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Evidence |
|-----------|--------|----------|
| I. Library-First | PASS | Every `mp replays` command delegates to a public `Workspace` method (`list_replays`, `sign_replays`, `fetch_replay`, `stream_replay`, `fetch_replays`, `replays_for_user`, `analyze_replay`, `events_for_replay`, `events_for_replays`). CLI does I/O formatting only. All public methods have type hints and docstrings. |
| II. Agent-Native | PASS | No interactive prompts on any default path. All output is structured (JSON / JSONL / table) and pipe-composable. The vendored analyzer produces deterministic markdown; no LLM-call required. The `--reveal-signed-urls` flag is the only opt-in, never required. |
| III. Context Window Efficiency | PASS | `ReplaySummary` is a lightweight discovery handle (no bytes). `stream_replay` keeps memory bounded for large recordings. `Replay.summary_markdown` is the LLM-context-friendly projection; full DataFrames are opt-in. The bundle-level convenience aggregations (`top_clicks`, `rage_clicks`, ...) return precise answers rather than raw streams. |
| IV. Two Data Paths | PASS | Live query path: `Workspace.query()` for discovery + signed-URL fetch. Local analysis path: `Replay`/`ReplayBundle` DataFrames feed directly into DuckDB via `duckdb.from_df(bundle.actions_df)`. Both paths share the authenticated `Workspace`. |
| V. Explicit Over Implicit | PASS | `re_sign_on_expiry` defaults to True but is overridable. `max_files` defaults to 500 but is configurable. `retention_days=None` triggers discovery; explicit value bypasses it. `include_mixpanel_events=False` by default — opt-in to the extra round trip. No silent retries on 404 (end-of-recording sentinel). |
| VI. Unix Philosophy | PASS | `mp replays fetch -o file.json` writes raw rrweb JSON suitable for piping into the rrweb JS player or jq. `mp replays analyze --format json` emits structured action lists for downstream tools. `--reveal-signed-urls` emits the credential to stdout AND a warning to stderr. Exit codes follow the existing `ExitCode` enum. |
| VII. Secure by Default | PASS WITH JUSTIFICATION | Signed URLs are bearer credentials. `SignedReplay.__repr__` and `__str__` mask the `query_string`. The library NEVER logs the credential. The `SESSION_RECORDING_SENSITIVE_DATA` 403 maps to a distinct `SessionReplayAccessError` with actionable details. The CLI `--reveal-signed-urls` flag is the single opt-in path to credential disclosure; it emits a stderr warning every time. See [Complexity Tracking](#complexity-tracking) for the `to_dict()` serialization justification (full credential preserved but flagged). |

**Gate Result**: PASS. Principle VII needs the explicit `to_dict()` justification because we preserve the full credential on serialization (the user chose to serialize; we cannot meaningfully prevent it once `.query_string` is accessed). No actual violations.

## Project Structure

### Documentation (this feature)

```text
specs/044-session-replay/
├── plan.md                       # This file
├── spec.md                       # Feature specification (created by /speckit-specify)
├── research.md                   # Phase 0 output (this command)
├── data-model.md                 # Phase 1 output (this command)
├── quickstart.md                 # Phase 1 output (this command)
├── contracts/                    # Phase 1 output (this command)
│   ├── python-api.md             # Workspace methods + result types + exception hierarchy
│   ├── cli-commands.md           # `mp replays {list, events, sign, fetch, analyze, for-user}`
│   └── error-messages.md         # Stable error catalog (sensitive-data 403, signed-URL expiry, missing extras)
├── checklists/
│   └── requirements.md           # Spec quality checklist (created by /speckit-specify)
└── tasks.md                      # Phase 2 output (via /speckit-tasks)
```

### Source Code (repository root)

```text
src/mixpanel_headless/
├── workspace.py                                # MODIFIED (Phase 1: +4 methods; Phase 2: +5 methods)
│                                               # Phase 1: list_replays, events_for_replay,
│                                               #          events_for_replays, sign_replay,
│                                               #          sign_replays, fetch_replay, stream_replay
│                                               # Phase 2: fetch_replays, replays_for_user, analyze_replay
├── types.py                                    # MODIFIED (Phase 1: ReplaySummary, SignedReplay, ReplayEvent, Replay;
│                                               #            Phase 2: UserAction, ReplayBundle)
├── exceptions.py                               # MODIFIED (Phase 1) — add SessionReplayError,
│                                               # SessionReplayAccessError, SignedURLExpiredError, ReplayNotFoundError
├── __init__.py                                 # MODIFIED — add 10 new public exports
├── _internal/
│   ├── services/
│   │   └── replays.py                          # NEW (Phase 1) — ReplaysService: orchestrates sign + fetch + discovery
│   ├── api_client.py                           # MODIFIED (Phase 1) — add sign_replays() method;
│   │                                           # wire the SESSION_RECORDING_SENSITIVE_DATA 403 mapping
│   └── replays/                                # NEW SUBPACKAGE (Phase 2)
│       ├── __init__.py
│       ├── rrweb_analyzer.py                   # NEW (Phase 2) — VENDORED from analytics/backend/replays/rrweb_analyzer.py
│       │                                       # DOMTracker + EventAnalyzer + MarkdownReporter, pure stdlib
│       ├── labels.py                           # NEW (Phase 2) — default_label_fn, selector_label_fn, url_normalizer
│       └── aggregators.py                      # NEW (Phase 2) — top_clicks, rage_clicks,
│                                               # long_pauses, error_sessions, real_clicks
└── cli/
    ├── main.py                                 # MODIFIED (Phase 1) — register replays_app in _register_commands()
    └── commands/
        └── replays.py                          # NEW (Phase 1 core + Phase 2 analyze/for-user) — Typer commands

tests/
├── unit/
│   ├── test_replays_service.py                 # NEW (Phase 1) — mocked HTTP, request shape, error mapping
│   ├── test_types_replay_summary.py            # NEW (Phase 1) — dataclass shape, from-Insights conversion
│   ├── test_types_signed_replay.py             # NEW (Phase 1) — __repr__ masking, expires_at, is_expired
│   ├── test_workspace_replays.py               # NEW (Phase 1) — Workspace method tests (mocked service)
│   ├── test_rrweb_analyzer.py                  # PORTED (Phase 2) from analytics/backend/replays/test_rrweb_analyzer.py
│   ├── test_replay_labels.py                   # NEW (Phase 2) — default + selector label stability
│   ├── test_types_replay.py                    # NEW (Phase 2) — Replay DataFrame projections, mode-aware df
│   └── test_types_replay_bundle.py             # NEW (Phase 2) — ReplayBundle aggregations, filters, lazy props
├── pbt/
│   ├── test_cdn_walker_pbt.py                  # NEW (Phase 1) — file-numbering walker invariants
│   ├── test_replay_labels_pbt.py               # NEW (Phase 2) — label_fn stability across DOM perturbations
│   └── test_types_replay_bundle_pbt.py         # NEW (Phase 2) — DataFrame projection invariants
├── integration/
│   └── test_replays_live.py                    # NEW (Phase 1) — @pytest.mark.live: list / sign / fetch a known replay
└── fixtures/
    └── rrweb/
        ├── sample-replay-001.json              # NEW (Phase 1) — login + one click + navigation
        ├── sample-replay-002.json              # NEW (Phase 2) — multi-page, mixed interactions
        ├── sample-replay-003.json              # NEW (Phase 2) — console errors, rage clicks, dead clicks, long pauses
        └── sample-bundle-fixture.py            # NEW (Phase 2) — builds a deterministic 10-replay ReplayBundle
```

**Structure Decision**: Single-project Python library layout (Option 1). The feature extends three existing surfaces (`workspace.py` Python facade, `types.py` result classes, `cli/commands/` Typer commands) and adds one new internal subpackage (`_internal/replays/`) for the vendored analyzer, label functions, and aggregators. No new top-level layout; all changes nest under existing module roots.

## Complexity Tracking

> Fill ONLY if Constitution Check has violations that must be justified

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| `SignedReplay.to_dict()` preserves the full bearer credential | Round-tripping a `SignedReplay` through serialization (e.g. caching to disk for testing, sending across an IPC boundary, pickling for a multiprocessing worker pool) requires the credential to survive. Users opting into serialization have already chosen to accept the disclosure surface; redacting in `to_dict()` would silently break the contract that `from_dict(to_dict(x)) == x`. | Drop the credential on serialization: breaks round-trip semantics and forces every caller who legitimately needs to persist a signed URL to re-sign. Forcing them to re-sign is a worse outcome than including a top-level `_warning` marker noting the bearer nature. |
| Vendored analyzer (~600 LoC ports from analytics monorepo into `_internal/replays/rrweb_analyzer.py`) | The analyzer is the load-bearing piece for `Replay.actions` and `ReplayBundle.actions_df`. Pulling it in as a runtime dependency on the analytics monorepo is impossible (private repo, cross-repo coupling). Pulling it in as a separate PyPI package would create a 3-way release dance with no clear owner. | Direct dependency on the analytics monorepo: rejected (private). Separate PyPI package: rejected (release-coordination cost). Re-implement from scratch: rejected (duplicate work, drift risk). Vendoring with a documented source link and periodic diff is the standard pattern for this kind of shared internal logic. |
| Phase 2 ships analyzer + ReplayBundle in one PR (~1,500 LoC) instead of splitting them | The analyzer is what populates `Replay.actions`, which is what `ReplayBundle.actions_df` reads. Shipping them separately means either the analyzer ships first with no consumer (dead code in the merged branch) OR the bundle ships first with empty action streams (incorrect / misleading API). | Two separate PRs: the dependency chain forces a coupled review anyway; the cognitive cost of splitting outweighs the per-PR review cost. The PRs would be ~700 LoC and ~800 LoC, neither small enough to warrant the split. |
