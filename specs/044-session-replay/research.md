# Phase 0 Research: Session Replay

**Feature**: 044-session-replay
**Date**: 2026-05-27
**Status**: Complete — no NEEDS CLARIFICATION markers in plan.md remain.

The source design (`context/session-replay-plan.md`) already settled the load-bearing decisions through code-archaeology against the analytics monorepo, Mixpanel's MCP server, and the rrweb upstream. This document records the decisions, their rationale, and the rejected alternatives so reviewers can audit without re-deriving.

---

## R-1. Discovery via Insights Query API, not legacy Segmentation

**Decision**: `list_replays` issues a single `Workspace.query()` call against `$mp_session_record` events, grouped on `$mp_replay_id` AND `$mp_replay_retention_period` AND `$time`. Returns shape into `list[ReplaySummary]`.

**Rationale**:
- The Phase 029 typed Insights surface (`Workspace.query()`) already supports the required grouping and is the project's standard query path.
- `$mp_replay_retention_period` is the source of truth for per-replay retention (set at ingestion). Grouping on it makes the retention value available without a second round-trip.
- The Insights group-by limit is high enough (>5) to add optional event_properties for `events_for_replay` without contortions.

**Alternatives considered**:
- **Legacy Segmentation API**: rejected — Phase 029 deprecated it for typed callers and the grouping API there is weaker.
- **Direct enumeration via `/api/2.0/events`**: rejected — no group-by support, wastes bandwidth on event bodies.
- **Cohort-driven discovery (`replays_for_cohort`)**: deferred — adds a join layer with no clear demand yet.

---

## R-2. Signed CDN access uses the bulk endpoint always

**Decision**: All signing goes through `POST /app/projects/<id>/replays/sign/bulk`, even single-replay signing. `sign_replay(id)` is a thin wrapper that passes a one-element list to `sign_replays([id])`.

**Rationale**:
- Reduces surface area: one endpoint binding, one error-mapping path, one set of tests.
- The bulk endpoint accepts single-element lists without overhead.
- Future batch optimizations (e.g. signing a whole bundle's worth of IDs upfront) need no extra plumbing.

**Alternatives considered**:
- **Wrap both `/replays/sign` and `/replays/sign/bulk`**: rejected — duplicates code, doubles the error-mapping surface for no caller-visible benefit.
- **Issue parallel single-replay sign requests for bundles**: rejected — N round-trips where 1 suffices.

---

## R-3. CDN file walker terminates on first 404, bounded by `max_files`

**Decision**: The CDN walker fetches files `0000-N.json`, `0001-N.json`, ... in parallel batches of 50. The first 404 in numeric order is the end-of-recording sentinel; the walker terminates cleanly without retry. `max_files=500` (default) is a hard upper bound in case the sentinel is somehow missed.

**Rationale**:
- 404 as end-of-recording is the documented contract from `go/src/mixpanel.com/ingestion/api/handlers/record_session.go`. Retrying it is wrong.
- Parallel batches of 50 match Mixpanel's MCP server's existing CDN concurrency; matches their server-side capacity planning.
- `max_files=500` covers 99.99% of real replays (a 5-second replay fits in 1 file; a 90-minute replay fits in ~50). 500 is the safety belt.

**Alternatives considered**:
- **Treat 404 as transient, retry with exponential backoff**: rejected — masks the sentinel and burns CDN bandwidth.
- **Walk serially, one file at a time**: rejected — multiplies wall-clock time by 50× for large replays.
- **No `max_files` bound**: rejected — a corrupted recording (e.g. file `0042-30.json` exists but `0043-30.json` was never uploaded then someone uploaded `1000-30.json` by accident) could runaway-loop the walker.

---

## R-4. Streaming variant re-signs on expiration by default

**Decision**: `stream_replay(replay_id, re_sign_on_expiry=True)` catches a 403 with an "expired" signature reason mid-stream, re-signs the prefix transparently, and continues. Setting `re_sign_on_expiry=False` propagates a distinct `SignedURLExpiredError`.

**Rationale**:
- A 5-minute TTL is enough for `fetch_replay` (signs + fetches in immediate succession) but tight for `stream_replay` consumers that process events as they arrive (e.g. an LLM digesting a 1-hour session).
- Re-signing is cheap (one API call) and the prefix URL is stable across re-signs (only the `query_string` rotates).
- Power users (e.g. a deterministic test harness, a strict-budget agent) can disable to surface the timing issue.

**Alternatives considered**:
- **Never re-sign, always raise**: rejected — surfaces a transient timing issue as a hard failure for the common case.
- **Always re-sign silently, no opt-out**: rejected — hides the timing issue from callers who legitimately want determinism.
- **Pre-extend TTL via a custom signing endpoint**: rejected — would require server-side changes to Mixpanel's signing service.

---

## R-5. `SignedReplay.__repr__` masks the credential

**Decision**: `SignedReplay.__repr__` and `__str__` replace the `query_string` field with `<redacted N chars>`. The library NEVER logs the credential at any level. The CLI defaults to redacted output; `--reveal-signed-urls` is the single opt-in.

**Rationale**:
- Coding agents routinely paste tool outputs into LLM transcripts. A default `repr` that includes a 5-minute bearer credential turns every `print(sign_replays(...))` into a leak vector.
- Mixpanel's own MCP server treats signed URLs as bearer credentials. Headless should match.
- The `--reveal-signed-urls` flag is a deliberate friction-point: every use emits a stderr warning naming the bearer-credential semantics. Hard to miss in transcripts.

**Alternatives considered**:
- **Default to full disclosure, document the security note**: rejected — documentation does not protect against accidental leaks; defaults do.
- **Encrypt the `query_string` field, decrypt only on URL construction**: rejected — adds key-management surface for a 5-minute credential.
- **Refuse to construct `SignedReplay` in dataclass form, only return URL strings**: rejected — loses the `expires_at` / `is_expired` accessors and breaks the dataclass-shaped API expected by typed callers.

---

## R-6. Vendored rrweb analyzer (pure-stdlib, no third-party deps)

**Decision**: Port `analytics/backend/replays/rrweb_analyzer.py` (~600 LoC) into `_internal/replays/rrweb_analyzer.py`. Mark the file with a docstring naming the upstream source and a comment block on the divergence policy.

**Rationale**:
- The analyzer is the load-bearing piece for `Replay.actions` and `ReplayBundle.actions_df`. Without it, "fetch the bytes" is the only shippable capability.
- Cross-repo dependency on the analytics monorepo is impossible (private repo, no public release surface).
- A separate PyPI package would create a 3-way release dance (analytics monorepo → standalone package → `mixpanel-headless`) with no clear owner.
- The analyzer is pure stdlib (no `numpy`, no `pydantic`, no `httpx`). Vendoring adds zero install weight.

**Alternatives considered**:
- **Standalone PyPI package**: rejected — release coordination cost, no clear owner.
- **Direct dependency on analytics monorepo**: rejected — private, would require publishing the monorepo or a sub-tree.
- **Re-implement from scratch**: rejected — duplicate work, drift risk, defect risk against a battle-tested implementation.
- **Call into the MCP server as a sidecar**: rejected — adds a runtime dependency and a network hop for what is fundamentally a pure compute task.

**Drift mitigation**: explicit `# Vendored from analytics/backend/replays/rrweb_analyzer.py @ <sha>` in the module docstring + a quarterly diff check (manual or via a CI job that fetches the upstream and runs `diff`).

---

## R-7. Default activity label: `f"{action}:{tag_name}@{normalized_url}"`

**Decision**: The default `label_fn` produces stable activity labels of shape `f"{action}:{tag_name}@{normalized_url}"`. URL normalization strips query strings and replaces numeric path segments with `:id` (`/users/12345/profile` → `/users/:id/profile`). A built-in `selector_label_fn(attr="data-testid")` is provided for projects that tag interactive elements.

**Rationale**:
- Process mining requires stable labels: same semantic action must produce the same label across sessions.
- `tag_name` (e.g. `button`, `input[type=email]`) is coarse enough to align across A/B tests and i18n drift.
- `normalized_url` collapses noise (query strings, numeric IDs) that would otherwise fragment the label space.
- `data-testid` (or equivalent) is the SDK-side best practice for stable element identification; the built-in label fn rewards projects that adopt it.

**Alternatives considered**:
- **Use the rrweb node ID as the label**: rejected — node IDs are per-session, never align across sessions.
- **Use the element's text content**: rejected — fragments under i18n, A/B tests, dynamic content.
- **Use the full CSS selector path**: rejected — fragile under DOM drift (a parent div rename invalidates every descendant's label).
- **Hash the entire element subtree**: rejected — opaque to humans reading the labels; debugging becomes guesswork.

**Escape valve**: every method that emits activity labels (`find_pattern`) accepts `label_fn=` for caller-controlled labeling. The default is a sensible starting point, not a forced choice.

---

## R-8. Insights group-by limit (5 properties) enforced client-side

**Decision**: `events_for_replay(replay_id, event_properties=[...])` validates `len(event_properties) <= 5` before constructing the query. Raises `ValueError` with a clear message naming the limit.

**Rationale**:
- The Insights API caps group-by at 5 keys (counting `$time`, `$event_name`, `$mp_replay_id` plus user-supplied properties).
- A server-side 400 returns a generic "too many group-by keys" message. Client-side validation surfaces the issue with the actual count and the actual list of properties.
- Saves a round trip on the failure path.

**Alternatives considered**:
- **Defer to the server's 400**: rejected — slower failure, less informative error.
- **Auto-truncate to the first 5**: rejected — silent data loss, violates Explicit Over Implicit.
- **Group differently to bypass the limit**: rejected — the limit exists for a reason (query cost); working around it would surprise the user with slower queries.

---

## R-9. Bundle memory budget documented, not enforced

**Decision**: Documentation states that `ReplayBundle` targets hundreds of replays (memory ~2 MB per replay in `actions_df`). No runtime enforcement of bundle size. Callers exceeding the budget are directed to `stream_replay` per replay + incremental aggregation.

**Rationale**:
- Hard caps would surprise legitimate large-bundle callers (e.g. a behavioral scientist with a curated 10,000-replay corpus).
- Memory budgets are user-context-specific (a 64 GB workstation can comfortably hold 10× what a 4 GB CI runner can).
- Documentation + an obvious alternative path (streaming) is the standard Python-library pattern.

**Alternatives considered**:
- **Hard cap at 1,000 replays**: rejected — arbitrary, surprises power users.
- **Soft warning above N replays**: rejected — log noise for callers who know what they are doing.
- **Lazy DataFrame materialization with a row-count budget**: rejected — adds complexity to the bundle internals for a problem better solved at the call site.

---

## R-10. Phase boundaries match shippable PRs, not feature completeness

**Decision**: Phase 1 ships discovery + signed access + per-replay fetch with empty `Replay.actions` (analyzer not yet shipped). Phase 2 ships the analyzer, populating `Replay.actions` and adding `ReplayBundle`.

**Rationale**:
- Each phase delivers caller-visible value independently. Phase 1 alone lets users pull raw bytes for the rrweb JS player. Phase 2 adds structured behavioral data.
- Phase 1 is the most uncertain (new endpoints, new error mapping, new bearer-credential handling). Shipping it alone lets reviewers focus on that surface without the analyzer's 1,500-LoC noise.
- Phase 2 builds on Phase 1's foundations; reviewers can assume the discovery / signing / fetching layer is already approved.

**Alternatives considered**:
- **Single mega-PR (~2,700 LoC)**: rejected — review burden, regression risk.
- **One PR per file**: rejected — review thrash, no logical breakpoints.
- **Phase 2 splits analyzer and bundle**: rejected (see Complexity Tracking in plan.md) — the analyzer is the bundle's data source; shipping separately creates dead code or incorrect API.
