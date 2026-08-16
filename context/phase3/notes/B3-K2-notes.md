# B3-K2 notes — `bookmark_builders.py` (whole file)

**Task**: `context/phase3/design/b3-packets.md` §"Packet K2". **Vectors: 134**
(replayed at the (b′) binding task — not this task's).
**Date**: 2026-08-15. **Model**: opus.
**Python source of record**: `src/mixpanel_headless/_internal/bookmark_builders.py`
(904 LOC, whole file) at `ts-port/phase2-contract-support` HEAD.
**TS home**: `packages/core/src/bookmarks/builders.ts` (NEW, 12 exported
functions), barrelled from `packages/core/src/bookmarks/index.ts`.
**Baseline unchanged**: 3,251 vectors = 1,229 PASS / 0 FAIL / 2,022 UNPORTED
@ corpus `b5c1369`. No corpus change, no re-pin, no `batch-status.ts` flip.

---

## 1. Function-by-function mapping

| Python | TS | notes |
|---|---|---|
| `_build_composed_properties` `:32-69` | `buildComposedProperties` | insertion order preserved |
| `build_time_section` `:72-127` | `buildTimeSection` | **clock seam** — `options.today` (B2-V2 precedent) |
| `build_date_range` `:130-170` | `buildDateRange` | `"$now"` is a literal, no clock read |
| `build_filter_section` `:173-205` | `buildFilterSection` | **silent skip** of foreign elements (no `else`) |
| `patch_custom_property_filters_for_transform` `:208-239` | `patchCustomPropertyFiltersForTransform` | mutates + returns the SAME array |
| `build_group_section` `:242-403` | `buildGroupSection` | BB1; conditional `customBucket.min/max` |
| `_build_cohort_group_entry` `:406-466` | `buildCohortGroupEntry` | shallow negated spread |
| `build_filter_entry` `:469-530` | `buildFilterEntry` | **R10.12** `filterValue: f._value` |
| `_build_list_contains_entry` `:533-580` | `buildListContainsEntry` | `setdefault("dataset")`; `filterValue: true` |
| `build_flow_property_filter` `:583-646` | `buildFlowPropertyFilter` | BB2 then per-filter build-then-BB3 |
| `build_flow_cohort_filter` `:649-737` | `buildFlowCohortFilter` | BB4→BB5→BB6→BB7→BB8 |
| `build_frequency_group_entry` `:740-802` | `buildFrequencyGroupEntry` | `label is not None` |
| `build_frequency_filter_entry` `:805-855` | `buildFrequencyFilterEntry` | **R10.7 bug-compat** |
| `build_time_comparison` `:858-904` | `buildTimeComparison` | TC1/TC2 as unreachable throws |

## 2. Cautions checklist — how each one landed

1. **R10.12** — the three `filterValue` sites pass values through natively;
   there is no `String(` / `pythonStr(` anywhere in `builders.ts` (grep-clean:
   the file imports `pythonRepr` for one display-only `{g!r}` message and
   nothing else from `compat`).
2. **R10.11** — no `str(x)` site exists in this module, so the segfilter
   number-operand carve-out does not apply here at all. Confirmed by reading
   the whole Python file: zero `str(`, zero `.strip()`, zero `int(`.
3. **R10.7 bug-compat** — `buildFrequencyFilterEntry` replicates the
   server-500 clause byte-for-byte, with the probe citation
   (`context/phase1/addendum/frequency-filter-probe.md`) and the bug-report
   citation in its doc block and a `DO NOT "FIX" THIS SHAPE` banner. A NEW
   test (`builders.test.ts`) asserts the exact key ORDER of both the outer
   entry and the nested `behavior` dict.
4. **Watchlist #2** — no escaping site in this module (that is K3/K4).
5. **R11.7** — no `trim(` / `parseInt(` / `String(` in the diff.
6. **Watchlist #13 / #7** — `isPythonDict` (imported from
   `query/validation-shared.ts`, never re-derived) for the two BB7/BB8 dict
   tests; `Object.hasOwn` for all five key-presence tests
   (`"value" not in entry`, `"customPropertyId" in`, `"customProperty" in`,
   `"id" in cohort_data`, `"raw_cohort" in cohort_data`) plus the
   `setdefault` and the `cohort_data.get("name", "")` default.
7. **R4.8** — this module declares no lookup tables (they are K3's).
8. **Watchlist #1 (arity)** — the module contains no tuple unpacking; the
   only positional indexing is `filters[0]` after an explicit
   `length === 0` / `length > 1` gate.
9. **Uncoded builtin raises** — none originate in this module.
10. **Watchlist #6** — `filters.length === 0` for all three emptiness
    guards; `cb.name || ""` for the falsy-OR (documented in-place: only
    `string | null` reaches that field, so the JS `||` is exact); and the
    `label is not None` guards use `!== null` so an EMPTY-STRING label is
    emitted verbatim (locked by two NEW tests).
11. **Booleans are ints** — no numeric `isinstance` gate in this module.
    `isPyInt(cb.cohort)` is the one `isinstance(x, int)` twin, reusing the
    landed `types/query-params/guards.ts` helper (R10.8).
12. **Clock seam** — `options.today` on `buildTimeSection` only; library
    default is the real local clock rendered with `padStart`, never
    `Date.toISOString()` (which would be UTC, not local — a real
    `date.today()` divergence).
13. **Emission order** — array emission order is preserved everywhere
    (`buildFilterSection`, `buildGroupSection`, `children`, `eventFilters`,
    `cohorts`, `value` labels); dict literals are written in Python source
    order even though the canonicalizer sorts keys.
14. **In-place mutation** — `patchCustomPropertyFiltersForTransform` returns
    the same array instance (NEW identity test), and the negated cohort
    entry is `{...baseCohort, negated: true}` — a shallow spread sharing the
    `groups` array (NEW identity test asserts `cohorts[0].groups ===
    cohorts[1].groups`).
15. **Logging** — this module has no logging sites.
16/17. Baseline arithmetic and Discrepancy #9 are gate/B2 scope; untouched.

## 3. Discovered facts worth recording

- **Normalization asymmetry, deliberate**: `build_filter_section` accepts
  `(list, tuple)` (`:198`) but `build_flow_cohort_filter` tests `list` ONLY
  (`:683`). Both port to `Array.isArray` because the reachable decoded domain
  has no tuple twin, but the asymmetry is documented in-place so a future
  reader does not "unify" them.
- **BB3 fires AFTER `build_filter_entry` succeeded** (`:625` before
  `:630-636`), so an error raised inside `build_filter_entry` for the same
  filter wins. Ported call order verbatim; an edge probe with a good filter
  followed by a BB3 filter is in both the harness edge block and the new
  strategies family.
- **`eventFilters: []` is emitted** — the guard is `is not None`, so an empty
  `event_filters` list still adds the key (NEW test).
- **`_build_composed_properties` key ordering**: JS reorders integer-like
  object keys where Python `dict` does not. Not a conformance risk — the
  canonicalizer sorts dict keys — but noted in the function's doc block.
- **Playbook-omission confirmation (packet §K2)**: `tests/test_custom_property_builders.py`
  is absent from the playbook's B3 Layer-3 list yet is a measured source of
  15 K2 vectors. Its three builder-direct classes are translated (19 tests);
  `TestMeasurementPropertyBuilder` defers to B5 with a header citation.

## 4. Layer-3 translation

| Python source | translated to | count |
|---|---|---|
| `tests/unit/test_bookmark_builders.py` (1,396 LOC, 18 classes) | `packages/core/test/bookmarks/builders.test.ts` | all 18 classes |
| `tests/test_custom_property_builders.py` — `TestBuildComposedProperties`, `TestBuildGroupSectionCustomProperties`, `TestBuildFilterEntryCustomProperties` | same file | 19 tests |
| `tests/unit/test_bookmark_builders_pbt.py` — `TestListContainsRoundTrip` | `packages/core/test/bookmarks/builders.pbt.test.ts` | 1 fast-check property |
| — | NEW cases (branch/aliasing/order locks + the `buildFlowCohortFilter` corpus-vector mirrors) | 24 |
| **total** | | **163 + 3 PBT** |

**Deferrals (all header-cited in the TS files):**

- `test_bookmark_builders_pbt.py::TestTimeSectionEquivalence` /
  `TestFilterSectionEquivalence` / `TestGroupSectionEquivalence` — they assert
  `ws._build_query_params(...) == build_*(...)`, i.e. facade wiring → **B5-S2**.
- `tests/test_custom_property_builders.py::TestMeasurementPropertyBuilder` → **B5**.
- `tests/test_build_cohort_params.py` and `tests/test_query_params.py` are
  B5-owned Layer-3 files (playbook B5 row). Their 30 K2 vectors replay at the
  B3 gate regardless. Because `build_flow_cohort_filter` would otherwise have
  ZERO TS-side tests until B5, K2 adds a NEW describe block mirroring those
  corpus vector ids one-for-one — additive, never a substitute for the B5
  translation.

## 5. R10.9 harness

Full RUN record: `throwaway/b3-k2/RUN.md` (TS repo; the batch gate deletes
`throwaway/` after arbiter sign-off).

**Headline**: 5 seeds × 600 draws/family × 12 entry points + the verbatim
mandatory edge block = **36,250 compared / 0 divergences / 0 class-only
error spellings**. Every one of BB1-BB8 was exercised (4,594 error cases
total). Re-run with `bash throwaway/b3-k2/run.sh`.

**Disclosed limitation**: the throwaway comparator collapses Python
`int`/`float` to one JS number, so int-vs-float-ness of a *pass-through*
value is not diffed there; the real conformance codecs carry it and the 134
vectors check it at (b′). Every number in a K2 output is a pass-through —
the module performs no arithmetic — so the gap is structural, not incidental.
A self-test (mutating 3 expected outputs + 1 expected code) confirmed the
comparator reports exactly 4 divergences, i.e. the zeros are real.

**Python-side `strategies.py`** gains seven K2 families
(`PHASE3_B3_K2_TARGETS`): `build_filter_section_family`,
`build_group_section_family`, `build_flow_property_filter_family`,
`build_flow_cohort_filter_family`, `build_frequency_filter_entry_family`,
`build_time_section_family`, `build_date_range_family` (13/20/12/15/10/5/5
edge calls respectively). `build_filter_entry` needs no new target — the
Phase-1 `_BUILD_FILTER_ENTRY` target already drives it and starts ANSWERING
once (b′) registers the TS side. The four unregistered helpers are documented
as un-fuzzable through the oracle on the `PHASE3_B3_K2_TARGETS` docstring, and
are covered by the throwaway harness instead. Smoke-driven against the real
builders: all seven families generate, and the group/flow families reach
BB1-BB8 organically.

Two strategy-authoring facts: `FrequencyFilter.operator` has no
`"is exactly"` spelling (it is `"is equal to"` — FF2 rejects the former), and
`build_date_range_family`'s domain is small enough (4×4×6) that Hypothesis
exhausts it before 200 examples; both are intentional, neither is a narrowing.

## 6. Gate handoff

- **(b′) binding task**: `builders.ts` exports the eight registry-named
  entry points under the packet's signatures
  (`buildTimeSection`/`buildDateRange` take the keyword bag with
  `today?: () => string`; `buildGroupSection`/`buildFrequencyGroupEntry`
  take `options.data_group_id`). Pass `context.shims.today()` to
  `buildTimeSection`; everything else is seam-free.
- **B5-S2 consumers**: `patchCustomPropertyFiltersForTransform` must be
  chained on the *result* of `buildFilterSection` (aliasing is contract),
  and `buildGroupSection(segments)` at `workspace.py:3631` passes NO
  `data_group_id` (default `null`).
- **Referee expectation at the gate**: the `bookmark_parser` round-trip
  referee carries two standing, expected-and-disclosed REJECTs for the
  frequency-filter clause shape. `buildFrequencyFilterEntry` reproduces that
  shape on purpose; those REJECTs are not new findings.
