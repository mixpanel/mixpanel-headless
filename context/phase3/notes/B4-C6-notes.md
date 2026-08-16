# B4-C6 notes — pagination.py (paginate_all)

**Task**: b4-packets.md Packet C6 (39 vectors, 0 api-index `api_client.*` names; owns the
`pagination.` prefix — flip deferred to the gate).
**Status**: DONE — TS commit on mixpanel-headless-ts main (see Done-criteria).
**Date**: 2026-08-16.

## Progress log

- [x] Packet C6 + `pagination.py` (288 LOC, whole file) + `tests/unit/test_pagination.py`
  (824 LOC, 40 tests) read; C1 core seam (`ClientCore.executeDeps/buildUrl/getAuthHeader`)
  + C2 streaming patterns + C5 harness/notes conventions inventoried. No prior C6 work found.
- [x] Layer-3 translation FIRST (P3-2 a): `packages/core/test/client/pagination.test.ts`
  (40 tests, ALL four Python classes + the `run_rate_limited_pagination` driver; red until
  the module landed) + `pagination-async.test.ts` (4 TS-native async locks — delayed pages,
  abort between pages, abort during backoff sleep, early `return()`).
- [x] `packages/core/src/client/pagination.ts` — `async function* paginateAll(...)`
  (R6.1/R6.6/R6.7), exported through `client/index.ts`.
- [x] Binding `pagination.paginate_all` (`conformance-runner/src/wire-pagination.ts`,
  registered in `bindings.ts` — same commit, b′ rule). Oracle registration: wire names are
  EXEMPT (no oracle call surface, P3-2 c) — nothing to register.
- [x] Vector replay: **39/39 PASS on first replay**; cumulative full run
  **2,370 PASS / 0 FAIL / 881 UNPORTED** (= the packet's all-six-shards interim AND the
  gate-report target; prefixes still `pending` — NO flip, the gate's job).
- [x] R10.9 harness `throwaway/b4-c6/` — **56/56 branches OK**.
- [x] `npm run check` green (exit 0; 128 test files); one TS commit; this notes commit.

## Design decisions / findings

1. **Client seam**: `paginateAll(client, path, options)` takes the assembled client and
   reaches Python's private wiring through `client.core` (C1 `ClientCore`):
   `_build_url("app", ...)` → `core.buildUrl`, `_get_auth_header()` → `core.getAuthHeader`
   (per PAGE, inside the while loop — R2.8), `_ensure_client()` + raw
   `http_client.request(...)` → `core.executeDeps(signal).request` (the text-buffering
   B0 `RequestExecutor` over the injected fetch — this walk never enters
   `executeWithRetry`/`appRequest`, matching the measured spine), `client._timeout` →
   `core.timeoutSeconds`. Literal `{Authorization}` headers — NO `requestHeaders` merge,
   NO User-Agent (`pagination.py:161-163`); harness-locked
   (`pages/1-page-wire-shape` asserts `user-agent` absent + byte-exact Basic header).
2. **R6.7 all four points without touching B0 signatures**: point 1 = explicit
   `signal.aborted` check at the loop head (throws `normalizedAbortError`); points 2/3 =
   the C1 signal-aware `request`/`sleep` closures from `core.executeDeps(signal)`;
   point 4 = every exit is a `DOMException(..., 'AbortError')` (transport.ts
   normalization). Locked by `pagination-async.test.ts` (abort between pages fires BEFORE
   the next request; abort during backoff sleep leaves exactly 1 request + 1 sleep).
3. **MAX_PAGES monkeypatch → injectable `maxPages` option** (default 10000; an option,
   not a mutable module global — packet C6 §Layer-3 / playbook B4 row). Assertion content
   preserved: with `maxPages: 3` the `PAGINATION_LIMIT` raise fires at the page-4 loop
   head, BEFORE a 4th request (harness `limit/overflow-request-count` = 3 requests), with
   details `{max_pages: <injected>, path}`.
4. **`_parse_retry_after` is the module-level STRING parser** — ported as a private
   `parseRetryAfterSeconds` using `pythonFloat` (R11.7 [SA3]; the ValueError analog is the
   `PY_FLOAT_INVALID_LITERAL`-guarded catch, never bare — B0-ARB F3 discipline). `"inf"`
   parses then filters to null; `"1,000"` fails the CPython grammar; value NOT capped in
   the parser (`_BACKOFF_MAX` applies at the sleep site). Exhausted-raise
   `retry_after = int(advertised)` → `Math.trunc` (harness: `"45.7"` → 45).
5. **Reduced RateLimitError shape verbatim** (Caution #3 — NOT one of the five
   `project_id` sites): carries `retry_after?`/`status_code=429`/`response_body`
   (=`response.text`)/`request_method="GET"`/`request_url`; NO `project_id`, NO
   `request_params`. Harness asserts both keys ABSENT from `details`.
6. **Unjittered waits in both arms** (packet spine: "do not import `calculateBackoff`'s
   jitter"): advertised → `min(advertised, 60)`; fallback → `min(1·2^attempt, 60)`.
   Harness `retry/backoff-schedule-unjittered` proves it with `random: () => 0.999`
   (the client backoff would add ~0.1·delay) — schedule stays exactly [1, 2, 4] s.
   Per-paginator retry ×3 independent of client `max_retries`: harness runs a
   `maxRetries: 0` client and still observes 4 attempts (review-checklist delta).
7. **Error mapping divergences from the client paths, ported as measured**: transport
   failure → `NETWORK_ERROR` `{path, error}` (not `HTTP_ERROR`); non-429 non-2xx via the
   `raise_for_status` analog — httpx raises for EVERY non-2xx, so an unfollowed 3xx lands
   in the `API_ERROR` arm `{status_code, response_body}` (R2.11; harness
   `errors/3xx-api-error` locks 302 → API_ERROR); 401 → `AuthenticationError`; ≥500 →
   `ServerError`.
8. **Lossless body parse** (GATE-R5 + B0 arbiter F1): `response.json()` →
   `parseLossless(text, { pythonConstants: true })`; the JSONDecodeError-analog catch is
   `instanceof LosslessJsonError` (Python's broad `except Exception` would also swallow a
   RecursionError — the sanctioned B0-ARB F3 narrowing is kept; RangeError propagates,
   disclosed at B0). INVALID_RESPONSE details use `.get` WITHOUT the message's "unknown"
   default: `content_type` is present-with-null when the header is absent (harness
   `errors/empty-body-200`).
9. **`results_type` detail** = `type(raw_results).__name__` over the `json.loads` product
   domain: a local `pythonJsonTypeName` maps lossless values (JsonNumber tokens split
   int/float by token shape — `1.5` → "float" harness-locked beyond Python's 4 test
   params). `isinstance(data, dict)` here is the "JSON object body" predicate →
   `isPlainRecord` (the packet Caution #9 either-or, matching C2's streaming usage).
10. **`next_cursor is None` is the ONLY terminator**: `false`/`0`/`""` cursors continue
    (harness `pages/next-cursor-false-not-none`: second request carries `cursor=false`,
    httpx bool rendering). Numeric cursors render `str()`-faithfully (int tokens keep
    exact digits; float tokens via `pythonFloatStr`; a `// TODO(port)` discloses the
    unreachable exponent-token arm). Only a TRUTHY dict `pagination` block is consulted
    (empty dict is falsy → single page).
11. **Zero in-library call sites preserved** (packet §R10.10): `paginateAll` is exported
    from `client/pagination.ts` + `client/index.ts` but wired into NO client method.
12. **JS-number-domain disclosures** (same class as the C2/C5 notes): a Python
    `page_size=18.0` / float-typed `str()` spelling is not representable from a plain JS
    number (`String(18) === "18"`); params share Python's `dict[str, str]` annotation, so
    the `True`/`None`/`[]`/`18.0` fixed-edge values flow only where strings can carry
    them (`"1.5"`, `""`, `"𝒳"` — harness `edge/params-values`, incl. the non-BMP
    percent-encoding on the wire).

## Rig-change log

- `conformance-runner/src/wire-pagination.ts` — NEW: the one C6 binding
  (`registerPaginationBindings`), registered in `bindings.ts::createRunnerDeps`.
- `conformance-runner/test/runner.test.ts` — the mapped-but-unbound UNPORTED probe moved
  `pagination.paginate_all` → `workspace.list_dashboards` (the C1-notes-predicted move:
  C6 binds the last B4 name; the new probe is a B6 facade name and stays valid after the
  B4 gate flip since `workspace.` remains pending until B5/B6).

## R10.9 RUN record

`bash throwaway/b4-c6/run.sh` → **56/56 branches OK** (deterministic, no fuzz seeds —
wire methods have no oracle bridge, P3-2 c; expectations transcribed from
`pagination.py` whole-file).

- §1 page walks (20): 1-page + wire shape (GET, app host, page_size "100",
  query_origin, byte-exact Basic auth, NO user-agent) · 3-page cursor thread + request
  sequence · empty-results · results-null · results-null-follows-cursor (2 requests) ·
  missing-pagination-block · top-level-list-body (yields directly, single page) ·
  scalar-200-body (42 → zero items, no raise, single page) · pagination-non-dict ·
  pagination-empty-dict (falsy → single page) · next-cursor-false-not-none (+ cursor
  param "false") · numeric-cursor-tokens ("5" exact digits / "1.5" float repr).
- §2 page limit (4): maxPages=3 overflow → PAGINATION_LIMIT `{max_pages: 3, path}` with
  exactly 3 requests (loop-head raise) · repeat-cursor guardless walk (no repeat guard in
  source; runs to the limit).
- §3 429 retry loop (12): 429-then-success (sleep [30000], 2 requests) · 429×4 exhausted
  reduced shape (retry_after trunc 45, response_body text, NO project_id, NO
  request_params; 4 requests / 3 sleeps) · independence from client max_retries
  (maxRetries=0 → still 4 attempts) · Retry-After clamp (86400 → 60 s) · hostile
  fallback ("abc" → 1 s) · unjittered schedule under random()=0.999 ([1, 2, 4] s).
- §4 error branches (13): NETWORK_ERROR `{path, error}` (+ mid-walk after page 1
  yielded) · 401 AUTH_FAILED · 503 SERVER_ERROR · 404 API_ERROR
  `{status_code, response_body}` · 302 API_ERROR (R2.11 — never a success) ·
  non-JSON-200 INVALID_RESPONSE `{content_type: "text/html"}` · empty-body-200
  INVALID_RESPONSE `{content_type: null}` · results-non-list ×5
  (str/int/float/bool/dict — exact `{path, results_type}` details).
- §5 edge values (7): params `{"𝒳": "𝒳", empty: "", frac: "1.5"}` + page_size 18
  round-trip + non-BMP `%F0%9D%92%B3` on the wire · query_origin spoof → canonical ·
  per-page auth header on every request.

Harness-artifact note: the empty-body-200 case needs a `null` `Response` body (a JS
string body makes the platform `Response` auto-add `text/plain;charset=UTF-8`, defeating
the absent-content-type branch) — a rig detail, not a library behavior.

Disclosures: `18.0`/`True`/`None`/`[]` are not representable through the `dict[str, str]`
params annotation Python shares (finding 12); packet edge set otherwise complete.

## Vector replay (per packet C6)

`npm run conformance -- --filter "pagination.paginate_all/"` → **39/39 PASS**
(no other corpus name starts with `pagination.` — the substring trap does not bite here,
trailing-slash form used anyway). Full run: **3,251 = 2,370 PASS / 0 FAIL / 881
UNPORTED** — exactly the packet's post-all-six-shards interim and the B4 gate-report
target (delta +842 cumulative; the P3-1 † carried vector stays UNPORTED on its
`workspace.me` setup). NO batch-status flip (gate task).

## Done-criteria check

- [x] Files on disk; `tsc --strict` clean; `npm run check` green (exit 0, 128 test files).
- [x] 44 translated/authored Layer-3 tests green (translations written first, red before
      the module existed).
- [x] All 39 C6 vectors PASS; cumulative 2,370/0/881.
- [x] Binding in the same shard commit (b′); oracle surface: wire-exempt (nothing to
      register).
- [x] R10.9 RUN record (above); harness lives in `throwaway/b4-c6/` inside the shard
      commit (gate removes it after arbiter sign-off).
- [x] One TS commit; this notes commit on the Python support branch.
