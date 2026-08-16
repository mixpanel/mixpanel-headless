# B2 review resolution — arbiter (P3-2d)

**Status**: COMPLETE · 2026-08-15 · fable arbiter (B2 review pair: fidelity
`b2-review-fidelity.md` NO-GO / assertions `b2-review-assertions.md` GO)
**Inputs**: both review files (commits `996957d` / `61a64a0`), playbook v1.1,
b2-packets.md, rulebook, B2-M1/M2/M3/BIND/HK notes, Python + TS source.
**Method**: every finding independently re-verified against source AND both
oracle bridges (the reviewers' repro scripts `/tmp/b2rev_spot{,2,3}.py`
re-run pre- and post-fix, plus two new arbiter probes
`/tmp/b2arb_probe{1,2}.py`); fixes applied red-first (TDD); every affected
harness re-run from its recorded seed.

**Split resolution: the fidelity NO-GO was correct.** All five fidelity
findings verified. Post-resolution state: F1 (extended) and F3 FIXED with
locks; F2 and F4 BLESSED as playbook Discrepancies #8/#9; F5 corrected in
the surviving records. Assertions findings: F1 FIXED, F2 FIXED, observations
recorded. **B2 is GO for the gate** once this resolution's commits land.

## Verdicts

| # | Finding (reviewer) | Verdict | Disposition |
|---|---|---|---|
| FID-F1 | blocker — `isDict`/`isPlainObject` conflate PyFloat carriers + class instances with dicts | **CONFIRMED — FIXED (and extended, see F1b)** | Shared prototype-based `isPythonDict` in `validation-shared.ts`; `isDict`/`isPlainObject`/`requireHashable`/`user-builders.isPythonDict` all delegate (R10.4 → rulebook watchlist #13). 19 red-first locks in `validation-dict-fidelity.test.ts`; strategy domains extended; all 11 oracle rows now match. |
| FID-F1b | arbiter extension — the carrier DUCK-shape misclassifies plain `{"spelling": ...}` dicts as floats | **CONFIRMED — FIXED** | 4 additional oracle-confirmed in-annotation divergences (incl. a `PY_FLOAT_INVALID_LITERAL` crash where Python returns `bool(dict)`; a `requireHashable` no-raise where CPython raises). The rig's carrier is a `PyFloat` CLASS instance (single construction site `conformance-runner/src/codecs.ts:483`), so `isFloatCarrier` now also rejects `isPythonDict` values. The reviewer's suggested duck-exclusion fix shape would have left these (and regressed 2 of its own rows to the inverse direction); prototype discrimination fixes both directions. |
| FID-F2 | major — out-of-annotation scalars: CPython raises, TS returns (15 sites) | **CONFIRMED — BLESSED as a class** (option b) | Playbook **Discrepancy #8**. Boundary = the declared annotation: IN-annotation raise behavior (`dict[str, Any]` interiors — requireHashable) IS contract; out-of-annotation behavior is unspecified. Verified every one of the 15 reviewer sites violates its annotation (`last: int`, `born_event: str`, `rolling: int \| None`, `params: dict[str, Any]`, `segment_by: list[int]`, `properties: list[str]`, `distinct_ids: list[str]`, `sort_by: str`, `workers: int`) — no member of the class is in-annotation, so the ruling does NOT contradict the R10.7 requireHashable adjudication; it draws the line the adjudication implied. strategies.py domain notes now carry the class constraint (supersedes the lone `workers=None` mention). |
| FID-F3 | major — CM5 spelled `typeof !== "number"` vs `instanceof CohortDefinition` | **CONFIRMED — FIXED** | `validation-args.ts` now spells `item.cohort instanceof CohortDefinition`. Locks: `CohortMetric(cohort=true)` / `cohort=<carrier>` / mixed-list tests + query_args strategy arms (CM5 pinned by REACHABLE non-CohortDefinition arms). Oracle rows match. |
| FID-F4 | minor — S4 warning order flips for integer-like unknown chart keys | **CONFIRMED — BLESSED** | Playbook **Discrepancy #9**. Not fixable for plain-object inputs (JS objects cannot hold integer-like keys in insertion order — the loss is at object construction for consumers, not only at `JSON.parse`); an ordered-map value domain end-to-end is out of proportion for a warning-order flip with identical triples. Integer-like unknown chart keys = documented sorting-domain omission. |
| FID-F5 | minor — stale skip-class prose in `throwaway/b2-m2/RUN.md` | **CONFIRMED — FIXED** | Correction paragraph prepended to the RUN.md skip section (original text preserved beneath, marked superseded) + surviving correction in `B2-M2-notes.md` (which outlives the gate's `throwaway/` deletion). |
| ASSERT-F1 | minor — M1 PBT files narrow Hypothesis Unicode text domains to ASCII, mostly uncited | **CONFIRMED — FIXED** | `queryStringsArb`/`nonemptyFormulasArb` → `fc.string({unit: "binary"})` (full-Unicode, the M2 idiom); the two L/N alphabets extended with explicit non-ASCII L/N members incl. non-BMP `𝒳` (code-point-safe indexing in `query-validation.pbt.test.ts` — the old UTF-16 string indexing would have emitted lone surrogates); both "mirroring" comments replaced with accurate NARROWED-stand-in citations. All PBT suites green post-widening. |
| ASSERT-F2 | nit — `validation-bookmark.test.ts` header says (22), class has 20 | **CONFIRMED — FIXED** | Header corrected to (20); both sides re-counted (20/20, file totals 56/56). |
| ASSERT-ObsA | `test_frozen` has no runtime counterpart in Phase-2 `errors.test.ts` | **CONFIRMED — FORWARDED** | Phase-2-owned; not a B2 defect. Forward note (below) for the next Phase-2-owned touch: either add `Object.freeze` + a runtime lock or record readonly-only as the blessed idiom in the Phase-2 audit trail. |
| ASSERT-ObsB | b2-packets.md §V2 "5" vs 4 edge-case vectors | **CONFIRMED — RECORDED** | Packet-internal nit; 690 verified by replay on both reviews and again post-fix. No action beyond this line (the packet is a historical artifact; correcting it would falsify the record the notes cite). |
| FID-Obs (`Number(spelling)` in `vector-codecs.ts:434`) | — | **NO CHANGE** | The rig-internal exemption is cited at the call site and the input domain is codec-canonical spellings only; letter-of-R11.7 substitution would touch adjudicated rig code for zero behavioral delta. |

## Fixes applied (both repos)

**TS (`mixpanel-headless-ts`, one commit on `main`)**:

- `packages/core/src/query/validation-shared.ts`: new exported
  `isPythonDict` (prototype-based: plain object = `Object.prototype` or
  `null` prototype); `isFloatCarrier` tightened with `!isPythonDict(value)`;
  `requireHashable` dict branch delegates to `isPythonDict`.
- `packages/core/src/query/validation-bookmark.ts`: `isDict` delegates.
- `packages/core/src/bookmarks/schema-sorting.ts`: `isPlainObject` delegates.
- `packages/core/src/query/user-builders.ts`: local `isPythonDict` replaced
  by re-export of the shared one (semantics identical for its consumers).
- `packages/core/src/query/validation-args.ts`: CM5 branch →
  `item.cohort instanceof CohortDefinition` (+ `CohortDefinition` import).
- `packages/core/test/query/validation-dict-fidelity.test.ts` (NEW, 19
  red-first tests): the 11 FID-F1 oracle rows, the CM5 rows, and the 6
  F1b spelling-dict rows (incl. the unhashable-dict raise and the
  no-crash truthiness case). TS-only suite — reference outputs are the
  oracle-py records herein (no Python Layer-3 twin exists by construction).
- `packages/core/test/query/validation.pbt.test.ts` +
  `query-validation.pbt.test.ts`: ASSERT-F1 strategy widenings + comment
  corrections. `validation-bookmark.test.ts`: header count fix.
- `throwaway/b2-m2/RUN.md`: F5 correction paragraph.

**Python (`mixpanel-headless`, support branch, one commit)**:

- `conformance/differential/strategies.py`: §B2 domain-notes header
  rewritten (Discrepancy #8 class constraint supersedes `workers=None`;
  Discrepancy #9 omission; F1 in-domain note); bookmark/sorting pools
  widened (floats, `Filter` instance, spelling-dicts at dict positions);
  edge calls added — bookmark ×9, sorting ×4, flow_bookmark ×1,
  query_args ×3 (CM5 arms), user_params ×2, query-events pool ×2.
- `context/phase3/design/phase3-playbook.md`: Discrepancies #8, #9.
- `context/typescript-port-rulebook.md`: watchlist item **13** (R10.4
  amendment — `isinstance(x, dict)` discrimination, import
  `isPythonDict`, never re-derive; 4 unified occurrences listed).
- `context/phase3/notes/B2-M2-notes.md`: F5/F4/F1 correction section.
- `context/phase3/notes/B2-BIND-notes.md`: post-fix fuzz RUN record +
  domain-extension addendum.
- This file.

## Post-fix verification (all green)

| Check | Result |
|---|---|
| New locks | 19/19 `validation-dict-fidelity.test.ts` (red-first: 13/13 failed pre-fix, then green; +6 F1b cases) |
| Full TS suite | `npm run check` exit 0 — 3,619 passed / 2,022 corpus-skipped (was 3,600 + the 19 new) |
| B2 vectors | `npm run conformance -- --filter validation/` → **690/690 PASS** @ b5c1369 |
| Reviewer spot scripts | spot2: 16→7 divergences; spot1: 3→1; spot3: 11/13 — **every remaining divergence is a blessed Discrepancy-#8 member or the Discrepancy-#9 order case; zero others** |
| Arbiter probes | probe1 4/4 OK; probe2 5/5 OK (were 4/5 diverging pre-F1b-fix) |
| BIND fuzz (extended domains) | seed 83155107, 500/family: **5,882 examples, 0 skips, 0 divergences** (per-family table in the B2-BIND notes addendum; +19 examples from the new edges) |
| Module harnesses (recorded seeds) | m1 3,828/506/0 · m2 1,921/8/0 (skips now bilateral per F5) · m3 1,510/0/0 — all counts reproduce post-fix |
| Python side | `just check` green (strategies.py + docs) |

## Ripple audit

- The F1/F1b/F3 code fixes invalidated no vector, no Layer-3 test, and no
  RUN-record count (all three module harnesses reproduce their recorded
  totals; the BIND fuzz totals moved only by the +19 added edges).
- `user-builders.isPythonDict` consumers (`isCohortFilter`, UP2) verified
  behavior-identical under the unification (probe1) — the shared
  implementation matches the user-builders original for every reachable
  input class.
- The binding layer is untouched (no honesty-surface changes); the GroupBy
  codec, encoder, and carrier tables are as the assertions review verified.

## Gate handoff / forward notes

1. **Gate flip unchanged**: `validation.` + `user_validators.` → done;
   PASS stays 1,229 / UNPORTED 2,022 / FAIL 0 at the flip.
2. `throwaway/` deletion at the gate: the F5 correction survives in
   `B2-M2-notes.md`; nothing else in `throwaway/` is load-bearing.
3. **Phase-2 forward note (ASSERT-ObsA)**: `ValidationError` frozen-ness
   has no runtime lock — next Phase-2-owned touch adds `Object.freeze` +
   test, or blesses readonly-only in the Phase-2 audit trail.
4. **B3-K1/K4 forward note**: `schema-sorting.ts` and `user-builders.ts`
   growers inherit watchlist #13 — import `isPythonDict`, never re-derive
   a dict test; `bookmark_schema.validate_with_pydantic` binding still B3's.
5. **B5-S2 obligations** (restated from the assertions review §6):
   translate `test_validation_bypass{,_r2}.py` whole; extend
   `CoreLibraryError.toExpectError()` with `errors[]`; facade-driven
   classes of `test_query_validation.py`.
6. Discrepancies #8/#9 re-examination triggers are recorded in the
   playbook entries (B5-facade runtime forwarding; consumer dependence on
   S4 order).
