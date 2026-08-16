# B4-C4 notes — flags + experiments + annotations + webhooks + alerts

**Status**: DONE (shard-level; batch flip stays with the gate).
Packet: `context/phase3/design/b4-packets.md` §Packet C4.
Scope: 46 api-index names, 109 vectors, `api_client.py:4938-6479`.
TS homes: `packages/core/src/services/entities/{flags,experiments,annotations,webhooks,alerts}.ts`.
Bindings: `conformance-runner/src/wire-lifecycle.ts` (`registerLifecycleWireBindings`, 46 names),
registered in `bindings.ts` in the same shard commit (P3-2 b′ fable-batch rule).

## Progress log

- [x] Python source read verbatim (`api_client.py:4938-6479` — flags :4938-5271,
  experiments :5277-5668, annotations :5674-5914, webhooks :5920-6072, alerts :6078-6474)
- [x] Layer-3 translation FIRST (R10.2/P3-2a): 5 files, ALL classes, 109 tests
  (mirrors the 5 Python files test-for-test; red before implementation)
- [x] Implementation green (tsc --strict + 109/109 translated tests)
- [x] Bindings (46 names) + oracle surface (wire = exempt, P3-2 c) in the SAME commit
- [x] Vector replay: 109/109 PASS; cumulative 2,112 PASS / 0 FAIL (packet interim number hit exactly)
- [x] R10.9 harness `throwaway/b4-c4/` — 59/59 branches

## Layer-3 translation map (R10.2 — no weakened assertions)

| Python source (ALL classes) | TS translation |
|---|---|
| `tests/unit/test_api_client_flags.py` (23 tests) | `packages/core/test/client/client-entities-flags.test.ts` |
| `tests/unit/test_api_client_experiments.py` (25) | `client-entities-experiments.test.ts` |
| `tests/unit/test_api_client_annotations.py` (20) | `client-entities-annotations.test.ts` |
| `tests/unit/test_api_client_webhooks.py` (13) | `client-entities-webhooks.test.ts` |
| `tests/unit/test_api_client_alerts.py` (28) | `client-entities-alerts.test.ts` |

Total 109 translated tests = 109 measured vectors (1:1, as measured in the packet).
`pytest.raises(APIError)` rows assert `rejects.toBeInstanceOf(APIError)` (same class
altitude as the Python assertion — QueryError ⊂ APIError). The flags fixture's
`create_mock_client(..., workspace_id=100)` translates to
`createMockClient(...)` + `client.setWorkspaceId(100)`.

## Design decisions / findings

1. **`require_scoped_path` seam (flags only)**: feature flags are the one C4 domain on
   `require_scoped_path` (auto-discovering workspace scope). The C1 closure that
   backed the public `client.requireScopedPath` member was extracted to a named
   closure in `client.ts` (identical body, `api_client.py:1666-1694`) and passed to
   `createFlagMethods(core, { requireScopedPath })` — the C2
   `createQueryHostMethods(core, { resolveWorkspaceId })` extras-pattern precedent.
   No B0/C1 re-implementation (R10.8); the public member now references the same
   closure.
2. **`get_flag_limits` scoping**: ALWAYS project-scoped
   (`/projects/{pid}/feature-flags/limits/`, `api_client.py:5263-5264`) even with a
   workspace pinned — locked by Layer-3 `test_always_uses_project_scoped_path` +
   harness row `flags/limits-project-scoped-despite-pin`.
3. **Experiments trailing-slash matrix**: collections keep the slash
   (`experiments/`, `experiments/erf/`); item + lifecycle endpoints do NOT
   (`experiments/{id}`, `/launch`, `/force_conclude`, `/decide`, `/archive`,
   `/duplicate`). Verbatim from `:5372-5661`; harness row `exp/trailing-slash-matrix`.
4. **Body-presence semantics** (vector-visible):
   - `conclude_experiment`: `json_body=body or {}` — ALWAYS sends a body; falsy
     (absent/None/`{}`) → `{}` (ported as `truthyRecord(body) ? body : {}`).
   - `duplicate_experiment`: `json_body=body if body else None` — Python truthiness:
     absent/None AND empty `{}` send NO body (new shared helper `truthyRecord` in
     `entities/shared.ts`; `{}` is falsy in Python, non-null in JS — the one spot
     where `body ?? {}`-style porting would diverge).
   - `launch_experiment`/`archive_*`: no body at all.
5. **Param gating split**: alerts use `is not None` gates (`bookmark_id=0` → `"0"`,
   `skip_user_filter=False` → `"false"` — `str(x).lower()` ported as
   `pythonStr(x).toLowerCase()`, R11.7); flags/experiments `include_archived` and
   annotations `from_date`/`to_date`/`tags` use Python TRUTHINESS (falsy → param
   omitted). Harness rows `alerts/is-not-none-param-gate`,
   `flags/include-archived-truthiness`, `annotations/truthiness-gates-and-camelCase`.
6. **`get_alert_history` (`_raw=True`) shape ladder** (`:6341-6371`) ported branch-
   for-branch: outer dict missing `results` → raise "dict missing 'results' key";
   inner dict WITH `results` → `pagination=null` injected when missing, returned
   (in-place mutation preserved); inner list → `{results, pagination: null}`;
   outer list → same wrap; every fall-through → raise
   `got {type(result).__name__} without results list` (note: an inner scalar reports
   the OUTER type `dict` — bug-compat, ported verbatim). isinstance-dict on wire
   values = B0 `isPlainRecord` (watchlist #13: wire domain carries no PyFloat
   carriers/class instances — the C3 `shared.ts` header note applies).
7. **annotations `tags`/ids joins**: `",".join(str(t) for t in tags)` via the C3
   `joinIds` (pythonStr) helper; camelCase wire params `fromDate`/`toDate` from
   snake_case kwargs.
8. **`get_flag_history` params passthrough**: `params=params` verbatim (None stays
   None — no empty-dict elision on this one method, unlike the `params if params
   else None` list methods).
9. **No result pre-shaping** (Caution #11): every method returns the
   `appRequest` product verbatim after the source's isinstance guard
   (`expectRecordResult`/`expectListResult` — the exact `UNKNOWN_ERROR`
   bare-constructor twins, message spelling `Unexpected response from <name>:
   expected dict|list, got <pytype>`).
10. **Binding honesty (P3-5 §3)**: all 46 bindings = memoized `clientFromSession` +
    one client-method call + kwarg passthrough (`kwargBag` absent-stays-absent;
    `optionalBody` for the two optional-positional `body=None` params); void methods
    return `null`. No path/param assembly in any binding.

## Rig changes

- `conformance-runner/src/wire-lifecycle.ts` (NEW): 46 C4 registrations.
- `conformance-runner/src/bindings.ts`: +import, +`registerLifecycleWireBindings(implementations)`
  (append-only at the marked B4 block).
- No changes to runner/codecs/canonicalizer/batch-status (no flip — that is the gate's).

## Vector replay (per-name, trailing-slash filters per the packet trap note)

Full-corpus replay: **3,251 = 2,112 PASS / 0 FAIL / 1,139 UNPORTED** — delta +109 over
the C3 baseline (2,003), matching the packet's interim expectation for C1+C2+C3+C4
EXACTLY. Per-name (all `total/pass/fail`):

flags: list_feature_flags 5/5/0 · create_feature_flag 2/2/0 · get_feature_flag 2/2/0 ·
update_feature_flag 2/2/0 · delete_feature_flag 2/2/0 · archive_feature_flag 1/1/0 ·
restore_feature_flag 1/1/0 · duplicate_feature_flag 1/1/0 · set_flag_test_users 1/1/0 ·
get_flag_history 3/3/0 · get_flag_limits 3/3/0 (Σ 23)

experiments: list_experiments 4/4/0 · create_experiment 2/2/0 · get_experiment 2/2/0 ·
update_experiment 2/2/0 · delete_experiment 2/2/0 · launch_experiment 2/2/0 ·
conclude_experiment 4/4/0 · decide_experiment 2/2/0 · archive_experiment 1/1/0 ·
restore_experiment 1/1/0 · duplicate_experiment 1/1/0 · list_erf_experiments 2/2/0 (Σ 25)

annotations: list_annotations 7/7/0 · create_annotation 2/2/0 · get_annotation 2/2/0 ·
update_annotation 2/2/0 · delete_annotation 2/2/0 · list_annotation_tags 3/3/0 ·
create_annotation_tag 2/2/0 (Σ 20)

webhooks: list_webhooks 4/4/0 · create_webhook 2/2/0 · update_webhook 2/2/0 ·
delete_webhook 2/2/0 · test_webhook 3/3/0 (Σ 13)

alerts: list_alerts 6/6/0 · create_alert 2/2/0 · get_alert 2/2/0 · update_alert 2/2/0 ·
delete_alert 2/2/0 · bulk_delete_alerts 2/2/0 · get_alert_count 3/3/0 ·
get_alert_history 3/3/0 · test_alert 2/2/0 · get_alert_screenshot_url 2/2/0 ·
validate_alerts_for_bookmark 2/2/0 (Σ 28)

Σ = 109/109 PASS across 46 names.

## RUN record (R10.9) — `throwaway/b4-c4/` (2026-08-16)

`bash throwaway/b4-c4/run.sh` → **59/59 branches PASS, 0 FAIL** (deterministic
hand-built matrix; wire methods have no oracle bridge, P3-2 c — the harness IS the
differential, expectations transcribed from `api_client.py:4938-6479` +
`_handle_response :503-670` / `app_request :1160-1389`).

Branch table:
- §Wire status matrix through `create_alert` (28 rows): 200-object results-unwrap;
  200-array/int/str/bool/NoneType/float expected-dict guards; 200-non-JSON
  INVALID_RESPONSE; 3xx-with-JSON-body HTTP_ERROR (R2.11); 400 QueryError;
  401 AuthenticationError; 403-plain QueryError; 403 `["SESSION_RECORDING_SENSITIVE_DATA"]`
  exact-element → SessionReplayAccessError; R10.7 bug-compat rows (42/1.5/true →
  bare TypeError analog; 0/false/null → QueryError; substring-miss list →
  QueryError); 404; 418 other-4xx; 422-app; 429-retry-then-success (Retry-After 2 →
  ONE unjittered 2000 ms sleep, Discrepancy #1); 429-exhausted (maxRetries=2 → 3
  calls, RateLimitError with `project_id: "12345"`, FF4); 500 ServerError; 204-app →
  `{status: "ok"}` passthrough; transport rejection → HTTP_ERROR (R2.10).
- Void/204 family (3 rows): flags DELETE/archive-POST/test-users-PUT verbs+paths under
  the workspace-100 pin; experiments/annotations/webhooks/alerts delete family all
  resolve `undefined` with exact verbs+paths incl. `bulk-delete` `{alert_ids}` body.
- Experiments trailing-slash matrix (1 row, 6 endpoints).
- `get_alert_history` (9 rows): raw-envelope ladder (inner-dict-with-pagination
  verbatim; missing-pagination null-injection; inner-list wrap; outer-list wrap;
  outer-dict-missing-results raise; inner-dict-without-results raise (reports
  `dict`); inner-scalar raise (reports `dict` — bug-compat); outer-scalar raise
  (`int`)) + the page_size/next_cursor/previous_cursor param grid.
- Flags scoping (2 rows): require-scoped pinned path; limits project-scoped despite pin.
- Owned guard branches (8 rows): exact Python message spellings for one list-guard +
  one dict-guard per domain.
- Body-presence semantics (1 row): conclude always-`{}` vs duplicate no-body-for-`{}`
  vs launch/archive empty.
- Param gating (4 rows): alerts `is not None` (0/"false" sent) vs flags/annotations
  truthiness (falsy omitted); camelCase fromDate/toDate; `1,2` tag join;
  count `type` + screenshot `gcs_key`.
- Edge values (2 rows): `{}` body, `[]` ids, `"𝒳"` names, 18.5/1.5 floats, `true`,
  `null`, `""` through JSON bodies verbatim (18.0-as-distinct-double unreachable in
  JS — C3 precedent note applies); `get_flag_history` params passthrough + non-BMP
  flag id in the path.

## Done-criteria check (packet C4)

- tsc --strict clean; `npm run check` green (exit 0; 122 files / 5,555 passed /
  1,139 corpus-skipped; browser smoke OK).
- 109 translated Layer-3 tests green.
- All 109 vectors PASS (cumulative 2,112/0 — interim number reproduced exactly).
- R10.9 RUN record above; harness in the shard commit.
- No batch-status flip (gate-owned). No TODO(port) left in C4 files.
