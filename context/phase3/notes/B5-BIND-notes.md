# B5-BIND notes — bindings + oracle registration for the B5 surface (fable)

**Task**: b5-packets.md §6 (binding plan) — P3-2 (b′) for batch B5.
**Date**: 2026-08-16. **Status**: DONE.
**Commits**: TS `952a2cf` (main); Python — this commit
(`ts-port/phase2-contract-support`).

## Scope checklist (from the packet) — ALL DONE

- [x] `conformance-runner/src/wire-workspace.ts` — `workspaceFromSession`
      + all 44 `workspace.<member>` bindings (§6.1/§6.2)
- [x] `conformance-runner/src/replays-bindings.ts` — 5 `replays.*` wire +
      3 `replay_labels.*` + `rrweb_analyzer.analyze` builders (§6.3)
- [x] Binding honesty (§6.4) — every binding calls the real facade member
      / service method; adaptations are kwarg plumbing, the U8 `today`
      seam, and the recorder output-codec twins (below)
- [x] `CoreLibraryError.toExpectError()` errors[] extension (§6.5)
- [x] Oracle strategies for the 9 servable families (§6.6 —
      `conformance/differential/strategies.py` `PHASE3_B5_TARGETS`;
      target-table unit test extended)
- [x] UNPORTED-probe re-anchor → `workspace.me`
      (`differential/test/oracle-protocol.test.ts` ×2; §6.7 —
      `conformance-runner/test/runner.test.ts` already anchored on
      `workspace.list_dashboards`/`workspace.me`, no change needed)
- [x] `workspace.me` NOT bound (§6.8 — B6-owned; holdback stays UNPORTED)
- [x] All 506 B5 vectors PASS; **NO batch-status flip** (gate task owns it)
- [x] R10.9 oracle fuzz ≥500/family, fresh seed, both bridges — clean
- [x] VectorFetch status-branch replay re-run for the wire members
- [x] `npm run check` green (TS); `just check` green (Python)

## Conformance checkpoint (exact delta)

`npm run conformance` @ corpus pin `70c904dc598d`:
**3,251 vectors — 2,876 PASS / 0 FAIL / 375 UNPORTED**
(B4 baseline 2,370 PASS / 881 UNPORTED → **+506 PASS / −506 UNPORTED**,
exactly the packet §1 gate delta). The P3-1 † carried vector
(`auth/api_client.resolve_workspace_id/...` with setup `workspace.me`)
stays UNPORTED as designed. The batch-status table is UNTOUCHED — the
gate task lands the 44 exact-name flips + the `workspace.list_bookmarks_v2`
pending override + the three prefix flips in its own commit.

## Design decisions

1. **`workspaceFromSession` / `clientForContext`** (`wire-workspace.ts`)
   mirror `execute.py::_ReplayContext.get_workspace/get_client`:
   - facade memoized in `context.state` under `"workspace"`; client under
     the shared `CLIENT_STATE_KEY` (`clientFromSession` when
     `call.session` exists — so `api_client.*` setup entries mutate the
     SAME client the facade uses);
   - session-free vectors get the synthetic
     `targets.py::_DEFAULT_SESSION_VALUES` session; builder-kind vectors
     additionally bind an EMPTY `VectorFetch` (`createVectorFetch([])` —
     any network attempt fails the vector loudly, D5.1);
   - facade session = `workspace_session` ?? `session` ?? synthetic.
2. **Output encoding** (`encodeFacadeValue`): the recorder
   `encode_expect_value` twin — `toVectorPayload()` (the S-shard
   recorder-walk methods) preferred, then the contract-codec table with
   rich tags stripped (B3 `toBuilderExpectOutput` semantics, kept local
   per the wire-module self-containment precedent), then `toJSON()`;
   core `JsonNumber` tokens → runner tokens; `PyFloat` carriers → raw
   float tokens (non-finite spellings stay tagged); `Map` → dict.
3. **Recorder float twins** (Python-`float`-typed fields whose values
   are integral — the recorder writes `1.0`/`0.0`/`22150.0` raw tokens
   that native JS numbers cannot reproduce; each twin cites the Python
   type): `workspace.funnel` conversion rates (`live_query.py:135-147`),
   `workspace.retention` cohort rate lists (`:159-221`),
   `segmentation_sum`/`segmentation_average` `results: dict[str, float]`,
   `query_saved_flows` `overall_conversion_rate` (number → float token;
   the storybook `"NaN"` STRING passes through untouched), and the
   replays-error detail keys `signed_at`/`expired_at`
   (`time.time()` floats — `ReplaysWireError` in `replays-bindings.ts`).
   Precedent: the Phase-2 `SignedReplay.signed_at` codec twin
   (`vector-codecs.ts:733`).
4. **U8 clock seam**: `today: () => context.shims.today()` injected into
   the 12 query/build member option bags that accept it (the recorder and
   both oracles run under the frozen epoch); wire members inherit the
   client's `now` seam via `clientFromSession`; `ReplaysService` gets
   `now` from the shims (freezegun twin — `targets.py` injects none
   because the Python runner freezes globally).
5. **Replays wire bindings** mirror `targets.py::make_replays_service`
   verbatim: FRESH service per call (`execute.py:484-486`), shared
   client, `fetchImpl` = harness fetch (CDN seam), NO `queryFn`
   (`discover`/`events_for` replay the no-query_fn raise branch exactly
   like the Python replay target).
6. **`rrweb_analyzer.analyze` carrier unwind**: oracle-ts's
   `executeBound` re-tags integral-float input tokens (a fidelity
   mechanism for carrier-aware modules); the analyzer consumes plain
   `json.loads` trees, so the binding unwinds `PyFloat` carriers back to
   natives — matching the RUNNER's own decode of the rrweb-seed vectors
   (raw tokens → native numbers). Behaviorally safe: timestamps go
   through the CPython `int()` ladder; non-str console payload members
   are never stringified (S3 R10.9 record, 520 cases).
7. **`selector_label_fn` flattening**: bound as `(attr, action) → label`
   over the REAL public factory, mirroring the recorder's
   `adapters.py:65-87` flattening adapter.
8. **`stream_replay` / `walk_cdn_async` generators**: collected to item
   lists (the Python runner's `isinstance(result, Iterator)` branch,
   `execute.py:553-555`).

## Vector failures found (attributed to owning shards; fixed at the layer)

- **S3 (`packages/core/src/services/replays.ts`) — cause-in-details
  leak** (found by
  `replays/replays.fetch_files/...credentialredaction...`):
  `CDN_FETCH_ERROR` / `CDN_INVALID_RESPONSE` passed `{cause: exc}` as
  the DETAILS bag where Python raises with NO details
  (`raise ... from exc`, `replays.py:457-469`) — the recorded
  `expect.error` has no `details_contain`, so the leaked
  `cause: {name, status}` detail failed the structural error diff.
  Fixed at the owning layer: `null` details + `ErrorOptions.cause`
  threading (the `pagination.ts:328-330` / `streaming.ts:476-478`
  pattern, which were already correct). No masking — grep confirmed no
  other `{cause}`-as-details site in `packages/core/src`.

That was the ONLY vector failure across all 506; everything else passed
on the first full run.

## RUN records (R10.9)

### Oracle fuzz — final domain, fresh seed 789657390

```bash
uv run python -m conformance.differential.fuzz_harness \
  --right "node /Users/jaredmcfarland/Developer/mixpanel-headless-ts/scripts/run-oracle.mjs" \
  --targets workspace_build_params_family,workspace_build_funnel_params_family,\
workspace_build_flow_params_family,workspace_build_retention_params_family,\
workspace_build_user_params_family,replay_url_normalizer_family,\
replay_default_label_family,replay_selector_label_family,rrweb_analyze_family \
  --examples 500 --seed 789657390 --report json
```

status **ok** — **4,555 examples / 0 skips / 0 divergences**:

```
workspace_build_params_family           509   workspace_build_funnel_params_family  506
workspace_build_flow_params_family      506   workspace_build_retention_params_family 505
workspace_build_user_params_family      513   replay_url_normalizer_family          506
replay_default_label_family             503   replay_selector_label_family          503
rrweb_analyze_family                    504
```

An identical clean 4,555/0 run at seed **822819180** preceded the final
domain tightening (raw JSON: TS repo `throwaway/b5-bind/fuzz-seed822819180.json`;
the shrunken-repro dir `conformance/differential/repros/` is unchanged —
the two bring-up repros below were fixed and their files removed).

### Bring-up divergences (found → resolved before the clean runs)

1. `rrweb_analyzer.analyze` error payload lacked `code` (raw
   `ParamValidationError` reached the oracle unwrapped): fixed — the four
   replay builder bindings wrap coded errors as `WireCoreError`
   (`runBuilder`). Divergence class: rig encoding, not library.
2. `workspace.build_params` with `GroupBy(bucket_max=18.0)` rendered
   `customBucket.max` as `18` vs Python `18.0`: **F1-class narrowing at
   a NEW site** — the typed `GroupBy` constructor unwraps the
   `$type: float` carrier for its V18 numeric guards
   (`vector-codecs.ts:600-635` parks float-ness in a codec-side WeakMap
   the builders cannot see). Handled per the S2 F1 option (b): INTEGRAL
   floats excluded from the bucket-field fuzz domain (documented at the
   strategy site; fractional floats stay; zero corpus vectors carry
   float buckets; a JS caller cannot express the distinction).
   **Arbiter-visible**: flagged for the review pair — if the pair wants
   option (a) instead (carrier-aware `buildGroupSection`), it is a
   library change on the S2 surface.

### Strategy-domain notes (Discrepancy #8 + F1, documented in
`strategies.py` at each site)

- Domains are ports of the arbitrated S2/S3 throwaway generators
  (`throwaway/b5-s2/py-side.py`, `throwaway/b5-s3/py-side.py`).
- F1 exclusions (S2 option (b)): integral floats OUT of the filter-value
  domains of `build_flow_params` / `build_user_params` (string-render
  sites), OUT of `GroupBy` bucket fields (above), and OUT of the
  `UserAction.metadata` VALUE slot (`selector_label_fn` renders the
  candidate via CPython `str()` spelling).
- Annotation constraints enforced by mypy --strict at authoring time:
  booleans out of `Filter.equals` (`str | list[str]`); `UserAction.action`
  literal union respected; empty cohort names (constructor CM/CF guards)
  out of the bridgeable domain; the S2 `where_scalar` anchors dropped
  (out-of-annotation, Discrepancy #8).

### Mechanical both-bridge probe (§6.6 / gate-step-3 shape)

One `oracle.call` per builder-kind name — 9/9 `ok` (non-"unknown api")
on BOTH bridges (oracle-py 0.2.1 / oracle-ts 0.0.0, both
`source_commit 70c904dc…`, protocol 1.1): the five
`workspace.build_*params`, the three `replay_labels.*`,
`rrweb_analyzer.analyze`. Wire names exempt (no oracle surface).

### VectorFetch status-branch replay (wire members)

The three shard wire-edge matrices re-run against the post-BIND tree
(post replays.ts fix): S1 **47/0**, S2 **119/0**, S3 **70/0** failures
(`npx vite-node throwaway/b5-s{1,2,3}/wire-edges.ts`).

## Outbound notes for the review pair / gate

- Decision 3's float twins and the F1 bucket exclusion are the two
  arbiter-attention items.
- Gate reminders (unchanged from the packet): 44 exact-name flips + the
  `workspace.list_bookmarks_v2` pending override in ONE commit; expect
  **2,876 / 0 / 375** post-flip (identical to the current pre-flip counts
  since every bound name already replays); referee (a) FEED_SLOTS gains
  `workspace.build_params` (§7.4); remove `throwaway/b5-*` after arbiter
  sign-off (incl. `throwaway/b5-bind/`).
- `conformance/tests/test_fuzz_harness.py` target-table test extended
  with `_PHASE3_B5_NAMES` (same commit).
