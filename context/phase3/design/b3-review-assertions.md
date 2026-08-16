# B3 adversarial review — ASSERTION FIDELITY + BINDING HONESTY lens

**Status**: COMPLETE · 2026-08-15 · fable review-pair member (P3-2d, strongest tier)
**Scope reviewed**: TS `794fea1..45a06cf` (K1 `0a68942`, K2 `5024bb4`, K3 `755e9a1`,
K4 `9add8c4`, BIND `45a06cf`); Python `a2163c7..0f7f80e` (K1–K4 oracle families,
adapter retarget `70c904d`, re-pin `d89f2a8`, notes `17a8172`/`0f7f80e`).
Verdict: **GO** — with one OPEN arbiter item (K1-D1) and three minor findings below.
No weakened assertion, no silently-skipped test, no binding-honesty violation found.

## 1. 299-vector replay (re-run by this reviewer)

`npm run conformance -- --filter <prefix>` per prefix, 2026-08-15, logs
`/tmp/b3rev-conf-*.log`:

| prefix | vectors | result |
|---|---|---|
| `bookmark_builders.` | 134 | 134 PASS / 0 FAIL / 0 UNPORTED |
| `segfilter.` | 51 | 51 PASS |
| `expressions.` | 30 | 30 PASS |
| `transforms.` | 2 | 2 PASS |
| `user_builders.` | 82 | 82 PASS |
| **Σ** | **299** | **299/299 @ corpus 70c904dc598d** |

Matches the packet's gate arithmetic (1,229+299 pending flip). Corpus pin is the
post-retarget re-pin (b5c1369 → 70c904d, P3-7 trigger 1) — correct.

## 2. R10.2 assertion-fidelity census (diffed file-by-file)

| Python source (tests) | TS twin | census | verdict |
|---|---|---|---|
| `test_expressions.py` (10) | `query/expressions.test.ts` | 10/10 via `it.each`; escaped literals byte-checked by this reviewer (`'path\\to\\"file'` → `'properties["path\\\\to\\\\\\"file"]'` identical char sequences in both languages) | VERBATIM |
| `test_expressions_pbt.py` (6) | `expressions.pbt.test.ts` | 6/6 | ok |
| `test_segfilter.py` (57, 9 classes) | `query/segfilter.test.ts` | 57/57, 9 describes; R10.11 stringify asserts (`"100"`, `"9.99"`, `["10","100"]`, typeof string) intact; SG1–SG4 as class+code; the Python `pytest.raises(ValueError)`+isinstance dual-catchability assert adapted to `MixpanelHeadlessError`+`ParamValidationError` descent with citation | FAITHFUL |
| `test_user_builders.py` (78, 18 classes) | `query/user-builders.test.ts` | 78/78 exact per-class map (verified describe-by-describe); ES1–ES13 direct+seam ×13 + catchable = 27/27; escaping classes exact-equality (`'properties["weird\\"prop"] == "val"'` etc.); bounds-validation message-matches UPGRADED to code asserts (ES11/ES12); `TestNotEqualsErrorMessage` message assert kept VERBATIM (`toContain("Filter.not_equals")`) plus code — not weakened | FAITHFUL+ |
| `test_query_user_structural.py` (4 B3 classes) | split K3/K4 with header citations | `TestPbtFormatValueSpecialChars` (2) → fast-check with SUPERSET domain (`unit:"binary"` + explicit special-char mix-in, numRuns 200 ≥ Python 100); `TestFiltersToSelectorOrAndPrecedence` exact-string; `TestTransformProfileMissingDistinctId`/`CompletelyEmpty` → transforms.test.ts verbatim | FAITHFUL |
| `test_bookmark_builders.py` (116, 18 classes) | `bookmarks/builders.test.ts` | per-class counts ALL ≥ Python (116 base + 9 in-class `// NEW` additions, each marked with a packet/watchlist citation); Set-comparisons at listContains mirror Python's own set comprehensions (NOT an order relaxation) | FAITHFUL |
| `test_custom_property_builders.py` (3 builder-direct classes, 19) | same file | 19/19; `TestMeasurementPropertyBuilder` deferred to B5 with header citation (drives `Workspace.build_params`) | FAITHFUL |
| `test_bookmark_builders_pbt.py` (4 classes) | `builders.pbt.test.ts` | `TestListContainsRoundTrip` translated in full (all 14 asserts; `fc.pre` re-establishes the min-size precondition rather than dropping asserts). **Three classes deferred to B5-S2** — see §2a | see §2a |
| `test_bookmark_enums.py` (39, 6 classes) | `bookmarks/enums.test.ts` | 39/39; set algebra helpers = Python `<=`/`==`/`-`/`&`; `isinstance(X, frozenset)` → `instanceof Set` + ReadonlySet type (documented) | FAITHFUL |
| `test_bookmark_schema.py` (42, 9 classes) | `bookmarks/schema.test.ts` | 42 → 53 (additions only); structural-twin caveat documented in header: `Model.model_validate(...)` + attribute asserts become zero-error asserts (no parsed object exists in the validator twin; sole consumer reads the error stream); every `pytest.raises` keeps full strength via pydantic error `type` strings pinned to the K1 CPython probe | FAITHFUL (documented adaptation) |
| `test_bookmark_schema_pbt.py` (14, 7 classes) | `schema.pbt.test.ts` | 14 fc properties; `TestRoundtripSoundness` "dump → re-validate" halves become second-validation (no `model_dump` in a validator twin) — disclosed in header | FAITHFUL (documented adaptation) |
| (no Python unit source) `transform_event` | `query/transforms.test.ts` | 11 NEW cases, every one marked `// NEW` with docstring/probe citation per packet §K3 | ok |

No `.skip` / `.todo` / `.fails` / `xit` / `xdescribe` anywhere in the ten new test
files. No assertion was found weakened, dropped, or narrowed without a header
citation.

### 2a. PBT deferral (verified against Python source, ruled LEGITIMATE)

The `builders.pbt.test.ts` header defers `TestTimeSectionEquivalence` /
`TestFilterSectionEquivalence` / `TestGroupSectionEquivalence` to **B5-S2**. The
packet's Layer-3 table says "all (fast-check twins)". I read the Python file:
all three classes assert `ws._build_query_params(...) == build_*(...)` against a
`Workspace` instance (`test_bookmark_builders_pbt.py:94,134,178,203,240,295,320`)
— they are facade WIRING tests; no `Workspace` exists at B3, so translating them
now would violate R10.1. Deferral is header-cited AND logged in
`B3-K2-notes.md:120-122`. **The B5-S2 packet author must pick these up** — the
deferral note is the tracking record. Not a finding against K2; the packet line
was imprecise.

## 3. Binding honesty (all 17 names, `45a06cf`)

- Only `conformance-runner/src/bindings.ts` changed under `conformance-runner/src`
  across ALL B3 commits — no runner/canonicalizer/codec/batch-status edits, no
  error-shape special-casing, no flip (flip correctly left to the gate).
- Every binding calls the real ported entry point (`buildFilterEntry`,
  `buildSegfilterEntry`, `normalizeOnExpression`, `transformEvent`,
  `filterToSelector`, `getRootModelForBookmarkType`, …) through
  `bindBuilder → runGuarded → codecs.encodeValue`. Kwargs pass through
  UNCONVERTED (PyFloat discipline); absent-stays-absent honored
  (`data_group_id` via `Object.hasOwn`, `path_prefix` via `!== undefined`).
- `toBuilderExpectOutput` is the expect-encoding codec twin the packet's
  §Binding-shapes sanctions: rich-tag strip driven by `CONTRACT_TAG_CODECS.keys()`
  (cannot drift from the decode table) + finite `$type:float` → `JsonNumber(spelling)`
  (token-preserving); built-in tags (datetime) and non-finite spellings stay
  tagged. Strings (selector_str) pass through VERBATIM — no trim, no normalize.
  This is a structural encoding, not output re-assembly.
- Seams: `today` ← `context.shims.today()` (build_time_section only);
  `uuid` ← `context.shims.uuid` (transform_event only). No fetch/sleep/random.
- `validate_with_pydantic`: TS mirror of the Python name-resolving adapter
  (`adapters.py::validate_with_pydantic`, commit `70c904d`) — same five names,
  same spellings, DEFAULT code mapper, unknown-name `ValueError` twin; output via
  the B2 `validation_errors` encoder (emission order preserved). Python adapter
  itself delegates to the real `bookmark_schema.validate_with_pydantic` — adds
  shape, never behavior.
- Errors: shared `runGuarded`/`guardCompat` wrap only; the 67 `expect.error`
  vectors round-trip `{class, code}` through the untouched `toExpectError` path
  (evidenced by 67/67 passing in the replay). K3 builtin twins
  (`ValueError`/`OverflowError`/`AttributeError`) rethrow raw and encode by
  `constructor.name` — the fable rig decision Cautions §9 required, made at (b′).

## 4. Rulebook-compliance greps (all new src files)

- **R11.7**: zero `.trim(`, zero `parseInt(`. `String(` appears only at (i) the
  two R10.11 segfilter operand positions (via natural JS rendering inside
  `stringifyOperand`), (ii) display-only message interpolations (out of contract),
  and (iii) `transforms.ts dictKeyText` — see finding F2.
- **Watchlist #2**: `replaceAll` at all four escaping sites
  (`expressions.ts:68`, `user-builders.ts:194,228`); zero bare `.replace(` with a
  string pattern in any B3 src file. `str(value)` renderings go through the
  shared carrier-aware `pythonStrValue` (validation-shared.ts) in BOTH segfilter
  (datetime `str(value)` path) and user-builders (`_format_value`).
- **R10.12**: `filterValue` sites `builders.ts:611` (`f._value` native), `:690`
  (`true` JSON boolean), `:961` (`ff.value` native) — no `String(`/`pythonStr(`
  near any `filterValue` assignment.
- **Watchlist #13/#7**: `isPythonDict` at `builders.ts:834,845` (the BB7/BB8
  `isinstance(x, dict)` sites); `Object.hasOwn` at `:331-333` (patch guard),
  `:855,859,862` (cohort_data), `transforms.ts` dictGet/dictPop — no bare `in`.
- **R4.8**: every table is `ReadonlyMap`/`ReadonlySet` (`segfilter.ts:62-137`,
  `transforms.ts:77,87`, `schema.ts PARTIAL_UPDATE_SUB_MODELS:1332`,
  `BOOKMARK_MODEL_HANDLES:1347`).
- **R10.7**: `buildFrequencyFilterEntry` replicates the server-500 shape with the
  probe-record citation in the function docblock; 9/9 corpus vectors pass; the
  flows `extra="allow"` upstream TODO quoted verbatim into the
  `FLOWS_BOOKMARK_PARAMS` docblock (drifts with source, as specified).
- **Watchlist #5**: `defaultToday()` reads LOCAL calendar date (matches Python
  `date.today()`), render-only; the isoformat path in transforms is pure
  arithmetic (no `new Date()` parsing anywhere).

## 5. TODO(port) triage

Exactly two markers in B3 src, both logged-not-guessed:
- `transforms.ts:136` (`dictKeyText` non-string dict-pair keys) — owner note cites
  B3-K3 notes §domain notes; see finding F2 for the spelling nit.
- `transforms.ts:307` (CPython OSError errno-84 band inside `fromtimestamp`) —
  probe-pinned, packet-authorized domain exclusion, disclosed in
  `B3-K3-notes.md` §5.2.
K1 left zero markers (`B3-K1-notes` §7 states it explicitly; verified by grep).

## 6. Discrepancy #8 / #9 (ratified rulings, applied as ratified)

- **#8**: no out-of-annotation guard code added anywhere. The deep CPython
  emulation in `transforms.ts pythonDictCopy` is IN-annotation (`properties` is a
  `dict[str, Any]` interior) — exactly what the ratification requires, pinned by
  a CPython 3.14.6 probe matrix (`B3-K3-notes.md:196-208`). `isSelectorNumber`
  accepts boolean + carrier per `bool <: int` (Caution 11). Fuzz domains
  annotation-constrained by construction; the two BIND-time domain exclusions
  (non-finite kwarg probes — unshippable through `encode_input_kwargs`; |time| ≤
  1e12) are documented omissions in the BIND notes.
- **#9**: NOT extended. The one new integer-like-key order flip found (K1's
  `extra_forbidden` emission order) was escalated as its own arbiter item
  (K1-D1) instead of being absorbed — the correct behavior under Caution 17.
  All sorted()/Set comparisons in tests correspond to Python set/frozenset
  comparisons in the originals (verified for the listContains and enums cases).

## 7. R10.9 RUN-record reproduction (P3-2d item 5)

Re-ran the K4 harness (riskiest module) from recorded seed `20260815` at the full
doubled budget: **3,531 compared / 0 divergences** — byte-identical to
`throwaway/b3-k4/RUN.md` §3 row 1. Harness provably calls the REAL entry points
on both sides (gen-cases.py imports `mixpanel_headless._internal.query.user_builders`;
entry.ts bundles `packages/core/src/query/user-builders.ts`). K1's recorded
15,389/1-disclosed, K2's 36,250/0, K3's 12,970/0 and the BIND bridge run
(seed 64091337, 9,395 ex, 0 div, probe 17/17 both bridges) are internally
consistent across RUN.md ↔ notes ↔ commit messages; K1's single divergence is
the disclosed K1-D1 (below), reproduced in the transcript.

## 8. Findings

### F1 (MAJOR, open-arbiter-item) — K1-D1 must be ruled before the gate flips `bookmark_schema.`

`B3-K1-notes.md:277-306` (and `throwaway/b3-k1/RUN.md` §6): mixed
integer-like/non-integer-like UNKNOWN keys on an `extra="forbid"` model emit
`extra_forbidden` in JS-object order, not Python insertion order (content
identical; order destroyed at `JSON.parse`/object-construction time — the same
engine limitation as ratified Discrepancy #9, at a NEW site). K1 correctly
refused to self-extend #9 and escalated; both the K1 harness and the (b′)
`bookmark_schema_family` exclude such inputs by construction. **Until the
arbiter rules (extend the sanctioned-deviation class or record a
permanently-disclosed divergence), this is an unratified fuzz-domain exclusion**
— the B3 gate should not close with K1-D1 unresolved. Recommended: bless as a
Discrepancy-#9-class deviation with the same "plain JS objects cannot hold
integer-like keys in insertion order" rationale, playbook discrepancy-log entry,
and re-examine trigger.

### F2 (minor, correctness-in-disclosed-branch) — `dictKeyText` float spelling uses `String()`, not the Python JSON spelling it claims

`packages/core/src/query/transforms.ts:154-156`: the TODO(port) docblock pins the
key spelling to "what any downstream encoder emits for the Python twin"
(`json.dumps`), but `String(floatCarrierValue(key))` / `String(key)` diverge from
`json.dumps`'s repr-based spelling for exponent-range floats
(`json.dumps({1e16: 1})` → `{"1e+16": 1}`; `String(1e16)` → `"10000000000000000"`).
Reachable only through the pathological `dict(iterable-of-pairs)` branch with a
float pair-key (fuzz never draws one; no Mixpanel response can produce one).
Fix is one line: route float(-carrier) keys through `pythonFloatStr`
(and non-float non-strings through `pythonStr`), matching the module's own
`pythonStrValue` idiom. Alternatively amend the docblock to disclose the
exponent-range deviation.

### F3 (minor, documentation) — the K1-D1 fuzz exclusion is not documented at the strategy site

`conformance/differential/strategies.py::_b3_schema_calls` draws extra keys from
`("zzz", "aaa", "b", <non-BMP>, "_idx")` — integer-like unknown keys are excluded
by construction, but unlike the B2 precedent (inline comment at
`strategies.py:2591-2594` for the S4/#9 exclusion) there is no comment in the
family explaining WHY, and the fullest rationale lives in
`throwaway/b3-k1/RUN.md`, which the gate deletes. `B3-K1-notes.md` retains the
arbiter item, so nothing is lost, but the strategy file is the designated home
for documented domain omissions (#8 pattern). Add the two-line comment when the
arbiter resolves F1.

### F4 (minor, stale notes) — `B3-K3-notes.md` §5 item 1 contradicts the shipped code

§5.1 says "The TS twin raises `TypeError` for every non-dict … `TODO(port)`
marker at the site", but the shipped `transforms.ts pythonDictCopy` reproduces
`dict(iterable-of-pairs)` branch-for-branch (per the same file's later
§probe-matrix section and the BIND commit's "dict(iterable-of-pairs) grammar
probed"). The §5.1 paragraph is a leftover from the pre-BIND state of the module.
Notes-only; update at the gate's notes-finalization step.

## 9. Checklist (final)

- [x] 299-vector replay re-run: 299/299 PASS @ corpus 70c904d
- [x] R10.2 census + spot-diffs across all ten translated test files — zero weakenings; adaptations all header-cited
- [x] No silently-skipped tests; deferrals verified against Python source and logged with owners (B5-S2)
- [x] TODO(port): 2 sites, both logged with owner notes
- [x] Binding honesty: 17/17 real entry points; sanctioned structural encodings only; no rig-verdict-path edits
- [x] Codes-not-messages: class+code asserted throughout; Python message-matches kept (verbatim) or upgraded to codes — never weakened
- [x] R4.8 / R11.7 / watchlist #2/#5/#7/#13 / R10.12 / R10.7 greps clean (F2 excepted)
- [x] Discrepancy #8 applied as ratified; #9 not extended (K1-D1 escalated properly)
- [x] RUN-record reproduction: K4 seed 20260815 reproduces exactly
