# B4-C3 notes — entity CRUD wire methods: dashboards (+blueprints/RCA) + bookmarks-v2 + cohorts-app

**Status**: complete · 2026-08-15/16 · fable ≤ high · packet: `context/phase3/design/b4-packets.md` §Packet C3.
Scope: 38 api-index names, 78 vectors, Python `api_client.py:3650-4937`.

## Progress log

- 2026-08-15: task start. Inventory: NO prior C3 work in the TS repo
  (`packages/core/src/services/entities/` absent; no C3 bindings; no
  `throwaway/b4-c3/`). C1 (4f7bfa5) and C2 (99ba862) landed — factory
  seams (`ClientCore`, `clientFromSession`, `runWire`/`coreToVectorJson`,
  `kwargBag` pattern) all present and binding.
- Read: packet C3 + Cautions; Python source :3650-4937 in full; the three
  Layer-3 sources in full (`test_api_client_crud.py` 1,059,
  `test_api_client_crud_edge.py` 605, `test_api_client_bookmarks.py` 548);
  C1 `client.ts`, C2 `engage.ts`/`query-host.ts` (pattern), `wire-client.ts`
  + `wire-queries.ts` (binding pattern), `client-test-helpers.ts`.
- 2026-08-15: TDD red — 3 translated suites written first
  (`client-entities-crud.test.ts` 49, `client-entities-crud-edge.test.ts` 33,
  `client-entities-bookmarks.test.ts` 23); crud suite red 49/49 (methods
  absent), bookmarks suite green immediately (locks C2 members — expected,
  see decision 2).
- 2026-08-15: implementation green — `services/entities/{shared,dashboards,
  bookmarks,cohorts}.ts` + the three append-only spread lines in
  `client/client.ts`; 105/105 shard tests pass; `tsc --strict` clean.
- 2026-08-15: bindings landed inline (`conformance-runner/src/wire-entities.ts`,
  38 registrations; wired in `bindings.ts`). Full conformance:
  **3,251 = 2,003 PASS / 0 FAIL / 1,248 UNPORTED** — exactly the packet's
  C1+C2+C3 interim expectation (+78; no batch-status flip).
- 2026-08-16: R10.9 harness `throwaway/b4-c3/` — **65/65 branches OK**
  (RUN record below). `npm run check` exit 0 (117 files, 5,337 passed /
  1,248 corpus-skipped).

## Design decisions

1. **TS homes exactly per packet**: `packages/core/src/services/entities/
   {dashboards,bookmarks,cohorts}.ts`, one exported `create<Domain>Methods
   (core)` factory each (R2.9/R7.2), spread into `createMixpanelClient` at
   the marked append-only merge point (three lines, no reordering).
   `entities/shared.ts` carries the shard-shared guards
   (`expectRecordResult`/`expectListResult` — the `isinstance(result,
   dict/list)` twins with Python message shapes), Python truthiness
   helpers, and `joinIds` (`",".join(str(i)…)` via `pythonStr`, R11.7).
2. **`test_api_client_bookmarks.py` locks C2 members** (`list_bookmarks`
   legacy, `query_saved_flows`, `query_saved_report` routing) but the C3
   packet row owns the FILE — translated here against the landed C2
   methods (file header cites the packet). No C2 code changed; all 23
   tests passed against the existing implementation on first run (an
   independent-translation cross-check of C2's querySavedReport routing
   + date-derivation arms).
3. **isinstance-dict predicate**: parsed wire values are JsonValue trees
   (no PyFloat carriers / class instances), so the guards use B0
   `isPlainRecord` (client-internal "JSON object body" predicate), NOT
   `isPythonDict` — per the watchlist #13 note in Caution #9 (recorded in
   `entities/shared.ts` JSDoc).
4. **v2 markers ported verbatim**: `list_bookmarks_v2`/`get_bookmark` send
   `v=2` as a STRING query param; `create_bookmark`/`update_bookmark`
   merge `"v": 2` (INT) into the JSON body via `{...body, v: 2}` (same
   string-key ordering as Python's `{**body, "v": 2}`).
5. **`get_bookmark_history` mutation twin**: Python mutates the parsed
   `inner` dict (`inner["pagination"] = None`); TS returns
   `{...inner, pagination: null}` — same content, same key position
   (append), no shared-reference observability on the wire path.
6. **`list_blueprint_templates` warning skip**: Python `logger.warning`
   for non-dict template entries is not observable — TS skips silently
   (comment cites the line range). Known JS-runtime caveat noted for the
   review pair: integer-like template NAMES would iterate in JS
   numeric-key order, not insertion order (no vector or Layer-3 lock
   carries one; plain-record product of parseLossless).
7. **`remove_report_from_dashboard` return type**: Python hints
   `dict | None` but the isinstance guard makes the None arm unreachable
   (204 → `{"status": "ok"}` IS a dict); TS returns
   `Promise<Record<string, JsonValue>>` (harness branch
   `cd/204-app-status-ok-dict` locks the envelope product).
8. **Bindings**: 38 registrations in `wire-entities.ts`, each = memoized
   `clientFromSession` + ONE method call + kwarg passthrough
   (`kwargBag` absent-stays-absent for options; `requireWireKwarg` for
   positional); void Python methods return `null` (recorder `None`).
   Kwarg spellings verified against the measured corpus (38/38 names,
   78 vectors, all input-key sets enumerated before writing).

## Findings / discrepancies

- **Pre-existing fmt:check failure on main**: `throwaway/b4-c2/harness.ts`
  was committed unformatted at 99ba862 — `npm run check` (prettier
  `fmt:check`) failed at C3 start BEFORE any C3 change. Fixed by
  `prettier --write` (formatting-only) inside the C3 commit; flagged for
  the C2 review pair / gate.
- **Rig-change log** (beyond bindings): `conformance-runner/test/
  runner.test.ts` UNPORTED-probe re-pointed `api_client.list_dashboards`
  → `pagination.paginate_all` (the C1-notes-documented churn: each shard
  binding the current probe name must re-point it; C6/the gate re-adjusts
  next — post-flip it must move to a B5+ name, comment updated in place).
- No behavior discrepancies against the Python source found; no
  TODO(port) markers needed for this shard.
- Float-identity caveat (pre-existing, R11.4-class): a hypothetical
  recorded JSON body carrying float-typed ids (e.g. `18.0` in
  `bulk_delete_dashboards`) would serialize as `18` from a native JS
  number. No C3 vector carries one (verified: all recorded ids are
  ints); `joinIds` param spellings are covered by pythonStr for the
  query-param path.

## R10.9 RUN record (2026-08-16)

Command: `bash throwaway/b4-c3/run.sh` → **65/65 branches OK**
(deterministic hand-built matrix; wire names have no oracle bridge,
P3-2 c — the harness is the differential, expectations transcribed from
`api_client.py:3650-4937` + `_handle_response`/`app_request` B0 ranges).

Branch table (all PASS):
- `cd/*` — the §Wire status matrix through `create_dashboard` (App-API
  representative), 23 branches: 200-object results-unwrap; 200-array /
  200-scalar / 200-null → the method's `expected dict, got {list,int,
  NoneType}` raises; 200-non-JSON → `INVALID_RESPONSE`; 3xx-with-JSON →
  `HTTP_ERROR` (R2.11); 400/404/418/422 → QueryError (status preserved);
  401 → AuthenticationError; 403-plain → QueryError; 403 sensitive-data
  exact-element list → SessionReplayAccessError; R10.7 bug-compat rows
  reachable through an App method (`42`/`1.5`/`true` → bare TypeError;
  `0`/`false`/`null` → QueryError; substring-miss list → QueryError);
  429-then-success (2 calls, one UNJITTERED 2000 ms sleep — Discrepancy
  #1 advertised path); 429×3-exhausted at maxRetries=2 → RateLimitError;
  500 → ServerError; 204 through a dict-returning method →
  `{status: "ok"}`; transport rejection → `HTTP_ERROR` (R2.10).
- `scope/pin-lifecycle-project-workspace-project` — listDashboards
  project-scoped → `set_workspace_id(789)` workspace-scoped →
  cleared → project-scoped (call-time pin reads).
- `void204/*` — 15 branches: every void method (delete/favorite/pin
  families ×3 domains, bulk delete/update ×3, report-link/text-card/
  blueprint-cohorts) returns undefined on 204 with the exact
  verb + path asserted.
- `raw/*` — 9 branches: get_dashboard results-unwrap vs
  get_bookmark_history `_raw=True` shaping (inner-with-pagination as-is;
  missing pagination → null default; inner list / scalar / null wrapped;
  dict-without-results self-wrap; top-level list wrap; scalar raw body →
  `expected dict, got int`).
- `env/*` — 10 branches: v2 double-envelope / flat-list / scalar-raise /
  inner-non-list-raise; blueprints dict-of-dicts name-merge +
  non-dict-skip / templates-list / plain-list / scalar-raise /
  templates-scalar fallthrough (outer type name in message);
  list_cohorts_app non-list raise.
- `edge/*` — 5 branches: `joinIds` pythonStr spellings (`"1,2"`,
  `"18.5,1.5"`, non-BMP `"𝒳"` type param); Python-falsy filters omitted
  (`[]` ids, `""` strings, null); bulk bodies verbatim (`[]`,
  `true`/`null`/`""`/`[]`/`"𝒳"` members); history params
  (`str(1.5)`→`"1.5"`, `page_size=0` sent as `"0"` under `is not None`,
  falsy cursor omitted, `"𝒳"` cursor); v-marker split (body INT 2 vs
  param STRING "2", POST vs PATCH).

## Per-name vector replay (trailing-slash filters per the packet trap note)

All 38 names, 78/78 PASS / 0 FAIL / 0 UNPORTED @ 70c904d:

| name | n | | name | n | | name | n |
|---|---|---|---|---|---|---|---|
| list_dashboards | 10 | | create_blueprint | 1 | | delete_bookmark | 1 |
| create_dashboard | 3 | | get_blueprint_config | 1 | | bulk_delete_bookmarks | 1 |
| get_dashboard | 2 | | update_blueprint_cohorts | 1 | | bulk_update_bookmarks | 1 |
| update_dashboard | 1 | | finalize_blueprint | 1 | | bookmark_linked_dashboard_ids | 6 |
| delete_dashboard | 2 | | create_rca_dashboard | 1 | | get_bookmark_history | 3 |
| bulk_delete_dashboards | 2 | | get_bookmark_dashboard_ids | 2 | | list_cohorts_app | 5 |
| favorite_dashboard | 2 | | get_dashboard_erf | 1 | | get_cohort | 3 |
| unfavorite_dashboard | 1 | | update_report_link | 1 | | create_cohort | 1 |
| pin_dashboard | 1 | | update_text_card | 1 | | update_cohort | 1 |
| unpin_dashboard | 1 | | list_bookmarks_v2 | 5 | | delete_cohort | 1 |
| remove_report_from_dashboard | 1 | | create_bookmark | 3 | | bulk_delete_cohorts | 1 |
| add_report_to_dashboard | 1 | | get_bookmark | 2 | | bulk_update_cohorts | 1 |
| list_blueprint_templates | 5 | | update_bookmark | 1 | | | |

Cumulative full-suite replay after C3: `npm run conformance` →
**3,251 = 2,003 PASS / 0 FAIL / 1,248 UNPORTED** (matches the packet's
C1+C2+C3 interim; the batch-status flip stays with the gate).
