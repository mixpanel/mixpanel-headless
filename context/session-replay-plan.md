# Implementation Plan: Session Replay for `mixpanel-headless`

**Branch**: `044-session-replay` (proposed) | **Date**: 2026-05-27 | **Author**: Jared McFarland
**Status**: Design (no code written)
**Source research**: [`jared-shares/2026-05/mixpanel-headless-session-replay-design.html`](https://storage.googleapis.com/jared-shares/2026-05/mixpanel-headless-session-replay-design.html)
**PR strategy**: Phased. Phase 1 (discovery + signed CDN access + `Replay`) ships as one PR. Phase 2 (vendored rrweb analyzer + `ReplayBundle` data model) ships as a second PR. Phase 3 (pm4py + tslearn optional extras) ships as a third PR, gated on user demand. Each phase is independently shippable and adds value.

---

## Summary

Add a first-class session replay surface to `mixpanel-headless` covering:

1. **Discovery** of replays for a user via the existing Insights Query API (`Workspace.query()`), grouped on `$mp_replay_id` and `$mp_replay_retention_period`.
2. **Signed CDN access** to raw rrweb recording files via Mixpanel's `/app/projects/<id>/replays/sign[/bulk]` endpoints, with both streaming and buffered fetch.
3. **Vendored rrweb analyzer** that converts raw rrweb event streams into normalized user-action timelines (DOM tracker + event interpreter + markdown reporter, ported from `analytics/backend/replays/rrweb_analyzer.py`).
4. **Two typed result classes** — `Replay` (single) and `ReplayBundle` (collection) — exposing long-format pandas DataFrames keyed by `replay_id`, lazy `networkx` page and element graphs, lazy `anytree` path trees, and a lazy `pm4py` event log for process mining.
5. **Convenience aggregations** matching the `FlowQueryResult` idiom: `top_paths()`, `top_clicks()`, `top_pages()`, `dead_clicks()`, `rage_clicks()`, `long_pauses()`, `error_sessions()`, plus bundle-returning filters (`filter()`, `where()`, `find_pattern()`) that chain cleanly.
6. **CLI group** `mp replays` with `list`, `events`, `sign`, `fetch`, `analyze`, and `for-user` commands.

The design treats a replay as an event log (timestamped activities keyed by a case ID) so the data shape lines up with every PyData library that touches sequential data — `pandas`, `pm4py`, `prefixspan`, `tslearn`, `duckdb`. The `ReplayBundle` is the high-leverage type; a `Replay` is conceptually a bundle of size 1, and the API treats them that way.

The work depends on one undocumented App API endpoint (`/replays/sign[/bulk]`), which is the same endpoint Mixpanel's own MCP server uses. `mixpanel-headless` is now an official second client to mixpanel.com and is already at near-parity on undocumented-API usage, so no special gating is needed beyond the existing pre-release version warning.

Estimated scope: ~3,000 LoC across ~25 new/modified files, three phases, total ~3-4 weeks of focused work.

---

## Technical Context

**Language/Version**: Python 3.10+ (mypy --strict compliant)

**Primary Dependencies**:
- Existing: `httpx` (HTTP client and CDN fetcher), `pydantic` v2 (validation), `pandas` (DataFrames), Typer (CLI), Rich (output), Hypothesis (PBT), mutmut (mutation testing)
- New (vendored, no third-party install): rrweb analyzer ported from analytics monorepo (~600 LoC, pure stdlib)
- New optional: `pm4py` (process mining; behind `replay-mining` extra), `tslearn` (DTW clustering; behind `replay-ml` extra), `networkx` and `anytree` (already optional via existing extras, reused)

**Storage**: None. Signed URLs are time-bounded bearer credentials; the library does not persist them. No new disk artifacts beyond what `httpx` already handles.

**Testing**: pytest (unit + integration); Hypothesis PBT for label-fn stability, file-numbering walker, and DataFrame projection invariants; mutmut on the vendored analyzer + new query builders. Integration tests gated on a known replay-bearing project (Mixpanel Labs internal project ID 3713224 or equivalent fixture).

**Target Platform**: Cross-platform (macOS, Linux, Windows).

**Performance Goals**:
- `list_replays(distinct_id, from_date, to_date)` ≤ 1 round trip to `/api/query/insights` for any date range up to 90 days.
- `sign_replays(ids)` ≤ 1 round trip for up to 1000 replay IDs.
- `fetch_replay(replay_id)` parallel CDN fetch with concurrency 50, terminates on first 404; for a typical 30 MB replay, expect under 5 s on a typical broadband connection.
- `stream_replay(replay_id)` first event yielded within 1 s of call (signed URL + first file fetch).
- `Replay.actions_df` materialization ≤ 200 ms for a 30 MB replay.
- `ReplayBundle.actions_df` materialization ≤ 100 ms per replay in the bundle (linear scaling).

**Constraints**:
- mypy --strict, zero unjustified `Any`.
- ruff format/check passes with zero violations.
- 90% test coverage minimum (CI fails below).
- 80% mutation score on new pure modules (`_internal/services/replays.py`, `_internal/replays/rrweb_analyzer.py`, `_internal/replays/labels.py`).
- Signed-URL `query_string` MUST NOT appear in any log line at any level (INFO/DEBUG/WARNING). `__repr__` of `SignedReplay` MUST mask the `query_string` field.
- Vendored analyzer MUST remain pure-Python (no native deps) so it works in every environment `mixpanel-headless` already supports.
- Optional extras (`replay-mining`, `replay-ml`) MUST NOT be required for any core surface to import; lazy imports inside property bodies and method bodies.

**Scale/Scope**:
- Phase 1: 5 new files, ~1,200 LoC including tests.
- Phase 2: 4 new files (vendored analyzer, labels, ReplayBundle expansion, tests), ~1,500 LoC.
- Phase 3: 2 new files (pm4py adapter, tslearn adapter), ~500 LoC.

---

## Out of Scope (explicit)

To keep the first cuts focused:

- **Mobile session replays.** Different recording format. The MCP server has an open TODO (SR-230). Discovery still works since `$mp_session_record` / `$mp_replay_id` are platform-agnostic, but the bytes layer and analyzer are web-only in this design.
- **Direct GCS access via internal service account.** The `gcs_fetcher.py` path in `analytics/backend/replays/` is reserved for Mixpanel's own P3 project. Not relevant or accessible to external callers.
- **Replay bookmarking / saved-report integration.** Replays aren't bookmarkable through the App API and there's no clear product fit for that yet.
- **LLM-based replay summarization.** The vendored analyzer produces a deterministic markdown timeline. LLM enrichment is a downstream concern — `mixpanelyst` skill or user code can layer it on.
- **Real-time replay streaming.** Replays are batched and uploaded every 10 s by the SDK and become available shortly after; this design is for retrospective analysis, not live tailing.
- **Replay deletion / retention management.** Out of scope for the read-side library.
- **Cohort-driven replay enumeration.** Listing replays for all members of a cohort is a natural extension but adds a join layer; can ship in a follow-up if there's demand.

---

## Functional Requirements

### Discovery

- **FR-001**: `Workspace.list_replays()` MUST accept either a `distinct_id` (with `from_date` / `to_date`) or an explicit list of `replay_ids`. Both paths return `list[ReplaySummary]`.
- **FR-002**: Discovery MUST use the Insights Query API (`Workspace.query()`), grouping on `$mp_replay_id` AND `$mp_replay_retention_period` AND `$time`, never the legacy Segmentation API.
- **FR-003**: When no `$mp_session_record` events are found in range, `list_replays(distinct_id=...)` MUST return an empty list, never raise. Empty-result handling is the caller's responsibility.
- **FR-004**: The retention period for each replay MUST be read from the discovered `$mp_replay_retention_period` property, not hardcoded. When the property is missing (older replays, edge cases), default to 30 days with a structured warning.
- **FR-005**: `Workspace.events_for_replay(replay_id)` and `Workspace.events_for_replays(replay_ids)` MUST query the Insights API for events filtered on `$mp_replay_id`, excluding `$mp_session_record` itself, optionally including up to 5 additional event properties as group keys.

### Signed CDN Access

- **FR-006**: `Workspace.sign_replays(replay_ids, env="prod")` MUST POST to `/app/projects/<project_id>/replays/sign/bulk` with the bulk shape, returning `list[SignedReplay]`. Single-replay sugar `sign_replay(replay_id)` is a thin wrapper around the bulk call.
- **FR-007**: A 403 response indicating the `SESSION_RECORDING_SENSITIVE_DATA` project flag is set MUST raise `SessionReplayAccessError` with structured details (project_id, hint to contact project owner). Other 4xx/5xx errors flow through the existing `QueryError` / `ServerError` mappings.
- **FR-008**: `SignedReplay` instances MUST mask the `query_string` field in `__repr__` and `__str__`. Default Python logging of a `SignedReplay` MUST NOT leak the signed credential.
- **FR-009**: The library MUST NOT log `query_string` at any log level. Logging the URL prefix (without query string) is acceptable at DEBUG.
- **FR-010**: Signed URLs have a 5-minute server-side expiration. `Workspace.stream_replay()` MUST re-sign on demand if a fetch fails with a 403 indicating signature expiration; `Workspace.fetch_replay()` does not need this because it signs and fetches in immediate succession.

### CDN Fetching

- **FR-011**: `Workspace.fetch_replay(replay_id)` MUST sign, fetch all CDN files in parallel (concurrency 50, batches), concatenate, sort by timestamp, and return a `Replay`.
- **FR-012**: `Workspace.stream_replay(replay_id)` MUST yield rrweb events one at a time. Implementation: fetch files in batches of 50 in parallel; within a batch, yield events in timestamp order; do not buffer across batches.
- **FR-013**: CDN file naming MUST use the per-replay retention period from FR-004: `{prefix}{N:04d}-{retention_days}.json`.
- **FR-014**: Fetching MUST terminate cleanly on the first 404 (signal of end-of-replay), not retry it. Other HTTP errors are retried per the existing `MixpanelAPIClient` policy.
- **FR-015**: A configurable `max_files` parameter (default 500; MCP server uses 200) bounds runaway fetches if the 404 sentinel is missed.

### Single-Replay Result Type

- **FR-016**: `Replay` MUST be a frozen dataclass inheriting from the existing `ResultWithDataFrame` mixin.
- **FR-017**: `Replay` MUST expose `rrweb_events`, `actions`, `mixpanel_events` as raw lists, and `events_df`, `actions_df`, `mixpanel_df`, `pages_df` as cached lazy DataFrame properties.
- **FR-018**: `Replay.df` MUST return `actions_df` by default (the most useful projection for typical analysis).
- **FR-019**: `Replay` MUST expose convenience methods `duration_seconds`, `page_path()`, `errors`, `clicks_on(selector)`, `summary_markdown`, `to_rrweb_player_json()`.

### Bundle Result Type

- **FR-020**: `ReplayBundle` MUST be a frozen dataclass inheriting from `ResultWithDataFrame`.
- **FR-021**: `ReplayBundle` MUST expose `replays: list[Replay]` and the seven cached lazy DataFrame projections: `sessions_df`, `actions_df`, `events_df`, `mixpanel_df`, `pages_df`, `elements_df`, `transitions_df`.
- **FR-022**: `ReplayBundle.df` MUST return `sessions_df` by default (one row per replay, most useful default).
- **FR-023**: `ReplayBundle` MUST expose graph projections `page_graph`, `element_graph`, `path_tree` as cached lazy properties using `networkx` and `anytree` respectively. These properties MUST lazy-import their dependencies inside the property body.
- **FR-024**: `ReplayBundle.event_log` MUST return a pm4py-compatible `pandas.DataFrame` (with renamed columns `case:concept:name`, `concept:name`, `time:timestamp`) when `pm4py` is not installed, or a `pm4py.objects.log.obj.EventLog` when it is. The lazy-import pattern from FR-023 applies.
- **FR-025**: `ReplayBundle` MUST expose convenience aggregations matching the `FlowQueryResult` idiom: `top_paths(n=10)`, `top_clicks(n=10)`, `top_pages(n=10)`, `dead_clicks(window_ms=200)`, `rage_clicks(threshold=3, window_ms=1000)`, `long_pauses(threshold_s=10)`, `error_sessions()`.
- **FR-026**: `ReplayBundle` MUST expose chainable filter methods that return new `ReplayBundle` instances: `filter(predicate)`, `where(**kwargs)`, `find_pattern(action_sequence)`, `head(n)`, `sample(n, seed=None)`.
- **FR-027**: `ReplayBundle.join_mixpanel_events(properties=None)` MUST enrich the bundle with `mixpanel_df` data fetched lazily on first access.
- **FR-028**: `ReplayBundle.summary_markdown` MUST produce a concise multi-session overview suitable for LLM consumption.

### Action Labeling

- **FR-029**: `ReplayBundle.event_log`, `top_paths()`, `find_pattern()`, and any process-mining-bound method MUST accept an optional `label_fn: Callable[[UserAction], str]` parameter for user-controlled activity labeling.
- **FR-030**: The default label function MUST produce stable labels of the shape `f"{action}:{tag_name}@{normalized_url}"` — coarse enough to align across sessions, specific enough to be meaningful.
- **FR-031**: A built-in `labels.selector_label_fn(attr="data-testid")` MUST be provided for projects that tag interactive elements with stable identifiers.

### CLI

- **FR-032**: A new `mp replays` Typer group MUST be registered in `cli/main.py::_register_commands()`.
- **FR-033**: Commands MUST follow the existing pattern: `@handle_errors`, `get_workspace(ctx)`, `output_result(ctx, ..., format=format)`.
- **FR-034**: The CLI surface MUST be: `list`, `events`, `sign`, `fetch`, `analyze`, `for-user` (sugar that composes `list` + `analyze`).
- **FR-035**: `mp replays sign` MUST default to redacted output (URL prefix only). A `--reveal-signed-urls` flag opts into the full output (required for actual CDN use); the flag MUST emit a stderr warning that signed URLs are bearer credentials.
- **FR-036**: `mp replays fetch <id> -o file.json` MUST write a JSON array of rrweb events directly compatible with the rrweb JS player.
- **FR-037**: `mp replays analyze <id>` MUST print the markdown timeline to stdout.

### Optional Extras

- **FR-038**: `pyproject.toml` MUST define three new install extras:
  - `replay-analyze`: vendored analyzer is in core (always available); this extra is reserved as a stable name for future analyzer-only deps.
  - `replay-mining`: `pm4py>=2.7`
  - `replay-ml`: `tslearn>=0.6`
  - `replay-all`: union of the above plus `networkx` and `anytree` (already extras)
- **FR-039**: Importing `mixpanel_headless` and instantiating `Workspace` MUST succeed with none of the optional extras installed.
- **FR-040**: When an optional dep is missing and the corresponding property is accessed, the error MUST be a clear `ImportError` with the install command in the message: `f"To use ReplayBundle.event_log, install: pip install 'mixpanel-headless[replay-mining]'"`.

### Security

- **FR-041**: Signed URLs MUST be treated as bearer credentials in all library logging, repr, and error contexts. `SignedReplay.__repr__` masks `query_string` as `"<redacted N chars>"`.
- **FR-042**: The library MUST translate the `SESSION_RECORDING_SENSITIVE_DATA` 403 into `SessionReplayAccessError` with structured `details = {"project_id": ..., "flag": "SESSION_RECORDING_SENSITIVE_DATA"}` and an actionable message.
- **FR-043**: `mp replays sign` CLI output MUST default to redacted; the `--reveal-signed-urls` flag is required to opt into the bearer-credential output and MUST emit a stderr warning.

---

## Architecture

```
                        ┌─────────────────────────────────────┐
                        │  Workspace (public facade)          │
                        │  list_replays, sign_replays,        │
                        │  fetch_replay, stream_replay,       │
                        │  analyze_replay, events_for_replay  │
                        └──────────────────┬──────────────────┘
                                           │
              ┌────────────────────────────┼────────────────────────────┐
              │                            │                            │
              ▼                            ▼                            ▼
   ┌─────────────────────┐      ┌─────────────────────┐      ┌─────────────────────┐
   │ ReplaysService      │      │ MixpanelAPIClient   │      │ Insights query path │
   │ _internal/services/ │      │ (existing)          │      │ (existing)          │
   │ replays.py          │      │                     │      │                     │
   │                     │      │ • sign_replays      │      │ • $mp_session_record│
   │ • orchestrates       │      │ • CDN fetch (httpx) │      │   discovery         │
   │   sign + fetch +    │      │ • error mapping     │      │ • $mp_replay_id     │
   │   analyze pipeline  │      │                     │      │   event window join │
   └────────┬────────────┘      └─────────────────────┘      └─────────────────────┘
            │
            ▼
   ┌─────────────────────┐
   │ rrweb_analyzer      │
   │ _internal/replays/  │
   │ rrweb_analyzer.py   │
   │ (vendored, pure-py) │
   │                     │
   │ • DOMTracker        │
   │ • EventAnalyzer     │
   │ • MarkdownReporter  │
   └─────────────────────┘
            │
            ▼
   ┌─────────────────────┐
   │ labels.py           │
   │ _internal/replays/  │
   │                     │
   │ • default_label_fn  │
   │ • selector_label_fn │
   │ • url_normalizer    │
   └─────────────────────┘

   Result types (mixpanel_headless.types):
     SignedReplay, ReplayEvent, UserAction, Replay, ReplayBundle, ReplaySummary
```

### Layered pipeline

1. **Discovery** — `Insights Query API` via existing `Workspace.query()`. Returns `(replay_id, retention_days, start_time)` triples per `$mp_session_record` event.
2. **Sign** — `POST /app/projects/<id>/replays/sign/bulk`. Returns prefix URL + signed query string (5-min TTL) per replay.
3. **Fetch** — Parallel HTTPS GETs to `cdn.mxpnl.com/srr-{region}/<prefix>/<NNNN>-<retention>.json?<query_string>`. Terminate on first 404.
4. **Parse** — Vendored rrweb analyzer walks the concatenated event stream, maintains DOM state, emits `UserAction` records.
5. **Aggregate** — `ReplayBundle` materializes long-format DataFrames and lazy graph/tree/event-log projections from action records.
6. **Mine (optional, behind extras)** — `pm4py` discovers process structure from the event log; `tslearn` clusters sessions by action sequence.
7. **Render** — CLI formatters / DataFrame heads / markdown timelines / Graphviz exports.

---

## API Surface — Python

### Workspace methods

All methods are added to `mixpanel_headless.workspace.Workspace`. They follow the existing pattern of calling either `self._api` for direct HTTP or a service from `self._services` for orchestrated work.

```python
class Workspace:

    # ─── Discovery ──────────────────────────────────────────────────────

    def list_replays(
        self,
        *,
        distinct_id: str | None = None,
        replay_ids: list[str] | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 100,
    ) -> list[ReplaySummary]:
        """List replays for a user or hydrate summaries for explicit IDs.

        Exactly one of (distinct_id, replay_ids) must be provided. When
        distinct_id is given, from_date and to_date are required.

        Implementation: queries $mp_session_record via the Insights API,
        grouped on $mp_replay_id and $mp_replay_retention_period.
        """

    def events_for_replay(
        self,
        replay_id: str,
        *,
        event_properties: list[str] | None = None,
    ) -> list[ReplayEvent]:
        """Mixpanel events that occurred during a replay's window.

        Queries the Insights API filtered on $mp_replay_id, excluding
        $mp_session_record. At most 5 event_properties can be requested
        (Insights group-clause limit).
        """

    def events_for_replays(
        self,
        replay_ids: list[str],
        *,
        event_properties: list[str] | None = None,
    ) -> dict[str, list[ReplayEvent]]:
        """Batch version of events_for_replay, single Insights round-trip."""

    # ─── Signed access ──────────────────────────────────────────────────

    def sign_replay(
        self,
        replay_id: str,
        *,
        env: Literal["prod", "dev"] = "prod",
    ) -> SignedReplay:
        """Single-replay signing sugar over sign_replays."""

    def sign_replays(
        self,
        replay_ids: list[str],
        *,
        env: Literal["prod", "dev"] = "prod",
    ) -> list[SignedReplay]:
        """POST to /app/projects/<id>/replays/sign/bulk."""

    # ─── Fetch ──────────────────────────────────────────────────────────

    def fetch_replay(
        self,
        replay_id: str,
        *,
        env: Literal["prod", "dev"] = "prod",
        retention_days: int | None = None,
        max_files: int = 500,
        include_mixpanel_events: bool = False,
        event_properties: list[str] | None = None,
    ) -> Replay:
        """Sign + fetch + parse + return a populated Replay.

        When retention_days is None, list_replays is consulted first to
        discover the actual retention period for this replay. Pass
        retention_days explicitly to skip the discovery round trip.

        include_mixpanel_events=True triggers a follow-up Insights query
        to populate Replay.mixpanel_events.
        """

    def stream_replay(
        self,
        replay_id: str,
        *,
        env: Literal["prod", "dev"] = "prod",
        retention_days: int | None = None,
        max_files: int = 500,
        re_sign_on_expiry: bool = True,
    ) -> Iterator[dict[str, Any]]:
        """Yield rrweb events one at a time, batched-parallel under the hood.

        re_sign_on_expiry=True re-signs the URL on a 403 indicating
        signature expiration. False propagates the 403 as a SignedURLExpiredError.
        """

    # ─── Bundle (collection) ────────────────────────────────────────────

    def fetch_replays(
        self,
        replay_ids: list[str],
        *,
        env: Literal["prod", "dev"] = "prod",
        max_files: int = 500,
        include_mixpanel_events: bool = False,
        event_properties: list[str] | None = None,
        concurrency: int = 4,
    ) -> ReplayBundle:
        """Sign + fetch + parse N replays in parallel, return a ReplayBundle.

        concurrency controls how many replays are fetched in parallel.
        Within each replay, CDN files are fetched at concurrency 50.
        """

    def replays_for_user(
        self,
        distinct_id: str,
        *,
        from_date: str,
        to_date: str,
        limit: int = 100,
        include_mixpanel_events: bool = True,
        event_properties: list[str] | None = None,
    ) -> ReplayBundle:
        """Discovery + fetch in one call. The 'I want this user's recent
        activity' convenience method.
        """

    # ─── Analysis ───────────────────────────────────────────────────────

    def analyze_replay(self, replay_id: str) -> str:
        """Sign + fetch + analyzer.analyze_events + return the markdown timeline.

        Sugar for: ws.fetch_replay(id).summary_markdown.
        """
```

### Result types

```python
# mixpanel_headless.types (new additions)

@dataclass(frozen=True)
class ReplaySummary(ResultWithDataFrame):
    """Lightweight handle to a replay, returned by list_replays.

    Does NOT include recording bytes or normalized actions. Use
    ws.fetch_replay(summary.replay_id) to materialize the full Replay.
    """
    replay_id: str
    distinct_id: str | None
    project_id: int
    start_time: int          # unix ms (from $mp_session_record event timestamp)
    retention_days: int

@dataclass(frozen=True)
class SignedReplay:
    """Time-bounded signed CDN access for one replay.

    SECURITY: query_string is a bearer credential valid for ~5 minutes.
    Treat it like a session token. __repr__ masks it; do not log it.
    """
    replay_id: str
    url: str              # prefix, includes trailing slash
    query_string: str     # MASKED IN __repr__
    env: Literal["prod", "dev"]
    signed_at: float      # unix seconds (for expiration arithmetic)

    def __repr__(self) -> str:
        masked = f"<redacted {len(self.query_string)} chars>"
        return (
            f"SignedReplay(replay_id={self.replay_id!r}, url={self.url!r}, "
            f"query_string={masked!r}, env={self.env!r}, signed_at={self.signed_at!r})"
        )

    @property
    def expires_at(self) -> float:
        """Approximate expiration timestamp (signed_at + 5 minutes)."""
        return self.signed_at + 300

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

@dataclass(frozen=True)
class UserAction:
    """Normalized user action extracted from rrweb events by the analyzer."""
    timestamp: int           # unix ms
    action: str              # 'click' | 'input' | 'scroll' | 'navigate' | 'select' | 'console_error' | ...
    target_node_id: int | None
    target_desc: str         # e.g. 'button "Sign in"'
    url: str | None
    metadata: dict[str, Any]

@dataclass(frozen=True)
class ReplayEvent(ResultWithDataFrame):
    """Mixpanel event that occurred during a replay's time window."""
    replay_id: str
    event_name: str
    event_time: int          # unix seconds
    properties: dict[str, Any] | None

@dataclass(frozen=True)
class Replay(ResultWithDataFrame):
    """Single fully-materialized replay.

    A Replay is conceptually a ReplayBundle of size 1; the same
    DataFrame projections are available on both.
    """
    replay_id: str
    distinct_id: str | None
    project_id: int
    start_time: int          # unix ms
    end_time: int
    retention_days: int

    rrweb_events: list[dict[str, Any]]
    actions: list[UserAction]
    mixpanel_events: list[ReplayEvent]    # empty unless include_mixpanel_events was True

    # cached projections
    _events_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _actions_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _mixpanel_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _pages_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)

    @property
    def events_df(self) -> pd.DataFrame: ...
    @property
    def actions_df(self) -> pd.DataFrame: ...
    @property
    def mixpanel_df(self) -> pd.DataFrame: ...
    @property
    def pages_df(self) -> pd.DataFrame: ...
    @property
    def df(self) -> pd.DataFrame:
        """Default projection: actions_df."""
        return self.actions_df

    @property
    def duration_seconds(self) -> float: ...
    @property
    def errors(self) -> pd.DataFrame: ...
    @property
    def summary_markdown(self) -> str: ...
    def page_path(self) -> list[str]: ...
    def clicks_on(self, predicate: Callable[[UserAction], bool]) -> pd.DataFrame: ...
    def to_rrweb_player_json(self) -> list[dict[str, Any]]:
        """Return rrweb_events sorted by timestamp, ready for the rrweb JS player."""

@dataclass(frozen=True)
class ReplayBundle(ResultWithDataFrame):
    """Collection of replays with cross-session DataFrame and graph projections."""
    replays: list[Replay]
    computed_at: str
    project_id: int

    # cached projections (DataFrames)
    _sessions_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _actions_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _events_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _mixpanel_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _pages_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _elements_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _transitions_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)

    # cached projections (graphs)
    _page_graph_cache: object | None = field(default=None, repr=False, kw_only=True)
    _element_graph_cache: object | None = field(default=None, repr=False, kw_only=True)
    _path_tree_cache: object | None = field(default=None, repr=False, kw_only=True)

    # DataFrame projections (see Data Model section for full columns)
    @property
    def sessions_df(self) -> pd.DataFrame: ...
    @property
    def actions_df(self) -> pd.DataFrame: ...
    @property
    def events_df(self) -> pd.DataFrame: ...
    @property
    def mixpanel_df(self) -> pd.DataFrame: ...
    @property
    def pages_df(self) -> pd.DataFrame: ...
    @property
    def elements_df(self) -> pd.DataFrame: ...
    @property
    def transitions_df(self) -> pd.DataFrame: ...
    @property
    def df(self) -> pd.DataFrame:
        """Default projection: sessions_df."""
        return self.sessions_df

    # Graph and tree projections (lazy, optional deps)
    @property
    def page_graph(self) -> "networkx.DiGraph": ...
    @property
    def element_graph(self) -> "networkx.DiGraph": ...
    @property
    def path_tree(self) -> "anytree.AnyNode": ...

    # Event log for process mining (DataFrame fallback when pm4py not installed)
    def event_log(
        self,
        *,
        label_fn: Callable[[UserAction], str] | None = None,
    ) -> "pd.DataFrame | pm4py.objects.log.obj.EventLog": ...

    # Aggregations (return DataFrames)
    def top_paths(self, n: int = 10, *, label_fn: Callable[[UserAction], str] | None = None) -> pd.DataFrame: ...
    def top_pages(self, n: int = 10) -> pd.DataFrame: ...
    def top_clicks(self, n: int = 10) -> pd.DataFrame: ...
    def dead_clicks(self, window_ms: int = 200) -> pd.DataFrame: ...
    def rage_clicks(self, threshold: int = 3, window_ms: int = 1000) -> pd.DataFrame: ...
    def long_pauses(self, threshold_s: float = 10) -> pd.DataFrame: ...

    # Filters (return new ReplayBundle)
    def filter(self, predicate: Callable[[Replay], bool]) -> "ReplayBundle": ...
    def where(
        self,
        *,
        distinct_id: str | None = None,
        contains_url: str | None = None,
        has_event: str | None = None,
        min_duration_s: float | None = None,
        max_duration_s: float | None = None,
    ) -> "ReplayBundle": ...
    def find_pattern(
        self,
        action_sequence: list[str],
        *,
        label_fn: Callable[[UserAction], str] | None = None,
    ) -> "ReplayBundle": ...
    def error_sessions(self) -> "ReplayBundle": ...
    def head(self, n: int = 5) -> "ReplayBundle": ...
    def sample(self, n: int = 5, seed: int | None = None) -> "ReplayBundle": ...

    # Enrichment
    def join_mixpanel_events(
        self,
        properties: list[str] | None = None,
    ) -> "ReplayBundle":
        """Return a new bundle with mixpanel_events populated on every Replay."""

    # Summary / comparison
    @property
    def summary_markdown(self) -> str: ...
    def compare(self, other: "ReplayBundle") -> pd.DataFrame:
        """Action-frequency diff vs another bundle (e.g., converters vs non-converters)."""

    # ML (lives in Phase 3, optional)
    def cluster(self, n: int = 5, *, features: Literal["actions", "pages"] = "actions") -> "ReplayBundle":
        """Add a cluster_label property to each Replay (uses tslearn DTW). Requires [replay-ml] extra."""
```

### Exception hierarchy additions

```python
# mixpanel_headless.exceptions (new additions)

class SessionReplayError(APIError):
    """Base for session-replay-specific errors."""

class SessionReplayAccessError(SessionReplayError):
    """The project has SESSION_RECORDING_SENSITIVE_DATA enabled and the
    caller lacks sensitive-data access. Contact the project owner.
    """
    # details = {"project_id": ..., "flag": "SESSION_RECORDING_SENSITIVE_DATA"}

class SignedURLExpiredError(SessionReplayError):
    """The signed URL passed to a CDN fetch has expired (5-minute TTL).
    Re-sign and retry.
    """

class ReplayNotFoundError(SessionReplayError):
    """A specific replay_id was requested but no CDN files were found.
    The replay may have aged out of retention, never been recorded, or
    been deleted.
    """
```

### Public exports

`mixpanel_headless/__init__.py` adds to `__all__`:

```python
# Session Replay (Phase 044)
"Replay",
"ReplayBundle",
"ReplaySummary",
"SignedReplay",
"ReplayEvent",
"UserAction",
"SessionReplayError",
"SessionReplayAccessError",
"SignedURLExpiredError",
"ReplayNotFoundError",
```

---

## API Surface — CLI

A new Typer group at `cli/commands/replays.py`, registered in `cli/main.py::_register_commands()`.

### Commands

```bash
# Discovery
mp replays list --user abc-123 --from 2026-05-01 --to 2026-05-27
mp replays list --user abc-123 --from 2026-05-01 --to 2026-05-27 --format table
mp replays events <replay_id>
mp replays events <replay_id> --properties '$browser,$current_url'

# Signed access (defaults to redacted output; --reveal-signed-urls opts in)
mp replays sign <replay_id> [<replay_id>...] --env prod
mp replays sign <replay_id> --reveal-signed-urls --format jsonl

# Fetch raw recording bytes
mp replays fetch <replay_id> -o recording.json
mp replays fetch <replay_id> --include-events -o recording_with_events.json

# Analysis (vendored rrweb analyzer)
mp replays analyze <replay_id>
mp replays analyze <replay_id> --format json  # structured action list

# Sugar — combines list + fetch + analyze
mp replays for-user abc-123 --from 2026-05-01 --to 2026-05-27 \
    --include analyze --include events \
    --out-dir ./replays/
```

### Output formats

Follows existing convention via `FormatOption`:

- `list`: defaults to `table` (columns: replay_id, distinct_id, started, retention)
- `events`: defaults to `json`
- `sign`: defaults to `json` (redacted unless `--reveal-signed-urls`)
- `fetch`: writes raw JSON to the file given via `-o`; without `-o`, writes a one-line summary to stdout
- `analyze`: defaults to `plain` (the markdown timeline); `--format json` returns the structured action list

### Examples

```bash
# Quickly inspect what a user did last week
mp replays for-user user-42 --from 2026-05-20 --to 2026-05-27 --include analyze

# Pull a single replay for offline analysis with the rrweb JS player
mp replays fetch r-19221397401184 -o replay.json
# Then in a browser:
#   import rrwebPlayer from 'rrweb-player';
#   const events = await (await fetch('replay.json')).json();
#   new rrwebPlayer({ target: document.body, props: { events } });

# Get raw signed URLs for a custom CDN-fetch pipeline
mp replays sign r-a r-b r-c --reveal-signed-urls --format jsonl > urls.jsonl
```

---

## Data Model

### Discovery query shape

For `list_replays(distinct_id=..., from_date=..., to_date=...)`:

```python
result = ws.query(
    "$mp_session_record",
    from_date=from_date,
    to_date=to_date,
    where=Filter(
        property="$distinct_id",
        operator="equals",
        values=[distinct_id],
    ),
    group_by=[
        "$mp_replay_id",
        "$mp_replay_retention_period",
    ],
    mode="table",
)
```

The resulting `QueryResult.df` is shaped roughly:

| date | $mp_replay_id | $mp_replay_retention_period | count |
|---|---|---|---|
| 2026-05-21 | r-19221... | 30 | 1 |
| 2026-05-21 | r-19222... | 30 | 1 |
| 2026-05-22 | r-19223... | 30 | 1 |

`list_replays` reshapes this into `list[ReplaySummary]`, taking the earliest `date` per `replay_id` as the start time.

### `events_for_replay` query shape

```python
group_keys = ["$time", "$event_name", "$mp_replay_id"]
if event_properties:
    group_keys += event_properties

result = ws.query(
    "$all_events",                # behavior-set query, not a literal event
    from_date=replay_start_date,
    to_date=replay_end_date,
    where=[
        Filter(property="$mp_replay_id", operator="equals", values=[replay_id]),
        Filter(property="$event_name", operator="does not equal", values=["$mp_session_record"]),
    ],
    group_by=group_keys,
    mode="table",
)
```

The exact bookmark shape mirrors the MCP server's `build_replay_events_request` in `analytics/backend/replays/query_utils.py` but routed through `Workspace.query()` instead of constructing an `InsightsBookmarkParams` directly. The Phase 029 typed Insights surface in `mixpanel-headless` supports this group-by shape.

### CDN fetch pattern

After signing, the CDN access pattern is:

```
https://cdn.mxpnl.com/srr-{us|eu|in}/{sha256(replay_id)}-{project_id}/{NNNN}-{retention_days}.json?{query_string}
```

The library walks `NNNN` from `0000` upward in parallel batches of 50, stops on first `404`. The retention period comes from `ReplaySummary.retention_days` (discovered via FR-004), not hardcoded.

Each `NNNN-N.json` is a JSON array of rrweb event objects. The library concatenates them and sorts by `timestamp` (rrweb timestamps are unix ms).

### `Replay` DataFrame columns

**`events_df`** — flat rrweb events:

| Column | Type | Notes |
|---|---|---|
| `t` | `int64` | rrweb timestamp (unix ms) |
| `type` | `category` | rrweb EventType: `DomContentLoaded` (0), `Load` (1), `FullSnapshot` (2), `IncrementalSnapshot` (3), `Meta` (4), `Custom` (5), `Plugin` (6) |
| `source` | `category` | `IncrementalSource` for type=3 events; null otherwise. Values: `Mutation`, `MouseMove`, `MouseInteraction`, `Scroll`, `ViewportResize`, `Input`, `TouchMove`, `MediaInteraction`, `StyleSheetRule`, `CanvasMutation`, `Font`, `Log`, `Drag`, `StyleDeclaration`, `Selection` |
| `mouse_type` | `category` | For MouseInteraction events: `click`, `dbl_click`, `context_menu`, `focus`, `touch_start`, ... |
| `target_node_id` | `Int64` | nullable; the rrweb node ID the event targets |
| `url` | `string` | extracted from Meta events; null otherwise |
| `raw` | `object` | full original rrweb dict for callers that need everything |

**`actions_df`** — normalized actions from the analyzer:

| Column | Type | Notes |
|---|---|---|
| `t` | `int64` | unix ms |
| `action` | `category` | `click`, `input`, `scroll`, `navigate`, `select`, `console_error`, ... |
| `target_node_id` | `Int64` | nullable |
| `target_desc` | `string` | `'button "Sign in"'`, `'input[type=email]'`, ... |
| `url` | `string` | active page URL at the time of the action |
| `metadata` | `object` | dict (text_length, is_checked, range_count, etc.) |

**`pages_df`** — one row per Meta navigation event:

| Column | Type | Notes |
|---|---|---|
| `t` | `int64` | unix ms when navigation happened |
| `url` | `string` | destination URL |
| `dwell_ms` | `int64` | time until next navigation (or end of replay) |

**`mixpanel_df`** — empty unless populated; same columns as the bundle's `mixpanel_df`.

### `ReplayBundle` DataFrame columns

**`sessions_df`** — one row per replay:

| Column | Type | Notes |
|---|---|---|
| `replay_id` | `string` | primary key |
| `distinct_id` | `string` | nullable |
| `start_time` | `datetime64[ns, UTC]` | from rrweb |
| `end_time` | `datetime64[ns, UTC]` | from rrweb |
| `duration_s` | `float64` | end - start |
| `retention_days` | `Int16` | from `$mp_replay_retention_period` |
| `n_events` | `Int32` | rrweb event count |
| `n_actions` | `Int32` | normalized action count |
| `n_clicks` | `Int32` | |
| `n_inputs` | `Int32` | |
| `n_pages` | `Int32` | distinct URLs visited |
| `n_errors` | `Int32` | console errors |
| `n_mp_events` | `Int32` | Mixpanel events joined in (0 unless joined) |
| `entry_url` | `string` | first URL visited |
| `exit_url` | `string` | last URL visited |
| `dead_click_count` | `Int32` | clicks with no DOM mutation within 200ms |
| `rage_click_count` | `Int32` | ≥3 clicks on same target within 1s |
| `longest_pause_s` | `float64` | longest gap between consecutive actions |

**`actions_df`** — long format, all bundle replays:

| Column | Type | Notes |
|---|---|---|
| `replay_id` | `string` | foreign key to sessions_df |
| `t` | `datetime64[ns, UTC]` | normalized to UTC |
| `action` | `category` | |
| `target_node_id` | `Int64` | nullable |
| `target_desc` | `string` | |
| `url` | `string` | |

**`events_df`** — long format, raw rrweb events across the bundle; same columns as `Replay.events_df` plus `replay_id`.

**`mixpanel_df`** — long format, Mixpanel events across the bundle:

| Column | Type | Notes |
|---|---|---|
| `replay_id` | `string` | foreign key |
| `t` | `datetime64[ns, UTC]` | |
| `event_name` | `string` | |
| `properties` | `object` | dict |

**`pages_df`** — long format page visits:

| Column | Type | Notes |
|---|---|---|
| `replay_id` | `string` | |
| `t` | `datetime64[ns, UTC]` | navigation timestamp |
| `url` | `string` | |
| `dwell_ms` | `int64` | |

**`elements_df`** — element-level aggregations:

| Column | Type | Notes |
|---|---|---|
| `target_desc` | `string` | primary key (with the active URL) |
| `url` | `string` | |
| `n_clicks` | `Int32` | total clicks across all replays |
| `n_unique_users` | `Int32` | distinct `distinct_id` count |
| `n_unique_replays` | `Int32` | distinct `replay_id` count |
| `n_dead_clicks` | `Int32` | |
| `n_rage_clicks` | `Int32` | |
| `mean_dwell_after_ms` | `float64` | average time until next action after clicking this element |

**`transitions_df`** — page-to-page transitions across all replays:

| Column | Type | Notes |
|---|---|---|
| `from_url` | `string` | |
| `to_url` | `string` | |
| `count` | `Int32` | |
| `n_unique_replays` | `Int32` | |
| `mean_dwell_s` | `float64` | average dwell on `from_url` before transitioning |

### Graph projections

**`page_graph`** — `networkx.DiGraph`:
- Nodes: URL strings
- Node attributes: `n_visits`, `n_unique_replays`, `is_entry`, `is_exit`
- Edges: directed transitions
- Edge attributes: `count`, `n_unique_replays`, `mean_dwell_s`
- Algorithms that work out of the box: `nx.pagerank` (most-visited pages weighted by traffic), `nx.betweenness_centrality(weight="count")` (bottleneck pages), `nx.simple_cycles` (loops in navigation), `nx.shortest_path` (typical user trajectory).

**`element_graph`** — `networkx.DiGraph`:
- Nodes: `(target_desc, url)` tuples
- Node attributes: `n_clicks`, `n_unique_users`
- Edges: directed sequence of clicks (X → Y when a user clicked X then Y within the same replay)
- Edge attributes: `count`, `mean_gap_s`
- Useful for finding interaction clusters and common click sequences.

**`path_tree`** — `anytree.AnyNode`:
- Root: synthetic "Start" node
- Children: action sequences across the bundle, with frequency counts on each node
- Methods inherited from anytree: `RenderTree`, `findall`, `UniqueDotExporter` for Graphviz.
- Matches the `FlowQueryResult.anytree` pattern.

### Event log for process mining

```python
bundle.event_log(label_fn=None)
```

When `pm4py` is **not** installed: returns a `pandas.DataFrame` with columns renamed for the XES standard:

| Column | Original | Notes |
|---|---|---|
| `case:concept:name` | `replay_id` | pm4py-canonical case ID column |
| `concept:name` | `label_fn(action)` or default | activity label |
| `time:timestamp` | `t` | datetime64[ns, UTC] |

When `pm4py` **is** installed: returns the same DataFrame (pm4py 2.7+ uses DataFrames as primary citizens, per their docs) and additionally registers it as an `EventLog` via `pm4py.format_dataframe()`. The returned object is usable directly with `pm4py.discover_petri_net_inductive()` etc.

### Label functions

```python
# mixpanel_headless._internal.replays.labels

def default_label_fn(action: UserAction) -> str:
    """Default activity label: '{action}:{tag_name}@{normalized_url}'.

    Coarse enough to align across sessions, specific enough to be meaningful
    for process mining. Strips query strings from URLs; normalizes path
    parameters (numeric IDs replaced with ':id').
    """

def selector_label_fn(attr: str = "data-testid") -> Callable[[UserAction], str]:
    """Returns a label_fn that uses a stable selector attribute when present.

    Best practice for projects that tag interactive elements:
        bundle.event_log(label_fn=selector_label_fn("data-testid"))

    Falls back to default_label_fn when the attribute is missing.
    """

def url_normalizer(url: str) -> str:
    """Strip query strings; replace numeric path segments with ':id'.

    /users/12345/profile → /users/:id/profile
    /products?ref=email  → /products
    """
```

---

## Endpoints used

### Insights Query (existing in headless)

```http
POST /api/query/insights
Content-Type: application/json
Authorization: Bearer <token>

{
  "bookmark": { ... InsightsBookmarkParams ... },
  "project_id": <id>,
  "workspace_id": <id>
}
```

Already wrapped by `Workspace.query()`. No new endpoint binding needed.

### Replays sign (new, undocumented but used by Mixpanel MCP)

```http
POST /app/projects/<project_id>/replays/sign/bulk
Content-Type: application/json
Authorization: Bearer <token>

{
  "replays": [
    {"replay_id": "...", "replay_env": "prod"},
    ...
  ]
}
```

Response:

```json
{
  "results": [
    {
      "replay_id": "...",
      "url": "https://cdn.mxpnl.com/srr-{us|eu|in}/{sha256(replay_id)}-{project_id}/",
      "query_string": "URLPrefix=...&Expires=...&KeyName=...&Signature=..."
    },
    ...
  ]
}
```

Auth: standard project-scoped (OAuth bearer or Service Account). Gated by `SESSION_RECORDING_SENSITIVE_DATA` project flag → 403 with `"Your project has sensitive replay data..."` message. Signature TTL: 5 minutes.

The single-variant endpoint `POST /app/projects/<id>/replays/sign` is **not** wrapped — the bulk endpoint with a one-element list covers it, and reducing surface area is preferred.

### CDN (Cloud CDN signed URL)

```http
GET https://cdn.mxpnl.com/srr-<region>/<prefix>/<NNNN>-<retention>.json?<query_string>
```

No auth header — the query string IS the credential. Returns a JSON array of rrweb events; 404 signals end of files.

---

## Security model

**Trust boundary**: the library never sees the HMAC signing key. Signing happens server-side at Mixpanel; the library presents standard OAuth/Service-Account credentials to `/replays/sign[/bulk]` and receives presigned URLs in response. Identical model to Cloud Storage / S3 presigned URLs.

**Bearer-credential handling**: the returned `query_string` IS a bearer credential for ~5 minutes. Anyone in possession of `url + query_string` can read the replay until the signature expires. The library's job is to keep that credential out of incidental contexts:

| Surface | Treatment |
|---|---|
| `SignedReplay.__repr__` | masks `query_string` as `"<redacted N chars>"` |
| `SignedReplay.__str__` | same masking |
| `mp replays sign` default output | redacted (URL prefix only); `--reveal-signed-urls` opts in with stderr warning |
| Library logging (any level) | no log statement includes `query_string`; URL prefix is logged at DEBUG only |
| Exception `details` dicts | URL prefix only, never query_string |
| Pickling / dataclass `asdict` | full value preserved (the user serializing has chosen to; we can't prevent it) |
| `mixpanel_headless.types.SignedReplay.to_dict()` | full value preserved with a top-level `_warning` key flagging the bearer nature |

**Coding-agent-specific concern**: agents often paste tool outputs into LLM transcripts and other logging pipelines. The default `__repr__` masking means an agent that prints `sign_replays(...)` output for reasoning context does not leak the bearer credential. The `--reveal-signed-urls` flag and explicit `.query_string` field access are the opt-in escape valves.

**Sensitive-data gating**: server-side enforcement of the `SESSION_RECORDING_SENSITIVE_DATA` project flag returns 403. The library translates to `SessionReplayAccessError` with structured `details = {"project_id": ..., "flag": "SESSION_RECORDING_SENSITIVE_DATA"}` and an actionable message naming the permission required.

**Open-source library specifically**: the library being open-source changes nothing in the security model. No secrets ship with the library; trust flows through the user's authenticated session. The signed-URL pattern is industry-standard.

---

## Performance and limits

| Operation | Target | Notes |
|---|---|---|
| `list_replays(user, 30d)` | ≤ 1 RTT | Single Insights query |
| `sign_replays(ids)` | ≤ 1 RTT | Bulk endpoint; no documented cap, MCP uses 20 for LLM context; headless can comfortably batch 100+ |
| `fetch_replay` (30 MB replay) | ≤ 5 s | Concurrent file fetch, 50-wide batches |
| `stream_replay` first-event latency | ≤ 1 s | Sign + first batch of files |
| `Replay.actions_df` materialization | ≤ 200 ms | Linear in rrweb event count; analyzer is the hot path |
| `ReplayBundle.actions_df` materialization | linear in `sum(n_actions)` | Cached after first access |
| `fetch_replays(N replays)` | parallel | Outer concurrency 4, inner concurrency 50 |
| pm4py inductive discovery | seconds for N≤1000 replays | bottleneck is process tree construction |

**No cap on bundle size in headless**. The MCP server's `MCP_MAX_REPLAYS_TO_PROCESS = 20` is an LLM-context-window concern, not a technical limit. `mixpanel-headless` users with 10,000 replays should be able to materialize a bundle, paying memory linearly. Document the rough memory budget (~2 MB per replay in `actions_df` at typical density).

**Streaming vs buffering tradeoff (documented)**:
- `fetch_replay` buffers all events. Memory ~ replay size (10–500 MB typical).
- `stream_replay` yields events incrementally with bounded memory (one batch of 50 files at a time, ~5–50 MB peak).
- The analyzer requires the full stream (DOM state propagation), so `analyze_replay` builds on `fetch_replay`, not `stream_replay`.

**CDN concurrency tuning**: the existing MCP fetcher uses `batch_size=50`. We adopt the same default. Expose `cdn_concurrency` parameter on `fetch_replay` for users on slow connections who want to lower it.

---

## Optional dependencies

`pyproject.toml` adds:

```toml
[project.optional-dependencies]
# ... existing extras ...

replay-mining = ["pm4py>=2.7"]
replay-ml = ["tslearn>=0.6"]
replay-all = ["mixpanel-headless[replay-mining,replay-ml]", "networkx>=3", "anytree>=2"]
```

The vendored rrweb analyzer ships in core (no extra needed) — it's pure-stdlib Python and adds no install weight.

`networkx` and `anytree` are reused from the existing flow-query optional extras (they are already optional deps of `mixpanel-headless` via `[flows]` or similar).

### Lazy import pattern

Every property that touches an optional dep follows this pattern:

```python
@property
def page_graph(self) -> "networkx.DiGraph":
    if self._page_graph_cache is not None:
        return self._page_graph_cache
    try:
        import networkx as nx
    except ImportError as e:
        raise ImportError(
            "ReplayBundle.page_graph requires networkx. "
            "Install with: pip install 'mixpanel-headless[replay-all]'"
        ) from e
    # ... build graph ...
    object.__setattr__(self, "_page_graph_cache", graph)
    return graph
```

This matches the existing `FlowQueryResult.graph` pattern.

---

## File layout

### New files (Phase 1)

```
src/mixpanel_headless/
├── _internal/
│   └── services/
│       └── replays.py                    # ReplaysService — orchestrates sign/fetch/discovery
│
├── workspace.py                           # MODIFIED — add 9 new methods
├── types.py                               # MODIFIED — add ReplaySummary, SignedReplay, ReplayEvent
├── exceptions.py                          # MODIFIED — add SessionReplayError hierarchy
├── __init__.py                            # MODIFIED — add new exports
│
└── cli/
    ├── main.py                            # MODIFIED — register replays_app
    └── commands/
        └── replays.py                     # NEW — Typer commands: list, events, sign, fetch

tests/
├── unit/
│   ├── test_replays_service.py            # NEW — ReplaysService unit tests (mocked HTTP)
│   ├── test_types_replay_summary.py       # NEW — dataclass shape
│   ├── test_types_signed_replay.py        # NEW — __repr__ masking, expires_at logic
│   └── test_workspace_replays.py          # NEW — Workspace method tests
├── pbt/
│   └── test_cdn_walker_pbt.py             # NEW — file-numbering walker invariants
├── integration/
│   └── test_replays_live.py               # NEW — live-marked: list, sign, fetch a known replay
└── fixtures/
    └── rrweb/
        └── sample-replay-001.json         # NEW — recorded rrweb event stream for parsing tests
```

### New files (Phase 2 — analyzer + ReplayBundle)

```
src/mixpanel_headless/
├── _internal/
│   └── replays/                           # NEW SUBPACKAGE
│       ├── __init__.py
│       ├── rrweb_analyzer.py              # VENDORED from analytics/backend/replays/rrweb_analyzer.py
│       ├── labels.py                      # NEW — default_label_fn, selector_label_fn, url_normalizer
│       └── aggregators.py                 # NEW — top_paths, dead_clicks, rage_clicks, etc.
│
├── workspace.py                           # MODIFIED — add fetch_replay, stream_replay, fetch_replays,
│                                          #            replays_for_user, analyze_replay
└── types.py                               # MODIFIED — add Replay, ReplayBundle, UserAction

tests/
├── unit/
│   ├── test_rrweb_analyzer.py             # PORTED from analytics/backend/replays/test_rrweb_analyzer.py
│   ├── test_replay_labels.py              # NEW — default + selector label stability
│   ├── test_types_replay.py               # NEW — Replay DataFrame projections
│   └── test_types_replay_bundle.py        # NEW — ReplayBundle aggregations, filters
├── pbt/
│   ├── test_replay_labels_pbt.py          # NEW — label_fn stability across DOM perturbations
│   └── test_types_replay_bundle_pbt.py    # NEW — DataFrame projection invariants
└── fixtures/
    └── rrweb/
        ├── sample-replay-002.json         # multi-page replay
        ├── sample-replay-003.json         # replay with errors and rage clicks
        └── sample-bundle-fixture.py       # builds a deterministic 10-replay ReplayBundle
```

### New files (Phase 3 — pm4py + tslearn)

```
src/mixpanel_headless/
├── _internal/
│   └── replays/
│       ├── pm4py_adapter.py               # NEW — event_log() pm4py wrapping
│       └── ml_adapter.py                  # NEW — cluster() using tslearn DTW

tests/
├── unit/
│   ├── test_pm4py_adapter.py              # NEW — gated on pm4py install marker
│   └── test_ml_adapter.py                 # NEW — gated on tslearn install marker
```

### Modified files (cross-phase summary)

| File | Phase | Change |
|---|---|---|
| `workspace.py` | 1, 2 | +9 methods (Phase 1: 4; Phase 2: 5) |
| `types.py` | 1, 2 | +6 dataclasses (Phase 1: 3; Phase 2: 3) |
| `exceptions.py` | 1 | +4 exception classes |
| `__init__.py` | 1, 2 | +10 exports |
| `cli/main.py` | 1 | +1 group registration |
| `pyproject.toml` | 3 | +2 optional-dependencies groups |

---

## Test strategy

### Unit tests

- **`test_replays_service.py`**: mocked `MixpanelAPIClient`. Verify `/replays/sign/bulk` request body shape, error mapping (403 → `SessionReplayAccessError`, 404 → `ReplayNotFoundError`, etc.), retry behavior.
- **`test_types_signed_replay.py`**: `__repr__` redaction, `expires_at` arithmetic, `is_expired` boundary.
- **`test_workspace_replays.py`**: mocked service + API client. Verify `list_replays` query shape (uses `query()`, groups on `$mp_replay_id` + `$mp_replay_retention_period`), validates argument combinations (distinct_id XOR replay_ids), error propagation.
- **`test_rrweb_analyzer.py`**: ported from `analytics/backend/replays/test_rrweb_analyzer.py`. Covers DOM tracker invariants, all incremental sources, debounce behavior, markdown output format.
- **`test_types_replay.py`** and **`test_types_replay_bundle.py`**: DataFrame projection columns, cache behavior, mode-aware `df` selection, `.to_dict()` serializability, `__repr__` shape.
- **`test_replay_labels.py`**: default and selector label stability across DOM perturbations; URL normalizer round-tripping.

### Property-based tests

- **`test_cdn_walker_pbt.py`**: invariants for the file-numbering walker. Given arbitrary 404 positions, the walker terminates correctly; never re-fetches a 404; respects `max_files`.
- **`test_replay_labels_pbt.py`**: label stability across DOM perturbations (Hypothesis generates trees with random attribute drift, label_fn outputs must match for semantically-equivalent elements).
- **`test_types_replay_bundle_pbt.py`**: DataFrame projection invariants. Given an arbitrary bundle (Hypothesis-generated list of `Replay` instances with random action streams):
  - `sessions_df` has exactly `len(replays)` rows.
  - `actions_df.groupby("replay_id").size().sum() == sum(len(r.actions) for r in bundle.replays)`.
  - `bundle.filter(predicate).replays` is a subset of `bundle.replays`.
  - `bundle.where(distinct_id=x).replays` is the same as `bundle.filter(lambda r: r.distinct_id == x).replays`.
  - `bundle.head(n)` returns at most `n` replays.

### Integration tests

- **`test_replays_live.py`** (marked `@pytest.mark.live`): against a real project with known replays. Tests:
  - `list_replays` returns at least one replay for a known active user.
  - `sign_replays` returns valid signed URLs.
  - A CDN fetch of the signed URL returns at least one rrweb event.
  - `analyze_replay` produces non-empty markdown output.
  - Sensitive-data 403 path tested against a sensitivity-flagged fixture project (if one exists).

### Mutation testing

`just mutate` targets:
- `src/mixpanel_headless/_internal/services/replays.py`
- `src/mixpanel_headless/_internal/replays/rrweb_analyzer.py`
- `src/mixpanel_headless/_internal/replays/labels.py`
- `src/mixpanel_headless/_internal/replays/aggregators.py`

Target: 80%+ mutation score.

### Fixture strategy

Three sample rrweb event streams checked into `tests/fixtures/rrweb/`:
- **sample-replay-001.json**: minimal — login + one click + navigation.
- **sample-replay-002.json**: multi-page — 5+ navigations, mixed interactions.
- **sample-replay-003.json**: pathological — console errors, rage clicks, dead clicks, long pauses.

A Python fixture builder at `tests/fixtures/rrweb/sample-bundle-fixture.py` constructs a deterministic 10-replay `ReplayBundle` for bundle-level tests.

Signed-URL handling is tested with mocked HTTP; real CDN fetches happen only in the live-marked integration tests.

---

## Phase plan

### Phase 1 — Discovery + Signed Access + `Replay` (1 PR, ~1,200 LoC)

**Ships**:
- `ReplaysService` orchestrating discovery + signing + fetching
- `Workspace.list_replays`, `sign_replays`, `sign_replay`, `events_for_replay`, `events_for_replays`, `fetch_replay`, `stream_replay`
- `ReplaySummary`, `SignedReplay`, `ReplayEvent`, `Replay` (with `events_df`, `mixpanel_df`, `pages_df`, `to_rrweb_player_json`) — note: `actions_df` requires the analyzer, so `Replay.actions` is empty in Phase 1; the analyzer arrives in Phase 2
- `SessionReplayError` hierarchy
- `mp replays {list, events, sign, fetch}` CLI
- Unit + PBT + integration test coverage to 90%+

**Does not ship**: vendored analyzer, `ReplayBundle`, action-level aggregations, graphs/trees, pm4py, tslearn.

**Why ship-able alone**: gives users the building blocks (signed URLs, raw rrweb streams) immediately. Users who want analysis can layer their own or wait for Phase 2.

**Estimated effort**: 1 week.

### Phase 2 — Vendored Analyzer + `ReplayBundle` (1 PR, ~1,500 LoC)

**Ships**:
- Vendored `rrweb_analyzer.py` at `_internal/replays/rrweb_analyzer.py` with full DOM tracker + event analyzer + markdown reporter
- `labels.py` with `default_label_fn`, `selector_label_fn`, `url_normalizer`
- `aggregators.py` with `top_paths`, `top_clicks`, `top_pages`, `dead_clicks`, `rage_clicks`, `long_pauses`
- `UserAction`, `Replay.actions_df`, `Replay.summary_markdown` populated by the analyzer
- `ReplayBundle` with all 7 DataFrame projections (`sessions_df`, `actions_df`, `events_df`, `mixpanel_df`, `pages_df`, `elements_df`, `transitions_df`)
- `ReplayBundle.page_graph`, `element_graph`, `path_tree` (lazy `networkx` + `anytree`)
- `ReplayBundle.filter`, `where`, `find_pattern`, `error_sessions`, `head`, `sample`, `join_mixpanel_events`, `summary_markdown`, `compare`
- `Workspace.fetch_replays`, `replays_for_user`, `analyze_replay`
- `mp replays analyze` and `mp replays for-user` CLI
- Unit + PBT + integration test coverage to 90%+; mutation score 80%+ on analyzer

**Estimated effort**: 1.5 weeks.

### Phase 3 — `pm4py` + `tslearn` extras (1 PR, ~500 LoC)

**Ships**:
- `pm4py_adapter.py` powering `ReplayBundle.event_log()` (returns DataFrame when pm4py is absent, pm4py-formatted DataFrame when present)
- `ml_adapter.py` powering `ReplayBundle.cluster(n, features)` (uses `tslearn.clustering.TimeSeriesKMeans` with DTW metric)
- Optional extras `replay-mining`, `replay-ml`, `replay-all` in `pyproject.toml`
- Unit tests gated on install markers
- A documentation page showing the pm4py integration end-to-end (BPMN discovery, conformance, variant analysis)

**Decision gate**: ship if there's user demand, otherwise defer indefinitely.

**Estimated effort**: 3-4 days.

### Phase 4 — Mobile session replays (future)

Out of scope for now. The discovery layer already works for mobile (`$mp_session_record` + `$mp_replay_id` are platform-agnostic), but the bytes layer and analyzer assume rrweb. Mobile uses a different format. Track at SR-230 in the analytics monorepo for upstream parity.

---

## Open questions and risks

### Endpoint stability

The `/replays/sign[/bulk]` endpoint is not in the public API reference but is used by Mixpanel's own MCP server. `mixpanel-headless` is now an official second client to mixpanel.com and is already at near-parity on undocumented API usage. Risk is real but bounded; the pre-release version notice already warns of API changes.

**Mitigation**: clear `CHANGELOG.md` entry noting the endpoint dependency. If the endpoint ever changes shape, the surface in `mixpanel-headless` is small (a single service file) and easy to update.

### Action labeling for process mining

The default `f"{action}:{tag_name}@{normalized_url}"` label is a starting point. Real-world replays may exhibit:

- DOM drift (i18n, A/B tests, dynamic content) producing different labels for semantically-identical actions.
- Granularity mismatches (per-button vs per-page-area vs per-feature).

**Mitigation**: ship the `label_fn=` escape valve from day one. Document the recommended SDK practice of tagging interactive elements with `data-testid`. Provide `selector_label_fn` as a one-liner for projects that do.

### Retention period edge cases

`$mp_replay_retention_period` is stamped at ingestion time. Older replays (pre-feature) won't have it. Orgs that change retention plans will have replays with different values.

**Mitigation**: when the property is missing, default to 30 days with a structured warning that includes the replay_id and a hint to upgrade Mixpanel SDK versions on the client side.

### Bundle memory budget

10,000 replays at ~2 MB each = ~20 GB just for raw rrweb events. Realistic bundle sizes:

- Single user, single month: ~10–50 replays — trivial
- All users for a feature, single week: ~500–5,000 replays — manageable with `actions_df` only
- All replays for a project for a quarter: 100k+ — needs streaming, not bundles

**Mitigation**: document the memory budget. `ReplayBundle` is for hundreds, not millions. For larger analysis, suggest `stream_replay` per replay + incremental aggregation.

### Concurrent CDN fetches

Mixpanel's CDN has rate limits we haven't characterized. The MCP server uses concurrency 50 internally.

**Mitigation**: adopt the same default; expose `cdn_concurrency` parameter for tuning; add a 429-aware retry in the CDN fetcher (already in `MixpanelAPIClient`).

### Signed URL expiration mid-stream

A slow consumer of `stream_replay` could outlive the 5-minute signature.

**Mitigation**: `re_sign_on_expiry=True` (default) catches the 403, re-signs, and continues. Caller can disable for tighter control.

### Backwards compatibility with future MCP analyzer changes

The MCP analyzer has open tickets (SR-229 pagination, SR-230 mobile). When upstream changes, our vendored copy will drift.

**Mitigation**: explicitly mark the analyzer as vendored with a source link in the module docstring; add a CI job (or docstring TODO) to periodically diff against upstream.

### sklearn / scipy install footprint

`tslearn` depends on `numpy`, `scipy`, `scikit-learn`, `joblib`. That's a heavy install.

**Mitigation**: extra is opt-in. Users who want clustering accept the install weight.

---

## Documentation

### `help.py` updates

Add Replay-related entries to the live documentation system so `python help.py Replay` and `python help.py ReplayBundle` work.

### `mixpanelyst` skill updates

Add a section on session replay analysis to the auto-triggered analytics skill. Example queries:

- "Show me what user X did in the last week"
- "Find all sessions where users clicked the upgrade button but didn't complete checkout"
- "What's the most common path users take through onboarding?"

### `dashboard-expert` skill

No changes — dashboards don't currently embed replays.

### New skill: `replay-analyst` (optional, Phase 2 or 3)

A purpose-built skill that auto-triggers on questions like "show me a replay", "analyze user behavior in this session", "what are users doing in feature X". Composes `replays_for_user`, `analyze_replay`, and `ReplayBundle` aggregations into LLM-friendly outputs.

### Plugin command `mixpanel-headless:replays`

A slash command for the `mixpanel-headless` Claude Code plugin: `/mixpanel-headless:replays USER [--from DATE] [--to DATE]` produces a markdown summary of a user's recent activity.

---

## References

### Internal source (analytics monorepo)

- `mcp_server/tools/replays.py` — MCP `Get-User-Replays-Data` tool definition
- `mcp_server/api/replays.py` — `ReplaysService` (the orchestration we're paralleling)
- `mcp_server/api/utils/replays.py` — `ReplayEvent` type
- `backend/replays/rrweb_analyzer.py` — analyzer to vendor (~600 LoC)
- `backend/replays/cdn_fetcher.py` — CDN walker pattern
- `backend/replays/query_utils.py` — events-in-window query builder (we re-implement via `Workspace.query()`)
- `backend/replays/constants.py` — GCS bucket map, MCP cap, retention defaults
- `webapp/app_api/projects/replays/views.py` — endpoint implementation, signing logic, sensitive-data gate
- `webapp/app_api/projects/replays/urls.py` — route definitions
- `webapp/app_api/projects/replays/utils.py` — `get_replay_gcs_prefix`
- `go/src/mixpanel.com/ingestion/api/handlers/record_session.go` — source of truth for `$mp_replay_retention_period` and CDN file naming format

### Public documentation

- [Session Replay overview](https://docs.mixpanel.com/docs/session-replay)
- [JavaScript SDK replay docs](https://docs.mixpanel.com/docs/tracking-methods/sdks/javascript/javascript-replay)
- [iOS SDK replay docs](https://docs.mixpanel.com/docs/tracking-methods/sdks/swift/swift-replay)
- [Android SDK replay docs](https://docs.mixpanel.com/docs/tracking-methods/sdks/android/android-replay)
- [Session Replay Privacy Controls](https://docs.mixpanel.com/docs/session-replay/session-replay-privacy-controls)

### Third-party libraries

- [rrweb event types](https://github.com/rrweb-io/rrweb/blob/master/packages/types/src/index.ts) — `EventType` and `IncrementalSource` enums
- [rrweb event recipe](https://rrweb.com/docs/recipes/dive-into-event) — event-shape walkthrough
- [pm4py documentation](https://pm4py.fit.fraunhofer.de/documentation) — process mining library
- [pm4py `format_dataframe`](https://pm4py.fit.fraunhofer.de/static/assets/api/2.7.8/pm4py.html) — DataFrame-to-EventLog adapter
- [pm4py `discover_petri_net_inductive`](https://pm4py.fit.fraunhofer.de/static/assets/api/2.7.11/generated/pm4py.discovery.discover_petri_net_inductive.html) — inductive miner
- [tslearn documentation](https://tslearn.readthedocs.io/) — time series clustering with DTW
- [networkx](https://networkx.org/) — graph algorithms (already a `mixpanel-headless` optional dep)
- [anytree](https://anytree.readthedocs.io/) — tree algorithms (already a `mixpanel-headless` optional dep)

### Headless precedent

- `src/mixpanel_headless/types.py:11434` — `FlowQueryResult` (the pattern we're matching)
- `src/mixpanel_headless/types.py:11073` — `FlowTreeNode` (tree projection pattern)
- `src/mixpanel_headless/workspace.py:2321` — `Workspace.query()` (the typed Insights API to use for discovery)
- `src/mixpanel_headless/workspace.py:3888` — `Workspace.query_flow()` (similar high-leverage query method)
- `src/mixpanel_headless/workspace.py:1246` — `Workspace.stream_events()` (streaming convention)
- `src/mixpanel_headless/_internal/services/` — service layer where `replays.py` lives
- `src/mixpanel_headless/cli/commands/cohorts.py` — CLI command pattern to mirror
- `specs/034-flow-query/plan.md` — closest spec precedent for shape and detail

### Research artifacts

- [Initial design report (2026-05-27)](https://storage.googleapis.com/jared-shares/2026-05/mixpanel-headless-session-replay-design.html)
