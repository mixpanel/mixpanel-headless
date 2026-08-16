# B5-S2 notes — LiveQueryService + workspace.ts query members

Packet: `context/phase3/design/b5-packets.md` §3 (v1.0). Python arbiter branch
`ts-port/phase2-contract-support`; TS branch `main`. Corpus pin `70c904dc`.
Vectors owned: **480** (packet §1) — they replay at the fable (b′) BIND task,
not here.

Status: **IN PROGRESS** (written incrementally per R10.13).

## 0. Sequencing

S1 landed first and created `packages/core/src/workspace.ts` with the §2
skeleton (see `B5-S1-notes.md` §0). S2 therefore EXTENDS that file: it fills
the `=== B5-S2 query members ===` section and adds the `_live_query_service`
accessor.

**Outbound to S3 (recorded here AND as a cited TODO(port) in the S2 section of
`workspace.ts`)**: packet §2 assigns the `query`-bound `_replays_service`
accessor to S2, but `ReplaysService` does not exist in the TS tree until S3
lands, so S2 cannot reference the class. S3 must add the accessor inside the
S2 marker block, memoized in a `#replays` field, constructed as
`new ReplaysService(this.client, {query_fn: (...a) => this.query(...a)})` —
the bound `query` member (`replays.py:150-176`).

## 1. Files

TS (repo `mixpanel-headless-ts`), all under `packages/core`:

| Path | Content |
|---|---|
| `src/services/live-query-transforms.ts` (NEW) | the module-level transforms of `_internal/services/live_query.py` (`:51-674` + `:1567-2042`) |
| `src/services/live-query.ts` (NEW) | `LiveQueryService` (`live_query.py:677-1565`), 16 query methods |
| `src/workspace-query-params.ts` (NEW) | the 11 private param-building methods of `workspace.py` (R7.2 split — see the file header table) |
| `src/workspace.ts` (EXTENDED) | the `liveQueryService` accessor + the 22 S2 members + the three query-user execution engines |
| `src/services/discovery.ts` | `isoUtc` promoted to an export (R10.8 — the query-user engine stamps `computed_at` from the same expression) |
| `src/query/transforms.ts` | `timestampNumber` promoted to an export (R10.8 — `_transform_activity_feed` coerces `properties["time"]` identically) |
| `src/query/python-builtins.ts` | `RuntimeError` twin added (§3 finding 2) |
| `src/query/user-validators.ts` | U24 catch widened (§3 finding 2) |

Layer-3 suites (`packages/core/test/`):

| Path | Python source | Classes | Tests |
|---|---|---|---|
| `test/services/live-query.test.ts` | `tests/unit/test_live_query.py` | ALL 7 | 40 |
| `test/services/live-query.pbt.test.ts` | `tests/unit/test_live_query_pbt.py` | ALL 2 | 10 |
| `test/services/live-query-phase008.test.ts` | `tests/unit/test_live_query_phase008.py` | ALL 8 | 31 |
| `test/services/live-query-flow.test.ts` | `tests/unit/test_live_query_flow.py` | ALL 6 | 19 |
| `test/services/live-query-bookmarks.test.ts` | `tests/unit/test_live_query_bookmarks.py` | ALL 2 | 19 |
| `test/services/transform-funnel.test.ts` | `tests/test_transform_funnel.py` (B3-K3 deferral) | ALL 2 | 40 |
| `test/services/transform-retention.test.ts` | `tests/test_transform_retention.py` (B3-K3 deferral) | ALL 6 | 40 |
| `test/workspace/workspace-test-helpers.ts` | the shared `_TEST_SESSION` / `MagicMock(spec=…)` twins | — | — |
| `test/workspace/query-user-parallel.test.ts` | `tests/test_workspace_query_user_parallel.py` | ALL 10 | 48 |
| `test/workspace/query-user-aggregate.test.ts` | `tests/test_workspace_query_user_aggregate.py` | ALL 14 | 47 |
| `test/workspace/query-user-structural.test.ts` | `tests/test_query_user_structural.py` | the 8 S2-owned | 8 |
| `test/workspace/build-user-params.test.ts` | `tests/test_workspace_build_user_params.py` | ALL 13 | 68 |
| `test/workspace/query-user.test.ts` | `tests/test_workspace_query_user.py` | ALL 18 | 47 |
| `test/workspace/query-user-integration.test.ts` | `tests/test_workspace_query_user_integration.py` | ALL 11 | 36 |

Python repo: this notes file only.

## 2. Translation decisions

1. **R7.2 three-way split.** Python's `live_query.py` (2,042) becomes
   `live-query-transforms.ts` + `live-query.ts`; the `workspace.py` private
   param builders become `workspace-query-params.ts`. Every one of those
   Python methods is `self`-free apart from the `self._build_*_params` call
   chain, so they port as free functions and the facade members delegate.
2. **Wire calls are B4 client methods, imported by name** (R10.8): the 14
   query-host methods plus `exportProfilesPage` / `engageStats`. Their
   `JsonValue` products convert through `toNativeJson` at the service
   boundary — the documented point where the TS wire layer equals
   `json.loads`.
3. **`_STEP_PREFIX_RE` is re-spelled, not copied.** Python's `\d` in a `str`
   pattern is `\p{Nd}` (not ASCII-only), its `\s` is the pinned
   `str.isspace()` table, and its `$` also matches before ONE trailing
   newline. All three are reproduced explicitly.
4. **`_normalize_cohort_date`'s `key[:10]` is a CODE-POINT slice** (R11.6,
   `cpSlice`), and every `sorted(...)` over strings is code-point ordered
   (R11.5).
5. **CPython arithmetic guards.** `sum(...)` and the `existing + count`
   aggregation route through a `pyNumber` coercion that rejects non-numeric
   operands with `TypeError` — a bare JS `+` would silently concatenate where
   Python raises.
6. **Error-message interpolation.** `f"…{raw['error']}"` uses `pythonStr`;
   `{metric_key!r}` and `{sorted(keys)}` use `pythonRepr` (a Python list
   renders the same under `str()` and `repr()`).
7. **`warnings.warn` → an injected `WarningSink`** (R9.5, the S1 seam);
   `logger.debug` / `logger.warning` → an injected `WorkspaceLogger`
   (`warning` is optional so existing `{debug}`-only sinks keep working).
8. **`ThreadPoolExecutor` → a bounded promise scheduler.** `min(workers, 5)`
   worker loops pull page numbers from a shared cursor; results land in a
   `Map` keyed by page and are re-emitted in sorted page order. A CODED wire
   error (`AuthenticationError` / `RateLimitError` / `ServerError` /
   `QueryError`) sets an abort flag — new pages stop being scheduled, the
   in-flight ones settle, then the error re-throws. That is exactly what
   Python's `future.cancel()` + `with ThreadPoolExecutor` shutdown does
   (queued futures cancelled, running futures allowed to finish, their
   results dropped). Every observable the Layer-3 suite pins — call COUNT,
   page ORDER, `failed_pages`, `pages_fetched`, coded-error propagation —
   holds (48/48 on the first run).
9. **`calendar.timegm(date.fromisoformat(s).timetuple())`** is pure calendar
   arithmetic (`days_from_civil * 86400`); no `Date` parsing (watchlist #5).
10. **`int(self._session.project.id)`** routes through `pythonInt` (R11.7).
11. **`ReadonlyMap` chart-type lookups** (R4.8): the three
    `chart_type_map.get(mode, default)` sites are `Map`s, so a `mode` of
    `"toString"` cannot reach `Object.prototype`.
12. **`json.dumps` → `pythonJsonDumps`** at the four engage-param sites
    (CPython separators and `\uXXXX` policy), never `JSON.stringify`.
13. **`ws.close()` in the Python `finally:` blocks has no TS twin** —
    `Workspace.close()` is a B6-W1 stub and the TS client owns no pool
    (R6.2). Recorded once in `workspace-test-helpers.ts` rather than in every
    translated file.
14. **`.df` asserts** become `toRows()` / `rowColumns()` per the C6 pandas
    convention. The one place this is not a mechanical swap is
    `test_df_profiles_varying_property_sets_union_columns`, whose pandas-NaN
    assertions become key-ABSENCE assertions on the ragged TS rows (recorded
    in that file's header).
15. **`UserEvent.time`** is a `datetime` in Python and preserved ISO text in
    TS (watchlist #5), so `time.year == 2024` style asserts translate to the
    exact isoformat string — a strictly stronger assertion over the same
    conversion.

## 3. Findings fixed at their owning layers (Layer-3-driven, red-first)

1. **`except ValueError` over the converted ES* guards
   (`workspace-query-params.ts`, the `U_FILTER` wrap).** Python's
   `ParamValidationError` dual-inherits `ValueError` (`exceptions.py:97`), so
   `except ValueError` around `filters_to_selector` catches the converted
   coded guards. The Phase-2 header note ("`except ValueError` reachability
   is a Python-side compatibility concern only", `errors.ts:11-14`) does not
   hold at this one site: RR-4
   (`test_workspace_query_user_integration.py:1116-1152`) pins that an ES11
   raise surfaces as `U_FILTER` with the guard error as the chained cause.
   The catch now names both classes and sets `cause` (Python's
   `raise … from exc`).
2. **U24's catch was too narrow (`query/user-validators.ts:746`).** Python
   catches `(ValueError, TypeError, RuntimeError)` around
   `CohortDefinition.to_dict()`; the B2 port narrowed to
   `ParamValidationError | TypeError` on the reasoning that the ported
   `toDict()` can only raise those. That is true of the LIBRARY path but
   Layer-3-visible:
   `test_workspace_query_user_integration.py:594-649` patches `to_dict` to
   raise `RuntimeError("serialization failed")` / `ValueError("bad selector
   node")` and pins U24 for both. The catch now names all four arms, and a
   `RuntimeError` twin joins `query/python-builtins.ts` (which already
   carries `ValueError` / `OverflowError` / `KeyError` / `AttributeError`).

3. **`AttributeError` fidelity on non-mapping members
   (`services/live-query-transforms.ts`).** Harness-driven (R10.9 rows
   T1/T2), fixed red-first with 4 regression tests in
   `packages/core/test/services/transform-funnel.test.ts`. Two sites
   consume an API member with a mapping method — `raw.get("data", {}).items()`
   in `_transform_funnel` (`live_query.py:141`) and
   `cohort_data.get("first", 0)` in `_transform_retention`
   (`live_query.py:198`). CPython raises `AttributeError` the moment the
   method lookup fails on a non-mapping; the port raised `TypeError`
   (`Object.values(null)`) at the first and SILENTLY SUCCEEDED with a
   size-0 cohort (`Object.hasOwn("str", "first")` -> `false`) at the
   second. Both now route through a `pyMapping(value, attr)` guard that
   tests with `isPythonDict` (watchlist #13) and raises the
   `AttributeError` twin. The module header already claimed this
   behaviour (`dictGetRecord` doc comment) — the harness proved the claim
   was not implemented.

## 4. R10.9 harness RUN record

Mirrored from `throwaway/b5-s2/RUN.md` (the harness itself is deleted
at the batch gate per packet §7.5; this copy survives).

### 4.1 Part 1 — differential (Python arbiter vs TS port)

| file | role |
|---|---|
| `py-side.py` | seeded recipe generation + Python arbiter outputs (`cases.json`, `py-out.json`) |
| `ts-side.ts` | the same recipes rebuilt as TS objects, through the port (`ts-out.json`) |
| `compare.ts` | canonical-JSON comparator (sorted object keys, `-0` preserved) |

Run:

```
uv run python <ts-repo>/throwaway/b5-s2/py-side.py     # from the PYTHON repo
npx vite-node throwaway/b5-s2/ts-side.ts               # from the TS repo
npx vite-node throwaway/b5-s2/compare.ts
```

Seed `20260816`, `PER_FAMILY = 520`.

Both sides interpret ONE JSON recipe language into the same typed
objects, so the corpus is not TS-shaped or Python-shaped. Recipe
interpretation runs INSIDE the guard, and positional arguments are built
BEFORE the keyword bag, because CPython evaluates positionals first — a
constructor guard reached through `events` must beat one reached through
`where` (this is why case `build_params[81]` first reported `CF2_…`
instead of `CM2_…`; harness bug, fixed).

#### Counts

| family | cases | raised | diverged |
|---|---:|---:|---:|
| `build_params` | 520 | 117 | 0 |
| `build_funnel_params` | 520 | 142 | 0 |
| `build_flow_params` | 520 | 271 | **2** |
| `build_retention_params` | 520 | 319 | 0 |
| `build_user_params` | 520 | 115 | **10** |
| `transforms` | 78 | 2 | 0 |
| **total** | **2,678** | **966** | **12** |

**966 error branches** exercised across **36 distinct registry codes**,
every one class-and-code identical to the arbiter:

```
B20_EMPTY_FILTER_VALUE CF2_COHORT_NAME_EMPTY CM2_COHORT_NAME_EMPTY
EV1_EMPTY_EVENT F1_MIN_STEPS F3_CONVERSION_WINDOW_MAX
F3_CONVERSION_WINDOW_POSITIVE F4_EXCLUSION_STEP_BOUNDS
F4_EXCLUSION_STEP_ORDER F7_SECOND_MIN_WINDOW
F9_SESSION_WINDOW_REQUIRES_ONE FL10_SESSION_WINDOW_REQUIRES_ONE
FL5_NO_DIRECTION FL7_CONVERSION_WINDOW_MAX
FL9_SESSION_REQUIRES_SESSION_WINDOW FS1_SESSION_EVENT_MISMATCH
R11_INVALID_UNIT R8_INVALID_ALIGNMENT SG4_UNSUPPORTED_PROPERTY_TYPE
U12 U14 U19 U2 U22 U23 U26 U29 U3 U30 U5 U9 UP1 U_FILTER V0_NO_EVENTS
V17_EMPTY_EVENT V7_LAST_POSITIVE
```

#### Edge set

The mandated set — `18.0`, `1.5`, `True`, `None`, `[]`, `""`, `"𝒳"` —
appears verbatim in `EDGE_SCALARS` / `FILTER_VALUES` (`py-side.py:72,76`)
and is drawn into every position a recipe exposes: event names, property
names, `Filter.equals` values, cohort names, group-by buckets, labels,
`sort_by`, `search`, `as_of`, funnel/flow step fields, and the transform
response bodies. Domains are annotation-constrained (Discrepancy #8):
each keyword only draws from its own `Literal` union, and unknown-param
keys are never integer-like (#9/#10).

#### Transform-math corpus (78 cases)

Every case carries the raw response as JSON **text**; the TS side routes
it through `parseLossless(..., {pythonConstants: true})` + `toNativeJson`
— the production wire path (B0-1 F1) — while the arbiter uses
`json.loads`. Result objects are projected through Python `to_dict()` /
TS `toJSON()`, which mirror each other by construction
(`types/results/live-query.ts:12`).

Shapes covered, all named by the packet's harness spec:

- zero-denominator funnel (`steps[0].count == 0` → overall `0.0`);
- `prev_count == 0` → step rate `0.0` while step 0 stays the literal `1.0`;
- single-step funnel; empty-steps funnel; empty `data`;
- segmented `$overall` funnels; `$overall`-absent segmented shape
  (no first-segment fallback — `[]`, `live_query.py:76`);
- integral-float counts (`18.0`) through `parseLossless`;
- empty-cohort retention (all-`0.0`, never `NaN`); mixed empty/live
  cohorts; code-point key ordering with `""` and `"𝒳"` keys;
- negative cohort size; missing `first`; missing `counts`;
- non-dict retention series member;
- cohort-date normalization (15 keys incl. `""`, `"𝒳"`, `"18.0"`,
  `"None"`, `"$average"`, `"2025-01-01T"`, `"T00:00:00"`);
- `extractFunnelStepsFromSeries` step-prefix parsing incl. tab and
  double-space separators, prefix-less keys, non-dict members, and the
  multi-metric warning path;
- `extractCohortsAndAverage` with non-dict `$average` / members.

### 4.2 Divergence table

| # | family | cases | delta | verdict |
|---|---|---:|---|---|
| T1 | `transforms` | 1 | `transformFunnel({data: null})` raised `TypeError`; CPython raises `AttributeError` (`None.items()`) | **FIXED** — `pyMapping()` guard, `live-query-transforms.ts` |
| T2 | `transforms` | 1 | `transformRetention({"d": "notadict"})` returned a size-0 cohort; CPython raises `AttributeError` (`str.get`) | **FIXED** — same guard, `live_query.py:198` site |
| T3 | `transforms` | 29 | `_df_cache` present in the arbiter projection | harness bug — arbiter switched from `dataclasses.asdict` to `to_dict()` |
| H1 | `build_params` | 2 | `CF2_…` instead of `CM2_…` | harness bug — positional args must be built before the kwarg bag |
| H2 | `build_params` | 187 | `TypeError: CohortMetric is not a constructor` | harness bug — wrong import module |
| **F1** | `build_flow_params` | **2** | flow `property_filter_params_list[].filter.operand` renders `"18.0"` vs `"18"` | **known narrowing, NOT fixed** — see below |
| **F1** | `build_user_params` | **10** | engage `where` expression renders `18.0` vs `18` | **known narrowing, NOT fixed** — see below |

T1/T2 were fixed red-first at the owning layer, with regression tests in
`packages/core/test/services/transform-funnel.test.ts` (describe
`R10.9: AttributeError fidelity on non-mapping members`, 4 tests). After
the fix the whole `transforms` family is byte-identical.

#### F1 — the one residual divergence class (integral-float spelling)

All 12 remaining divergences are one thing: a Python `float` whose value
is integral (`18.0`) renders as `"18.0"`, while the JS number `18` — the
only thing a TS caller can pass — renders as `"18"`. It only surfaces at
the two sites that render a filter value **into a string**:

- `build_flow_params` → `steps[].property_filter_params_list[].filter.operand`
- `build_user_params` → the engage `where` expression

Everywhere else the value lands as a JSON number, where the narrowing is
erased by contract (`json-value.ts:108-112`). Non-integral floats (`1.5`)
are byte-identical on both sides, which pins the cause precisely.

This is the established `$type: float` **carrier** situation already
modelled in the tree (`types/vector-codecs.ts:580,605-613,675`;
`bookmarks/schema-sorting.ts:65-72,476,496`;
`compat/python-json-dumps.ts:133-134`). It is NOT fixable inside the
transform/param code, because JS has no runtime distinction to consult —
it has to be carried in.

**Outbound note for the vector-binding / oracle task (which this shard is
explicitly not allowed to write):** the `b′` bindings for
`workspace.build_flow_params` and `workspace.build_user_params` must
either (a) keep integral floats as PyFloat carriers all the way to the
two string-render sites and make those sites carrier-aware, or (b)
exclude integral floats from filter-value domains for those two
families, the same way Discrepancy #8 constrains other domains. Option
(b) matches the measured corpus (`python-json-dumps.ts:134` — zero
`$type:float` inputs across the 317 vectors).

### 4.3 Part 2 — wire edge set

`wire-edges.ts` — **119 checks / 0 failures**.

```
npx vite-node throwaway/b5-s2/wire-edges.ts
```

The 22 wire members have no oracle family, so the edge set is replayed
through canned responses on the injected fetch seam
(`createMockClient` / `makeSession`, the `httpx.MockTransport` twin).

1. **Status branches** — every consumed status (`400 401 403 404 429 500
   502 503`) through five members of different families
   (`segmentation`, `funnel`, `retention`, `Workspace.query`,
   `Workspace.queryUser`), asserting pure passthrough of the B4 mapping.
   `403` is `QueryError`, not `AuthenticationError` (`api_client.py:521`)
   — the harness's first guess was wrong, the port was right.
2. **Error-as-200** — all 7 edge values through the `raw["error"]` slot
   on `query` / `queryFunnel` / `queryRetention`; every one is
   `QueryError`.
3. **Transform math through the members** — the shapes listed above,
   asserted on the computed numbers (`[1.0, 0.0]`, `[1.0, 0.5]`,
   all-`0.0` rows, code-point cohort order `["", "2025-01-01",
   "2025-01-02", "𝒳"]`, `$average` excluded from `cohorts`,
   `"2025-01-01T00:00:00+00:00"` normalized to `"2025-01-01"`).
4. **Owned error branches with no wire call** — `V0_NO_EVENTS`,
   `V21_INVALID_EVENT_TYPE`, `V25_INVALID_FILTER_TYPE`, `F1_MIN_STEPS`
   (×2), `U26`, `U19`, `U9`, plus the two `ParamValidationError` ctor
   guards (`queryRetention("")`, `queryFlow("")`), each paired with a
   `calls.length === 0` assertion. Every expected code here is
   arbiter-verified: the same inputs are anchored in the differential
   `build_user_params` corpus (cases 8-14) rather than guessed.
5. **Edge set as argument values** — all 7 through `Filter.equals`
   (`[]` is the one rejection, `B20_EMPTY_FILTER_VALUE`, arbiter-
   confirmed) and three `on` spellings through `segmentation`.
6. **Notes (not assertions)** — non-JSON 200 and transport failure both
   normalize to `MixpanelHeadlessError` in the B4 adapter, i.e. the
   service does not re-handle them.

### 4.4 Findings summary

| id | fixed at | artifact |
|---|---|---|
| T1 | `packages/core/src/services/live-query-transforms.ts` (`pyMapping`, `transformFunnel`) | 2 regression tests |
| T2 | `packages/core/src/services/live-query-transforms.ts` (`transformRetention`) | 2 regression tests |
| F1 | not fixable in this shard — outbound note to the vector-binding task | this record |
