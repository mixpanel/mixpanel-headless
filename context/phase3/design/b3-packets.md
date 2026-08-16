# B3 design-lite packets — builders (P3-6 step 1)

**Status**: v1.0 · 2026-08-15 · fable design-lite packet for batch B3 (playbook P3-6 step 1,
sharding per P3-6 "B3 (4 tasks, opus)"). Location note: the orchestrator task names
`context/phase3/design/b3-packets.md` (B2 precedent); the playbook's generic path is
`context/phase3/packets/BX-packets.md` — this file is the packet of record for B3.
Every count below was measured 2026-08-15 against corpus pin `b5c1369`
(`conformance-runner/corpus.config.json`) and Python source at support-branch HEAD.
Baseline entering B3 (post-B2 gate, `context/phase3/reports/2026-08-15-b2-gate.json`):
**3,251 vectors = 1,229 PASS / 0 FAIL / 2,022 UNPORTED**.

**Shard map (counts sum to exactly 299):**

| Shard | Task | Scope | Vectors |
|---|---|---|---|
| K1 | opus | `bookmark_enums.py` parity + `bookmark_schema.py` remaining slice (`validate_with_pydantic` general dispatch, full model tree, `get_root_model_for_bookmark_type`, `PARTIAL_UPDATE_SUB_MODELS`) | **0** (oracle/Layer-3-locked; both registry names probe at the gate) |
| K2 | opus | `bookmark_builders.py` (whole file) | **134** |
| K3 | opus | `segfilter.py` + `expressions.py` + `transforms.py` | **83** (51+30+2) |
| K4 | opus | `query/user_builders.py` builders half (`filter_to_selector`/`filters_to_selector`/`extract_cohort_filter`) — DOUBLED fuzz | **82** |
| (b′) | fable | binding + oracle-ts registration for all four shards (17 registry names) | — |
| Σ | | | **299** |

**Execution order**: K2, K3, K4 are mutually independent AND independent of K1
(measured: `bookmark_builders.py` imports only `types`/`exceptions`/`_literal_types`;
the enum tables it never touches; `bookmarks/enums.ts` is already fully landed —
P2-3 + the B2 V1b TODO closure, 755 lines, all tables present). The playbook line
"K2–K4 depend on K1's tables" is therefore ALREADY SATISFIED by disk state — run all
four in parallel, or K2/K3/K4 first and K1 (the biggest single lift, zero vectors)
in parallel throughout. The fable (b′) task runs after each module task lands
(per-shard or combined; vector failures at (b′) are the MODULE task's attempt-1
failure, P3-6 step 3).

**Corpus location (all 299)** — B3 spans five capability directories (unlike B2's one):

| file (`conformance-runner/corpus/…`) | B3 vectors | shard |
|---|---|---|
| `authored/bookmarks/date-builders.jsonl` | 7 | K2 |
| `bookmarks/test_bookmark_builders.jsonl` | 32 | K2 |
| `bookmarks/test_bookmark_builders_pbt.jsonl` | 1 | K2 |
| `bookmarks/test_custom_property_builders.jsonl` | 8 | K2 |
| `filters/test_bookmark_builders.jsonl` | 48 | K2 |
| `filters/test_bookmark_builders_pbt.jsonl` | 1 | K2 |
| `filters/test_build_cohort_params.jsonl` | 16 | K2 |
| `filters/test_custom_property_builders.jsonl` | 7 | K2 |
| `filters/test_query_params.jsonl` | 14 | K2 |
| `filters/test_segfilter.jsonl` | 51 | K3 |
| `segmentation/test_expressions.jsonl` | 30 | K3 |
| `streaming/test_query_user_structural.jsonl` | 2 | K3 |
| `engage/test_user_builders.jsonl` | 78 | K4 |
| `engage/test_query_user_edge_cases.jsonl` | 3 | K4 |
| `engage/test_query_user_structural.jsonl` | 1 | K4 |
| **Σ** | **299** | |

Replay filters (vector ids embed the api name as path segment 2, so substring
`--filter` works per-module): `npm run conformance -- --filter bookmark_builders.`
(K2), `--filter segfilter.` / `--filter expressions.` / `--filter transforms.` (K3),
`--filter user_builders.` (K4).

**Expectation-shape measurement**: all 299 vectors are `kind: "builder"`;
**232 carry `expect.output`, 67 carry `expect.error`**. ZERO vectors carry
`call.setup[]`, and zero vectors of ANY batch carry a B3-prefixed setup entry
(measured: the corpus setup-api universe is 15 `api_client.*` names +
`workspace.me`) — **the B3 gate delta is exactly 299 with no P3-1 † adjustment**.
The 67 `expect.error` vectors carry `class` + `code` only (ParamValidationError /
ParamTypeError; codes BB1–BB8, SG1–SG4, ES1–ES13 — full ledger in §Guard-codes).

---

## Packet K1 — bookmark_enums parity + bookmark_schema remaining slice

**Model**: opus, effort ≤ high, R10.13 incremental protocol. **Vectors: 0** — this
shard is locked by Layer-3 translation, the R10.9 harness, and the gate's oracle
probe of its two registry names. Zero vectors ≠ optional: the B6-W3 bookmark CRUD
paths (`workspace.py:5234-5243`) and the B2-landed `validate_sorting_block` both
consume this module, and the batch cannot honestly flip `bookmark_schema.` without
the twin on disk.

### Python sources (re-read every range; line numbers at support-branch HEAD)

`src/mixpanel_headless/_internal/bookmark_enums.py` (607 LOC): **already fully
ported** to `packages/core/src/bookmarks/enums.ts` (755 lines; every
`VALID_*`/`MATH_*` table + `MAX_CONVERSION_WINDOW` ReadonlyMap +
`_MAX_FUNNEL_STEPS`/`_MAX_HOLDING_CONSTANT` landed at P2-3/B2). K1's enum work is
(a) a mechanical parity audit (diff every frozenset against its `ReadonlySet` —
member-for-member, no ordering claims) and (b) the Layer-3 translation of
`tests/unit/test_bookmark_enums.py` (270 LOC, 6 classes), which is the missing
lock. Any divergence found is a FINDING (fix enums.ts), not a rewrite.

`src/mixpanel_headless/_internal/bookmark_schema.py` (1,553 LOC). B2-V1b already
ported the pydantic-error adapter + sorting models (`:61-316`, `:372-680`) into
`packages/core/src/bookmarks/schema-sorting.ts` (956 lines; exports
`validateWithPydantic`, `validateInsightsBookmarkSortConfig`, `defaultCodeMapper`,
`sortingCodeMapper`, `DEFAULT_CODE_MAP`, `DISCRIMINATOR_TAGS`, `locToJsonPath`,
`translatePydanticError` machinery). **K1 owns the REMAINING slice:**

| Range | Contents |
|---|---|
| 38–59 | `_BASE_CONFIG` (`populate_by_name=True, extra="forbid"`) + `Ignore[T]` (`Annotated[SkipJsonSchema[T\|None], Field(default=None, exclude=True)]` — accepted at parse time, excluded from dumps) |
| 333–368 | `get_root_model_for_bookmark_type(bookmark_type) -> type[BaseModel] \| None` — dict-dispatch `{"insights"/"funnels"/"retention": InsightsBookmarkParams, "flows": FlowsBookmarkParams, "user": None}` via `.get()` (unknown type → `None` too) |
| 369–379 | `PARTIAL_UPDATE_SUB_MODELS: dict[str, type[BaseModel]]` — populated at module bottom (`:1548-1553`) with `{"sections": Sections, "displayOptions": DisplayOptions}`; `sorting` intentionally excluded |
| 695–835 | non-sorting literal aliases (`FiltersDeterminerLiteral` … `MathTypeLiteral`) |
| 837–1266 | the insights model tree: `RollingMeasurement`, `MultiAttributionWeights`, `CustomMultiAttribution`, `PredefinedMultiAttribution`, `StepRange`, `FunnelStep`, `ExclusionFunnelStep`, `MetricDisplay`, `Bucket`, `Winsorization`, `Statsig`, `SRM`, `Goal`, `SubBehavior`, `Behavior` (`:1025`), `MultiAttribution` union, `BehaviorMeasurement`, `FormulaMeasurement`, `BehaviorShowClause`, `FormulaShowClause`, `_show_clause_discriminator` (`:1200`), `ShowClause` discriminated union, `Sections` (`:1238`) |
| 1268–1418 | display-option literals + `AnnotationOptions`, `CommentOptions`, `SegmentId`, `FunnelStepsSelectedTableColumns`, `DisplayOptions` (`:1376`) |
| 1419–1483 | `InsightsBookmarkParams` root model |
| 1485–1542 | `FlowsBookmarkStep` + `FlowsBookmarkParams` — **NOTE `model_config = ConfigDict(populate_by_name=True, extra="allow")`** (deliberate; pinned by `test_flows_bookmark_params_currently_allows_extras`; keep the `TODO(corpus parity)` comment `:1511-1513` verbatim in the TS twin header) |

### TS homes

- `packages/core/src/bookmarks/schema.ts` (NEW) — the non-sorting model twin:
  structural validator functions for `InsightsBookmarkParams`,
  `FlowsBookmarkParams`, `Sections`, `DisplayOptions` (+ their nested model specs),
  `getRootModelForBookmarkType` returning a root-model HANDLE
  `{ name: string, validate: (raw: unknown) => PydanticErrorEntry[] } | null`
  (the binding's `model_name` codec serializes `.name`; B6-W3 calls `.validate`),
  and `PARTIAL_UPDATE_SUB_MODELS` as a `ReadonlyMap<string, RootModelHandle>`
  (R4.8).
- `packages/core/src/bookmarks/schema-sorting.ts` — EXPORT (do not duplicate) the
  internal model-spec/`validateModel` machinery so `schema.ts` builds on it
  (R10.8: one pydantic-core twin; `schema-sorting.ts`'s header already names B3-K1
  as the file's grower). Extensions the sorting slice did not need and K1 must add
  to the shared machinery: `extra="allow"` mode (FlowsBookmarkParams),
  `Ignore[T]` fields (accept anything incl. explicit null, never error),
  `JsonValue` passthrough fields, list-of-model fields, model-in-union defaults,
  and alias handling per `_BASE_CONFIG` (`populate_by_name` — accept BOTH the
  Python field name and the declared alias where one exists).
- `packages/core/src/bookmarks/index.ts` — extend the barrel (internal exports
  only; nothing new in the package barrel — Python keeps all of this `_internal`).

### Mandatory probe before implementing (V1b precedent, binding)

A throwaway CPython script (uv) driving `validate_with_pydantic` over
`InsightsBookmarkParams` / `FlowsBookmarkParams` / `Sections` / `DisplayOptions`
recording pydantic-core's error ORDER and MULTIPLICITY for multi-error inputs:
missing-`sections` + extra key together; a `ShowClause` union input failing the
`_show_clause_discriminator` (`union_tag_invalid`/`union_tag_not_found` →
B7_INVALID_BEHAVIOR_TYPE via `_DEFAULT_CODE_MAP:91-92`); nested `Behavior` errors
(loc depth + `_DISCRIMINATOR_TAGS` filtering through `_loc_to_jsonpath`);
lax-coercion cases (int-for-float, numeric-string-for-int — pydantic lax mode;
heed the B2-HK coerce.ts flag: pydantic trim ≠ `str.strip()` ≠ `.trim()`,
FEFF-prefixed numeric strings are the known divergence direction);
`extra="allow"` tolerance on FlowsBookmarkParams vs `extra_forbidden` →
S3_UNKNOWN_FIELD on the strict models; `Ignore` fields with junk values.
Lock the observed order in the Layer-3 tests and record the probe transcript in
`context/phase3/notes/B3-notes.md`. The `schema.ts` header states the R11.7
third-parser carve-out (reference semantics = pydantic-core) and cites the probe.

### Guard codes owned (K1)

No K1-owned coded raises. Output codes flow through the B2-ported
`_DEFAULT_CODE_MAP` (B0_MISSING_FIELD, S3_UNKNOWN_FIELD, B0_INVALID_LITERAL,
B0_WRONG_TYPE ×9 types, B7_INVALID_BEHAVIOR_TYPE ×2, B0_VALIDATOR_ERROR, generic
VALIDATION_ERROR fallback) — the harness must reach EVERY map row through the
non-sorting models (the sorting models already covered B2's rows).

### Layer-3 test translation (K1)

| Python source | Translate now | Defer note |
|---|---|---|
| `tests/unit/test_bookmark_enums.py` (270) | all 6 classes → `bookmarks/enums.test.ts` | — |
| `tests/unit/test_bookmark_schema.py` (574, 9 classes) | all → `bookmarks/schema.test.ts` (incl. `test_flows_bookmark_params_currently_allows_extras`) | — |
| `tests/unit/test_bookmark_schema_pbt.py` (387, 7 classes) | all (fast-check twins, same strategy shapes) | — |

R10.2: never weaken. Where a Python assert compares pydantic error `type` strings
or message substrings, keep the assert against the twin's faithfully-ported
`PydanticErrorEntry.type` values (they ARE the contract keys of the twin), citing
the probe.

### R10.10 consumer packet (K1)

- `Workspace._validate_bookmark_params_schema` (`workspace.py:5186-5243`, B6-W3):
  `root = get_root_model_for_bookmark_type(bookmark_type)` `:5234`; if non-None →
  `errors.extend(validate_with_pydantic(root, raw_no_sorting))` `:5236`; then for
  partial updates iterates `PARTIAL_UPDATE_SUB_MODELS.items()` `:5240` →
  `validate_with_pydantic(model, raw_no_sorting[key], path_prefix=key)` `:5243`.
  Consumed by bookmark CRUD paths `workspace.py:5296/:5396` (B6-W3 create/update).
- `validation.validate_sorting_block` (B2, already ported) — unchanged; K1 must
  not touch the sorting dispatch.
- TS ergonomics: B6-W3 will call
  `validateWithPydantic(root.validate, rawNoSorting)` and
  `validateWithPydantic(model.validate, raw[key], { path_prefix: key })` — the
  handle shape above is the contract; do not export bare validator functions
  without names (the `model_name` output codec and B6's dispatch both need
  `.name`).

### R10.9 harness spec (K1)

Throwaway harness in `throwaway/` inside the module commit; RUN record to
`context/phase3/notes/B3-notes.md`; review pair re-runs from recorded seeds; the
batch gate deletes `throwaway/`.

- **Oracle families** (extend `conformance/differential/strategies.py`; Python-side
  commit, `uv`, `just check`): NEW `bookmark_schema_family` driving
  `bookmark_schema.validate_with_pydantic` **by model NAME** (see §Binding-plan —
  the (b′) task retargets the registry entry to a name-resolving adapter) across
  all five models (sorting + the four K1 models), ≥500 examples; strategy bias:
  near-valid insights params dicts (drop one required key / add one unknown key /
  wrong-type one leaf / bad discriminator tag / deep Behavior nesting), flows
  params with extras (allowed) and wrong-typed `steps` elements, Sections /
  DisplayOptions fragments, `Ignore`-field junk. Plus one edge probe per
  `_DEFAULT_CODE_MAP` row per model family. NEW `get_root_model_family`
  (trivial, ≥500 or exhaustive-with-junk): the five literal types + unknown +
  empty string.
- **Mandatory edge set** (R10.9 verbatim): integral float `18.0`, fractional
  `1.5`, `True`, `None`, empty list, empty string, non-BMP `"𝒳"` — each as (i) the
  raw value and (ii) a leaf inside an otherwise-valid params dict; plus every
  `_DEFAULT_CODE_MAP` row (above). `dict[str, Any]` interiors are in-annotation
  (ratified Discrepancy #8) — no domain trimming inside params dicts.

### Done-criteria (K1)

`tsc --strict` clean; translated tests green; enums parity audit recorded in the
notes file (zero diffs or fixes committed); probe transcript recorded; after (b′):
both `bookmark_schema.*` names answer non-"unknown api" on BOTH bridges and the
R10.9 families run ≥500 clean; `npm run check` green; `just check` green
(strategies.py + adapter changed); one commit per repo; local commits only.

## Packet K2 — bookmark_builders

**Model**: opus, effort ≤ high, R10.13 incremental protocol. **Vectors: 134**
(measured per api: `build_filter_entry` 43 · `build_group_section` 32 ·
`build_flow_cohort_filter` 16 · `build_time_section` 10 ·
`build_frequency_filter_entry` 9 · `build_flow_property_filter` 9 ·
`build_filter_section` 9 · `build_date_range` 6).

### Python sources (whole file, 904 LOC; re-read every range)

`src/mixpanel_headless/_internal/bookmark_builders.py`:

| Range | Function |
|---|---|
| 32–69 | `_build_composed_properties(inputs: dict[str, PropertyInput])` — dict comprehension, insertion order preserved |
| 72–127 | `build_time_section(*, from_date, to_date, last, unit)` — **CLOCK SEAM** `:115`: from-only case fills `to_date` with `date.today().isoformat()` |
| 130–170 | `build_date_range(*, from_date, to_date, last)` — flows flat format; relative case emits `"to_date": "$now"` (a LITERAL string, not a clock read) |
| 173–205 | `build_filter_section(where)` — None → `[]`; single-or-sequence normalization `isinstance(where, (list, tuple))` `:198`; dispatches FrequencyFilter → `build_frequency_filter_entry`, Filter → `build_filter_entry`; **silently SKIPS elements that are neither** `:200-204` (no else — port the skip, no error) |
| 208–239 | `patch_custom_property_filters_for_transform(filter_entries)` — mutates IN PLACE and returns the same list; guard `"value" not in entry and ("customPropertyId" in entry or "customProperty" in entry)` `:235-237` → `Object.hasOwn`, never `in` |
| 242–403 | `build_group_section(group_by, *, data_group_id=None)` — str/FrequencyBreakdown/GroupBy(CustomPropertyRef \| InlineCustomProperty \| `_list_item_mode` \| plain)/CohortBreakdown dispatch; else raises **BB1_GROUP_BY_ELEMENT_TYPE** (`ParamTypeError`, `:397-401`); `customBucket` conditional-insert block `:383-390` (min/max only when non-None, R4.11) |
| 406–466 | `_build_cohort_group_entry(cb, *, data_group_id)` — `name = cb.name or ""` (falsy-OR: empty string AND None both → `""`); saved (`int`) vs inline cohort split `:443-447` (`base_cohort["id"]+["groups"]=[]` vs `raw_cohort = _sanitize_raw_cohort(cb.cohort.to_dict())`); negated copy via `{**base_cohort, "negated": True}` `:453` (SHALLOW — shared `raw_cohort` reference; encode-time equality makes this safe, but do not deep-copy); labels `[name, f"Not In {name}"]` |
| 469–530 | `build_filter_entry(f)` — `list_contains` short-circuit `:497`; key order: `resourceType, filterType, defaultType, filterValue, filterOperator`, then per-property-kind keys, then `value` (plain-str case `:527`), then `filterDateUnit` conditional `:528-529`. **R10.12 site: `filterValue: f._value` `:504` passes numbers through NATIVELY — never stringify** |
| 533–580 | `_build_list_contains_entry(f)` — recursive `build_filter_entry` on `_list_item_filters` with `setdefault("dataset", "$mixpanel")` `:567`; constant outer wrapper incl. **`filterValue: True`** `:579` (JSON `true` — R10.12's boolean cousin; never the string `"true"`) |
| 583–646 | `build_flow_property_filter(filters)` — empty → **BB2_FLOW_PROPERTY_FILTER_EMPTY** (`ParamValidationError` `:617-622`); non-str property → **BB3_FLOW_PROPERTY_FILTER_TYPE** (`ParamTypeError` `:630-636`); then `entry.pop("value", None)` + `entry.pop("defaultType", None)` `:638-640` — NOTE BB3 raises AFTER `build_filter_entry(f)` succeeded `:625` (a CustomPropertyRef reaches BB3, an InlineCustomProperty too — port the call order exactly, earlier raises from `build_filter_entry` win) |
| 649–737 | `build_flow_cohort_filter(where)` — empty list → `None` `:684-685`; per-filter `_property != "$cohorts"` → **BB4** `:688-694`; `len>1` → **BB5** `:696-701`; `_value` shape guards → **BB6/BB7/BB8** `:706-728`; result dict `name` (`.get("name","")`), `negated: f._operator == "does not contain"`, conditional `id`/`raw_cohort` copies `:733-736` (`"id" in cohort_data` → `Object.hasOwn` on a decoded dict — watchlist #13/#7) |
| 740–802 | `build_frequency_group_entry(fb, *, data_group_id)` — label default `f"{fb.event} Frequency"` `:780`; fixed key order `:781-801` |
| 805–855 | `build_frequency_filter_entry(ff)` — **R10.7 BUG-COMPAT, see below** |
| 858–904 | `build_time_comparison(tc)` — TC1/TC2 unreachable-guard `AssertionError` branches `:892-903` are `pragma: no cover`; port as unreachable throws, never as reachable codes |

### R10.7 bug-compat: `build_frequency_filter_entry` (`:805-855`)

The emitted `customProperty`-nested clause shape causes a **server HTTP 500** at
the execution layer — probe record
`context/phase1/addendum/frequency-filter-probe.md` (VERDICT: REJECTS; open
Python bug `context/phase1/bug-reports/mixpanel-headless-frequency-filter-clause-shape.md`).
**Replicate the shape byte-for-byte** (key order `event`, `aggregation`,
`filterOperator`, `filterValue`; conditional `dateRange` when BOTH
`date_range_value` and `date_range_unit` non-None `:839-843`; conditional
`eventFilters` `:844-845`; outer `resourceType: "people"`, `behaviorType:
"$frequency"`; conditional top-level `label` `:853-854`). Put the probe-record
citation in a comment on the TS function; NEVER fix; the 9
`build_frequency_filter_entry` vectors are the byte-compat lock (ids:
`filters/bookmark_builders.build_frequency_filter_entry/test_bookmark_builders-testbuildfrequencyfilterentry-*`,
9 of 9: basic_structure, custom_operator, label_included,
label_omitted_when_none, multiple_event_filters, with_date_range,
with_event_filters, without_date_range, without_event_filters).
`ff.value` lands in `filterValue` NATIVELY (`:837`) — R10.12 applies here too.

### Clock seam: `build_time_section` (`:115`)

`date.today().isoformat()` in the from-only branch. Port with an injectable seam
per the B2-V2 `today` precedent (`options.today?: () => string`; library default =
real clock; the (b′) binding passes `context.shims.today()` — `runner.ts:445`
builds `createShims(recordEpoch)`). The authored vector
`bookmarks/bookmark_builders.build_time_section/authored-from-only-today-fill-record-epoch`
expects `["2026-01-01", "2026-01-15"]` — the frozen 2026-01-15 clock is the lock.
`build_date_range` has NO clock read (`"$now"` is a literal).

### TS homes

- `packages/core/src/bookmarks/builders.ts` (NEW) — the whole module, Python
  names preserved in camelCase per established convention; module-privates
  (`_build_composed_properties`, `_build_cohort_group_entry`,
  `_build_list_contains_entry`) exported for intra-package use only (not in the
  package barrel).
- Imports: `Filter`, `FrequencyFilter`, `GroupBy`, `CohortBreakdown`,
  `FrequencyBreakdown`, `CustomPropertyRef`, `InlineCustomProperty`,
  `PropertyInput`, `TimeComparison`, `sanitizeRawCohort` from
  `packages/core/src/types/` (all Phase-2-ported; `sanitizeRawCohort` lives in
  `types/query-params/cohort.ts`) — never re-declare (R10.8).
- Type discrimination: `instanceof` against the REAL ported classes
  (FrequencyFilter before Filter, mirroring `:201-204` order); dict membership
  via `Object.hasOwn`; `isPythonDict` from `query/validation-shared.ts` for any
  plain-dict test (watchlist #13) — `cohort_data` in BB7/BB8 guards is a decoded
  plain dict, `isinstance(first_item, dict)` `:714` ports to `isPythonDict`.

### TS signatures (kwargs-bag for kwonly; positional stays positional, R3.9/R4.10)

```
buildTimeSection(options: {from_date: string|null, to_date: string|null, last: number, unit: QueryTimeUnit, today?: () => string}): Array<Record<string, unknown>>
buildDateRange(options: {from_date: string|null, to_date: string|null, last: number}): Record<string, unknown>
buildFilterSection(where: Filter|FrequencyFilter|ReadonlyArray<Filter|FrequencyFilter>|null): Array<Record<string, unknown>>
patchCustomPropertyFiltersForTransform(filterEntries: Array<Record<string, unknown>>): Array<Record<string, unknown>>
buildGroupSection(groupBy: …|null, options?: {data_group_id?: number|null}): Array<Record<string, unknown>>
buildFilterEntry(f: Filter): Record<string, unknown>
buildFlowPropertyFilter(filters: readonly Filter[]): Record<string, unknown>
buildFlowCohortFilter(where: Filter|readonly Filter[]): Record<string, unknown>|null
buildFrequencyGroupEntry(fb: FrequencyBreakdown, options?: {data_group_id?: number|null}): Record<string, unknown>
buildFrequencyFilterEntry(ff: FrequencyFilter): Record<string, unknown>
buildTimeComparison(tc: TimeComparison): {type: string, value: string}
```

Python `None` defaults → `null`; absent and `null` equivalent wherever the Python
default is `None`.

### Guard codes owned (K2) — ALL corpus-present

BB1_GROUP_BY_ELEMENT_TYPE (`ParamTypeError`, 5 vectors),
BB2_FLOW_PROPERTY_FILTER_EMPTY (3), BB3_FLOW_PROPERTY_FILTER_TYPE
(`ParamTypeError`, 3), BB4_FLOW_COHORT_FILTER_TYPE (4),
BB5_FLOW_MULTIPLE_COHORT_FILTERS (3), BB6_COHORT_VALUE_NOT_LIST (2),
BB7_COHORT_VALUE_NOT_DICT (2), BB8_COHORT_KEY_MISSING (2) — all
`ParamValidationError` unless noted. No corpus-silent coded branches; the two
TC1/TC2 assertion guards are unreachable by contract (do not fuzz for them,
document the omission).

### Layer-3 test translation (K2)

| Python source | Translate now | Defer note |
|---|---|---|
| `tests/unit/test_bookmark_builders.py` (1,396, 18 classes) | all builder-direct classes → `bookmarks/builders.test.ts` | any class driving `workspace.build_*params` → B5-S2, header citation |
| `tests/unit/test_bookmark_builders_pbt.py` (394, 4 classes) | all (fast-check twins) | — |
| `tests/test_custom_property_builders.py` (461) | `TestBuildComposedProperties`, `TestBuildGroupSectionCustomProperties`, `TestBuildFilterEntryCustomProperties` (builder-direct; the corpus extracts 15 K2 vectors from this file) | `TestMeasurementPropertyBuilder` + any facade-driving class → B5, header citation. **Playbook-omission note**: this file is absent from the playbook B3 Layer-3 list but is a measured vector source for K2 apis — translating its builder-direct classes is IN scope (R10.1; log in the notes file) |
| `tests/test_build_cohort_params.py` (1,034) | — | B5 Layer-3 (playbook B5 row); its 16 `build_flow_cohort_filter` vectors replay at B3 regardless (vector api gates, not test-file ownership) |
| `tests/test_query_params.py` | — | same: B5 file, its 14 K2 vectors replay at B3 |

### R10.10 consumer packet (K2)

Measured importers: `workspace.py` ONLY (import block `workspace.py:70-81`).
Call sites (B5-S2 unless noted):

- `workspace.build_params` path: metric behavior filters
  `[build_filter_entry(f) for f in item_filters]` `:2204`; `build_time_section`
  `:2237`; `build_filter_section(where)` `:2245`; `build_group_section(group_by,
  data_group_id=…)` `:2248`; `build_time_comparison` `:2268`.
- `workspace.build_funnel_params`: per-step filters `:2820`; time `:2891`;
  **`patch_custom_property_filters_for_transform(build_filter_section(where))`**
  `:2897-2899`; group `:2900`; time-comparison `:2913`.
- `workspace.build_retention_params`: behavior filters `:3392`; time `:3425`;
  patch+filter `:3431-3433`; group `:3434`; time-comparison `:3447`.
- `workspace.build_flow_params`/`query_flow`: `build_date_range` `:3591`;
  `build_flow_cohort_filter` `:3622`; `build_flow_property_filter` `:3627`;
  `build_group_section(segments)` `:3631` (NO data_group_id kwarg here — default
  None).
- B6: `create_cohort`/`update_cohort` flattening reaches
  `_build_cohort_group_entry` only via `sanitizeRawCohort` (types, ported).

Api-map rows of the five B5 builder members (verbatim; also in b2-packets §V1a):

```json
{"name":"build_params","params":["events"],"kwonly":["from_date","to_date","last","unit","math","math_property","per_user","percentile_value","group_by","where","formula","formula_label","rolling","cumulative","mode","time_comparison","data_group_id"],"returns":"dict[str, Any]","batch":"B5","ts_signature":"async build_params(events, from_date, to_date, …): Promise<Record<string, unknown>>"}
{"name":"build_funnel_params","params":["steps"],"kwonly":["conversion_window","conversion_window_unit","order","from_date","to_date","last","unit","math","math_property","group_by","where","exclusions","holding_constant","mode","reentry_mode","time_comparison","data_group_id"],"returns":"dict[str, Any]"}
{"name":"build_flow_params","params":["event"],"kwonly":["forward","reverse","from_date","to_date","last","conversion_window","conversion_window_unit","count_type","cardinality","collapse_repeated","hidden_events","mode","where","data_group_id","segments","exclusions"],"returns":"dict[str, Any]"}
{"name":"build_retention_params","params":["born_event","return_event"],"kwonly":["retention_unit","alignment","bucket_sizes","from_date","to_date","last","unit","math","group_by","where","mode","unbounded_mode","retention_cumulative","time_comparison","data_group_id"],"returns":"dict[str, Any]"}
{"name":"query_saved_report","params":["bookmark_id"],"kwonly":["bookmark_type","from_date","to_date"],"returns":"SavedReportResult","batch":"B5"}
```

Ergonomics consequence: builder inputs are the REAL ported classes (Filter etc.),
not duck shapes — `instanceof` discrimination is the contract; the facade
forwards user-constructed instances unchanged.

### R10.9 harness spec (K2)

- **Existing family un-skips**: `build_filter_entry`
  (`strategies.py:214-217`, `_filter_calls`/`_filter_edges` incl. the shared
  `_EDGE_FILTERS` at `:102-116`) starts answering once (b′) lands — re-run ≥500.
  The B20B non-finite `filterValue` note (`strategies.py:119-123`) stands:
  NaN operands stay corpus-authored, not fuzzed.
- **NEW families** (extend `strategies.py`, ≥500 each):
  `build_filter_section_family` (None / single Filter / single FrequencyFilter /
  mixed lists incl. skip-branch foreign elements — dicts/ints inside the list),
  `build_group_section_family` (str / GroupBy plain / GroupBy+CustomPropertyRef /
  GroupBy+InlineCustomProperty / GroupBy list_item mode / CohortBreakdown saved+
  inline ± include_negated / FrequencyBreakdown / mixed lists / BB1 foreign
  elements / bucket_size±min±max combos / data_group_id present+absent),
  `build_flow_property_filter_family` (empty → BB2, CustomPropertyRef → BB3,
  plain strs), `build_flow_cohort_filter_family` (empty list → None, non-cohort →
  BB4, two cohorts → BB5, malformed `_value` shapes → BB6/BB7/BB8 via direct
  Filter construction, saved id vs raw_cohort, negated operator),
  `build_frequency_filter_entry_family` (operator×value×label×date_range×
  event_filters grid), `build_time_section_family` + `build_date_range_family`
  (absolute/from-only/relative; from-only exercises the frozen `today`).
  NOT oracle-fuzzed (no registry name — document the omission in the strategy
  file exactly as `strategies.py:253-257` does):
  `build_time_comparison`, `build_frequency_group_entry`,
  `patch_custom_property_filters_for_transform`, `_build_composed_properties`
  (locked by Layer-3 now and by the B5 `workspace.build_*params` vectors later).
- **Mandatory edge set**: the fixed R10.9 items (`18.0` arrives as the PyFloat
  carrier; `True`; `None`; `[]`; `""`; `"𝒳"` as event names/labels/property
  names) + every BB code above + one probe per conditional-key branch
  (`filterDateUnit`, `customBucket.min/max`, `dateRange`, `eventFilters`,
  `label`, `id` vs `raw_cohort`).

### Done-criteria (K2)

TS files on disk; `tsc --strict` clean; translated tests green; after (b′): all
134 K2 vectors PASS, 0 FAIL (batch-status stays `pending` until the gate); R10.9
RUN record in `B3-notes.md`; `npm run check` green; `just check` green
(strategies.py changed); one commit per repo; local commits only.

## Packet K3 — segfilter + expressions + transforms

**Model**: opus, effort ≤ high, R10.13 incremental protocol. **Vectors: 83**
(`segfilter.build_segfilter_entry` 51 · `expressions.normalize_on_expression` 30 ·
`transforms.transform_profile` 2; `transforms.transform_event` is registered but
has ZERO vectors — oracle-fuzz + Layer-3 only).

### Python sources

`src/mixpanel_headless/_internal/segfilter.py` (323 LOC, whole file):

| Range | Contents |
|---|---|
| 39–98 | operator tables: `RESOURCE_TYPE_MAP` `:39-44`, `STRING_OPERATOR_MAP` `:47-54`, `NUMBER_OPERATOR_MAP` `:57-70`, `DATETIME_OPERATOR_MAP` `:73-85` (+ the `was before`→`">"` inversion comment `:76-79` — keep it), `_SETNESS_OPS`/`_NUMBER_RANGE_OPS`/`_DATETIME_RELATIVE_OPS`/`_DATETIME_RANGE_OPS` frozensets `:89-98` → ReadonlyMap/ReadonlySet (R4.8) |
| 106–122 | `_convert_date_format` — `year, month, day = date_str.split("-")` `:121` is **watchlist #1 tuple-unpacking arity** (Python raises ValueError on ≠3 parts; TS destructuring silently binds undefined → port an explicit length===3 check that throws the uncoded-raise twin; see Cautions §9); `zfill(2)` on month/day → compat `zfill` (R11.4), then `f"{m}/{d}/{year}"` |
| 130–158 | `_build_string_filter` — unknown op → **SG1_UNKNOWN_STRING_OPERATOR** `:144-149` (message embeds `sorted(STRING_OPERATOR_MAP)` — `sortedByCodepoint`, display-only); setness ops → operand `""` |
| 161–191 | `_build_number_filter` — unknown op → **SG2** `:175-180`; setness → `""`; range ops → `[str(v) for v in value]` `:187`; else `str(value)` `:189` — **THE two R10.11 positions** (see below) |
| 194–205 | `_build_boolean_filter` — NO `operator` key, only `operand: operator` (the string `"true"`/`"false"`) |
| 208–251 | `_build_datetime_filter` — unknown op → **SG3** `:232-237`; relative ops: operand = value verbatim + `unit: f"{date_unit}s"` pluralization `:245` only when `date_unit` non-None; range ops: `[_convert_date_format(d) for d in value]` `:247`; else `_convert_date_format(str(value))` `:249` — `str(value)` here is `pythonStr` (a non-str value stringifies THEN date-splits; probe `str` on the reachable `_value` types before assuming identity) |
| 259–323 | `build_segfilter_entry(f)` — `RESOURCE_TYPE_MAP.get(rt, rt)` fallback-to-self `:297`; property-type dispatch string/number/boolean/datetime else **SG4_UNSUPPORTED_PROPERTY_TYPE** `:308-312`; output key order `property{name,source,type}, type, selected_property_type, filter` `:314-323` |

`src/mixpanel_headless/_internal/expressions.py` (52 LOC, whole file):
`_FILTER_EXPR_ACCESSORS = ('properties["', 'user["', 'event["')` `:12`;
`normalize_on_expression(on)` `:15-52` — substring pass-through check `:47`
(`accessor in on` → `String.prototype.includes`), else escape
**backslashes FIRST, then double quotes** `:51`
(`on.replace("\\", "\\\\").replace('"', '\\"')` — Python `str.replace` replaces
ALL occurrences: TS MUST use `replaceAll`, never single-occurrence `replace`
with a string pattern) and wrap `properties["…"]`.

`src/mixpanel_headless/_internal/transforms.py` (130 LOC, whole file):

| Range | Contents |
|---|---|
| 18 | `RESERVED_EVENT_KEYS` frozenset (export for parity; consumers at B4) |
| 21–80 | `transform_event(event)` — shallow-copies `properties` `:60`, pops `distinct_id` (default `""`), `time` (default `0`), `$insert_id` (default None); **`datetime.fromtimestamp(event_time_raw, tz=timezone.utc)`** `:67`; **`str(uuid.uuid4())` when `$insert_id` is None** `:70-72` (logs debug — logging is out of contract); returns `{event_name: event.get("event",""), event_time, distinct_id, insert_id, properties: remaining}` |
| 85 | `RESERVED_PROFILE_KEYS` frozenset |
| 88–130 | `transform_profile(profile)` — `$distinct_id` default `""`, `$properties` default `{}`, pops `$last_seen` (default None); pure, no seams |

### transforms determinism seams (replay notes)

Recorder/oracle-py context: `conformance/record/clock.py` freezes the clock at
the record epoch (freezegun) and replaces `uuid.uuid4` with a counter-seeded
stream, template `"00000000-0000-4000-8000-{seq:012d}"` (`clock.py:30`), counter
reset per vector. TS runner twin: `createShims(recordEpoch)`
(`conformance-runner/src/shims.ts:90-115`) — SAME template
(`padStart(12, "0")` counter) + `now()`/`today()` off the epoch. Port
`transformEvent` with injectable seams `{uuid?: () => string}` (library default
`crypto.randomUUID()`); the (b′) binding passes `context.shims.uuid`. There is no
`now()` read in `transform_event` — the clock enters only through
`fromtimestamp` of the INPUT value; no clock seam needed.

**`event_time` representation (design decision, binding)**: Python returns a
`datetime`; the rig serializes it as `{"$type": "datetime", "iso":
value.isoformat()}` (`conformance/record/codecs.py:227-228`; TS `PyDatetime`
carrier, `conformance-runner/src/codecs.ts:66-74,559-560`). The TS library
returns `event_time` as **Python-isoformat TEXT** (Phase-2 precedent: result
models keep datetimes as iso text, `types/entities/model-base.ts:20,489-526`),
computed by a PURE arithmetic UTC formatter (days-from-epoch civil-date
conversion + `zfill` padding; **never `new Date()`** — watchlist #5, and JS Date
truncates to ms while CPython keeps µs). Python spelling:
`datetime.fromtimestamp(0, tz=utc).isoformat()` → `"1970-01-01T00:00:00+00:00"`
(offset `+00:00` not `Z`; NO fractional part for integral seconds; `.%f` 6-digit
µs when fractional). The `time` value is in-annotation `Any` (dict interior —
ratified Discrepancy #8): fuzz WILL send floats and negatives. **Mandatory
CPython probe** (record in B3-notes): `fromtimestamp` µs rounding for float
inputs (round-half-even at µs), negative timestamps, and large values; mirror
exactly; bias the fuzz domain to int seconds + µs-representable floats and
document any excluded pathological range (e.g. |t| beyond datetime.max) as a
domain note. The binding wraps the returned iso text in `PyDatetime` for
comparison.

### TS homes

- `packages/core/src/query/segfilter.ts` (NEW) — whole module.
- `packages/core/src/query/expressions.ts` (NEW) — whole module.
- `packages/core/src/query/transforms.ts` (NEW) — whole module (playbook home).
- Compat imports: `zfill`, `pythonStr`, `pythonFloatStr`, `sortedByCodepoint`
  from `compat` (R11.7/R10.8). None of these files enter the package barrel.

### R10.11 — the ONLY sanctioned numeric-string positions (segfilter)

`_build_number_filter` `:187` (`[str(v) for v in value]`) and `:189`
(`str(value)`) are the number-operand positions R10.11 covers: the TS port uses
**natural JS number rendering** (`String(v)`: `18.0` → `"18"`), and the
conformance canonicalizer normalizes numeric strings ONLY there
(`conformance-runner/src/canonical.ts:21,52-73` — rule 4, `filter.operand`
direct/element positions of number-typed segfilter entries). Two hard
corollaries the review pair checks: (1) NO other B3 site may rely on that
normalization — `user_builders._format_value` and `expressions` escaping are
verbatim-string contracts (see K4); (2) non-numeric operand values reaching
`:189` (e.g. `str(True)` → `"True"`, `str(None)` → `"None"`, `str("x")` → `"x"`)
are NOT numeric strings — the canonicalizer passes them through, so those
renderings must be `pythonStr`, not `String()` (watchlist #8: `String(true)` =
`"true"` ≠ `"True"`). Implement operand rendering as: numbers (incl. PyFloat
carrier spellings via the established unwrap) → natural JS rendering; everything
else → `pythonStr`.

### Guard codes owned (K3) — ALL corpus-present

SG1_UNKNOWN_STRING_OPERATOR (2 vectors), SG2_UNKNOWN_NUMBER_OPERATOR (2),
SG3_UNKNOWN_DATETIME_OPERATOR (2), SG4_UNSUPPORTED_PROPERTY_TYPE (4) — all
`ParamValidationError`. `expressions`/`transforms` own no coded raises.
Uncoded-raise branch: `_convert_date_format` arity failure (malformed date
string in a datetime Filter) — see Cautions §9.

### Layer-3 test translation (K3)

| Python source | Translate now | Defer note |
|---|---|---|
| `tests/unit/test_segfilter.py` (634; 10 classes: StringOperators, NumberOperators, BooleanOperators, DatetimeOperators, ResourceTypeMapping, Structure, ConvertDateFormat, EdgeCases, CodedSegfilterCodes) | all → `query/segfilter.test.ts` | — |
| `tests/unit/_internal/test_expressions.py` (114) + `test_expressions_pbt.py` (143) | all → `query/expressions.test.ts` (+ fast-check twin; strategy shapes vendored at `strategies.py:291-309` — keep in sync note) | — |
| `tests/test_query_user_structural.py` | ONLY `TestTransformProfileMissingDistinctId` (`:492`) + `TestTransformProfileCompletelyEmpty` (`:509`) → `query/transforms.test.ts`, header noting the split | rest of file → B5 (playbook B5 row) |
| `tests/test_transform_funnel.py` (524) / `tests/test_transform_retention.py` (613) | — **NONE** | **Playbook-misassignment discrepancy (log in notes + gate report)**: both files test `_internal/services/live_query.py` internals (`_transform_funnel_result`, `_extract_funnel_steps_from_series`, `_transform_retention_result` — imports at `test_transform_funnel.py:8-12`, `test_transform_retention.py:9`), a **B5-S2** module. The playbook B3 row lists them by name-match error. Defer to B5 with this citation; translating them at K3 would violate R10.1 (no implementation exists to test) |

`transform_event` Layer-3 gap: no Python unit file drives it directly (only
workspace streaming tests — B4/B6 scope). K3 writes NEW Vitest cases from the
docstring example (`transforms.py:36-55`) + the probe findings (missing keys,
`time` 0 default, uuid-fill branch with an injected uuid seam, µs rendering) —
mark them `// NEW (no Python source test; docstring + probe locked)`.

### R10.10 consumer packet (K3)

- `segfilter`: ONE importer — `workspace.py:100` → flow step filters
  `[build_segfilter_entry(f) for f in (step.filters or [])]` `:3582`
  (B5-S2 `build_flow_params`/`query_flow`). Api-map row:

```json
{"name":"query_flow","batch":"B5","params":["event"],"kwonly":["forward","reverse","from_date","to_date","last","conversion_window","conversion_window_unit","count_type","cardinality","collapse_repeated","hidden_events","mode","where","data_group_id","segments","exclusions"],"returns":"FlowQueryResult","ts_signature":"async query_flow(event, forward, reverse, …): Promise<FlowQueryResult>"}
```

- `expressions`: ONE importer — `services/live_query.py:17` →
  `normalize_on_expression(on)` at `:749` (segmentation, `if on else None` guard)
  and `:1436/:1493/:1549` (segmentation_numeric/sum/average) — all B5-S2.
  Api-map row:

```json
{"name":"segmentation","batch":"B5","params":["event"],"kwonly":["from_date","to_date","on","unit","where"],"returns":"SegmentationResult","ts_signature":"async segmentation(event, from_date, to_date, …): Promise<SegmentationResult>"}
```

- `transforms`: importer `workspace.py:107` — `transform_event` in
  `stream_events` `:1467` (**B4-C2**), `transform_profile` in `stream_profiles`
  `:1577` (B4-C2) and the `query_user` result paths `:9686/:9707/:10116/:10160`
  (B5-S2). Api-map rows:

```json
{"name":"stream_events","batch":"B4","params":[],"kwonly":["from_date","to_date","events","where","limit","raw"],"returns":"Iterator[dict[str, Any]]","ts_signature":"stream_events(from_date, to_date, events, …): AsyncIterable<dict[str, Any]>"}
{"name":"stream_profiles","batch":"B4","params":[],"kwonly":["where","cohort_id","output_properties","raw","distinct_id","distinct_ids","group_id","behaviors","as_of_timestamp","include_all_users"],"returns":"Iterator[dict[str, Any]]","ts_signature":"stream_profiles(where, cohort_id, output_properties, …): AsyncIterable<dict[str, Any]>"}
{"name":"query_user","batch":"B5","params":[],"kwonly":["where","cohort","properties","sort_by","sort_order","limit","search","distinct_id","distinct_ids","group_id","as_of","mode","aggregate","aggregate_property","percentile","segment_by","parallel","workers","include_all_users"],"returns":"UserQueryResult","ts_signature":"async query_user(where, cohort, properties, …): Promise<UserQueryResult>"}
```

  Ergonomics consequence: B4-C2 consumes `transformEvent` per streamed line —
  the `raw` flag bypasses it; the `uuid` seam must be threadable from the B4
  client options so streaming vectors replay deterministically at B4. Ship the
  seam on the function signature now; B4 wires it.

### R10.9 harness spec (K3)

- **Existing family un-skips** (≥500 each once (b′) lands):
  `build_segfilter_entry` (`strategies.py:208-211`), `normalize_on_expression`
  (`:327-345`).
- **NEW families**: `transform_event_family` (dicts with/without
  `event`/`properties`; `time` as int/float(µs)/0/negative/absent; `$insert_id`
  present/absent/None; extra properties preserved; non-BMP keys),
  `transform_profile_family` (`$distinct_id`/`$properties`/`$last_seen`
  present/absent grid), ≥500 each. Segfilter strategy EXTENSION: the shared
  `_filter_calls` domain must additionally reach every operator row of all three
  maps (incl. `is equal to`, `not between`, `was not in the`, setness ops on
  number type) and boolean/datetime filters with `date_unit` set/None — audit
  `filter_strategy()` coverage against the three tables and extend where a row
  is unreachable (edge_calls per uncovered row).
- **Mandatory edge set**: fixed R10.9 items (`_EDGE_FILTERS`,
  `strategies.py:102-116`, already encode them for the Filter dialects — reuse)
  + every SG code + `_convert_date_format` on `"2026-1-5"`/`"01/15/2026"`/junk
  (arity branch) + `transform_event` `time: 18.0` (PyFloat carrier) and
  `time: 1.5` + empty-dict inputs + `"𝒳"` event name.

### Done-criteria (K3)

`tsc --strict` clean; translated tests green (incl. the NEW transform_event
suite); after (b′): 83 K3 vectors PASS; fromtimestamp probe transcript + RUN
record in `B3-notes.md`; `npm run check` green; `just check` green; commits.

## Packet K4 — user_builders selector path (heaviest-fuzz mandate)

**Model**: opus, effort ≤ high, R10.13 incremental protocol. **Vectors: 82**
(`filter_to_selector` 53 · `filters_to_selector` 20 · `extract_cohort_filter` 9).
This is **semantic-trap watchlist #2** — "the single riskiest translation in the
whole port". The R10.9 budget DOUBLES (playbook P3-6: ≥1,000 examples for the two
selector entry points) with adversarial Unicode/quote/backslash inputs.

### Python sources

`src/mixpanel_headless/_internal/query/user_builders.py` (322 LOC; the builders
half — `_is_cohort_filter` `:69-85` already landed at B2-V2 as `isCohortFilter`
in `packages/core/src/query/user-builders.ts`, which this shard GROWS):

| Range | Contents |
|---|---|
| 27–42 | `_format_value(value: str\|int\|float)` — strings: escape backslash-first then quotes (`value.replace("\\","\\\\").replace('"','\\"')` `:40` — ALL occurrences → `replaceAll`) and wrap in `"…"`; non-strings: **`str(value)` `:42` → `pythonStr`** (`str(2.0)` = `"2.0"`, `str(True)` = `"True"`, `str(1e16)` = `"1e+16"` — R11.1/R11.2; NO canonicalizer help here, the `selector_str` output codec compares VERBATIM). NOTE Python `bool` IS `int`: `True`/`False` pass every `isinstance(...(int, float))` gate in this module and render capitalized — the TS twin must accept booleans wherever it accepts numbers and render via `pythonStr` (in-annotation per ratified Discrepancy #8: `bool <: int`) |
| 45–66 | `_prop_ref(f)` — non-str property → **ES1_PROPERTY_NOT_STRING** `:58-64`; same backslash-then-quote escaping `:65`; wraps `properties["…"]` |
| 69–85 | `_is_cohort_filter` — B2-landed; IMPORT, never re-declare (R10.8; the file header already names B3-K4 as grower) |
| 88–242 | `filter_to_selector(f)` — **evaluation order is contract**: `op = f._operator`, then `prop = _prop_ref(f)` `:117` (ES1 fires BEFORE any operator check), then per-op: `equals` `:120-146` (non-list → **ES2**; scalar-filtered parts with `isinstance(v,(str,int,float))` `:127-130`; dropped non-scalars → `logger.warning` `:132-137` (out of contract); zero parts → **ES3**; >1 part → `"(" + " or ".join + ")"`; exactly 1 → bare part); `does not equal` `:148-174` (**ES4**/**ES5**; `" and ".join` — NO parens, comment `:172-173` explains the and/or asymmetry — keep it); `contains` `:176-182` (**ES6**; emits `{value} in {prop}` — value FIRST); `does not contain` `:184-190` (**ES7**; `not {value} in {prop}`); `is greater than` `:192-198` (**ES8**); `is less than` `:200-206` (**ES9**); `is between` `:208-225` (non-list or len≠2 → **ES10**; `lo`/`hi` element checks → **ES11**/**ES12**; emits `{prop} >= {lo} and {prop} <= {hi}`); `is set` → `defined({prop})` `:227-228`; `is not set` → `not defined({prop})` `:230-231`; `true`/`false` → `{prop} == true` / `{prop} == false` `:233-237` (LOWERCASE literals — these are selector-language keywords, NOT Python str(bool)); fallthrough → **ES13_UNSUPPORTED_OPERATOR** `:239-242` (message uses `{op!r}` — pythonRepr, display-only) |
| 245–275 | `filters_to_selector(filters)` — empty list → `""` `:273-274` (empty STRING, not None); else `" and ".join(filter_to_selector(f) for f in filters)` — first error propagates (generator: elements after the failing one are never evaluated; port with a loop, not `.map()` then join, so error ORDER matches) |
| 278–322 | `extract_cohort_filter(filters)` — returns TUPLE `(remaining, cohort\|None)`; first cohort wins; EXTRA cohorts go to `remaining` + `logger.warning` `:315-319` (warning out of contract, placement of extras IS contract); non-cohorts keep relative order |

### TS homes

- `packages/core/src/query/user-builders.ts` — GROW the B2 stub: add
  `formatValue` (module-private), `propRef` (module-private),
  `filterToSelector`, `filtersToSelector`, `extractCohortFilter`. Import
  `isCohortFilter` (already exported here) and `isPythonDict` (re-exported here
  from `validation-shared.ts` — watchlist #13) — never re-derive.
- Compat: `pythonStr` (and via it `pythonFloatStr`) for `_format_value`
  non-string rendering; NO `String(...)` on operand values anywhere in this file.
- Not in the package barrel (Python keeps `_internal`).

### TS signatures

```
filterToSelector(f: Filter): string
filtersToSelector(filters: readonly Filter[]): string
extractCohortFilter(filters: readonly Filter[]): [Filter[], Filter | null]
```

`extract_cohort_filter` identity semantics: the SAME Filter instances flow
through to the outputs (locked by
`…-test_cohort_filter_identity_preserved`; the vector encodes each Filter
structurally as its Python-spelled field dict — `_property`, `_operator`,
`_value`, `_property_type`, `_resource_type`, `_date_unit`,
`_list_item_filters`, `_list_item_quantifier` — via the Phase-2 Filter codec;
the tuple encodes as a 2-element JSON array).

### Guard codes owned (K4) — ALL corpus-present (both entry points)

ES1_PROPERTY_NOT_STRING, ES2_EQUALS_EXPECTS_LIST, ES3_EQUALS_NO_TERMS,
ES4_NOT_EQUALS_EXPECTS_LIST, ES5_NOT_EQUALS_NO_TERMS, ES6_CONTAINS_EXPECTS_STR,
ES7_NOT_CONTAINS_EXPECTS_STR, ES8_GT_EXPECTS_NUMBER, ES9_LT_EXPECTS_NUMBER,
ES10_BETWEEN_EXPECTS_PAIR, ES11_BETWEEN_LOWER_NOT_NUMBER,
ES12_BETWEEN_UPPER_NOT_NUMBER, ES13_UNSUPPORTED_OPERATOR — all
`ParamValidationError`. Corpus splits: 20 error vectors on `filter_to_selector`
(all 13 codes), 13 on `filters_to_selector` (all 13 via propagation). No
corpus-silent codes.

Type-check subtleties per code (review-pair lines): ES2/ES4/ES10 `isinstance(value, list)`
→ `Array.isArray`; ES6/ES7 `isinstance(value, str)` → `typeof === "string"`;
ES8/ES9/ES11/ES12 `isinstance(v, (int, float))` → accepts number AND boolean AND
the rig's PyFloat carrier (integral floats arrive as the carrier through
oracle/codec decode — the check must classify carrier-as-number exactly where
Python classifies float-as-number; follow the B2 Cautions §8 idiom and unwrap
ONLY at rendering time via `pythonStr` of the carrier's spelling).

### Layer-3 test translation (K4)

| Python source | Translate now | Defer note |
|---|---|---|
| `tests/test_user_builders.py` (710; 18 classes `:27-514` incl. `TestFilterToSelectorValueFormatting`, `TestFilterToSelectorPropertyEscaping`, `TestCodedEngageSelectorCodes`) | WHOLE file → `query/user-builders.test.ts` | — |
| `tests/test_query_user_edge_cases.py` | — | B5 Layer-3 (b2-packets §V2 precedent); its 3 K4 vectors replay at B3 |
| `tests/test_query_user_structural.py` | `TestPbtFormatValueSpecialChars` (`:416`) + `TestFiltersToSelectorOrAndPrecedence` (`:461`) → appended to `user-builders.test.ts` with a split-header citation | rest → B5 (K3 takes the two transform_profile classes) |

R10.2: the escaping asserts (`TestFilterToSelectorPropertyEscaping`,
`TestFilterToSelectorValueFormatting`, `TestPbtFormatValueSpecialChars`)
translate VERBATIM — these are the watchlist-#2 locks; any loosening is an
automatic review finding.

### R10.10 consumer packet (K4)

Measured importers: `workspace.py:89-90` (`extract_cohort_filter`,
`filters_to_selector`) + `user_validators.py` (B2, `_is_cohort_filter` only).
Call sites (all B5-S2): `workspace.query_user` →
`remaining, cohort_from_filter = extract_cohort_filter(filters_list)` `:9471`
then `selector = filters_to_selector(remaining)` `:9474` (feeds the engage
`where` param). `filter_to_selector` has no direct facade caller — it is the
per-element worker (and the doubled-fuzz surface). Api-map rows for the
consumers (`query_user`, `build_user_params`) are pasted in §K3 and §K2
respectively; `build_user_params` row verbatim:

```json
{"name":"build_user_params","batch":"B5","params":[],"kwonly":["where","cohort","properties","sort_by","sort_order","search","distinct_id","distinct_ids","group_id","as_of","mode","aggregate","aggregate_property","percentile","segment_by","limit","parallel","workers","include_all_users"],"returns":"dict[str, Any]","ts_signature":"async build_user_params(where, cohort, properties, …): Promise<Record<string, unknown>>"}
```

Ergonomics: selectors are OPAQUE STRINGS to every consumer — no consumer parses
them back; fidelity is purely char-for-char.

### R10.9 harness spec (K4) — DOUBLED budget

- **Existing families un-skip**: `filter_to_selector` (`strategies.py:167-170`),
  `filters_to_selector` (`:190-206`) — both run at **≥1,000 examples** (P3-6 K4
  mandate; every other family keeps ≥500). `extract_cohort_filter`: NEW family
  (≥500; lists mixing property filters, 0/1/2 cohort filters, order
  preservation, empty list).
- **Adversarial escaping extension (MANDATORY)**: extend the drawn Filter
  domain (property names AND string values) with an escaping-biased alphabet:
  lone backslash, trailing backslash (`"a\\"`), doubled backslashes, `"` and
  `\"` sequences, `\\"` compounds, single quotes, newlines/tabs/CR, non-BMP
  (`"𝒳"`, emoji + variation selectors), combining marks, U+FEFF/U+200B, strings
  containing the literal accessor text `properties["` (selector-injection
  shape), and `' or '`/`' and '` fragments (operator-injection shape). Also
  numeric-value bias: integral floats (PyFloat carrier), `-0.0`, huge/small
  exponents (`1e16`, `1e-5` — pythonFloatStr exponent switch points), and
  booleans in equals-lists.
- **Mandatory edge set**: the fixed R10.9 items (via `_EDGE_FILTERS`, which
  already encodes the documented None-omission) + one probe per ES code per
  entry point + `filters_to_selector([])` (empty string) + a two-element list
  where the SECOND filter errors (generator-order lock).
- Zero unexplained divergences; shrunken repros to
  `conformance/differential/repros/` block the task.

### Done-criteria (K4)

`tsc --strict` clean; translated tests green; after (b′): 82 K4 vectors PASS;
doubled-budget RUN record (≥1,000 × 2 families + ≥500 extract family) in
`B3-notes.md`; `npm run check` green; `just check` green; commits.

## Binding plan — fable (b′) task

Rig code — **fable only** (P3-3 rig row; P3-6 step 3). New registration module
`registerBuilderBindings(implementations, codecs)` in
`conformance-runner/src/bindings.ts` (pattern: `registerValidatorBindings`,
bindings.ts:1081), shared with oracle-ts through the same registry (one
registration point, P3-2 b′). P3-5 rule-3 honesty check applies to EVERY
binding: call the ported public entry point; never re-derive a transform, never
filter/reorder outputs beyond the structural encodings below.

### Registry entry names (17 — bind ALL, including the three zero-vector ones)

```
bookmark_builders.build_filter_entry        bookmark_builders.build_filter_section
bookmark_builders.build_frequency_filter_entry  bookmark_builders.build_group_section
bookmark_builders.build_flow_property_filter    bookmark_builders.build_flow_cohort_filter
bookmark_builders.build_date_range          bookmark_builders.build_time_section
segfilter.build_segfilter_entry             expressions.normalize_on_expression
transforms.transform_event                  transforms.transform_profile
user_builders.filter_to_selector            user_builders.filters_to_selector
user_builders.extract_cohort_filter         bookmark_schema.get_root_model_for_bookmark_type
bookmark_schema.validate_with_pydantic
```

Source of truth: `conformance/record/registry.py` `_builder_entries()`
(`:194-289` — 15 of the 17; the two `bookmark_schema.*` names sit at `:316-323`
in the same tuple and at `:493-500` in `_validator_entries()`).
`transforms.transform_event`, `bookmark_schema.get_root_model_for_bookmark_type`
and `bookmark_schema.validate_with_pydantic` have ZERO corpus vectors but MUST
bind: the B3 gate probe issues one `oracle.call` per newly registered name on
BOTH bridges (P3-2e step 3), and the gate flip makes any unbound straggler
under a flipped prefix a FAIL_ERROR. This closes the B2 gate-notes exclusion
("`bookmark_schema.validate_with_pydantic` is NOT bound at B2 … the B3 binder
picks it up", b2-packets §Binding-plan).

### validate_with_pydantic — adapter retarget (Python-side rig change + re-pin)

`validate_with_pydantic(model_cls, raw, *, path_prefix, code_mapper)` takes a
MODEL CLASS — not JSON-transportable. The (b′) task adds a flattening adapter in
`conformance/record/adapters.py` (precedent: `selector_label_fn`,
`registry.py:307-311` `_ADAPTERS_MODULE`) accepting `model: str` (one of
`"InsightsBookmarkSortConfig" | "InsightsBookmarkParams" | "FlowsBookmarkParams"
| "Sections" | "DisplayOptions"`) + `value` + optional `path_prefix`, resolving
over a fixed name→class map and forwarding with the DEFAULT code mapper (the
`_sorting_code_mapper` path is already fuzz-covered through
`validation.validate_sorting_block`, bound at B2). Retarget the registry entry
to the adapter. This is a Python-side registry change → **corpus re-pin event**
(P3-7 trigger 1): re-run `scripts/sync-corpus.sh`, D9 drift check (trivially
clean — zero vectors carry the api), re-run the P3-0 count measurement (must
still read 3,251), and commit the re-pin. The TS binding mirrors: name →
root-model handle map over K1's `getRootModelForBookmarkType` +
`PARTIAL_UPDATE_SUB_MODELS` + the B2 sorting validator; output codec
`validation_errors` (`[{code, path, severity}]`, emission order preserved —
identical to the B2 encoder, bindings.ts:928).

### Binding shapes

- **Decode**: `context.kwargs` through the shared `CodecRegistry`. Measured B3
  input `$type` tallies: `Filter` 246 · `GroupBy` 18 · `PropertyInput` 15 ·
  `InlineCustomProperty` 12 · `FrequencyFilter` 11 · `CustomPropertyRef` 10 ·
  `FrequencyBreakdown` 3 · `ListItemGroupMode` 3 · `CohortBreakdown` 1 — all
  Phase-2 contract codecs. A decode `UndecodableValueError` on a B3 vector is a
  codec-table gap → fable rig fix, not a module workaround.
- **Encode (dict/list outputs)**: K2 builders + `segfilter` return plain
  dicts/lists — encode via the standard codec path (canonicalize handles key
  sorting; emission order of ARRAYS is contract). **PyFloat discipline**: pass
  decoded kwargs through UNCONVERTED; the ONLY sanctioned unwrap points are (i)
  number-operand rendering inside the ported functions via `pythonStr`
  spellings and (ii) the vector-codecs.ts:606-611 non-finite precedent. Any
  other unwrap in a BINDING is a binding-honesty smell — flag to the arbiter.
- **Encode (`selector_str`)**: `filter_to_selector`/`filters_to_selector`
  return strings VERBATIM (`codecs.py:786-789` twin) — no trimming, no
  normalization.
- **Encode (tuple)**: `extract_cohort_filter` → 2-element JSON array; element 0
  = array of encoded Filters, element 1 = encoded Filter or `null` (Phase-2
  Filter codec — Python-spelled `_`-fields).
- **Encode (PyDatetime)**: `transform_event().event_time` iso text wraps as
  `new PyDatetime(iso)` (codecs.ts:66-74) so `encode` emits
  `{"$type":"datetime","iso":…}` byte-matching Python `isoformat()`.
- **Encode (`model_name`)**: `get_root_model_for_bookmark_type` → the handle's
  `.name` string, or `null` (codecs.py:780-784 twin).
- **Seams**: `build_time_section` ← `context.shims.today()`;
  `transforms.transform_event` ← `context.shims.uuid` (templates already
  matched: `clock.py:30` ↔ `shims.ts:107-110`; counters reset per vector on
  both sides). No fetch/sleep/random anywhere in B3.
- **Errors**: wrap invocations in the `runGuarded`/`CoreLibraryError` pattern
  (bindings.ts:472-524): coded raises surface as `{class, code}` and diff via
  `canonicalizeError` (advisory keys stripped). The 67 `expect.error` vectors
  need `ParamValidationError` and `ParamTypeError` classes + codes to
  round-trip through `toExpectError()` exactly as B2 left it — no adapter
  extension expected (verify the two classes emit their Python spellings; the
  BookmarkValidationError `errors[]` extension remains B5's, per b2-packets
  §Raised-error forward note).

### Oracle-ts registration + skip-ledger movement

Same module serves the oracle. After (b′): the five Phase-1 pending-skip
families (`build_filter_entry`, `build_segfilter_entry`, `filter_to_selector`,
`filters_to_selector`, `normalize_on_expression` — B2-BIND-notes:96-100) go
live; the gate's differential full-suite regression (P3-7: cumulative surface,
fresh seeds, ≥500/family — ≥1,000 for the two K4 selector families) must show
the skip count dropping to ZERO Phase-1 pending-skip families remaining;
document the new skip ledger in the gate notes.

## Batch-status / flip / gate

NO flip in module/binding commits. The single B3 gate commit
(`context/phase3/notes/B3-notes.md` finalized alongside):

1. `batch-status.ts`: flip `bookmark_builders.` + `segfilter.` +
   `user_builders.` + `expressions.` + `transforms.` → `done` (P3-5 rule 4), and
   ADD `bookmark_schema.` → `done` (count-neutral — zero corpus vectors; makes
   the batch's owned-name universe explicit and keeps the two oracle-probed
   names honest). Update the header comment's pending-list (the Discrepancy-#2
   correction already landed at the B2 gate — `batch-status.ts:38-45`). Run the
   standing no-prefix-collision assertion: no still-pending corpus api name
   starts with any flipped entry (verified at design time: the corpus's B3-prefix
   names are exactly the 15 vector-bearing apis; no `workspace.`-style collisions
   exist for these prefixes).
2. Conformance checkpoint: `npm run conformance` — expected
   **1,528 PASS / 0 FAIL / 1,723 UNPORTED** (1,229+299 / 2,022−299; adjust by +N
   only if a B3 task lands authored vectors — none are planned by this packet).
   Archive the report JSON under `context/phase3/reports/` (Python repo), commit
   both repos.
3. Oracle probe: one `oracle.call` per the 17 names on BOTH bridges,
   non-"unknown api" required; then the differential full-suite regression
   (fresh seeds) green; RUN record appended to `differential/oracle/RUN.md`.
4. **REFEREES REQUIRED at this gate** (P3-7, ground state): (a) the
   bookmark.json ajv validator and (b) the bookmark_parser round-trip harness
   re-run over the B3-produced bookmark fragments. Expected caveat: referee (b)
   carries the two standing expected-and-disclosed REJECTs for the
   frequency-filter clause shape (`last-run-deep.json`; probe record §K2) —
   those are NOT new findings; anything BEYOND them blocks.
5. `npm run check` green; `just check` green (Python repo touched: strategies,
   adapter, notes); `throwaway/` harness directories removed after arbiter
   sign-off; batch notes finalized; LOCAL COMMITS ONLY (TS `main`, Python
   support branch — verify `git branch --show-current` first).

## Cautions (all shards — each line is a review-pair checklist item)

1. **R10.12 — new-format insights `filterValue` = native JSON numbers, never
   strings** (rulebook §9). Sites: `bookmark_builders.build_filter_entry`
   `filterValue: f._value` (`bookmark_builders.py:504`),
   `_build_list_contains_entry` `filterValue: True` (`:579` — JSON `true`),
   `build_frequency_filter_entry` `behavior.filterValue: ff.value` (`:837`).
   The reviewer greps `builders.ts` for any `String(`/`pythonStr(` touching a
   `filterValue` assignment — any hit is a finding.
2. **R10.11 — numeric-string equivalence is ONLY segfilter number-operand
   positions** (`segfilter.py:187,189`; canonicalizer rule 4,
   `canonical.ts:21,52-73`). Natural JS number rendering there; `pythonStr`
   for non-number operands there; `pythonStr`/`pythonFloatStr` EVERYWHERE else
   a Python `str(x)` lands in output (`user_builders.py:42` `_format_value`,
   `segfilter.py:249` datetime `str(value)`). No epsilon, no rounding
   (watchlist #12).
3. **R10.7 bug-compat — `build_frequency_filter_entry`** replicates the
   server-500 clause byte-for-byte (`bookmark_builders.py:805-855`; probe
   `context/phase1/addendum/frequency-filter-probe.md`). Comment with the probe
   citation; never fix; never "improve" the shape.
4. **Watchlist #2 — selector/expression escaping char-for-char.** Backslash
   FIRST then quote, ALL occurrences (`user_builders.py:40,65`;
   `expressions.py:51`). JS `String.prototype.replace` with a string pattern
   replaces only the FIRST occurrence — `replaceAll` is mandatory; a bare
   `.replace("\\"…` in the diff is a finding. The `selector_str` codec compares
   verbatim (no canonicalizer rescue).
5. **R11.7 — `pythonStrip`/`pythonInt`/`pythonStr`, never
   `trim`/`parseInt`/`String()`** on ported semantics. B3 has NO `.strip()` or
   `int(str)` sites (measured), so any `trim(`/`parseInt(` in the diff is
   automatically wrong; `String(` is allowed ONLY at the two R10.11 segfilter
   operand positions.
6. **Watchlist #13 — `isPythonDict` for every dict membership/type test.**
   Sites: `build_flow_cohort_filter` `isinstance(first_item, dict)` /
   `isinstance(cohort_data, dict)` (`bookmark_builders.py:714,722`);
   `isCohortFilter` (already unified). Key-presence checks on plain dicts
   (`"value" not in entry` `:235`, `"id" in cohort_data` `:733`,
   `"raw_cohort" in cohort_data` `:735`, `event.get(...)`/`pop` defaults in
   `transforms.py:57-63,119-124`) → `Object.hasOwn`, never `in`
   (watchlist #7).
7. **R4.8 — ReadonlyMap/ReadonlySet** for every lookup table
   (`segfilter.py:39-98` maps/frozensets; `transforms.py:18,85` frozensets;
   K1's `PARTIAL_UPDATE_SUB_MODELS`). Enum membership through the landed
   `bookmarks/enums.ts` tables; never re-declare (R10.8).
8. **Watchlist #1 — tuple-unpacking arity.** `_convert_date_format`'s
   3-way split (`segfilter.py:121`) and `lo, hi = value[0], value[1]`
   (`user_builders.py:214` — safe, indexed) — every destructuring in the diff
   gets an arity audit; silent `undefined` binding is the worst-class failure.
9. **Uncoded builtin raises** (R5.5): malformed date → `_convert_date_format`
   ValueError. Oracle compares bare class (`oracle-protocol.md:118-120`); the
   TS twin must throw an error whose `toExpectError()` yields
   `{class: "ValueError"}` — follow the established rig convention for builtin
   classes (check `_EDGE_FILTERS`' cohort-rejection comment,
   `strategies.py:113-115`, and probe which class Python actually raises
   before assuming: ES6 may fire first for `in_cohort` on the selector path).
   If no convention exists yet for a builtin class in bindings, that is a
   fable rig decision at (b′), not a module improvisation.
10. **Watchlist #6 — empty-collection truthiness.** `if not filters` →
    `filters.length === 0` (`bookmark_builders.py:617`, `user_builders.py:273`,
    `build_flow_cohort_filter` `:684`); `name = cb.name or ""` (`:433`) — Python
    falsy-OR catches `""` AND `None` (port as
    `cb.name == null || cb.name === "" ? "" : cb.name` … i.e. `cb.name || ""`
    is CORRECT in JS here since only strings/None reach it — document why).
11. **Booleans are ints in Python.** `isinstance(v, (str, int, float))`
    (`user_builders.py:129,157`) and `isinstance(v, (int, float))`
    (`:193,201,215,220`) ACCEPT `True`/`False` and render `"True"`/`"False"`
    via `pythonStr`. The TS twins accept `typeof "boolean"` wherever Python
    accepts int — ratified Discrepancy #8 makes this in-annotation
    (`bool <: int`). Contrast B2's validators, where bool must be REJECTED
    before int checks — direction flips per site; read each guard.
12. **Clock/UUID seams.** `build_time_section` `date.today()`
    (`bookmark_builders.py:115`) → injectable `today` (B2-V2 precedent);
    `transform_event` `uuid.uuid4()` (`transforms.py:71`) → injectable `uuid`;
    library defaults = real clock / `crypto.randomUUID()`; bindings pass
    `context.shims.*`. Dates stay STRINGS end-to-end; never `new Date()` in
    accept/reject or formatting paths (watchlist #5; K3's pure isoformat
    arithmetic).
13. **Emission order is contract.** `expect.output` arrays and dict-insertion
    orders port in source order (canonicalizer sorts dict KEYS only); pydantic
    error order in K1 comes from the probe; `filters_to_selector` error order
    from lazy iteration; `extract_cohort_filter` preserves relative order.
14. **In-place mutation semantics.**
    `patch_custom_property_filters_for_transform` mutates and returns the SAME
    array (`bookmark_builders.py:234-239`); `build_filter_section` builds fresh
    entries per element; `{**base_cohort, negated: true}` is a SHALLOW copy
    (`:453`). Port aliasing exactly — B5 consumers chain these
    (`workspace.py:2897-2899`).
15. **Logging is out of contract.** `logger.warning`/`debug` sites
    (`user_builders.py:132,161,315`; `transforms.py:72`) never enter vectors;
    do not surface them as errors; the VALUE behavior around them (dropped
    non-scalars, extras-to-remaining, uuid fill) IS contract.
16. **Baseline arithmetic**: entering report 3,251 = 1,229/0/2,022; B3 gate
    expectation 1,528/0/1,723; delta exactly 299 (zero `call.setup[]`
    adjustments — measured). The (b′) `validate_with_pydantic` adapter
    retarget is a re-pin event but adds zero vectors.
17. **Ratified Discrepancy #9 (S4 order)** is B2-scoped (sorting warnings) —
    no B3 output is order-relaxed. Do not extend it.

## Vector-count reconciliation (must sum to 299)

Per api (measured from corpus pin `b5c1369`):

| api | vectors | shard |
|---|---|---|
| `bookmark_builders.build_filter_entry` | 43 | K2 |
| `bookmark_builders.build_group_section` | 32 | K2 |
| `bookmark_builders.build_flow_cohort_filter` | 16 | K2 |
| `bookmark_builders.build_time_section` | 10 | K2 |
| `bookmark_builders.build_frequency_filter_entry` | 9 | K2 |
| `bookmark_builders.build_flow_property_filter` | 9 | K2 |
| `bookmark_builders.build_filter_section` | 9 | K2 |
| `bookmark_builders.build_date_range` | 6 | K2 |
| `segfilter.build_segfilter_entry` | 51 | K3 |
| `expressions.normalize_on_expression` | 30 | K3 |
| `transforms.transform_profile` | 2 | K3 |
| `transforms.transform_event` | 0 (registered; oracle/Layer-3 only) | K3 |
| `user_builders.filter_to_selector` | 53 | K4 |
| `user_builders.filters_to_selector` | 20 | K4 |
| `user_builders.extract_cohort_filter` | 9 | K4 |
| `bookmark_schema.get_root_model_for_bookmark_type` | 0 (registered; oracle/Layer-3 only) | K1 |
| `bookmark_schema.validate_with_pydantic` | 0 (registered; oracle/Layer-3 only) | K1 |
| **Σ** | **299** | |

Per shard: K1 0 + K2 134 (= 43+32+16+10+9+9+9+6) + K3 83 (= 51+30+2) +
K4 82 (= 53+20+9) = **299** = `bookmark_builders.` 134 + `segfilter.` 51 +
`user_builders.` 82 + `expressions.` 30 + `transforms.` 2 — matches the P3-1 B3
row exactly. ✓ Per corpus file: see the table in the header (sums 299). ✓

### B2-deferred items — explicit placement ledger

| B2 deferral (source) | B3 placement |
|---|---|
| `bookmark_schema.validate_with_pydantic` binding excluded at B2 (b2-packets §Binding-plan "the B3 binder picks it up") | (b′) task — adapter retarget + bind + oracle probe (§Binding-plan) |
| `schema-sorting.ts` grower role ("B3-K1 IMPORTS and extends this file; never re-implements", b2-packets §V1b) | K1 — machinery exported/shared, `schema.ts` built on it |
| `user-builders.ts` grower role ("B3-K4 grows this file … MUST import isCohortFilter", b2-packets §V2 + file header) | K4 — grows the stub; imports `isCohortFilter`/`isPythonDict` |
| Remaining `bookmark_schema` slice (playbook B3 row; B2 took only `:61-316`/`:372-680`) | K1 — `:333-379`, `:695-1553` |
| `tests/test_validation_bypass{,_r2}.py` facade halves | NOT B3 — B5 (b2-packets already routed them; no B3 residue) |
| Bypass-test scope note (ground state "validate_with_pydantic and the bypass-test scope moved to B3") | The validator-direct bypass asserts landed at B2-V1b; what moves to B3 is the SCHEMA-slice coverage those tests presuppose — satisfied by K1's `test_bookmark_schema{,_pbt}.py` translation; no bypass test file translates at B3 (log in notes if the B3 arbiter reads the ground-state line differently) |

### Model/tier assignments (P3-3, restated)

K1–K4: **opus**, effort ≤ high, R10.13 incremental protocol, escalation = retry
once on fable with failure context. (b′) binding + adapter + re-pin, review
pair ×2 + arbiter per shard, batch gate + referees: **fable**, effort ≤ high.
NO mutation testing anywhere [SA1]. `/Users/jaredmcfarland/Developer/analytics`
is READ-ONLY. Python via `uv` (`uv run python -m pytest`); bare `python` and the
literal p-y-t-e-s-t string are hook-blocked.
