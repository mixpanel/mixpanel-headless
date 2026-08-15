# Adversarial review — phase3-playbook.md — Lens: PORTING FIDELITY

Reviewer: fidelity lens · 2026-08-15 · playbook @ dbb08a7 (`context/phase3/design/phase3-playbook.md`)
Sources verified: `src/mixpanel_headless/_internal/api_client.py` (support-branch HEAD, read end-to-end
for every cited range), `context/typescript-port-api-map.json`,
`conformance-runner/{src/runner.ts,src/batch-status.ts,src/vector-fetch.ts,src/authored-apis.json,corpus/*}`,
`tests/unit/test_api_client.py`, live recounts of the 3,179-vector corpus.

## Verdict summary

The playbook's measurements are excellent — every count I recomputed matched exactly. The B0
retry/backoff spec is faithful to post-PR-206 source on the load-bearing items (60s clamp in
`_retry_wait_seconds`, negative/unparseable/HTTP-date Retry-After → None, jitter on the backoff
fallback only, Discrepancy #1 correctly anchored at `api_client.py:680`). The findings below are
where the spec or the enablement plan deviates from what the code actually does.

## Findings

### F1 (major) — B5 flip mechanics: `workspace.list_bookmarks` exact-name entry prefix-captures the B6 member `workspace.list_bookmarks_v2`

P3-5 §4 says the B5 gate adds 44 exact-name `done` entries "generated mechanically" with
`jq ... select(.batch=="B5") ... "workspace." + .name`. But `batchStatusFor`
(`conformance-runner/src/batch-status.ts:90-95`) is `api.startsWith(prefix)` longest-match, and
the B5 member `list_bookmarks` is a string prefix of the B6 member `list_bookmarks_v2`
(verified: the only such B5→B6 collision in the api-map). At the B5 gate the entry
`workspace.list_bookmarks` → done would flip the **7** `workspace.list_bookmarks_v2` vectors
(counted in corpus) from UNPORTED to FAIL_ERROR while B6 is still pending — the gate's own
expectation ("FAIL = 0; UNPORTED shrinks by exactly 480", P3-2 e.2 / P3-5 §4 closing line)
becomes unsatisfiable as written. Note `workspace.list_bookmarks` itself carries **0** corpus
vectors, so the offending entry protects nothing.
**Fix**: at the B5 flip, either add a longer overriding entry `workspace.list_bookmarks_v2` →
pending (longest-prefix wins), or exclude `list_bookmarks` from the generated list (it has no
vectors), and add a P3-5 rule: after generating exact-name entries, assert no pending api name
in the corpus startsWith any generated entry.

### F2 (major) — P3-5 wire-enablement plan ignores `call.setup[]` and the shared per-vector state map

P3-5 §1 defines the whole client-construction story as `clientFromSession(context)` per binding.
But the runner executes `call.setup[]` entries *before* the measured call with a **shared
`state` map** created once per vector (`runner.ts:446`, `runner.ts:478-500`; doc comment
`runner.ts:51-52`: "state map is shared … so state-mutating setup calls (`set_workspace_id`, …)").
Measured from the corpus: **97** `api_client.set_workspace_id` setup entries plus
`api_client.close` (8), `api_client.retention`/`list_bookmarks`/discovery prerequisites,
`api_client.use` (2), `api_client.resolve_workspace_id` (2), etc., attached to 100+ wire vectors
(`activity_feed` 26, feature-flag and saved-report families, …). All setup + measured traffic is
served by ONE `createVectorFetch(interactions)` harness per vector. If `clientFromSession`
builds a fresh client on every binding invocation — which is the natural reading of P3-5 §1 —
the `set_workspace_id` setup mutates a different instance than the measured call and every
workspace-scoped vector fails FAIL_REQUEST (project-scoped path instead of `/workspaces/{wid}/…`).
**Fix**: P3-5 §1 must state that `clientFromSession` memoizes the constructed client in
`context.state` (keyed per vector) so setup entries and the measured call share the instance,
and that every setup api (`set_workspace_id`, `close`, `use`, `resolve_workspace`, …— all
present in the 183 api-index names) needs a binding at B4, or the vectors carrying them
short-circuit at `gateApis` (`runner.ts:372-386`).

### F3 (major) — `_handle_response` fallthrough branch order is inverted in the B0 checklist; the 2xx JSON-scalar path is missing

Playbook: "2xx/other → return parsed body if object/array, else re-raise-for-status helper …
non-JSON 2xx → `MixpanelHeadlessError` INVALID_RESPONSE". Actual source order
(`api_client.py:652-662`): `response.raise_for_status()` runs **first**, then the
object/array return, then a second `response.json()` whose success returns **JSON scalars**
(`42`, `"ok"`, `true`, `null`) and whose JSONDecodeError raises INVALID_RESPONSE. Two concrete
divergences for a builder implementing the checklist verbatim:
1. A 3xx response (reachable in TS — R2.11 mandates `redirect: 'manual'`) with a JSON object
   body would be *returned as success*; Python raises (verified: httpx `raise_for_status`
   raises `HTTPStatusError` on 302), and because `httpx.HTTPStatusError ⊂ httpx.HTTPError`
   the raise is then caught at `api_client.py:801` and wrapped as `MixpanelHeadlessError`
   code `HTTP_ERROR`. The checklist neither orders the raise first nor states that the R2.11
   throwing helper must throw a `MixpanelHttpError`-normalized error so the `_execute_with_retry`
   catch produces the same `HTTP_ERROR` wrap.
2. A 2xx JSON-scalar body returns the scalar in Python (verified: `Response(200, b"42").json()`
   → 42); the checklist's "else … INVALID_RESPONSE" reading throws instead.
**Fix**: restate the tail as source order: (i) non-2xx-non-mapped status → throwing helper
(error must funnel to the HTTP_ERROR wrap); (ii) parsed body object/array → return; (iii)
re-parse: JSON scalar → return scalar; parse failure → INVALID_RESPONSE with `cpSlice(text,0,500)`.

### F4 (major) — RateLimitError spec omits `project_id` (and the corpus cannot catch the omission)

Every RateLimitError raise site passes `project_id=self.project_id`: `_execute_with_retry`
(`api_client.py:779`, and the fallthrough `:819`), `app_request` (`:1322`, `:1386`), streaming
export (`:1890`). The P3-4 retry bullet specs only "retry_after … + lossless-parsed body". This
omission is NOT vector-caught: 429 corpus vectors assert errors via `details_contain` subset
matching (e.g. `pagination.paginate_all` vectors list only
`request_method/request_url/response_body/status_code`), so a port that drops `project_id`
replays green. It IS asserted by the Layer-3 files B0 must translate
(`tests/unit/test_api_client.py:504,527,1567,4090` — `exc_info.value.project_id == "12345"`),
but the playbook's checklist is defined as "each line = an assertion the review pair verifies",
so the missing line weakens exactly that review. Also note the two constructor shapes: the
final-fallthrough raises (`:814-820`, `:1381-1387`) omit `retry_after`/`status_code`/
`response_body`.
**Fix**: add `project_id: this.session.project.id` (Python spelling in the detail bag, R7.6) to
the RateLimitError line of the checklist, and note both constructor arg-sets.

### F5 (major) — `_request_headers` is consumed by both B0 functions but has no B0 row (R10.8 ownership ambiguity)

B0-2's `_execute_with_retry` calls `self._request_headers(headers)` (`api_client.py:747`) and
`app_request` calls it at `:1264`, yet the B0 table gives `_request_headers`
(`api_client.py:452-481` — the 4-layer merge: `User-Agent` from `get_user_agent()` →
`MP_CUSTOM_HEADER_NAME`/`MP_CUSTOM_HEADER_VALUE` env pair → `session.headers` → caller extras)
no TS home; it appears only parenthetically in the `_execute_with_retry` bullet, while B4-C1's
scope also claims "headers". Two claimed owners for behavior both B0 packets need on day one is
the R10.8 duplicate-implementation failure mode this batch exists to prevent — and its Layer-3
lock (`test_settings_headers.py`) is listed under **B8**, so neither B0 nor B4 translates it.
**Fix**: give `_request_headers` an explicit row (e.g. `client/headers.ts`, B0, with the env-pair
and session-headers layers named), have C1 import it by name, and move/copy
`test_settings_headers.py` into the B0/B4 Layer-3 list.

### F6 (minor) — `_error_message` dict branch: `{"error": null}` returns the default, not `pythonStr(None)`

`api_client.py:98-100`: `raw = body.get("error"); if raw is None: return default`. The playbook
line "dict with `error` key → string as-is, non-string `error` → `pythonStr(raw)`" maps
`{"error": null}` to `"None"`. Message text is out of contract (R5.4), but the playbook chose to
port the defaults, so the branch should be stated: absent OR null `error` → default.

### F7 (minor) — B4 sharding says "assign each of the 183 `api_client.*` api-index names to exactly one of C2–C5", but the 183 include C1-owned names

Verified in `corpus/api-index.json`: the 183 include `api_client.use`, `set_workspace_id`,
`close`, `with_project`, `resolve_workspace_id`, `require_scoped_path`, `maybe_scoped_path`,
`request` — all client-assembly/scoping names the playbook itself assigns to C1 (or B0 for
`maybe_scoped_path`). The gate's mechanical coverage diff as written ("covers all 183" over
C2–C5) either fails or pressures the packet author to misassign client-assembly names into
domain shards. **Fix**: "exactly one of C1–C6 (with B0-owned `_iter_jsonl_lines` excluded and
`maybe_scoped_path` counted as B0-bound)".

### F8 (minor) — B2 row: "Vectors: 690 (all kind: validation-error or builder)"

Measured: all 690 `validation.` + `user_validators.` vectors are `kind: "builder"`; zero carry
`kind: "validation-error"` (error expectations ride on builder-kind vectors via `expect.error`).
Harmless, but the row reads like a report expectation; state "all kind builder (error cases via
`expect.error`)".

## Verified-correct claims (no action)

- **Vector counts, all recounted exactly**: total 3,179; PASS composition 461 = types 419 +
  compat 34 + wirestub 8; B2 = 512+178 = 690; B3 = 134+51+82+30+2 = 299; B4 = 810−6+39 = 843;
  B5 = 480+8+16+2 = 506; B6 = 353; B7 = 14; B8 = 7; cumulative column arithmetic exact.
- **B5/B6 workspace split**: api-map batches B4=3/B5=44/B6=158 (205 total); the 44 B5 names carry
  exactly 480 of 833 `workspace.*` vectors; per-member counts match verbatim (build_params 143,
  build_funnel_params 95, build_user_params 80, build_retention_params 55, build_flow_params 53,
  query_saved_report 37).
- **B6 W-group arithmetic**: every section count (6+2+3+4, 6+16, 9+7, 11+12, 7+5+11, 11+4,
  5+6+9+4, 6+5+2+3+4) matches the api-map sections; Σ=158.
- **B0 line anchors**: `_error_message` :81, `_iter_jsonl_lines` :109, ENDPOINTS :153-172,
  `_handle_response` :503-662, `_calculate_backoff` :664-681, `_retry_wait_seconds` :683-704,
  `_execute_with_retry` :706-820, `_parse_retry_after` :1159-1185, `app_request` :1191-1387,
  `maybe_scoped_path` :1637-1664, `max_retries=3` :312 — all correct.
- **Retry semantics**: 60s clamp lives in `_retry_wait_seconds` (`min(float(retry_after), 60)`),
  not in `_parse_retry_after` — playbook places it correctly; negative → None (`:1183-1185`,
  zero accepted); HTTP-date → None via `int()` ValueError; jitter only on the backoff fallback
  (`:680`) — Discrepancy #1 is real and correctly cited; 5xx/network no-retry confirmed;
  `pythonInt` is the right model for `int(retry_after)` (underscores + Nd digits accepted by
  CPython — the Nd-digit port rationale in B0-1 item 1 is sound).
- **`_handle_response` mapped branches**: 401 / 403-sensitive (substring on
  `json.dumps(body)`-or-string, `int(project.id)` coercion, details keys exact) / 403-plain
  "Permission denied" / 400 "Unknown error" / 404 "Resource not found" / other-4xx "Request
  failed" / 5xx `"Server error: " + …` — all match source order and defaults; all six error
  raises carry the full request-context kwargs including `request_body` (the PR-206 401 fix
  is in).
- **`app_request`**: AC1 guard, per-call auth resolution before the loop, no `query_origin`
  (vs. `:746` injection in `_execute_with_retry`), 204 → `{"status": "ok"}` before the 429
  check, own 429 loop reusing the trio, 422 → QueryError with lossless body, `"results" in`
  unwrap gated on `_raw` — all as specced.
- **`_iter_jsonl_lines`**: byte-buffer split on 0x0A, per-line UTF-8 decode
  `errors="replace"`, Python `.strip()` (→ `pythonStrip` ✓), tail flush — matches; the 6
  authored vectors exist at `corpus/authored/streaming/jsonl-chunks.jsonl`; the name resolves
  today as module-known → UNPORTED (not UNMAPPED), so B0's bind-without-flip plan works;
  18 `api_client.*` streaming wire vectors confirmed.
- **`maybe_scoped_path`**: `/workspaces/{wid}/{path}` (no project segment) vs
  `/projects/{pid}/{path}` — playbook templates exact; `require_scoped_path`/`resolve_workspace_id`
  correctly excluded from B0 (network discovery).
- **B0 internals enumeration otherwise complete**: swept every module-level def and private
  method in `api_client.py`; the non-enumerated helpers are single-consumer
  (`_canonical_resource_type` — 1 call site :6721; `_parse_feed_date`/
  `_build_activity_feed_date_range` — activity-feed only; `_event_definitions`/
  `_property_definitions` — C5-local) or explicitly seam-replaced (`_get_auth_header` → Phase-2
  auth model). Streaming's inline 429 loop (`export_events` :1870-1896) reuses the B0 trio by
  name — no hidden duplicate. `_request_headers` is the one real gap (F5).
- **Runner/VectorFetch claims**: `session`/`workspaceSession` surfaced on the binding context
  (`runner.ts:462-467`); `createVectorFetch` has positional serving, unordered-group keyed
  matching, `transport_error` rejection, `body_stream` chunk rebuild (`vector-fetch.ts`
  header + :141-164, :255-308); `parseAccount`/`accountAuthHeader`/`sessionAuthHeader` exist in
  `packages/core/src/auth/account.ts`; `wirestub.ts:198` is exactly the grandfathered
  `response.json()`; `batch-status.ts` doc comment does bin user_builders/expressions/transforms
  under "B2" (Discrepancy #2 real); longest-prefix + exact-name flips work as designed
  (modulo F1).
- **Layer-3 cites**: `test_api_client.py:444-540` (429/Retry-After: 0 loops incl. the
  project_id asserts), `:1436-1560` (retry-state reset), `:1762-1800` (hostile Retry-After
  hardening block), `:3467-3520` (streaming 429) — all present as described.
- **LOC claims**: pagination 288, workspace 11,292, client_metadata 73, validation 3,090,
  user_validators 580 — exact. B4 api-map members = `stream_events`/`stream_profiles`/`api` ✓.
- Corpus pin `sourceCommit 8ae76314…` matches `corpus.config.json` ✓.
