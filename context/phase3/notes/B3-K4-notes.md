# B3-K4 notes — `query/user_builders.py` builders half (selector path)

Shard: **K4** of batch B3 (`context/phase3/design/b3-packets.md` §"Packet K4").
Model: opus, effort ≤ high, R10.13 incremental protocol.
Scope: `_format_value`, `_prop_ref`, `filter_to_selector`, `filters_to_selector`,
`extract_cohort_filter` (`src/mixpanel_headless/_internal/query/user_builders.py`
`:27-322`; `_is_cohort_filter` `:69-85` was landed at B2-V2 and is IMPORTED, never
re-declared — R10.8).

Vectors owned: 82 (`filter_to_selector` 53 · `filters_to_selector` 20 ·
`extract_cohort_filter` 9). Bindings/oracle registration are the separate fable
(b′) task — NOT this shard.

## 1. Inventory of prior work (task instruction: "inventory first")

Checked 2026-08-15 before writing anything:

| path | state |
|---|---|
| `packages/core/src/query/user-builders.ts` | B2-V2 stub — `isCohortFilter` + the `isPythonDict` re-export only (59 lines). GROWN by this shard. |
| `packages/core/test/query/user-builders.test.ts` | absent — created here. |
| `throwaway/b3-k4/` | absent — created here. |
| `conformance-runner/src/bindings.ts` | no `user_builders.*` registrations (b′ task's job — untouched). |

No partial K4 work existed; nothing was reused unverified.

## 2. Translation decisions (each cites the Python line it mirrors)

- **Watchlist #2 escaping** (`:40`, `:65`): backslash FIRST then double quote, ALL
  occurrences → two `replaceAll` calls in both `formatValue` and `propRef`. A
  string-pattern `.replace()` would rewrite only the first hit. Locked by the
  translated `TestFilterToSelectorPropertyEscaping` /
  `TestFilterToSelectorValueFormatting` / `TestPbtFormatValueSpecialChars` asserts
  and by the harness's escaping-biased alphabet.
- **`_format_value` non-string branch** (`:42`) is Python `str(value)` and the
  `selector_str` codec compares VERBATIM (no canonicalizer rescue — R10.11 covers
  segfilter operand positions ONLY). Rendered through the shared
  `pythonStrValue` (see §3), never `String(...)`: `String(true)` is `"true"`,
  Python's `str(True)` is `"True"` (watchlist #8).
- **Booleans are ints** (Caution #11): every `isinstance(v, (str, int, float))`
  (`:129`, `:157`) and `isinstance(v, (int, float))` (`:193`, `:201`, `:215`,
  `:220`) accepts `True`/`False`; the TS twins accept `typeof "boolean"`.
  In-annotation per ratified Discrepancy #8 (`bool <: int`).
- **PyFloat carrier**: the rig decodes Python floats as a `PyFloat` CLASS
  instance, so `isFloatCarrier` (B2 arbiter fix F1) classifies it as a number
  exactly where Python classifies `float` as `(int, float)`, and the carrier is
  unwrapped ONLY at rendering time (`pythonFloatStr` of its CPython `repr`
  spelling) — B2 Cautions §8 idiom, K3 `operandStr` precedent.
- **Guard order is contract** (`:116-118`): `op = f._operator` then
  `prop = _prop_ref(f)` — ES1 fires BEFORE any operator dispatch, so a
  non-string property with an unsupported operator yields ES1, not ES13.
- **`filters_to_selector` laziness** (`:275`): Python's generator means a failing
  element aborts before later elements are evaluated. Ported as an explicit
  `for` loop (never `.map().join()`), so the FIRST error wins in source order.
  Empty list → `""` (`:273-274`, watchlist #6: `filters.length === 0`).
- **`extract_cohort_filter`** (`:306-322`): returns a 2-tuple → TS
  `[Filter[], Filter | null]`; the SAME Filter instances flow through
  (identity lock `test_cohort_filter_identity_preserved`); extras beyond the
  first cohort append to `remaining` in encounter order (the `logger.warning`
  next to them is out of contract, Caution #15); the input array is never
  mutated.
- **Logging** (`:132-137`, `:159-165`, `:315-319`): out of contract. The
  `dropped` list Python builds exists solely to feed `logger.warning` and has no
  observable effect, so it is not rebuilt in TS; the comment at each site records
  why. The VALUE behavior around it (non-scalars dropped from `parts`) IS ported.
- **Message text** is out of contract (R5.4) but ported verbatim anyway
  (`{op!r}` → `pythonRepr`, `type(x).__name__` → `pythonTypeName`), so the one
  Python test that asserts on message content
  (`TestNotEqualsErrorMessage::test_error_references_correct_method_name`)
  translates as a real `toContain("Filter.not_equals")` assert rather than being
  weakened to class+code.

## 3. R10.8 shared extraction — `pythonStrValue`

`str(value)`-on-a-possibly-carried-value now has TWO ported sites
(`segfilter.py:187,189,249` — K3's module-private `operandStr`; and
`user_builders.py:42`). Rather than duplicate the carrier-unwrap, the body moved
to `packages/core/src/query/validation-shared.ts` as `pythonStrValue` (the
established shared home both modules already import) and K3's `operandStr`
delegates to it, keeping its R10.11 documentation in place. Semantics are
unchanged in both directions (pure delegation; K3's `segfilter.test.ts` and the
K3 harness both stay green).

## 4. Deliberate omissions / deferrals

- `tests/test_query_user_edge_cases.py` → B5 Layer-3 (packet table); its 3 K4
  vectors replay at B3 regardless.
- The rest of `tests/test_query_user_structural.py` → B5 (K3 already took the two
  `transform_profile` classes); only `TestPbtFormatValueSpecialChars` (`:416`)
  and `TestFiltersToSelectorOrAndPrecedence` (`:461`) translate here, under a
  split-header citation in the test file.
- No vector bindings, no oracle registration, no `batch-status.ts` flip (b′ /
  gate tasks own those).

## 5. R10.9 harness RUN record

Harness: `throwaway/b3-k4/` (TS repo) — `gen-cases.py` (CPython, drives the REAL
`mixpanel_headless._internal.query.user_builders`) + `harness.mjs` (Node, drives
the REAL `packages/core/src/query/user-builders.ts` through an esbuild bundle of
`entry.ts`). Byte-exact comparison; no canonicalizer rescue anywhere (selector
strings are verbatim contracts).

Re-run everything from the recorded seeds with:

```bash
bash throwaway/b3-k4/run.sh              # recorded sweep
bash throwaway/b3-k4/run.sh 4242 1100    # one seed / N draws per selector family
```

Full record (what it compares, oracle-bridge status, edge-set coverage table,
domain omissions): `throwaway/b3-k4/RUN.md` in the TS repo, committed with the
module.

### Recorded sweep (2026-08-15)

Seeds `20260815, 4242, 99991, 20260816, 7`; **1,100 draws per selector family**
(the packet's DOUBLED ≥1,000 budget), 550 for `extract_cohort_filter` and the
`_format_value` probe, plus the mandatory edge block on every seed.

| seed | compared | divergences | class-only error spellings |
|---|---|---|---|
| 20260815 | 3,531 | **0** | 0 |
| 4242 | 3,531 | **0** | 0 |
| 99991 | 3,531 | **0** | 0 |
| 20260816 | 3,531 | **0** | 0 |
| 7 | 3,531 | **0** | 0 |
| **Σ** | **17,655** | **0** | **0** |

Per-api counts, identical every seed (surplus over the draw count = the shared
edge block): `filter_to_selector` 1,260 · `filters_to_selector` 1,136 ·
`extract_cohort_filter` 559 · `_format_value` 576. All 13 ES codes fire on
every seed and agree on both sides (seed-7 tally in `RUN.md`). Zero
divergences ⇒ no repros in `conformance/differential/repros/`.

Comparison is byte-exact string equality — deliberately stricter than any
canonicalizer, because the `selector_str` codec compares selectors verbatim and
R10.11's numeric-string rule does not reach this module.

### Oracle-bridge deferral (P3-2 step c, explicit)

`filter_to_selector` / `filters_to_selector` are Phase-1 pending-skip families
on oracle-ts and `extract_cohort_filter` has no family at all, because the
`user_builders.*` names are registered by the SEPARATE fable (b′) task
(P3-6 step 3) which this module task must not perform. The through-the-bridge
fuzz at the doubled budget is therefore **deferred to (b′)**; the direct
CPython ↔ Node harness above stands in meanwhile (K3 precedent).

## 6. Layer-3 gap closed with NEW cases (declared, not silent)

Every escaping assert in the Python suite uses a value or property name with
exactly ONE backslash / ONE quote — inputs where `str.replace` and `replaceAll`
AGREE. The translated Python suite therefore does NOT lock watchlist #2's
replace-all requirement (verified: swapping both `replaceAll`s for `replace`
left the 81 translated tests green). The test file adds a declared
`// NEW (no Python source test)` block — multi-backslash, multi-quote,
backslash-before-quote ordering, trailing backslash, a property name with two
of each, a selector-injection value, and a 500-run round-trip property — which
DOES fail against the first-occurrence-only spelling (3 failures, verified
before reverting). No Python assertion was weakened; assertions were only
added.
