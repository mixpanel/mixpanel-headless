# B4-C5 notes — data governance + schemas + audit/anomalies/deletion + business context + replays signing

**Task**: b4-packets.md Packet C5 (219 vectors, 64 api-index names + index-absent members).
**Status**: DONE — TS commit `9305700` (mixpanel-headless-ts, branch main).
**Date**: 2026-08-16.

## Progress log

- [x] Packet + Python sources read (`api_client.py:3294-3649`, `:6480-8894`); C1 core seam +
  C3/C4 factory/binding/test patterns inventoried. No prior C5 work found.
- [x] Layer-3 translations FIRST (P3-2 a, red until the factories landed):
  `client-entities-schemas.test.ts` (40), `client-entities-data-governance.test.ts` (109),
  `client-entities-governance.test.ts` (41), `client-sign-replays.test.ts` (5) — 195 tests, all green.
- [x] 12 factories in `packages/core/src/services/entities/` per the packet TS-home list;
  `client.ts` interface extension + 12 append-only spread lines; `shared.ts` gains
  `pythonQuote`/`jsonTruthy`/`pyIntEquals`.
- [x] Bindings: `conformance-runner/src/wire-governance.ts` (all 64 names, same commit — b′ rule).
- [x] Vector replay: 219/219 PASS first replay; cumulative 2,331 PASS / 0 FAIL / 920 UNPORTED.
- [x] R10.9 harness `throwaway/b4-c5/` — 75/75 branches.
- [x] `npm run check` green (exit 0; 126 test files, 5,969 passed / 920 corpus-skipped).
- [x] One TS commit (`9305700`); this notes commit on the Python support branch.

## Design decisions / findings

1. **`pythonQuote` (shared.ts)** — `urllib.parse.quote(s, safe="")` twin for the
   schemas/lexicon path segments (`api_client.py:3426`/`:3469`/`:3634-3636`/`:7080`/`:7118`).
   `encodeURIComponent` is NOT equivalent (passes `!'()*`); byte-loop over UTF-8 with the
   ALWAYS_SAFE set, space → `%20` (unlike `quotePlus`'s `+`). Harness-locked with
   `"User Sign Up / 𝒳"` → `User%20Sign%20Up%20%2F%20%F0%9D%92%B3`.
2. **`get_schemas`/`get_schema` ride the `_request` twin** (`core.requestQueryHost`,
   `injectProjectId: false`) — NOT `appRequest`. Vector-confirmed: the recorded requests
   carry `params={"query_origin":"mixpanel-headless"}` and NO `project_id` (the pid is in
   the path), and the error vectors carry `request_params` in `details_contain` (the
   `executeWithRetry` detail shape, vs `request_params: {}` on the appRequest names).
3. **`dict.get` twin without an isinstance guard** — `get_schemas`/`get_schema` call
   `.get` on an `Any` annotated `dict`; a non-dict body raises AttributeError in Python.
   TS throws the closest analog (`TypeError` with the CPython message spelling) — a
   `// TODO(port)` documents that no vector/Layer-3 locks the non-dict arm, and that the
   source's debug-log set comprehension failure modes are not replicated (R9.5: log-only).
   Also: `results: null` returns `null` (the `.get` default applies only to ABSENT keys) —
   harness-locked (`edge/get_schemas-results-null-returns-null`).
4. **Direct-request pair** (`register_lookup_table` `:7716`, `download_lookup_table`
   `:7919` — the B0 R10.8 ownership call sites): `core.rawRequest` + B0 `requestHeaders`
   with an explicit Authorization extra + MANUAL `handleResponse` on `status >= 400`,
   bypassing the retry loop. Consequence (harness finding, expectation corrected during
   the run): a 429 on this path is the `_handle_response` other-4xx **QueryError** —
   single attempt, never RateLimitError ("429 is handled by the callers' retry loops,
   never here"). `response.json()` → `parseLossless(text, {pythonConstants: true})` with
   the `instanceof LosslessJsonError` guard (GATE-R5 + B0-ARB F3); `text[:500]` → `cpSlice`.
   NOTE: the packet's parenthetical "(+ Accept-Encoding: gzip on download)" is NOT in the
   source at support-branch HEAD — `:7919-7925` builds only
   `_request_headers({"Authorization": ...})`; ported per source truth (the recorded
   download vectors carry no Accept-Encoding assertion either).
5. **`upload_to_signed_url`** — external PUT through the injected fetch with ONLY
   `Content-Type: text/csv` (no auth, no 4-layer merge — GCS signature). Its own
   `httpx.HTTPError → UPLOAD_ERROR {url}` mapping is replicated with the R2.10 adapter's
   classification guards (Abort passthrough; TypeError/DOMException/MixpanelHttpError →
   wrap; anything else rethrows — no bare catch). Status ≥ 300 → UPLOAD_ERROR
   `{status_code, url}`. Bytes body means the B0 `TransportRequestOptions` shape can't
   carry it; the method calls the injected fetch directly (mirroring Python's fresh
   `httpx.Client`) rather than widening a B0 signature.
6. **`create_custom_event`** — `appRequest` form body; peels the `{custom_event: ...}`
   inner envelope after the standard `results` unwrap; non-dict guard. 422's
   `details.request_body` carries the FORM dict (B0 appRequest already provides this —
   Layer-3-locked).
7. **`update_custom_event` echo check** — `returned_id != custom_event_id` is CPython
   numeric cross-type equality: `pyIntEquals` (shared.ts) accepts JsonNumber/number/
   bigint/bool (`42.0 == 42` no-raise, `"42" != 42` raises UPDATE_TARGET_MISMATCH —
   both harness-locked). Message uses a repr-ish spelling (strings quoted) — message
   text out of contract (R5.4), but the Layer-3 lock asserts both ids appear.
8. **`export_lexicon`** — `json.dumps(types)` → `pythonJsonDumps` (ensure_ascii:
   `["𝒳", ""]` → `["𝒳", ""]` on the wire — harness-locked). String `results`
   → `{status: "pending", message}` wrap.
9. **`name[]` list params** — `_event_definitions`/`_property_definitions` thread
   `string[]` values through `AppRequestOptions.params` with a cast mirroring Python's
   own `# type: ignore[arg-type]` at `:6507`/`:6730`; the transport's
   `urlencode(doseq=True)` twin emits repeated keys (harness:
   `name%5B%5D=%F0%9D%92%B3&name%5B%5D=&name%5B%5D=Sign+Up`).
10. **List-returning mutations** (Caution #11 "no results-unwrap surprises"):
    `create/update/delete_drop_filter`, `create_deletion_request`,
    `cancel_deletion_request` return LISTS; `run_audit`/`run_audit_events_only` use
    `_raw=True` with the exact dict-with-results / bare-list / else ladder;
    `list_data_volume_anomalies` digs `results.anomalies` with the
    `result.get("results", result)` passthrough arm (harness-locked both ways).
11. **Business context** (index-absent ×3) — direct project/org paths, NEVER
    `maybe_scoped_path` (harness-locked: workspace pin does not scope it).
12. **`sign_replays`** — plain `appRequest` POST; the 403 sensitive-data branch lives in
    B0 `handleResponse` (R10.8 — nothing re-implemented). The R10.7 bug-compat matrix is
    re-exercised through the REAL method (harness section 2): dict-with-flag →
    SessionReplayAccessError (details `project_id=12345` int via `pythonInt`, `flag`,
    `permission_required`); truthy scalars `42`/`1.5`/`true` → plain TypeError;
    falsy `0`/`false`/`null`/`""` → QueryError; `["SESSION_RECORDING_SENSITIVE_DATA"]`
    exact-element → SessionReplayAccessError; `["x…y"]` substring-miss → QueryError.
    Bug report `python-handle-response-403-typeerror.md` replicated, NOT fixed.
13. **`download_lookup_table` bytes** — method returns `Uint8Array`; the binding encodes
    via the recorder's own bytes codec (`encodeExpectValue` → `$type: bytes` base64
    carrier) — the one output-codec adaptation beyond the C1 twins (P3-5 §3 disclosed).
14. **Header exclusion** (`client-sign-replays.test.ts`): TestSensitiveDataMapping +
    TestOtherHttpErrors were translated at B0 against `handleResponse`
    (`b0-review-assertions.md`); only TestSignReplaysRequest translates here (packet
    §Layer-3 scope).
15. **Edge-value disclosure**: `18.0` is not representable from a plain JS number at
    these call sites (all C5 numeric params are ints in the source signatures); the
    packet's C2 float-carrier note applies — the edge set ran with
    `1.5`/`true`/`null`/`[]`/`""`/`"𝒳"` plus int ids.

## Rig changes

- `conformance-runner/src/wire-governance.ts` (NEW): `registerGovernanceWireBindings`
  — 64 registrations, memoized `clientFromSession` + one client call + kwarg
  passthrough (absent-stays-absent via the C3 `kwargBag` twin). `get_schemas` (the
  shard's setup api, 1 corpus-wide occurrence) is covered by its ordinary binding.
- `conformance-runner/src/bindings.ts`: one import + one registration call (append-only).
- No oracle registration: wire names have no oracle call surface (P3-2 c/e).

## Vector replay (219/219 PASS; no batch-status flip)

Full-suite conformance after the shard commit:
**3,251 vectors = 2,331 PASS / 0 FAIL / 920 UNPORTED @ 70c904d** — exactly the packet's
C1+C2+C3+C4+C5 interim expectation (delta +219). Per-name replay (trailing-slash
filters per the packet's substring-trap rule; columns: total/pass/fail/unported):

| name | n | P | F | U | | name | n | P | F | U |
|---|---|---|---|---|---|---|---|---|---|---|
| get_schemas | 7 | 7 | 0 | 0 | | list_custom_properties | 3 | 3 | 0 | 0 |
| get_schema | 5 | 5 | 0 | 0 | | create_custom_property | 2 | 2 | 0 | 0 |
| list_schema_registry | 7 | 7 | 0 | 0 | | get_custom_property | 2 | 2 | 0 | 0 |
| create_schema | 7 | 7 | 0 | 0 | | update_custom_property | 2 | 2 | 0 | 0 |
| create_schemas_bulk | 9 | 9 | 0 | 0 | | delete_custom_property | 2 | 2 | 0 | 0 |
| update_schema | 5 | 5 | 0 | 0 | | validate_custom_property | 2 | 2 | 0 | 0 |
| update_schemas_bulk | 5 | 5 | 0 | 0 | | list_lookup_tables | 4 | 4 | 0 | 0 |
| delete_schemas | 6 | 6 | 0 | 0 | | get_lookup_upload_url | 4 | 4 | 0 | 0 |
| get_event_definitions | 5 | 5 | 0 | 0 | | upload_to_signed_url | 3 | 3 | 0 | 0 |
| list_event_definitions | 2 | 2 | 0 | 0 | | register_lookup_table | 3 | 3 | 0 | 0 |
| update_event_definition | 2 | 2 | 0 | 0 | | mark_lookup_table_ready | 2 | 2 | 0 | 0 |
| delete_event_definition | 2 | 2 | 0 | 0 | | get_lookup_upload_status | 2 | 2 | 0 | 0 |
| bulk_update_event_definitions | 2 | 2 | 0 | 0 | | update_lookup_table | 2 | 2 | 0 | 0 |
| get_property_definitions | 4 | 4 | 0 | 0 | | delete_lookup_tables | 2 | 2 | 0 | 0 |
| list_property_definitions | 4 | 4 | 0 | 0 | | download_lookup_table | 3 | 3 | 0 | 0 |
| update_property_definition | 2 | 2 | 0 | 0 | | get_lookup_download_url | 3 | 3 | 0 | 0 |
| bulk_update_property_definitions | 2 | 2 | 0 | 0 | | create_custom_event | 11 | 11 | 0 | 0 |
| list_lexicon_tags | 3 | 3 | 0 | 0 | | update_custom_event | 4 | 4 | 0 | 0 |
| create_lexicon_tag | 2 | 2 | 0 | 0 | | delete_custom_event | 4 | 4 | 0 | 0 |
| update_lexicon_tag | 2 | 2 | 0 | 0 | | get_schema_enforcement | 4 | 4 | 0 | 0 |
| delete_lexicon_tag | 2 | 2 | 0 | 0 | | init_schema_enforcement | 2 | 2 | 0 | 0 |
| get_tracking_metadata | 2 | 2 | 0 | 0 | | update_schema_enforcement | 2 | 2 | 0 | 0 |
| get_event_history | 2 | 2 | 0 | 0 | | replace_schema_enforcement | 2 | 2 | 0 | 0 |
| get_property_history | 2 | 2 | 0 | 0 | | delete_schema_enforcement | 2 | 2 | 0 | 0 |
| export_lexicon | 5 | 5 | 0 | 0 | | run_audit | 5 | 5 | 0 | 0 |
| list_drop_filters | 3 | 3 | 0 | 0 | | run_audit_events_only | 4 | 4 | 0 | 0 |
| create_drop_filter | 2 | 2 | 0 | 0 | | list_data_volume_anomalies | 6 | 6 | 0 | 0 |
| update_drop_filter | 2 | 2 | 0 | 0 | | update_anomaly | 2 | 2 | 0 | 0 |
| delete_drop_filter | 2 | 2 | 0 | 0 | | bulk_update_anomalies | 2 | 2 | 0 | 0 |
| get_drop_filter_limits | 3 | 3 | 0 | 0 | | list_deletion_requests | 3 | 3 | 0 | 0 |
| | | | | | | create_deletion_request | 2 | 2 | 0 | 0 |
| | | | | | | cancel_deletion_request | 3 | 3 | 0 | 0 |
| | | | | | | preview_deletion_filters | 2 | 2 | 0 | 0 |
| | | | | | | sign_replays | 10 | 10 | 0 | 0 |

Σ = 219 vectors, 219 PASS (24 of them `expect.error` vectors — QueryError/
AuthenticationError/ServerError/SessionReplayAccessError/UNKNOWN_ERROR/
INVALID_RESPONSE/MISSING_FIELD/UPLOAD_ERROR/UPDATE_TARGET_MISMATCH/HTTP_ERROR shapes
all matched via the shared `WireCoreError` codec).

## R10.9 RUN record (throwaway/b4-c5/, deterministic — no fuzz seeds)

`bash throwaway/b4-c5/run.sh` → **75 branches, 75 passed, 0 failed** (2026-08-16,
post-prettier re-run confirmed).

Branch table:
- §1 create_schema status matrix (17): 200-object · 200-array-shape-guard ·
  200-scalar-shape-guard · 200-non-JSON INVALID_RESPONSE · 3xx-json-body HTTP_ERROR ·
  400 QueryError · 401 AuthenticationError · 403-plain QueryError ·
  403-sensitive-data SessionReplayAccessError · 404 · 412-other-4xx · 422-app-lossless ·
  429-retry-then-success (2 attempts) · 429-exhausted RateLimitError (maxRetries=2) ·
  5xx ServerError · 204-app `{status:"ok"}` · network-error HTTP_ERROR · plus the
  quote(safe="") path lock.
- §2 sign_replays R10.7 matrix (13): flag-in-dict · plain-dict QueryError · truthy
  scalars 42/1.5/true → TypeError ×3 · falsy 0/false/null/"" → QueryError ×4 ·
  list exact-element flag · list substring-miss · body-shape/env-default ·
  200-non-list guard.
- §3 upload_to_signed_url (3): PUT with NO auth/user-agent header + byte-exact 𝒳 body ·
  status-300 UPLOAD_ERROR {status_code,url} · transport UPLOAD_ERROR {url}.
- §4 register/mark-ready (7): form content-type + quote_plus body byte-exact · results
  unwrap · no-results-key verbatim · non-JSON-200 INVALID_RESPONSE · non-dict guard ·
  401 through handleResponse · **429-NOT-retried** (single attempt, other-4xx
  QueryError — the harness's one corrected expectation; see finding 4) ·
  mark_lookup_table_ready delegation.
- §5 download_lookup_table (2): bytes + params + merged auth headers · 404 QueryError.
- §6 list-returning endpoints (7): drop-filter create/guard/delete-body ·
  cancel_deletion_request list+DELETE-body · run_audit 2-element/non-list/bare-list.
- §7 edge values (26): name[] repeated params (𝒳/""/space) · export_type ensure_ascii ·
  default export types · history-path quote · JSON body edge values
  (""/true/[]/null/1.5/𝒳) · delete_schemas guard fires before any request ·
  list_property_definitions defaults + false toggles + people→User normalization ·
  get_schemas query-host route + results-null · get_schema normalized shape ·
  custom-event form quote_plus · float-echo 42.0==42 · string-echo mismatch ·
  workspace pin scopes C5 paths · business-context project/org scope ·
  download-url falsy-MISSING_URL/fallback-key · upload-url MISSING_FIELD ·
  anomalies passthrough/missing-key · export_lexicon pending-wrap.

Disclosure: `18.0` (integral float) is untestable from plain JS numbers at C5 call
sites (int-typed ids throughout); packet edge set otherwise complete.

## Done-criteria check

- [x] tsc --strict clean; `npm run check` green (exit 0).
- [x] 195 translated Layer-3 tests green (written first, red before implementation).
- [x] All 219 C5 vectors PASS; cumulative 2,331/0/920 (= packet interim; flip deferred
      to the gate).
- [x] Bindings + `get_schemas` setup coverage in the same shard commit (b′).
- [x] R10.9 RUN record (above).
- [x] One TS commit: `9305700`. Notes commit: this file.
