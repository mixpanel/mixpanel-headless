# B2-M1 Task Notes — validation.py shard V1a

**Status**: DONE (attempt 2; attempt 1 was harness-killed mid-flight)
**Model**: opus (per b2-packets.md §V1a "Model: opus, effort ≤ high")
**Date**: 2026-08-15

## Scope (per b2-packets.md §Packet V1a)

V1a — argument validators (Layer 1 + shared helpers), 372 vectors.
Python ranges: 1–90 / 91–338 (CP scan) / 341–402 (tables+helpers) /
405–464 (fuzzy) / 467–773 (sub-validators) / 774–1157 (funnel) /
1158–1479 (retention) / 1480–1766 (flow) / 1880–2282 (query_args).

## Inventory of attempt-1 partial work

Uncommitted in the TS repo at the start of attempt 2:

| Path | Verdict |
|---|---|
| `packages/core/src/query/validation-shared.ts` (1171 LOC) | **KEPT** — re-verified line-by-line against `validation.py:91-508`; faithful (difflib port, `_INVISIBLE_RE` from the pinned whitespace table, `matchesDateRe` with Unicode-Nd `\d` + trailing-newline `$`, pure-calendar `_isValidDate`, bool-before-int `_validateDataGroupId`, CP scan in source order). Three follow-ups applied in attempt 2 — see below. |
| `packages/core/src/query/validation-args.ts` (167 LOC) | **PARTLY KEPT** — the `validateTimeArgs` body was verified against `validation.py:511-647` and kept; the file did NOT compile (it imported `_DATE_RE`, which validation-shared exports as `matchesDateRe`) and used a raw JS `>` for V15. Rest of the file was a TODO stub; rewritten. |
| `packages/core/src/query/validation.ts` (17 LOC) | KEPT and extended (barrel). |
| `packages/core/src/query/index.ts` (diff) | REWRITTEN — attempt 1 left "TODO: add remaining exports". |
| `packages/core/src/bookmarks/enums.ts` (diff) | **KEPT** — adds `_MAX_FUNNEL_STEPS` (100) and `_MAX_HOLDING_CONSTANT` (3), verified against `bookmark_enums.py:516/519`. This is the packet's V1b-coordination note ("exactly ONE task adds them"); V1a adds them, V1b imports. |
| `packages/core/test/query/validation-args.test.ts` (186 LOC) | **DISCARDED** — hand-authored "spirit of" tests, not an R10.2 assertion-for-assertion translation of any Python test file. Replaced by real translations. |

Attempt-2 fixes to the kept `validation-shared.ts`:

1. V15's date comparison now goes through the module's own
   `codepointGreater` (R11.5): `_DATE_RE`'s `\d` admits non-BMP Unicode Nd
   digits, so JS `>` (UTF-16 code-unit order) can diverge from Python `>`.
2. Added `pythonNumberStr` / `pythonStrLoose` — the display-only `str(...)`
   helpers the R10/R11 `_enum_error(value=str(mode))` sites and the numeric
   f-strings need (R5.4: out of contract, ported for compilable fidelity).
3. `containsControlChars` re-expressed as an explicit codepoint predicate
   instead of a regex literal. The Python class is ASCII-explicit
   (`[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]`) so the spellings are equivalent, and
   the predicate form is lint-clean (`no-control-regex`) without a suppression.

## What landed (TS repo, branch `main`)

**Source** (`packages/core/src/`):

- `query/validation-shared.ts` — CP scan (CP1–CP6), `containsControlChars`,
  `isInvisibleOnly`, `matchesDateRe`, `_isValidDate`, `_isFinite`,
  `_suggest`/`getCloseMatches` (faithful `difflib.SequenceMatcher` port with
  the `real_quick_ratio`/`quick_ratio` pre-filters and the `heapq.nlargest`
  tie order), `_enumError`, `_validateDataGroupId`, module constants,
  `isPythonInt`/`isPythonFloat`/`isFloatCarrier`, `codepointGreater`.
- `query/validation-args.ts` — the six Layer-1 validators, options-bag
  signatures (Python is all-kwonly, R3.9/R4.10), every `errors.append` in
  Python source order including the delegation order from the packet's
  call-graph table.
- `query/validation.ts` — barrel re-exporting the six validators (V1b extends).
- `query/index.ts` — Phase-2 placeholder replaced; still NOT re-exported from
  `packages/core/src/index.ts` (that is V1b's `validate_bookmark` job).
- `bookmarks/enums.ts` — `_MAX_FUNNEL_STEPS`, `_MAX_HOLDING_CONSTANT`.

**Layer-3 tests** (`packages/core/test/query/`, **406 tests, all green**):

| TS file | Python source | tests | deferral |
|---|---|---|---|
| `query-validation.test.ts` | `tests/unit/test_query_validation.py` | 31 | facade-driven classes → B5 S2 (header citation) |
| `validation-args.test.ts` | `tests/unit/test_validation.py` | 33 | ValidationError classes → already Phase-2; bookmark/sorting → V1b |
| `validation-funnel.test.ts` | `tests/test_validation_funnel.py` | 129 | none (full file) |
| `validation-retention.test.ts` | `tests/test_validation_retention.py` | 103 | 4 `validate_bookmark` tests → V1b |
| `validation-flow.test.ts` | `tests/test_validation_flow.py` | 86 | 30 `validate_flow_bookmark` tests → V1b |
| `validation-cohort.test.ts` | `tests/test_validation_cohort.py` | 7 | `validate_bookmark` cohort classes → V1b |
| `query-validation.pbt.test.ts` | `tests/unit/test_query_validation_pbt.py` | 4 | none (full file) |
| `validation.pbt.test.ts` | `tests/unit/test_validation_pbt.py` | 13 | none (full file) |

Counts reconcile exactly against the Python method counts
(funnel 129 = 129; retention 107 − 4 = 103; flow 116 − 30 = 86; cohort 7;
`test_validation.py` 3 + 24 + 6 = 33; `test_query_validation.py` 3 + 4 + 1 +
12 + 11 = 31; PBT 4 and 13).

**Deviation from the packet, recorded**: the packet says Layer-3 tests are
"colocated under `packages/core/src/query/`". The repo's `vitest.config.ts`
only discovers `packages/*/test/**/*.test.ts` and every existing suite lives
under `packages/core/test/`, so the tests land in `packages/core/test/query/`.
Attempt 1 made the same call.

## R10.9 harness — RUN record

Full record: `throwaway/b2-m1/RUN.md` (TS repo). Summary:

- Driver: `bash throwaway/b2-m1/run.sh [seed] [runs]` (derandomised
  mulberry32; recorded seed **20260815**, 700 runs/family).
- Arbiter: the REAL oracle-py server
  (`uv run python -m conformance.oracle_py`, source_commit `b5c1369`);
  port side is the esbuild-bundled real TS module. Diff is the recorder's
  `[{code, path, severity}]` shape, position-by-position.
- **134/134 edge calls compared**, fuzz compared per family:
  time 700 · group_by 552 · query 567 · funnel 511 · retention 664 · flow 700
  (all ≥ the P2-9 500 budget). **Total 3,828 compared, 0 divergences.**
- 506 skips, ALL bilateral and explained: a TS constructor guard rejected the
  payload AND oracle-py's `decode_value` refused the same payload
  (`V18_BUCKET_ORDER` ×421, `EX2_STEP_ORDER` ×85). A skip is only recorded
  after Python is asked; a Python-accepts/TS-rejects case would be a
  divergence.
- Edge set covers the mandatory value edges per api (integral float via the
  `$type: float` carrier, fractional `1.5`, `True`, `None`, empty list, empty
  string, non-BMP `𝒳`) plus one explicit call per code in BOTH §V1a code
  lists. Codes made unreachable by Phase-2 `types.py` constructor guards
  (`V12`, `V18`, `V13`, `CM5`, `F4_CONTROL_CHAR_EXCLUSION`,
  `F4_EMPTY_EXCLUSION_EVENT`, `F4_EXCLUSION_NEGATIVE_STEP`) are documented in
  the edge-call comment, `strategies.py:253-257` style.

### Deferral to the (b′) binding task

The packet routes the fuzz through `conformance/differential/strategies.py`
plus oracle-ts. oracle-ts cannot answer `validation.*` until (b′) registers
the bindings, so no Python-side strategies were added (they could not have
been exercised); the harness compared against oracle-py directly instead.
**Formalising `group_by_args_family` / `query_args_family` /
`funnel_args_family` / `retention_args_family` / `flow_args_family` in
`strategies.py` is deferred to (b′).** No Python-source or
`conformance/` files were touched by this task, so `just check` was not
required.

### Finding handed to (b′): PyFloat carrier policy (Caution §8)

The harness's first pass produced 9 divergences, all one class, all a binding
question rather than a port bug:

> A `$type: float` payload must reach TS as the **PyFloat carrier** exactly
> where the Python source runs an `isinstance(…, int)` / `isinstance(…,
> float)` test, and as a **native number** everywhere else (Python's
> `30.0 == 30` is true; a carrier object `!== 30` in TS).

Measured split for the V1a surface:

| unwrap to number | keep as carrier |
|---|---|
| `last` (all five apis) | funnel `conversion_window` → `F3_CONVERSION_WINDOW_TYPE` |
| query `rolling` | retention `bucket_sizes[i]` → `R5_BUCKET_SIZES_INTEGER` |
| flow `forward`/`reverse`/`cardinality`/`conversion_window` | `data_group_id` → `DG1_INVALID_DATA_GROUP_ID` |
| `GroupBy.bucket_size`/`bucket_min`/`bucket_max` | |

Non-finite spellings always unwrap to native non-finite numbers
(`vector-codecs.ts:606-611` precedent, as the packet already states).

## Gate arithmetic at this commit

No bindings and no batch-status flip in this task (P3-5: bindings/oracle
registration are the separate strongest-tier (b′) task). TS conformance replay
at this HEAD is unchanged from the B0 baseline:
**3,251 vectors — 539 PASS / 0 FAIL / 2,712 UNPORTED @ corpus `b5c1369`.**
The 372 V1a vectors go PASS at (b′).

`npm run check` green at this HEAD (typecheck + eslint + prettier + 2,621
tests + browser smoke).

## Repo-hygiene changes riding along (TS repo)

- `.gitignore`: `throwaway/*/.build/` (esbuild output of the harness).
- `.prettierignore`: `throwaway/` (B0-1 precedent).
- `eslint.config.js`: node globals for `throwaway/**/*.mjs` and an ignore for
  `throwaway/*/.build/**`. **The batch gate reverts this glob together with
  the `throwaway/` directory** (B0 precedent, commit `8f79b67`).

## Open items for the review pair

1. Re-run `bash throwaway/b2-m1/run.sh` from the recorded seed (and one fresh
   seed) — must stay 0 divergences.
2. Grep the diff for `.trim(` / `parseInt(` / `\s` regex grammars (R11.7).
   Expected: zero hits. `pythonStrip` is used at all 11 `.strip()` sites the
   packet measured for `validation.py` that fall inside V1a.
3. Confirm the enums-constant landing (`_MAX_FUNNEL_STEPS`,
   `_MAX_HOLDING_CONSTANT`) so V1b imports rather than re-declares.
