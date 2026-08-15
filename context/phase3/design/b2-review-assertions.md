# B2 adversarial review — ASSERTION FIDELITY + BINDING HONESTY lens

**Status**: COMPLETE · 2026-08-15 · fable reviewer (P3-2d, lens: assertions/binding-honesty)
**Verdict**: **GO** — 1 minor finding, 2 nits/observations, 0 blocking. Every load-bearing
claim in the four B2 commits reproduced under my own runs.

**Commits reviewed**: TS `5c0e032` (M1/V1a), `617da2b` (M2/V1b), `83fbe2d` (M3/V2),
`2015565` (BIND) on `main`; Python `748ff4e` (B2-BIND strategies) + notes commits
`39282da`/`92e8a1c`/`b12fc18` on `ts-port/phase2-contract-support`. Specs: playbook v1.1
(read in full), `b2-packets.md`, rulebook R10.2/R5.3/R5.4/R4.8/R11.7, B2-HK notes.

---

## 1. Verification runs (all executed by this reviewer, clean tree @ TS HEAD `2015565`)

| Check | Result |
|---|---|
| `npm run conformance -- --filter validation/` | **690/690 PASS, 0 fail, 0 unported** @ corpus `b5c136982405` — the BIND claim reproduces exactly |
| `npx vitest run packages/core/test/query` | **693/693 green** (406 M1 + 113 M2 + 154 M3 + 20 unhashable — reconciles exactly with the three notes files) |
| R10.9 spot re-run, recorded seed **83155107**, families `bookmark_family,query_args_family,user_args_family,sorting_family`, `--examples 60` | **453 examples (incl. edge sets), 0 divergences, 0 skips** — RUN record reproduces; this also live-exercises the zero-vector `validate_sorting_block` binding on BOTH bridges (120 sorting examples py↔ts) |
| CPython probe (uv, this session) | `validate_bookmark` with `chartType: ["bar"]` raises `TypeError: cannot use 'list' as a set element` — independently confirms the R10.7 `requireHashable` adjudication direction |

## 2. R10.2 assertion diff — method

1. **Name-by-name set comparison** of every `def test_` in the 10 Python source files vs
   every `it("test_…")` in the 15 TS files (script, not eyeball):
   - funnel 129/129, retention 107/107 (103+4 across the V1a/V1b split),
     flow 116/116 (86+30), cohort 22/22 (7+15), user_validators 149/149 (+1 documented
     U24 extension + 4 clearly-labeled TS-only today-seam tests), PBT 4/4, 13/13, 8/8,
     `test_validation.py` split 33+56 with the 12-remainder correctly attributed to
     Phase-2 `errors.test.ts`, `test_query_validation.py` 31 validator-direct tests.
   - **Missing in TS: NONE. Silently skipped: NONE.** The 4 flow duplicate names are
     cross-class (no pytest shadowing); both sides carry all 116.
2. **Per-test assertion-count heuristic** (Python `assert`+`pytest.raises` vs TS
   `expect(`+`.toThrow` per same-named body) across all seven example-based pairs:
   **zero tests with fewer TS assertions than Python**.
3. **Deep spot-diffs** (verbatim body comparison): the packet's R10.2-critical
   suggestion-content asserts (`test_invalid_unit_has_suggestion` "hour",
   `test_retention_unit_close_match_has_suggestion` "week", R8 "birth", B5/B9/S4
   suggestion asserts) — all kept verbatim; message-substring asserts
   (`test_per_user_with_unique_raises` etc.) kept against the port's own ported strings
   (packet Caution §7's sanctioned option); the 4-error sorting collection test,
   helper-dict defaults (`_valid_funnel_args` ↔ `validFunnelArgs` field-for-field),
   `assert errors == []` → `toEqual([])`.
4. **Emission-order audit**: U-code push order in `user-validators.ts` matches
   `user_validators.py` code-for-code (U1,U0,U2…U29-between-U25-and-U11,
   U26/U27/U28-between-U17-and-U18, U30-before-U23, dual UP2); `validateQueryArgs`
   matches source order incl. the `_validateDataGroupId`-before-V0 position and the
   time/group_by/CP-scan delegation block between V23 and V13 (with `where=None`
   in the CP scan, verbatim).

### Deferral honesty (every exclusion has a measured citation)

- `query-validation.test.ts` header lists each facade-driven class deferred to B5-S2; I
  verified the class split myself (TestValidateTimeArgs/GroupByArgs fully direct; the 8
  mixed-class validator-direct tests translated; TestHistogramValidation etc. 100%
  `ws.build_params`-driven).
- **M2's whole-file deferral of `test_validation_bypass{,_r2}.py` deviates from the
  packet but is correct**: my grep confirms all 8 `validate_bookmark(params)` sites in
  `bypass.py` consume `ws.build_params(...)` output and `bypass_r2.py` has ZERO direct
  validator references. Translating them pre-B5 would require hand-forging facade output
  (a worse weakening). The 7 recorded bypass vectors replay in the 690.
  **B5-S2 obligation: translate both files whole** (header citation present).
- `test_query_user_edge_cases.py` correctly left to B5 (playbook B5 row); its
  `validation/` vectors replay via the corpus.
- TODO(port) ledger: `bookmarks/enums.ts` P2-3 TODO closed (constants verified = 100/3
  against `bookmark_enums.py:516/519`); M2's TypeError TODO(port) closed at BIND with
  R10.7 adjudication + 20-test lock; **zero stray TODO(port) markers** in the B2 surfaces.
- No `.skip`/`.todo`/`.only`/`xit` anywhere in the B2 test files.

## 3. Binding honesty (P3-5 rule 3) — verified line-by-line

`registerValidatorBindings` (`bindings.ts:1081-1241`): every one of the 11 names invokes
the real exported entry point from `packages/core/src/query` (`validateTimeArgs` …
`validateUserParams`). No re-derived checks, no list filtering/reordering, no output
re-assembly. Adaptations, each verified sanctioned:

- **Encoder** (`encodeValidationErrors`) is the recorder-codec twin: exactly
  `{path, code, severity}`, emission order preserved, throws on non-`ValidationError[]`
  (mirrors `UnencodableValueError`). No message/suggestion/fix serialization — R5.4 clean.
- **Error wrap** `guardCompat` wraps ONLY `MixpanelHeadlessError` → `CoreLibraryError`;
  everything else (incl. the R10.7 `requireHashable` TypeError) propagates unchanged —
  **no error-shape special-casing that could mask module bugs**.
- **PyFloat carrier policy verified against Python source, field by field**: funnel
  `conversion_window` keep-carrier (isinstance at `validation.py:907`) vs flow
  `conversion_window` unwrap (`:1673` pure `<= 0`) — the asymmetry is real; retention
  `bucket_sizes[i]` keep (`:1320/:1329`), `data_group_id` keep (`:487`); V2
  `limit/percentile/workers/segment_by[i]` unwrap (no `isinstance(int/float)` anywhere in
  `user_validators.py`; U17 is `sid <= 0` at `:347`). Deep unwrap is NON-FINITE-only
  (the packet Caution §8 sanctioned exception); behavior-neutrality for the carrier-aware
  M2 surface verified against `_isFinite` (`validation-shared.ts:560-569` classifies
  native and carrier non-finite identically). The redundant group_by unwrap was removed
  from the binding when the GroupBy codec took ownership — dead-adaptation hygiene.
- **GroupBy codec fix** (`vector-codecs.ts`) is decode-layer parity, not binding
  compensation: Python decodes `$type: float` into a real float inside the dataclass, so
  the TS instance must hold native numbers (SignedReplay precedent; `Number(spelling)`
  carries the R11.7 rig-internal exemption citation at the call site; red-first lock in
  `codecs.test.ts`).
- **`today` seam** from `context.shims.today()` (runner builds `createShims(recordEpoch)`
  at `runner.ts:445,460` — verified) on `validate_user_args` only; library defaults to
  the real clock.
- **One registration point**: oracle-ts serves the 11 names via `createRunnerDeps` →
  `executeBound` (`differential/oracle/server.ts` imports the same module);
  `validate_sorting_block` bound despite zero vectors and exercised live by my fuzz
  spot-run; `bookmark_schema.validate_with_pydantic` correctly NOT bound (B3's — the
  exclusion is recorded for the gate in the BIND notes).
- **No runner/canonicalizer edits** in the BIND commit (file stat: bindings, codecs
  test, two module files, vector-codecs, new test file only).
- Python-side `strategies.py` families: per-code edge calls for corpus-present AND
  source-only codes with `strategies.py:253-257`-style documented omissions
  (non-finite unshippable per D6 rule 5; ctor-guard-unreachable pinned by nearest arms;
  `workers=None` boundary); strategy-table lock extended (`_PHASE3_B2_NAMES`).

## 4. Rulebook compliance sweep (lens items)

- **R5.4 codes-not-messages**: vectors/binding encoder — codes only (verified above);
  test-side message asserts only against the port's own ported strings (sanctioned).
- **R4.8 / watchlist #7**: enum membership via imported `ReadonlySet.has()` /
  `ReadonlyMap` from `bookmarks/enums.ts` (never re-declared, R10.8); `Object.hasOwn` at
  every params-dict key test (3/8/7 hits across validation-bookmark / schema-sorting /
  user-validators; no bare `in` on user dicts — the single `"spelling" in value` hit is
  internal carrier plumbing on a known shape).
- **R11.7 [SA3] grep**: ZERO `.trim(` / `parseInt(` / `JSON.parse(` / `Number(` call
  sites and zero `\s`/`\d` regex grammars in the ported B2 sources (all hits are prose or
  the exempt rig-internal codec site); `pythonStrip` at all 14 measured `.strip()` sites;
  pydantic-core third-parser carve-out properly cited in the `schema-sorting.ts` header
  with probe evidence; `_ACTION_RE`/date checks built from pinned tables with pure
  ASCII-digit conversion helpers (no `Date()` in accept/reject decisions).
- **R10.8**: V1b imports V1a's shared helpers; `user-builders.ts` carries the B3-K4
  grower note; `schema-sorting.ts` names B3-K1 as its grower.

## 5. Findings

### F1 (minor, R10.2 strategy narrowing) — M1 PBT files narrow Hypothesis Unicode text domains to ASCII, mostly uncited

- `query-validation.pbt.test.ts:66-77`: `LN_ALPHABET` (62 ASCII chars) with a comment
  claiming it "mirrors `st.characters(categories=("L","N"))`" — Python's L/N is the full
  Unicode Letter/Number set incl. non-BMP.
- `validation.pbt.test.ts`: same `LN_ALPHABET` for `validSetsArb`/`propertyNamesArb`;
  `queryStringsArb = fc.string({maxLength: 20})` (fast-check default = printable ASCII)
  vs Python `st.text()` (full Unicode); `nonemptyFormulasArb` likewise. The file-header
  fidelity note covers ONLY `test_clean_strings_pass`.
- Materiality: `queryStringsArb` feeds `TestSuggestInvariants` — the `difflib` port.
  Suggestions are advisory (R5.3): the differential fuzz diffs `{code,path,severity}`
  only, so **Layer-3 is the sole lock on `_suggest`'s Unicode behavior, and it now tests
  ASCII only**. The port looks codepoint-correct on read (`Array.from` splitting,
  `sortedByCodepoint` candidates), but the Python test's generative domain was wider.
- Contrast: M2's `bookmark-validation.pbt.test.ts` uses `unit: "binary"` (full-Unicode)
  for its three `st.text` twins, and M1 itself uses `unit: "binary"` for
  `test_agrees_with_reference` — the faithful idiom was known and available.
- **Fix (cheap)**: switch the four M1 arbitraries to `unit: "binary"` / explicit
  Unicode-bearing alphabets (incl. one non-BMP char), or extend the two file headers with
  an explicit design citation for each narrowed strategy; correct the two "mirroring"
  comments either way. Not gate-blocking: the invariants themselves are untouched and
  cross-language behavior is separately locked by the full-Unicode Python-side R10.9
  strategies (`_B2_NON_BMP` edges throughout).

### F2 (nit, doc) — `validation-bookmark.test.ts` header miscounts a class

Header says "`TestValidateBookmarkLayer2` (22)"; the class has 20 methods in Python and
20 `it()` in TS (file totals reconcile at 56/56). Typo only — fix at the gate touch.

### Observation A (forward note, Phase-2 owner) — `test_frozen` has no runtime counterpart

The 12 `TestValidationError`/`TestBookmarkValidationError` tests deferred to Phase-2 are
behaviorally covered by `errors.test.ts` EXCEPT `test_frozen` (frozen-dataclass
assignment raises): TS `ValidationError` relies on compile-time `readonly` with no
`Object.freeze` and no runtime test. Phase-2 scope, not a B2 defect; recorded so the
ledger stays honest.

### Observation B (packet nit) — b2-packets.md §V2 says "5" edge-case vectors; the corpus and the packet's own reconciliation table say 4

No effect on any count that matters (690 verified by replay).

## 6. Gate handoff

- Batch-status flip (`validation.` + `user_validators.` → done) still pending — correct
  per the packet (gate's job). Expected: PASS stays 1,229, UNPORTED stays 2,022, FAIL 0.
- B5-S2 obligations restated: translate `test_validation_bypass{,_r2}.py` whole; extend
  `CoreLibraryError.toExpectError()` with `errors[]` for `BookmarkValidationError`
  replay; facade-driven classes of `test_query_validation.py` and the V1b bypass halves.
- B3 obligations: bind `bookmark_schema.validate_with_pydantic` (B3-K1); B3-K1 grows
  `schema-sorting.ts`; B3-K4 imports `isCohortFilter`.
- F1 fix can ride any pre-gate TS touch or the gate commit itself.
