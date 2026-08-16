# B2-M2 Task Notes — validation.py shard V1b (bookmark validators + sorting slice)

**Status**: DONE — TS commit `617da2b` (mixpanel-headless-ts, branch `main`)
**Model**: opus (per b2-packets.md §V1b)
**Date**: 2026-08-15

## Scope (per b2-packets.md §Packet V1b)

140 vectors (110 `validate_bookmark` + 30 `validate_flow_bookmark` + 0
`validate_sorting_block`). Python ranges: `validation.py` 1767–1879
(`validate_flow_bookmark`), 2283–2417 (`validate_bookmark`), 2418–3020
(six Layer-2 clause sub-validators), 3021–3090 (`validate_sorting_block`)
+ the `bookmark_schema.py` sorting slice (61–316 adapter, 372–680 models).

## Inventory of prior partial work

TS repo working tree at task start: clean apart from `.DS_Store` files.
`git log` HEAD = `5c0e032` (B2-M1 / shard V1a). No M2 partial work existed;
nothing to salvage or revert.

Reused from M1 (imported, never re-derived — R10.8):
`query/validation-shared.ts` (`_enumError`, `_isFinite`,
`containsControlChars`, `pythonStrLoose`, `_MAX_FILTER_VALUES`),
`bookmarks/enums.ts` tables.

## CPython pydantic probe (b2-packets.md §V1b "Mandatory probe")

Scripts (TS repo, deleted by the batch gate):
`throwaway/b2-m2/probe-sorting.py` (48 wrapper+pydantic cases),
`probe-sorting2.py` (coercion matrix + error ordering),
`probe-int-grammar.py` (lax `str -> int` grammar).
Run from the Python repo: `uv run python ../mixpanel-headless-ts/throwaway/b2-m2/<script>`.
pydantic version: see `uv.lock` at support-branch HEAD (pydantic v2).

Findings the TS twin (`bookmarks/schema-sorting.ts`) reproduces:

1. **Error ORDER** = model **field-definition** order first
   (`bar, table, line, insights-metric, pie, retention-curve, funnel-steps`;
   inside a config: the class's field order), THEN `extra_forbidden` for
   unexpected keys in **input insertion order**. Verified with
   `order/top-level-mixed` (input `pie, sankey, bar, funnel-steps, column,
   table` → errors `bar, table, pie, funnel-steps`, then extras
   `sankey, column`) and `order/two-extras-two-fields`.
2. **Tag names in `loc`** — discriminated unions insert the variant Tag
   (`["bar","SortByValueConfig","sortBy"]`); `_DISCRIMINATOR_TAGS` strips it.
   A `model_type` error's loc ENDS with the Tag → path is the config path.
3. **`_BASE_CONFIG` has no `strict=True`** → pydantic-core LAX mode:
   - `int` field (`viewNLimit`): `bool` OK, integral finite float OK,
     `NaN`/`inf` → `finite_number` (unmapped → `VALIDATION_ERROR`),
     fractional float → `int_from_float` (also unmapped → `VALIDATION_ERROR`),
     list/dict → `int_type`, unparseable string → `int_parsing`, `null` OK
     (field is Optional).
   - `str` field (`valueField`): only `str` (and Python `bytes`) accepted;
     `3`, `3.5`, `True`, `[]`, `{}` → `string_type`.
   - `list` field (`colSortAttrs`): Python list/tuple/set accepted;
     `null`, str, dict, int → `list_type`.
   - Literal fields: exact match only; `None` on a required Literal →
     `literal_error` (not `missing`).
4. **Lax `str -> int` grammar** (third-parser carve-out, R11.7): trim by the
   **`PYTHON_NUMERIC_WHITESPACE`** set — measured identical to Rust
   `str::trim` (Python `str.isspace()` minus `U+001C..U+001F`; `U+FEFF`,
   `U+200B`, `U+180E` are NOT trimmed) — then
   `[+-]? DIGITS(single underscores between digits) ( "." "0"+ )?`,
   ASCII digits only. Accepts `"5"`, `"05"`, `"+5"`, `"1_0"`, `"1_000.0"`,
   `"0.000"`, `"9007199254740993"`, `"1"*30`; rejects `"1__0"`, `"_1"`,
   `"1_"`, `"5."`, `".5"`, `"1e3"`, `"0x5"`, `"10.01"`, `"1.0_0"`,
   `"1.0000000000000001"`, `"٥"`, `"５"`, `"inf"`, `""`.
   Magnitude is irrelevant (arbitrary-precision accept) — the twin returns a
   boolean accept/reject, never a number, so R4.5 (2^53) never applies.
5. **Unreachable codes through `validate_sorting_block`** (documented, not
   implemented as dead branches): `B0_MISSING_FIELD` — every required field
   in the sorting models is `sortBy` / `sortOrder` / `colSortAttrs` /
   `sortColumn`, the first three map to S8/S9/S2 and `sortColumn` can only
   be reached when the key is PRESENT (`_table_sort_discriminator` routes on
   `"sortColumn" in v`), so a `missing` at `sortColumn` cannot occur;
   `B0_VALIDATOR_ERROR` — no `@field_validator`/`@model_validator` on any
   sorting model. Reachable B0 codes: `B0_WRONG_TYPE` (string_type /
   int_type / int_parsing) and `B0_INVALID_LITERAL` (`sortColumn`).
   `VALIDATION_ERROR` fallback reachable via `int_from_float` and
   `finite_number`.

## Progress log

- [x] Read packet + playbook + M1 notes
- [x] CPython pydantic probe (sorting slice)
- [x] Layer-3 test translation (red first: every new suite imports
      `src/query/validation-bookmark.js`, which did not exist when the
      suites were written)
- [x] Implementation
- [x] R10.9 harness (0 divergences)
- [x] commit

## What landed (TS repo, branch `main`)

**Source** (`packages/core/src/`):

| File | Contents |
|---|---|
| `bookmarks/schema-sorting.ts` (NEW, 830 LOC) | the `bookmark_schema.py` slice: `_DEFAULT_CODE_MAP` / `_default_code_mapper` / `_sorting_code_mapper` / `validate_with_pydantic` / `_translate_pydantic_error` / `_DISCRIMINATOR_TAGS` / `_loc_to_jsonpath`, and a hand-rolled structural twin of the six sorting models + four discriminator callables. R10.8 header names **B3-K1** as the file's grower. |
| `query/validation-bookmark.ts` (NEW, 1,040 LOC) | `validateFlowBookmark` (FLB1–FLB6), `validateBookmark` (B1–B26), the six clause sub-validators, `validateSortingBlock` (S1–S9 + the pre-filter). |
| `query/validation.ts`, `query/index.ts` | barrels extended with the three new entry points. |
| `src/index.ts` | public export `validateBookmark` — the phase2-audit A1 deferral (Python `__all__` entry `"validate_bookmark"`), owner B2. |
| `bookmarks/enums.ts` | P2-3 `TODO(port)` marker REMOVED (V1a landed `_MAX_FUNNEL_STEPS` / `_MAX_HOLDING_CONSTANT`; V1b closes the comment per the packet). |
| `bookmarks/index.ts` | re-exports `schema-sorting.js`. |

**Layer-3 tests** (`packages/core/test/query/`, **113 tests, all green**):

| TS file | Python source | tests | deferral |
|---|---|---|---|
| `validation-bookmark.test.ts` | `tests/unit/test_validation.py` | 56 | query-args classes were V1a's; `TestValidationError`/`TestBookmarkValidationError` are Phase-2 |
| `validation-flow-bookmark.test.ts` | `tests/test_validation_flow.py` | 30 | flow-args classes were V1a's |
| `validation-cohort-bookmark.test.ts` | `tests/test_validation_cohort.py` | 15 | CB3 retention class was V1a's |
| `validation-retention-bookmark.test.ts` | `tests/test_validation_retention.py` | 4 | retention-args classes were V1a's |
| `bookmark-validation.pbt.test.ts` | `tests/unit/test_bookmark_validation_pbt.py` | 8 | none (full file) |

Counts reconcile against the Python method counts: `test_validation.py`
20 (`TestValidateBookmarkLayer2`) + 4 (`TestValidateMeasurementFunnelContext`)
+ 32 (`TestValidateSortingBlock`) = 56; flow FLB classes 4+5+6+6+3+5+1 = 30;
cohort 3+3+8+1 = 15; retention 1+1+2 = 4; PBT 4+2+2 = 8.

Whole-file deferral, documented in the `validation-bookmark.test.ts`
header (phase2-audit A2 style): **`tests/test_validation_bypass.py` and
`tests/test_validation_bypass_r2.py` move WHOLE to B5-S2.** The packet
listed their "validator-direct asserts" as V1b scope, but all 8
`validate_bookmark(params)` call sites
(`test_validation_bypass.py:128,215,237,248,259,355,369` + the import)
consume a dict built by `ws.build_params(...)`; `test_validation_bypass_r2.py`
never calls a validator directly at all (measured 2026-08-15). Translating
them would have required hand-forging the facade's output — an R10.2
weakening. Layer-2 coverage of those exact inputs is preserved by the 7
recorded vectors in `corpus/validation/test_validation_bypass.jsonl`,
which replay at (b′).

Test-home deviation (same as M1): `vitest.config.ts` only discovers
`packages/*/test/**`, so the suites live in `packages/core/test/query/`
rather than colocated under `src/`.

## Findings handed to (b′) / the review pair

1. **PyFloat carrier policy for B2-M2 — no path-dependent unwrap needed.**
   The binding should decode as M1 documented (non-finite spellings →
   native non-finite numbers; finite spellings stay carriers, which is
   what makes `isinstance(x, int)` fail in TS exactly where it fails in
   CPython — B18B `customPropertyId`, B22 cohort `id`). The sorting slice
   would naively have wanted the OPPOSITE (pydantic accepts integral
   floats on `int` fields), and both live in the same `params` dict, so
   `schema-sorting.ts` is carrier-aware internally instead: its
   `optionalInt` classifies by numeric value. **The binding must not add
   a `params.sorting` unwrap rule.**
2. **`TypeError: unhashable type` deviation (arbiter decision requested).**
   Python's 12 `value not in FROZENSET` guards in this shard raise when
   the params dict carries a `list`/`dict` at the checked key; the TS
   port returns the enum error instead. Documented as a `TODO(port)` at
   the top of `query/validation-bookmark.ts` with the remediation recipe
   if R10.7 bug-compatibility is ruled to win. The harness measured this
   as the ONE unilateral-skip class (8/1,929 calls at the recorded seed),
   never as a silent pass.
3. **`B0_MISSING_FIELD` / `B0_VALIDATOR_ERROR` are unreachable** through
   `validate_sorting_block` (proof in §probe finding 5). The packet lists
   them as "harness must cover" — the harness covers their nearest
   reachable neighbours and documents the omission
   (`strategies.py:253-257` style). If (b′) wants them exercised, the
   only route is `bookmark_schema.validate_with_pydantic` directly, which
   the packet explicitly excludes from B2 binding (B3 owns it).
4. **`Object.keys` vs Python dict ordering.** JS orders integer-like keys
   first; Python is pure insertion order. Only reachable with
   numeric-string chart-type keys, which the S4 pre-filter removes before
   the model validator sees them. Noted in the `schema-sorting.ts` JSDoc.
5. **Suggestion asserts kept verbatim** (Caution §6): B5/B9/FLB3/FLB4/S4
   tests assert `"bar" in suggestion`, `"total"`, `"unique"`, `"sankey"`,
   `"conversion_rate_unique"` — all pass against V1a's `difflib` port.

## R10.9 harness — RUN record

Full record: `throwaway/b2-m2/RUN.md` (TS repo). Summary:

- Driver: `bash throwaway/b2-m2/run.sh [seed] [runs]` (derandomised
  mulberry32; recorded seed **20260815**, 600 runs/family).
- Arbiter: the REAL oracle-py server
  (`uv run python -m conformance.oracle_py`, source_commit `b5c1369`);
  port side is the esbuild-bundled real TS modules. Diff is the
  recorder's `[{code, path, severity}]` shape, position-by-position.
- **129/129 edge calls compared**; fuzz compared per family:
  `validate_bookmark` 592 · `validate_flow_bookmark` 600 ·
  `validate_sorting_block` 600 (all ≥ the P2-9 500 budget).
  **Total 1,921 compared, 0 divergences.** Fresh seed 777001: 1,924
  compared, 0 divergences.
- 8 skips, ALL the single documented unilateral class (finding 2 above),
  recorded with full inputs in `report.json`.
- Edge set: the mandatory value edges per api (integral float via the
  `$type: float` carrier, fractional `1.5`, `True`, `None`, empty list,
  empty string, non-BMP `𝒳`) + one explicit call per code in BOTH §V1b
  code lists + 28 pydantic lax-coercion probes + 4 emission-order pins.
- One divergence was found and fixed during development
  (`optionalInt` compared `Number.isInteger` on the raw value instead of
  the carrier-unwrapped numeric → spurious `VALIDATION_ERROR` on
  `viewNLimit: 5.0`).

### Deferral to the (b′) binding task

As in M1: oracle-ts cannot answer `validation.*` until (b′) registers the
bindings, so no `conformance/differential/strategies.py` families were
added (they could not have been exercised); the harness compared against
oracle-py directly. **Formalising `bookmark_family`,
`flow_bookmark_family` and `sorting_family` in `strategies.py` is
deferred to (b′).** No Python-source or `conformance/` files were touched
by this task, so `just check` was not required (writes were confined to
`context/phase3/notes/B2-M2-notes.md`).

## Gate arithmetic at this commit

No bindings and no batch-status flip in this task (P3-5: bindings/oracle
registration are the separate strongest-tier (b′) task). TS conformance
replay at this HEAD is unchanged from the B0/M1 baseline:
**3,251 vectors — 539 PASS / 0 FAIL / 2,712 UNPORTED @ corpus `b5c1369`.**
The 140 V1b vectors go PASS at (b′).

`npm run check` green at this HEAD (typecheck ×5 workspaces + eslint +
prettier + 2,734 tests + browser smoke).

## Open items for the review pair

1. Re-run `bash throwaway/b2-m2/run.sh` from the recorded seed (and one
   fresh seed) — must stay 0 divergences, and every skip must be the
   `TypeError` class.
2. Re-run the three probe scripts if the pydantic pin moves; the
   `schema-sorting.ts` accept/reject decisions are pinned to them.
3. Grep the diff for `.trim(` / `parseInt(` / `\s` regex grammars
   (R11.7). Expected: zero hits. The pydantic-core trim is spelled as an
   explicit codepoint scan over `PYTHON_NUMERIC_WHITESPACE` with the
   third-parser carve-out cited at the call site.
4. Adjudicate finding 2 (`TypeError` bug-compatibility) and finding 1
   (carrier policy) before (b′) writes the bindings.

## B2 arbiter corrections (2026-08-15, b2-review-resolution.md)

- **Skip-class correction (fidelity review F5)**: after the B2-BIND
  commit `2015565` landed the R10.7 `requireHashable` adjudication, the
  8 recorded-seed harness skips changed CLASS: they are now BILATERAL
  ("ts threw + python errored" in `report.json` skip_reasons — the TS
  port raises the same `TypeError` at the 16 frozenset-membership
  sites). Open-item 1's phrase "every skip must be the `TypeError`
  class" is satisfied by the BILATERAL TypeError class; the RUN.md
  prose describing a unilateral "TS returned the enum error" class is
  pre-`2015565` and superseded (correction paragraph added to
  `throwaway/b2-m2/RUN.md` before gate deletion). Counts unchanged:
  1,921 compared / 8 skips / 0 divergences at seed 20260815 —
  re-verified post-arbiter-fixes.
- **Finding-4 correction (fidelity review F4)**: the M2 claim that the
  S4 pre-filter makes key ordering unreachable is true only for the
  model walk over `known` (valid chart types are never integer-like),
  NOT for the S4 warning loop itself: integer-like UNKNOWN chart keys
  flip the S4 emission order (JS integer-like-key ordering). Blessed as
  playbook Discrepancy #9; integer-like keys are a documented omission
  in the sorting fuzz domain.
- **isDict correction (fidelity review F1, blocker — fixed)**: M2's
  `isDict`/`isPlainObject` classified PyFloat carriers and class
  instances as dicts (11 oracle-confirmed divergent shapes), and the
  carrier duck-shape misclassified plain `{"spelling": ...}` dicts in
  the OTHER direction (4 more oracle-confirmed shapes incl. a
  PY_FLOAT_INVALID_LITERAL crash where Python returns `bool(dict)`).
  Both directions fixed by the shared prototype-based `isPythonDict`
  (`validation-shared.ts`; rulebook watchlist #13). Locks:
  `packages/core/test/query/validation-dict-fidelity.test.ts` (19
  tests) + bookmark/sorting/flow/user_params strategy-domain edges.
