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

## 4. R10.9 harness RUN record

(filled in at the end)
