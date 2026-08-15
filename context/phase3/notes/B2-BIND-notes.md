# B2-BIND Task Notes — bindings + oracle registration (P3-2 b′, fable)

**Status**: DONE — TS commit `2015565` (mixpanel-headless-ts, branch
`main`); Python commit on `ts-port/phase2-contract-support` (strategies
families + strategy-table lock + these notes)
**Model**: fable (rig code — P3-3 rig row)
**Date**: 2026-08-15

## Scope (per b2-packets.md §Binding plan)

- Register 11 api names (`validation.*` ×9 + `user_validators.*` ×2) in the shared
  bindings registration module; oracle-ts gains them through the same point.
- Replay all 690 B2 vectors to PASS (no batch-status flip — gate's job).
- Extend `conformance/differential/strategies.py` with the 10 deferred families
  (M1: group_by/query/funnel/retention/flow; M2: bookmark/flow_bookmark/sorting;
  M3: user_args/user_params) and run the R10.9 oracle fuzz ≥500/family, fresh seed.
- Mechanical oracle probe: one `oracle.call` per name on BOTH bridges (GF4).
- Binding honesty (P3-5 rule 3): call the real ported entry points only.

## Progress log

- [x] Read playbook + b2-packets + M1/M2/M3/HK notes
- [x] Read rig: bindings.ts, runner.ts, codecs.ts (PyFloat), oracle server
      (executeBound serves ANY bound api → one registration point confirmed;
      oracle-py __main__ freezes clock via freezegun RecordClock, so
      date.today() == 2026-01-15 on the Python side)
- [x] Read Python: strategies.py (FuzzTarget table), registry
      `_validator_entries` (12 entries; `bookmark_schema.validate_with_pydantic`
      excluded from B2 per packet), fuzz_harness.py (--seed / --targets)
- [x] Design check: TS validators are carrier-aware internally
      (isPythonInt/isFloatCarrier/_isFinite; schema-sorting optionalInt
      classifies by numeric value) → binding does ONLY the M1/M3 field-level
      finite-carrier unwraps + a uniform deep non-finite→native unwrap
      (M1 rule; behavior-neutral for the M2 surface — verified against
      validation-bookmark.ts:1082-1092 and schema-sorting.ts:720-745)
- [x] Write bindings (`registerValidatorBindings` in
      `conformance-runner/src/bindings.ts` — the one registration point,
      wired into `createRunnerDeps`; oracle-ts serves the names via
      `executeBound` automatically)
- [x] 690 vectors green FIRST RUN (`npm run conformance -- --filter
      validation/` → 690/690; full corpus 3,251 → **1,229 PASS / 0 FAIL /
      2,022 UNPORTED** — exactly the packet §13 expectation, +690 PASS)
- [x] strategies.py: 11 families added (`PHASE3_B2_TARGETS`; edge sets
      ported from the three module throwaway harnesses into Python-object
      form; self-parity smoke 25/family all clean)
- [x] Oracle probe both bridges: 11/11 `oracle.call` non-"unknown api",
      outputs EQUAL py↔ts (record below)
- [x] Fuzz run 2 (post-fix, seed 83155107): status ok, 5,384 examples,
      0 divergences — but `group_by_args_family` exhausted its finite
      `sampled_from` domain at 37 examples (< the 500 budget). Widened
      the strategy with generated mixed lists over the scalar pool.
- [x] FINAL R10.9 RUN RECORD (seed **83155107**, fresh — B0 gate used
      52794688; `--examples 500`, oracle-py ↔ oracle-ts, corpus pin
      b5c1369, TS repo post-fix tree): status **ok**, **5,863 examples,
      0 skips, 0 divergences**. Per family: time_args 513 ·
      group_by_args 516 · query_args 527 · funnel_args 526 ·
      retention_args 525 · flow_args 523 · bookmark 551 ·
      flow_bookmark 515 · sorting 560 · user_args 575 · user_params 532
      (every family ≥ 513 ≥ the P2-9 500 budget). Re-run command:
      `uv run python -m conformance.differential.fuzz_harness --right
      "node <ts-repo>/scripts/run-oracle.mjs" --targets <the 11 names>
      --examples 500 --seed 83155107 --report json`. The run-1 repro
      `2026-08-15-validation-validate_bookmark.json` was deleted after
      the clean re-run (fix landed at the owning module, see findings).
- [x] npm run check green (typecheck ×5 + eslint + prettier + 3,600
      tests with 2,022 corpus-UNPORTED skips + browser smoke)
- [x] just check green (second run — the first ran against the
      pre-update strategy-table lock in
      `conformance/tests/test_fuzz_harness.py`, which was then extended
      with `_PHASE3_B2_NAMES`)
- [x] Commits: TS `2015565` (bindings + codec fix + module R10.7 fix +
      locks); Python (strategies.py + test_fuzz_harness.py + notes).
      LOCAL ONLY, not pushed.

## Fuzz-domain omissions (strategies.py section header carries the full text)

- Non-finite floats are unshippable through `encode_input_kwargs`
  (`_reject_bad_float`, D6 rule 5) — V24/B20B/`finite_number` non-finite
  arms stay corpus-authored/Layer-3-locked (the module throwaway
  harnesses covered them by hand-building payloads).
- Constructor-guarded instances cannot be generated (Python raises at
  strategy time) — the post-Phase-2-unreachable codes are pinned by
  nearest reachable arms, per the M1-notes inventory.
- `workers=None` excluded (B2-M3 known boundary — CPython TypeError
  outside both signatures).

## Notes for the B2 gate task

- `bookmark_schema.validate_with_pydantic` intentionally NOT bound at B2
  (packet §Binding-plan) — the B3 binder owns it; the gate's oracle
  probe covers the 11 B2 names only.
- Gate flip expectation unchanged: `validation.` + `user_validators.` →
  done; PASS 1,229 → gate makes no further PASS change (all 690 already
  replay green while pending); UNPORTED stays 2,022 at flip (delta was
  taken at bind time — the flip is the straggler ratchet only).
- The B0-gate skip ledger partially un-skips: `validators_by_code` (510
  skips at the B0 gate) now answers on both bridges; the remaining
  Phase-1 pending-skip families are the five B3 ones
  (`build_filter_entry`, `build_segfilter_entry`, `filter_to_selector`,
  `filters_to_selector`, `normalize_on_expression`).

## Binding design (arbiter checklist)

- Honesty (P3-5 rule 3): every binding calls the real ported entry point
  from `packages/core/src/query` (validateTimeArgs/…/validateUserParams).
  Adaptations, in full: (1) kwarg plumbing (options bag pass-through,
  absent keys stay absent, R3.5); (2) `validation_errors` output encoding
  `[{path, code, severity}]` (the recorder codec twin — runner's
  diffReturnedValue does not strip advisory keys); (3) guardCompat error
  wrap (MixpanelHeadlessError → CoreLibraryError); (4) `today` seam from
  `context.shims.today()` on validate_user_args (frozen-clock parity —
  oracle-py freezes via freezegun in `oracle_py/__main__`); (5) the
  measured PyFloat carrier policy:
  - deep non-finite→native unwrap over all kwargs (M1 rule; plain
    dicts/lists only, class instances untouched; behavior-neutral for the
    carrier-aware M2 surface — NOT a `params.sorting` unwrap rule);
  - finite-carrier→number on exactly the M1/M3-measured numeric fields:
    `last` (time/funnel/retention/query/flow via bag), query `rolling`,
    flow `forward/reverse/cardinality/conversion_window`, user
    `limit/percentile/workers` + `segment_by[i]`;
  - keep-carrier fields untouched: funnel `conversion_window`, retention
    `bucket_sizes[i]`, `data_group_id`, user `cohort`/`as_of`, all
    bookmark params (module is carrier-aware via isPythonInt/
    isFloatCarrier/_isFinite).
- `validation.validate_sorting_block` bound despite zero vectors (gate
  probe + prefix-flip straggler rule). `bookmark_schema.
  validate_with_pydantic` NOT bound (B3's — record for the B2 gate notes
  so the B3 binder picks it up).
- Forward note for B5 (unchanged from packet): `CoreLibraryError.
  toExpectError()` still emits only `{class, code}`; the B5 binding task
  must extend it with `errors[]` for `BookmarkValidationError` replay.

## Fuzz findings (run 1, seed 83155107, py↔ts, 500/family)

Run 1: 5,323 examples, 0 skips, **1 divergence + 1 harness-crash class**
— both REAL, both attributed and fixed at the owning layer (no
binding-layer masking):

1. **GroupBy carrier crash (rig codec gap — fable-owned, fixed in
   `packages/core/src/types/vector-codecs.ts`)**. `GroupBy(bucket_min=
   0.0, bucket_max=100.0)` encodes with `$type: float` children (P2-5a);
   the GroupBy contract codec passed PyFloat CARRIERS into the
   constructor, where JS `>=` on two carrier objects string-compares
   `"[object Object]" >= "[object Object]"` → true → the V18 ctor guard
   raised where CPython's `0.0 >= 100.0` is False → decode crash
   (-32602) on 4 families. Fix: the GroupBy codec `construct` unwraps
   the three bucket fields to native numbers (SignedReplay `signed_at`
   precedent; B2-M1 carrier-table row "GroupBy.bucket_* → unwrap"
   implemented at the decode layer where it belongs). Red-first lock:
   `conformance-runner/test/codecs.test.ts` "GroupBy contract codec
   float-carrier buckets". The binding's redundant group_by unwrap was
   then REMOVED (dead adaptation = honesty smell).
2. **`validate_bookmark` unhashable-membership divergence (module bug —
   B2-M2 finding 2 adjudicated by R10.7)**. Repro: measurement
   `math: []` → Python raises `TypeError: cannot use 'list' as a set
   element (unhashable type: 'list')` (CPython hashes in
   `x in frozenset`); TS returned `B9_INVALID_MATH`. M2 shipped the
   total-function spelling and flagged for adjudication; the fuzz made
   it a blocking divergence, and R10.7 (bug-compatibility, standing
   constraint) rules Python's raise is the contract. Fix in the MODULE
   (`validation-bookmark.ts`): shared `requireHashable(...)` guard
   (validation-shared.ts) at all 16 probe-verified membership sites
   (validation.py :1832/:1845/:2483/:2549/:2618/:2647/:2662/:2674/
   :2712/:2754/:2767/:2846/:2860/:2873/:2981/:2995 — the M2 TODO said
   12; the probe found 16, incl. B13 and the measurement-property
   B16/B17 pair). CPython probe matrix (2026-08-15, uv run): 16/16
   raise on list+dict; controls True/1.5/None-branch stay enum errors.
   Red-first lock: `packages/core/test/query/validation-unhashable.test.ts`
   (20 tests). Module-header TODO(port) replaced with the resolution
   note. The stale repro file is deleted after the clean re-run.

## Oracle probe record (2026-08-15)

py: `{language: python, library_version: 0.2.1, protocol_version: 1.1,
source_commit: b5c1369…}`; ts: `{language: typescript, library_version:
0.0.0, protocol_version: 1.1, source_commit: b5c1369…}`. All 11 apis:
`py_ok=True ts_ok=True equal=True` (probe script inline in task
transcript; one representative valid input per api).

## Handed-in constraints from module tasks

- M1 carrier table (V1a): unwrap→number: `last` (all), query `rolling`,
  flow `forward/reverse/cardinality/conversion_window`, `GroupBy.bucket_*`;
  keep carrier: funnel `conversion_window` (F3 type check), retention
  `bucket_sizes[i]` (R5), `data_group_id` (DG1).
- M2: NO `params.sorting` unwrap rule (schema-sorting is carrier-aware internally).
- M3 carrier table (V2): unwrap→number: `limit`, `percentile`, `workers`,
  `segment_by[i]`; keep carrier: `cohort`, `as_of`. `today` seam from
  `context.shims`. `workers=None` excluded from fuzz domain (Python TypeError).
- Non-finite spellings ALWAYS unwrap to native non-finite (vector-codecs precedent).
- `bookmark_schema.validate_with_pydantic` NOT bound at B2 (B3's; record for gate).
- Encoder: `[{path, code, severity}]` exactly, emission order preserved.
