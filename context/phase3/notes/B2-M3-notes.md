# B2-M3 Task Notes — `query/user_validators.py` shard V2

**Status**: DONE
**Model**: opus (per b2-packets.md §Packet V2 "Model: opus, effort ≤ high")
**Date**: 2026-08-15

## Scope (per b2-packets.md §Packet V2)

V2 — `src/mixpanel_headless/_internal/query/user_validators.py` (580 LOC,
whole file), 178 vectors (`user_validators.validate_user_args` 143 +
`validate_user_params` 35).

## Inventory of prior partial work

Checked at task start: the TS repo working tree had **no** V2 files
(`packages/core/src/query/` held only V1a/V1b output: `validation-shared.ts`,
`validation-args.ts`, `validation-bookmark.ts`, `validation.ts`, `index.ts`).
`throwaway/` held `b2-m1/` and `b2-m2/` only. Nothing to reuse or revert.

## What landed (TS repo, branch `main`)

**Source** (`packages/core/src/`):

- `query/user-validators.ts` — `validateUserArgs` (U0-U30, no U9),
  `validateUserParams` (UP1-UP4), `_normalizeFilters`, the `_ACTION_RE` /
  `_DATE_RE` ports and the `today` clock seam. Every `errors.push` sits at
  its Python source position (emission order is contract, Cautions §11),
  including the U29-between-U25-and-U11 and U26/U27/U28-between-U17-and-U18
  interleavings.
- `query/user-builders.ts` — **only** `isCohortFilter`
  (`user_builders.py:69-85`) plus the shared `isPythonDict` primitive, with a
  header note naming **B3-K4 as the file's grower** (it must import, never
  re-declare — R10.8).
- `query/index.ts` — the two validators, their options type, `isCohortFilter`
  and `isPythonDict` added to the internal barrel. NOT re-exported from
  `packages/core/src/index.ts` (Python keeps these `_internal`).

**Layer-3 tests** (`packages/core/test/query/user-validators.test.ts`,
**154 tests, all green**): the WHOLE of `tests/test_user_validators.py`
(149 Python test methods, assertion-for-assertion) + 1 U24 extension arm
+ 4 TS-only `today`-seam tests. Test-count reconciliation: 149 + 1 + 4 = 154.

`tests/test_query_user_edge_cases.py` is NOT translated here — that FILE is
B5 Layer-3 scope (playbook B5 row); its 4 `validation/`-capability vectors
replay through the corpus. The split is stated in the test-file header.

Deviation from the packet, recorded (same call as B2-M1/M2): the packet says
Layer-3 tests are "colocated under `packages/core/src/query/`", but
`vitest.config.ts` only discovers `packages/*/test/**/*.test.ts`, so the file
lands in `packages/core/test/query/`.

## Python-source findings (probe-verified, CPython 3.14.6)

Probe script run under `uv run python`; results reproduced in
`throwaway/b2-m3/RUN.md`.

1. **The packet's V2 trap 2a is a false lead.** It says `as_of` has "no
   `_DATE_RE` pre-gate there" and that the wider CPython 3.11+
   `fromisoformat` grammar must be ported. **The source DOES pre-gate**
   (`user_validators.py:198`: `if _DATE_RE.match(as_of):` before
   `date.fromisoformat`). Probed: `"20260114"`, `"2026-1-4"` fail the gate;
   `"2026-01-14\n"` and Arabic-Indic `"٢٠٢٦-٠١-١٤"` pass the gate but raise
   `ValueError` in `fromisoformat`. All four are U6. So the accepted set is
   exactly `matchesDateRe && _isValidDate` — the V1a pair, imported (R10.8),
   not re-derived. All six spellings are in the harness edge set.
2. **The packet's V2 trap 4 is a false lead too.** It asks for "the
   bool-before-int pattern and integral-float rejection" on
   `limit`/`workers`/`percentile`/`segment_by`. `user_validators.py` has
   **no** `isinstance(x, int)` / `isinstance(x, float)` test anywhere — the
   only `isinstance` calls are against `str`, `Filter`, `CohortDefinition`,
   `dict`, `list`. Every numeric argument feeds a pure numeric comparison.
   This drives the (b′) unwrap table below.
3. **Python str-pattern `\s` == `str.isspace()`** — verified by sweeping the
   whole codepoint range (`re.match(r"\s", chr(cp))` vs `chr(cp).isspace()`):
   zero differences. Confirms Caution §4's premise for the pinned
   `compat/whitespace.gen.ts` table, which `_ACTION_RE`'s port uses.
4. **`_ACTION_RE` corners** (probed): `"count()\n"` matches (Python `$`
   before ONE trailing newline), `"count()\n\n"` does not; `.` does not
   match `\n` but DOES match `\r` (JS `.` excludes `\r`/U+2028/U+2029, so
   the port spells it `[^\n]`); `\s` matches NBSP and U+FEFF is NOT in the
   set; `\d` matches Arabic-Indic digits; the greedy-`.+` backtracking case
   `percentile(properties["a"], 5"], 7)` matches; `extremes(properties[""])`
   does not (`.+` needs ≥1 char).
5. **UP2's early return is real**: a bad-JSON `filter_by_cohort` string
   `return`s immediately, so UP3/UP4 are never reached
   (`{"filter_by_cohort": "nope", "action": "bad"}` → `["UP2"]` only).
   Ported verbatim and locked by the `params/up2-bad-json-early-return`
   edge call.
6. **`ParamValidationError` dual-inherits `ValueError`**
   (`exceptions.py:97`), so U24's `except (ValueError, TypeError,
   RuntimeError)` DOES cover the guard errors `to_dict()` can raise. The TS
   catch is `exc instanceof ParamValidationError || exc instanceof
   TypeError`, with everything else rethrown (Python likewise lets
   `KeyError`/`AttributeError`/`RecursionError` propagate).
7. **`percentile=True`** produces no errors in Python (`0 < True < 100`);
   the TS port behaves identically (JS coerces the same way). Covered by an
   edge call.

## Deliberate porting decisions (review-pair checklist)

- **`today` clock seam** (packet V2 trap 2b): `options.today?: () => string`
  defaults to the real LOCAL clock (`date.today()` is local). The clock is
  READ, never used to PARSE (watchlist #5). The (b′) binding must pass the
  record-epoch date from `context.shims`.
- **Non-`None` Python defaults do NOT collapse `null` into "absent".** Six
  parameters (`limit`, `mode`, `aggregate`, `parallel`, `workers`,
  `include_all_users`) use `=== undefined ? default : value`, not `??`, so
  an explicit `null` reaches the comparisons verbatim. This matters:
  `aggregate=None` makes Python's `aggregate != "count"` true → U14, which a
  `?? "count"` collapse would have silently suppressed. Every other field
  uses `?? null` because its Python default IS `None` (R4.10/R4.11).
- **`_ACTION_RE`** is built at module load from the pinned CPython tables
  (`PYTHON_STR_WHITESPACE`, `DECIMAL_DIGIT_RUNS`) — never JS `\s`/`\d`
  (R11.7 / Caution §4) — with `.`→`[^\n]` and the `u` flag; Python's
  trailing-newline `$` is handled by stripping one trailing `\n`, mirroring
  the `matchesDateRe` precedent.
- **R11.7 audit**: zero `.trim(`, `parseInt(`, `Number(` or `JSON.parse`
  call sites in the new source AND test files (only prose mentions in
  comments). `pythonStrip` at all three Python `.strip()` sites
  (`:186`, `:237`, `:273`); `parseLossless(..., {pythonConstants: true})`
  with `LosslessJsonError`-guarded catches at both `json.loads` sites
  (`:525` UP2, `:551` UP3).
- **Watchlist #6/#7**: `Object.hasOwn` for every `"k" in params` test;
  explicit `.length === 0` / `!== null` for every Python truthiness site.
- **R4.9 loose input typing**: `_normalizeFilters` returns `unknown[]` (rule
  U0 exists precisely to report non-`Filter` members) and takes real ported
  `Filter` instances via `instanceof`, not duck shapes.

## R10.9 harness — RUN record

Full record: `throwaway/b2-m3/RUN.md` (TS repo). Summary:

- Driver: `bash throwaway/b2-m3/run.sh [seed] [runs]` (derandomised
  mulberry32; recorded seed **20260815**, 700 runs/family).
- Arbiter: the REAL oracle-py server (`uv run python -m
  conformance.oracle_py`, `source_commit` `b5c1369`, protocol 1.1, D1.4
  frozen clock `RECORD_EPOCH 2026-01-15T12:00:00Z`); port side is the
  esbuild-bundled real TS module, `today` seam fed `"2026-01-15"`.
- Diff: the recorder's `[{code, path, severity}]` shape, position-by-position.
- **110/110 edge calls compared** + fuzz `user_args_family` 700 /
  `user_params_family` 700 (both ≥ the P2-9 500 budget).
  **Total 1,510 compared, 0 skips, 0 divergences** — reproduced on a fresh
  seed 90210 (identical counts, 0 divergences).
- All **33** owned codes observed in oracle-py's answers (the driver fails
  the run if any is missing): U0-U8, U10-U23, U25-U30, UP1-UP4. **U24** is a
  documented omission (unreachable from a serialisable input — every codec-
  decodable `CohortDefinition` has a `to_dict()` that succeeds); it is
  covered by two Layer-3 twins instead.
- Harness self-test: `--break-unwrap` (disables the carrier unwrap) reports
  3 divergences at 30 runs, proving the comparison is not vacuous.

### Deferral to the (b′) binding task

The packet routes the fuzz through `conformance/differential/strategies.py`
plus oracle-ts. oracle-ts cannot answer `user_validators.*` until (b′)
registers the bindings, so no Python-side strategies were added (they could
not have been exercised); the harness compared against oracle-py directly.
**Formalising `user_args_family` / `user_params_family` in `strategies.py`
is deferred to (b′).** No Python-source or `conformance/` files were touched
by this task, so `just check` was not required.

### Findings handed to (b′)

1. **PyFloat-carrier policy for the V2 surface** (Caution §8). Because
   `user_validators.py` has no `isinstance(int/float)` test, the binding
   must unwrap carriers to native numbers for the four numeric arguments —
   otherwise the comparison silently flips (proved by `--break-unwrap`):

   | unwrap to number | keep as carrier |
   |---|---|
   | `limit` (U3) | `cohort` (only `is None` / `isinstance(CohortDefinition)`) |
   | `percentile` (U28) | `as_of` (only `isinstance(str)` / `is None`) |
   | `workers` (U23) | |
   | `segment_by[i]` — **element-level** (U17) | |

   Non-finite spellings always unwrap to native non-finite numbers
   (`vector-codecs.ts:606-611` precedent).
2. **`today` seam**: pass `context.shims`' record-epoch date as the `today`
   field of the options bag (`runner.ts:445,460`; the oracle builds the same
   shims via `createShims(recordEpoch)`). Without it, U8 answers drift with
   the wall clock and the 3 as_of/U8 vectors fail.
3. **Corpus float-tag reminder**: the `$type: "float"` tag is decode-REJECTED
   for finite NON-integral spellings (`codecs.py:36-44`, D6 rule 3), so a
   fractional float rides as a raw JSON number token. The harness hit this
   (5 skips) before the payloads were corrected.

## Known boundary (documented, not a divergence)

`workers=None` is outside BOTH the Python annotation (`workers: int = 5`) and
the TS `workers?: number` signature: CPython raises `TypeError: '<' not
supported between instances of 'NoneType' and 'int'` while JS coerces
(`null < 1` → true → U23). It is excluded from the fuzz domain rather than
emulated — adding a guard Python does not have would be worse than honest.
`mode=None` / `aggregate=None` are NOT in this class: Python compares strings
there without raising, and the `=== undefined ?` default form makes the port
match exactly (both are in the fuzz pools as near-misses).

## Gate arithmetic at this commit

No bindings and no batch-status flip in this task (P3-5: bindings/oracle
registration are the separate strongest-tier (b′) task). TS conformance
replay at this HEAD is unchanged from the B0 baseline:
**3,251 vectors — 539 PASS / 0 FAIL / 2,712 UNPORTED @ corpus `b5c1369`.**
The 178 V2 vectors go PASS at (b′).

`npm run check` green at this HEAD (typecheck + eslint + prettier + 2,888
tests + browser smoke).

## Open items for the review pair

1. Re-run `bash throwaway/b2-m3/run.sh` from the recorded seed 20260815 (and
   one fresh seed) — must stay 0 divergences / 0 missing codes; then run
   `--break-unwrap` and confirm it DOES diverge.
2. Grep the diff for `.trim(` / `parseInt(` / `Number(` / `JSON.parse` /
   JS `\s`-`\d` regex grammars (R11.7). Expected: zero call sites.
3. Confirm the emission order against `user_validators.py:120-476`
   line-by-line — in particular U29 sitting between U25 and U11, and
   U26/U27/U28 between U17 and U18.
4. Confirm the `=== undefined ?` default form on the six non-`None`-default
   parameters (a `??` there is a silent-suppression bug).
5. Confirm `user-builders.ts` carries the B3-K4 grower note and that B3-K4
   will import `isCohortFilter` rather than re-declaring it (R10.8).
