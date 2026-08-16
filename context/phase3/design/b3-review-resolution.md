# B3 arbiter resolution (P3-2d) — review pair `b3-review-fidelity.md` × `b3-review-assertions.md`

**Status**: COMPLETE · 2026-08-15 · Arbiter (fable tier, strongest-tier pair per P3-7)
**Inputs**: fidelity review (NO-GO: F1 major + F2/F3 minor + K1-D1 open item, commit
`8e72163`) · assertions review (GO-with-items: K1-D1 major-open + 3 minors, commit
`769eb04`). Reviews overlap on two findings (fidelity-F3 ≡ assertions-F2 dictKeyText;
K1-D1 raised by both); six distinct findings total. Every verdict below was
re-verified against source/probes by the arbiter before ruling — nothing accepted on
reviewer authority alone.

**Outcome: ALL SIX FINDINGS CONFIRMED AND APPLIED (fixes red-first; no assertion
weakened; no comparison logic relaxed). Post-fix verdict: GO for the B3 gate.**

---

## Findings ledger

| # | Finding (reviewer) | Verdict | Disposition |
|---|---|---|---|
| F1 | `buildCohortGroupEntry` bool cohort id: py `id: true` vs ts TypeError crash (fidelity F1, MAJOR) | **CONFIRMED** (arbiter re-ran the both-bridge probe: 2/2 divergences pre-fix, 0 post-fix) | FIXED red-first + ctor-guard sweep + fuzz-domain extension (§F1) |
| F2 | K1-D1 `extra_forbidden` order flip needs a ruling before the gate (both reviewers; assertions F1 MAJOR) | **CONFIRMED** as requiring a ruling | RULED: playbook **Discrepancy #10** — standing disclosed divergence; exclusion codified at the strategy site (§K1-D1) |
| F3 | fromtimestamp OSError disclosure understates the band (fidelity F2, minor) | **CONFIRMED** (arbiter re-ran the bisect: boundary 67,768,036,191,676,800 / −67,768,040,609,740,801 reproduces) | Comment + notes corrected; promoted to playbook **Discrepancy #11** (§F3) |
| F4 | `dictKeyText` float(-carrier) keys violate the stated json.dumps spelling policy (fidelity F3 ≡ assertions F2, minor) | **CONFIRMED** (red test: pre-fix rendered `"18"`/`"10000000000000000"`/`"0"` for `18.0`/`1e16`/`-0.0`) | FIXED red-first via `pythonFloatStr` (§F4) |
| F5 | K1-D1 fuzz exclusion undocumented at the strategy site (assertions F3, minor) | **CONFIRMED** (no comment at `_b3_schema_calls` choice 2; B2 precedent has one at `strategies.py:2591`) | FIXED — comment citing Discrepancy #10 added (§K1-D1) |
| F6 | `B3-K3-notes.md` §5 item 1 stale (assertions F4, minor) | **CONFIRMED** (§5.1 contradicted the shipped branch-for-branch `pythonDictCopy` and the same file's probe matrix) | FIXED — §5.1 rewritten to the post-BIND state (§F4 note) |

Nothing was REJECTED. No reviewer split existed (the two lenses agreed wherever they
overlapped); the arbiter's job reduced to verification, the K1-D1 ruling, and fixes.

---

## F1 — bool <: int in the cohort saved-vs-inline path (MAJOR, fixed)

**Verified.** Python `_validate_cohort_args` (`types.py:9148`) and the two
`isinstance(cohort, int)` splits (`bookmark_builders.py:443`,
`types.py:7765`) are bool-INCLUSIVE; TS `isPyInt` (`guards.ts`) is
bool-EXCLUSIVE. Arbiter truth table from live CPython:
`CohortBreakdown(False)`/`CohortMetric(False)`/`Filter.in_cohort(False)` →
CB1/CM1/CF1; `True` constructs everywhere; `Filter.in_cohort(True)._value` →
`[{"cohort": {"negated": false, "name": "", "id": true}}]`;
`build_group_section(CohortBreakdown(True, "N"))` → saved entry `id: true,
groups: []`. Both-bridge probe (`/tmp/b3-bool-cohort-probe.py`) re-run:
**2/2 divergences pre-fix (ts bare TypeError), 0/2 post-fix.** In-annotation
per ratified Discrepancy #8; flipped-direction twin of B2 arbiter F3 (CM5),
exactly as the fidelity review framed it.

**Fix (TS, red-first).** New red lock file
`packages/core/test/bookmarks/cohort-bool-fidelity.test.ts` (9 tests,
oracle-py reference outputs incl. a byte-exact `JSON.stringify` insertion-order
assert) — **7/9 red pre-fix** (the 2 passing were the already-correct
`True`-constructs cases), 9/9 green post-fix. Changes:

- `types/query-params/guards.ts`: new bool-INCLUSIVE `isinstance(int)` helper
  **`isPyIntOrBool`** (documented contrast with bool-EXCLUSIVE `isPyInt` and
  B2's `isPythonInt` — direction flips per site, Caution #11; the
  validation-shared helper was NOT reused, per the fidelity review's warning).
- `validateCohortArgs` CB1/CM1/CF1 guard: `(isPyInt(cohort) && cohort <= 0) ||
  cohort === false` — the exact boolean residue of Python's
  `isinstance(cohort, int) and cohort <= 0` (`False <= 0` fires, `True <= 0`
  passes).
- `bookmarks/builders.ts:551` and `types/query-params/filter.ts:807`
  (`buildCohortFilter`): split now `isPyIntOrBool(...)` — booleans take the
  SAVED branch on both sites.
- **Ctor sweep result** (fidelity's ask): `CohortMetric` needed only the shared
  guard fix (its CM5 check is already `instanceof CohortDefinition`, bool-safe,
  from B2 arbiter F3); `metric.ts`/`user-validators.ts`/`validation-args.ts`
  `instanceof CohortDefinition` sites verified bool-safe unchanged.

**Fuzz-domain remediation** (Caution #11): Python rig
`conformance/differential/strategies.py` — `st.booleans()` added to the
`filter_family` `in_cohort`/`not_in_cohort` cohort draw and to the
`cohort_family` `types.CohortBreakdown` cohort draw; `st.just(True)` added to
the K2 `_bb_group_element` cohort draw (`False` is unconstructible — fires CB1
at draw time); new edge calls `Filter.in_cohort(True)`,
`Filter.not_in_cohort(False, "VIPs")`, and
`build_group_section(CohortBreakdown(True, "N"))`. K2 throwaway harness
`gen-cases.py` cohort choice gains `True`.

**Post-fix evidence:**
- Both-bridge fuzz, seed **84150301**, 9 families (`filter_family`,
  `cohort_family`, `metric_group_family`, `build_group_section_family`,
  `build_filter_entry`, `build_flow_cohort_filter_family`,
  `bookmark_schema_family`, `transform_event_family`,
  `transform_profile_family`): **4,744 examples / 0 divergences / 0 skips**.
- K2 throwaway harness re-run, seed 4242 at the reviewers' budget with the
  extended domain: **7,250 compared / 0 divergences / 21 construction skips**
  (same counts as the RUN record), with **32 boolean-cohort cases drawn**
  (pre-fix domain drew zero — confirming the fidelity review's gap analysis).
- Full conformance report unchanged by the fixes (all 299 B3 vectors keep
  passing; see §Post-fix verification).

---

## K1-D1 ruling (arbiter item raised by both reviewers) → Discrepancy #10

**Verified.** The K1 escalation record (`B3-K1-notes.md` §6,
`throwaway/b3-k1/RUN.md` §6) is accurate: mixed integer-like/non-integer-like
UNKNOWN keys on an `extra="forbid"` model emit `extra_forbidden` in JS object
order (content identical, order only); the loss happens at
`JSON.parse`/object-construction time — the same engine limitation as ratified
Discrepancy #9 at a NEW site. K1 correctly escalated instead of self-extending
#9 (Caution #17). Both reviewers reproduced the disclosed divergence and the
`has_int_like_extra = 0` exclusion counter from the recorded seeds.

**Ruling: standing disclosed divergence — playbook Discrepancy #10** (full
entry in `phase3-playbook.md` §P3-8). Rationale for choosing disclosure over
comparison-extension: (i) extending #9's order-insensitive comparison to a new
warning family would, per the #9 precedent, require a user ratification the
arbiter cannot grant; (ii) the exclusion approach requires NO comparison-logic
change and leaves content equality fully strict; (iii) reachability is nil at
this batch (zero `bookmark_schema.*` corpus vectors) and speculative at B6-W3.
The gate is therefore NOT blocked on a user round-trip. **HUMAN-CALL
(optional, non-blocking)**: the user may instead ratify a #9-style
order-insensitive comparison scoped to `extra_forbidden`-on-integer-like-keys,
which would let the fuzz domain re-include such inputs; until then the
documented exclusion stands.

**Applied**: exclusion codified at the strategy site
(`strategies.py::_b3_schema_calls` choice-2 comment citing Discrepancy #10 —
the B2 `strategies.py:2591` pattern; resolves assertions F3);
`B3-K1-notes.md` §6 marked RESOLVED with the ruling; the `throwaway/b3-k1`
RUN.md is left untouched (the gate deletes `throwaway/`; the durable record is
the playbook entry + K1 notes + this file).

---

## F3 — fromtimestamp OSError band disclosure (minor, fixed + promoted)

**Verified by re-execution**: the arbiter re-ran the reviewer's bisect —
first OSError at exactly **67,768,036,191,676,800**, negative twin at
**−67,768,040,609,740,801**, `2^62` → py OSError / ts ValueError as the sole
divergence in the re-run of the 54-case transforms probe (53/54 agree —
unchanged post-F4-fix). The original "narrow band" phrasing understated a
five-orders-of-magnitude region.

**Applied**: `transforms.ts` TODO(port) rewritten with the measured boundary +
platform-dependence caveat + Discrepancy pointer; `B3-K3-notes.md` §5.2
likewise; promoted to **playbook Discrepancy #11** (class-level sanctioned
deviation of the #6/#7 kind, per the fidelity review's ask — no longer living
only in a code comment). No code behavior change (the deviation itself remains
sanctioned: both sides raise; fuzz caps |t| ≤ 1e12).

---

## F4 — dictKeyText float(-carrier) key spelling (minor, fixed red-first)

**Verified.** Both reviewers' claims confirmed: the branch's own policy is the
json.dumps KEY spelling; CPython reference (arbiter probe):
`transform_event` with properties pairs `[(18.0,1),(1e16,2),(-0.0,3)]` keeps
float keys that json.dumps spells `"18.0"` / `"1e+16"` / `"-0.0"`; the pre-fix
`String()` rendered `"18"` / `"10000000000000000"` / `"0"`.

**Applied red-first**: two NEW tests in
`packages/core/test/query/transforms.test.ts` (CPython-reference,
`PyFloatStub` per the `validation-dict-fidelity.test.ts` precedent) — the
transformEvent case red pre-fix, green post-fix. Fix: carrier keys →
`pythonFloatStr(floatCarrierValue(key))`; plain FRACTIONAL numbers (direct-TS
pathological calls only) → `pythonFloatStr(key)`; integral numbers/bigints
keep `String()` (= json.dumps int spelling); bool/null keep the JSON spelling
(`pythonStr` would WRONGLY yield `"True"` — the assertions review's
parenthetical "non-float non-strings through pythonStr" was NOT adopted for
bools, with the spelling table now documented in the docblock). **Ruling
note**: this input class is rig-UNTRANSPORTABLE (oracle output encode refuses
non-string mapping keys — arbiter probe `/tmp/b3-arb-dictkey-probe.py`
confirmed `output encode failed`), so the Layer-3 CPython-reference lock is
the only possible lock; recorded in `B3-K3-notes.md` §5.1.

`B3-K3-notes.md` §5.1 rewritten (assertions F4 / arbiter F6): the stale
"TS raises TypeError for every non-dict" paragraph replaced with the
post-BIND branch-for-branch state + the two disclosed residues.

---

## Ripple check (beyond the findings)

- `isPyIntOrBool` introduced WITHOUT changing `isPyInt` — the B2 validators'
  bool-rejection direction is untouched (grep: no other `isPyInt` call sites
  remain; the three cohort sites all moved to the bool-inclusive reading,
  matching their Python twins' `isinstance(int)`).
- `Filter.inCohort(true)` transports: the Filter codec carries `_value` raw,
  so `build_filter_entry`/`filter_to_selector` consumers see `id: true`
  natively on both sides (covered by the new `filter_family` edge calls).
- The prettier/eslint/tsc surface: `npm run check` green post-fix.
- Vector surface: full conformance report byte-identical to the entering
  baseline (the fix is unreachable from the 299 recorded vectors — booleans
  never appear in recorded cohort positions — hence Layer-2 was silent and
  the R10.9/K2-fuzz gap was the real miss, now closed at the strategy layer).

- **R10.4 recurrence tally**: this is the SECOND bool-direction
  `isinstance(int)` finding of the port (1: B2 arbiter F3 — CM5 over-fired on
  `CohortMetric(cohort=True)`; 2: B3 F1 — the flipped-direction under-accept
  here). One more occurrence hits the ≥3 stop-amend-regenerate threshold; the
  next batch's reviewers should treat every new `isinstance(x, int)` port site
  as a mandatory checklist item (Caution #11 already says so — a rulebook
  amendment would add the `isPyIntOrBool`-vs-`isPyInt`-vs-`isPythonInt`
  selection table).

## Post-fix verification matrix

| Check | Result |
|---|---|
| F1 lock file (9 tests, oracle-py references) | 7/9 red pre-fix → 9/9 green |
| F4 lock tests (2 NEW in transforms.test.ts) | 1 red pre-fix → green |
| Both-bridge F1 probe | 2/2 div pre-fix → **0** post-fix |
| 54-case transforms probe | 53/54 (sole div = Discrepancy #11 band, disclosed) |
| Fuzz: 9 touched families, seed 84150301, 500/family | **4,744 ex / 0 div / 0 skips** |
| K2 throwaway harness, seed 4242, extended domain | **7,250 / 0 div / 21 ctor-skips**, 32 bool-cohort draws |
| Affected vitest suites (19 files) | 658/658 green |
| `npm run check` (TS) | green (exit 0) |
| `npm run conformance` | 3,251 vectors — **1,528 PASS / 0 FAIL / 1,723 UNPORTED** @ corpus 70c904dc598d (the post-BIND state: 1,229 + the 299 B3 vectors already replaying while `pending` per P3-5 §5 — exactly Caution #16's gate arithmetic; unchanged by the fixes) |
| `just check` (Python — strategies.py touched) | green |

## Verdict and handoff to the B3 gate

**GO.** Fidelity's NO-GO conditions are both discharged: F1 fixed and
oracle-confirmed; K1-D1 ruled (Discrepancy #10) with the exclusion codified
before the gate's differential regression. The gate task should additionally:
(1) include the six B3 prefixes' flip per P3-5 with the Discrepancy #2 comment
correction; (2) run the full-suite differential regression with fresh seeds —
the `_b3_schema_calls` exclusion is now load-bearing and documented; (3) keep
the B5-S2 pickup obligation for the three deferred PBT classes
(assertions §2a) on the B5 packet author's list; (4) delete `throwaway/` per
protocol (RUN records survive in the notes files).

**HUMAN-CALLS (non-blocking)**: (1) optional ratification of an
order-insensitive comparison for the Discrepancy #10 family (see §K1-D1);
(2) FYI — Discrepancies #10/#11 were recorded by arbiter authority following
the #6/#7 precedent (arbiter blessings); if the user prefers #8/#9-style
explicit ratification for #10/#11 as well, `user-ratifications.md` is the
place to add it.

## Commits

- TS repo (`main`): the arbiter fix commit accompanying this file (F1 + F4
  code fixes, red-first locks, F3 comment, K2 harness domain).
- Python repo (`ts-port/phase2-contract-support`): this file + playbook
  Discrepancies #10/#11 + strategies.py domain extensions/comments + K1/K3
  notes corrections.
