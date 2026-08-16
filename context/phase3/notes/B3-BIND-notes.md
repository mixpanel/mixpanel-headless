# B3-BIND notes — bindings + oracle registration (P3-2 b′, fable)

**Status**: DONE — TS commit `45a06cf` (mixpanel-headless-ts, branch
`main`); Python commits `70c904d` (rig: adapter + retarget + codecs fix
+ strategies + lock test) and `d89f2a8` (re-pin extraction) on
`ts-port/phase2-contract-support`, plus this notes commit. LOCAL ONLY.
**Model**: fable (rig code — P3-3 rig row)
**Date**: 2026-08-15
**Packet**: b3-packets.md §"Binding plan — fable (b′) task"

## Scope

- Register the 17 B3 registry names in `conformance-runner/src/bindings.ts`
  (`registerBuilderBindings`); oracle-ts gains them through the same point.
- Python-side `validate_with_pydantic` name-resolving adapter
  (`conformance/record/adapters.py`) + registry retarget → corpus re-pin
  event (P3-7 trigger 1; zero vectors carry the api, D9 drift trivially
  clean, counts must still read 3,251).
- Replay all 299 B3 vectors to PASS (no batch-status flip — gate's job).
- strategies.py: the K3-deferred families (`transform_event_family`,
  `transform_profile_family`) + the segfilter operator-row sweep
  (K3-notes §7.4 deferral); lock-test update.
- Mechanical oracle probe: one `oracle.call` per the 17 names on BOTH
  bridges, non-"unknown api".
- R10.9 oracle fuzz for the B3 families: ≥500/family; the two K4
  selector families at the DOUBLED ≥1,000 budget; fresh seed; RUN record
  below.

## Progress log

- [x] Read playbook v1.1 (fully) + b3-packets.md (fully) + K1-K4 notes +
      B2-BIND notes (precedent) + user-ratifications
- [x] Read rig: bindings.ts, runner.ts (InvocationContext, diffReturnedValue
      uses encodeExpectValue with NO rich hook → bindings must emit
      expect-position encodings), codecs.ts (PyFloat/PyDatetime/JsonNumber,
      encodeExpectValue), canonical.ts (no `$type: float` normalization in
      the canonicalizer → PyFloat must leave the binding as JsonNumber),
      shims.ts, oracle server.ts (executeBound + toExpectEncoding + fresh
      shims per call + constructor.name error encoding)
- [x] Read Python: registry.py (17 names; validate_with_pydantic at
      `_validator_entries`, model_name codec on get_root_model), adapters.py,
      codecs.py (encode_expect_value: rich tags stripped, floats raw tokens,
      datetime stays tagged), strategies.py (K1/K2/K4 families present;
      K3 families MISSING — my scope), fuzz_harness CLI, lock test
- [x] TS: registerBuilderBindings + expect-output walk (tsc --strict
      clean; prettier/eslint clean)
- [x] TS: **all 299 B3 vectors PASS on the FIRST run** (per prefix:
      bookmark_builders. 134 · segfilter. 51 · expressions. 30 ·
      transforms. 2 · user_builders. 82); full corpus
      **3,251 = 1,528 PASS / 0 FAIL / 1,723 UNPORTED** — exactly the
      packet §Cautions 16 expectation (delta +299 over the entering
      1,229; batch-status NOT flipped — gate's job)
- [x] Python: adapter + registry retarget + strategies K3 families +
      segfilter row sweep (41 rows, smoke: 41/41 run green against the
      real function) + lock test; just check green; commit `70c904d`
- [x] Corpus re-pin b5c1369 → **70c904d** (P3-7 trigger 1): Python
      re-extraction `just conformance-record --mp-record-date=2026-08-15
      --mp-record-commit=70c904dc…` (commit `d89f2a8`); D9 drift CLEAN —
      3,031 recorded vectors byte-identical, 157 `$bundle` stamp lines +
      manifest only (manifest delta: the three TestPydanticAdapter
      exclusions move unserializable_input→no_seam_hit, seam now on the
      adapter); TS `corpus.config.json` pin updated + `sync-corpus.sh`
      re-sync (171 bundles); P3-0 count re-measurement reads exactly
      **3,251**; post-re-pin conformance identical
      (1,528/0/1,723 @ 70c904dc598d)
- [x] Oracle probe 17/17 both bridges (record below)
- [x] R10.9 fuzz runs (seed 64091337 fresh; counts recorded below) —
      status ok, 9,395 examples, 0 skips, 0 divergences, no repros
- [x] npm run check green (100 test files, 4,433 passed / 1,723
      corpus-UNPORTED skips) after re-anchoring the two
      oracle-protocol UNPORTED exemplars (see §Test re-anchor); commits
      both repos (LOCAL ONLY)

## Test re-anchor (rig test, disclosed)

`differential/test/oracle-protocol.test.ts` used
`user_builders.filter_to_selector` / `segfilter.build_segfilter_entry`
as its "mapped-but-unported" UNPORTED-scope exemplars; both went live at
this bind, so the two tests re-anchored to `workspace.build_params`
(B5-owned, still unported, rich Filter input) with in-test comments
noting the wave-by-wave re-anchor convention. Assertion strength
unchanged (same `{class: "Unported", code: "UNPORTED"}` shape, same
malformed-rich-payload decode-ordering trap).

## Gate handoff

- Batch-status flip NOT performed (gate's job, packet §Batch-status):
  flip the five vector-bearing prefixes + ADD `bookmark_schema.` → done.
  All 299 already replay PASS while pending, so the gate's conformance
  checkpoint should read the SAME 1,528/0/1,723 — the flip is the
  straggler ratchet only (the +299 PASS delta was taken at bind time,
  B2 precedent).
- The gate's oracle probe covers the same 17 names; the cumulative
  differential regression should list ZERO remaining Phase-1
  pending-skip families (see the skip-ledger movement note below).
- Referee (b) expectation stands: two expected-and-disclosed
  frequency-filter REJECTs (K2-notes §6) — not new findings.
- `throwaway/b3-k*` directories: still present, gate deletes after
  arbiter sign-off (untouched by this task).
- K1-D1 arbiter item (integer-like `extra_forbidden` order) remains
  open; the K1 fuzz-generator exclusion held — no such input was drawn
  by the bookmark_schema_family run (0 divergences).

## Rig fixes surfaced by this task (fable-owned, fixed at the owning layer)

1. **`model_name` output codec rejected `None`**
   (`conformance/record/codecs.py` `encode_output`): the pre-B3 spelling
   raised `UnencodableValueError` for the DOCUMENTED
   `get_root_model_for_bookmark_type` `None` return (`"user"`/unknown
   types) — never seen before because the api had zero vectors and no
   oracle family. Found by the get_root_model_family self-parity smoke;
   fixed to encode `None` → JSON null (the packet's §Binding shapes
   "model_name — the handle's `.name` string, or null" already specified
   the null arm; the TS binding twin emits null).
2. **Non-finite edge probes in the K1 `bookmark_schema_family`**
   (`strategies.py`): `float("inf")`/`float("nan")` in `_B3_LEAF_VALUES`
   and the explicit `finite_number` edge are unshippable through
   `encode_input_kwargs` (`_reject_bad_float`, D6 rule 5) — the K1
   module task declared the family but never ran it through the bridge
   (transport deferral, K1-notes §4). Removed with a documented-omission
   note (same standing posture as the B2 `finite_number` arms); the
   pydantic `finite_number` row stays locked by the K1 throwaway harness
   + Layer-3, and the huge-finite `1e300` probe (`int_parsing_size`)
   remains the nearest bridge-reachable neighbour.

## Binding design decisions (arbiter checklist)

1. **Honesty (P3-5 rule 3)**: every binding calls the real ported entry
   point (`bookmarks/builders.ts`, `query/{segfilter,expressions,
   transforms,user-builders}.ts`, `bookmarks/schema.ts` +
   `schema-sorting.ts`). Adaptations, in full: kwarg plumbing; the
   `today`/`uuid` shims; the expect-position output encoding (below); the
   `runGuarded` error wrap; the `model_name`/`validation_errors` output
   codecs (recorder-codec twins).
2. **Expect-position output encoding**: the runner's `diffReturnedValue`
   calls `encodeExpectValue` with NO rich-tag hook and the canonicalizer
   does NOT normalize `{$type: "float"}` objects, so builder bindings
   post-process `codecs.encodeValue(...)` with a walk that (a) drops
   `$type` members whose tag is a CONTRACT rich tag (Python
   `encode_expect_value(tagged_models=False)` twin — Filter dicts in
   `extract_cohort_filter` outputs), and (b) rewrites finite
   `{$type: "float", value: s}` payloads to `new JsonNumber(s)` so
   float-ness renders `18.0` exactly like the recorded raw token.
   Mirrors oracle-py `_encode_result` and oracle-ts `toExpectEncoding`
   (server.ts:239) — the server's own transform is idempotent over this.
   Non-finite spellings stay tagged (illegal as raw canonical JSON;
   measured: NO B3 vector carries a non-finite value — the B20B NaN
   vectors live in `bookmarks/test_validation_bypass_r2.jsonl`, a B2
   `validate_bookmark` surface — so the non-finite arm of the walk is
   oracle-path safety only).
3. **PyFloat kwarg discipline**: decoded kwargs pass through UNCONVERTED
   (packet §Binding shapes). No deep unwraps anywhere in the B3 bindings;
   the ported modules are carrier-aware (`isFloatCarrier` /
   `pythonStrValue` / `timestampNumber`).
4. **Seams**: `build_time_section` ← `context.shims.today`;
   `transforms.transform_event` ← `context.shims.uuid` + PyDatetime wrap
   of the returned `event_time` iso text (codecs.py:227-228 twin).
5. **Builtin-exception propagation (K3-notes §7.3)**: the
   `python-builtins.ts` twins are not `MixpanelHeadlessError`s, so
   `runGuarded` rethrows them raw; the oracle's `errorPayload` encodes
   `constructor.name` → `{class: "ValueError"|...}`. No vector reaches
   them (all 299 well-formed).
6. **validate_with_pydantic retarget**: Python adapter
   `(model: str, value, path_prefix="")` over the fixed 5-name map,
   DEFAULT code mapper; TS twin resolves `BOOKMARK_MODEL_HANDLES` and
   calls `validateWithPydantic(handle.validate, value, {path_prefix})`,
   output through the B2 `encodeValidationErrors` encoder.

## Discovered facts / measurements

(running)

## Oracle probe record (2026-08-15)

py: `{language: python, library_version: 0.2.1, protocol_version: 1.1,
source_commit: b5c1369…}`; ts: `{language: typescript, library_version:
0.0.0, protocol_version: 1.1, source_commit: b5c1369…}` (pre-re-pin
manifest stamp). **All 17 B3 apis: `py_ok=True ts_ok=True equal=True`**
via `compare_call` (shared codec encode + canonical diff — a bridge
missing a name surfaces as an "unknown api" protocol error, so EQUAL
proves both bridges answer). Probe script: one representative edge call
per api drawn from the api's own strategy family
(`/tmp/b3bind-oracle-probe.py`, transcript in the task log; re-run =
rerun that script with both bridges).

## R10.9 RUN record (seed **64091337**, fresh — B2-BIND used 83155107,
B0 gate 52794688)

Command (run 1, 15 families at the 500 budget):

```
uv run python -m conformance.differential.fuzz_harness \
  --right "node <ts-repo>/scripts/run-oracle.mjs" \
  --targets build_filter_entry,build_segfilter_entry,normalize_on_expression,\
bookmark_schema_family,get_root_model_family,build_filter_section_family,\
build_group_section_family,build_flow_property_filter_family,\
build_flow_cohort_filter_family,build_frequency_filter_entry_family,\
build_time_section_family,build_date_range_family,transform_event_family,\
transform_profile_family,extract_cohort_filter_family \
  --examples 500 --seed 64091337 --report json
```

Run 2 (the K4 DOUBLED budget): same, `--targets
filter_to_selector,filters_to_selector --examples 1000`.

**Results: status ok on both runs — 9,395 examples total, 0 skips,
0 divergences, no repros written.** Per family:

| family | examples | div |
|---|---|---|
| build_filter_entry | 508 | 0 |
| build_segfilter_entry | 549 | 0 |
| normalize_on_expression | 505 | 0 |
| bookmark_schema_family | 589 | 0 |
| get_root_model_family | 510 | 0 |
| build_filter_section_family | 513 | 0 |
| build_group_section_family | 520 | 0 |
| build_flow_property_filter_family | 512 | 0 |
| build_flow_cohort_filter_family | 515 | 0 |
| build_frequency_filter_entry_family | 510 | 0 |
| build_time_section_family | 485 † | 0 |
| build_date_range_family | 101 † | 0 |
| transform_event_family | 516 | 0 |
| transform_profile_family | 508 | 0 |
| extract_cohort_filter_family | 510 | 0 |
| filter_to_selector | **1,020** | 0 |
| filters_to_selector | **1,024** | 0 |

† Finite-domain EXHAUSTION, not a budget miss: `build_time_section_family`
draws from 4 dates × 4 dates × 6 lasts × 5 units = 480 distinct calls
(+5 edges = 485 — every possible probe ran); `build_date_range_family`
is 4×4×6 = 96 (+5 edges = 101). K2-notes recorded the date_range
exhaustion as intentional; the time_section domain is the same shape.
Exhaustive coverage strictly dominates the ≥500 sampled budget.

Skip-ledger movement (packet §Oracle-ts registration): the five Phase-1
pending-skip families (`build_filter_entry`, `build_segfilter_entry`,
`filter_to_selector`, `filters_to_selector`, `normalize_on_expression` —
B2-BIND-notes) are now LIVE with the counts above — **ZERO Phase-1
pending-skip families remain**. The gate's cumulative full-suite
regression should show the same.
