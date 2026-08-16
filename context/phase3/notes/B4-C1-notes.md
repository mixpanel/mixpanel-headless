# B4-C1 notes — client core + wire-enablement seam

**Status**: DONE (module task; review pair pending) · 2026-08-15 · fable ≤ high · packet: `context/phase3/design/b4-packets.md` §Packet C1

## Plan of record

1. Read Python sources (api_client.py C1 ranges, me.py pure half) + B0 TS modules.
2. Layer-3 translation (R10.1/R10.2): test_api_client_session.py (ALL), test_api_client.py
   (construction/close/ctx-mgr + TestPublicRequest), test_query_workspace_scoping.py
   (client-side classes), test_workspace_resolution.py (TestSelectWorkspaceId /
   TestResolveWorkspaceIdWithResolver / TestProjectsMetadataIndex), test_me.py (pure half),
   test_api_client_pbt.py (TestAuthHeaderProperties + the three B0-module PBT classes),
   test_workspace_resolution_pbt.py, test_app_api_client.py B0 deferrals.
3. Implement `packages/core/src/client/client.ts` (createMixpanelClient) + `client/me.ts`.
4. b′ inline: `clientFromSession` + memoization in bindings.ts; register 11 C1 names; replay.
5. R10.9 harness `throwaway/b4-c1/`; RUN record below.

## Progress log

- [x] Notes skeleton committed
- [x] Sources read (api_client.py C1 ranges; me.py :40-411; response_validation.py;
      Layer-3 files; runner/bindings/vector-fetch/canonical/emit._encode_error;
      corpus vector shapes for all 8 measured C1 apis; Python runner targets.py
      build_session/make_api_client mirror points)
- [x] Layer-3 tests translated (132 tests, 7 files under
      `packages/core/test/client/`: client-core 31, client-request 18,
      client-workspace 42, client-scoping 9, me 18, client-pbt 12, me-pbt 2)
- [x] client.ts + me.ts + response-validation.ts + transport.ts green
      (`tsc --strict` clean, all translated tests pass)
- [x] Bindings + vector replay: **3,251 = 1,608 PASS / 0 FAIL / 1,643
      UNPORTED** — exactly baseline 1,528 + the packet's C1 interim delta
      +80 (81 owned minus the P3-1 † carried `workspace.me`-setup vector,
      which stays UNPORTED as designed). Per-name replay (trailing-slash
      filters): app_request 31/31, request 15/15, projects_metadata_index
      10/10, resolve_workspace_id 14/14, resolve_workspace 3/3,
      require_scoped_path 3/3, list_workspaces 5/5. No batch-status flip
      (gate's job).
- [x] R10.9 RUN record (below): 39/39 branches PASS
- [x] npm run check green (109 test files, 4,659 passed / 1,643
      corpus-skipped); commits

## TS files landed

- `packages/core/src/client/client.ts` — `createMixpanelClient` factory
  (R2.9), `ClientCore` seam for C2-C6, append-only domain merge point,
  R6.7 signal-aware request/sleep closures (B0-ARB carried item 6a — B0
  signatures untouched).
- `packages/core/src/client/transport.ts` — the fetch adapter (R2.10
  normalization, R2.11 redirect manual, quote_plus form/query encoding,
  httpx primitive param rendering, rawFetch streaming seam for C2/C6).
- `packages/core/src/client/me.ts` — pure me.py half (models on the
  Phase-2 EntityModel machinery, WorkspaceView, selectWorkspaceId,
  WorkspaceResolver).
- `packages/core/src/client/response-validation.ts` — response_validation.py
  port (see design decision 4; B5 must import, not re-port).
- `packages/core/src/client/json-value.ts` — added `toNativeJson`.
- `conformance-runner/src/wire-client.ts` — clientFromSession (memoized
  under state key `"api_client"`), buildReplaySession (targets.py twin),
  WireCoreError (`_encode_error` twin incl. details_contain),
  coreToVectorJson, registerApiClientCoreBindings (all 11 C1 names incl.
  the 4 setup-only ones).

## Rig changes (fable-authored, in the same commit)

1. `runner.ts`: `InvocationContext.clientOptions` surfaced from
   `call.client_options` (max_retries; Python runner execute.py:529 twin).
2. `interactions.ts`/`transport-errors.ts`/`vector-fetch.ts`: the recorded
   transport_error `message` is now parsed and threaded into the fetch
   rejection's `cause.message` — the Python replay transport re-raises
   `cls(recorded_message)` and `str(e)` lands in `details_contain.error`,
   so the TS rejection must carry the same text (found via 2 FAIL_ERROR
   app_request vectors on first replay; fixed at the rig+adapter layers,
   post-fix 31/31).
3. `conformance-runner/test/runner.test.ts`: `depsWith` now builds a FRESH
   ImplementationRegistry (+contract codecs) instead of createRunnerDeps —
   the synthetic stub tests borrowed real corpus names
   (`api_client.set_workspace_id`, `api_client.get_events`) and collided
   with the real C1 bindings; fresh-registry deps future-proof them
   against every later shard. NOTE for the B4 GATE: the two api-gating
   tests asserting UNPORTED for `api_client.activity_feed` via
   `createRunnerDeps` will need adjustment when the `api_client.` prefix
   flips to done (the flip commit re-runs this suite per P3-5 §4).
4. `eslint.config.js`: `throwaway/**` added to ignores (B0-gate
   precedent — the gate removes it with `throwaway/`); `.prettierignore`
   + `.gitignore`: `throwaway/*/.build/` bundle output.

## Design decisions (recorded before implementation)

1. **details_contain is FULL-equality, not subset** (measured: runner
   `canonicalizeError` compares whole structures; recorder `emit._encode_error`
   emits ALL encodable details minus message/suggestion/fix). C1 adds a
   `WireCoreError` wrapper in the rig whose `toExpectError()` mirrors
   `_encode_error` exactly (class/code/details_contain; BookmarkValidationError
   errors[] branch included for completeness).
2. **Core JsonNumber ≠ runner JsonNumber** (different classes). Wire bindings
   convert core JsonValue results/details through a token-preserving converter
   before `encodeExpectValue`.
3. **`call.client_options` (max_retries; 22 vectors corpus-wide) is not on
   `InvocationContext`** — rig extension: runner.ts `contextFor` now surfaces
   `clientOptions` (fable rig change, mirrors Python runner execute.py:529).
4. **response_validation.py ports at C1** (playbook lists it under B5; C1's
   `list_workspaces` needs it — the two ResponseValidationError vectors lock
   pydantic-style `{type,loc,msg,input}` error lists). B5 must IMPORT
   `client/response-validation.ts`, not re-port. Only the `missing` error row is
   corpus-locked; other pydantic type/msg rows implemented per pydantic-v2
   tables with a TODO(port) disclosure.
5. **httpx param/form serialization**: query params via quote_plus-equivalent
   encoding (URLSearchParams decode washes it out; form `body_text` is
   byte-exact → hand-rolled `quotePlus` matching urllib: safe = ALPHA/DIGIT/
   `_.-~`, space→`+`); primitive values via httpx rules (True→"true",
   None→"", str(int), non-integral floats via pythonFloatStr).
6. **Transport identity (R6.2)**: Python `_http` httpx.Client identity ports as
   a lazily-created `HttpHandle` pool token object (`ensure` on first use,
   nulled by `close()`, PRESERVED by `use()`); Layer-3 identity tests compare
   handle object identity (entry-point substitution documented in test headers).
7. **`use()` is async in TS** (auth-header probe goes through the async
   TokenResolver seam); atomicity preserved (probe before any mutation).
8. **test_query_workspace_scoping client-side classes**: the pin-injection
   assertions port against the internal `requestQueryHost` seam (the exact seam
   Python's TestInjectionOptOut drives via `_request`); the `get_events`/
   `insights_query`/`export_events` public surfaces land at C2 which re-locks
   them end-to-end. `test_export_stream_carries_no_workspace_id_param` is
   DEFERRED to C2 (export_events is C2-owned) — C2 must pick it up.
9. **`from_metadata_entry` bool ids**: Python `isinstance(wid, (int, str))` +
   `int(wid)` accepts booleans (True→1). TS twin handles `true→1/false→0`;
   `int(str)` via pythonInt (R11.7); >2^53 integer-token ids read as unusable
   (R4.5 policy — disclosed, unreachable for real workspace ids).
10. **PBT**: the three MeService-backed resolution properties defer to B8
    (MeService is B8-N2, playbook Discrepancy #5); the two pure
    select_workspace_id properties translate now with the same strategy shapes.

## Findings / TODO(port) log

1. `response-validation.ts` TODO(port): only the pydantic `missing`
   error rows are corpus-locked (`{type:"missing", loc:[field],
   msg:"Field required", input:<payload>}` — the two list_workspaces
   ResponseValidationError vectors); the non-missing type/msg rows follow
   the pydantic-v2 JSON-mode tables and are disclosed as not-yet-locked.
2. Integral-float PARAM spelling: a Python float `18.0` query param
   spells `"18.0"` on the wire; a plain JS number cannot carry
   float-ness, so the adapter renders `"18"` (harness branch "edge values
   through params encoding" documents it). No C1 vector or Layer-3 assert
   passes float params; C2 must thread float-ness through its own call
   shapes where a recorded vector requires it (watchlist §8 item 3).
3. SA Basic-header cache fills LAZILY (TS auth model is async; Python
   caches at construction). Observationally identical — SA derivation is
   pure and the resolver is never consulted for SA (locked by
   test_service_account_session_uses_basic_auth_no_resolver_call).
4. `me.ts` metadata ids: integer tokens beyond 2^53−1 read as unusable
   (R4.5 policy; Python keeps the exact big int) — disclosed, unreachable
   for real workspace ids. Bool ids replicate Python's `bool <: int`
   (`True → 1`).
5. DEFERRALS HANDED TO C2 (add to the C2 packet checklist):
   `test_export_stream_carries_no_workspace_id_param`
   (test_query_workspace_scoping.py:300 — export_events is C2-owned);
   `TestActivityFeedDateRange` PBT (test_api_client_pbt.py:673). Both
   noted in the corresponding test-file headers.
6. `core` has no default TokenResolver (Python defaults to
   OnDiskTokenResolver — node-only I/O, R9.1/R9.4). B8-N2 wires the
   on-disk default at the node layer; until then OAuth header resolution
   without a resolver throws the Phase-2 ParamTypeError.

## R10.9 RUN record (throwaway/b4-c1 — deterministic branch matrix)

Run: `bash throwaway/b4-c1/run.sh` @ TS repo, 2026-08-15. No fuzz seeds —
wire methods have no oracle bridge (P3-2 c); the harness is the hand-built
VectorFetch-style branch matrix over the REAL `createMixpanelClient`.

**Result: total=39 pass=39 fail=0.** Branch table (verbatim labels):
200-object/{query,app,data}, 200-array/{query,app,data}, 200-scalar
{42,"ok",true,null}, 200-non-JSON→INVALID_RESPONSE,
3xx-with-JSON-body→HTTP_ERROR (R2.11), 400→QueryError,
401→AuthenticationError, 403-plain→QueryError,
403-sensitive-data→SessionReplayAccessError (details.project_id int
12345), 404→QueryError, other-4xx(412)→QueryError, 5xx→ServerError,
429-retry-then-success, 429-exhausted carries project_id (FF4),
204-app→{status:ok}, 422-app→QueryError, network-error→HTTP_ERROR
(details.error = cause message); R10.7 403 matrix: bodies 42/1.5/true →
TypeError, 0/false/null → QueryError, ["SESSION_RECORDING_SENSITIVE_DATA"]
exact-element → SessionReplayAccessError, ["x…y"] substring-miss →
QueryError; use() preserves transport identity (R6.2, same harness keeps
serving), pin set→cleared across use(), resolve_workspace_id metadata
fallback, resolve_workspace_id exhausted → NO_WORKSPACES, edge values
(18.0, 1.5, True, None, [], "", "𝒳") through params + JSON body encoding,
lossless 18.0 result token (GATE-R5).
