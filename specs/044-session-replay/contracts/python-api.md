# Contract: Python API

**Feature**: 044-session-replay
**Surface**: `mixpanel_headless` public exports
**Audience**: Developers using `mixpanel-headless` as a Python library

This contract enumerates every new public symbol and its signature. The companion `data-model.md` documents the shape of returned types; `error-messages.md` documents stable error messages.

---

## 1. `Workspace` methods

All methods added to `mixpanel_headless.workspace.Workspace`. Group by phase.

### Phase 1: Discovery

#### `list_replays`

```python
def list_replays(
    self,
    *,
    distinct_id: str | None = None,
    replay_ids: list[str] | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    limit: int = 100,
) -> list[ReplaySummary]:
    """List replays for a user, or hydrate summaries for explicit IDs.

    Exactly one of `distinct_id` or `replay_ids` MUST be provided.
    When `distinct_id` is given, `from_date` and `to_date` are required.

    Args:
        distinct_id: Mixpanel user identifier. Mutually exclusive with replay_ids.
        replay_ids: Explicit list of replay IDs to hydrate. Mutually exclusive
            with distinct_id; from_date/to_date are inferred.
        from_date: ISO date string (YYYY-MM-DD). Required when distinct_id is set.
        to_date: ISO date string (YYYY-MM-DD). Required when distinct_id is set.
        limit: Maximum summaries to return. Default 100.

    Returns:
        List of ReplaySummary, possibly empty.

    Raises:
        ValueError: If neither or both of distinct_id and replay_ids are provided,
            or if distinct_id is set without from_date/to_date.
        QueryError: For Insights API failures.
    """
```

#### `events_for_replay`

```python
def events_for_replay(
    self,
    replay_id: str,
    *,
    event_properties: list[str] | None = None,
) -> list[ReplayEvent]:
    """Mixpanel events that occurred during a replay's time window.

    Filters on $mp_replay_id, excludes $mp_session_record itself.

    Args:
        replay_id: The replay ID to fetch events for.
        event_properties: Up to 5 additional event properties to include as
            group keys. Default None (no extras).

    Returns:
        List of ReplayEvent in time order.

    Raises:
        ValueError: If len(event_properties) > 5.
        QueryError: For Insights API failures.
    """
```

#### `events_for_replays`

```python
def events_for_replays(
    self,
    replay_ids: list[str],
    *,
    event_properties: list[str] | None = None,
) -> dict[str, list[ReplayEvent]]:
    """Batched version of events_for_replay. Single round-trip.

    Args:
        replay_ids: List of replay IDs.
        event_properties: Up to 5 additional event properties.

    Returns:
        Dict mapping replay_id to its event list. Missing keys for replays
        with no events.
    """
```

### Phase 1: Signed CDN access

#### `sign_replay`

```python
def sign_replay(
    self,
    replay_id: str,
    *,
    env: Literal["prod", "dev"] = "prod",
) -> SignedReplay:
    """Single-replay signing sugar over sign_replays."""
```

#### `sign_replays`

```python
def sign_replays(
    self,
    replay_ids: list[str],
    *,
    env: Literal["prod", "dev"] = "prod",
) -> list[SignedReplay]:
    """Sign multiple replays via POST /app/projects/<id>/replays/sign/bulk.

    Args:
        replay_ids: List of replay IDs. No documented maximum.
        env: "prod" or "dev". Default "prod".

    Returns:
        List of SignedReplay, one per requested ID, in the same order.

    Raises:
        SessionReplayAccessError: 403 with SESSION_RECORDING_SENSITIVE_DATA flag set.
        APIError: Other 4xx/5xx responses.
    """
```

### Phase 1: Fetch

#### `fetch_replay`

```python
def fetch_replay(
    self,
    replay_id: str,
    *,
    env: Literal["prod", "dev"] = "prod",
    retention_days: int | None = None,
    max_files: int = 500,
    include_mixpanel_events: bool = False,
    event_properties: list[str] | None = None,
    cdn_concurrency: int = 50,
) -> Replay:
    """Sign + fetch + parse + return a populated Replay.

    When retention_days is None, list_replays is consulted to discover
    the actual retention period. Pass explicitly to skip the lookup.

    Args:
        replay_id: The replay to fetch.
        env: "prod" or "dev".
        retention_days: 1, 7, 30, or 90. Auto-discovered if None.
        max_files: Hard upper bound on CDN file walk. Default 500.
        include_mixpanel_events: Trigger a follow-up Insights query to populate
            Replay.mixpanel_events. Default False.
        event_properties: Up to 5 properties for the Mixpanel join query.
        cdn_concurrency: Parallel batch size for CDN fetches. Default 50.

    Returns:
        Replay with rrweb_events populated. In Phase 1, actions is always empty.

    Raises:
        ReplayNotFoundError: First CDN file (0000-N.json) returned 404.
        SessionReplayAccessError: Sensitive-data flag set.
        SignedURLExpiredError: Signed URL expired mid-fetch (rare; fetch_replay
            signs and fetches in immediate succession).
    """
```

#### `stream_replay`

```python
def stream_replay(
    self,
    replay_id: str,
    *,
    env: Literal["prod", "dev"] = "prod",
    retention_days: int | None = None,
    max_files: int = 500,
    re_sign_on_expiry: bool = True,
    cdn_concurrency: int = 50,
) -> Iterator[dict[str, Any]]:
    """Yield rrweb events one at a time, batched-parallel under the hood.

    Fetches files in batches of `cdn_concurrency`. Within a batch, yields
    events in timestamp order. Does not buffer across batches.

    Args:
        replay_id: The replay to stream.
        env: "prod" or "dev".
        retention_days: 1, 7, 30, or 90. Auto-discovered if None.
        max_files: Hard upper bound on CDN file walk. Default 500.
        re_sign_on_expiry: When True (default), catches 403 indicating
            signature expiration and re-signs transparently. When False,
            propagates SignedURLExpiredError.
        cdn_concurrency: Parallel batch size. Default 50.

    Yields:
        Raw rrweb event dicts in timestamp order.

    Raises:
        ReplayNotFoundError: First CDN file returned 404.
        SignedURLExpiredError: Signed URL expired and re_sign_on_expiry=False.
        SessionReplayAccessError: Sensitive-data flag set.
    """
```

### Phase 2: Bundle

#### `fetch_replays`

```python
def fetch_replays(
    self,
    replay_ids: list[str],
    *,
    env: Literal["prod", "dev"] = "prod",
    max_files: int = 500,
    include_mixpanel_events: bool = False,
    event_properties: list[str] | None = None,
    concurrency: int = 4,
    cdn_concurrency: int = 50,
) -> ReplayBundle:
    """Sign + fetch + parse N replays in parallel; return a ReplayBundle.

    Args:
        replay_ids: Replays to fetch.
        concurrency: How many replays to fetch in parallel. Default 4.
        cdn_concurrency: Per-replay CDN batch size. Default 50.
        (other args same as fetch_replay)

    Returns:
        ReplayBundle with all requested replays populated.
    """
```

#### `replays_for_user`

```python
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
    """Discovery + fetch in one call. The "show me this user's recent
    activity" convenience method.

    Args:
        distinct_id: Mixpanel user identifier.
        from_date, to_date: ISO date window.
        limit: Maximum replays. Default 100.
        include_mixpanel_events: Default True for this convenience method.
        event_properties: Up to 5 properties for Mixpanel join.

    Returns:
        ReplayBundle, possibly empty if no replays exist in the window.
    """
```

#### `analyze_replay`

```python
def analyze_replay(self, replay_id: str) -> str:
    """Sign + fetch + run the analyzer + return the markdown timeline.

    Sugar for: `ws.fetch_replay(replay_id).summary_markdown`.

    Returns:
        Markdown string suitable for stdout or LLM consumption.
    """
```

---

## 2. Result types

Documented in detail in [data-model.md](../data-model.md). Quick reference:

| Type | Returned by | Key feature |
|------|-------------|-------------|
| `ReplaySummary` | `list_replays` | Discovery handle, no bytes |
| `SignedReplay` | `sign_replay(s)` | Time-bounded CDN access, bearer credential |
| `UserAction` | `Replay.actions[i]` | Normalized action from analyzer |
| `ReplayEvent` | `events_for_replay(s)`, `Replay.mixpanel_events[i]` | Mixpanel event in window |
| `Replay` | `fetch_replay` | Single materialized session |
| `ReplayBundle` | `fetch_replays`, `replays_for_user` | Collection with DataFrame / graph / tree projections |

---

## 3. Exception hierarchy

```python
APIError                              # existing
└── SessionReplayError                # NEW base
    ├── SessionReplayAccessError      # 403 with SESSION_RECORDING_SENSITIVE_DATA
    ├── SignedURLExpiredError         # 5-minute TTL expired
    └── ReplayNotFoundError           # CDN walk found nothing
```

See [error-messages.md](error-messages.md) for stable error messages.

---

## 4. Label functions

Defined in `mixpanel_headless._internal.replays.labels`. Re-exported from `mixpanel_headless.types`.

```python
def default_label_fn(action: UserAction) -> str:
    """Default activity label: f"{action}:{tag_name}@{normalized_url}".

    URL normalization: strip query strings; replace numeric path segments
    with ':id' (e.g. /users/12345/profile → /users/:id/profile).
    """

def selector_label_fn(attr: str = "data-testid") -> Callable[[UserAction], str]:
    """Returns a label_fn that prefers a stable selector attribute when
    present, falling back to default_label_fn otherwise.

    Example:
        bundle.top_paths(label_fn=selector_label_fn("data-testid"))
    """

def url_normalizer(url: str) -> str:
    """Strip query strings; replace numeric path segments with ':id'."""
```

---

## 5. Public exports (`__init__.py`)

```python
# Added to mixpanel_headless.__all__:
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
"default_label_fn",
"selector_label_fn",
```

---

## 6. Phase boundaries (Python API)

| Method | Phase | Notes |
|--------|-------|-------|
| `list_replays` | 1 | Required for everything else |
| `events_for_replay(s)` | 1 | Required for `include_mixpanel_events` |
| `sign_replay(s)` | 1 | |
| `fetch_replay` | 1 | `Replay.actions` empty in Phase 1 |
| `stream_replay` | 1 | |
| `fetch_replays` | 2 | Requires `ReplayBundle` |
| `replays_for_user` | 2 | Sugar over `list_replays` + `fetch_replays` |
| `analyze_replay` | 2 | Requires vendored analyzer |
