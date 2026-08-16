# B4 adversarial review — WIRE SEMANTICS lens (P3-2d)

**Status**: COMPLETE · 2026-08-16 · reviewer: wire-semantics lens (one of the B4 pair).
Scope: the six B4 shard commits on TS `main` (4f7bfa5 C1, 99ba862 C2, be74c38 C3,
e42c6c7 C4, 9305700 C5, 023cab5 C6) incl. their inline bindings
(`conformance-runner/src/wire-*.ts`), audited against Python source of record at
support-branch HEAD (`ts-port/phase2-contract-support`) and the playbook v1.1 +
`b4-packets.md` cautions. No code edited (review-only).

## Verification log (what was checked, with evidence)

1. **Retry loop vs `api_client.py:706-820`** — `internals.ts executeWithRetry`:
   429-only retry; `for attempt in 0..maxRetries` (`attempt <= deps.maxRetries`,
   default 3); exhausted raise carries `retry_after` (parsed, may be null) +
   lossless-parsed body + `project_id`; type-checker fallthrough raise uses the
   reduced FF4 shape. `request_body = json_data or form_data` dict-truthiness
   preserved. Params mutation + `query_origin` injection at the single site.
   `timeout or self._timeout` 0-falls-back truthiness preserved. **MATCH.**
2. **Retry-After grammar + cap + raw-value reporting** — `backoff.ts`:
   `parseRetryAfter` = `pythonInt` full CPython grammar, negative → null,
   HTTP-date → null; `retryWaitSeconds` header path `min(x, 60)` UNJITTERED;
   fallback `min(1.0*2^attempt, 60) + random()*delay*0.1` via injected RNG
   (Discrepancy #1 resolved to source truth); raw value reported verbatim in
   `RateLimitError.retry_after` while the sleep caps at 60 (locked by the
   translated `test_huge_retry_after_reported_verbatim_on_error`). Discrepancy #6
   (>2^53 reads as absent) documented in the JSDoc. **MATCH.**
3. **`_handle_response` integration** — every branch diffed against
   `api_client.py:503-662` in source order: 401, 403-sensitive
   (`pythonInt(project_id)` coercion, exact-element list membership, R10.7
   403-TypeError branch for truthy non-container scalars, falsy scalars →
   QueryError), 400/404/other-4xx defaults, 5xx `"Server error: "` prefix,
   fallthrough tail order (raise_for_status FIRST → object/array → scalar
   re-parse → INVALID_RESPONSE with `cpSlice(text,0,500)`). `errorMessage`
   absent-or-null `error` → default. All five RateLimitError `project_id` sites
   verified: `:779` + `:819` (executeWithRetry), `:1322` + `:1386` (appRequest),
   `:1883-1891` (streaming — carries `project_id`, omits `response_body` only);
   the pagination raise correctly carries NEITHER `project_id` nor
   `request_params` (not one of the five). **MATCH.**
4. **Pagination (R6.1/R6.6)** — `pagination.ts` vs `pagination.py` whole-file:
   `MAX_PAGES` 10000 + injectable `maxPages` option (monkeypatch replacement);
   per-paginator 429 retry ×3 independent of client `max_retries`; header wait
   `min(float, 60)` / fallback `min(2^attempt, 60)` — NO jitter in either arm;
   module-level `_parse_retry_after` = `pythonFloat` (inf parses then filters;
   value uncapped at parse); exhausted raise `retry_after = trunc(float)`,
   `response_body = response.text` raw; NETWORK_ERROR (not HTTP_ERROR) transport
   mapping; 401/5xx/API_ERROR ladder; `results` absent-or-null → `[]`, non-list →
   INVALID_RESPONSE with `results_type`; top-level list yields directly;
   item-level `yield*`; cursor from truthy-dict `pagination` only; falsy-but-
   non-null cursors (`""`, `false`) continue exactly like Python; `query_origin`
   literal `"mixpanel-headless"` set LAST; literal `{Authorization}` headers (no
   4-layer merge); per-page auth re-resolution. **MATCH** except finding F4.
5. **Streaming** — `streaming.ts` vs `:1813-2110` + `workspace.py:1381-1578`:
   params assembly (`event` json.dumps only when truthy list, `where` truthy,
   `limit is not None`); headers captured ONCE pre-loop incl. `Accept-Encoding:
   gzip`; per-attempt `batch_count` reset (deviation-3 lock present:
   TestRetryStateResetRegression ×4 + `:1560-1575` project_id + `:3810`
   negative-Retry-After all found in the translated suites); 429/401/400
   branches; raise_for_status → retried MixpanelHttpError → exhausted
   `HTTP_ERROR` with `{error}` details only; per-line
   `parseLossless(line, {pythonConstants:true})` (`:1931`), malformed line
   skipped; on_batch cadence (every 1000 + final partial); `export_profiles` AC2-
   AC6 guard order, empty-distinct_ids early return, ordered dedupe, page/
   session_id threading, `include_all_users` sent only with cohort, dict-body
   POST via the `_request` twin, results truthiness break, dict/str iteration
   bug-compat. `stream_events`/`stream_profiles` wrappers: `_validate_limit`
   (WR2/WR3), raw passthrough vs transform_event/transform_profile — matches
   `workspace.py` (the packet's "raw yields undecoded lines" wording was wrong;
   the port follows source truth). **MATCH** except findings F1/F5.
6. **URL construction (R2.13)** — grep over `packages/*/src`: zero `new URL(`
   in library code (rig `vector-fetch.ts`/`wirestub.ts` only); `buildUrl` string
   concatenation with leading-`/` normalization (`""` → `/` matches
   `_build_url("engage","")`). **CLEAN.**
7. **Region table** — `ENDPOINTS` us/eu/in × query/export/engage/app verified
   byte-equal to `api_client.py:151-172`. **COMPLETE.**
8. **GATE-R5 lossless + pythonConstants site audit** — no bare `JSON.parse` /
   `response.json()` on wire text in `packages/*/src`; `pythonConstants: true`
   present at: handleResponse parseBody + scalar tail, appRequest 422 + 429,
   streaming per-line + 400 body, pagination body parse, registerLookupTable
   body parse. **CLEAN.**
9. **R11.7** — no `parseInt`/`.trim()`/bare `Number(str)` in ported client/
   services code; `\s`/`\d` grammar in `get_events`' date-gate regex spelled as
   the CPython whitespace class + `\p{Nd}` with `pythonInt` capture. **CLEAN.**
10. **AbortSignal (R6.7)** — all four points present: between pages
    (pagination loop-head check), into the request (`rawFetch` passes signal),
    into the backoff sleep (`signalAwareSleep`), normalization via
    `normalizedAbortError`. Probe: default-reason abort rejects through
    `rawFetch` as `DOMException` name `AbortError` and passes the
    `executeWithRetry` taxonomy untouched (not wrapped as HTTP_ERROR). **PASS**
    except the custom-reason gap (finding F3).
11. **ms/seconds (R2.12)** — module boundary audit: backoff/pagination speak
    seconds with `*_SECONDS` names; single `* 1000` conversion at each sleep
    call site (executeWithRetry, appRequest, streaming ×2, pagination);
    Layer-3 asserts ms values (`[30000,30000,30000]`, `[5000]`). **MATCH.**
12. **Vector replay** — full conformance run (superset of the 30-vector
    mandate): **3,251 vectors — 2,370 PASS / 0 FAIL / 881 UNPORTED** @ corpus
    70c904dc598d — exactly the packet's post-C6 expectation; all 842 replayable
    B4 wire vectors PASS (request byte-shapes, paths, headers, retry sequences,
    pagination pages locked).
13. **Layer-3 timing suites** — `client-streaming-async.test.ts` (9),
    `pagination.test.ts` (40), `backoff.test.ts` (24) green; full
    `packages/core/test/client/` = **934/934 green**. Timing is asserted through
    the injected sleep seam (recorded ms durations), abort-during-backoff-sleep
    and early-`return()` locks present. NOTE: no `vi.useFakeTimers` anywhere;
    `chunkedFetch` uses a real 1 ms `setTimeout` between chunks (see F6).
14. **Bindings** — the 183 api-index `api_client.*` names + `pagination.
    paginate_all` each appear in exactly the wire-* registration modules
    (mechanical diff clean, zero missing); `clientFromSession` memoizes under
    `context.state["api_client"]` (P3-5 §1), injects `fetch`/zero-sleep/
    `random: () => 0`/frozen `now`, honors recorded `max_retries`; binding
    bodies are client-method calls + kwarg plumbing (spot-checked; honesty
    verdict is the arbiter's).
15. **Misc branch checks** — `_request` project-id/workspace-pin injection
    (setdefault twin via `Object.hasOwn`); public `request()` header collision
    order; `use()` atomic-on-success + unconditional pin sync; workspace
    resolution ladder + 403/404 fallthrough set; `me()` non-dict wrap;
    `list_workspaces` validation; `with_project` truthy-vs-`is not None` twin
    guards; engage_stats selector rename + non-dict QueryError(status 200);
    export_profiles_page param grid + ProfilePageResult assembly;
    lookup-tables direct-request paths (register/download raw wiring,
    no-retry, results unwrap, external PUT with Content-Type only);
    `query_origin` single-injection (no double-inject in any C2 method). All
    **MATCH**.

## Findings (ranked)

### F1 — MAJOR (CONFIRMED): `exportEvents` mid-stream body failures escape raw — no retry, no HTTP_ERROR wrap
`packages/core/src/services/queries/streaming.ts:394-433`. Python iterates
`_iter_jsonl_lines(response)` INSIDE the `try` guarded by `except httpx.HTTPError`
(`api_client.py:1870-1953`): an `httpx.ReadError`/`ReadTimeout` raised while
consuming the body (mid-download network drop, gzip truncation) is an
`httpx.HTTPError` → retried up to `max_retries`, then wrapped as
`MixpanelHeadlessError` code `HTTP_ERROR` ("HTTP error during export: ...").
The TS twin consumes `response.body` directly via `bodyByteSource` without
normalizing read errors; undici surfaces them as raw `TypeError`, which the
catch (`!(cause instanceof MixpanelHttpError)) throw cause`) rethrows verbatim.
**Probe (executed)**: a body stream erroring after one line escapes as
`TypeError: terminated`, 1 fetch call (no retry), no `HTTP_ERROR` code. The
buffered path (`createRequestExecutor`) wraps exactly this case as
`MixpanelHttpError` ("Body-read failures are transport errors in httpx too") —
the streaming path missed the same normalization. Not vector-observable
(recorded streams use full `body_text`) and no Python Layer-3 test simulates a
mid-body ReadError, so nothing locks it — but it is a real taxonomy + retry
divergence on the production streaming path. Fix: wrap the byte-source
iteration (or `bodyByteSource`) so non-Abort read failures throw
`MixpanelHttpError`, mirroring `createRequestExecutor`.

### F2 — MAJOR (CONFIRMED): request timeouts are never enforced — `timeoutSeconds` is dead at the adapter
`packages/core/src/client/transport.ts:201-254` (`rawFetch`). Python enforces
`timeout=timeout or self._timeout` (default 120 s; 600 s export; pagination
passes `client._timeout`) on every httpx call; a timeout raises
`httpx.TimeoutException` ⊂ `httpx.HTTPError` → surfaces as `HTTP_ERROR`
(or NETWORK_ERROR in pagination). The TS adapter threads
`options.timeoutSeconds` through every call site but `rawFetch` never reads it —
no `AbortSignal.timeout`, no race, nothing. A hung server stalls a TS caller
forever where Python fails in 120 s. Unobservable in vectors/Layer-3 (fake
transports resolve immediately) and NOT disclosed in any B4-C1 notes entry
(grep clean). Fix: combine the per-call signal with
`AbortSignal.timeout(timeoutSeconds * 1000)` (`AbortSignal.any`) in `rawFetch`
and normalize the timeout rejection to `MixpanelHttpError` (undici throws
`TimeoutError` DOMException — the existing DOMException arm already catches it,
but only once a timeout signal exists); alternatively document a sanctioned
deviation with an arbiter blessing — silent nothing is neither.

### F3 — MINOR (CONFIRMED): R6.7 normalization gap — a custom abort reason escapes the request point un-normalized
`packages/core/src/client/transport.ts:231-252`. R6.7/packet Caution #6:
"every cancellation throws `DOMException(…, 'AbortError')`". The sleep wrapper
and the pagination between-pages check normalize via `normalizedAbortError`,
but the request point relies on fetch rejecting with the signal's reason:
`controller.abort("user-stop")` makes fetch reject with the raw string, which
is neither an AbortError DOMException nor TypeError/DOMException → `throw
cause` re-raises the bare string (probe executed: `ESCAPED: string user-stop`).
Same value then passes the `executeWithRetry` filter unwrapped. Default-reason
aborts behave correctly. Fix: in the `rawFetch` catch, check
`signal?.aborted === true` FIRST and throw `normalizedAbortError(signal.reason)`.

### F4 — MINOR (CONFIRMED, source-diff): pagination body-parse catch is narrower than Python's `except Exception`
`packages/core/src/client/pagination.ts:418-437` guards the JSON-parse catch
with `instanceof LosslessJsonError`, citing B0-ARB F3. That ruling covered the
`except json.JSONDecodeError`-ONLY sites (`_handle_response`, app_request 422/
429); `pagination.py:246-254` catches **broad `Exception`** — in Python even a
`RecursionError` from a pathologically nested body wraps as `INVALID_RESPONSE`
(code + `content_type` detail), while the TS twin lets the parser `RangeError`
propagate uncoded. Pathological-input-only divergence, zero vector/Layer-3
reach, but the code comment misstates the Python catch scope and no design doc
sanctions THIS site. Fix: catch-all here (`catch (cause)` → INVALID_RESPONSE),
or file the deviation with a correct citation for the arbiter to bless.

### F5 — MINOR (PLAUSIBLE): `exportProfiles` coerces a non-string `session_id` with `String()` — a numeric session id would corrupt the next page request
`packages/core/src/services/queries/streaming.ts:586`. Python threads
`response.get("session_id")` verbatim into the next page's JSON body
(`params["session_id"] = session_id` — an int stays an int on the wire). TS
does `sessionId = String(nextSession)`: a native number becomes `"123"`, and a
lossless `JsonNumber` token (no `toString` override) becomes
`"[object Object]"`. Every recorded vector carries string-or-null session_ids
(corpus grep), so this is corpus-unreachable today, but the engage API contract
does not promise string ids. Fix: keep the raw `JsonValue` and place it in the
params untouched (the body is JSON — no stringification needed).

### F6 — NIT: dedicated async suites use real 1 ms timers, and no suite uses Vitest fake timers
`packages/core/test/client/client-streaming-async.test.ts:44-48` awaits a real
`setTimeout(…, 1)` between chunks; risk-register #4 and the B4 row say
"Layer-3 uses Vitest fake timers; no real timers anywhere in tests". The
retry-wait assertions correctly go through the injected sleep seam (recorded ms
durations — deterministic, arguably stronger than fake timers), so this is a
compliance wording nit + a negligible flake surface, not a behavior gap. Note
for the arbiter: either bless the injected-seam pattern as satisfying the
fake-timer mandate or swap the 1 ms delay for `vi.useFakeTimers` +
`advanceTimersByTimeAsync`.

## Verdict

GO with fixes: F1 and F2 should land (or be explicitly arbiter-sanctioned as
deviations) before the B4 gate; F3-F5 are small, contained fixes; F6 is a
bless-or-tweak. Everything else audited under this lens — retry loop,
Retry-After handling, all five project_id raise sites, the 403-TypeError
bug-compat matrix, pagination spine, URL/region tables, GATE-R5 lossless
coverage, R2.12 unit boundaries, 183-name binding coverage, and the full
842-vector replay — matches Python source byte-for-byte.
