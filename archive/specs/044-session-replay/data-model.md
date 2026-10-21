# Phase 1 Data Model: Session Replay

**Feature**: 044-session-replay
**Date**: 2026-05-27

The session-replay feature adds six new in-memory types and one new exception hierarchy. No on-disk persistence: signed URLs are time-bounded bearer credentials handled in-process; `Replay` and `ReplayBundle` are computed-on-demand result types. This document is the entity ledger plus the state-transition table for the discovery → sign → fetch → analyze pipeline.

---

## 1. Reused entities (no changes)

| Entity | Source | Notes |
|--------|--------|-------|
| `ResultWithDataFrame` | `types.py` | Mixin used by every existing result class (e.g. `FlowQueryResult`). `Replay` and `ReplayBundle` inherit it; provides `.df`, `.to_dict()`, `.__repr_html__()` for notebook display. |
| `Workspace` | `workspace.py` | Public facade. Gains 9 new methods (Phase 1: 4; Phase 2: 5). No schema change. |
| `MixpanelAPIClient` | `_internal/api_client.py` | Gains `sign_replays(replay_ids, env)` method and one new error-mapping case (403 → `SessionReplayAccessError`). No schema change. |
| `Filter` / `InsightsBookmarkParams` | `_internal/query/` | Reused by `list_replays` and `events_for_replay` discovery queries. No schema change. |
| `QueryResult` | `types.py` | Returned by the underlying `Workspace.query()` call; `ReplaySummary` and `ReplayEvent` are constructed by walking its raw `.series` nested dict (skipping `$overall` rollups), **not** its single-level `.df` projection, which cannot represent the multi-key replay group-by. |
| `APIError`, `QueryError`, `ServerError` | `exceptions.py` | Parent classes for the new `SessionReplayError` hierarchy. |

---

## 2. New result types

All defined in `mixpanel_headless.types`.

### 2.1 `ReplaySummary`

Lightweight discovery handle. Does not include recording bytes. Returned by `Workspace.list_replays()`.

```python
@dataclass(frozen=True)
class ReplaySummary(ResultWithDataFrame):
    """Discovery handle for a single replay.

    Returned by Workspace.list_replays(). Use Workspace.fetch_replay(s.replay_id)
    to materialize the full Replay with rrweb event bytes.
    """
    replay_id: str
    distinct_id: str | None
    project_id: int
    start_time: int          # unix ms; from $mp_session_record event timestamp
    retention_days: int      # from $mp_replay_retention_period; defaults to 30
```

**Validation**:
- `replay_id` MUST be non-empty.
- `project_id` MUST be positive.
- `start_time` MUST be a valid unix ms timestamp (positive int).
- `retention_days` MUST be in `{1, 7, 30, 90}` (the allowed Mixpanel retention values).

---

### 2.2 `SignedReplay`

Time-bounded CDN access handle. Bearer-credential semantics enforced via `__repr__` masking, `expires_at` arithmetic, and `is_expired` boolean.

```python
@dataclass(frozen=True)
class SignedReplay:
    """Signed CDN access for one replay.

    SECURITY: query_string is a bearer credential valid for ~5 minutes.
    Treat it like a session token. __repr__ masks it.
    """
    replay_id: str
    url: str              # CDN prefix, trailing slash; e.g. "https://cdn.mxpnl.com/srr-us/<sha>-<pid>/"
    query_string: str     # signed credential; MASKED IN __repr__
    env: Literal["prod", "dev"]
    signed_at: float      # unix seconds (for expiration arithmetic)

    def __repr__(self) -> str:
        masked = f"<redacted {len(self.query_string)} chars>"
        return (
            f"SignedReplay(replay_id={self.replay_id!r}, url={self.url!r}, "
            f"query_string={masked!r}, env={self.env!r}, signed_at={self.signed_at!r})"
        )

    __str__ = __repr__

    @property
    def expires_at(self) -> float:
        """Approximate expiration timestamp (signed_at + 5 minutes)."""
        return self.signed_at + 300

    @property
    def is_expired(self) -> bool:
        return time.time() >= self.expires_at

    def to_dict(self) -> dict[str, Any]:
        """Full serialization including the bearer credential.

        WARNING: includes the full bearer credential. The returned dict carries
        a top-level `_warning` key noting the bearer nature.
        """
        return {
            "_warning": "query_string is a bearer credential valid for ~5 minutes",
            "replay_id": self.replay_id,
            "url": self.url,
            "query_string": self.query_string,
            "env": self.env,
            "signed_at": self.signed_at,
        }
```

**Validation**:
- `query_string` MUST be non-empty (server contract).
- `url` MUST end with `/`.
- `env` MUST be one of `{"prod", "dev"}`.
- `signed_at` MUST be a non-negative float (seconds since epoch).

---

### 2.3 `UserAction`

Normalized user action extracted from rrweb events by the vendored analyzer. The atomic unit `ReplayBundle` aggregates over.

```python
@dataclass(frozen=True)
class UserAction:
    """Normalized user action from rrweb event stream.

    Produced by the vendored rrweb analyzer (Phase 2). The atomic unit
    bundle aggregations operate over.
    """
    timestamp: int           # unix ms
    action: Literal[
        "click", "input", "scroll", "navigate",
        "select", "console_error", "viewport_resize",
        "touch_start", "media_interaction",
    ]
    target_node_id: int | None
    target_desc: str         # e.g. 'button "Sign in"', 'input[type=email]'
    url: str | None          # active page URL at the time of the action
    metadata: dict[str, Any] # action-specific extras (text_length, is_checked, etc.)
    description: str = ""    # full phrase for the markdown timeline,
                             # e.g. 'Clicked button "Sign in"', 'Scrolled'
```

**Validation**:
- `timestamp` MUST be a valid unix ms timestamp.
- `target_desc` MUST be non-empty (analyzer always produces a description, even if generic).
- `description` is the analyzer's full human-readable phrase; renderers fall back to `target_desc` when it is empty (hand-built fixtures).
- `metadata` keys depend on `action`; documented in the analyzer module docstring.

---

### 2.4 `ReplayEvent`

A Mixpanel event that occurred during a replay's time window. Optional enrichment on `Replay` / `ReplayBundle`.

```python
@dataclass(frozen=True)
class ReplayEvent(ResultWithDataFrame):
    """Mixpanel event in a replay's time window."""
    replay_id: str
    event_name: str
    event_time: int          # unix seconds (Mixpanel native)
    properties: dict[str, Any] | None
```

**Validation**:
- `replay_id`, `event_name` MUST be non-empty.
- `event_time` MUST be a valid unix seconds timestamp.

---

### 2.5 `Replay`

Single fully-materialized session. Conceptually a `ReplayBundle` of size 1; the same DataFrame projections are available on both.

```python
@dataclass(frozen=True)
class Replay(ResultWithDataFrame):
    """Single fully-materialized session replay."""
    replay_id: str
    distinct_id: str | None
    project_id: int
    start_time: int          # unix ms
    end_time: int            # unix ms
    retention_days: int

    rrweb_events: list[dict[str, Any]]   # raw rrweb events, timestamp-sorted
    actions: list[UserAction]            # populated by analyzer (Phase 2);
                                         # empty list in Phase 1
    mixpanel_events: list[ReplayEvent]   # populated only when fetched
                                         # with include_mixpanel_events=True

    # Cached projections (lazy, computed on first access)
    _events_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _actions_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _mixpanel_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)

    # DataFrame projections
    @property
    def events_df(self) -> pd.DataFrame: ...
    @property
    def actions_df(self) -> pd.DataFrame: ...
    @property
    def mixpanel_df(self) -> pd.DataFrame: ...
    @property
    def df(self) -> pd.DataFrame:
        """Default projection: actions_df."""
        return self.actions_df

    # Convenience accessors
    @property
    def duration_seconds(self) -> float: ...
    @property
    def errors(self) -> pd.DataFrame: ...
    @property
    def summary_markdown(self) -> str: ...
    def page_path(self) -> list[str]: ...
    def clicks_on(self, predicate: Callable[[UserAction], bool]) -> pd.DataFrame: ...
    def to_rrweb_player_json(self) -> list[dict[str, Any]]: ...
```

**DataFrame column contracts** (see `quickstart.md` for full schemas):

- `events_df`: `t`, `type`, `source`, `mouse_type`, `target_node_id`, `url`, `raw`
- `actions_df`: `t`, `action`, `target_node_id`, `target_desc`, `description`, `url`, `metadata`
- `mixpanel_df`: empty unless `include_mixpanel_events=True`; columns match `ReplayBundle.mixpanel_df`

**Analyzer output**: the analyzer populates `actions`; `summary_markdown` renders each action's full `description`, collapsing consecutive duplicates into a `(×N)` suffix. `page_path()` derives the navigation URL sequence from the `navigate` actions.

---

### 2.6 `ReplayBundle`

Collection of `Replay` objects with cross-session DataFrame projections. The high-leverage type.

```python
@dataclass(frozen=True)
class ReplayBundle(ResultWithDataFrame):
    """Collection of replays with cross-session projections."""
    replays: list[Replay]
    computed_at: str         # ISO 8601 timestamp
    project_id: int

    # Cached DataFrame projections
    _sessions_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _actions_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _events_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _mixpanel_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)
    _elements_df_cache: pd.DataFrame | None = field(default=None, repr=False, kw_only=True)

    # DataFrame projections
    @property
    def sessions_df(self) -> pd.DataFrame: ...
    @property
    def actions_df(self) -> pd.DataFrame: ...
    @property
    def events_df(self) -> pd.DataFrame: ...
    @property
    def mixpanel_df(self) -> pd.DataFrame: ...
    @property
    def elements_df(self) -> pd.DataFrame: ...
    @property
    def df(self) -> pd.DataFrame:
        """Default projection: sessions_df."""
        return self.sessions_df

    # Aggregations (return DataFrames; top_clicks/elements_df exclude focus)
    def top_clicks(self, n: int = 10) -> pd.DataFrame: ...
    def rage_clicks(self, threshold: int = 3, window_ms: int = 1000) -> pd.DataFrame: ...
    def long_pauses(self, threshold_s: float = 10) -> pd.DataFrame: ...

    # Filters (return new ReplayBundle — immutable semantics)
    def filter(self, predicate: Callable[[Replay], bool]) -> "ReplayBundle": ...
    def where(self, *, distinct_id=None, contains_url=None, has_event=None,
              min_duration_s=None, max_duration_s=None) -> "ReplayBundle": ...
    def find_pattern(self, action_sequence: list[str], *, label_fn=None) -> "ReplayBundle": ...
    def error_sessions(self) -> "ReplayBundle": ...
    def head(self, n: int = 5) -> "ReplayBundle": ...
    def sample(self, n: int = 5, seed: int | None = None) -> "ReplayBundle": ...

    # Enrichment
    def join_mixpanel_events(self, properties: list[str] | None = None) -> "ReplayBundle": ...

    # Summary / comparison
    @property
    def summary_markdown(self) -> str: ...
    def compare(self, other: "ReplayBundle") -> pd.DataFrame: ...
```

**DataFrame column contracts** (full schemas in `quickstart.md`):

| Projection | Grain | Key columns |
|------------|-------|-------------|
| `sessions_df` | one row per replay | `replay_id`, `distinct_id`, `start_time`, `end_time`, `duration_s`, `retention_days`, `n_events`, `n_actions`, `n_clicks`, `n_inputs`, `n_pages`, `n_errors`, `n_mp_events`, `entry_url`, `exit_url` |
| `actions_df` | long format, all replays | `replay_id`, `t`, `action`, `target_node_id`, `target_desc`, `description`, `url`, `metadata` |
| `events_df` | long format, raw rrweb | `replay_id`, `t`, `type`, `source`, `mouse_type`, `target_node_id`, `url`, `raw` |
| `mixpanel_df` | long format, Mixpanel events | `replay_id`, `t`, `event_name`, `properties` |
| `elements_df` | per element across all replays | `target_desc`, `url` (normalized), `n_clicks`, `n_unique_replays` |

---

## 3. Exception hierarchy

All defined in `mixpanel_headless.exceptions`.

```python
class SessionReplayError(APIError):
    """Base for session-replay-specific errors."""

class SessionReplayAccessError(SessionReplayError):
    """The project has SESSION_RECORDING_SENSITIVE_DATA enabled and the
    caller lacks sensitive-data access.

    details = {"project_id": int, "flag": "SESSION_RECORDING_SENSITIVE_DATA"}
    """

class SignedURLExpiredError(SessionReplayError):
    """A signed URL passed to a CDN fetch has expired (5-minute TTL).
    Re-sign and retry; or set re_sign_on_expiry=True on stream_replay.
    """

class ReplayNotFoundError(SessionReplayError):
    """A specific replay_id was requested but no CDN files were found.
    The replay may have aged out of retention, never been recorded,
    or been deleted.
    """
```

**Inheritance**: every new class subclasses `APIError` via `SessionReplayError`. Existing `handle_errors` decorator in `cli/utils.py` already catches `APIError` and maps to exit codes — no CLI surface changes needed.

---

## 4. State transitions

### 4.1 Discovery → Sign → Fetch pipeline

```
distinct_id + date range
    │
    ▼
list_replays() ── 1 RTT to /api/query/insights
    │
    ▼
list[ReplaySummary]
    │
    ▼ (per replay_id, or batched)
sign_replays() ── 1 RTT to /app/projects/<id>/replays/sign/bulk
    │
    ├─ 403 sensitive-data flag ─► SessionReplayAccessError
    └─ 200 ────────────────────► list[SignedReplay]
                                       │
                                       ▼
                                  fetch_replay() / stream_replay()
                                       │
                                       ├─ Walk CDN files NNNN-RR.json in parallel
                                       ├─ 404 on file 0000 ─► ReplayNotFoundError
                                       ├─ 404 mid-walk ────► clean termination (end sentinel)
                                       ├─ 403 mid-walk ────► re-sign + retry (default ON)
                                       │                     OR SignedURLExpiredError (if OFF)
                                       └─ 200 ──────────────► concatenate, sort by t
                                                                  │
                                                                  ▼
                                                              Replay (Phase 1: actions=[])
                                                                  │
                                                                  ▼ (Phase 2)
                                                              analyzer.parse(rrweb_events)
                                                                  │
                                                                  ▼
                                                              Replay (with actions populated)
```

### 4.2 `ReplayBundle` construction

```
list[Replay]
    │
    ▼
ReplayBundle(replays=..., computed_at=now, project_id=...)
    │
    ▼ (lazy on first access)
    ├─ sessions_df  (one row per replay; derived columns: n_events, duration_s, ...)
    ├─ actions_df   (long format)
    ├─ events_df    (long format)
    ├─ mixpanel_df  (empty unless join_mixpanel_events was called)
    └─ elements_df  (aggregated by target_desc + normalized url, focus excluded)
```

### 4.3 `ReplayBundle` filter chain

Filters return new bundles. Original is unchanged. Caches are NOT shared across bundles (each new bundle has its own cache slots).

```
bundle (10 replays)
    │
    ├─ .where(distinct_id="user-42")  ── new bundle (subset)
    │       │
    │       ├─ .head(5)                ── new bundle (≤5 replays)
    │       └─ .find_pattern([...])    ── new bundle (subset matching pattern)
    │
    └─ .filter(lambda r: r.duration_seconds > 60)  ── new bundle
            │
            └─ .sample(n=3, seed=42)               ── new bundle (3 deterministic replays)
```

---

## 5. Invariants (verified by PBT)

These properties are tested via Hypothesis in `tests/pbt/test_types_replay_bundle_pbt.py`:

- **Sessions cardinality**: `len(bundle.sessions_df) == len(bundle.replays)` for every bundle.
- **Actions sum**: `bundle.actions_df.groupby("replay_id").size().sum() == sum(len(r.actions) for r in bundle.replays)`.
- **Filter subset**: `set(r.replay_id for r in bundle.filter(p).replays) ⊆ set(r.replay_id for r in bundle.replays)`.
- **Filter ↔ where equivalence**: `bundle.where(distinct_id=x).replays == bundle.filter(lambda r: r.distinct_id == x).replays`.
- **Head bound**: `len(bundle.head(n).replays) <= min(n, len(bundle.replays))`.
- **Sample bound**: `len(bundle.sample(n, seed=k).replays) == min(n, len(bundle.replays))`.
- **Sample determinism**: `bundle.sample(n, seed=k).replays == bundle.sample(n, seed=k).replays` (same seed, same output).
- **Immutability**: applying any filter / sample method does NOT change the original `bundle.replays` list.
- **Label stability**: `default_label_fn(a) == default_label_fn(a')` whenever `a` and `a'` differ only in `metadata` keys not used by the label.

---

## 6. Validation rules summary

| Type | Validation |
|------|------------|
| `ReplaySummary` | `replay_id` non-empty; `project_id > 0`; `start_time > 0`; `retention_days ∈ {1, 7, 30, 90}` |
| `SignedReplay` | `url` ends with `/`; `query_string` non-empty; `env ∈ {"prod", "dev"}`; `signed_at >= 0` |
| `UserAction` | `timestamp > 0`; `target_desc` non-empty; `action` in the documented Literal set |
| `ReplayEvent` | `replay_id`, `event_name` non-empty; `event_time > 0` |
| `Replay` | `start_time <= end_time`; `rrweb_events` timestamp-sorted; `retention_days` matches summary |
| `ReplayBundle` | `replays` not None (can be empty); `computed_at` is ISO 8601; all replays share `project_id` |
| `events_for_replay` | `len(event_properties) <= 5` (Insights group-by cap, see R-10) |
