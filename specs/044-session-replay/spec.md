# Feature Specification: Session Replay for `mixpanel-headless`

**Feature Branch**: `044-session-replay`
**Created**: 2026-05-27
**Status**: Draft
**Input**: User description: "@context/session-replay-plan.md"

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Discover and pull a user's recent replays (Priority: P1)

A UX researcher, support engineer, or product analyst knows a specific Mixpanel user is having trouble and wants to see what that user did. They use `mixpanel-headless` to discover all of that user's session replays in a date window, sign them for CDN access, and pull the raw recording bytes — either for offline playback in the rrweb JS player or for downstream programmatic analysis.

**Why this priority**: This is the headline use case. Without it the feature delivers nothing. The plan's Phase 1 ships exactly what this story requires (discovery + signed access + per-replay fetch) and is independently shippable.

**Independent Test**: Given a known active `distinct_id` and a 7-day window: `Workspace.list_replays` returns at least one summary; `sign_replay` produces a valid signed URL; the CDN file behind that URL contains rrweb events; `fetch_replay` returns a `Replay` whose raw event list serializes to a JSON file playable directly in `rrweb-player`.

**Acceptance Scenarios**:

1. **Given** a `distinct_id` with 3 recorded sessions in the last 7 days, **When** the caller invokes `list_replays(distinct_id=..., from_date=..., to_date=...)`, **Then** 3 summaries are returned, each carrying the correct retention period read from `$mp_replay_retention_period`.
2. **Given** an active session of recording bytes on the CDN, **When** the caller invokes `fetch_replay(replay_id)`, **Then** a `Replay` is returned with at least one rrweb event and a non-zero duration.
3. **Given** the same fetch via `stream_replay`, **When** the caller iterates the generator, **Then** the first rrweb event is yielded within ~1 second and memory stays bounded to a single in-flight batch.
4. **Given** a project flagged `SESSION_RECORDING_SENSITIVE_DATA` and a caller without sensitive-data access, **When** `sign_replay` is called, **Then** a distinct `SessionReplayAccessError` is raised naming the project and the missing permission — not a generic 403.
5. **Given** a replay missing `$mp_replay_retention_period` (older SDK), **When** discovery runs, **Then** the summary carries `retention_days=30` and a structured warning is emitted naming the replay ID.

---

### User Story 2 — Behavioral analysis across many replays (Priority: P2)

A product manager wants to know where users get stuck in a flow. They pull all replays for users who hit a particular event, then ask the library which click sequences are most common, which clicks were "dead" (no DOM response), which sessions ended in console errors, and which contained rage-click patterns. They iterate by filtering, sampling, and joining Mixpanel events into the bundle without re-fetching.

**Why this priority**: This is the high-leverage type — converting raw recordings into structured behavioral data. Phase 2 of the plan ships exactly this and is independently shippable on top of Phase 1.

**Independent Test**: A `ReplayBundle` built from 10 fixture rrweb streams exposes seven long-format DataFrame projections (sessions, actions, events, mixpanel, pages, elements, transitions). The aggregations (`top_clicks`, `dead_clicks`, `rage_clicks`, `long_pauses`, `error_sessions`) return non-empty results for the appropriate fixtures. The chainable filters (`filter`, `where`, `find_pattern`, `head`, `sample`) return new bundles that are proper subsets of the original, with no shared mutable state.

**Acceptance Scenarios**:

1. **Given** a bundle of 10 replays where one fixture has 5 consecutive clicks on the same button in <1 second, **When** `rage_clicks(threshold=3, window_ms=1000)` is called, **Then** exactly that replay's rage-click rows appear in the result.
2. **Given** a bundle and a user-defined predicate, **When** `filter(predicate)` is called, **Then** a new bundle is returned containing exactly the subset matching the predicate; the original is unchanged.
3. **Given** a bundle with mixed pages, **When** `top_paths(n=5)` is called, **Then** a 5-row DataFrame is returned in frequency order, with stable activity labels following the default labeling convention.
4. **Given** a bundle whose `path_tree`, `page_graph`, or `element_graph` property is accessed without `networkx` / `anytree` installed, **When** the property is touched, **Then** an `ImportError` is raised whose message names the exact `pip install` command required.
5. **Given** two bundles (e.g. converters vs non-converters), **When** `bundle_a.compare(bundle_b)` is called, **Then** a DataFrame is returned showing action-frequency differences across the two bundles.

---

### User Story 3 — Pull a user's activity from the command line (Priority: P2)

A support engineer pasting context into a chat does not want to write Python. They want one `mp` command that takes a user ID and produces a readable markdown summary of recent sessions, or a JSON dump for another tool to consume.

**Why this priority**: CLI sugar is independently valuable — same backend, different surface, different audience. Ships across Phase 1 (basic commands) and Phase 2 (`analyze`, `for-user`).

**Independent Test**: `mp replays list --user X --from D --to D` produces a table. `mp replays analyze REPLAY_ID` produces a markdown timeline on stdout. `mp replays for-user X --from D --to D --include analyze --out-dir DIR` writes per-replay markdown files. `mp replays sign R` redacts the bearer credential by default; `--reveal-signed-urls` includes it but writes a stderr warning every time.

**Acceptance Scenarios**:

1. **Given** an analyst running `mp replays for-user user-42 --from 2026-05-20 --to 2026-05-27 --include analyze --out-dir ./replays/`, **When** the command completes, **Then** per-replay markdown timelines are written to disk and a summary line is printed to stdout.
2. **Given** a request to sign a replay without `--reveal-signed-urls`, **When** the command emits its result in any output format, **Then** the bearer credential is replaced with a redaction marker.
3. **Given** a request to sign with `--reveal-signed-urls`, **When** the command runs, **Then** the bearer credential is printed in full AND a warning is written to stderr stating that signed URLs are bearer credentials.
4. **Given** `mp replays fetch <id> -o file.json`, **When** the command completes, **Then** the output is a JSON array of rrweb events directly compatible with the rrweb JS player (verified by round-tripping into `rrweb-player`).

---

### User Story 4 — Process mining and ML clustering on action streams (Priority: P3)

A behavioral scientist wants to discover the implicit process model in user behavior (the BPMN of how people actually use the product) or cluster sessions by sequence similarity using time-series ML. They install an optional extras group and use the existing bundle without restructuring their analysis pipeline.

**Why this priority**: Specialist. Adds heavy dependencies (`pm4py`, `scipy`, `scikit-learn` via `tslearn`). The plan gates Phase 3 on actual user demand — ship only if pull materializes.

**Independent Test**: With `mixpanel-headless[replay-mining]` installed, `ReplayBundle.event_log()` returns a `pm4py.objects.log.obj.EventLog` directly usable in `pm4py.discover_petri_net_inductive`. Without it, the same call returns a pm4py-compatible DataFrame (with `case:concept:name`, `concept:name`, `time:timestamp` columns) that any pm4py 2.7+ install can consume. With `mixpanel-headless[replay-ml]` installed, `bundle.cluster(n=5)` returns a new bundle whose replays each carry a `cluster_label`.

**Acceptance Scenarios**:

1. **Given** pm4py is NOT installed, **When** the caller invokes `bundle.event_log()`, **Then** a pandas DataFrame is returned with the three XES-canonical columns.
2. **Given** pm4py IS installed, **When** the caller invokes `bundle.event_log()`, **Then** a `pm4py.objects.log.obj.EventLog` is returned, ready for downstream pm4py functions.
3. **Given** a custom `label_fn`, **When** `event_log(label_fn=label_fn)` is called, **Then** every activity label in the output is produced exclusively by that function (no fallback to the default).
4. **Given** `tslearn` is installed AND a bundle of ≥10 replays, **When** `bundle.cluster(n=3, features="actions")` is called, **Then** a new bundle is returned and every replay has a `cluster_label` in `{0, 1, 2}`.

---

### Edge Cases

- **Empty discovery**: `list_replays` returns an empty list, never raises. Caller decides how to surface "no replays found".
- **Missing retention property**: `$mp_replay_retention_period` absent on the discovered event (older SDK) → default to 30 days, emit structured warning naming the replay ID and hinting at SDK upgrade.
- **Signed URL expired mid-stream**: slow `stream_replay` consumer outlives the 5-minute TTL. Default `re_sign_on_expiry=True` re-signs and continues; `False` propagates a clear `SignedURLExpiredError`.
- **404 before `max_files`**: terminate cleanly. 404 is the documented end-of-recording sentinel and MUST NOT be retried.
- **Runaway CDN walker**: `max_files` (default 500) bounds the walker if the 404 sentinel is somehow missed.
- **Sensitive-data 403**: maps to `SessionReplayAccessError` with structured `details = {"project_id": ..., "flag": "SESSION_RECORDING_SENSITIVE_DATA"}` and an actionable message naming the missing permission.
- **Mobile replays**: discoverable (the discovery layer is platform-agnostic), but the bytes / analyzer layers are web-only. The library MUST either skip mobile events the analyzer cannot interpret, or raise a clear "mobile not yet supported" error.
- **Insights group-by limit**: caller asks for more than 5 event_properties on `events_for_replay` → explicit error before the round-trip rather than a Mixpanel API 400.
- **Very large bundle**: `ReplayBundle` is for hundreds, not millions. Documented memory budget (~2 MB per replay in `actions_df`). For 100k+ replays, callers fall back to `stream_replay` + incremental aggregation.
- **Replay ID with zero CDN files**: signed URL points to a prefix where `0000-N.json` is already 404 → raise `ReplayNotFoundError` naming the replay ID (replay aged out of retention or was never recorded).

## Requirements *(mandatory)*

### Functional Requirements

#### Discovery (Phase 1)

- **FR-001**: System MUST let callers list a user's replays by `distinct_id` and date window, returning lightweight summaries.
- **FR-002**: System MUST let callers hydrate summaries for an explicit list of `replay_ids` without requiring a `distinct_id`.
- **FR-003**: Discovery MUST use the existing typed Insights query path (`Workspace.query()`) against `$mp_session_record`, grouping on `$mp_replay_id` and `$mp_replay_retention_period` and reading each replay's `start_time` from a `min` aggregation on `$time` (`math="min", math_property="$time"`) — never the legacy Segmentation API. (A `min($time)` aggregation returns one compact min-timestamp per replay; grouping on `$time` directly would emit a per-second bucket per event and risk the Insights result cap for no benefit.) Discovery MUST parse the raw `result.series` nested dict, not the lossy single-level `result.df` projection.
- **FR-004**: Discovery MUST return an empty list when no replays are found in range. It MUST NOT raise.
- **FR-005**: Per-replay retention MUST be read from `$mp_replay_retention_period` on the discovered event. When missing, retention MUST default to 30 days AND a structured warning MUST be emitted naming the replay ID.
- **FR-006**: System MUST let callers fetch Mixpanel events filtered to a replay's time window — single (`events_for_replay`) AND batched (`events_for_replays`) — optionally with up to 5 event properties as additional group keys.

#### Signed CDN access (Phase 1)

- **FR-007**: System MUST sign one or many replays via the bulk endpoint, returning time-bounded handles (TTL ~5 minutes).
- **FR-008**: Signed-URL handles MUST mask their bearer credential in `repr` AND `str` so default Python logging cannot leak it accidentally.
- **FR-009**: System MUST NOT log the bearer credential at any log level. URL prefix (without query string) MAY be logged at DEBUG level only.
- **FR-010**: A 403 response indicating the `SESSION_RECORDING_SENSITIVE_DATA` project flag MUST raise a distinct `SessionReplayAccessError` carrying structured `details = {"project_id": ..., "flag": "SESSION_RECORDING_SENSITIVE_DATA", "permission_required": "sensitive_data_replay"}` and an actionable user-facing message naming the missing permission. (This is the authoritative location for the exception contract; FR-045 references it.)
- **FR-011**: Serialization paths on signed-URL handles (e.g. `to_dict`) MUST preserve the full credential AND include a top-level warning marker noting the bearer nature.

#### CDN fetching (Phase 1)

- **FR-012**: System MUST fetch a replay by signing then walking the CDN files in parallel batches, concatenating events, sorting by timestamp, and returning a populated `Replay`.
- **FR-013**: System MUST also offer a streaming variant that yields rrweb events one at a time with bounded memory (one batch in flight at a time, batches yielded in timestamp order).
- **FR-014**: The CDN walker MUST terminate cleanly on the first 404 (end-of-recording sentinel) and MUST bound itself by a configurable `max_files` parameter (default 500).
- **FR-015**: The streaming variant MUST optionally re-sign on a 403 indicating signature expiration (default ON). When OFF, it MUST raise a distinct `SignedURLExpiredError`.
- **FR-016**: Per-replay fetch MUST accept an explicit `retention_days` parameter to bypass the discovery round-trip. When absent, it MUST discover retention via the same Insights query path as `list_replays`.
- **FR-017**: Per-replay fetch MUST accept an `include_mixpanel_events` flag that triggers a follow-up Insights query to populate the `Replay.mixpanel_events` list.

#### Single-replay analysis (Phase 1 raw, Phase 2 normalized)

- **FR-018**: `Replay` MUST expose the raw rrweb event list AND lazy pandas DataFrame projections for raw events, normalized actions, Mixpanel events (when populated), and page navigations.
- **FR-019**: `Replay` MUST default its primary DataFrame view to the normalized actions projection.
- **FR-020**: `Replay` MUST expose convenience accessors: `duration_seconds`, `page_path()`, `errors`, `clicks_on(predicate)`, `summary_markdown`, and `to_rrweb_player_json()`.
- **FR-021**: In Phase 1 (no vendored analyzer yet), `Replay.actions` MAY be empty and the analyzer-dependent accessors MAY raise a clear "analyzer not yet shipped, ships in Phase 2" error.

#### Cross-session analysis (Phase 2)

- **FR-022**: System MUST provide a `ReplayBundle` collection type exposing long-format DataFrame projections: `sessions_df`, `actions_df`, `events_df`, `mixpanel_df`, `pages_df`, `elements_df`, `transitions_df`.
- **FR-023**: `ReplayBundle.df` MUST default to `sessions_df` (one row per replay).
- **FR-024**: `ReplayBundle` MUST expose graph projections `page_graph` and `element_graph` (using `networkx`) and `path_tree` (using `anytree`), lazily imported inside the property body — never at module import time.
- **FR-025**: `ReplayBundle` MUST expose a pm4py-compatible event log via `event_log(label_fn=None)`: a DataFrame with `case:concept:name`, `concept:name`, `time:timestamp` columns when pm4py is absent; a `pm4py.objects.log.obj.EventLog` when present.
- **FR-026**: `ReplayBundle` MUST expose convenience aggregations following the existing `FlowQueryResult` idiom: `top_paths(n)`, `top_pages(n)`, `top_clicks(n)`, `dead_clicks(window_ms)`, `rage_clicks(threshold, window_ms)`, `long_pauses(threshold_s)`, `error_sessions()`.
- **FR-027**: `ReplayBundle` MUST expose chainable filter operations that return new bundles (immutable semantics): `filter(predicate)`, `where(distinct_id=..., contains_url=..., has_event=..., min_duration_s=..., max_duration_s=...)`, `find_pattern(action_sequence)`, `head(n)`, `sample(n, seed)`.
- **FR-028**: `ReplayBundle` MUST expose lazy enrichment via `join_mixpanel_events(properties=None)` returning a new bundle with `mixpanel_df` populated on first access.
- **FR-029**: `ReplayBundle` MUST expose `summary_markdown` (multi-session overview suitable for LLM consumption) AND `compare(other)` (action-frequency diff against another bundle).
- **FR-030**: A `replays_for_user(distinct_id, from_date, to_date)` convenience method MUST combine discovery + fetch in one call, returning a `ReplayBundle` populated with Mixpanel events by default.

#### Action labeling (Phase 2)

- **FR-031**: All process-mining-bound methods (`event_log`, `top_paths`, `find_pattern`, and any future method that emits activity labels) MUST accept an optional `label_fn: Callable[[UserAction], str]` parameter.
- **FR-032**: The default label function MUST produce stable labels of shape `f"{action}:{tag_name}@{normalized_url}"`. URL normalization MUST strip query strings AND replace numeric path segments with `:id` (e.g. `/users/12345/profile` → `/users/:id/profile`).
- **FR-033**: A built-in `selector_label_fn(attr="data-testid")` MUST be provided. When the named attribute is present on the target, the label MUST use it; when absent, it MUST fall back to the default label.

#### CLI (Phase 1 + Phase 2)

- **FR-034**: A new `mp replays` Typer command group MUST be registered alongside the existing groups.
- **FR-035**: Commands MUST follow the existing pattern: `@handle_errors`, `get_workspace(ctx)`, `output_result(ctx, ..., format=format)`.
- **FR-036**: The CLI surface MUST be: `list`, `events`, `sign`, `fetch`, `analyze`, `for-user`.
- **FR-037**: `mp replays sign` MUST default to redacted output (URL prefix only). The `--reveal-signed-urls` flag MUST opt into the full credential AND MUST emit a stderr warning EVERY time it is used — not just first use, not just interactive sessions, not just TTY. The warning fires unconditionally on every invocation. (This is the authoritative location for the CLI warning contract; FR-046 references it.)
- **FR-038**: `mp replays fetch <id> -o file.json` MUST write a JSON array of rrweb events directly compatible with the rrweb JS player.
- **FR-039**: `mp replays analyze <id>` MUST print a markdown timeline to stdout by default. `--format json` MUST emit the structured action list.
- **FR-040**: `mp replays for-user <id> --include analyze --out-dir DIR` MUST write per-replay markdown timelines to `DIR` AND print a one-line summary to stdout.

#### Optional extras (Phase 3)

- **FR-041**: `pyproject.toml` MUST add three install extras: `replay-mining` (`pm4py>=2.7`), `replay-ml` (`tslearn>=0.6`), `replay-all` (union plus `networkx>=3` and `anytree>=2`).
- **FR-042**: Importing the library AND instantiating `Workspace` MUST succeed with NONE of the optional extras installed.
- **FR-043**: When an optional dependency is missing and the corresponding property or method is accessed, the error MUST be a clear `ImportError` whose message names the exact `pip install` command required, e.g. `pip install 'mixpanel-headless[replay-mining]'`.

#### Security

- **FR-044**: Signed URL query strings MUST be treated as bearer credentials in every public surface — logging, `repr`, `str`, CLI default output, exception `details` dicts.
- **FR-045**: (Cross-reference to FR-010.) The exception payload contract for `SessionReplayAccessError` is defined at FR-010. No additional behavior beyond what FR-010 specifies.
- **FR-046**: (Cross-reference to FR-037.) The CLI warning contract for `--reveal-signed-urls` is defined at FR-037. No additional behavior beyond what FR-037 specifies.
- **FR-047**: A new exception hierarchy MUST be added: `SessionReplayError` (base), `SessionReplayAccessError`, `SignedURLExpiredError`, `ReplayNotFoundError`.

### Key Entities

- **ReplaySummary**: lightweight discovery handle (`replay_id`, `distinct_id?`, `project_id`, `start_time`, `retention_days`). Returned by `list_replays`. Does not include recording bytes.
- **SignedReplay**: time-bounded CDN access handle (`replay_id`, `url`, `query_string`, `env`, `signed_at`). Bearer-credential semantics enforced via `repr` masking, `expires_at` arithmetic, and `is_expired` boolean.
- **UserAction**: normalized action extracted from rrweb events by the vendored analyzer (`timestamp`, `action`, `target_node_id?`, `target_desc`, `url?`, `metadata`). The atomic unit the bundle aggregates over.
- **ReplayEvent**: a Mixpanel event that occurred during a replay's time window (`replay_id`, `event_name`, `event_time`, `properties?`). Optional enrichment on `Replay` / `ReplayBundle`.
- **Replay**: single fully-materialized session — raw rrweb events plus normalized actions plus optional Mixpanel events plus four lazy DataFrame projections plus convenience accessors.
- **ReplayBundle**: collection of `Replay` objects with seven cross-session DataFrame projections, two graph projections (`page_graph`, `element_graph`), one tree projection (`path_tree`), one event log for process mining, plus chainable filter / sample operations.
- **Exception hierarchy**: `SessionReplayError` (base) → `SessionReplayAccessError` (sensitive-data 403), `SignedURLExpiredError` (5-minute TTL expired), `ReplayNotFoundError` (no CDN files for the given replay_id).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user can list all of a known user's replays in a 7-day window with one Python call OR one CLI command, completing in under 2 seconds on a typical broadband connection.
- **SC-002**: A user can fetch a 30 MB replay's raw bytes in under 5 seconds (concurrent batched CDN fetch) AND can see the first event from `stream_replay` within 1 second of calling it.
- **SC-003**: A `ReplayBundle` of 100 typical replays materializes `actions_df` end-to-end (fetch + parse + project) in under 10 seconds on a typical broadband connection.
- **SC-004**: Bearer credentials NEVER appear in default library logging, default `repr`, default CLI output, default `str`, or default error messages. The library passes a manual "grep the transcript for the signed query string" audit against every public surface.
- **SC-005**: A user without `networkx`, `anytree`, `pm4py`, or `tslearn` installed can import the library, instantiate `Workspace`, list replays, sign replays, fetch a single replay, and call all `Replay` accessors that do not require those packages — with zero `ImportError`s on the core paths.
- **SC-006**: Every optional-extra-bound property and method raises an `ImportError` whose message names the exact `pip install` command required. Verified for every gated property in unit tests.
- **SC-007**: The vendored rrweb analyzer reaches at least 80% mutation score (`just mutate-check`) AND the new pure modules (services, analyzer, labels, aggregators) reach at least 90% line coverage (`just test-cov`).
- **SC-008**: The Phase 1 PR ships independently and delivers value (raw bytes + signed URLs + per-replay fetch) even if Phase 2 and Phase 3 never ship.
- **SC-009**: A new contributor can read the spec, plan, and module docstrings, then add a new bundle aggregation (e.g. `time_to_first_click()`) without needing to touch the analyzer or the CDN fetcher.
- **SC-010**: An analyst can produce a markdown summary of a known user's last week of behavior with a single command: `mp replays for-user USER --from D --to D --include analyze`.
- **SC-011**: A 403 from the sensitive-data flag never appears to the caller as a raw HTTP status — it always arrives as `SessionReplayAccessError` with structured `details` and an actionable message. Verified against a fixture project carrying the flag.

## Assumptions

- The undocumented `POST /app/projects/<id>/replays/sign/bulk` endpoint (used by Mixpanel's own MCP server) remains available to authenticated `mixpanel-headless` clients. If its shape changes, the surface to update is small (one service file) and the pre-release version notice already warns of API changes.
- Web session replays use rrweb format. Mobile replays use a different format and are out of scope for the bytes / analyzer layers; discovery still works because `$mp_session_record` / `$mp_replay_id` are platform-agnostic.
- The `$mp_replay_retention_period` event property is set by recent SDK versions. Older replays may lack it; the system defaults to 30 days with a structured warning.
- Mixpanel's CDN concurrency tolerance matches what the MCP server already uses (batch size 50). The library adopts the same default and exposes a `cdn_concurrency` parameter for tuning.
- `mixpanel-headless` is now considered an official second client to mixpanel.com and is already at near-parity on undocumented API usage; no special gating is required beyond the existing pre-release version warning.
- The existing `Workspace.query()` typed Insights surface (Phase 029) supports the grouping required for discovery; no Insights API changes are needed.
- `networkx` and `anytree` are reused from existing optional extras (already in `pyproject.toml` for flow-query usage), not introduced fresh by this feature.
- pm4py 2.7+ uses DataFrames as primary citizens, so the DataFrame-vs-EventLog branch in `event_log()` is a pure type-level fork, not a data-shape change.
- The vendored rrweb analyzer (ported from `analytics/backend/replays/rrweb_analyzer.py` in the analytics monorepo) is pure-stdlib Python and adds no install weight to the core package.
- The optional `replay-ml` extra carries heavy dependencies (`scipy`, `scikit-learn`, `joblib` via `tslearn`); users who opt in accept the install weight.
- Cohort-driven replay enumeration, real-time replay streaming, replay deletion / retention management, LLM-based replay summarization, replay bookmarking, and direct GCS access via internal service accounts are explicitly out of scope.
- The phased PR strategy (Phase 1 → Phase 2 → Phase 3) is enforced by reviewer convention, not tooling. Phase 3 ships only if user demand materializes after Phase 2 lands.
