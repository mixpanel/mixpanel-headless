# B2 adversarial review — SEMANTIC FIDELITY lens (P3-2d)

**Status**: COMPLETE · 2026-08-15 · fable reviewer (adversarial pair, fidelity lens)
**Commits under review**: TS `5c0e032` (M1/V1a), `617da2b` (M2/V1b), `83fbe2d` (M3/V2),
`2015565` (B2-BIND); Python `748ff4e` (BIND strategies).
**Verdict: NO-GO as-is — 1 blocker class + 2 major classes + 1 minor, all
oracle-confirmed with repro inputs below.** The in-domain surface (690 vectors,
5,863-example BIND fuzz, three module harnesses) is genuinely clean and all RUN
records reproduce byte-exactly; every finding below lives in input territory the
fuzz domains structurally never generate.

## Method

- Rule-by-rule diff of `validation.py` (3,090; V1a ranges 91–2280, V1b ranges
  1767–3090) and `query/user_validators.py` (580, whole file) against
  `validation-shared.ts` / `validation-args.ts` / `validation-bookmark.ts` /
  `schema-sorting.ts` (skim + probe) / `user-validators.ts` (probe +
  targeted read) / `bindings.ts` `registerValidatorBindings`.
- Checked: emission order (incl. delegation order + the U29/U26-28
  interleavings), comparison operators, boundaries (3650/3651, 730, 1000/1001,
  0–5, 1–50, 366/52/12, second-window 0<w<2), watchlist-6 truthiness sites
  (B18 `pythonTruthy`, `if known:`, `if not steps`, `formulas or []`),
  R11.7 pythonStrip/pythonInt at all 14 measured `.strip()` sites + grep of the
  full B2 diff for `.trim(`/`parseInt(`/`Number(`/`JSON.parse`/`new Date(`,
  severity assignments (B7/B10/B13/B15/B16/B17/B19/S4 warning; rest error),
  float equality (no epsilon anywhere; `pythonEqualsNumber`, `_isFinite` exact).
- R10.9 harness re-runs from RUN-record seeds + fresh seeds (below).
- 95 adversarial spot inputs through oracle-py ↔ oracle-ts (`OracleProcess` +
  `encode_input_kwargs` + `_canonical_outcome`), scripts preserved at
  `/tmp/b2rev_spot.py`, `/tmp/b2rev_spot2.py`, `/tmp/b2rev_spot3.py`.

## Harness re-runs (P3-2d item 5 — all reproduce)

| Harness | Recorded seed | Result | Fresh seed | Result |
|---|---|---|---|---|
| `throwaway/b2-m1/run.sh` | 20260815/700 | 3,828 compared / 506 bilateral skips / **0 div** — matches RUN record exactly | 424242/700 | 3,886 / 448 / **0 div** |
| `throwaway/b2-m2/run.sh` | 20260815/600 | 1,921 / 8 skips / **0 div** — counts match; skip class is now BILATERAL ("ts threw + python errored") post-`2015565` requireHashable fix; RUN.md prose still describes the pre-fix unilateral class (stale, see minor finding F5) | 424242/600 | 1,926 / 3 / **0 div** |
| `throwaway/b2-m3/run.sh` | 20260815/700 | 1,510 / 0 / **0 div** — matches | 424242/700 | 1,510 / 0 / **0 div** |
| BIND `fuzz_harness` 11 families | 83155107/500 | status ok, **5,863 examples**, per-family counts byte-identical to B2-BIND notes, **0 div** | 971231/500 | ok, 5,863, **0 div** |

## Findings

### F1 (BLOCKER) — `isDict`/`isPlainObject` conflate PyFloat carriers and class instances with dicts (V1b)

Python's `isinstance(x, dict)` is False for floats and for core class
instances; the TS predicates (`validation-bookmark.ts:94-96` `isDict`,
`schema-sorting.ts` `isPlainObject`) return true for ANY non-array object —
including the rig's PyFloat carrier (`{spelling}`) and reconstructed core
instances (`Filter`, …). Eleven oracle-confirmed divergent shapes (all
`encode_input_kwargs`-shippable; `params: dict[str, Any]` makes every one
in-annotation):

| Input | Python | TS |
|---|---|---|
| `validate_bookmark params={"sections": 5.0, "displayOptions": {...}}` | `[B1_MISSING_SECTIONS]` | `[B3_MISSING_SHOW]` |
| `validate_sorting_block sorting=5.0` | `[S5_NOT_A_DICT]` | `[S4 warning @ sorting.spelling]` |
| `validate_bookmark …"sorting": 5.0` | `[S5_NOT_A_DICT]` | `[S4 @ sorting.spelling]` |
| `…sections.time=[5.0]` | `[B12_INVALID_TIME_UNIT]` | `[]` |
| `…sections.group=[5.0]` | `[B17_INVALID_PROPERTY_TYPE]` | `[]` |
| `…sections.filter=[Filter.equals("a","b")]` | `[B14_INVALID_FILTER_TYPE]` | `[B18_MISSING_FILTER_PROPERTY]` |
| `…show[0].behavior=5.0` | `[B6_MISSING_BEHAVIOR]` | `[]` |
| `…displayOptions=5.0` | `[]` (isinstance-dict gate skips) | `[B5_INVALID_CHART_TYPE]` |
| `validate_flow_bookmark steps=[5.0]` | `[]` (isinstance gate skips) | `[FLB2_EMPTY_STEP_EVENT]` |
| `sorting={"bar": 5.0}` | `[S5_NOT_A_DICT @ sorting.bar]` | `[S8, S2, S3 @ sorting.bar.spelling]` |
| `sorting={"table": {"sortBy":"column","colSortAttrs":[5.0]}}` | `[S5 @ …colSortAttrs[0]]` | `[S8, S9, S3 @ …spelling]` |

Two facets: (a) **library-level** — a real TS consumer putting a `Filter`
instance (or any class instance) at a dict position gets different codes than
the Python library; (b) **rig-level** — integral-float carriers at dict
positions (any `$type: float` value where Python holds a float and the source
does `isinstance(x, dict)`). The packet's own V1b language applies: the
sorting family is "B2's heaviest-fuzz surface — treat divergences as
findings…every unexplained one blocks". The module harness/fuzz missed this
because carrier edges were only placed at numeric-comparison positions and
`bookmark_family`/`sorting_family` never generate floats/instances at
dict-expected positions. Fix shape (module task, red-first): exclude
`isFloatCarrier` and non-`Object.prototype`-prototyped objects — exactly the
discrimination `requireHashable` (validation-shared.ts:275-291) already gets
right — in both `isDict` and `isPlainObject`; then extend
`bookmark_family`/`flow_bookmark_family`/`sorting_family` domains with
float/instance values at dict positions.

### F2 (MAJOR) — out-of-annotation scalars: CPython raises, TS returns (all three shards) — needs the arbiter's class ruling

Python's bare comparisons/attribute reads raise `TypeError`/`AttributeError`
on inputs outside the declared annotation; the TS port silently coerces (JS
`"a" <= 0` → false) or emits a code Python never reaches. 14 oracle-confirmed
instances (py outcome → ts outcome):

- V1a: `validate_time_args last="30"` → TypeError → `[]`; `last=None` →
  TypeError → `[V7]`; `validate_retention_args born_event=3` →
  AttributeError → `[R1_EMPTY_BORN_EVENT]`; `validate_flow_args forward="2"` /
  `cardinality="10"` → TypeError → `[]`; `validate_query_args rolling="7"` →
  TypeError → `[]`.
- V1b: `validate_bookmark params=5.0` → TypeError (`"sections" not in 5.0`) →
  `[B1, B2]`; `validate_flow_bookmark params=5.0` → AttributeError → `[FLB1,
  FLB5, FLB6]`; `validate_user_params params=5.0` → TypeError → `[]`.
- V2: `limit="5"` / `workers="3"` / `percentile="50"` /
  `segment_by=["a", 3, True]` → TypeError → `[]`; `distinct_ids=7` →
  TypeError (`len(7)`) → `[]`; `properties=["ok", 3]` → AttributeError →
  `[U11]`; `sort_by=3` → AttributeError → `[U5]`; `properties=[None]` →
  AttributeError → thrown TypeError (wrong class).

Contrast: funnel `conversion_window="7"` matches (both `F3_CONVERSION_WINDOW_TYPE`)
because Python has an isinstance guard there — the divergent sites are exactly
the guard-free comparisons. Why this is not automatically dismissible as
out-of-contract: (i) the standing R10.7 adjudication at B2-BIND
(requireHashable, fixed at 16 sites) ruled "Python's raise is the contract"
for the same kind of hostile input; (ii) the packet's R10.10 ergonomics note
makes the validators "the type police" for raw user input forwarded by the B5
facade — a Python user gets a TypeError from `ws.query_user(limit="5")`
where a TS user gets silent acceptance; (iii) only ONE member of this class
(`workers=None`, B2-M3 notes) was documented as a known boundary — the other
14+ sites are neither emulated nor documented, and the fuzz domains are
in-annotation by construction (verified: `_b2_user_args` `segment_by` pool is
numeric-only), so the 0-divergence records cannot speak to it. Disposition
needed from the arbiter: either (a) raise-emulation at the guard-free
comparison/`.strip()`/`len()` sites (requireHashable pattern), or (b) a
playbook Discrepancy entry blessing the WHOLE class with an explicit
fuzz-domain constraint note superseding the single workers=None mention —
today's state (one documented member, 14 silent members, one contradictory
prior adjudication) fails binding honesty of the record, not of the code.

### F3 (MAJOR) — CM5 mis-spelled: `typeof item.cohort !== "number"` vs `isinstance(item.cohort, CohortDefinition)` (V1a)

`validation-args.ts:1505-1517` emits `CM5_INLINE_COHORT_METRIC` for ANY
non-number cohort; Python (`validation.py:1967-1981`) only for
`CohortDefinition`. Both languages' `CohortMetric` ctor guards accept
`cohort=True` (Python: `isinstance(True, int) and True <= 0` is False —
`types.py:9148`; TS `isPyInt(true)` is false — `guards.ts:124`), so the
instance is constructible and shippable. Oracle-confirmed ×2:
`validate_query_args(events=[CohortMetric(cohort=True)])` → py `[]`, ts
`[CM5 @ events[0]]`; same with a mixed list → py `[]`, ts `[CM5 @ events[1]]`.
A float cohort (`CohortMetric(cohort=5.0)` — also ctor-accepted; decodes to a
carrier in TS) hits the same wrong branch. Fix: spell it
`item.cohort instanceof CohortDefinition` — identical dead-code status to
CPython (both ctors raise CM5 for real inline definitions), which is exactly
what the adjacent comment claims but the code does not implement.

### F4 (MINOR) — S4 warning emission order flips for integer-like unknown chart-type keys (V1b)

`validateSortingBlock` iterates `Object.entries(sorting)` — JS orders
integer-like keys first; Python iterates insertion order. Oracle-confirmed:
`sorting={"zzz": {}, "1": {}}` → py `[S4 @ sorting.zzz, S4 @ sorting.1]`, ts
`[S4 @ sorting.1, S4 @ sorting.zzz]`. Emission order is contract (packet
Cautions §11). B2-M2 notes finding 4 claimed the S4 pre-filter makes key
ordering unreachable — true for the model walk over `known` (valid chart types
are never integer-like), false for the S4 loop itself. Caveat for the fix
discussion: the insertion order is already destroyed by `JSON.parse` at vector
decode (JS objects cannot hold integer-like keys in insertion order), so full
fidelity needs an ordered-map decode path — likely a documented-discrepancy
candidate rather than a code fix; the arbiter should bless it explicitly
either way and add the integer-like-key case to the fuzz-domain omission notes.

### F5 (MINOR) — stale RUN-record prose in `throwaway/b2-m2/RUN.md`

The recorded-seed skip class changed meaning after `2015565` (requireHashable):
the 8 skips at seed 20260815 are now BILATERAL ("ts threw + python errored"),
but RUN.md still describes the pre-fix unilateral "TS returned B9" class, and
the M2 notes' open-item 1 ("every skip must be the TypeError class") reads
ambiguously against it. One-paragraph doc fix at the gate (before `throwaway/`
deletion, update the notes file instead).

## Observations (no action required)

- `vector-codecs.ts:434` uses `Number(spelling)` in the GroupBy carrier unwrap
  with an inline "rig-internal exemption" citing the SignedReplay precedent;
  behaviorally safe for codec-canonical spellings (`Infinity`/`-Infinity`/`NaN`
  parse identically), but the arbiter may want `pythonFloat` for
  letter-of-R11.7 consistency.
- CP4/CP6 error ORDER under integer-like `InlineCustomProperty.inputs` keys
  differs (Object.keys) but is unobservable — the divergent entries carry
  identical `{path, code, severity}` triples.
- `user-validators.ts` `defaultToday()` reads `new Date()` — clock READ, never
  parse; documented and correct (watchlist #5).
- R11.7 grep over the full B2 diff: zero forbidden call sites outside the two
  documented carve-outs (pydantic-core `pydanticTrim`/ASCII `\d` grammar with
  third-parser citation; the vector-codecs exemption above). All 14 measured
  `.strip()` sites use `pythonStrip`.
- Verified faithful under adversarial probing (49 + 28 + 13 + 3 = 93 spot
  cases, the rest OK): V15 codepoint date compare incl. non-BMP/fullwidth
  digits and trailing-`\n` `$` semantics; V19 multi-position formulas + the
  27-event `max_letter` overflow; V20/B21/R5c/FL3-FL7 boundaries; F7 second
  window; F3/DG1/B18B bool-before-int; B22's deliberate bool-INCLUSIVE int
  check (`id=True` valid, `id=False` → B22 — both match); B18 truthiness with
  a 0.0 carrier; B25 tuple membership (no spurious requireHashable); FLB6
  `pythonEqualsNumber`; difflib port internals (SequenceMatcher chain/autojunk/
  quick-ratio bookkeeping/nlargest tie order all verbatim vs CPython 3.14);
  U-code emission order incl. U29 and U26-28 interleavings; as_of grammar
  corners (compact/Arabic-Indic/trailing-newline all U6) and the frozen-clock
  U8 boundary (2026-01-15 no-error / 16 U8); UP1 tuple membership with a list;
  UP2 early return + `NaN`/`Infinity` JSON constants via parseLossless;
  UP4 `_ACTION_RE` corners (`count()\n` ok, `count()\r` UP4, greedy backtrack).
- Binding honesty (fidelity view): `registerValidatorBindings` calls the real
  entry points; unwrap table matches the M1/M3 measurements exactly
  (funnel `conversion_window`, `bucket_sizes[i]`, `data_group_id`, `cohort`,
  `as_of`, bookmark params all keep carriers; `last`/`rolling`/flow numerics/
  `limit`/`percentile`/`workers`/`segment_by[i]` unwrap); `today` seam from
  `context.shims`; output encoder is the strict `{path, code, severity}` twin.

## Why the clean fuzz records and these findings coexist

All four code findings live in inputs the strategies never generate: floats or
class instances at dict-typed positions (F1), scalars outside the annotation
(F2), a bool/float cohort inside a `CohortMetric` (F3 — the strategy only
builds `CohortMetric(cohort=42)`), integer-like unknown chart keys (F4). The
recorded 0-divergence results are honest for their domains; the domains encode
the same in-annotation assumption the port silently baked in.
