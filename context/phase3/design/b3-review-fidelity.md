# B3 adversarial review — SEMANTIC FIDELITY lens (P3-2d)

**Status**: COMPLETE · 2026-08-15 · Verdict: **NO-GO** (one major finding F1; K1-D1
arbiter ruling required; two minors)
**Reviewer**: fidelity lens (adversarial pair, fable tier)
**Scope**: B3 commits — TS 0a68942 (K1), 5024bb4 (K2), 755e9a1 (K3), 9add8c4 (K4), 45a06cf (BIND); Python 1ba5730, 8316a10, 17a8172, 9569ff9, 70c904d, d89f2a8, 0f7f80e.

## Checklist (per task assignment)

- [x] 1. Selector-escaper char-for-char audit vs user_builders.py — CLEAN.
  Code diff: `user-builders.ts:192-198` (`formatValue`) and `:218-230` (`propRef`) are
  exact twins of `user_builders.py:39-42/:58-66` — `replaceAll("\\","\\\\")` FIRST then
  `replaceAll('"','\\"')`, both passes replace-all; non-strings via `pythonStrValue`
  (carrier→`pythonFloatStr`, else `pythonStr`), never `String()`. Guard helpers
  `isSelectorScalar`/`isSelectorNumber` accept boolean + PyFloat carrier exactly where
  Python's `isinstance(...(int,float))` accepts bool/float. Reviewer adversarial corpus
  (`/tmp/b3-fidelity-escaper-probe.py`): 352 both-bridge oracle comparisons over
  quotes/backslash compounds (`\`, `\\`, trailing `\`, `\"`×50, 500-char+`\`), NUL and
  NUL-adjacent controls, RTL/bidi (U+202E/U+200F, Arabic), non-BMP + emoji/variation
  selectors + ZWJ flags, combining marks (composed/decomposed/lone), BOM/ZWSP/NBSP,
  selector/operator-injection shapes, numeric adversaries (−0.0, 1e16, 1e-5, 5e-324,
  1.798e308, 1e21, bools, 2^53−1) in value/property/contains/joined positions —
  **0 divergences** (raw payload byte-diff, `ensure_ascii=False`). Lone surrogates are
  structurally untransportable (`UnencodableValueError` at `encode_input_kwargs` — rig
  policy, both sides symmetric; documented, not a gap in the port).
- [x] 2. R10.12 spot-audit — CLEAN. The three B3 `filterValue` emission sites
  (`builders.ts:611` `filterValue: f._value`; `:690` `filterValue: true` — JSON `true`;
  `:961` `filterValue: ff.value`) all pass natively; grep of `builders.ts` for
  `String(`/`pythonStr(`/`toString`: zero code hits near a filterValue assignment
  (only comments + one out-of-contract message-text `String(x)` at `:813` operating on
  a length, not a value). Matches Python `bookmark_builders.py:504/:579/:837` exactly.
- [x] 3. R10.11 boundary — CLEAN. The two sanctioned positions (`segfilter.py:187,189`)
  port as `operandStr` = `pythonStrValue` (carrier → `pythonFloatStr` spelling —
  strictly tighter than natural JS rendering, so the canonicalizer rescue is not even
  needed for carried values). `String(` appears in B3 files ONLY in error-message text,
  in `zfill(String(intField))` isoformat digit formatting (identical to Python f-string
  of int), and in the pathological `dictKeyText` branch (F3). No
  `.trim(`/`parseInt(`/single-occurrence `.replace(`-with-string-pattern anywhere in
  the six B3 source files (grep clean); the four escaping sites
  (`user-builders.ts:194,228`; `expressions.ts:68`) are all backslash-first
  `replaceAll` pairs. Canonicalizer NOT widened by B3: `git diff 794fea1..45a06cf --
  conformance-runner/src/canonical.ts …codecs.ts vector-codecs.ts` is EMPTY.
- [x] 4. Frequency-filter byte-compat — CLEAN. `buildFrequencyFilterEntry` vs
  `bookmark_builders.py:805-855`: identical key insertion order (behavior: event,
  aggregation, filterOperator, filterValue; dateRange only when BOTH halves non-null;
  eventFilters on `is not None` incl. empty list; outer resourceType, behaviorType,
  customProperty; conditional label last). Reviewer probe (`/tmp/b3-freq-byte.py`):
  direct-CPython `json.dumps` insertion-order bytes vs oracle-ts raw output — **8/8
  byte-identical**, including the probe-record clause (`FrequencyFilter("Query",
  operator="is at least", value=500000)` → the exact
  `context/phase1/addendum/frequency-filter-probe.md` shape), date-range, empty and
  1-element eventFilters, label, 5.0-carrier and 2.5 values. (NOTE for other
  reviewers: oracle-py's bridge sorts output keys at encode, so raw bridge-vs-bridge
  diffs show key-order noise — insertion order must be diffed against the Python
  library directly, as done here.) Probe-record citation comment present on the TS
  function; shape not "fixed"; the FF ctor guard makes half-set dateRange
  unconstructible on both sides (verified: Python raises at construction).
- [x] 5. Guard order + codes — CLEAN except F1 (line-by-line diff): K4 ES1 fires
  before operator dispatch (`user-builders.ts:287`), ES2-ES13 conditions and order
  match `user_builders.py:120-242` verbatim (Array.isArray / typeof-string /
  number+boolean+carrier per Caution #11); K2 BB1 dispatch order
  str→FrequencyBreakdown→GroupBy→CohortBreakdown→raise matches `:293-401`; BB2 before
  the per-filter loop, BB3 AFTER `build_filter_entry(f)` succeeded (earlier raises
  win), BB4-loop before BB5-length, BB6→BB7→BB8 with `isPythonDict`/`Object.hasOwn` at
  exactly the watchlist-#13/#7 sites; K3 SG1-SG4 positions and setness/range branch
  order match `segfilter.py:130-323`; `_convert_date_format` arity → ValueError twin
  (watchlist #1); datetime range non-str element → AttributeError twin; K1 owns no
  coded raises (codes flow through the B2 `_DEFAULT_CODE_MAP`, exercised by the K1
  probe-transcript replay). Vector re-verification: reviewer replay of all five B3
  prefixes = **299/299 PASS, 0 FAIL** (134+51+82+30+2, corpus @ 70c904dc598d).
- [x] 6. transforms UUID/clock determinism + fromtimestamp fidelity — VERIFIED with one
  disclosed-band finding. Reviewer probe (`/tmp/b3-fidelity-transforms-probe.py`): 54
  both-bridge comparisons over µs round-half-even ties (0.5e-6/1.5e-6/2.5e-6/3.5e-6 ±),
  carry cases (0.9999995, −0.9999995, 86399.999999499), datetime.max/min boundary
  (253402300799/.4/253402300800, −62135596800/−1/−.5), bool timestamps, `time: "0"` /
  `None` TypeErrors, dict-from-pairs properties, uuid-fill via `context.shims.uuid`,
  non-BMP keys — 53/54 agree byte-exactly. The single divergence: `time = 2^62` →
  CPython `OSError` vs TS `ValueError` — inside the deviation ALREADY DISCLOSED at
  `transforms.ts:307-313` (TODO(port), B3-K3 notes domain exclusion), BUT the band is
  much wider than the note's "narrow band" phrasing: measured boundary (this platform)
  is |t| ≥ 67,768,036,191,676,800 (~6.78e16, tm_year > INT_MAX) up to 2^63 — see
  finding F2. Everything succeeds/raises identically elsewhere; no clock read exists in
  `transform_event` (input-driven only); uuid seam threads `options.uuid` with
  `crypto.randomUUID()` default (`transforms.ts:60-68,421-441`) — twin of
  `clock.py:30` template confirmed via the shims counter agreeing across bridges.
- [x] 7. R10.9 harness re-runs from RUN records — ALL FOUR REPRODUCE:
  - K4 seed 7 (doubled budget): outcome tally + per-api counts byte-match RUN.md
    (3,531 compared / 0 divergences; all 13 ES codes fire; exit 0).
  - K2 seed 4242: 7,250 compared / 0 divergences / 21 construction skips = RUN.md row.
  - K3 seed 7: 2,594 compared / 0 divergences = RUN.md row.
  - K1 seed 4242: probe-transcript replay 389 compared / 1 divergence (exactly the
    DISCLOSED K1-D1 order flip) + fuzz 3,000 / 0 div / 0 int-like-extra skips = RUN.md.

## Findings

### F1 (MAJOR, CONFIRMED) — `buildCohortGroupEntry` misclassifies a boolean saved-cohort id: Python emits `id: true`, TS crashes TypeError

- **Site**: `packages/core/src/bookmarks/builders.ts` `buildCohortGroupEntry` —
  `isPyInt(cb.cohort)` vs Python `isinstance(cb.cohort, int)`
  (`bookmark_builders.py:443`).
- **Mechanism**: Python `bool` IS `int`, and `CohortBreakdown(True)` is CONSTRUCTIBLE on
  both sides (CB1 is `isinstance(cohort, int) and cohort <= 0` — `True <= 0` is False, so
  no raise; `_validate_cohort_args`, `types.py:9148`). Python then takes the saved-id
  branch (`base_cohort["id"] = True; base_cohort["groups"] = []`). TS `isPyInt` explicitly
  EXCLUDES booleans (`types/query-params/guards.ts:63-68` — `typeof value === "number"`),
  so `true` falls to the inline-cohort branch and `cb.cohort.toDict()` crashes with a bare
  `TypeError` (`true.toDict is not a function`).
- **In-annotation**: YES — `cohort: int | CohortDefinition` and `bool <: int` (ratified
  Discrepancy #8; b3-packets Caution #11 states verbatim "The TS twins accept
  `typeof 'boolean'` wherever Python accepts int … direction flips per site; read each
  guard"). This is the flipped-direction twin of B2 arbiter finding F3 (CM5).
- **Oracle-confirmed** (`/tmp/b3-bool-cohort-probe.py`, both bridges):
  `build_group_section(CohortBreakdown(True, "N"))` →
  py `{"ok": true, "output": [{"cohorts": [{"…", "id": true, "groups": [], …}]…}]}`;
  ts `{"ok": false, "error": {"class": "TypeError"}}`. Same divergence with
  `include_negated=False`. The K2 R10.9 fuzz missed it because the drawn
  `CohortBreakdown` domain never put a boolean in the `cohort` position.
- **Suggested fix (module layer)**: the saved-vs-inline split must accept booleans as
  ints exactly where Python does — e.g. `isPyInt(cb.cohort) || typeof cb.cohort ===
  "boolean"` or an `isinstance(x, int)`-faithful helper (contrast `isPythonInt` in
  `validation-shared.ts`, which deliberately EXCLUDES bool for the B2 direction — do not
  reuse it blindly; this site needs the bool-INCLUSIVE reading). Also sweep the TS
  `CohortBreakdown`/`CohortMetric`/`Filter.in_cohort` ctor guards (Phase-2 files) for the
  same `cohort <= 0` reading with boolean ids — `CohortBreakdown(false)`:
  Python `False <= 0` → CB1 raise; verify the TS guard fires CB1 for `false` too.
- **Fuzz-domain remediation**: extend the K2 `build_group_section` strategy (and the
  cohort-bearing K4/K2 Filter domains where `int` positions exist) with boolean draws at
  every `int`-annotated position, per Caution #11.

### F2 (MINOR, CONFIRMED) — the disclosed `fromtimestamp` OSError→ValueError deviation is far wider than its disclosure states; promote to the discrepancy log

- **Site**: `packages/core/src/query/transforms.ts:307-313` (TODO(port) comment) +
  B3-K3 notes domain-notes entry.
- **What the disclosure says**: "CPython additionally raises `OSError` (errno 84) in a
  narrow band of very large in-int64 magnitudes … (probe: 9.2e18 -> OSError, 1e16 ->
  ValueError)".
- **Measured** (reviewer bisect, `/tmp/b3-ostime-bisect.py`, CPython on this platform):
  the OSError region is |t| ≥ **67,768,036,191,676,800** (~6.78e16 — the `gmtime`
  tm_year > INT_MAX overflow, year ≈ 2,147,485,547) up to the 2^63 OverflowError bound;
  negative twin at −67,768,040,609,740,801. That is virtually the ENTIRE span above
  datetime.max (2.53e11 … 6.78e16 is ValueError on both sides; 6.78e16 … 9.22e18 —
  five orders of magnitude — is OSError-vs-ValueError class divergence). Reviewer
  both-bridge probe confirms: `time = 2^62` → py `OSError` / ts `ValueError`.
- **Why still minor**: every affected input RAISES on both sides (no wrong success);
  the values are unreachable from any real Mixpanel export (year > 2.1 billion); the
  fuzz-domain exclusion is documented and the packet explicitly authorizes excluding
  |t| beyond datetime.max; the boundary is PLATFORM-dependent (macOS gmtime), so
  chasing it byte-exactly would pin platform trivia.
- **Asks**: (1) correct the TODO(port) comment and the K3 domain note ("narrow band"
  → the measured boundary + platform-dependence caveat); (2) arbiter files this as a
  numbered playbook Discrepancy (it is a permanent class-level sanctioned deviation of
  exactly the Discrepancy #6/#7 kind, currently living only in a code comment).

### F3 (MINOR/NIT, CONFIRMED by inspection) — `dictKeyText` integral-float-carrier keys violate the branch's own stated JSON-spelling policy

- **Site**: `packages/core/src/query/transforms.ts:146-157`.
- The TODO(port) states non-string dict-from-pairs keys use "the JSON spelling (what
  any downstream encoder emits for the Python twin — `json.dumps({True: 1})` is
  `{"true": 1}`)". For a PyFloat carrier of `18.0`, `String(floatCarrierValue(key))`
  yields `"18"`, but `json.dumps({18.0: 1})` spells `"18.0"` — the one case where the
  policy and the code disagree. Only reachable through the pathological
  `dict(iterable-of-pairs)` branch with a float key (no Mixpanel response can produce
  it; the fuzz domain excludes it, disclosed). Fix is one line
  (`pythonFloatStr(floatCarrierValue(key))`) or extend the disclosure to name the
  carrier-key case.

## Open arbiter item (not a new finding — disclosed by K1, needs a ruling)

- **K1-D1** (`throwaway/b3-k1/RUN.md` §6): `extra_forbidden` emission ORDER flips for
  integer-like unknown keys on `extra="forbid"` models (JS integer-key reordering at
  decode). Same mechanism as ratified Discrepancy #9 but a DIFFERENT site, and Caution
  #17 forbids silently extending #9 — the K1 task correctly escalated instead of
  absorbing. Reviewer confirms the mechanism claim (loss occurs at `JSON.parse` /
  object construction, content identical, order-only) and confirms the fuzz exclusion
  counter (`has_int_like_extra` = 0 skips) reproduces. The arbiter must either extend
  the order-insensitive comparison to this warning family (mirroring #9's scope
  discipline — needs a user ratification per the #9 precedent) or record it as a
  standing disclosed divergence before the gate's differential regression can draw it.

## Binding-honesty (fidelity aspects; the assertions lens owns the full check)

`registerBuilderBindings` (`bindings.ts:1318-1489`): all 17 names call the real ported
entry points; kwargs pass through UNDECORATED (no PyFloat unwraps in any binding);
absent-stays-absent for `data_group_id` / `path_prefix`; `build_time_section` ←
`context.shims.today()`, `transform_event` ← `context.shims.uuid()`;
`event_time` wrapped as `PyDatetime` (encode twin of `codecs.py:227-228`); selector
strings returned VERBATIM; `validate_with_pydantic` TS adapter mirrors
`conformance/record/adapters.py:153-198` (same five names, unknown → ValueError).
One nit: for a NON-STRING `model` the Python adapter reaches its ValueError
(`model not in models` accepts any hashable) while the TS twin throws TypeError first
— rig-internal, unreachable by the strategies (they draw mapped names only), zero
library impact.

## Evidence log

- Reviewer probes (throwaway, /tmp — not committed):
  `/tmp/b3-fidelity-escaper-probe.py` (352 both-bridge comparisons, 0 div),
  `/tmp/b3-fidelity-surrogate-probe.py` (lone surrogates — symmetric
  `UnencodableValueError`, rig policy), `/tmp/b3-fidelity-transforms-probe.py`
  (54 comparisons, 1 div = F2 band), `/tmp/b3-ostime-bisect.py` (F2 boundary),
  `/tmp/b3-fidelity-freq-probe.py` + `/tmp/b3-freq-byte.py` (frequency-filter
  byte-compat, 8/8 insertion-order-exact), `/tmp/b3-bool-cohort-probe.py` (F1).
- Harness re-runs: `throwaway/b3-k4/run.sh 7 1100`, `b3-k2/run.sh 4242 600`,
  `b3-k3/run.sh 7 600`, `b3-k1/run.sh 4242 600` — all reproduce their RUN records.
- Vector replay: `npm run conformance -- --filter <prefix>` × 5 → 299/299 PASS.
- Sources diffed line-by-line: `user_builders.py` ↔ `user-builders.ts`;
  `segfilter.py` ↔ `segfilter.ts`; `expressions.py` ↔ `expressions.ts`;
  `transforms.py` ↔ `transforms.ts`; `bookmark_builders.py` ↔ `bookmarks/builders.ts`;
  `bookmark_schema.py:333-379` ↔ `bookmarks/schema.ts` dispatch/maps (spot);
  `adapters.py` ↔ bindings adapter.

## Verdict (fidelity lens)

**NO-GO until F1 is fixed** (major, in-annotation, oracle-confirmed divergence —
crash vs valid output in `buildCohortGroupEntry`), plus the K1-D1 arbiter ruling must
land before the gate's differential regression. F2/F3 are minor docs/nit fixes that
can ride the same resolution commit. Everything else on this lens — the watchlist-#2
escaper, R10.12, R10.11 boundary, frequency-filter byte-compat, guard order/codes,
transforms determinism, all four RUN records, 299/299 vectors — is clean and
verified by re-execution, not by reading alone.
