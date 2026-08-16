# B4-C2 running notes — query-host methods + streaming/export

**Status**: DONE (module task; review pair pending) · 2026-08-15 · fable ≤ high ·
packet: `context/phase3/design/b4-packets.md` §Packet C2 (317 vectors, 24
api-index names). C1 prerequisite landed (`4f7bfa5`).

## Progress log

- [x] Inventory: no prior C2 work; C1 seams binding (`core.requestQueryHost`,
      `core.rawRequest`, `core.executeDeps().sleep` signal-aware closures,
      `clientFromSession` + `CLIENT_STATE_KEY` memoization).
- [x] Python sources read: `api_client.py:1813-3293` (all 26 methods incl.
      index-absent `arb_funnels_query`), helpers `:175-249`
      (`_parse_feed_date`/`_build_activity_feed_date_range`), `:664-704`
      (backoff trio — B0, imported), `_request` `:822-920` (C1
      `requestQueryHost` twin verified), `types.py:6499` (`ProfilePageResult`),
      `workspace.py:326-351` (`_validate_limit`) + `:1381-1578`
      (`stream_events`/`stream_profiles`).
- [x] Layer-3 translated to green (178 tests, 5 files under
      `packages/core/test/client/`): client-export 16 (TestEventExport,
      TestRequestEncodingRegression, TestRetryStateResetRegression ×4 incl.
      the :1551 project_id lock, :3810 negative-retry-after, the C1 hand-off
      test_export_stream_carries_no_workspace_id_param, +1 lossless-spine
      lock), client-engage 87 (TestProfileExport + all six TestEngage* classes
      + TestExportProfilesPage/Pagination + TestCodedExportProfilesCodes +
      ALL of tests/test_api_client_engage_stats.py), client-query-host 65
      (TestSegmentation, TestDiscovery, TestFunnelAndRetention,
      TestActivityFeed + ALL of test_api_client_phase008.py),
      client-queries-pbt 1 (TestActivityFeedDateRange → fast-check, 200 runs),
      client-streaming-async 9 (NEW dedicated async suites: chunk-boundary
      reassembly across await points, lazy yield, early-`return()`, 429 retry
      timing through the ms sleep seam, abort-during-backoff-sleep →
      AbortError, stream_events/stream_profiles wrapper locks incl. WR2/WR3).
- [x] Implementation green (`tsc --strict` all workspaces).
- [x] b′ inline: 24 bindings in `conformance-runner/src/wire-queries.ts`;
      cumulative replay **3,251 = 1,925 PASS / 0 FAIL / 1,326 UNPORTED** —
      exactly the packet's C1+C2 interim expectation (1,608 + 317). Per-name
      trailing-slash replay (substring-trap rule): export_events 13,
      export_profiles 19, export_profiles_page 31, engage_stats 21,
      get_events 54, get_event_properties 5, get_property_values 23,
      list_funnels 4, list_cohorts 5, get_top_events 6, event_counts 5,
      property_counts 7, segmentation 10, funnel 7, retention 10,
      activity_feed 26, query_saved_report 20, list_bookmarks 9,
      insights_query 1, query_saved_flows 4, frequency 10,
      segmentation_numeric 9, segmentation_sum 9, segmentation_average 9 —
      Σ = 317, all PASS. No batch-status flip (gate's job).
- [x] R10.9 RUN record (below): 52/52 branches PASS.
- [x] `npm run check` green (114 test files, 5,154 passed / 1,326
      corpus-skipped; lint/fmt/smoke clean); commits.

## TS files landed

- `packages/core/src/services/queries/query-host.ts` — 21 query-host methods
  (`createQueryHostMethods(core, {resolveWorkspaceId})`), the exported
  `buildActivityFeedDateRange` (+ private `parseFeedDate`), the get_events
  403-gate retry, and `arb_funnels_query` (index-absent, Layer-3-locked).
- `packages/core/src/services/queries/engage.ts` — `engageStats` +
  `exportProfilesPage` (returns the Phase-2 `ProfilePageResult`).
- `packages/core/src/services/queries/streaming.ts` — `exportEvents`
  (`async function*`, its own inline 429 loop; FF4 `:1883-1891` reduced-shape
  raise), `exportProfiles` (session-paged generator, AC2–AC6 guards),
  `validateLimit` (WR2/WR3), and the two B4 api-map wrappers
  `streamEvents`/`streamProfiles` (standalone functions over the client until
  the B6 facade lands; consume B3 `transformEvent`/`transformProfile`).
- `packages/core/src/services/queries/py-dates.ts` — strptime(`%Y-%m-%d`)
  twin (Unicode `\p{Nd}`, 1-4 digit year), Hinnant civil arithmetic,
  `timedelta(days=n)` with the Python year-1..9999 OverflowError guard.
- `packages/core/src/compat/python-json-dumps.ts` — CPython `json.dumps`
  default-args twin (`(", ", ": ")` separators, `ensure_ascii=True` \uXXXX
  escapes incl. surrogate pairs, `NaN`/`Infinity` spellings, floats via
  `pythonFloatStr`) — the wire-param spelling contract for
  events/output_properties/distinct_ids/behaviors/segment_by_cohorts/
  filter_by_cohort/values.
- `packages/core/src/client/client.ts` — the three C2 spreads at the marked
  append-only merge point; `MixpanelClient` extends
  `QueryHostMethods`/`EngageMethods`/`StreamingMethods`.
- `packages/core/src/client/internals.ts` — `jsonValuePythonStr` exported
  (R10.8 by-name consumers: engage_stats non-dict guard, get_events /
  get_property_values `str(e)` casts).
- `packages/core/src/services/index.ts` — services module exports.
- `conformance-runner/src/wire-queries.ts` — the 24 registrations
  (binding honesty: memoized client + one method call + kwarg passthrough;
  generators drained; `on_batch` served by the shared `RecordingCallback`;
  `ProfilePageResult.toVectorPayload()` as the recorder's field walk).

## Rig changes (fable-authored, in the same commit)

1. `vector-fetch.ts`: recorded JSON `body` responses are now serialized with
   `storedJsonText` (compact separators, STORED key order, lossless tokens
   verbatim) instead of `canonicalize` — the Python replay transport uses
   `json.dumps(body, separators=(",",":"), ensure_ascii=False)`
   (`conformance/runner/transport.py:188-190`); canonicalize's key sorting
   broke the first key-order-sensitive consumer
   (`get_event_properties` → `list(response.keys())`; found via 2
   FAIL_OUTPUT vectors on first replay).
2. `runner.ts`: setup-call raises are now SWALLOWED (`continue`), mirroring
   the Python runner (`execute.py:532-541`, design-D2 logged limitation) —
   found via a recorded 400 on a `get_event_properties` SETUP call
   (`test_list_properties_with_event_not_found_raises_with_suggestions`).
   `conformance-runner/test/runner.test.ts` adjusted: the FAIL_ERROR
   setup-raise lock now asserts the swallow semantics (PASS), and the
   UNPORTED probe name moved `api_client.activity_feed` →
   `api_client.list_dashboards` (C3; the C1 notes item 3 forward-look —
   the GATE flip must revisit again).
3. `wire-client.ts`: `requireWireKwarg` / `runWire` / `optionalRecord`
   exported for the sibling shard binding modules.

## Design decisions / findings

1. **`pythonJsonDumps` lives in compat/** — C2 is the first consumer; C5's
   governance methods may reuse it. Wire-visible spellings locked by the
   recorded params (`'["Purchase", "View"]'` with the ", " separator) and by
   the harness ensure_ascii branch (`"𝒳"` → `"𝒳"`).
2. **`date.today()` / `datetime.now()` read the injected clock in UTC**
   (py-dates.ts module header): both conformance runners freeze the clock at
   the record epoch (D1.4/D12 — `shims.today()` is documented UTC), so the
   TS client derives calendar dates from `core.now()` in UTC. TODO(port)
   disclosure: at real runtime a non-UTC host can differ from CPython's
   LOCAL date near midnight — out of vector reach.
3. **strptime twin** accepts the full `%Y-%m-%d` grammar (1-2 digit
   month/day, 1-4 digit year, Unicode Nd digits via `\p{Nd}` + `pythonInt` —
   R11.7); `formatYmd` zero-pads (isoformat semantics; `strftime("%Y")` for
   years < 1000 is platform-dependent in CPython — unreachable: the only
   sub-1000 lock is the `0001-01-10` OverflowError arm).
4. **`query_saved_report` funnels date derivation**: strptime failures raise
   the bare `ValueError` twin (`query/python-builtins.ts` class), NOT
   QueryError — Python lets them propagate (`:2960/:2965`).
   `min(computed_to, datetime.now())` ports as a CIVIL-date comparison
   (the calendar day is what survives strftime).
5. **`exportProfilesPage` non-dict body** raises a TypeError analog
   (`'X' object has no attribute 'get'`) mirroring Python's AttributeError;
   no lock reaches the arm (disclosed). `export_profiles`' truthy-dict
   `results` iterates KEYS, a str iterates code points (`pyIterate`) —
   Python `for x in results` semantics.
6. **`distinct_ids` dedup**: `list(dict.fromkeys(ids))` ports as
   `Array.from(new Set(ids))` — identical for the string domain; the
   `True`/`1` key-collapse corner differs and is disclosed (ids are typed
   `str` in Python, unreachable).
7. **`export_events` non-2xx fallthrough**: `response.raise_for_status()`
   raises an `httpx.HTTPError` SUBCLASS, so 3xx/5xx inside the stream loop
   RETRY and then surface as `MixpanelHeadlessError` HTTP_ERROR ("HTTP error
   during export: …") — NOT ServerError (unlike the buffered paths). Ported
   verbatim via a `MixpanelHttpError` throw with an httpx-shaped message
   (message text out of contract, R5.4; no vector or Layer-3 lock asserts
   it — harness branches exp/5xx + exp/3xx lock the class/code/retry count).
8. **:3810 monkeypatch substitution** (B0 deviation-5 precedent): the Python
   `_calculate_backoff → 0.75` pin translates to `random: () => 0` making the
   fallback backoff exactly 1.0 s; `recorded_sleeps == [0.75]` becomes
   `sleeps == [1000]` (ms seam). Assertion content — negative Retry-After
   rejected, exactly one backoff sleep — preserved.
9. **204 through `_request`** is INVALID_RESPONSE (`response.json()` on an
   empty body), NOT the app_request `{status:"ok"}` mapping — first harness
   draft expected the app shape; corrected against `api_client.py:655-662`.
10. **engage_stats non-dict guard** uses B0 `isPlainRecord` ("JSON object
    body" predicate — watchlist #13 note: wire-parsed values can't be class
    instances or carriers) and `jsonValuePythonStr` for the recorded
    `response_body: "[1, 2, 3]"` detail (str() of the parsed body).
11. **DEFERRALS PICKED UP** (B0-ARB carried item 6b, all landed here):
    TestRetryStateResetRegression ×4; the streaming project_id raise
    `:1883-1891` + `test_api_client.py:1560-1575` lock;
    `test_export_events_negative_retry_after_uses_backoff` :3810; the C1
    hand-off `test_export_stream_carries_no_workspace_id_param`;
    `TestActivityFeedDateRange` PBT.
12. **stream_events/stream_profiles land as standalone wrapper functions**
    (`services/queries/streaming.ts`) — the B6 `Workspace` facade re-exposes
    them as methods; `transformEvent`'s `$insert_id` uuid seam is threaded as
    `StreamEventsOptions.uuid` (defaults to `crypto.randomUUID` inside the
    B3 transform).

## R10.9 RUN record (throwaway/b4-c2 — deterministic branch matrix)

Run: `bash throwaway/b4-c2/run.sh` @ TS repo, 2026-08-15. No fuzz seeds —
wire methods have no oracle bridge (P3-2 c).

**Result: total=52 pass=52 fail=0.** Branch table (verbatim labels):
seg/200-object, seg/200-array, seg/200-scalar, seg/200-non-JSON→
INVALID_RESPONSE, seg/3xx-with-JSON-body→HTTP_ERROR (R2.11),
seg/400→QueryError, seg/401→AuthenticationError, seg/403-plain→QueryError,
seg/403-sensitive-data→SessionReplayAccessError, seg/404→QueryError,
seg/other-4xx(412)→QueryError, seg/429-retry-then-success,
seg/429-exhausted carries project_id (FF4), seg/5xx→ServerError,
seg/network-error→HTTP_ERROR, listBookmarks/204 via _request→
INVALID_RESPONSE, listBookmarks/422→QueryError, exp/200-two-lines,
exp/429-then-success mid-export (sleep 2000 ms, 2 calls),
exp/429-exhausted reduced shape (:1883-1891 — project_id + retry_after +
request_params present, response_body ABSENT), exp/401, exp/400-json-body,
exp/400-non-json-body (cp-500 slice), exp/malformed-line-skipped,
exp/empty-body-stream, exp/non-BMP 𝒳 line round-trip,
exp/pythonConstants NaN line, exp/5xx retries→HTTP_ERROR,
exp/3xx→raise_for_status analog→HTTP_ERROR, exp/network-error
retries→HTTP_ERROR, exp/edge-params ('["𝒳", ""]' event dump,
empty where omitted, limit=18, Accept-Encoding gzip),
epp/has_more-true (num_pages 2), epp/termination (defaults 0/1000),
ep/loop terminates on empty results page, ep/loop terminates on missing
session_id, ep/page+session threading (page 0/1/2, session_id absent then
"sess"), es/edge-value body encoding (selector omitted for "", action
default, segment_by_cohorts '{"𝒳": true, "": false}',
as_of_timestamp 0 SENT, include_all_users false SENT, project_id "12345"),
es/non-dict-200→QueryError(200, "[1, 2, 3]"), counts/json.dumps edge
spellings ('[1.5, true, null, ""]'), codes/AC2..AC6 (5), codes/WR2,
codes/WR3 (lazy on first next()), af/include-exclude mutex (request_params
exact), af/search_properties-without-search, af/invalid-from_date,
af/to_date-too-early (OverflowError arm), ge/403-gate retry once
(2026-08-15 − 45d = 2026-07-01), ge/str-cast elements
(["True","None","18","𝒳","1.5"] — the "18" cell is a harness-input
limitation: JSON.stringify of a canned 18.0 carries no float token; the
recorded corpus path covers the "18.0" spelling).
