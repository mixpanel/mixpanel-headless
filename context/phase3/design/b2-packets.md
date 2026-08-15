# B2 design-lite packets — validators (P3-6 step 1)

**Status**: v1.0 · 2026-08-15 · fable design-lite packet for batch B2 (playbook P3-6 step 1,
sharding per P3-6 "B2 (3 tasks, sonnet)"). Location note: the orchestrator task names
`context/phase3/design/b2-packets.md`; the playbook's generic path is
`context/phase3/packets/BX-packets.md` — this file is the packet of record for B2.
Every count below was measured 2026-08-15 against corpus pin `b5c1369`
(`conformance-runner/corpus.config.json`) and Python source at support-branch HEAD.

**Shard map (counts sum to exactly 690):**

| Shard | Task | Scope | Vectors |
|---|---|---|---|
| V1a | sonnet | `validation.py` argument-validator half (Layer 1 + shared helpers) | **372** |
| V1b | sonnet | `validation.py` bookmark half (Layer 2) + sorting slice + `validate_bookmark` export + `enums.ts` TODO closure | **140** |
| V2 | sonnet | `query/user_validators.py` | **178** |
| (b′) | fable | binding + oracle-ts registration for all three shards | — |
| Σ | | | **690** |

Execution order: **V1a → V1b** (V1b imports V1a's shared helpers and both extend the same
barrel); **V2 in parallel with either** (disjoint files). The fable binding task (b′) runs
after each module task lands (may be one combined task after all three, or per-shard —
orchestrator's choice; vector failures at (b′) are the MODULE task's attempt-1 failure,
P3-6 step 3).

Corpus location (all 690): `conformance-runner/corpus/validation/*.jsonl` (10 files) +
`conformance-runner/corpus/authored/validation/uncovered-codes.jsonl` (10 vectors).
Replay filter: every B2 vector id starts `validation/` (capability directory) —
`npm run conformance -- --filter validation/`.

Measured per-api vector counts (sums: `validation.` = 512, `user_validators.` = 178):

| api | vectors | shard |
|---|---|---|
| `validation.validate_time_args` | 12 | V1a |
| `validation.validate_group_by_args` | 8 | V1a |
| `validation.validate_query_args` | 39 | V1a |
| `validation.validate_funnel_args` | 117 | V1a |
| `validation.validate_retention_args` | 107 | V1a |
| `validation.validate_flow_args` | 89 | V1a |
| `validation.validate_flow_bookmark` | 30 | V1b |
| `validation.validate_bookmark` | 110 | V1b |
| `validation.validate_sorting_block` | 0 (registry entry exists; oracle-probe-only) | V1b |
| `user_validators.validate_user_args` | 143 | V2 |
| `user_validators.validate_user_params` | 35 | V2 |

**Expectation-shape measurement (corrects the playbook B2 row's wording):** ALL 690
vectors are `kind: "builder"` (680 extracted + 10 authored `uncovered-codes`) and ALL
690 carry `expect.output` — **zero B2 vectors use `expect.error`**.
These validators are total functions returning `list[ValidationError]`; the "error cases"
ARE the returned list, serialized structurally as `[{code, path, severity}]` (recorder
codec `validation_errors`, `conformance/record/codecs.py:720-748`). The
raised-`BookmarkValidationError` `expect.error` shape exists in the corpus only on the B5
consumers (`workspace.build_*params`, `kind: "validation-error"`). Both shapes are
specified in §Binding-plan below.

---

## Packet V1a — argument validators (Layer 1)

**Model**: sonnet, effort ≤ high, R10.13 incremental protocol. **Vectors: 372.**

### Python sources (re-read every range before porting; line numbers at support-branch HEAD)

`src/mixpanel_headless/_internal/validation.py` (3,090 LOC total; V1a owns ≈2,170):

| Range | Contents |
|---|---|
| 1–90 | module docstring + imports (enum tables from `bookmark_enums`, literal types) |
| 91–338 | custom-property scan: `_CP_INPUT_KEY_RE`, `_CP_MAX_FORMULA_LENGTH` (20_000), `_validate_custom_property` (95–188, CP1–CP6), `_scan_filters_for_custom_properties` (191–215), `_scan_custom_properties` (218–335) |
| 341–402 | shared tables/helpers: `_DATE_RE`, `_FORMULA_POSITION_RE`, `_CONTROL_CHAR_RE`, `contains_control_chars` (346–360), `_INVISIBLE_RE` (363), `_MAX_LAST_DAYS`=3650, `_MAX_ROLLING`=365, `_MAX_FILTER_VALUES`=1000, `_is_valid_date` (369–384), `_is_finite` (387–402) |
| 405–464 | fuzzy helpers: `_suggest` (410–428, `difflib.get_close_matches` over `sorted(valid)`, n=3, cutoff=0.5), `_enum_error` (431–464) |
| 467–773 | reusable sub-validators: `_validate_data_group_id` (472–508, DG1), `validate_time_args` (511–647), `validate_group_by_args` (650–771) |
| 774–1157 | `validate_funnel_args` (779–1155, F1–F12 + V-code reuse) |
| 1158–1479 | `validate_retention_args` (1179–1477, R1–R13 + CB3) — incl. `_MAX_RETENTION_BUCKETS`=730 |
| 1480–1766 | `validate_flow_args` (1498–1764, FL1–FL10 + FL_* enums) — incl. `_MAX_FLOW_STEPS_DIRECTION`=5, `_MAX_FLOW_CARDINALITY`=50 |
| 1880–2282 | `validate_query_args` (1885–2280, V0–V27 Layer 1) |

Internal call graph (measured; port as calls, never duplication): every composite
validator delegates — `validate_funnel_args` → `_validate_data_group_id` (:851),
`validate_time_args` (:1132), `validate_group_by_args` (:1135), `_scan_custom_properties`
(:1138); retention → same set (:1248, :1311, :1314, :1457); flow → `_validate_data_group_id`
(:1565), `validate_time_args` (:1762); query_args → `_validate_data_group_id` (:1936),
`validate_time_args` (:2177), `validate_group_by_args` (:2180), `_scan_custom_properties`
(:2184).

### TS homes

- `packages/core/src/query/validation-shared.ts` — CP scan, control/invisible-char checks,
  `_is_valid_date`, `_is_finite`, `_suggest`/`getCloseMatches`, `_enum_error`,
  `_validate_data_group_id`, module constants. (Internal module; not in the package barrel.)
- `packages/core/src/query/validation-args.ts` — the six exported validators.
- `packages/core/src/query/validation.ts` — barrel matching the playbook home name;
  V1a creates it re-exporting the six Layer-1 validators; V1b extends it.
- `packages/core/src/query/index.ts` — replace the Phase-2 placeholder `export {}` with
  the internal module exports (still NOT re-exported from `packages/core/src/index.ts`
  except `validate_bookmark`, which is V1b's job).
- Enum tables: IMPORT from `packages/core/src/bookmarks/enums.ts` (ReadonlySet/ReadonlyMap,
  landed P2-3) — never re-declare (R10.8 discipline applies to tables too).
- Compat: IMPORT `pythonStrip`, `pythonInt`, `cpLength`, `cpSlice`, `sortedByCodepoint`
  from `packages/core/src/compat/index.js` (R10.8/R11.7 — never re-derive).

### TS signatures (kwargs-bag pattern; Python is all-kwonly, R3.9/R4.10)

Python signatures of record (paste from `ast` sweep 2026-08-15):

```
validate_time_args(*, from_date, to_date, last) -> list[ValidationError]
validate_group_by_args(*, group_by) -> list[ValidationError]
validate_funnel_args(*, steps, conversion_window, conversion_window_unit, math,
    math_property, exclusions, holding_constant, from_date, to_date, last, group_by,
    reentry_mode, data_group_id) -> list[ValidationError]
validate_retention_args(*, born_event, return_event, retention_unit, alignment,
    bucket_sizes, math, mode, unit, from_date, to_date, last, group_by, unbounded_mode,
    data_group_id) -> list[ValidationError]
validate_flow_args(*, steps, forward, reverse, count_type, mode, cardinality,
    conversion_window, conversion_window_unit, from_date, to_date, last,
    time_comparison, data_group_id) -> list[ValidationError]
validate_query_args(*, events, math, math_property, per_user, percentile_value,
    from_date, to_date, last, has_formula, rolling, cumulative, group_by, formulas,
    data_group_id) -> list[ValidationError]
```

TS: one options-object parameter per validator, `ValidationError[]` return
(`ValidationError` from `packages/core/src/errors.ts:1179` — already ported, positional
ctor `(path, message, code, severity, suggestion, fix)`). Python `None` defaults →
`null`; absent keys and `null` are equivalent wherever Python's default is `None`
(document any site where they differ — none found on read).

### Rule codes owned (V1a)

**Corpus-present** (enumerate = the shard's minimum PASS surface; measured from the 372
vectors' `expect.output[].code`):
- `validate_time_args`: V7_LAST_POSITIVE, V8_DATE_FORMAT, V8_DATE_INVALID,
  V9_TO_REQUIRES_FROM, V10_DATE_LAST_EXCLUSIVE, V15_DATE_ORDER, V20_LAST_TOO_LARGE
- `validate_group_by_args`: V11_BUCKET_REQUIRES_SIZE, V12B_BUCKET_REQUIRES_NUMBER,
  V12C_BUCKET_REQUIRES_BOUNDS
- `validate_query_args`: V0_NO_EVENTS, V1_MATH_REQUIRES_PROPERTY, V2_MATH_REJECTS_PROPERTY,
  V3_PER_USER_INCOMPATIBLE, V3B_PER_USER_REQUIRES_PROPERTY, V4_FORMULA_MIN_EVENTS,
  V5_ROLLING_CUMULATIVE_EXCLUSIVE, V6_ROLLING_POSITIVE, V7/V8/V9 (shared),
  V10_DATE_LAST_EXCLUSIVE, V11/V12B (shared), V16_FORMULA_SYNTAX, V21_INVALID_EVENT_TYPE,
  V23_ROLLING_TOO_LARGE, DG1_INVALID_DATA_GROUP_ID
- `validate_funnel_args`: F1_MIN_STEPS, F1_MAX_STEPS, F2_EMPTY_STEP_EVENT,
  F2_CONTROL_CHAR_STEP_EVENT, F2_INVISIBLE_STEP_EVENT, F3_CONVERSION_WINDOW_POSITIVE,
  F3_CONVERSION_WINDOW_MAX, F3_CONVERSION_WINDOW_TYPE, F4_EXCLUSION_STEP_BOUNDS,
  F4_EXCLUSION_STEP_ORDER, F7_INVALID_WINDOW_UNIT, F7_SECOND_MIN_WINDOW,
  F8_MAX_HOLDING_CONSTANT, F9_SESSION_WINDOW_REQUIRES_ONE,
  F9_SESSION_MATH_REQUIRES_SESSION_WINDOW, F10_MATH_MISSING_PROPERTY,
  F11_MATH_REJECTS_PROPERTY, F12_INVALID_REENTRY_MODE, V7/V8/V9/V15/V12B, DG1
- `validate_retention_args`: R1_{EMPTY,CONTROL_CHAR,INVISIBLE}_BORN_EVENT,
  R2_{EMPTY,CONTROL_CHAR,INVISIBLE}_RETURN_EVENT, R5_BUCKET_SIZES_{INTEGER,POSITIVE,TOO_MANY},
  R6_BUCKET_SIZES_ASCENDING, R7_INVALID_RETENTION_UNIT, R8_INVALID_ALIGNMENT,
  R9_INVALID_MATH, R10_INVALID_MODE, R11_INVALID_UNIT, R12_EMPTY_GROUP_BY,
  R13_INVALID_UNBOUNDED_MODE, CB3_RETENTION_MIXED_BREAKDOWN, V7/V8/V9/V15, DG1
- `validate_flow_args`: FL1_EMPTY_STEPS, FL2_{EMPTY,CONTROL_CHAR,INVISIBLE}_STEP_EVENT,
  FL3_FORWARD_RANGE, FL4_REVERSE_RANGE, FL5_NO_DIRECTION, FL6_CARDINALITY_RANGE,
  FL7_CONVERSION_WINDOW_{POSITIVE,MAX}, FL9_SESSION_REQUIRES_SESSION_WINDOW,
  FL10_SESSION_WINDOW_REQUIRES_ONE, FL_INVALID_COUNT_TYPE, FL_INVALID_MODE,
  FL_INVALID_WINDOW_UNIT, FL_TIME_COMPARISON_NOT_SUPPORTED, V7/V8/V9, DG1

**Source-present but NOT corpus-exercised** (the R10.9 harness MUST cover every one —
"every error branch = every code"): V12_BUCKET_SIZE_POSITIVE, V13_METRIC_MATH_PROPERTY,
V14_METRIC_REJECTS_PROPERTY, V17_EMPTY_EVENT, V18_BUCKET_ORDER, V19_FORMULA_BOUNDS
(corpus-present only via B5 `workspace.build_params` error vectors), V22_CONTROL_CHAR_EVENT,
V22_INVISIBLE_EVENT, V24_BUCKET_NOT_FINITE, V26_PERCENTILE_REQUIRES_VALUE,
V27_HISTOGRAM_REQUIRES_PER_USER, CM5_INLINE_COHORT_METRIC, CP1_INVALID_ID,
CP2_EMPTY_FORMULA, CP3_EMPTY_INPUTS, CP4_INVALID_INPUT_KEY, CP5_FORMULA_TOO_LONG,
CP6_EMPTY_INPUT_NAME, F4_CONTROL_CHAR_EXCLUSION, F4_EMPTY_EXCLUSION_EVENT,
F4_EXCLUSION_NEGATIVE_STEP, F8_EMPTY_HOLDING_CONSTANT_PROPERTY.

**Doc-only families**: the module docstring advertises CF1–CF2, CB1–CB2, CM1–CM4 — those
rules are enforced by the Phase-2 `types.py` constructor guards (already ported and
vector-locked), NOT emitted by this module. Only CB3 and CM5 are literal codes here. Do
not invent branches for the others.

### Layer-3 test translation (V1a)

Vitest + fast-check, colocated under `packages/core/src/query/`; one TS file per Python
file with a header citing the source; classes that drive `workspace.build_*params` (a B5
member) instead of calling validators directly are EXCLUDED with a file-header design
citation ("B5 facade scope — translated with the B5 S2 shard", phase2-audit A2 style):

| Python source | Translate now | Defer note |
|---|---|---|
| `tests/unit/test_query_validation.py` (827) | validator-direct classes (validate_time_args ×17, group_by ×13, query_args ×9 refs) | `TestBuildParamsValidation` etc. (15 `build_params` refs) → B5 |
| `tests/unit/test_query_validation_pbt.py` (237) | all (fast-check twins, same strategy shapes) | — |
| `tests/unit/test_validation_pbt.py` (373) | time-args + custom-property PBT | — |
| `tests/unit/test_validation.py` (1238) | the validate_query_args classes (32 refs) → `validation-args.test.ts` | validate_bookmark classes (59 refs) → V1b |
| `tests/test_validation_funnel.py` (1373) | all | — |
| `tests/test_validation_retention.py` (1087) | all | — |
| `tests/test_validation_flow.py` (1066) | validate_flow_args classes | FLB classes → V1b |
| `tests/test_validation_cohort.py` (504) | validate_retention_args classes (9 refs) | validate_bookmark cohort classes → V1b |

R10.2: never weaken an assertion. Suggestion-content asserts (e.g.
`test_validation_funnel.py:838-846` asserts `"hour" in f7[0].suggestion`;
`test_validation_retention.py:273-279` asserts `"week"`) translate VERBATIM — see
Cautions §difflib. Message-text asserts: R5.4 places message text out of contract;
where a Python test asserts message substrings, port the message string faithfully and
keep the assert (cheapest honest option), or drop it WITH a file-header R5.4 citation —
never silently.

### R10.10 consumer packet (V1a)

Measured importers of `_internal/validation.py`: `workspace.py` + the public
`__init__.py` export ONLY. **Correction to the playbook B2 row**: `bookmark_builders.py`
does NOT call these validators (grep 2026-08-15: zero hits) — the B3 dependency on B2 is
the enums-TODO closure and shared helpers, not validator calls.

Consumer call sites (B5 shard S2 / B6, signatures from api-map, pasted per P3-1):

- `workspace.query` → `validate_query_args(...)` at `workspace.py:2693`, then
  `validate_bookmark(params)` at `:2736`; raises `BookmarkValidationError(errors)` when
  any severity=="error".
- `workspace.funnel` → `validate_funnel_args(...)` `:3015` + `validate_bookmark(params,
  bookmark_type="funnels")` `:3058`.
- `workspace.flow` → `validate_flow_args(...)` `:3807` + `validate_flow_bookmark(params)`
  `:3846`.
- `workspace.retention` → `validate_retention_args(...)` `:4171` + `validate_bookmark(params,
  bookmark_type="retention")` `:4219`.
- The five B5 builder members (api-map rows, verbatim):

```json
{"name":"build_params","params":["events"],"kwonly":["from_date","to_date","last","unit","math","math_property","per_user","percentile_value","group_by","where","formula","formula_label","rolling","cumulative","mode","time_comparison","data_group_id"],"returns":"dict[str, Any]","batch":"B5","ts_signature":"async build_params(events, from_date, to_date, …): Promise<Record<string, unknown>>"}
{"name":"build_funnel_params","params":["steps"],"kwonly":["conversion_window","conversion_window_unit","order","from_date","to_date","last","unit","math","math_property","group_by","where","exclusions","holding_constant","mode","reentry_mode","time_comparison","data_group_id"],"returns":"dict[str, Any]"}
{"name":"build_flow_params","params":["event"],"kwonly":["forward","reverse","from_date","to_date","last","conversion_window","conversion_window_unit","count_type","cardinality","collapse_repeated","hidden_events","mode","where","data_group_id","segments","exclusions"],"returns":"dict[str, Any]"}
{"name":"build_retention_params","params":["born_event","return_event"],"kwonly":["retention_unit","alignment","bucket_sizes","from_date","to_date","last","unit","math","group_by","where","mode","unbounded_mode","retention_cumulative","time_comparison","data_group_id"],"returns":"dict[str, Any]"}
{"name":"build_user_params","params":[],"kwonly":["where","cohort","properties","sort_by","sort_order","search","distinct_id","distinct_ids","group_id","as_of","mode","aggregate","aggregate_property","percentile","segment_by","limit","parallel","workers","include_all_users"],"returns":"dict[str, Any]"}
```

Ergonomics consequence (R10.10): validators accept exactly the loosely-typed values the
facade forwards (e.g. `steps: unknown[]`-shaped input where Python accepts heterogenous
lists and type-checks per element) — do NOT tighten TS parameter types to the point that
the B5 facade cannot forward raw user input for validation (the validators ARE the type
police; `unknown`-leaning input types + narrowing inside, R4.9).

### R10.9 harness spec (V1a)

Throwaway harness in `throwaway/` inside the module commit; RUN record (counts, seeds,
divergence table) appended to `context/phase3/notes/B2-notes.md`; the review pair re-runs
from recorded seeds; the batch gate deletes `throwaway/`.

- **Oracle families** (extend `conformance/differential/strategies.py` — Python-side
  commit, `uv`, `just check`): the existing `validators_by_code` target drives ONLY
  `validation.validate_time_args` (:211-270). Add fuzz targets `group_by_args_family`,
  `query_args_family`, `funnel_args_family`, `retention_args_family`, `flow_args_family`
  — ≥500 examples per family (P2-9 budget), strategy shapes biased to the input domains
  (dates via the existing `_DATE_ARGS` mix, enum near-misses for every `_enum_error`
  site, control/invisible/non-BMP event names, bucket lists with bools/floats/negatives/
  descending, formula strings for V16/V19, CustomPropertyRef instances for the CP scan).
  Oracle-py answers these apis already (registry `_validator_entries()`); oracle-ts gains
  them via the (b′) binding commit BEFORE the harness runs.
- **Mandatory edge set per api** (verbatim from R10.9): integral float `18.0` (arrives as
  the PyFloat carrier — see Cautions §int/float), fractional `1.5`, `True`, `None`, empty
  list, empty string, non-BMP string `"𝒳"`, and **every code in the V1a inventory above**
  (corpus-present AND source-only lists) — one explicit edge call per code, per the
  `validators_by_code` precedent comment (:253-257). Where an edge item is outside a
  validator's typed input domain, document the omission in the edge-call comment exactly
  as `strategies.py:253-257` does.
- Zero unexplained divergences; shrunken repros to `conformance/differential/repros/`
  block the task.

### Done-criteria (V1a)

TS files on disk; `tsc --strict` clean; translated tests green; after (b′): all 372
V1a vectors PASS, 0 FAIL (batch-status stays `pending` until the gate — PASS is visible
without a flip); R10.9 RUN record in the notes file; `npm run check` green;
`just check` green (strategies.py changed); one commit per repo; local commits only.

## Packet V1b — bookmark validators (Layer 2) + sorting slice

**Model**: sonnet, effort ≤ high. **Vectors: 140** (110 `validate_bookmark` + 30
`validate_flow_bookmark` + 0 `validate_sorting_block`). Runs AFTER V1a (imports
`validation-shared.ts` helpers `_enum_error`/`_suggest`/`_is_finite`/
`contains_control_chars` and extends the `validation.ts` barrel).

### Python sources

`src/mixpanel_headless/_internal/validation.py` (V1b owns ≈920 LOC):

| Range | Contents |
|---|---|
| 1767–1879 | `validate_flow_bookmark` (1772–1877, FLB1–FLB6) |
| 2283–2417 | `validate_bookmark` (2288–2415, B1–B26 dispatch; `bookmark_type` kwonly, default `"insights"`; routes `params["sorting"]` → `validate_sorting_block` at :2413) |
| 2418–3020 | Layer-2 sub-validators: `_validate_show_clause` (2423–2586), `_validate_measurement` (2589–2686), `_validate_display_options` (2689–2723), `_validate_time_clause` (2726–2783), `_validate_filter_clause` (2786–2950, incl. B18B/B20/B20B/B21 + cohort checks B22–B26), `_validate_group_clause` (2953–3018) |
| 3021–3090 | `validate_sorting_block` (3036–3090, S4/S5 pre-filter + pydantic delegation) |

**Cross-batch dependency slice (measured — the ONE hard problem of B2):**
`validate_sorting_block` calls `validate_with_pydantic(InsightsBookmarkSortConfig,
known, path_prefix="sorting", code_mapper=_sorting_code_mapper)`
(`validation.py:3082-3087`), importing from `_internal/bookmark_schema.py` — a **B3-K1
module**. 31 corpus vectors (`validate_bookmark`/`validate_query_args` inputs carrying
`sorting`) exercise it; codes S1–S9 all appear in `validate_bookmark` expectations, so
the B2 gate flip of the `validation.` prefix CANNOT succeed without this slice. Required
`bookmark_schema.py` ranges:

- 61–316: pydantic-error adapter — `_DEFAULT_CODE_MAP` (:71), `_default_code_mapper`
  (:110), `_sorting_code_mapper` (:124-167), `validate_with_pydantic` (:170-221),
  `_translate_pydantic_error` (:223-254), `_DISCRIMINATOR_TAGS` (:257-272),
  `_loc_to_jsonpath` (:274-316).
- 372–680: sorting models — `SortOrderLiteral`/`SortByLiteral`, `FlatLabelSortConfig`
  (:390), `FlatValueSortConfig` (:404), `_flat_sort_discriminator` (:425),
  `SortByColumnsConfig` (:455), `SortByValueConfig` (:477), `_sort_config_discriminator`
  (:500), `OldTableSortByValue` (:530), `_flat_or_column_sort_discriminator` (:547),
  `FlatOrColumnSortConfig` (:600), `_table_sort_discriminator` (:609), `TableSortConfig`
  (:640), `InsightsBookmarkSortConfig` (:648-680; kebab-case aliases via
  `alias_generator`, `populate_by_name`, `extra="forbid"`).

**R10.8 ownership decision (binding)**: V1b ports this slice ONCE into
`packages/core/src/bookmarks/schema-sorting.ts` (a `bookmark_schema`-owned TS home) as a
hand-rolled structural validator that reproduces pydantic v2 `model_validate(...).errors()`
for THESE models only — error `type` strings, `loc` tuples (Tag names included, then
filtered by the `_DISCRIMINATOR_TAGS` port), **emission order and multiplicity** — then
maps through the ported `sortingCodeMapper`. B3-K1 IMPORTS and extends this file; it never
re-implements the sorting models or the adapter. Put a header note naming B3-K1 as the
file's grower. TS has no pydantic: the module must state at the top (R11.7 third-parser
carve-out) that its reference semantics are pydantic-core, and cite probe evidence.

**Mandatory probe before implementing**: a throwaway CPython script (uv) driving
`validate_sorting_block` across every S-code branch AND the fallthrough branches
(`string_type` on `valueField` → B0_WRONG_TYPE, unmapped type → VALIDATION_ERROR),
recording pydantic's error ORDER for multi-error inputs (e.g. two bad chart-type configs;
one config with both missing `sortOrder` and unknown key). Lock the observed order in
Layer-3 tests. Pydantic-core is lax-coercion by default unless `_BASE_CONFIG` says
otherwise — READ `_BASE_CONFIG` (`bookmark_schema.py` head) first and mirror its
strict/lax mode; where lax coercion applies, use/extend the existing shared `coerce`
module semantics (R4.12) and heed the B2-HK-notes coerce.ts flag (pydantic trim ≠
`str.strip()` ≠ `.trim()` — FEFF-prefixed numeric strings are the known divergence
direction; the B2 review pair must check any coerce path a sorting vector touches).

### TS homes

- `packages/core/src/query/validation-bookmark.ts` — `validate_flow_bookmark`,
  `validate_bookmark`, the six `_validate_*` clause helpers, `validate_sorting_block`.
- `packages/core/src/bookmarks/schema-sorting.ts` — the bookmark_schema slice (above).
- `packages/core/src/bookmarks/enums.ts` — CLOSE the `TODO(port)` at :26-29: add
  module-private `_MAX_FUNNEL_STEPS = 100` and `_MAX_HOLDING_CONSTANT = 3` (exported for
  intra-package use, not in the package barrel; consumed by V1a's funnel validator F1/F8 —
  coordinate: V1a may land them if it reaches F1 first; exactly ONE task adds them, the
  other imports; V1b owns the TODO-comment removal either way).
- `packages/core/src/index.ts` — add the deferred public export `validate_bookmark`
  (phase2-audit A1 deferral, owner B2; Python: `__init__.py:9`, `__all__` entry
  `"validate_bookmark"`).
- Extend the `query/validation.ts` barrel with the V1b exports.

### Rule codes owned (V1b)

**Corpus-present** (`validate_bookmark`, 110 vectors): B1_MISSING_SECTIONS,
B2_MISSING_DISPLAY_OPTIONS, B3_MISSING_SHOW, B4_SHOW_EMPTY, B5_INVALID_CHART_TYPE,
B6_MISSING_BEHAVIOR, B7_INVALID_BEHAVIOR_TYPE, B8_MISSING_EVENT_NAME, B9_INVALID_MATH,
B10_MATH_MISSING_PROPERTY, B11_INVALID_PER_USER, B12_INVALID_TIME_UNIT,
B13_INVALID_DATE_RANGE_TYPE, B14_INVALID_FILTER_TYPE, B15_INVALID_FILTER_OPERATOR,
B16_INVALID_RESOURCE_TYPE, B17_INVALID_PROPERTY_TYPE, B18_MISSING_FILTER_PROPERTY,
B18B_INVALID_CP_ID, B19_INVALID_FILTERS_DETERMINER, B20_EMPTY_FILTER_VALUE,
B20B_FILTER_VALUE_NOT_FINITE, B21_FILTER_VALUE_TOO_MANY, B22_COHORT_BEHAVIOR_ID,
B22_COHORT_MISSING_IDENTIFIER, B23_COHORT_RESOURCE_TYPE, B24_COHORT_MATH,
B25_COHORT_FILTER_VALUE, B26_EMPTY_COHORTS, and the sorting set S1_INVALID_SORT_BY,
S2_MISSING_COL_SORT_ATTRS, S3_UNKNOWN_FIELD, S4_UNKNOWN_CHART_TYPE (severity
**warning**), S5_NOT_A_DICT, S6_INVALID_SORT_ORDER, S7_NOT_A_LIST, S8_MISSING_SORT_BY,
S9_MISSING_SORT_ORDER. (`validate_flow_bookmark`, 30 vectors): FLB1_EMPTY_STEPS,
FLB2_EMPTY_STEP_EVENT, FLB3_INVALID_COUNT_TYPE, FLB4_INVALID_CHART_TYPE,
FLB5_MISSING_DATE_RANGE, FLB6_INVALID_VERSION.

**Source-present, corpus-silent** (harness must cover): the sorting fallbacks
B0_MISSING_FIELD, B0_INVALID_LITERAL, B0_WRONG_TYPE, B0_VALIDATOR_ERROR, and the generic
`VALIDATION_ERROR` fallback (unmapped pydantic type) — all reachable through
`validate_sorting_block` inputs only.

### Layer-3 test translation (V1b)

| Python source | Translate now | Defer note |
|---|---|---|
| `tests/unit/test_validation.py` | validate_bookmark classes (59 refs) → `validation-bookmark.test.ts` | query-args classes were V1a's |
| `tests/unit/test_bookmark_validation_pbt.py` (288) | all (validate_bookmark ×11 + flow_bookmark) | — |
| `tests/test_validation_flow.py` | FLB classes appended to V1a's flow test file (or a sibling `validation-flow-bookmark.test.ts` citing the same source) | flow-args classes were V1a's |
| `tests/test_validation_cohort.py` | validate_bookmark cohort classes (B22–B26; 16 refs) | retention classes were V1a's |
| `tests/test_validation_bypass.py` (414) | validator-direct asserts (8 `validate_bookmark` refs — the "L2 also catches" halves) | `ws.build_params`-driving halves (16 refs) → B5, header citation |
| `tests/test_validation_bypass_r2.py` (287) | validator-direct asserts | facade-driving classes → B5 |

### R10.10 consumer packet (V1b)

- `workspace.query/funnel/retention` call `validate_bookmark(params[, bookmark_type=
  "funnels"|"retention"])` post-construction (`workspace.py:2736/:3058/:4219`);
  `workspace.flow` calls `validate_flow_bookmark(params)` (`:3846`) — all B5-S2.
- `Workspace._validate_bookmark_params_schema` (`workspace.py:5186-5230`, B6 bookmark
  CRUD paths `:5296/:5396`) routes `params["sorting"]` through `validate_sorting_block`
  — B6-W3 consumer.
- Public API: `import { validate_bookmark } from "@mixpanel-headless/core"` — end users;
  keep the Python docstring example semantics (returns the full list; caller decides
  whether to raise).
- Forward note to B5: `BookmarkValidationError` replay — see §Binding-plan (the
  `CoreLibraryError.toExpectError()` extension belongs to B5's binding task, not B2).

### R10.9 harness spec (V1b)

New oracle fuzz targets: `bookmark_family` (dict-shaped params: sections/show/time/
filter/group permutations, cohort-bearing group clauses, filterValue lists with
non-finite floats, >1000-element lists for B21, bad customPropertyId types),
`flow_bookmark_family`, `sorting_family` (chart-type keys valid/unknown/non-dict configs,
every discriminator route: sortBy column/label/value/liftComparisonValue ×
colSortAttrs present/absent × sortColumn present/absent, missing sortBy/sortOrder/
colSortAttrs, unknown keys, non-list colSortAttrs, wrong-typed valueField/viewNLimit).
≥500 examples each; edge set = the fixed R10.9 items + every V1b code above (both
lists), incl. one probe per `_sorting_code_mapper` branch. This family is B2's
heaviest-fuzz surface (hand-rolled pydantic twin) — treat divergences as findings, not
noise; every unexplained one blocks.

### Done-criteria (V1b)

`tsc --strict` clean; translated tests green; after (b′): 140 V1b vectors PASS (and V1a's
372 still PASS); `validate_bookmark` exported from the core barrel; `enums.ts` TODO
closed; probe script results recorded in the notes file; R10.9 RUN record; `npm run
check` green; `just check` green (strategies additions); commits.

## Packet V2 — user validators

**Model**: sonnet, effort ≤ high. **Vectors: 178** (143 `validate_user_args` + 35
`validate_user_params`). May run in parallel with V1a/V1b (disjoint files).

### Python sources

`src/mixpanel_headless/_internal/query/user_validators.py` (580 LOC, whole file):

| Range | Contents |
|---|---|
| 14–34 | imports — NOTE `from ..query.user_builders import _is_cohort_filter` (B3-K4 module) and `from mixpanel_headless.types import CohortDefinition, Filter` (Phase-2, ported) |
| 37–55 | `_normalize_filters(where) -> list[Filter]` |
| 58–476 | `validate_user_args(*, where, cohort, properties, sort_by, sort_order, limit, search, distinct_id, distinct_ids, group_id, as_of, mode, aggregate, aggregate_property, percentile, segment_by, parallel, workers, include_all_users) -> list[ValidationError]` — rules U0–U30 ("U9 enforced at call site" per the docstring; **no U9 code exists in source** — do not invent one) |
| 479–580 | `validate_user_params(params) -> list[ValidationError]` — UP1–UP4 over an engage params dict |

**Cross-batch dependency (R10.8 decision)**: `_is_cohort_filter`
(`user_builders.py:69-85`, a 3-line shape predicate: `f._value` is a non-empty list of
dicts). V2 creates `packages/core/src/query/user-builders.ts` containing ONLY
`isCohortFilter` (JSDoc citing the Python range), with a header note that **B3-K4 grows
this file** (`filter_to_selector` etc.) and must import — never re-declare — this
predicate. Single implementation by name, R10.8.

### TS homes

- `packages/core/src/query/user-validators.ts` — both validators + `_normalizeFilters`.
- `packages/core/src/query/user-builders.ts` — `isCohortFilter` only (see above).
- Not in the package barrel (Python keeps these `_internal`).

### Rule codes owned (V2)

**Corpus-present** (`validate_user_args`): U0, U1, U2, U3, U4, U5, U6, U7, U8, U10, U11,
U12, U13, U14, U15, U16, U17, U18, U19, U20, U21, U22, U23, U25, U26, U27, U28, U29, U30.
(`validate_user_params`): UP1, UP2, UP3, UP4.

**Source-present, corpus-silent** (harness must cover): **U24** (grep 2026-08-15 — in
source, zero vectors). There is deliberately no U9 (call-site rule) — the harness
enumerates U0–U30 minus U9, plus UP1–UP4.

### Known traps specific to V2 (each is a review-pair checklist line)

1. `sort_by.strip() == ""` (:186), `f._property.strip() == ""` (:237),
   `prop.strip() == ""` (:273) → `pythonStrip` (R11.7); never `.trim()`.
2. `as_of` handling (:199-217): `contextlib.suppress(ValueError):
   date.fromisoformat(as_of)` then `parsed_date > date.today()` — TWO traps:
   (a) CPython 3.11+ `date.fromisoformat` accepts MORE than `YYYY-MM-DD` (`"20250101"`,
   week dates) — probe on CPython 3.14.6 and port the accepted grammar exactly (no
   `Date()` construction in the accept/reject decision — watchlist #5; implement a pure
   calendar parse like `_is_valid_date`'s port);
   (b) `date.today()` is a CLOCK read: the recorded expectations were extracted under
   the recorder's frozen clock. Port with an injectable `today` seam
   (`options.today?: () => string` or module-level injection): the (b′) binding passes
   the recordEpoch-derived date via `context.shims` (the oracle already builds
   `createShims(recordEpoch)`), the library defaults to the real clock.
3. `json.loads` on `filter_by_cohort` (:525, error branch UP-coded on
   `JSONDecodeError`/`TypeError`) and on `op_val` (:551, suppressed) — use core
   `parseLossless` with `pythonConstants` (B0 arbiter F1: `json.loads` accepts
   `NaN`/`Infinity`/`-Infinity`), and guard catches with the `LosslessJsonError`
   instanceof pattern (B0 arbiter F3) so a parser RangeError propagates like Python's
   RecursionError. Never bare `JSON.parse`.
4. `limit`/`workers`/`percentile`/`segment_by` numeric checks: read each `isinstance`
   chain for the bool-before-int pattern and integral-float rejection — see Cautions
   §int/float for the required TS idiom + PyFloat carrier semantics.
5. `cohort: int | CohortDefinition` and `where: Filter | list[Filter] | str | None` —
   vector inputs arrive as `$type`-tagged `CohortDefinition`/`CohortCriteria`/`Filter`
   instances through the Phase-2 contract codecs; `_normalizeFilters` must accept the
   real ported `Filter` class (instanceof), not duck shapes.

### Layer-3 test translation (V2)

- `tests/test_user_validators.py` (1,340 LOC) — whole file →
  `packages/core/src/query/user-validators.test.ts`.
- The 5 `validation/`-capability vectors extracted from
  `tests/test_query_user_edge_cases.py` replay via the corpus; the FILE
  `test_query_user_edge_cases.py` itself is B5 Layer-3 scope (playbook B5 row) — do not
  translate it here; note the split in the test-file header.

### R10.10 consumer packet (V2)

- `workspace.query_user` → `validate_user_args(...)` at `workspace.py:9437`; raises
  `BookmarkValidationError` on any severity=="error" (B5-S2).
- `workspace.build_user_params` / the engage param path → `validate_user_params(params)`
  at `workspace.py:9623` (B5-S2). Api-map row for `build_user_params` pasted in §V1a.
- No other importers (measured).

### R10.9 harness spec (V2)

New oracle fuzz targets `user_args_family` + `user_params_family`, ≥500 examples each.
Strategy bias: conflicting identity args (distinct_id + distinct_ids), mode/aggregate
matrix (all 2×4 combos ± aggregate_property ± percentile edge values 0/100/50.0/-1),
as_of strings (ISO, compact, junk, future/past relative to the frozen today), where as
str/Filter/list/cohort-filter shapes, segment_by lists with non-ints, limit/workers
0/negative/float/bool, params dicts for UP1–UP4 (filter_by_cohort as dict/bad-JSON
string/valid-JSON string, op_val JSON round-trips). Edge set: the fixed R10.9 items +
every code U0–U30 (sans U9) + UP1–UP4 incl. corpus-silent U24.

### Done-criteria (V2)

`tsc --strict` clean; translated tests green; after (b′): 178 vectors PASS; `today` seam
in place and documented; R10.9 RUN record; `npm run check` green; `just check` green;
commits.

## Binding plan — fable (b′) task

Rig code — **fable only** (P3-3 rig row; P3-6 step 3). Registers the batch's api names in
`conformance-runner/src/bindings.ts` (new registration module
`registerValidatorBindings(implementations, codecs)`) and in oracle-ts via the SAME
shared registration (the oracle imports the bindings registry — one registration point,
P3-2 b′). Applies the P3-5 rule-3 binding-honesty check: each binding calls the ported
public entry point (`validateTimeArgs(...)` etc.) — never re-derives a check, never
filters/reorders the returned list beyond the structural encoding below.

### Registry entry names (11 — bind ALL, including the zero-vector one)

```
validation.validate_time_args        validation.validate_group_by_args
validation.validate_funnel_args      validation.validate_retention_args
validation.validate_flow_args        validation.validate_flow_bookmark
validation.validate_query_args       validation.validate_bookmark
validation.validate_sorting_block    user_validators.validate_user_args
user_validators.validate_user_params
```

Source of truth: `conformance/record/registry.py::_validator_entries()` (:450-500) — 11
of its 12 entries. The 12th, `bookmark_schema.validate_with_pydantic`, is **NOT bound at
B2**: its prefix (`bookmark_schema.`) flips at the B3 gate and the gate's oracle probe
covers "newly registered registry-covered apis" only — record this exclusion in the B2
gate notes so the B3 binder picks it up. `validation.validate_sorting_block` has ZERO
corpus vectors but MUST be bound: the B2 gate probe issues one `oracle.call` per
registered `validation.*`/`user_validators.*` name against both bridges (P3-2e step 3),
and the `validation.` prefix flip at the gate makes any unbound `validation.*` straggler
a FAIL_ERROR.

### Binding shape (returned-list replay — ALL 690 B2 vectors)

Decode: `context.kwargs` arrives through the shared `CodecRegistry` — B2 inputs carry
`$type` tags `Filter`, `Exclusion`, `GroupBy`, `CohortBreakdown`, `FunnelStep`,
`CohortDefinition`, `CohortCriteria`, `TimeComparison`, `Metric`, `HoldingConstant`,
`Formula`, `CustomPropertyRef`, `float` (measured tallies in the corpus) — all already
registered Phase-2 contract codecs. No new input codecs are expected; if decode throws
`UndecodableValueError` on a B2 vector, that is a codec-table gap → fable rig fix, not a
module workaround.

Encode: the TS twin of the Python `validation_errors` output codec
(`conformance/record/codecs.py::_encode_validation_errors`, :720-748): map the returned
`ValidationError[]` to `[{path: e.path, code: e.code, severity: e.severity}]` —
**exactly those three keys, emission order preserved**. This is load-bearing: the runner
compares `expect.output` through `diffReturnedValue` → `canonicalize`
(`runner.ts:532-580`), which does NOT strip advisory keys — `canonicalizeError`'s
message/suggestion/fix stripping (`canonical.ts:115-157`) applies ONLY to `expect.error`
values. If the binding serialized `message` or `suggestion`, every vector would
FAIL_OUTPUT. All 690 recorded `expect.output` entries carry exactly
`{code, path, severity}` (measured: 420 non-empty entries, one field-set). `severity` is
compared strictly (S4_UNKNOWN_CHART_TYPE vectors expect `"warning"`).

Wrap the invocation in the `runGuarded` pattern (bindings.ts:484-494): these validators
are total functions and should never throw; an unexpected `MixpanelHeadlessError`
surfaces as `CoreLibraryError` → the runner reports FAIL_ERROR `unexpected raise: …`
(honest failure, correct behavior). Determinism: no fetch/sleep/random; the ONE seam is
`user_validators.validate_user_args`'s `today` — pass `context.shims.today()`
(`runner.ts:445,460`; the oracle builds the same shims, `differential/oracle/server.ts`
`createShims(recordEpoch)`), so vector replay and fuzz both see the frozen 2026-01-15
clock while the library defaults to the real one.

Sample vectors of the returned-list shape (2 quoted, per the task spec):

```json
{"call":{"api":"validation.validate_bookmark","input":{"params":{…}}},
 "expect":{"output":[{"code":"B18B_INVALID_CP_ID","path":"sections.show[0].behavior.filters[0].customPropertyId","severity":"error"}]},
 "id":"validation/validation.validate_bookmark/test_validation_bypass-testvector1metricfiltercpfixed-test_l2_also_catches_invalid_cp_id-2","kind":"builder"}

{"call":{"api":"user_validators.validate_user_args","input":{"limit":0}},
 "expect":{"output":[{"code":"U3","path":"limit","severity":"error"}]},
 "id":"validation/user_validators.validate_user_args/test_query_user_edge_cases-testtier3validationgaps-test_t3_11_limit_zero_raises_u3","kind":"builder"}
```

(Third shape datum: the all-valid case `expect.output: []` — e.g.
`…test_validation_bypass-testvector3inlinecohortdesignchoice-test_raw_cohort_structure_present-2`
— an empty JSON array, not an absent key.)

### Raised-error replay (`expect.error` class+code) — how it works, and why it is NOT B2's

Runner mechanics (read 2026-08-15): when a binding throws, `runVector` requires the
vector to carry `expect.error` (`runner.ts:539-553`) and diffs via `diffThrownError`
(:319-332): thrown value must implement `toExpectError()` (the bindings-layer
`CoreLibraryError` wrapper, bindings.ts:449-473, emits `{class, code}`), then BOTH sides
pass through `canonicalizeError` — advisory keys `message`/`suggestion`/`fix` stripped at
the top level and inside each `errors[]` element (`canonical.ts:119-157`), everything
else compared exactly.

The raised shape in the corpus belongs to the **B5 consumers**, kind
`"validation-error"`, e.g. (2 quoted):

```json
{"call":{"api":"workspace.build_params","input":{"events":"Login","formula":"A + B"}},
 "expect":{"error":{"class":"BookmarkValidationError","code":"BOOKMARK_VALIDATION_ERROR",
   "errors":[{"code":"V4_FORMULA_MIN_EVENTS","path":"formula","severity":"error"},
             {"code":"V19_FORMULA_BOUNDS","path":"formula","severity":"error"}]}},
 "id":"bookmarks/workspace.build_params/test_query_validation-testbuildparamsvalidation-test_rejects_formula_without_events","kind":"validation-error"}

{"call":{"api":"workspace.build_params","input":{"events":"Login","from_date":"01/01/2024"}},
 "expect":{"error":{"class":"BookmarkValidationError","code":"BOOKMARK_VALIDATION_ERROR",
   "errors":[{"code":"V8_DATE_FORMAT","path":"from_date","severity":"error"}]}},
 "id":"bookmarks/workspace.build_params/test_query_validation-testbuildparamsvalidation-test_rejects_invalid_date_format","kind":"validation-error"}
```

**Forward note the B2 binder records for B5 (do not fix at B2):** the current
`CoreLibraryError.toExpectError()` emits ONLY `{class, code}`; a
`BookmarkValidationError` expectation also carries `errors[]` (order-sensitive,
`{code, path, severity}` per element after advisory stripping), so the B5 binding task
must extend the adapter (e.g. include `errors` when `original instanceof
BookmarkValidationError`, mapping each `ValidationError` to the three contract keys) or
those `workspace.build_*params` vectors will FAIL_ERROR on canonical-string mismatch.
Zero B2 vectors hit this path, so B2 lands nothing there (binding honesty: no
speculative rig edits outside the batch's surface).

Cross-batch setup scan (measured 2026-08-15): **zero** B2 vectors carry `call.setup[]`,
and zero vectors of ANY batch carry a `validation.*`/`user_validators.*` setup entry —
the B2 gate delta is exactly 690 with no P3-1 † adjustment.

### Oracle-ts registration + honesty check

Same registration module serves the oracle (`differential/oracle/server.ts` executes
bound apis through the shared registry; integral-float inputs are re-tagged to the
PyFloat carrier before decode, server.ts:186-215/:725). After registration, the module
tiers run P3-2(c); at the B2 gate: mechanical probe = one `oracle.call` per the 11 names
on BOTH bridges, non-"unknown api" responses required; then the differential full-suite
regression — note the six Phase-1 families recorded as "B2/B3-pending skips" at the B0
gate (B0-notes: 3,049 explained skips) partially un-skip once `validation.*` names bind;
expect the skip count to DROP and document the new number in the gate notes.

### Batch-status / flip

NO flip in the binding commits. The single B2 gate commit flips `validation.` +
`user_validators.` → `done` (P3-5 rule 4); expected gate deltas: PASS +690 (539 → 1,229
against the current baseline), UNPORTED −690 (2,712 → 2,022), FAIL 0. Run the standing
no-prefix-collision assertion after the flip (no corpus api name outside B2 starts with
either prefix — `bookmark_schema.` does not collide; verified against the api list).

## Cautions (all shards — each line is a review-pair checklist item)

1. **R4.8 ReadonlyMap/ReadonlySet lookup tables.** All enum membership goes through the
   P2-3 `bookmarks/enums.ts` `ReadonlySet.has()` tables (`MAX_CONVERSION_WINDOW` is a
   `ReadonlyMap`); dict-key presence checks on user-supplied params dicts
   (`"sections" not in params`, `"sorting" in params`, measurement/behavior key reads)
   use `Object.hasOwn` — never `in` (prototype-chain membership, watchlist #7:
   `'toString' in obj` is true in JS, `False` in Python).
2. **Watchlist #6 — empty-collection truthiness.** `[]`/`{}`/`""` are falsy in Python,
   truthy in JS. Every `if not steps` → `steps.length === 0`; `if known:`
   (validate_sorting_block :3080) → `Object.keys(known).length > 0`; `if errors:` /
   `if suggestion:` → explicit length/null checks (note `ValidationError.toString`
   already ports the `None`-AND-`()`-falsy nuance — errors.ts:1262-1266 is the
   precedent). Grep every translated `if (!x)` in review.
3. **R11.7 (amended post-B0, [SA3]) — `pythonStrip`/`pythonInt` mandatory.** Every
   blank/emptiness guard (`not s.strip()`) → `pythonStrip`; every `int(str)` →
   `pythonInt`; bare `String.trim()`, `parseInt`, `Number(...)`, and `\s`-regex grammars
   are FORBIDDEN in ported code. Measured `.strip()` sites: `validation.py`
   :128, :176, :878, :1037, :1110, :1251, :1280, :1432, :1592, :1821, :1986;
   `user_validators.py` :186, :237, :273. The 13×-recurrence remediation `3c07d4e` and
   gate report `2026-08-15-b0-gate.json` are the amendment's evidence — the reviewer
   greps the diff for `.trim(` and `parseInt(` and fails the review on any hit outside
   the pydantic-core carve-out (which must cite its third-parser reference at the call
   site).
4. **`_INVISIBLE_RE` may NOT port as a `\s` regex** (R11.7's regex ban). Python
   `\s` (str pattern) == the `str.isspace()` set == the pinned
   `compat/whitespace.gen.ts` table. Build the invisible-char test from that table ∪
   the explicit literals {U+200B, U+200C, U+200D, U+FEFF, U+00AD, U+2060}
   (`validation.py:363`). JS `\s` diverges in both directions (has U+FEFF, lacks
   U+001C–U+001F). Same rule for any other `\s` in translated PBT strategies.
5. **`severity` is compared strictly.** It is one of the three contract keys in every
   output entry; `S4_UNKNOWN_CHART_TYPE` is the corpus's `"warning"` case (and
   `_enum_error` takes severity as a parameter — port the default `"error"` and the
   explicit warning call). Do not normalize or default it in the binding encoder.
6. **`suggestion`/`fix` are advisory (R5.3) — but only in VECTORS.** They never enter
   `expect.output` (recorder strips them; D4.3) and `canonicalizeError` strips them from
   `expect.error`. HOWEVER Layer-3 tests assert suggestion CONTENTS
   (`test_validation_funnel.py:838-846`, `test_validation_retention.py:273-279,314+`),
   so `_suggest` needs a faithful `difflib.get_close_matches` port: SequenceMatcher
   `ratio()` semantics with the `real_quick_ratio`/`quick_ratio` pre-filters, candidates
   from `sortedByCodepoint(valid)` (R11.5 — Python `sorted(valid)`, validation.py:427),
   n=3, cutoff=0.5, results ordered by descending ratio (stable). Home:
   `query/validation-shared.ts` (exported for V1b/V2 reuse); autojunk is irrelevant at
   these input sizes but document the choice. R10.2 forbids weakening those asserts.
7. **No message text in expectations (R5.4).** Vectors never assert messages; the
   binding encoder never serializes them; translated tests keep message asserts only
   against the TS port's own faithfully-ported strings (see V1a Layer-3 note). Message
   formatting (`_enum_error`'s `sample = sorted(valid)[:5]` list repr etc.) is
   display-only — do not spend fidelity effort beyond compilable sanity, and never
   let a message diff fail a vector.
8. **int/bool/float checks (Python `isinstance` semantics).** Sites:
   `_validate_data_group_id` (:487 — `isinstance(x, bool) or not isinstance(x, int)`),
   retention `bucket_sizes` elements (:1329), `_validate_filter_clause` cp_id (:2834),
   `_validate_custom_property` CP1, plus V2's numeric args. TS idiom:
   `typeof v === "number" && Number.isInteger(v)` with an explicit
   `typeof v === "boolean"` reject FIRST (Python: bool IS int — the guard order
   matters). Oracle/fuzz semantics: Python integral floats (`2.0`) arrive in TS as the
   rig's **PyFloat carrier** (oracle `tagIntegralFloatTokens`, server.ts:186-215; corpus
   `$type: "float"` — the only two B2 float-tagged vectors are the authored B20B
   Infinity cases), i.e. a non-number object — which correctly fails the
   `typeof === "number"` check exactly where Python's `isinstance(x, int)` fails a
   float. The (b′) binding passes decoded kwargs through UNCONVERTED except where a
   value must become a TS number for finiteness checks (`_is_finite` → B20B: unwrap
   PyFloat spellings `Infinity`/`-Infinity`/`NaN` to the native non-finite numbers, the
   vector-codecs.ts:606-611 unwrap precedent). Any other PyFloat unwrapping in a binding
   is a binding-honesty smell — flag to the arbiter.
9. **R11.6 codepoint lengths.** `_CP_MAX_FORMULA_LENGTH` (`len(prop.formula) > 20_000`,
   CP5) and every other `len(str)` bound counts CODEPOINTS: use `cpLength`, and
   `cpSlice` for any truncation. JS `.length` counts UTF-16 units — the non-BMP edge
   item (`"𝒳"`) in every harness exists to catch exactly this.
10. **Dates are strings end-to-end (watchlist #5).** `_is_valid_date` regex-gates
    `YYYY-MM-DD` then checks calendar validity via `date.fromisoformat` — port as a pure
    calendar-validity check (month 1–12, day vs month length, Gregorian leap rule);
    never `new Date(...)` parsing. V2's `as_of` accepts the WIDER CPython 3.11+
    `fromisoformat` grammar (no `_DATE_RE` pre-gate there) — probe and port that grammar
    explicitly (V2 trap #2) and pin findings in the test file.
11. **Emission order is contract.** `expect.output` is an ordered array; the runner
    canonicalizes without sorting entries. Port every `errors.append`/`errors.extend`
    in source order, including the composite-validator delegation order (V1a call-graph
    table) and pydantic error order in the sorting slice (V1b probe).
12. **`float` vs `int` rendering never enters B2 outputs** (codes/paths/severities are
    strings) — but fuzz INPUTS hit every numeric branch; do not add epsilon or rounding
    anywhere (watchlist #12).
13. **Baseline arithmetic**: current report 3,251 = 539 PASS / 0 FAIL / 2,712 UNPORTED.
    B2 gate expectation: 1,229 / 0 / 2,022 — ADJUST both by +N if B2 tasks add authored
    vectors (none are planned by this packet; the uncovered-codes file already exists
    and is counted).

## Vector-count reconciliation (must sum to 690)

Per corpus file (B2-owned lines only; each bundle file carries one non-vector meta line,
excluded):

| file (`conformance-runner/corpus/…`) | B2 vectors |
|---|---|
| `validation/test_validation.jsonl` | 106 |
| `validation/test_validation_funnel.jsonl` | 117 |
| `validation/test_validation_retention.jsonl` | 104 |
| `validation/test_validation_flow.jsonl` | 119 |
| `validation/test_validation_cohort.jsonl` | 22 |
| `validation/test_validation_bypass.jsonl` | 7 |
| `validation/test_query_validation.jsonl` | 26 |
| `validation/test_query_validation_pbt.jsonl` | 2 |
| `validation/test_user_validators.jsonl` | 173 |
| `validation/test_query_user_edge_cases.jsonl` | 4 |
| `authored/validation/uncovered-codes.jsonl` | 10 |
| **Σ** | **690** |

Per shard: V1a 372 (= 12 + 8 + 39 + 117 + 107 + 89) + V1b 140 (= 110 + 30 + 0) +
V2 178 (= 143 + 35) = **690** = `validation.` 512 + `user_validators.` 178. ✓
