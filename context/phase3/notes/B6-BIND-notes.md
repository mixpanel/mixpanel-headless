# B6-BIND notes — (b′) bindings for the 154 registry-covered B6 workspace members

Status: **DONE**. Packet: `context/phase3/design/b6-packets.md` §11.
Tier: fable (rig code). Spec: phase3-playbook.md v1.1 P3-2 (b′), P3-5 rule 3.

## §1 Result (measured 2026-08-16, corpus pin 70c904dc)

Full replay AFTER binding, NO batch-status flip (bound names replay
while pending — P3-5 §4 B4 note):

| | before (B5 gate) | after B6-BIND | delta |
|---|---|---|---|
| PASS | 2,876 | **3,230** | **+354** |
| FAIL | 0 | **0** | 0 |
| UNPORTED | 375 | **21** | −354 |

Delta attribution: **+353** = the B6 member vectors (138 member names
carry vectors; per-shard: W1 15, W2 38, W3 89, W4 40, W5 43, W6 33,
W7 44, W8 51 — sums 353, §1 table), **+1** = the P3-1 † dagger
`auth/api_client.resolve_workspace_id/test_workspace_resolution-testfacaderesolverwiring-test_resolves_from_me_cache_without_public_call`
(verified individually with `--filter`: 1/1 PASS — the `workspace.me`
setup now executes through the REAL facade over the SHARED
`clientFromSession` client; the resolver seam is installed at
`Workspace` construction, `workspace.ts:1145`, and the measured call
resolves `2` from the me cache with exactly the ONE recorded `/me`
interaction). The 21 remaining UNPORTED = 14 `region_probe.probe_region`
+ 7 `oauth_flow.refresh_tokens` (verified by filter: region_probe →
14/14 unported).

`npm run check` green (typecheck ×5, eslint, prettier, vitest 195
files / 9,048 passed, browser smoke).

## §2 What landed (TS repo, one commit)

1. `conformance-runner/src/wire-workspace.ts` — the 11 B6-W1 names
   fold in beside `workspaceFromSession` (§11.3): `use`/`close`
   (wire_state — executed through the REAL members, `null` returned per
   the `clear_discovery_cache` precedent), `list_workspaces`,
   `resolve_workspace_id`, `me`, `projects`, `workspaces`, and the four
   business-context members. `runFacade` + `optionsBag` exported for
   the sibling module; module/registration docs updated (the stale
   "workspace.me deliberately NOT bound" B5 note replaced).
2. `conformance-runner/src/wire-workspace-entities.ts` (NEW) — the 143
   W2–W8 registrations over a `bindFacade` helper (memoized facade +
   `runFacade` expect encoding). Honesty (§11.4): every handler calls
   the REAL `Workspace` member; adaptations are positional pulls
   (`requireWireKwarg` — kwargs arrive as reconstructed Phase-2 params
   instances via the contract codecs) + `optionsBag` kwonly plumbing
   (Python kwonly names ARE the TS option keys) + the ONE input twin
   below. `get_lookup_upload_url` honors its positional-with-default
   (`content_type` omitted → zero-arg call).
3. `conformance-runner/src/bindings.ts` — imports + calls
   `registerWorkspaceEntityBindings`; B5-era comment updated.
4. Binding-coverage assertion: 55 distinct `workspace.*` names in
   wire-workspace.ts (44 B5 + 11 W1) + 143 in the entities module =
   exactly the 44 B5 + 154 B6 registry-covered names; zero duplicates;
   mechanical diff against the api-map B6 set → zero missing. The 4
   read-only properties (`account`/`project`/`workspace`/`session`)
   have no api names (registry enumerates functions only) — no binding,
   per §11.1. The 16 zero-vector method names ARE bound (straggler
   ratchet / future authored vectors, B5 §6.1 precedent).

## §3 The two vector failures surfaced at (b′) — attributed to W4, fixed at fable

**Failures (attempt-1, owning module = W4 per §11.6):**
`entities/workspace.create_feature_flag/...test_create_feature_flag`
and `...test_create_feature_flag_with_options` — FAIL_REQUEST: sent
json_body carried `"split":{"spelling":"1.0"}` where the recording
asserts `"split":1.0`. These are the ONLY two vectors in the whole
3,251-vector corpus whose recorded request json_body contains a float
token (measured: corpus-wide scan of
`expect.interactions[].request.json_body` for `[0-9]\.[0-9]`), i.e. the
first vector-observable REQUEST-side instance of the Discrepancy #12
class. The W4 shard-notes claim "every
`expect.interactions[].request.body` is null — measured"
(`B6-W4-notes.md` §4 obs. 1) checked the wrong field name (`body` vs
`json_body`) — flagged for the review pair.

**Mechanism**: the recorder tags INTEGRAL floats inside rich payloads
(`codecs.py:185-207` `in_rich_payload`), the runner decodes the tag to
a `PyFloat` carrier, the carrier rode the `ruleset: dict[str, Any]`
passthrough into the request body, and the model-dump walk cloned it
into `{spelling: "1.0"}`. Python's replay passes a real `float` whose
`json.dumps` spelling is `1.0`; the request diff compares LOSSLESS
tokens (D6 rule 3, `request-diff.ts:19-20`), so a native JS `1` also
fails (`canonicalize`: fraction token `1.0` ≠ native `1`).

**Fix, two parts (both in the BIND commit; comparison logic UNTOUCHED —
no #9/#10-style relaxation, Caution 17 respected):**

1. **Rig input twin** (`wire-workspace-entities.ts` `WireRawFloat` +
   `twinPyFloatsInPlace`, applied to decoded kwargs in `bindFacade`):
   finite `PyFloat` carriers inside entity-params payloads become
   wrappers whose `toJSON()` returns `JSON.rawJSON(spelling)` (TC39
   raw-JSON, Node ≥ 21; ambient declaration local to the rig — the
   pinned ES2022 lib lacks it). The wrapper travels OPAQUELY through
   the REAL facade → model dump → transport path and re-emits the
   recorded token at the ONE legal place, `JSON.stringify` inside the
   core transport (`transport.ts:244`). This is the request-side
   counterpart of the B5 output float twins; non-finite spellings stay
   untouched (not valid JSON tokens; a leak fails loudly).
2. **Library fidelity fix** (`packages/core/src/types/entities/model-base.ts`
   `dumpValue`): the dump walk previously cloned ANY non-array object
   (its `isPlainObject` has no prototype check), stripping class
   behavior from arbitrary values inside `dict[str, Any]` fields (a
   `Uint8Array` would decompose into index keys). Pydantic v2
   `model_dump` keeps such objects by IDENTITY — measured against live
   pydantic 2026-08-16: `out['d']['k'] is c` → `True` for a
   custom-class dict member, with and without `exclude_none`. `dumpValue`
   now clones only PLAIN records (`Object.prototype`/null proto —
   new `isPlainRecordValue`) and passes other instances through by
   reference. `serializeValue` (`toJSON`/`toVectorPayload`) and the
   validation-side `isPlainObject` uses are UNCHANGED. All 9,048 tests
   + 3,230 vectors green after the change.

**Standing observation for the W3/W4 reviews + the gate** (no fix here,
recorded per R10.10): facade results retain core `JsonNumber` tokens
inside `dict[str, Any]` fields (that is how the dict-returning members
byte-match), so a REAL TS round-trip (read entity → feed a dict back
into a create/update params model) would put `JsonNumber` instances
into a request body, where the transport's plain `JSON.stringify`
renders `{"raw":"1.0"}` — the library has no lossless stringifier.
No corpus vector and no known consumer flow does this today; candidate
R10.4/B7+ follow-up: teach the transport (or `dumpValue`) to render
`JsonNumber`/raw-token carriers natively.

## §4 UNPORTED-exemplar re-anchors (forced by BIND, ahead of §12.5)

Binding `workspace.me` / `workspace.list_dashboards` made three
exemplar tests' anchor names LIVE (the bound-name gate replays bound
names even while pending):

- `conformance-runner/test/runner.test.ts` "returns UNPORTED for a
  mapped name with no bound implementation" → re-anchored
  `workspace.list_dashboards` → `region_probe.probe_region`.
- `differential/test/oracle-protocol.test.ts` both `workspace.me`
  exemplars (`:298-314`) → `region_probe.probe_region` (comments note
  the B6-BIND wave; pattern retires at the B8 gate).

STILL for the gate task (§12.5): the runner.test.ts SETUP-gating test
("gates on setup apis too", `:148+`) keeps `workspace.me` as its
pending setup exemplar — it uses a private registry (workspace.me
unbound there) and only the gate FLIP (`workspace.` → done) breaks it;
re-anchor it at the gate as specced.

## §5 Oracle registration + R10.9 (for the gate task)

- **NOTHING new registered on the oracle surface** (§11.5): all 154
  names are wire-kind (`use`/`close` wire_state, 152 wire_api); B6 adds
  ZERO builder-kind apis, so there are no new strategies in
  `conformance/differential/strategies.py`, the gate's mechanical
  oracle probe has an EMPTY new-name set (wire names exempt,
  `oracle_py/server.py:414-418`), and there is NO R10.9 fuzz family
  servable for this task (nothing to seed). The §12.3 differential
  full-suite regression over the cumulative surface remains the gate's
  duty.
- Setup-api coverage: the corpus's `api_client.use` (2 occurrences) and
  `api_client.close` (8) setup entries ride on four B4-measured vectors
  (`api_client.get_events` ×2, `api_client.list_bookmarks`,
  `api_client.retention`) — bound since B4 (`wire-client.ts:530/536`),
  all four PASS. The one `workspace.me` setup occurrence is the dagger
  (§1). No `workspace.use`/`workspace.close` setup occurrences exist.
- `workspace.stream_events`/`stream_profiles`/`api` are B4-batch
  api-map rows with zero corpus vectors and no api-index entries — out
  of §11.1 scope, left unbound (unchanged from B5; the gate flip is
  unaffected: unbound+zero-vector names produce no verdicts).

## §6 Ground-state measurements (2026-08-16)

- 138 B6 member names carry 353 vectors (sum verified against the §1
  packet table); 16 zero-vector bindable names: close, create_blueprint,
  favorite_dashboard, get_blueprint_config, get_bookmark_dashboard_ids,
  get_dashboard_erf, list_blueprint_templates, me, pin_dashboard,
  projects, unfavorite_dashboard, unpin_dashboard, update_text_card,
  upload_lookup_table, use, workspaces.
- api-index carries 139 B6 `workspace.*` names (138 with vectors + the
  setup-only `workspace.me`); the 15 other zero-vector names have no
  api-index entry (recorder emitted no vectors for them) — binding them
  is the resolvability ratchet only.
- The 14 non-B6 `workspace.*` corpus names are all B5 members, bound
  since B5-BIND.
