# B3-K3 notes — segfilter + expressions + transforms (opus, P3-2 loop)

Status: implementation + Layer-3 green; R10.9 harness in progress.

Scope per `context/phase3/design/b3-packets.md` §Packet K3:

| Python source | TS home | Vectors |
|---|---|---|
| `_internal/segfilter.py` (323, whole file) | `packages/core/src/query/segfilter.ts` | 51 |
| `_internal/expressions.py` (52, whole file) | `packages/core/src/query/expressions.ts` | 30 |
| `_internal/transforms.py` (130, whole file) | `packages/core/src/query/transforms.ts` | 2 (`transform_profile`; `transform_event` has 0) |

New shared internal module: `packages/core/src/query/python-builtins.ts` —
`ValueError` / `OverflowError` / `AttributeError` twins (see §4).

## 1. Running log

- [x] Read playbook v1.1 + b3-packets K3 section + Cautions + user-ratifications.
- [x] Read Python sources in full (segfilter, expressions, transforms) and the
      three Layer-3 sources.
- [x] Mandatory CPython `fromtimestamp` probe (§2).
- [x] Layer-3 tests written FIRST (R10.1), then implementation:
      `packages/core/test/query/{segfilter,expressions,expressions.pbt,transforms}.test.ts`
      — 142 tests green (61 + 27 + 6 + 48).
- [x] `tsc --strict` clean, eslint clean, prettier clean.
- [ ] R10.9 throwaway harness (`throwaway/b3-k3/`) + RUN record.
- [ ] `npm run check` green; commit.

## 2. Mandatory CPython probe — `datetime.fromtimestamp(t, tz=utc).isoformat()`

CPython 3.14.6 (`uv run python`, support-branch venv), 2026-08-15. Verbatim
transcript of the values that drive the ported formatter:

```
0            -> 1970-01-01T00:00:00+00:00
1            -> 1970-01-01T00:00:01+00:00
-1           -> 1969-12-31T23:59:59+00:00
1704067200   -> 2024-01-01T00:00:00+00:00
18.0         -> 1970-01-01T00:00:18+00:00      # integral float: NO .ffffff
1.5          -> 1970-01-01T00:00:01.500000+00:00
-1.5         -> 1969-12-31T23:59:58.500000+00:00
-0.5         -> 1969-12-31T23:59:59.500000+00:00
0.5          -> 1970-01-01T00:00:00.500000+00:00
1.0000005    -> 1970-01-01T00:00:01.000001+00:00
0.1+0.2      -> 1970-01-01T00:00:00.300000+00:00
1.9999995    -> 1970-01-01T00:00:01.999999+00:00
2.9999995    -> 1970-01-01T00:00:02.999999+00:00
-1.0000005   -> 1969-12-31T23:59:58.999999+00:00
1699999999.9999995 -> 2023-11-14T22:13:20+00:00
5e-07        -> 1970-01-01T00:00:00+00:00        # round-half-EVEN: 0.5 -> 0
1.5e-06      -> 1970-01-01T00:00:00.000002+00:00 #                  1.5 -> 2
2.5e-06      -> 1970-01-01T00:00:00.000002+00:00 #                  2.5 -> 2
-5e-07       -> 1970-01-01T00:00:00+00:00
-1.5e-06     -> 1969-12-31T23:59:59.999998+00:00 #                 -1.5 -> -2
True         -> 1970-01-01T00:00:01+00:00        # bool <: int (Caution 11)
False        -> 1970-01-01T00:00:00+00:00
253402300799 -> 9999-12-31T23:59:59+00:00        # last in-range second
-62135596800 -> 0001-01-01T00:00:00+00:00        # first in-range second
'x'/None/[1]/{'a':1}/complex -> TypeError argument must be int or float, not X
253402300800 -> ValueError year must be in 1..9999, not 10000
-62135596801 -> ValueError year must be in 1..9999, not 0
nan          -> ValueError Invalid value NaN (not a number)
inf/-inf     -> OverflowError timestamp out of range for platform time_t
2**63        -> OverflowError timestamp out of range for platform time_t
9.2e18       -> OSError [Errno 84] Value too large ...   (see §5 exclusion)
```

Findings applied to `transforms.ts`:

1. **µs rounding is round-half-even** (`us = round(frac * 1e6)`), NOT
   `Math.round` (half-up, and `-0.5 -> -0`). `pyRoundHalfEven` implements
   CPython's `2.0 * round(x / 2.0)` tie correction; the three probe ties
   (`5e-7`, `1.5e-6`, `2.5e-6`) are locked as Layer-3 cases.
2. **No fractional part when `microsecond == 0`**, offset spelled `+00:00`
   (never `Z`), year zero-padded to 4 (`0001-…`).
3. The `frac<0` carry (`us < 0 → t -= 1; us += 1e6`) is what turns `-1.5`
   into `…58.500000`; ported verbatim.
4. Valid second range is exactly `[-62135596800, 253402300799]`; the
   formatter checks it BEFORE the civil-date conversion, so no
   `Number.isSafeInteger` hazard reaches the arithmetic.
5. `bool` is accepted (1/0); everything non-numeric is a `TypeError`.

## 3. Discrepancies / playbook corrections logged

- **Playbook B3 Layer-3 misassignment (packet-flagged, confirmed by source
  read)**: `tests/test_transform_funnel.py` (524) and
  `tests/test_transform_retention.py` (613) test
  `_internal/services/live_query.py` internals (`_transform_funnel_result`,
  `_extract_funnel_steps_from_series`, `_transform_retention_result` —
  imports at `test_transform_funnel.py:8-12`, `test_transform_retention.py:9`),
  a **B5-S2** module. NOT translated at K3 (R10.1: no implementation exists);
  cited in the `transforms.test.ts` header. Carry to the B3 gate report.
- `tests/test_query_user_structural.py` is split three ways: K3 takes
  `TestTransformProfileMissingDistinctId` (`:492`) and
  `TestTransformProfileCompletelyEmpty` (`:509`); K4 takes the two selector
  classes; the rest is B5. Header citation present in `transforms.test.ts`.
- `transform_event` has NO Python unit test and ZERO vectors — the new Vitest
  cases are marked `// NEW` and are locked by the docstring example plus the
  §2 probe, per the packet.

## 4. Builtin-exception twins (Caution #9 resolution)

`packages/core/src/query/python-builtins.ts` mints `ValueError`,
`OverflowError` and `AttributeError` as `Error` subclasses whose
`constructor.name` equals the CPython class name — the oracle bridge encodes a
thrown error as `thrown.constructor.name`
(`differential/oracle/server.ts:956`), so a `RangeError` stand-in would diff.
`TypeError` keeps using the NATIVE JS class (the `requireHashable` precedent,
`validation-shared.ts:313`). Reached from:

| Site | Python | TS |
|---|---|---|
| `_convert_date_format` 3-way unpack (`segfilter.py:121`) | `ValueError` | `ValueError` twin (explicit `parts.length !== 3`, watchlist #1) |
| datetime range element not a `str` (`segfilter.py:247` → `.split`) | `AttributeError` | `AttributeError` twin |
| range operand not iterable (`segfilter.py:187,247`) | `TypeError` | native `TypeError` |
| `fromtimestamp` NaN / out-of-range year | `ValueError` | `ValueError` twin |
| `fromtimestamp` ±inf / beyond `time_t` | `OverflowError` | `OverflowError` twin |
| `dict(non-dict)` in transforms | `TypeError` | native `TypeError` |

**(b′) note (fable rig decision)**: these classes are NOT
`MixpanelHeadlessError` descendants, so `runGuarded`'s
`instanceof MixpanelHeadlessError` wrap does not catch them. No corpus vector
reaches any of them (checked: all 83 K3 vectors are well-formed), so the
binding needs no change for vectors — but the ORACLE path must surface
`{class: "ValueError" | "OverflowError" | "AttributeError"}` for the fuzz to
compare. Recommendation to the binder: let them propagate (the oracle's
`constructor.name` encoding already produces the right class name).

## 5. Documented domain notes / exclusions (fuzz + contract)

1. **`dict(iterable-of-pairs)`** — CPython's `dict(properties)` accepts an
   iterable of pairs and raises `ValueError` for a malformed one
   (`dict("ab")`). The TS twin raises `TypeError` for every non-dict.
   Excluded from the fuzz domain (`properties` is drawn as dict-or-absent);
   no Mixpanel response can produce a non-dict `properties`. `TODO(port)`
   marker at the site.
2. **CPython's `OSError` (errno 84) band** — for very large in-int64
   timestamps the platform `gmtime` fails before the year check
   (`9.2e18 → OSError`, `1e16 → ValueError`). The TS twin reports
   `ValueError` across the whole out-of-range span and `OverflowError` from
   2^63 up. The packet authorises excluding "|t| beyond datetime.max"; the
   fuzz domain caps |t| at 1e12. `TODO(port)` marker at the site.
3. **`Filter._value` int-vs-float-ness** — a plain JS number cannot record
   it; `operandStr` renders a PyFloat carrier from its CPython `repr`
   spelling (byte-exact `"18.0"`), and only an UNCARRIED integral float
   would render `"18"`. That residue is exactly what canonicalizer rule 4
   (R10.11, `canonical.ts:52-73`) normalizes at the two number-operand
   positions.

## 6. R10.9 harness — RUN record

Harness: `mixpanel-headless-ts/throwaway/b3-k3/` (`gen-cases.py` + `entry.ts` +
`harness.mjs` + `run.sh`); full record in that directory's `RUN.md`. Both sides
call the REAL functions (Python: the `_internal` modules; TS: the ported
`packages/core/src/query/*` through an esbuild bundle). Comparison is
BYTE-EXACT — stricter than the conformance canonicalizer, so the R10.11 operand
renderings are proven without the numeric-string rescue.

| seed | compared | divergences |
|---|---|---|
| 20260815 | 2,594 | **0** |
| 4242 | 2,594 | **0** |
| 99991 | 2,594 | **0** |
| 20260816 | 2,594 | **0** |
| 7 | 2,594 | **0** |
| **Σ** | **12,970** | **0** |

Per-api (identical every seed, all ≥ the 500 budget): `build_segfilter_entry`
731 · `normalize_on_expression` 634 · `transform_event` 626 ·
`transform_profile` 603. Outcome tally (seed 7): OK 1,910 · SG4 252 ·
TypeError 174 · SG3 78 · SG1 66 · ValueError 64 · SG2 49 · AttributeError 1 —
every K3-owned guard code fires and agrees on both sides.

Coverage audit (packet mandate "audit `filter_strategy()` coverage against the
three tables"): a systematic row sweep emits every row of all three operator
maps on its matching property type, with `date_unit` ∈ {None, day, hour, week,
month, ""} for the datetime rows. Verified programmatically: **0 missing rows**
(the free draw alone left `datetime|was since` uncovered at seed 7 — that is
exactly the gap the sweep closes).

### Offline vector pre-check (not a substitute for (b′))

The 83 K3 corpus vectors (`filters/test_segfilter.jsonl` 51,
`segmentation/test_expressions.jsonl` 30,
`streaming/test_query_user_structural.jsonl` 2) were replayed offline through
the ported entry points with a throwaway decoder (`$type: Filter/float`) and
byte-compared against `expect.output` / `expect.error`:
**83 checked, 0 failures** (outputs byte-identical without any canonicalizer
rescue; both `expect.error` classes+codes match). The AUTHORITATIVE replay is
the (b′) binding task's `npm run conformance -- --filter …` run.

### Harness finding (fixed red→green at its owning layer)

`transform_profile({"$properties": "ab"})`: CPython `dict("ab")` raises
**ValueError**; the first TS draft raised `TypeError` for every non-dict.
`properties` is a `dict[str, Any]` INTERIOR value → in-annotation under ratified
Discrepancy #8 → CPython's behavior is contract. `pythonDictCopy` now
reproduces `dict(iterable-of-pairs)` branch for branch. CPython 3.14.6 probe
that pinned it:

```
dict('ab')          -> ValueError dictionary update sequence element #0 has length 1; 2 is required
dict('')            -> {}
dict([1, 2])        -> TypeError object is not iterable
dict([[1, 2]])      -> {1: 2}
dict(['ab', 'cd'])  -> {'a': 'b', 'c': 'd'}
dict(['abc'])       -> ValueError ... has length 3; 2 is required
dict([{'a': 1}])    -> ValueError ... has length 1; 2 is required
dict([{'a':1,'b':2}]) -> {'a': 'b'}          # dict elements iterate KEYS
dict(5) / dict(None)  -> TypeError 'int'/'NoneType' object is not iterable
dict([[['x'], 2]])  -> TypeError cannot use 'list' as a dict key (unhashable type: 'list')
```

Consequences recorded in the code: the unhashable-key branch reuses the shared
`requireHashable` guard (R10.8, never re-derived), and non-string pair keys use
the JSON key spelling with a `TODO(port)` (a JS object cannot hold Python's
int/bool/None key types; only reachable through this pathological branch).
Exclusion #1 in §5 is therefore CLOSED (emulated, not excluded); exclusions #2
and #3 stand.

No repros written to `conformance/differential/repros/` — zero unexplained
divergences remain.

## 7. Deferrals to the (b′) binding task (fable rig)

1. **Registry names** `segfilter.build_segfilter_entry`,
   `expressions.normalize_on_expression`, `transforms.transform_event`,
   `transforms.transform_profile` — bind to the ported entry points
   `buildSegfilterEntry` / `normalizeOnExpression` / `transformEvent` /
   `transformProfile` (`packages/core/src/query/{segfilter,expressions,transforms}.ts`).
2. **`transform_event` seams**: pass `context.shims.uuid` as the `uuid` option;
   wrap the returned `event_time` iso TEXT in `PyDatetime` (codecs.ts:66-74) so
   it encodes as `{"$type":"datetime","iso":…}`. No clock seam is needed —
   `transform_event` reads no `now()`.
3. **Builtin twins**: `ValueError`/`OverflowError`/`AttributeError`
   (`query/python-builtins.ts`) are NOT `MixpanelHeadlessError` descendants, so
   `runGuarded` will not wrap them; the oracle's `constructor.name` encoding
   already yields the right class. No corpus vector reaches them (all 83 K3
   vectors are well-formed), so no vector-path change is expected — but the
   binder should confirm the oracle path surfaces the bare class.
4. **`strategies.py` extension** (Python rig, fable): the K3 harness covers the
   full operator-row matrix and the new transform families in `throwaway/b3-k3`;
   the equivalent extension of `conformance/differential/strategies.py`
   (`filter_strategy` row coverage + `transform_event_family` /
   `transform_profile_family`) is left to the binder/gate so the CUMULATIVE
   gate regression exercises it. Domain notes to carry over: cap `|time|` at
   1e12 (excludes CPython's `OSError` band) and draw `properties` as
   dict-or-absent-or-small-pair-iterable.

